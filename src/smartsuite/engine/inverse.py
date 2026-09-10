"""工艺参数反解模块：列角色识别与历史行/请求行分类。"""

import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from smartsuite.engine._constants import (
    INVERSE_RATE_MIN_ROWS,
    INVERSE_RATE_RIDGE_ALPHA_MAX,
    INVERSE_RATE_RIDGE_ALPHA_MIN,
    INVERSE_RATE_RIDGE_ALPHA_N,
)

logger = logging.getLogger(__name__)

DEFAULT_PREFIXES = {
    "incoming": ("incoming", "来料"),
    "variable": ("variable", "变量", "可调"),
    "fixed": ("fixed", "固定"),
    "output": ("output", "输出"),
    "target": ("target", "目标"),
}

MODEL_KINDS = ("linear", "poly", "gpr", "gbm")


@dataclass
class RoleMap:
    incoming: list[str] = field(default_factory=list)
    variable: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    target: list[str] = field(default_factory=list)
    time: str | None = None


def _split_param_cols(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _match_by_prefix(columns, prefixes) -> list[str]:
    lowered = [(c, str(c).lower()) for c in columns]
    return [c for c, low in lowered if low.startswith(tuple(p.lower() for p in prefixes))]


def resolve_roles(df: pd.DataFrame, params: dict) -> RoleMap:
    roles = RoleMap()
    for role, prefixes in DEFAULT_PREFIXES.items():
        explicit = _split_param_cols(params.get(f"{role}_cols"))
        cols = explicit if explicit else _match_by_prefix(df.columns, prefixes)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"参数指定的{role}_cols列不存在: {missing}")
        setattr(roles, role, cols)
    time_col = str(params.get("time_col") or "").strip()
    if time_col and time_col not in df.columns:
        raise ValueError(f"参数指定的 time_col 列不存在: {time_col}")
    roles.time = time_col or None
    if not roles.output:
        raise ValueError(f"未识别到输出列（前缀 output/输出），可用列: {list(df.columns)[:10]}")
    if not roles.incoming and not roles.variable:
        raise ValueError("未识别到来料列与可调参数列，请通过 params 指定")
    for col in set(roles.incoming + roles.variable + roles.fixed + roles.output + roles.target):
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return roles


def split_rows(df: pd.DataFrame, roles: RoleMap):
    var_cols = roles.variable + (
        [roles.time] if roles.time and roles.time not in roles.variable else []
    )
    has_vars = df[var_cols].notna().all(axis=1) if var_cols else pd.Series(False, index=df.index)
    out_ok = df[roles.output].notna().all(axis=1)
    incoming_ok = (
        df[roles.incoming].notna().all(axis=1)
        if roles.incoming
        else pd.Series(True, index=df.index)
    )
    history = df[has_vars & out_ok]
    request = df[(~has_vars) & incoming_ok & out_ok]
    skipped = []
    for idx in df.index:
        if idx in history.index or idx in request.index:
            continue
        reasons = []
        if var_cols and not has_vars.loc[idx] and not out_ok.loc[idx]:
            reasons.append("缺少输出值")
        if not reasons:
            reasons.append("行类型无法判定（变量与输出组合不完整）")
        skipped.append((int(idx), "; ".join(reasons)))
    return history, request, skipped


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


@dataclass
class ForwardModel:
    feature_cols: list[str]
    models: list
    choice: list[str]

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.column_stack([m.predict(x[self.feature_cols]) for m in self.models])

    @property
    def has_tree(self) -> bool:
        return "gbm" in self.choice


def fit_forward(history, roles, model="auto", random_state=42):
    feature_cols = [
        c
        for c in roles.incoming + roles.variable + roles.fixed
        if history[c].nunique(dropna=True) > 1
    ]
    dropped = [c for c in roles.incoming + roles.variable + roles.fixed if c not in feature_cols]
    X = history[feature_cols]
    quality_rows = []
    models, choices = [], []
    for out_col in roles.output:
        y = history[out_col].to_numpy(float)
        candidates = MODEL_KINDS if model == "auto" else (model,)
        best_kind, best_r2, best_model = None, -np.inf, None
        if len(feature_cols) == 0:
            raise ValueError("所有候选特征列均为常量，无法建模")
        for kind in candidates:
            est = _build_candidate(kind, random_state)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                pred = cross_val_predict(est, X, y, cv=LeaveOneOut())
            r2 = r2_score(y, pred)
            quality_rows.append(
                {
                    "Output": out_col,
                    "候选": kind,
                    "LOO_R2": round(float(r2), 3),
                    "LOO_MAE": round(float(mean_absolute_error(y, pred)), 4),
                    "选用": False,
                }
            )
            if r2 > best_r2:
                best_kind, best_r2, best_model = kind, r2, est
        best_model.fit(X, y)
        models.append(best_model)
        choices.append(best_kind)
        for row in quality_rows:
            if row["Output"] == out_col and row["候选"] == best_kind:
                row["选用"] = True
    if dropped:
        logger.warning("常量列已从特征中剔除: %s", dropped)
    return ForwardModel(feature_cols, models, choices), pd.DataFrame(quality_rows)


def _strip_role_prefix(name: str) -> str:
    lowered = name.lower()
    for prefix in ("incoming", "output", "来料", "输出"):
        if lowered.startswith(prefix.lower()):
            return name[len(prefix) :]
    return name


def pair_incoming_output(incoming, output) -> list[tuple[str, str]]:
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

    @property
    def has_tree(self) -> bool:
        return False

    def predict_rate(self, incoming_row: dict, u: dict) -> np.ndarray:
        rates = []
        for cols, model in zip(self.rate_feature_cols, self.models, strict=True):
            values = {col: _rate_feature_value(col, incoming_row, u) for col in cols}
            features = pd.DataFrame([values], columns=cols)
            rates.append(float(np.ravel(model.predict(features))[0]))
        return np.asarray(rates, dtype=float)

    def predict_output(self, incoming_row: dict, u: dict, time: float) -> np.ndarray:
        offsets = np.asarray(
            [_rate_feature_value(col, incoming_row, u) for col in self.incoming_cols], dtype=float
        )
        return offsets - self.predict_rate(incoming_row, u) * float(time)


def fit_rate_forward(history, roles, time_col, random_state=42):
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
    pairs = pair_incoming_output(roles.incoming, roles.output)
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
                pred = cross_val_predict(est, X, rate, cv=LeaveOneOut())
            r2 = r2_score(rate, pred)
            quality_rows.append(
                {
                    "Output": out_col,
                    "候选": name,
                    "LOO_R2": round(float(r2), 3),
                    "LOO_MAE": round(float(mean_absolute_error(rate, pred)), 6),
                    "选用": False,
                }
            )
            if r2 > best_r2:
                best_name, best_r2, best_model, best_cols = name, r2, est, cols
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
        ),
        pd.DataFrame(quality_rows),
    )
