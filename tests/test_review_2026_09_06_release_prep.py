"""审查 2026-09-06 发版前修复回归（B3 / R4-1）。

B3：detection.py `_acf_values` 分母保护 `denom <= 1e-12` 为量纲绑定绝对判据，
微尺度残差（~1e-13，纳米/微应变数据）恒命中退化分支，AR(1) 真实自相关
[1, 0.45, 0.211] 被静默吞为 [1, 0, 0]（trend_forecast 的 DW/Ljung-Box 随之误判）。
修复：改为相对判据 `denom <= 1e-12 * max(Σx², 1e-300)`（与 exploratory.py ssx 同族）。

R4-1：doe_opt.py lasso_regression 以绝对阈值 `abs(coef) > 1e-6` 标注「选中」，
系数带 y 量纲（模型拟合于 X_scaled、y 未标准化），微尺度目标列（y~1e-10）
系数 ~1e-9 整表误标「否」，输出「选中 0/2 变量, R²=0.99」的自相矛盾结论。
修复：改为相对判据 `abs(coef) > 1e-6 * max(abs(coefs))`（与 B1/B3 同族）。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.detection import _acf_values
from smartsuite.engine.doe_opt import lasso_regression


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


# ── R4-1：lasso 标准化系数 1e-6 绝对阈值相对化 ──
def test_lasso_micro_scale_selection_not_swallowed():
    """微尺度目标列（y~1e-10）：变量选择标注不得整表「否」（审查 R4-1）。

    同结构数据 ×1e-10（纳米/微应变量纲）下 Lasso 拟合正常（R²≈0.99），
    系数 ~1e-9 被旧绝对阈值 1e-6 全部标「否」；相对化后选择结果应与
    常态量纲一致（尺度不变），且「选中」列与 summary 自洽。
    """
    rng = np.random.RandomState(42)
    n = 60
    x1 = rng.normal(50, 5, n)
    x2 = rng.normal(20, 4, n)
    noise = rng.normal(0, 1, n)

    for scale in (1.0, 1e-10):
        df = pd.DataFrame({"x1": x1, "x2": x2, "y": (2 * x1 - 1.5 * x2 + noise) * scale})
        req = AnalysisRequest(
            task="lasso_regression", data=df, target_col="y", feature_cols=["x1", "x2"]
        )
        r = lasso_regression(req)
        assert r.status == "ok", r.messages
        coef = r.tables["coefficients"]
        sel = coef[coef["变量"] != "(截距)"]["选中"]
        n_sel = int((sel == "是").sum())
        assert n_sel >= 1, f"scale={scale:g}: 全部变量被标「否」: {sel.tolist()}"
        # 标注与 summary 自洽（表格「是」行数 == summary 报告的选中数）
        assert f"选中 {n_sel}/" in r.summary, f"scale={scale:g}: summary={r.summary!r}"
