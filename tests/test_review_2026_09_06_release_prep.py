"""审查 2026-09-06 发版前修复回归（B3）。

历史：detection.py `_acf_values` 分母保护 `denom <= 1e-12` 为量纲绑定绝对判据，
微尺度残差（~1e-13，纳米/微应变数据）恒命中退化分支，AR(1) 真实自相关
[1, 0.45, 0.211] 被静默吞为 [1, 0, 0]（trend_forecast 的 DW/Ljung-Box 随之误判）。
修复：改为相对判据 `denom <= 1e-12 * max(Σx², 1e-300)`（与 exploratory.py ssx 同族）。
"""

import numpy as np
import pytest

from smartsuite.engine.detection import _acf_values


def _ar1_residuals(n=200, phi=0.5, seed=3):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, n)
    ar = np.empty(n)
    ar[0] = noise[0]
    for i in range(1, n):
        ar[i] = phi * ar[i - 1] + noise[i]
    return ar


def test_acf_micro_scale_ar1_not_degenerate():
    """微尺度（1e-13）AR(1) 残差给出真实自相关，与常态量纲尺度无关。"""
    ar = _ar1_residuals()
    micro = _acf_values(ar * 1e-13, max_lag=5)
    normal = _acf_values(ar, max_lag=5)
    # 尺度不变性：同形状数据仅量纲不同 → ACF 逐项一致
    assert micro == pytest.approx(normal, rel=1e-9, abs=1e-12)
    # 真实自相关（φ=0.5 → 理论 0.5/0.25；n=200 seed=3 实测 ≈0.45/0.211，scipy 独立参考一致）
    assert micro[1] == pytest.approx(0.45, abs=0.06)
    assert micro[2] == pytest.approx(0.211, abs=0.06)


def test_acf_true_constant_residuals_still_degenerate():
    """真常量残差（任意量纲）仍命中退化分支 [1,0,...]，防零方差除零。"""
    for scale in (1e-10, 1.0):
        const = np.full(50, 3.7 * scale)
        acf = _acf_values(const, max_lag=5)
        assert acf[0] == 1.0
        assert acf[1:] == [0.0] * 5


def test_acf_all_zero_residuals():
    """全零残差：denom=0 且 Σx²=0 → 走 max(…, 1e-300) 下限，退化分支不除零。"""
    acf = _acf_values(np.zeros(30), max_lag=3)
    assert acf == [1.0, 0.0, 0.0, 0.0]
