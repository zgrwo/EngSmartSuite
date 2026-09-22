"""前向模型与速率模型：候选构建、交叉验证与拟合（原 inverse.py，2026-09-21 拆分）。"""

import logging
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from smartsuite.engine._constants import (
    INVERSE_AUTO_CANDIDATE_MAX_ROWS,
    INVERSE_CV_LOO_MAX_ROWS,
    INVERSE_GPR_MAX_ROWS,
    INVERSE_POLY_MAX_TERMS,
    INVERSE_RATE_MIN_ROWS,
    INVERSE_RATE_RIDGE_ALPHA_MAX,
    INVERSE_RATE_RIDGE_ALPHA_MIN,
    INVERSE_RATE_RIDGE_ALPHA_N,
)
from smartsuite.engine._utils import round_for_display

logger = logging.getLogger(__name__)


MODEL_KINDS = ("linear", "poly", "gpr", "gbm")


def _build_candidate(kind: str, random_state: int):
    if kind == "linear":
        return make_pipeline(StandardScaler(), LinearRegression())
    if kind == "poly":
        return make_pipeline(
            PolynomialFeatures(2, include_bias=False),
            StandardScaler(),
            RidgeCV(alphas=np.logspace(-3, 3, 13)),
        )
    if kind == "gpr":
        kernel = ConstantKernel(1.0, (1e-2, 1e3)) * Matern(
            length_scale=3.0, length_scale_bounds=(0.5, 50.0), nu=1.5
        ) + WhiteKernel(noise_level=0.05, noise_level_bounds=(1e-4, 1.0))
        return make_pipeline(
            StandardScaler(),
            GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=random_state),
        )
    if kind == "gbm":
        return GradientBoostingRegressor(
            n_estimators=300, max_depth=2, learning_rate=0.05, random_state=random_state
        )
    raise ValueError(f"未知模型: {kind}")


def _fast_predictor(model):
    """构造与 StandardScaler+（线性/Ridge/多项式）pipeline 等价的快速预测函数。

    求解器目标函数按单行调用 predict 数千次，sklearn pipeline 的逐次输入校验
    是主要开销（实测 33 行 × 11 请求约 115s 花在校验）；可解析结构改为纯 numpy
    等价式计算（差异 ~1e-15）。不可解析（GPR/GBM 等）返回 None，走原 pipeline。
    """
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None
    scaler = steps.get("standardscaler")
    if scaler is None:
        return None
    mean = np.ravel(np.asarray(scaler.mean_, dtype=float))
    scale = np.ravel(np.asarray(scaler.scale_, dtype=float))
    if "linearregression" in steps:
        reg = steps["linearregression"]
        coef = np.ravel(np.asarray(reg.coef_, dtype=float))
        intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
        raw_coef = coef / scale
        raw_intercept = intercept - float(np.sum(coef * mean / scale))
        return lambda x: x @ raw_coef + raw_intercept
    if "polynomialfeatures" in steps and "ridgecv" in steps:
        poly = steps["polynomialfeatures"]
        reg = steps["ridgecv"]
        coef = np.ravel(np.asarray(reg.coef_, dtype=float))
        intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
        weights = coef / scale
        raw_intercept = intercept - float(np.sum(coef * mean / scale))
        powers = np.asarray(poly.powers_, dtype=int)

        def _poly_predict(x: np.ndarray) -> float:
            basis = np.prod(np.power(x, powers), axis=1)
            return float(basis @ weights + raw_intercept)

        return _poly_predict
    if "ridgecv" in steps:
        # 速率模型：StandardScaler + RidgeCV
        reg = steps["ridgecv"]
        coef = np.ravel(np.asarray(reg.coef_, dtype=float))
        intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
        raw_coef = coef / scale
        raw_intercept = intercept - float(np.sum(coef * mean / scale))
        return lambda x: x @ raw_coef + raw_intercept
    return None


@dataclass
class ForwardModel:
    feature_cols: list[str]
    models: list
    choice: list[str]
    note: str | None = None
    fast: list | None = None

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.column_stack([m.predict(x[self.feature_cols]) for m in self.models])

    @property
    def has_tree(self) -> bool:
        return "gbm" in self.choice


