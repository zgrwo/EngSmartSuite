"""共享助手：跨模块复用的效应量/CI/分组解析工具。"""

import numpy as np
from scipy import stats as sp_stats

from smartsuite.engine._constants import (
    CLIFFS_DELTA_LARGE,
    CLIFFS_DELTA_MEDIUM,
    CLIFFS_DELTA_SMALL,
    COHENS_D_LARGE,
    COHENS_D_MEDIUM,
    COHENS_D_SMALL,
    CORRELATION_LARGE,
    CORRELATION_MEDIUM,
    CORRELATION_SMALL,
    ETA_SQ_LARGE,
    ETA_SQ_MEDIUM,
    ETA_SQ_SMALL,
)
from smartsuite.engine._utils import threshold_label


def _safe_int(value, default=None):
    """安全转换整数参数（CLI/YAML 字符串防护），失败返回 default。

    审查 2026-09-22 发现 5：`int(float('inf'))` 抛 OverflowError（不属于
    ValueError/TypeError），此前穿透参数守卫被 orchestrator 泛化翻译为
    「数值溢出，数据中可能存在极端值」——与用户参数错误无关。
    """
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def _effect_interpretation(eta2):
    """η² 效应量解读 (Cohen 准则)。"""
    return threshold_label(eta2, [ETA_SQ_SMALL, ETA_SQ_MEDIUM, ETA_SQ_LARGE])


def _effect_size_label(d, test_type="cohens_d"):
    """效应量大小解读标签（Cohen's d 使用 _constants.py 阈值）。"""
    ad = abs(d)
    if test_type == "cohens_d":
        return threshold_label(ad, [COHENS_D_SMALL, COHENS_D_MEDIUM, COHENS_D_LARGE])
    if test_type == "correlation":
        return threshold_label(ad, [CORRELATION_SMALL, CORRELATION_MEDIUM, CORRELATION_LARGE])
    # cliffs_delta
    return threshold_label(ad, [CLIFFS_DELTA_SMALL, CLIFFS_DELTA_MEDIUM, CLIFFS_DELTA_LARGE])


def _correlation_ci(r: float, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Pearson r 的 95% CI（Fisher z 变换法）。"""
    if n < 4 or abs(r) >= 1.0:
        return (float("nan"), float("nan"))
    z = np.arctanh(np.clip(r, -0.9999, 0.9999))
    se = 1.0 / np.sqrt(n - 3)
    z_crit = sp_stats.norm.ppf(1 - alpha / 2)
    lo = np.tanh(z - z_crit * se)
    hi = np.tanh(z + z_crit * se)
    return (float(lo), float(hi))
