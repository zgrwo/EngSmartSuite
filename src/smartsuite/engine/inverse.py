"""工艺参数反解模块：列角色识别、前向建模与约束求解。"""

import json
import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy.optimize import differential_evolution, minimize
from scipy.stats import qmc
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    INVERSE_ATTAIN_N,
    INVERSE_DE_MAXITER,
    INVERSE_DE_POPSIZE,
    INVERSE_LAM_TIME,
    INVERSE_MAX_REQUESTS,
    INVERSE_MIN_HISTORY,
    INVERSE_RATE_MIN_ROWS,
    INVERSE_RATE_RIDGE_ALPHA_MAX,
    INVERSE_RATE_RIDGE_ALPHA_MIN,
    INVERSE_RATE_RIDGE_ALPHA_N,
    INVERSE_REG_LAMBDA,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float

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


def _coerce_request_value(value):
    """请求行取值归一：数值字符串转 float，空字符串转 None。"""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return value
    return value


def _parse_request_rows(value) -> list[dict]:
    """解析界面/API 录入的请求行（对象列表或其 JSON 字符串）。

    空值返回 []；非列表或含非对象行时抛中文 ValueError（入口转为 status=error）。
    数值字符串统一转 float，避免追加后与历史数据 dtype 冲突。
    """
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("参数「request_rows」不是有效的 JSON 字符串") from None
    if not isinstance(value, list):
        raise ValueError('参数「request_rows」必须是对象列表（每行形如 {"列名": 数值}）')
    rows: list[dict] = []
    for i, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"参数「request_rows」第 {i} 行不是对象：{row!r}")
        rows.append({str(k): _coerce_request_value(v) for k, v in row.items()})
    return rows


def _append_request_rows(df: pd.DataFrame, rows: list[dict], messages: list[str]) -> pd.DataFrame:
    """把录入的请求行追加到数据末尾（可调参数留空 → 引擎按请求行分类）。

    未知列名忽略并把警告写入 messages；原数据行顺序与索引语义保持不变。
    """
    unknown = sorted({key for row in rows for key in row if key not in df.columns})
    if unknown:
        messages.append(f"request_rows 中以下列不存在于数据中，已忽略：{unknown}")
    appended = pd.DataFrame(rows, columns=list(df.columns))
    messages.append(f"已追加 {len(rows)} 条界面录入的请求行（可调参数留空，按请求行处理）")
    return pd.concat([df, appended], ignore_index=True)


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
    for prefix in ("incoming", "output", "target", "来料", "输出", "目标"):
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
    time_col: str | None = None

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
            time_col=time_col,
        ),
        pd.DataFrame(quality_rows),
    )


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "是")
    return bool(value)


def _safe_json_dict(value, name: str) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    logger.warning("参数「%s」不是有效的 JSON 对象（%r），已回退默认值", name, value)
    return {}


def _safe_bound_pair(pair) -> tuple[float, float] | None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    lo = safe_float(pair[0], float("nan"))
    hi = safe_float(pair[1], float("nan"))
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None
    if hi < lo:
        lo, hi = hi, lo
    return float(lo), float(hi)


def _bound_value(pair, index: int) -> float:
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return safe_float(pair[index], float("nan"))
    return float("nan")


def _sanitize_scale(scale) -> np.ndarray:
    arr = np.ravel(np.asarray(scale, dtype=float))
    if arr.size == 0:
        return np.array([1.0])
    return np.where(np.isfinite(arr) & (arr > 0), arr, 1.0)


def _sanitize_weights(weights) -> np.ndarray:
    arr = np.ravel(np.asarray(weights, dtype=float))
    if arr.size == 0:
        return np.array([1.0])
    return np.where(np.isfinite(arr) & (arr >= 0), arr, 1.0)


def _time_anchor(forward, incoming, time_bounds) -> tuple[float, float]:
    """解析时间正则锚点 (t0, tau)。

    契约：调用方必须把**有限的历史时间中位数**放入 ``incoming[forward.time_col]``；
    缺失或非有限时回退时间区间中点为兜底路径（记录警告）。tau 为区间宽度，
    宽度无效时回退 1.0。
    """
    lo = safe_float(time_bounds[0], 0.0)
    hi = safe_float(time_bounds[1], 0.0)
    time_col = getattr(forward, "time_col", None)
    t0 = None
    if time_col and isinstance(incoming, dict) and time_col in incoming:
        value = safe_float(incoming[time_col], float("nan"))
        if np.isfinite(value):
            t0 = float(value)
    if t0 is None:
        t0 = 0.5 * (lo + hi)
        logger.warning(
            "时间锚点缺失：incoming 未提供时间列「%s」的有限取值，已回退时间区间中点 %g",
            time_col or "?",
            t0,
        )
    scale = hi - lo
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0
    return float(t0), float(scale)


def resolve_bounds(history, roles, params) -> dict[str, tuple[float, float]]:
    """解析可调参数与时间的优化边界。

    优先使用显式 `variable_bounds`（dict 或 JSON 字符串），否则取历史 min/max；
    时间列（`roles.time`）**仅当 `time_adjustable=true`** 时作为可优化维度进入
    bounds，边界取 `time_min/time_max`（空字符串或缺失时回退历史 min/max）。
    `time_adjustable=false` 时时间列即使位于 `roles.variable` 也被排除
    （调用方须把历史中位数作为固定输入注入请求行）。候选区间宽度为 0 的参数
    视为常数，不参与优化并记录警告。
    """
    explicit = _safe_json_dict(params.get("variable_bounds"), "variable_bounds")
    unknown = [key for key in explicit if key not in roles.variable]
    if unknown:
        logger.warning("variable_bounds 中的参数不在可调列中，已忽略: %s", unknown)
    time_adjustable = bool(roles.time) and _as_bool(params.get("time_adjustable"), False)
    bounds: dict[str, tuple[float, float]] = {}
    for col in roles.variable:
        if col == roles.time and not time_adjustable:
            continue
        values = pd.to_numeric(history[col], errors="coerce").dropna()
        lo = float(values.min()) if not values.empty else 0.0
        hi = float(values.max()) if not values.empty else 0.0
        pair = explicit.get(col)
        if pair is not None:
            parsed = _safe_bound_pair(pair)
            if parsed is None:
                logger.warning(
                    "参数「%s」的 variable_bounds 无效（%r），应为 [下限, 上限]，已回退历史范围",
                    col,
                    pair,
                )
            else:
                lo, hi = parsed
        if hi - lo <= 0:
            logger.warning(
                "参数「%s」候选区间宽度为 0（[%g, %g]），视为常数不参与优化", col, lo, hi
            )
        bounds[col] = (float(lo), float(hi))
    if roles.time and time_adjustable:
        values = pd.to_numeric(history[roles.time], errors="coerce").dropna()
        if values.empty:
            logger.warning("时间列「%s」历史无有效数值，无法确定时间边界，已跳过", roles.time)
        else:
            lo = safe_float(params.get("time_min"), float(values.min()))
            hi = safe_float(params.get("time_max"), float(values.max()))
            if hi < lo:
                logger.warning("time_min=%g 大于 time_max=%g，已自动交换", lo, hi)
                lo, hi = hi, lo
            if hi - lo <= 0:
                logger.warning("时间列「%s」候选区间宽度为 0，视为常数不参与优化", roles.time)
            bounds[roles.time] = (float(lo), float(hi))
    return bounds