def _cv_split(n_rows: int, random_state: int, kind: str):
    """候选筛选交叉验证方案（R-1：控制拟合次数，防候选门控成本爆炸）。

    GPR/GBM 恒用 5 折（LOO 会把拟合次数放大 n 倍；GPR 单次成本 O(n³)，GBM
    单次拟合亦随 n 增长，n≈500 时 LOO 已达分钟级悬崖，审查 2026-09-13 N-1）；
    其余候选在 n ≤ INVERSE_CV_LOO_MAX_ROWS 时用精确 LOO，超过改用 5 折。
    返回 (splitter, 标签)。
    """
    if kind in ("gpr", "gbm") or n_rows > INVERSE_CV_LOO_MAX_ROWS:
        splits = max(2, min(5, int(n_rows)))
        return KFold(n_splits=splits, shuffle=True, random_state=random_state), "5折"
    return LeaveOneOut(), "LOO"


def _auto_candidates(n_rows: int, feature_count: int) -> tuple[tuple[str, ...], list[str]]:
    """auto 候选与规模削减说明（R-1）。显式模型不受候选削减影响。"""
    candidates: tuple[str, ...] = MODEL_KINDS
    notes: list[str] = []
    if n_rows >= INVERSE_AUTO_CANDIDATE_MAX_ROWS:
        skipped = [kind for kind in candidates if kind in ("gpr", "gbm")]
        candidates = tuple(kind for kind in candidates if kind in ("linear", "poly"))
        notes.append(
            f"历史 n={n_rows} 达到 {INVERSE_AUTO_CANDIDATE_MAX_ROWS}，"
            f"auto 已跳过候选：{'、'.join(skipped)}"
        )
    poly_terms = feature_count * (feature_count + 3) // 2
    if "poly" in candidates and poly_terms > INVERSE_POLY_MAX_TERMS:
        candidates = tuple(kind for kind in candidates if kind != "poly")
        notes.append(
            f"poly 展开列数 {poly_terms} 超过 {INVERSE_POLY_MAX_TERMS}，auto 已跳过候选：poly"
        )
    return candidates, notes


def _fit_forward(history, roles, model="auto", random_state=42):
    feature_cols = [
        c
        for c in roles.incoming + roles.variable + roles.fixed
        if history[c].nunique(dropna=True) > 1
    ]
    dropped = [c for c in roles.incoming + roles.variable + roles.fixed if c not in feature_cols]
    X = history[feature_cols]
    quality_rows = []
    models, choices = [], []
    n_rows = len(history)
    if model == "gpr" and n_rows > INVERSE_GPR_MAX_ROWS:
        raise ValueError(
            f"高斯过程 GPR 仅支持历史 n ≤ {INVERSE_GPR_MAX_ROWS}（当前 {n_rows}），"
            "请选择 linear/poly/gbm/rate 或减少数据量"
        )
    if model == "auto":
        candidates, auto_notes = _auto_candidates(n_rows, len(feature_cols))
    else:
        candidates, auto_notes = (model,), []
    for out_col in roles.output:
        y = history[out_col].to_numpy(float)
        best_kind, best_r2, best_model = None, -np.inf, None
        if len(feature_cols) == 0:
            raise ValueError("所有候选特征列均为常量，无法建模")
        for kind in candidates:
            cv, cv_label = _cv_split(n_rows, random_state, kind)
            est = _build_candidate(kind, random_state)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                pred = cross_val_predict(est, X, y, cv=cv)
            r2 = r2_score(y, pred)
            quality_rows.append(
                {
                    "Output": out_col,
                    "候选": kind,
                    "CV方案": cv_label,
                    "CV_R2": round_for_display(float(r2), 3),
                    "CV_MAE": round_for_display(float(mean_absolute_error(y, pred)), 4),
                    "选用": False,
                }
            )
            if r2 > best_r2:
                best_kind, best_r2, best_model = kind, r2, est
        assert best_model is not None and best_kind is not None  # 候选循环至少产出一个模型
        best_model.fit(X, y)
        models.append(best_model)
        choices.append(best_kind)
        for row in quality_rows:
            if row["Output"] == out_col and row["候选"] == best_kind:
                row["选用"] = True
    if dropped:
        logger.warning("常量列已从特征中剔除: %s", dropped)
    note = "；".join(auto_notes) if auto_notes else None
    if note:
        logger.warning(note)
    fast = [_fast_predictor(model_item) for model_item in models]
    return (
        ForwardModel(feature_cols, models, choices, note=note, fast=fast),
        pd.DataFrame(quality_rows),
    )


