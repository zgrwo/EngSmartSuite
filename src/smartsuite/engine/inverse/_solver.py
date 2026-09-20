"""单条请求求解与可达性采样（原 inverse.py，2026-09-21 拆分）。"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution, minimize
from scipy.stats import qmc

from smartsuite.engine._constants import (
    INVERSE_DE_MAXITER,
    INVERSE_DE_POPSIZE,
    INVERSE_LAM_TIME,
    INVERSE_MAX_STARTS,
    INVERSE_REG_LAMBDA,
)
from smartsuite.engine._utils import safe_float
from smartsuite.engine.inverse._bounds import (
    _bound_value,
    _sanitize_scale,
    _sanitize_weights,
    _time_anchor,
)
from smartsuite.engine.inverse._models import RateForwardModel, _rate_feature_value
from smartsuite.engine.inverse._params import _DEFAULT_MAX_STARTS

logger = logging.getLogger(__name__)


def _optimal_time(forward, incoming, target, scale, weights, u, time_bounds) -> float:
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


def _solve_one(forward, incoming_row, target, scale, weights, bounds, baseline, params):
    """对单条请求行反解可调参数（rate 模型含解析时间）。

    目标函数：Σ_j w_j·((ŷ_j−y*_j)/s_j)² + reg_lambda·Σ_k ((u_k−u0_k)/range_k)²。
    参数合同：`scale` 为 weight_mode 尺度（**不含** output_weights），
    `weights` 为 output_weights（默认 1.0），二者相乘构成目标权重 w_j；
    与 `_optimal_time` 的传入口径一致，调用方不得在 scale 中重复乘 output_weights。
    平滑模型用 L-BFGS-B 多起点（基准点 + max_starts-1 个随机起点，种子固定）；
    树模型用 differential_evolution + L-BFGS-B polish；rate 模型的时间按
    `_optimal_time` 解析求解（bounds 含 time 时）。宽度为 0 的参数按常数处理。

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
    max_starts = min(
        max(int(safe_float(params.get("max_starts"), _DEFAULT_MAX_STARTS)), 1),
        INVERSE_MAX_STARTS,
    )
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
                time_value = _optimal_time(
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
        fast = getattr(forward, "fast", None)
        if fast is not None and all(predictor is not None for predictor in fast):
            values = np.asarray([[row[col] for col in forward.feature_cols]], dtype=float)
            pred = np.asarray(
                [float(np.ravel(predictor(values))[0]) for predictor in fast], dtype=float
            )
            return pred, None
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
        assert time_col is not None  # time_value 由 time_col 模型产出
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
    info: dict[str, Any] = {
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


def _reachable_range(forward, incoming_row, bounds, n, seed, time_bounds=None):
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
            （镜像 `_solve_one`），否则时间取 incoming_row 固定值并记录警告。

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