def optimal_time(forward, incoming, target, scale, weights, u, time_bounds) -> float:
    """固定参数 u 时时间 t 的解析最优（profile），并裁剪到 time_bounds。

    闭式解 t*(u) = (Σ_j w_j·b_j·a_j + c·t0) / (Σ_j w_j·b_j² + c)，其中
    a_j=(Inc_j−y*_j)/s_j、b_j=r_j/s_j、c=INVERSE_LAM_TIME/τ²；t0 优先取
    incoming 中时间列的取值（契约：调用方须把有限的历史时间中位数放入该键），
    缺失时回退区间中点并告警。

    参数合同：`scale` 为 weight_mode 尺度（std/range/none 所得，**不含**
    output_weights）；`weights` 为各输出 output_weights（默认 1.0）。目标函数
    权重 w_j = weights_j，与 scale 相乘构成 §4.3 的 w_j·((ŷ_j−y*_j)/s_j)²。
    本 profile 对 t 使用含 w_j 的严格闭式解（spec §4.3 含权目标；spec §4.2
    简式省略 w_j，以含权式为准）。
    """
    lo = safe_float(time_bounds[0], 0.0)
    hi = safe_float(time_bounds[1], 0.0)
    if hi < lo:
        lo, hi = hi, lo
    rates = np.ravel(np.asarray(forward.predict_rate(incoming, u), dtype=float))
    offsets = np.ravel(np.asarray(forward.predict_output(incoming, u, 0.0), dtype=float))
    target_arr = np.ravel(np.asarray(target, dtype=float))
    scale_arr = _sanitize_scale(scale)
    weight_arr = _sanitize_weights(weights)
    if not (target_arr.size == scale_arr.size == weight_arr.size == rates.size):
        raise ValueError(
            f"目标值/尺度/权重/速率模型输出的数量不一致"
            f"（{target_arr.size}/{scale_arr.size}/{weight_arr.size}/{rates.size}），无法解析时间"
        )
    a = (offsets - target_arr) / scale_arr
    b = rates / scale_arr
    t0, tau = _time_anchor(forward, incoming, (lo, hi))
    c = INVERSE_LAM_TIME / (tau * tau)
    denom = float(np.sum(weight_arr * b * b) + c)
    if not np.isfinite(denom) or denom <= 0:
        t_star = t0
    else:
        t_star = (float(np.sum(weight_arr * b * a)) + c * t0) / denom
    return float(np.clip(t_star, lo, hi))