def _strip_role_prefix(name: str) -> str:
    lowered = name.lower()
    for prefix in ("incoming", "output", "target", "来料", "输出", "目标"):
        if lowered.startswith(prefix.lower()):
            return name[len(prefix) :]
    return name


def _pair_incoming_output(incoming, output) -> list[tuple[str, str]]:
    """按去前缀后的列名后缀配对来料与输出；无法配对时回退共用/顺序配对。"""
    incoming_cols = [str(c) for c in incoming]
    output_cols = [str(c) for c in output]
    pairs: list[tuple[str, str]] = []
    for out_col in output_cols:
        suffix = _strip_role_prefix(out_col)
        match = next((inc for inc in incoming_cols if _strip_role_prefix(inc) == suffix), None)
        if match is None:
            pairs = []
            break
        pairs.append((match, out_col))
    if pairs or not output_cols:
        return pairs
    if len(incoming_cols) == 1:
        return [(incoming_cols[0], out_col) for out_col in output_cols]
    return list(zip(incoming_cols, output_cols, strict=False))


def _rate_feature_value(col: str, incoming_row, u) -> float:
    for source in (u, incoming_row):
        if source is None or col not in source:
            continue
        value = source[col]
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"速率特征列「{col}」的取值不是数值: {value!r}") from None
        if not np.isfinite(number):
            raise ValueError(f"速率特征列「{col}」的取值无效（NaN/Inf），请检查输入")
        return number
    raise ValueError(f"速率特征缺少列「{col}」的取值")


@dataclass
class RateForwardModel:
    incoming_cols: list[str]
    rate_feature_cols: list[list[str]]
    models: list
    feature_choice: list[str]
    uses_time: bool = True
    random_state: int = 42
    pairing_note: str | None = None
    time_col: str | None = None
    fast_rate: list | None = None

    @property
    def has_tree(self) -> bool:
        return False

    def predict_rate(self, incoming_row: dict, u: dict) -> np.ndarray:
        rates = []
        for index, (cols, model) in enumerate(
            zip(self.rate_feature_cols, self.models, strict=True)
        ):
            values = {col: _rate_feature_value(col, incoming_row, u) for col in cols}
            fast = self.fast_rate[index] if self.fast_rate else None
            if fast is not None:
                features = np.asarray([[values[col] for col in cols]], dtype=float)
                rates.append(float(np.ravel(fast(features))[0]))
            else:
                features = pd.DataFrame([values], columns=cols)
                rates.append(float(np.ravel(model.predict(features))[0]))
        return np.asarray(rates, dtype=float)

    def predict_output(self, incoming_row: dict, u: dict, time: float) -> np.ndarray:
        offsets = np.asarray(
            [_rate_feature_value(col, incoming_row, u) for col in self.incoming_cols], dtype=float
        )
        return offsets - self.predict_rate(incoming_row, u) * float(time)


