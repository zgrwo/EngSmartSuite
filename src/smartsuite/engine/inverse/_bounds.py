"""边界、尺度与权重的规整（原 inverse.py，2026-09-21 拆分）。"""

import json
import logging

import numpy as np
import pandas as pd

from smartsuite.engine._utils import safe_float

logger = logging.getLogger(__name__)


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


def _resolve_bounds(history, roles, params) -> dict[str, tuple[float, float]]:
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
