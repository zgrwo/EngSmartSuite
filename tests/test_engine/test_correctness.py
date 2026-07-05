"""统计正确性回归测试 — 使用已知标准答案验证引擎计算的准确性。"""
import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt import regression_analysis
from smartsuite.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    hypothesis_test,
)
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


# ── Lasso 回归正确性 ──

def test_lasso_shrinks_coefficients():
    """Lasso 应能将冗余变量的系数压缩到零。"""
    from smartsuite.engine.doe_opt import lasso_regression
    np.random.seed(42)
    n = 200
    x1 = np.random.normal(0, 1, n)
    x2 = x1 + np.random.normal(0, 0.01, n)  # 与 x1 几乎共线
    x3 = np.random.normal(0, 1, n)
    y = 3.0 * x1 + 0.0 * x2 + 1.5 * x3 + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3, "y": y})
    req = AnalysisRequest(task="lasso_regression", data=df, target_col="y",
                          feature_cols=["x1", "x2", "x3"])
    result = lasso_regression(req)
    assert result.status == "ok"
    # Lasso 应选中 x1 和 x3，但 x2 可能被压缩（接近零或未选中）
    coef = result.tables["coefficients"]
    x2_row = coef[coef["变量"] == "x2"]
    x2_coef = float(x2_row["标准化系数"].iloc[0])
    # x2 系数应显著小于 x1
    x1_coef = float(coef[coef["变量"] == "x1"]["标准化系数"].iloc[0])
    assert abs(x2_coef) < abs(x1_coef) * 0.5, (
        f"Lasso 应将共线变量 x2 系数压缩，x1={x1_coef:.3f}, x2={x2_coef:.3f}"
    )
    assert result.metadata["n_selected"] >= 2  # 至少选 x1 和 x3


# ── 稳健回归正确性 ──

def test_robust_resists_outliers():
    """Huber 回归在有异常值时系数应比 OLS 更接近真实值。"""
    from smartsuite.engine.doe_opt import robust_regression
    np.random.seed(42)
    n = 100
    x = np.random.uniform(0, 10, n)
    y_true = 2.0 + 3.0 * x
    y = y_true + np.random.normal(0, 1, n)
    # 注入 5 个极端异常值
    y[-5:] += 50.0
    df = pd.DataFrame({"x": x, "y": y})
    req = AnalysisRequest(task="robust_regression", data=df, target_col="y",
                          feature_cols=["x"])
    result = robust_regression(req)
    assert result.status == "ok"
    coef = result.tables["coefficient_comparison"]
    huber_slope = float(coef[coef["变量"] == "x"]["Huber系数"].iloc[0])
    ols_slope = float(coef[coef["变量"] == "x"]["OLS系数"].iloc[0])
    # Huber 斜率应比 OLS 更接近真值 3.0
    assert abs(huber_slope - 3.0) < abs(ols_slope - 3.0), (
        f"Huber 应对异常值不敏感: Huber={huber_slope:.3f}, OLS={ols_slope:.3f}, true=3.0"
    )


# ── 网格搜索正确性 ──

def test_grid_search_finds_optimum():
    """网格搜索应在已知线性趋势下找到正确的最优方向。"""
    from smartsuite.engine.doe_opt import grid_search
    np.random.seed(42)
    n = 100
    x1 = np.random.uniform(-5, 5, n)
    # y = 3*x1 + noise → 最大化时 x1 应取最大值
    y = 3.0 * x1 + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({"x1": x1, "y": y})
    req = AnalysisRequest(task="grid_search", data=df, target_col="y",
                          feature_cols=["x1"],
                          params={"ranges": {"x1": (-5, 5)},
                                  "n_points": 20, "direction": "maximize"})
    result = grid_search(req)
    assert result.status == "ok"
    optimal = result.metadata["optimal_params"]
    # 线性趋势下，最大化方向 x1 应接近上界 5
    assert optimal["x1"] > 2.0, f"x1 应在正方向, 实际={optimal['x1']}"
    assert result.metadata["optimal_value"] > 5.0, "预测最优值应显著大于均值"


# ── 多目标优化正确性 ──