def _fit_rate_forward(history, roles, time_col, random_state=42):
    """速率物理先验模型：Y_j = Inc_j - r_j(z)·t，r_j 用 StandardScaler + RidgeCV。

    速率特征二选一（逐输出按 LOO R² 选优）：params = fixed + variable；
    all = incoming + fixed + variable。time_col 不参与速率特征（防止速率依赖预报时间）。
    """
    if not time_col or time_col not in history.columns:
        raise ValueError("rate 模型需要有效的时间列 time_col")
    time_values = pd.to_numeric(history[time_col], errors="coerce")
    time_array = time_values.to_numpy(float)
    valid_time = np.isfinite(time_array) & (time_array != 0)
    if not valid_time.any():
        raise ValueError("rate 模型需要有效的时间列 time_col（非缺失且非零）")
    pairs = _pair_incoming_output(roles.incoming, roles.output)
    if len(pairs) < len(roles.output):
        raise ValueError("来料列少于输出列且无法配对，无法建立速率模型")
    pairing_note = None
    if not all(
        _strip_role_prefix(inc_col) == _strip_role_prefix(out_col) for inc_col, out_col in pairs
    ):
        mode = "共用" if len(roles.incoming) == 1 else "顺序"
        detail = "、".join(f"{inc_col}→{out_col}" for inc_col, out_col in pairs)
        pairing_note = f"来料与输出未能按后缀完全配对，已按{mode}方式配对：{detail}"
        logger.warning(pairing_note)
    params_cols = list(dict.fromkeys(c for c in roles.fixed + roles.variable if c != time_col))
    all_cols = list(
        dict.fromkeys(c for c in roles.incoming + roles.fixed + roles.variable if c != time_col)
    )
    union_cols = list(dict.fromkeys(params_cols + all_cols))
    candidates = [
        name_cols for name_cols in (("params", params_cols), ("all", all_cols)) if name_cols[1]
    ]
    if not candidates:
        raise ValueError("无可用速率特征列，无法建立速率模型")
    dropped_time = int((~valid_time).sum())
    if dropped_time:
        logger.warning("速率模型丢弃 %d 行缺少有效时间值的记录", dropped_time)
    train = history.loc[valid_time]
    train_time = time_values.loc[valid_time].to_numpy(float)
    finite_union = np.isfinite(train[union_cols].to_numpy(float)).all(axis=1)
    quality_rows = []
    models, feature_choice, rate_feature_cols = [], [], []
    cv, cv_label = _cv_split(len(train), random_state, "linear")
    for out_col, (inc_col, _) in zip(roles.output, pairs, strict=True):
        y = pd.to_numeric(train[out_col], errors="coerce").to_numpy(float)
        inc = pd.to_numeric(train[inc_col], errors="coerce").to_numpy(float)
        mask = np.isfinite(y) & np.isfinite(inc) & finite_union
        if mask.sum() < INVERSE_RATE_MIN_ROWS:
            raise ValueError(
                f"输出「{out_col}」的速率模型有效历史不足"
                f"（{int(mask.sum())} 行 < {INVERSE_RATE_MIN_ROWS} 行），"
                "请检查来料/输出/速率特征列的缺失值"
            )
        dropped = int(len(mask) - mask.sum())
        if dropped:
            logger.warning(
                "输出「%s」的速率模型剔除 %d 行含缺失/非有限特征的数据", out_col, dropped
            )
        rate = (inc[mask] - y[mask]) / train_time[mask]
        best_name, best_r2, best_model, best_cols = None, -np.inf, None, None
        for name, cols in candidates:
            X = train[cols][mask]
            est = make_pipeline(
                StandardScaler(),
                RidgeCV(
                    alphas=np.logspace(
                        np.log10(INVERSE_RATE_RIDGE_ALPHA_MIN),
                        np.log10(INVERSE_RATE_RIDGE_ALPHA_MAX),
                        INVERSE_RATE_RIDGE_ALPHA_N,
                    )
                ),
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                pred = cross_val_predict(est, X, rate, cv=cv)
            r2 = r2_score(rate, pred)
            quality_rows.append(
                {
                    "Output": out_col,
                    "候选": name,
                    "CV方案": cv_label,
                    "CV_R2": round_for_display(float(r2), 3),
                    "CV_MAE": round_for_display(float(mean_absolute_error(rate, pred)), 6),
                    "选用": False,
                }
            )
            if r2 > best_r2:
                best_name, best_r2, best_model, best_cols = name, r2, est, cols
        assert best_model is not None and best_name is not None and best_cols is not None
        best_model.fit(train[best_cols][mask], rate)
        models.append(best_model)
        feature_choice.append(best_name)
        rate_feature_cols.append(list(best_cols))
        for row in quality_rows:
            if row["Output"] == out_col and row["候选"] == best_name:
                row["选用"] = True
    return (
        RateForwardModel(
            incoming_cols=[pair[0] for pair in pairs],
            rate_feature_cols=rate_feature_cols,
            models=models,
            feature_choice=feature_choice,
            random_state=random_state,
            pairing_note=pairing_note,
            time_col=time_col,
            fast_rate=[_fast_predictor(model_item) for model_item in models],
        ),
        pd.DataFrame(quality_rows),
    )
