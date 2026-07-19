"""引擎层共享工具函数。

本模块存放被多个引擎子模块（root_cause, doe_opt, spc_monitor）共同使用的
通用工具函数，避免代码重复和跨子模块导入。
"""
import logging

import numpy as np

from smartsuite.engine._constants import EPSILON

logger = logging.getLogger(__name__)


def safe_float(value, default: float) -> float:
    """安全转换参数值为 float，防御 CLI/YAML 字符串参数导致的 TypeError。

    所有从 req.params 提取数值参数的位置均应使用此函数，
    避免 `"0.05" < 0.05` 之类的类型比较崩溃。

    Args:
        value: 待转换的值（可能为 None、str、int、float 等）
        default: 转换失败时返回的默认值

    Returns:
        转换后的 float 值，或 default
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.debug("参数值转换失败: %r → 使用默认值 %s", value, default)
        return default


def threshold_label(value, thresholds, labels=("可忽略", "小", "中", "大")):
    """通用效应量阈值标签函数。

    跨模块共享工具：被 root_cause.py 和 doe_opt.py 调用。

    Args:
        value: 待判定的效应量值
        thresholds: 升序阈值列表，如 [0.01, 0.06, 0.14]
        labels: 对应标签元组，比 thresholds 多一个元素

    Returns:
        效应量等级标签字符串
    """
    if not np.isfinite(value):
        return "N/A"
    for t, label in zip(thresholds, labels, strict=False):
        if value < t:
            return label
    return labels[-1]


def durbin_watson(residuals):
    """Durbin-Watson 统计量 — 检测残差一阶自相关。

    跨模块共享工具：被 doe_opt.py (regression_analysis) 和 spc_monitor.py (trend_forecast) 调用。

    Args:
        residuals: 残差数组

    Returns:
        DW 统计量 (0-4)，接近 2 表示无自相关

    Raises:
        ValueError: 残差数量不足 2 个
    """
    if len(residuals) < 2:
        raise ValueError(
            f"Durbin-Watson 统计量需要至少 2 个残差值，当前仅有 {len(residuals)} 个。"
            f"请确保回归模型有足够的观测数据。"
        )
    diff = np.diff(residuals)
    dw = np.sum(diff**2) / (np.sum(residuals**2) + EPSILON)
    return float(dw)