def test_multi_objective_correct_ranking():
    """多目标优化应对两个目标正确加权排序。"""
    from smartsuite.engine.doe_opt import multi_objective_opt
    np.random.seed(42)
    n = 50
    df = pd.DataFrame({
        "param1": np.random.uniform(0, 10, n),
        "param2": np.random.uniform(0, 10, n),
        "strength": np.random.normal(45, 5, n),    # 越大越好
        "defect": np.random.normal(2, 0.5, n),      # 越小越好
    })
    # 人为制造一个明显最优：param1=5, param2=5 时 strength=max, defect=min
    best_idx = 25
    df.loc[best_idx, "strength"] = 60.0
    df.loc[best_idx, "defect"] = 0.1
    df.loc[best_idx, "param1"] = 5.0
    df.loc[best_idx, "param2"] = 5.0

    req = AnalysisRequest(task="multi_objective", data=df, target_col="",
                          feature_cols=["param1", "param2"],
                          params={"objectives": [
                              {"col": "strength", "direction": "maximize"},
                              {"col": "defect", "direction": "minimize"},
                          ], "weights": [1.0, 1.0]})
    result = multi_objective_opt(req)
    assert result.status == "ok"
    optimal = result.metadata["optimal_params"]
    # 最优方案 param1 应接近 5
    assert 4.0 < optimal["param1"] < 6.0, f"最优 param1 应接近 5, 实际={optimal['param1']}"


# ── 分位数回归正确性 ──

def test_quantile_regression_median():
    """中位数回归应在对称分布下给出与 OLS 接近的系数。"""
    from smartsuite.engine.doe_opt import quantile_regression
    np.random.seed(42)
    n = 200
    x = np.random.uniform(0, 10, n)
    y = 2.0 + 3.0 * x + np.random.normal(0, 1, n)
    df = pd.DataFrame({"x": x, "y": y})
    req = AnalysisRequest(task="quantile_regression", data=df, target_col="y",
                          feature_cols=["x"], params={"quantile": 0.5})
    result = quantile_regression(req)
    assert result.status == "ok"
    coef = result.tables["coefficients"]
    x_row = coef[coef["变量"] == "x"]
    beta_x = float(x_row["系数"].iloc[0])
    # 中位数回归斜率应接近 3.0
    assert 2.6 < beta_x < 3.4, f"中位数回归斜率应接近 3.0, 实际={beta_x:.3f}"


# ── 属性控制图边缘情况 ──

def test_attribute_chart_types():
    """p/np/c/u 四种属性控制图均应正常返回。"""
    from smartsuite.engine.spc_monitor import attribute_chart
    np.random.seed(42)

    # p-chart: 不良率数据
    df_p = pd.DataFrame({
        "batch": np.repeat(range(1, 21), 50),
        "defect": np.random.binomial(1, 0.05, 1000),
    })
    req = AnalysisRequest(task="spc_attribute", data=df_p, target_col="defect",
                          params={"chart_type": "p", "subgroup_col": "batch"})
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "p"

    # c-chart: 缺陷数数据
    df_c = pd.DataFrame({
        "unit": range(1, 26),
        "defects": np.random.poisson(4, 25),
    })
    req = AnalysisRequest(task="spc_attribute", data=df_c, target_col="defects",
                          params={"chart_type": "c"})
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "c"

    # u-chart: 单位缺陷率
    df_u = pd.DataFrame({
        "batch": np.repeat(range(1, 16), 2),
        "defects": np.random.poisson(2, 30),
    })
    req = AnalysisRequest(task="spc_attribute", data=df_u, target_col="defects",
                          params={"chart_type": "u", "subgroup_col": "batch"})
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "u"

    # np-chart: 不良数（固定样本量）
    df_np = pd.DataFrame({
        "batch": np.repeat(range(1, 21), 50),
        "defect": np.random.binomial(1, 0.05, 1000),
    })
    req = AnalysisRequest(task="spc_attribute", data=df_np, target_col="defect",
                          params={"chart_type": "np", "subgroup_col": "batch"})
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "np"
    # np-chart 应在合理范围内
    assert 1 <= r.metadata["n_subgroups"] <= 30


# ── SPC X-bar/R 控制图正确性 ──

