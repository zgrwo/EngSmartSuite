"""工艺参数反解模块：列角色识别、前向建模与约束求解。"""

import json
import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution, minimize
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
    INVERSE_DE_MAXITER,
    INVERSE_DE_POPSIZE,
    INVERSE_LAM_TIME,
    INVERSE_RATE_MIN_ROWS,
    INVERSE_RATE_RIDGE_ALPHA_MAX,
    INVERSE_RATE_RIDGE_ALPHA_MIN,
    INVERSE_RATE_RIDGE_ALPHA_N,
    INVERSE_REG_LAMBDA,
)
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
    时间列仅在 `time_adjustable=true` 时纳入，边界取 `time_min/time_max`
    （空字符串或缺失时回退历史 min/max）。候选区间宽度为 0 的参数视为
    常数，不参与优化并记录警告。
    """
    explicit = _safe_json_dict(params.get("variable_bounds"), "variable_bounds")
    unknown = [key for key in explicit if key not in roles.variable]
    if unknown:
        logger.warning("variable_bounds 中的参数不在可调列中，已忽略: %s", unknown)
    bounds: dict[str, tuple[float, float]] = {}
    for col in roles.variable:
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
    if roles.time and _as_bool(params.get("time_adjustable"), False):
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