def solve_one(forward, incoming_row, target, scale, weights, bounds, baseline, params):
    """对单条请求行反解可调参数（rate 模型含解析时间）。

    目标函数：Σ_j w_j·((ŷ_j−y*_j)/s_j)² + reg_lambda·Σ_k ((u_k−u0_k)/range_k)²。
    参数合同：`scale` 为 weight_mode 尺度（**不含** output_weights），
    `weights` 为 output_weights（默认 1.0），二者相乘构成目标权重 w_j；
    与 `optimal_time` 的传入口径一致，调用方不得在 scale 中重复乘 output_weights。
    平滑模型用 L-BFGS-B 多起点（基准点 + max_starts-1 个随机起点，种子固定）；
    树模型用 differential_evolution + L-BFGS-B polish；rate 模型的时间按
    `optimal_time` 解析求解（bounds 含 time 时）。宽度为 0 的参数按常数处理。

    返回 (u, pred, info)：u 为参数名→推荐值；pred 为预测输出数组；
    info 含 `at_bound`（每参数是否触界）、`residual_sigma`（每输出偏差 σ）、
    `method`（求解方式），rate 可调时另含 `time`。
    """
    target_arr = np.ravel(np.asarray(target, dtype=float))
    scale_arr = _sanitize_scale(scale)
    weight_arr = _sanitize_weights(weights)
    n_outputs = len(getattr(forward, "models", []))
    if not (target_arr.size == scale_arr.size == weight_arr.size == n_outputs and n_outputs > 0):
        raise ValueError(
            f"目标值/尺度/权重的数量（{target_arr.size}/{scale_arr.size}/{weight_arr.size}）"
            f"与模型输出数量（{n_outputs}）不一致，无法反解"
        )
    if not np.isfinite(target_arr).all():
        raise ValueError("目标值包含缺失或非有限数值，无法反解")

    reg_lambda = safe_float(params.get("reg_lambda"), INVERSE_REG_LAMBDA)
    max_starts = max(int(safe_float(params.get("max_starts"), 10)), 1)
    random_state = int(safe_float(params.get("random_state"), 42))

    is_rate = isinstance(forward, RateForwardModel)
    time_col = getattr(forward, "time_col", None)

    merged: dict = dict(baseline or {})
    if incoming_row:
        merged.update(incoming_row)

    optimized: list[str] = []
    lo_list: list[float] = []
    hi_list: list[float] = []
    time_bounds: tuple[float, float] | None = None
    constants: dict[str, float] = {}
    for name, pair in bounds.items():
        lo = _bound_value(pair, 0)
        hi = _bound_value(pair, 1)
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            if is_rate and name == time_col:
                time_bounds = (float(lo), float(hi))
                continue
            optimized.append(name)
            lo_list.append(float(lo))
            hi_list.append(float(hi))
        elif np.isfinite(lo) and np.isfinite(hi):
            constants[name] = float(lo)
        else:
            constants[name] = safe_float(merged.get(name), 0.0)
    merged.update(constants)

    lo_arr = np.asarray(lo_list, dtype=float)
    hi_arr = np.asarray(hi_list, dtype=float)
    range_arr = hi_arr - lo_arr
    u0_arr = np.asarray(
        [
            safe_float((baseline or {}).get(name), 0.5 * (lo + hi))
            for name, lo, hi in zip(optimized, lo_list, hi_list, strict=True)
        ],
        dtype=float,
    )
    if u0_arr.size:
        u0_arr = np.clip(u0_arr, lo_arr, hi_arr)

    def _row(x: np.ndarray) -> dict:
        row = dict(merged)
        row.update({name: float(value) for name, value in zip(optimized, x, strict=True)})
        return row

    def _predict(x: np.ndarray) -> tuple[np.ndarray, float | None]:
        row = _row(x)
        u_dict = {name: row[name] for name in optimized}
        if is_rate:
            if time_bounds is not None:
                time_value = optimal_time(
                    forward, row, target_arr, scale_arr, weight_arr, u_dict, time_bounds
                )
            else:
                time_value = safe_float(row.get(time_col), float("nan"))
                if not np.isfinite(time_value):
                    raise ValueError(f"rate 模型缺少时间列「{time_col}」的取值，无法预测")
            pred = np.ravel(
                np.asarray(forward.predict_output(row, u_dict, time_value), dtype=float)
            )
            return pred, float(time_value)
        pred = np.ravel(np.asarray(forward.predict(pd.DataFrame([row])), dtype=float))
        return pred, None

    def objective(x: np.ndarray) -> float:
        pred, time_value = _predict(x)
        if pred.size != target_arr.size or not np.isfinite(pred).all():
            return float("inf")
        residual = (pred - target_arr) / scale_arr
        total = float(np.sum(weight_arr * residual * residual))
        if range_arr.size:
            offset = (np.asarray(x, dtype=float) - u0_arr) / range_arr
            total += reg_lambda * float(offset @ offset)
        if time_value is not None and time_bounds is not None:
            t0, tau = _time_anchor(forward, merged, time_bounds)
            total += INVERSE_LAM_TIME * ((time_value - t0) / tau) ** 2
        return total

    bounds_list = list(zip(lo_arr.tolist(), hi_arr.tolist(), strict=True))
    if not optimized:
        best_x = np.array([], dtype=float)
        method = "constant"
    elif forward.has_tree:
        result = differential_evolution(
            objective,
            bounds_list,
            seed=random_state,
            maxiter=INVERSE_DE_MAXITER,
            popsize=INVERSE_DE_POPSIZE,
            polish=False,
        )
        best_x = np.asarray(result.x, dtype=float)
        best_f = float(result.fun)
        polished = minimize(objective, best_x, method="L-BFGS-B", bounds=bounds_list)
        if polished.fun < best_f:
            best_x = np.asarray(polished.x, dtype=float)
        method = "differential_evolution+L-BFGS-B"
    else:
        rng = np.random.default_rng(random_state)
        starts = [u0_arr.copy()]
        for _ in range(max_starts - 1):
            starts.append(np.array([rng.uniform(lo, hi) for lo, hi in bounds_list]))
        best_x = u0_arr.copy()
        best_f = float("inf")
        for start in starts:
            res = minimize(objective, start, method="L-BFGS-B", bounds=bounds_list)
            if res.fun < best_f:
                best_x = np.asarray(res.x, dtype=float)
                best_f = float(res.fun)
        method = "L-BFGS-B"

    row = _row(best_x)
    pred, time_value = _predict(best_x)
    u_result = {name: float(row[name]) for name in optimized}
    u_result.update(constants)
    if time_value is not None:
        u_result[time_col] = float(time_value)
    at_bound = {}
    for name, value in u_result.items():
        if name not in optimized and not (time_value is not None and name == time_col):
            at_bound[name] = False
            continue
        pair = bounds.get(name)
        lo = _bound_value(pair, 0) if pair is not None else float("nan")
        hi = _bound_value(pair, 1) if pair is not None else float("nan")
        at_bound[name] = bool(
            np.isfinite(lo) and np.isfinite(hi) and (np.isclose(value, lo) or np.isclose(value, hi))
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        residual_sigma = [float(dev) for dev in (pred - target_arr) / scale_arr]
    info = {
        "at_bound": at_bound,
        "residual_sigma": residual_sigma,
        "method": method,
    }
    if time_value is not None:
        info["time"] = float(time_value)
    return u_result, np.asarray(pred, dtype=float), info


def _sampled_feature_frame(cols, incoming_row, param_index, samples, n) -> pd.DataFrame:
    """按采样矩阵构造特征表：可调参数取采样列，其余列取 incoming_row 固定值。"""
    data = {}
    for col in cols:
        if col in param_index:
            data[col] = samples[:, param_index[col]]
            continue
        value = incoming_row.get(col) if incoming_row else None
        number = safe_float(value, float("nan"))
        if value is None or not np.isfinite(number):
            raise ValueError(f"前向模型特征列「{col}」缺少有效取值，无法评估可达性")
        data[col] = np.full(n, float(number))
    return pd.DataFrame(data, columns=list(cols))


def _sampled_rate_matrix(forward, incoming_row, param_index, samples, n) -> np.ndarray:
    """向量化速率预测：每输出一列，shape (n, n_outputs)。"""
    rates = []
    for cols, model in zip(forward.rate_feature_cols, forward.models, strict=True):
        data = {}
        for col in cols:
            if col in param_index:
                data[col] = samples[:, param_index[col]]
            else:
                data[col] = np.full(n, _rate_feature_value(col, incoming_row, None))
        features = pd.DataFrame(data, columns=list(cols))
        rates.append(np.ravel(np.asarray(model.predict(features), dtype=float)))
    return np.column_stack(rates)


def _sampled_rate_offsets(forward, incoming_row, param_index, samples, n) -> np.ndarray:
    """向量化来料截距：每输出一列，shape (n, n_outputs)。"""
    values = []
    for col in forward.incoming_cols:
        if col in param_index:
            values.append(samples[:, param_index[col]])
        else:
            values.append(np.full(n, _rate_feature_value(col, incoming_row, None)))
    return np.column_stack(values)


def _sample_time_values(forward, incoming_row, time_pair, samples, param_count, n) -> np.ndarray:
    if time_pair is not None:
        return np.asarray(samples[:, param_count], dtype=float)
    if not getattr(forward, "uses_time", False):
        return np.zeros(n, dtype=float)
    time_col = getattr(forward, "time_col", None)
    value = incoming_row.get(time_col) if incoming_row else None
    number = safe_float(value, float("nan"))
    if value is None or not np.isfinite(number):
        raise ValueError(f"rate 模型缺少时间列「{time_col}」的取值，无法评估可达性")
    return np.full(n, float(number))


def reachable_range(forward, incoming_row, bounds, n, seed, time_bounds=None):
    """拉丁超立方采样评估参数盒内各输出的可达范围（spec §4.4）。

    参数:
        forward: 前向模型（`ForwardModel` 或 `RateForwardModel`）。
        incoming_row: 请求行的来料/固定列取值 dict（rate 模型的 time 固定值也从此取）。
        bounds: 可调参数边界 {参数名: (下限, 上限)}；**为空时抛中文 ValueError**
            （退化输入不静默传播）。
        n: 采样点数，须 >= 2，否则抛中文 ValueError。
        seed: 采样随机种子，同 seed 结果确定。
        time_bounds: rate 模型可调时间区间；非 None 且 `forward.uses_time` 时
            把 time 作为额外采样维度；None 时若 `bounds` 含时间列则自动取其区间
            （镜像 `solve_one`），否则时间取 incoming_row 固定值并记录警告。

    返回:
        (lo, hi)：每个输出列的最小/最大可达值，shape 均为 (n_outputs,)。
        参数/时间边界非有限、特征缺失或预测非有限时抛中文 ValueError。
    """
    if not bounds:
        raise ValueError("可调参数边界为空，无法进行可达性采样")
    n = int(n)
    if n < 2:
        raise ValueError(f"采样点数 n 必须 >= 2（当前 {n}），无法评估可达范围")
    if incoming_row is None:
        incoming_row = {}
    uses_time = bool(getattr(forward, "uses_time", False))
    time_col = getattr(forward, "time_col", None)
    param_names: list[str] = []
    lo_list: list[float] = []
    hi_list: list[float] = []
    time_pair: tuple[float, float] | None = None
    for name, pair in bounds.items():
        lo = _bound_value(pair, 0)
        hi = _bound_value(pair, 1)
        if not (np.isfinite(lo) and np.isfinite(hi)):
            raise ValueError(f"参数「{name}」的边界无效（{pair!r}），无法进行可达性采样")
        if hi < lo:
            lo, hi = hi, lo
        if uses_time and name == time_col:
            if time_bounds is None:
                time_pair = (float(lo), float(hi))
            continue
        param_names.append(name)
        lo_list.append(float(lo))
        hi_list.append(float(hi))
    if uses_time and time_bounds is not None:
        t_lo = _bound_value(time_bounds, 0)
        t_hi = _bound_value(time_bounds, 1)
        if not (np.isfinite(t_lo) and np.isfinite(t_hi)):
            raise ValueError(f"时间边界无效（{time_bounds!r}），无法进行可达性采样")
        if t_hi < t_lo:
            t_lo, t_hi = t_hi, t_lo
        time_pair = (float(t_lo), float(t_hi))
    if uses_time and time_pair is None:
        logger.warning(
            "时间未作为可调维度参与可达性采样（bounds 无时间列且未提供 time_bounds），"
            "可达范围为时间固定假设"
        )
    if not param_names and time_pair is None:
        raise ValueError("可调参数与时间边界均为空，无法进行可达性采样")
    sampler = qmc.LatinHypercube(
        d=len(param_names) + (1 if time_pair is not None else 0), seed=seed
    )
    unit = sampler.random(n)
    lo_arr = np.asarray(lo_list + ([time_pair[0]] if time_pair is not None else []), dtype=float)
    hi_arr = np.asarray(hi_list + ([time_pair[1]] if time_pair is not None else []), dtype=float)
    samples = lo_arr + unit * (hi_arr - lo_arr)
    param_index = {name: i for i, name in enumerate(param_names)}
    if isinstance(forward, RateForwardModel):
        rates = _sampled_rate_matrix(forward, incoming_row, param_index, samples, n)
        offsets = _sampled_rate_offsets(forward, incoming_row, param_index, samples, n)
        times = _sample_time_values(forward, incoming_row, time_pair, samples, len(param_names), n)
        pred = offsets - rates * times[:, None]
    else:
        features = _sampled_feature_frame(
            forward.feature_cols, incoming_row, param_index, samples, n
        )
        pred = np.asarray(forward.predict(features), dtype=float)
    if pred.ndim == 1:
        pred = pred.reshape(-1, 1)
    if not np.isfinite(pred).all():
        raise ValueError("可达性采样预测包含非有限值（NaN/Inf），请检查模型与输入数据")
    return pred.min(axis=0), pred.max(axis=0)


_LOW_LOO_R2 = 0.3  # spec §5：选中模型 LOO R² 低于该值提示"可解释性弱"
_INVERSE_MODELS = ("auto", "linear", "poly", "gpr", "gbm", "rate")
_WEIGHT_MODES = ("std", "range", "none")
_DEFAULT_ATTAIN_TOL = 0.5  # spec §3 attain_tol 默认值
_DEFAULT_MAX_STARTS = 10  # spec §3 max_starts 默认值
_DEFAULT_RANDOM_STATE = 42  # spec §3 random_state 默认值


def _parse_float_param(params, key, default, messages) -> float:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return float(default)
    value = safe_float(raw, float("nan"))
    if not np.isfinite(value):
        messages.append(f"参数「{key}」取值无效（{raw!r}），已回退默认值 {default!r}")
        return float(default)
    return float(value)


def _parse_optional_float(params, key, messages) -> float | None:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value = safe_float(raw, float("nan"))
    if not np.isfinite(value):
        messages.append(f"参数「{key}」取值无效（{raw!r}），已忽略并使用历史范围")
        return None
    return float(value)


def _parse_json_param(params, key, messages, fallback_note) -> dict:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    messages.append(f"参数「{key}」不是有效的 JSON 对象（{raw!r}），{fallback_note}")
    return {}


def _output_scale(history, output_cols, mode, messages) -> np.ndarray:
    """按 weight_mode 计算各输出的目标尺度（不含 output_weights，避免双重加权）。"""
    labels = {"std": "标准差", "range": "极差", "none": "常数 1"}
    scales = []
    for col in output_cols:
        values = pd.to_numeric(history[col], errors="coerce").dropna()
        if mode == "range" and not values.empty:
            scale = float(values.max() - values.min())
        elif mode == "std" and len(values) > 1:
            scale = float(values.std())
        else:
            scale = 1.0
        if not np.isfinite(scale) or scale <= 0:
            messages.append(
                f"输出「{col}」的{labels.get(mode, mode)}为 0 或无效，尺度已按 1.0 处理"
            )
            scale = 1.0
        scales.append(scale)
    return np.asarray(scales, dtype=float)


def _pair_targets(target_cols, output_cols) -> dict[str, str]:
    """目标列→输出列配对：优先按去前缀后缀，其次顺序配对，单列时全输出共用。"""
    pairs: dict[str, str] = {}
    if not target_cols:
        return pairs
    for out_col in output_cols:
        suffix = _strip_role_prefix(out_col)
        match = next((t for t in target_cols if _strip_role_prefix(t) == suffix), None)
        if match is not None:
            pairs[out_col] = match
    if len(pairs) < len(output_cols):
        if len(target_cols) == len(output_cols):
            for out_col, t_col in zip(output_cols, target_cols, strict=True):
                pairs.setdefault(out_col, t_col)
        elif len(target_cols) == 1:
            for out_col in output_cols:
                pairs.setdefault(out_col, target_cols[0])
    return pairs


def _fmt_num(value: float) -> str:
    """方程系数格式化：4 位有效数字并去除末尾 0（如 0.05000 → 0.05）。"""
    number = float(value)
    if number == 0:
        return "0"
    text = f"{number:.4g}"
    if "e" in text or "E" in text:
        return text
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _linear_expression(intercept: float, cols: list[str], coefs) -> str:
    """原始单位线性表达式 b0 + b1·x1 − b2·x2（|系数|<1e-12 的项省略）。"""
    expr = _fmt_num(intercept)
    for col, coef in zip(cols, np.ravel(np.asarray(coefs, dtype=float)), strict=True):
        coef = float(coef)
        if abs(coef) < 1e-12:
            continue
        expr += f" {'+' if coef > 0 else '-'} {_fmt_num(abs(coef))}·{col}"
    return expr


def _raw_linear_coefficients(model):
    """把 StandardScaler + 线性/Ridge pipeline 换算为原始单位系数 (截距, 系数)。

    输入/输出关系：ŷ = b0' + Σ b_i·(x_i−μ_i)/σ_i = b0 + Σ (b_i/σ_i)·x_i，
    故 b0 = b0' − Σ b_i·μ_i/σ_i。非该结构返回 None。
    """
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None
    scaler = steps.get("standardscaler")
    reg = steps.get("linearregression")
    if reg is None:
        reg = steps.get("ridgecv")
    if scaler is None or reg is None:
        return None
    coef = np.ravel(np.asarray(reg.coef_, dtype=float))
    intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
    mean = np.ravel(np.asarray(scaler.mean_, dtype=float))
    scale = np.ravel(np.asarray(scaler.scale_, dtype=float))
    return intercept - float(np.sum(coef * mean / scale)), coef / scale


def _raw_poly_expression(model, cols: list[str]) -> str | None:
    """把 PolynomialFeatures + StandardScaler + Ridge pipeline 展开为原始单位多项式。"""
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None
    poly = steps.get("polynomialfeatures")
    scaler = steps.get("standardscaler")
    reg = steps.get("ridgecv")
    if poly is None or scaler is None or reg is None:
        return None
    coef = np.ravel(np.asarray(reg.coef_, dtype=float))
    intercept = float(np.ravel(np.asarray(reg.intercept_, dtype=float))[0])
    mean = np.ravel(np.asarray(scaler.mean_, dtype=float))
    scale = np.ravel(np.asarray(scaler.scale_, dtype=float))
    weights = coef / scale
    expr = _fmt_num(intercept - float(np.sum(coef * mean / scale)))
    for row_idx, powers in enumerate(poly.powers_):
        weight = float(weights[row_idx])
        if abs(weight) < 1e-12:
            continue
        term = (
            "·".join(
                name if int(power) == 1 else f"{name}^{int(power)}"
                for name, power in zip(cols, powers, strict=True)
                if power > 0
            )
            or "1"
        )
        expr += f" {'+' if weight > 0 else '-'} {_fmt_num(abs(weight))}·{term}"
    return expr


def _forward_equation(kind: str, model, cols: list[str], out_col: str) -> tuple[str | None, str]:
    """单个输出的前向方程（原始单位）；无解析式返回 (None, 中文说明)。"""
    if kind == "linear":
        raw = _raw_linear_coefficients(model)
        if raw is not None:
            return (
                f"{out_col} = {_linear_expression(raw[0], cols, raw[1])}",
                "线性回归（原始单位）",
            )
    if kind == "poly":
        expr = _raw_poly_expression(model, cols)
        if expr is not None:
            return f"{out_col} = {expr}", "二次多项式 Ridge（原始单位）"
    if kind == "gpr":
        return None, "高斯过程核方法无解析表达式（预测由核函数加权给出）"
    if kind == "gbm":
        return None, "梯度提升树集成无解析表达式（预测由各回归树求和给出）"
    return None, f"模型 {kind} 无解析表达式"


def _rate_equation(forward, index: int, out_col: str) -> tuple[str | None, str]:
    """速率模型单输出方程：Y = 来料 − 速率(z)·t（速率为原始单位线性式）。"""
    raw = _raw_linear_coefficients(forward.models[index])
    inc_col = forward.incoming_cols[index]
    cols = list(forward.rate_feature_cols[index])
    if raw is None:
        return None, "速率模型无解析表达式（速率项非线性）"
    return (
        f"{out_col} = {inc_col} − ({_linear_expression(raw[0], cols, raw[1])})·t",
        "速率物理模型（输出=来料−速率×时间，原始单位）",
    )


def _inverse_formula_rows(forward, roles, bounds) -> list[dict]:
    """逐可调参数给出解析反解公式；不可解析的模型注明数值优化。"""
    rows: list[dict] = []
    adjustable = [name for name, pair in bounds.items() if pair[1] > pair[0]]
    if not adjustable:
        return rows
    if isinstance(forward, RateForwardModel):
        time_col = forward.time_col
        for index, out_col in enumerate(roles.output):
            raw = _raw_linear_coefficients(forward.models[index])
            inc_col = forward.incoming_cols[index]
            rate_expr = (
                _linear_expression(raw[0], list(forward.rate_feature_cols[index]), raw[1])
                if raw is not None
                else None
            )
            for name in adjustable:
                if name == time_col and rate_expr is not None:
                    rows.append(
                        {
                            "类型": "反解公式",
                            "对象": f"{out_col} → {name}",
                            "表达式": f"{name} = ({inc_col} − 目标{out_col}) / ({rate_expr})",
                            "说明": (
                                "速率模型时间解析反解；其余可调项取推荐值，"
                                "多输出时按加权目标解析（见优化目标）"
                            ),
                        }
                    )
                else:
                    rows.append(
                        {
                            "类型": "反解公式",
                            "对象": f"{out_col} → {name}",
                            "表达式": "—",
                            "说明": "速率模型非时间参数无闭式反解，采用数值优化（见优化目标）",
                        }
                    )
        return rows
    for index, out_col in enumerate(roles.output):
        kind = forward.choice[index]
        feature_cols = list(forward.feature_cols)
        raw = _raw_linear_coefficients(forward.models[index]) if kind == "linear" else None
        for name in adjustable:
            if name not in feature_cols:
                continue
            if raw is None:
                rows.append(
                    {
                        "类型": "反解公式",
                        "对象": f"{out_col} → {name}",
                        "表达式": "—",
                        "说明": f"{kind} 模型无解析反解，采用数值优化（见优化目标）",
                    }
                )
                continue
            intercept, coefs = raw
            position = feature_cols.index(name)
            coef_u = float(coefs[position])
            if abs(coef_u) < 1e-12:
                rows.append(
                    {
                        "类型": "反解公式",
                        "对象": f"{out_col} → {name}",
                        "表达式": "—",
                        "说明": f"该参数在「{out_col}」方程中系数≈0，无法由该输出反解",
                    }
                )
                continue
            rest_cols = [c for i, c in enumerate(feature_cols) if i != position]
            rows.append(
                {
                    "类型": "反解公式",
                    "对象": f"{out_col} → {name}",
                    "表达式": (
                        f"{name} = (目标{out_col} − "
                        f"({_linear_expression(intercept, rest_cols, np.delete(coefs, position))})) "
                        f"/ ({_fmt_num(coef_u)})"
                    ),
                    "说明": "线性模型解析反解；多可调参数时其余项取推荐值，多输出时按加权目标寻优",
                }
            )
    return rows


def _objective_row(forward, bounds, params, weight_mode: str) -> dict:
    """优化目标函数（含实际 λ 与权重口径），供非线性模型对照。"""
    lam = safe_float(params.get("reg_lambda"), INVERSE_REG_LAMBDA)
    expr = "min Σ_j w_j·((ŷ_j − y*_j)/s_j)² + λ·Σ_k((u_k − u0_k)/range_k)²"
    adjustable = [name for name, pair in bounds.items() if pair[1] > pair[0]]
    if isinstance(forward, RateForwardModel) and getattr(forward, "time_col", None) in adjustable:
        expr += " + c·((t − t0)/τ)²"
    if not adjustable:
        expr = "—"
        note = "无可调参数（variable_cols 为空或候选区间宽度为 0）"
    else:
        note = (
            f"λ={_fmt_num(lam)}；w_j 为输出权重（默认 1），尺度 s_j 按 {weight_mode} 口径；"
            "线性模型解析/L-BFGS-B 多起点，树模型差分进化"
        )
    return {"类型": "优化目标", "对象": "全部可调参数", "表达式": expr, "说明": note}


def _build_model_equations(forward, roles, bounds, params, weight_mode: str) -> pd.DataFrame:
    """组装 model_equations 表：前向方程（逐输出）+ 反解公式（逐参数）+ 优化目标。"""
    rows: list[dict] = []
    if isinstance(forward, RateForwardModel):
        for index, out_col in enumerate(roles.output):
            expr, note = _rate_equation(forward, index, out_col)
            rows.append({"类型": "前向方程", "对象": out_col, "表达式": expr or "—", "说明": note})
    else:
        feature_cols = list(forward.feature_cols)
        for index, out_col in enumerate(roles.output):
            expr, note = _forward_equation(
                forward.choice[index], forward.models[index], feature_cols, out_col
            )
            rows.append({"类型": "前向方程", "对象": out_col, "表达式": expr or "—", "说明": note})
    rows.extend(_inverse_formula_rows(forward, roles, bounds))
    rows.append(_objective_row(forward, bounds, params, weight_mode))
    return pd.DataFrame(rows, columns=["类型", "对象", "表达式", "说明"])


def _figure_parameter_comparison(history, bounds, roles, recommendations):
    cols = list(bounds) or list(roles.variable)
    fig = Figure(figsize=(max(len(cols) * 1.4, 6.5), 4.5))
    ax = fig.add_subplot(111)
    if cols:
        data = [pd.to_numeric(history[c], errors="coerce").dropna().to_numpy(float) for c in cols]
        box = ax.boxplot(
            data,
            positions=list(range(1, len(cols) + 1)),
            widths=0.5,
            patch_artist=True,
            showfliers=False,
        )
        for patch in box["boxes"]:
            patch.set_facecolor(PALETTE["data"]["secondary"])
            patch.set_edgecolor(PALETTE["data"]["primary"])
        for median in box["medians"]:
            median.set_color(PALETTE["data"]["primary"])
            median.set_linewidth(1.5)
        for rec_i, rec in enumerate(recommendations):
            xs, ys = [], []
            for j, col in enumerate(cols):
                value = safe_float(rec.get(col), float("nan")) if col in rec else float("nan")
                if np.isfinite(value):
                    xs.append(j + 1)
                    ys.append(float(value))
            if xs:
                ax.scatter(
                    xs,
                    ys,
                    marker="D",
                    s=45,
                    color=PALETTE["target"]["primary"],
                    edgecolors=PALETTE["misc"]["background"],
                    linewidths=0.8,
                    zorder=3,
                    label="推荐值" if rec_i == 0 else None,
                )
        ax.set_xticks(list(range(1, len(cols) + 1)))
        ax.set_xticklabels(cols, rotation=20, ha="right")
        if recommendations:
            ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "无可调参数或时间列", transform=ax.transAxes, ha="center", va="center")
    ax.set_ylabel("参数值")
    ax.set_title("推荐参数 vs 历史范围")
    return fig