def test_xbar_r_known_limits():
    """X-bar/R: 已知 μ=10, σ=1 的子组应产生接近的控制限。"""
    from smartsuite.engine.spc_monitor import xbar_r_chart
    np.random.seed(42)
    # 10 个子组，每个 5 个样本，μ=10, σ=1
    data = []
    for sg in range(1, 11):
        for _ in range(5):
            data.append({"子组": sg, "val": np.random.normal(10, 1)})
    df = pd.DataFrame(data)
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="val",
                          params={"subgroup_col": "子组"})
    r = xbar_r_chart(req)
    assert r.status == "ok"
    # 控制限应在合理范围 (CL≈10, UCL>10, LCL<10)
    cl = r.metadata["xbar_mean"]
    ucl = r.metadata["ucl_x"]
    lcl = r.metadata["lcl_x"]
    assert 9.0 < cl < 11.0, f"X-bar CL={cl:.2f}, expected ~10"
    assert ucl > cl, f"UCL={ucl:.3f} should be > CL={cl:.3f}"
    assert lcl < cl, f"LCL={lcl:.3f} should be < CL={cl:.3f}"
    # 子组大小 n=5 应匹配
    assert r.metadata["subgroup_size"] == 5


# ── 生存分析正确性 ──

def test_survival_km_known_median():
    """Kaplan-Meier: 已知指数分布 (λ=0.1) 的寿命数据，中位生存 ≈ ln(2)/λ ≈ 6.93。"""
    from smartsuite.engine.spc_monitor import survival_analysis
    np.random.seed(42)
    n = 200
    times = np.random.exponential(10, n)  # 均值=10, 中位≈6.93
    events = np.ones(n)  # 全部失效，无删失
    df = pd.DataFrame({"time": times, "event": events})
    req = AnalysisRequest(task="survival_analysis", data=df, target_col="time",
                          feature_cols=["event"])
    r = survival_analysis(req)
    assert r.status == "ok"
    median = r.metadata["median_survival"]
    assert median is not None, "应能计算中位生存时间"
    # 指数分布 μ=10, 中位 ≈ 6.93, 允许 ±3
    assert 4 < median < 10, f"中位生存={median:.1f}, expected ~7"


# ── CUSUM 正确性 ──

def test_cusum_no_shift():
    """CUSUM: 稳定过程不应产生违规。"""
    from smartsuite.engine.spc_monitor import cusum_chart
    np.random.seed(42)
    df = pd.DataFrame({"val": np.random.normal(10, 1, 100)})
    req = AnalysisRequest(task="spc_cusum", data=df, target_col="val",
                          params={"k": 0.5, "h": 5.0})
    r = cusum_chart(req)
    assert r.status == "ok"
    # 稳定过程的 CUSUM 不应触发违规（h=5 是宽松阈值）
    violations = r.metadata.get("violations", [])
    n_v = len(violations) if isinstance(violations, (list, dict)) else 0
    assert n_v <= 5, f"稳定过程 CUSUM 违规过多: {n_v}"


# ── 列联表 / 卡方正确性 ──

def test_contingency_known_chi2():
    """列联表: 已知关联的数据应产生显著的卡方 p 值。"""
    from smartsuite.engine.root_cause import contingency_analysis
    np.random.seed(42)
    # 构造强关联的 2x2 表: A→X, B→Y
    df = pd.DataFrame({
        "factor": ["A"] * 80 + ["A"] * 20 + ["B"] * 30 + ["B"] * 70,
        "outcome": ["X"] * 80 + ["Y"] * 20 + ["X"] * 30 + ["Y"] * 70,
    })
    req = AnalysisRequest(task="contingency", data=df, target_col="factor",
                          feature_cols=["outcome"])
    r = contingency_analysis(req)
    assert r.status == "ok"
    p_val = r.metadata["p_value"]
    # 强关联应显著
    assert p_val < 0.001, f"Expected p<0.001 for strong association, got p={p_val:.4f}"
    # Cramér's V 应在 0.2-0.6
    if "effect" in r.metadata and r.metadata["effect"] is not None:
        assert 0.2 < r.metadata["effect"] < 0.6, f"Cramér's V={r.metadata['effect']:.3f}"
