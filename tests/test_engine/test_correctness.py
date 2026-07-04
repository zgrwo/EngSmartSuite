"""统计正确性回归测试 — 使用已知标准答案验证引擎计算的准确性。"""
import numpy as np
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause import (
    correlation_analysis, anova_analysis, hypothesis_test, vif_analysis,
)
from smartsuite.engine.doe_opt import regression_analysis
from smartsuite.engine.spc_monitor import process_capability_analysis


def test_correlation_known_r():
    """验证 Pearson 相关：已知 r≈0.9 的数据应输出接近 0.9 的相关系数。"""
    np.random.seed(42)
    n = 500
    x = np.random.normal(0, 1, n)
    # y = 0.9 * x + noise → r should be close to 0.9/sqrt(0.81 + 0.19) ≈ 0.9
    y = 0.9 * x + np.random.normal(0, np.sqrt(1 - 0.9**2), n)
    df = pd.DataFrame({"x": x, "y": y})

    req = AnalysisRequest(task="correlation", data=df, target_col="y", feature_cols=["x"])
    result = correlation_analysis(req)
    assert result.status == "ok"
    r = result.tables["correlation_matrix"].loc["y", "x"]
    assert 0.85 < r < 0.95, f"Expected r≈0.9, got {r:.4f}"


def test_regression_known_slope():
    """验证回归：已知 y = 3.0 + 2.5*x + ε 应恢复接近的系数。"""
    np.random.seed(123)
    n = 200
    x = np.random.uniform(0, 10, n)
    y = 3.0 + 2.5 * x + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({"x": x, "y": y})

    req = AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
    result = regression_analysis(req)
    assert result.status == "ok"
    coef = result.tables["coefficients"]
    const_row = coef[coef["变量"] == "const"]
    x_row = coef[coef["变量"] == "x"]
    beta_const = float(const_row["系数"].iloc[0])
    beta_x = float(x_row["系数"].iloc[0])
    assert 2.8 < beta_const < 3.2, f"Expected intercept≈3.0, got {beta_const:.3f}"
    assert 2.45 < beta_x < 2.55, f"Expected slope≈2.5, got {beta_x:.3f}"


def test_hypothesis_known_difference():
    """验证 t 检验：已知均值差 2.0 的数据应检测出显著差异。"""
    np.random.seed(42)
    n = 100
    g1 = np.random.normal(10, 1, n)
    g2 = np.random.normal(12, 1, n)  # 均值差 = 2
    df = pd.DataFrame({
        "group": ["A"] * n + ["B"] * n,
        "val": np.concatenate([g1, g2]),
    })
    req = AnalysisRequest(
        task="hypothesis_test", data=df, target_col="val",
        feature_cols=["group"], params={"group_col": "group"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok"
    p = result.metadata["p_value"]
    assert p < 0.001, f"Expected p<<0.001 for Δμ=2, got p={p:.6f}"


def test_process_capability_known_cpk():
    """验证过程能力：μ=10, σ=1, USL=14, LSL=6 → Cpk≈1.33。"""
    np.random.seed(42)
    n = 1000
    data = np.random.normal(10, 1, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(
        task="process_capability", data=df, target_col="val",
        params={"usl": 14.0, "lsl": 6.0},
    )
    result = process_capability_analysis(req)
    assert result.status == "ok"
    cpk = result.metadata["cpk"]
    # 理论 Cpk = min(14-10, 10-6) / (3*1) = 4/3 ≈ 1.33
    assert 1.2 < cpk < 1.5, f"Expected Cpk≈1.33, got {cpk:.3f}"


def test_anova_known_group_diff():
    """验证 ANOVA：三组有明显差异时应检测出显著因子。"""
    np.random.seed(42)
    n = 30
    df = pd.DataFrame({
        "group": ["A"] * n + ["B"] * n + ["C"] * n,
        "val": np.concatenate([
            np.random.normal(10, 1, n),
            np.random.normal(13, 1, n),
            np.random.normal(16, 1, n),
        ]),
    })
    req = AnalysisRequest(
        task="anova", data=df, target_col="val", feature_cols=["group"],
    )
    result = anova_analysis(req)
    assert result.status == "ok"
    # 三组均值差很大，R² 应该很高
    assert result.metadata["r_squared"] > 0.7, (
        f"Expected R²>0.7, got {result.metadata['r_squared']:.3f}"
    )