def _figure_residuals(predictions, output_cols, attain_tol):
    fig = Figure(figsize=(max(len(predictions) * 0.9, 7.0), 4.0))
    ax = fig.add_subplot(111)
    ax.axhline(0.0, color=PALETTE["direction"]["zero"], linewidth=1.0, label="0")
    for sign, label in ((1.0, f"±{attain_tol:g}σ"), (-1.0, None)):
        ax.axhline(
            sign * attain_tol,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=label,
        )
    if predictions and output_cols:
        n_out = len(output_cols)
        width = 0.8 / n_out
        x = np.arange(len(predictions), dtype=float)
        colors = [
            PALETTE["contrast"]["a"],
            PALETTE["contrast"]["b"],
            PALETTE["contrast"]["c"],
            PALETTE["contrast"]["d"],
        ]
        for j, out_col in enumerate(output_cols):
            deviations = [safe_float(p.get(f"偏差{out_col}"), float("nan")) for p in predictions]
            offset = (j - (n_out - 1) / 2.0) * width
            ax.bar(
                x + offset,
                deviations,
                width=width,
                color=colors[j % len(colors)],
                label=out_col,
            )
        ax.set_xticks(x)
        ax.set_xticklabels([str(p["请求行号"]) for p in predictions])
        ax.set_xlabel("请求行号")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "无请求行，无偏差数据", transform=ax.transAxes, ha="center", va="center")
        ax.set_xticks([])
    ax.set_ylabel("偏差（σ）")
    ax.set_title("各请求输出偏差（σ 单位）")
    return fig


def inverse_parameter_solve(req: AnalysisRequest) -> AnalysisResult:
    """工艺参数反解入口：角色识别 → 行分类 → 前向建模 → 逐请求求解与可达性 → 结果组装。

    参数 (params): spec §3 共 17 键；数值一律经 safe_float、JSON 参数经安全解析，
    解析失败回退默认并把警告写入 messages。

    返回四表、两图、中文 summary 与 metadata；数据/参数错误返回
    ``status="error"`` + 中文 messages，不抛 traceback。
    """
    task = "inverse_solve"
    messages: list[str] = []
    try:
        df = req.data
        params = dict(req.params or {})
        model = str(params.get("model") or "auto").strip().lower()
        if model not in _INVERSE_MODELS:
            raise ValueError(f"参数「model」取值无效（{model}），可选：{'/'.join(_INVERSE_MODELS)}")
        params["model"] = model
        is_rate = model == "rate"
        weight_mode = str(params.get("weight_mode") or "std").strip().lower()
        if weight_mode not in _WEIGHT_MODES:
            messages.append(
                f"参数「weight_mode」取值无效（{params.get('weight_mode')!r}），已回退默认 std"
            )
            weight_mode = "std"
        params["weight_mode"] = weight_mode
        params["reg_lambda"] = _parse_float_param(
            params, "reg_lambda", INVERSE_REG_LAMBDA, messages
        )
        attain_tol = _parse_float_param(params, "attain_tol", _DEFAULT_ATTAIN_TOL, messages)
        params["max_starts"] = _parse_float_param(
            params, "max_starts", _DEFAULT_MAX_STARTS, messages
        )
        seed = int(_parse_float_param(params, "random_state", _DEFAULT_RANDOM_STATE, messages))
        params["random_state"] = seed
        params["time_min"] = _parse_optional_float(params, "time_min", messages)
        params["time_max"] = _parse_optional_float(params, "time_max", messages)
        params["variable_bounds"] = _parse_json_param(
            params, "variable_bounds", messages, "已回退为各参数历史范围"
        )
        bounds_map = params["variable_bounds"]
        weights_map = _parse_json_param(
            params, "output_weights", messages, "已按各输出权重 1.0 处理"
        )

        request_rows = _parse_request_rows(params.get("request_rows"))
        if request_rows:
            df = _append_request_rows(df, request_rows, messages)

        roles = resolve_roles(df, params)
        if is_rate and not roles.time:
            candidates = [
                c
                for c in roles.variable + roles.fixed
                if "time" in str(c).lower() or "时间" in str(c)
            ]
            if len(candidates) == 1:
                roles.time = candidates[0]
                messages.append(f"rate 模型未指定 time_col，已自动识别时间列「{candidates[0]}」")
            elif len(candidates) > 1:
                raise ValueError(
                    f"rate 模型识别到多个时间候选列 {candidates}，请用 time_col 参数显式指定"
                )
            else:
                raise ValueError(
                    "rate 模型需要时间列 time_col（列名含 time/时间 的可调或固定列），请显式指定"
                )
        time_adjustable = bool(roles.time) and _as_bool(params.get("time_adjustable"), False)
        unknown_bounds = [
            key for key in bounds_map if key not in roles.variable and key != roles.time
        ]
        if unknown_bounds:
            messages.append(
                f"variable_bounds 中的列不在可调参数/时间列中，已忽略：{unknown_bounds}"
            )
        unknown_weights = [key for key in weights_map if key not in roles.output]
        if unknown_weights:
            messages.append(f"output_weights 中的列不在输出列中，已忽略：{unknown_weights}")

        history, request, skipped = split_rows(df, roles)
        if len(history) < INVERSE_MIN_HISTORY:
            raise ValueError(
                f"历史数据不足（至少 {INVERSE_MIN_HISTORY} 行），当前有效历史 {len(history)} 行"
            )
        total_requests = len(request)
        if total_requests > INVERSE_MAX_REQUESTS:
            messages.append(
                f"请求行数 {total_requests} 超过上限 {INVERSE_MAX_REQUESTS}，"
                f"已截断为前 {INVERSE_MAX_REQUESTS} 行处理"
            )
            request = request.iloc[:INVERSE_MAX_REQUESTS]

        if is_rate:
            # 速率模型在 fit_rate_forward 内按输出做特征有限性掩码
            clean_cols = list(roles.output)
        else:
            # 仅清理会进入前向模型的特征列（常量列由 fit_forward 剔除，无需清行）
            clean_cols = [
                col
                for col in roles.incoming + roles.variable + roles.fixed
                if col in history.columns and history[col].nunique(dropna=True) > 1
            ] + list(roles.output)
        clean_mask = pd.Series(True, index=history.index)
        for col in clean_cols:
            clean_mask &= np.isfinite(pd.to_numeric(history[col], errors="coerce"))
        if not clean_mask.all():
            dropped_rows = int((~clean_mask).sum())
            messages.append(f"已剔除 {dropped_rows} 行历史数据（建模特征或输出含缺失/非有限值）")
            history = history[clean_mask]
        if len(history) < INVERSE_MIN_HISTORY:
            raise ValueError(
                f"历史数据不足（至少 {INVERSE_MIN_HISTORY} 行特征完整），当前 {len(history)} 行"
            )

        time_col = roles.time
        time_stats = None
        time_median = None
        if time_col:
            time_values = pd.to_numeric(history[time_col], errors="coerce").dropna()
            if not time_values.empty:
                time_median = float(time_values.median())
                time_stats = {
                    "min": float(time_values.min()),
                    "median": time_median,
                    "max": float(time_values.max()),
                }
        if is_rate and time_median is None:
            raise ValueError(f"时间列「{time_col}」在历史中无有效数值，无法建立速率模型")

        if is_rate:
            forward, quality = fit_rate_forward(history, roles, time_col, random_state=seed)
            if getattr(forward, "pairing_note", None):
                messages.append(forward.pairing_note)
            messages.append(
                "rate 模型基于时间线性速率假设（输出=来料−速率×时间），时间外推结论需实验验证"
            )
        else:
            forward, quality = fit_forward(history, roles, model=model, random_state=seed)
            dropped_features = [
                c
                for c in roles.incoming + roles.variable + roles.fixed
                if c not in forward.feature_cols
            ]
            if dropped_features:
                messages.append(
                    f"以下特征列在历史中为常量，未参与建模：{'、'.join(dropped_features)}"
                )
        selected = quality[quality["选用"]] if not quality.empty else quality
        choice_label = "速率特征" if is_rate else "模型"
        for _, q_row in selected.iterrows():
            r2 = safe_float(q_row["LOO_R2"], float("nan"))
            if not np.isfinite(r2):
                messages.append(
                    f"输出「{q_row['Output']}」模型质量无法评估（LOO R² 非有限），反解结果仅供参考"
                )
            elif r2 < _LOW_LOO_R2:
                messages.append(
                    f"输出「{q_row['Output']}」所选{choice_label}（{q_row['候选']}）可解释性弱"
                    f"（LOO R²={r2:.3f}），反解结果仅供参考"
                )

        bounds = resolve_bounds(history, roles, params)
        zero_width = [name for name, pair in bounds.items() if not (pair[1] - pair[0] > 0)]
        if zero_width:
            messages.append(
                f"以下参数候选区间宽度为 0，已视为常数不参与优化：{'、'.join(zero_width)}"
            )
        equations = _build_model_equations(forward, roles, bounds, params, weight_mode)
        baseline = {
            col: float(pd.to_numeric(history[col], errors="coerce").dropna().median())
            for col in roles.variable
        }
        scale = _output_scale(history, roles.output, weight_mode, messages)
        weights = _sanitize_weights(
            np.asarray(
                [safe_float(weights_map.get(col, 1.0), 1.0) for col in roles.output],
                dtype=float,
            )
        )
        target_pairs = _pair_targets(roles.target, roles.output)
        incoming_stats = {
            col: (float(history[col].min()), float(history[col].max())) for col in roles.incoming
        }
        fixed_values = {}
        for col in roles.fixed:
            values = pd.to_numeric(history[col], errors="coerce").dropna()
            fixed_values[col] = float(values.median()) if not values.empty else float("nan")
        used_features: set[str] = set()
        if is_rate:
            used_features.update(forward.incoming_cols)
            for cols in forward.rate_feature_cols:
                used_features.update(cols)
        else:
            used_features.update(forward.feature_cols)
        # 时间列是模型所需输入且不可调时，按历史中位数注入请求行；
        # rate 模型无论是否可调都注入中位数（作为时间正则锚点 t0）
        inject_time = (
            bool(time_col) and time_median is not None and (is_rate or time_col in used_features)
        )
        if inject_time and not time_adjustable and not request.empty:
            messages.append(f"时间列「{time_col}」不可调，已按历史中位数 {time_median:g} 处理")

        recommendation_rows: list[dict] = []
        prediction_rows: list[dict] = []
        reachable_rows: list[dict] = []
        sigma_by_output: dict[str, list[float]] = {col: [] for col in roles.output}
        n_failed = 0
        n_reachable = 0
        at_bound_total = 0

        for pos, (idx, row) in enumerate(request.iterrows(), start=1):
            label = int(idx) if isinstance(idx, (int, np.integer)) else pos
            incoming: dict[str, float] = {}
            invalid_inputs: list[str] = []
            for col in roles.incoming:
                value = safe_float(row[col], float("nan"))
                if np.isfinite(value):
                    incoming[col] = value
                else:
                    invalid_inputs.append(col)
            for col in roles.fixed:
                value = safe_float(row[col], float("nan"))
                if not np.isfinite(value):
                    value = fixed_values[col]
                if np.isfinite(value):
                    incoming[col] = value
                elif col in used_features:
                    invalid_inputs.append(col)
            if inject_time:
                incoming[time_col] = time_median
            targets: list[float] = []
            invalid_targets: list[str] = []
            for out_col in roles.output:
                t_col = target_pairs.get(out_col)
                value = safe_float(row[t_col], float("nan")) if t_col else float("nan")
                if not np.isfinite(value):
                    value = safe_float(row[out_col], float("nan"))
                if np.isfinite(value):
                    targets.append(value)
                else:
                    invalid_targets.append(out_col)
            if invalid_inputs or invalid_targets:
                reasons = []
                if invalid_inputs:
                    reasons.append(f"来料/固定列缺失或无效: {invalid_inputs}")
                if invalid_targets:
                    reasons.append(f"目标缺失或无效: {invalid_targets}")
                messages.append(f"请求行 {label} 已跳过（{'；'.join(reasons)}）")
                n_failed += 1
                continue
            target_arr = np.asarray(targets, dtype=float)
            for col in roles.incoming:
                lo_h, hi_h = incoming_stats[col]
                if incoming[col] < lo_h or incoming[col] > hi_h:
                    messages.append(
                        f"请求行 {label} 的来料「{col}」={incoming[col]:.4g} 超出历史范围 "
                        f"[{lo_h:.4g}, {hi_h:.4g}]，属外推预测，建议实验验证"
                    )

            try:
                u, pred, info = solve_one(
                    forward, incoming, target_arr, scale, weights, bounds, baseline, params
                )
                lo_arr, hi_arr = reachable_range(
                    forward,
                    incoming,
                    bounds,
                    n=INVERSE_ATTAIN_N,
                    seed=seed,
                    time_bounds=None,
                )
            except ValueError as exc:
                messages.append(f"请求行 {label} 反解失败，已跳过：{exc}")
                n_failed += 1
                continue

            resid_sigmas = list(info["residual_sigma"])
            misses = [
                f"{out_col}({dev:+.2f}σ)"
                for out_col, dev in zip(roles.output, resid_sigmas, strict=True)
                if abs(dev) > attain_tol
            ]
            at_bounds = [name for name, flag in info["at_bound"].items() if flag]
            at_bound_total += len(at_bounds)
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                if abs(dev) > attain_tol:
                    messages.append(
                        f"请求行 {label}：输出「{out_col}」偏差 {dev:+.2f}σ 超过达到阈值 "
                        f"{attain_tol:g}σ，目标难以达到"
                    )
            for name in at_bounds:
                pair = bounds.get(name, (float("nan"), float("nan")))
                messages.append(
                    f"请求行 {label}：参数「{name}」推荐值 {u[name]:.4g} 顶到边界 "
                    f"[{pair[0]:g}, {pair[1]:g}]"
                )
            if time_col and time_col in u and time_stats:
                t_value = float(u[time_col])
                if t_value < time_stats["min"] or t_value > time_stats["max"]:
                    messages.append(
                        f"请求行 {label}：推荐时间 {t_value:.4g} 超出历史时间范围 "
                        f"[{time_stats['min']:g}, {time_stats['max']:g}]；"
                        "时间线性为模型假设，历史数据未覆盖，建议实验验证"
                    )

            rec = {"请求行号": label}
            rec.update(incoming)
            for out_col, value in zip(roles.output, targets, strict=True):
                rec[f"目标{out_col}"] = float(value)
            for name, value in u.items():
                rec[name] = float(value)
            if misses:
                rec["状态"] = "不可达: " + ", ".join(misses)
            elif at_bounds:
                rec["状态"] = "可达（参数触界: " + ", ".join(at_bounds) + "）"
            else:
                rec["状态"] = "可达"
            recommendation_rows.append(rec)

            pred_row = {"请求行号": label}
            for out_col, value in zip(roles.output, pred, strict=True):
                pred_row[f"预测{out_col}"] = float(value)
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                pred_row[f"偏差{out_col}"] = round(float(dev), 3)
                sigma_by_output[out_col].append(abs(float(dev)))
            pred_row["总残差σ"] = round(float(np.sqrt(np.mean(np.square(resid_sigmas)))), 3)
            for out_col, dev in zip(roles.output, resid_sigmas, strict=True):
                pred_row[f"可达{out_col}"] = "否" if abs(dev) > attain_tol else "是"
            prediction_rows.append(pred_row)
            if not misses:
                n_reachable += 1

            for out_col, lo_v, hi_v, tgt in zip(roles.output, lo_arr, hi_arr, targets, strict=True):
                inside = float(lo_v) - 1e-9 <= tgt <= float(hi_v) + 1e-9
                reachable_rows.append(
                    {
                        "请求行号": label,
                        "Output": out_col,
                        "可达下限": float(lo_v),
                        "可达上限": float(hi_v),
                        "目标": float(tgt),
                        "是否在内": "是" if inside else "否",
                    }
                )

        if skipped:
            detail = "；".join(f"行 {idx}: {reason}" for idx, reason in skipped[:5])
            suffix = " 等" if len(skipped) > 5 else ""
            messages.append(
                f"已跳过 {len(skipped)} 行无法判定为历史或请求的数据（{detail}{suffix}）"
            )
        if request.empty:
            messages.append("未检测到请求行（仅历史数据），已完成前向建模与模型质量评估")

        n_solved = len(recommendation_rows)
        bottleneck = None
        if n_solved:
            means = {
                out_col: float(np.mean(values))
                for out_col, values in sigma_by_output.items()
                if values
            }
            if means:
                bottleneck = max(means, key=means.get)
        all_sigmas = [value for values in sigma_by_output.values() for value in values]
        if is_rate:
            choice_desc = "rate（时间线性速率模型）"
        elif model == "auto":
            detail = "、".join(
                f"{out_col}={kind}"
                for out_col, kind in zip(roles.output, forward.choice, strict=True)
            )
            choice_desc = f"auto（{detail}）"
        else:
            choice_desc = model
        summary_parts = [
            f"工艺参数反解完成：历史 {len(history)} 行，请求 {len(request)} 行",
            f"模型 {choice_desc}",
        ]
        if n_solved:
            summary_parts.append(f"可达 {n_reachable}/{n_solved}（偏差≤{attain_tol:g}σ）")
            if bottleneck is not None:
                summary_parts.append(
                    f"主要瓶颈 {bottleneck}（平均 {float(np.mean(sigma_by_output[bottleneck])):.2f}σ）"
                )
            if at_bound_total:
                summary_parts.append(f"{at_bound_total} 个参数触界")
            if n_failed:
                summary_parts.append(f"{n_failed} 条请求未能求解")
        elif request.empty:
            summary_parts.append("未检测到请求行，仅输出模型质量评估")
        else:
            summary_parts.append(f"请求 {len(request)} 行均未能求解")
        summary = "；".join(summary_parts) + "。"

        time_rec_cols = (
            [time_col] if time_col and time_col not in bounds and (is_rate or inject_time) else []
        )
        rec_columns = (
            ["请求行号"]
            + list(roles.incoming)
            + [f"目标{col}" for col in roles.output]
            + list(bounds)
            + time_rec_cols
            + ["状态"]
        )
        pred_columns = (
            ["请求行号"]
            + [f"预测{col}" for col in roles.output]
            + [f"偏差{col}" for col in roles.output]
            + ["总残差σ"]
            + [f"可达{col}" for col in roles.output]
        )
        reach_columns = ["请求行号", "Output", "可达下限", "可达上限", "目标", "是否在内"]

        model_choice = (
            {out_col: "rate" for out_col in roles.output}
            if is_rate
            else dict(zip(roles.output, forward.choice, strict=True))
        )
        rate_feature_choice = (
            dict(zip(roles.output, forward.feature_choice, strict=True)) if is_rate else None
        )
        return AnalysisResult(
            task=task,
            tables={
                "recommendations": pd.DataFrame(recommendation_rows, columns=rec_columns),
                "predictions": pd.DataFrame(prediction_rows, columns=pred_columns),
                "model_quality": quality,
                "reachable_ranges": pd.DataFrame(reachable_rows, columns=reach_columns),
                "model_equations": equations,
            },
            figures=[
                _figure_parameter_comparison(history, bounds, roles, recommendation_rows),
                _figure_residuals(prediction_rows, roles.output, attain_tol),
            ],
            summary=summary,
            metadata={
                "n_history": int(len(history)),
                "n_request": int(len(request)),
                "n_skipped": int(len(skipped) + n_failed),
                "model_choice": model_choice,
                "rate_feature_choice": rate_feature_choice,
                "bounds": {name: [float(pair[0]), float(pair[1])] for name, pair in bounds.items()},
                "time_adjustable": bool(time_adjustable),
                "time_stats": time_stats,
                "residual_summary": {
                    "n_solved": n_solved,
                    "n_reachable": n_reachable,
                    "n_at_bound": at_bound_total,
                    "mean_abs_sigma": round(float(np.mean(all_sigmas)), 4) if all_sigmas else None,
                    "max_abs_sigma": round(float(np.max(all_sigmas)), 4) if all_sigmas else None,
                    "bottleneck_output": bottleneck,
                },
                "seed": seed,
            },
            messages=messages,
        )
    except ValueError as exc:
        return AnalysisResult(
            task=task,
            status="error",
            messages=[*messages, str(exc)],
        )
