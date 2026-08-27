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
from smartsuite.engine.spc_monitor import (
    anomaly_detect,
    attribute_chart,
    bootstrap_ci,
    change_point_detect,
    ewma_chart,
    gage_rr,
    median_ci,
    process_capability_analysis,
    scatter_plot,
    spc_nonparametric,
    tolerance_interval,
    trend_forecast,
)


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
    df = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n,
            "val": np.concatenate([g1, g2]),
        }
    )
    req = AnalysisRequest(
        task="hypothesis_test",
        data=df,
        target_col="val",
        feature_cols=["group"],
        params={"group_col": "group"},
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
        task="process_capability",
        data=df,
        target_col="val",
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
    df = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n + ["C"] * n,
            "val": np.concatenate(
                [
                    np.random.normal(10, 1, n),
                    np.random.normal(13, 1, n),
                    np.random.normal(16, 1, n),
                ]
            ),
        }
    )
    req = AnalysisRequest(
        task="anova",
        data=df,
        target_col="val",
        feature_cols=["group"],
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
    req = AnalysisRequest(
        task="lasso_regression", data=df, target_col="y", feature_cols=["x1", "x2", "x3"]
    )
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
    req = AnalysisRequest(task="robust_regression", data=df, target_col="y", feature_cols=["x"])
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
    req = AnalysisRequest(
        task="grid_search",
        data=df,
        target_col="y",
        feature_cols=["x1"],
        params={"ranges": {"x1": (-5, 5)}, "n_points": 20, "direction": "maximize"},
    )
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
    df = pd.DataFrame(
        {
            "param1": np.random.uniform(0, 10, n),
            "param2": np.random.uniform(0, 10, n),
            "strength": np.random.normal(45, 5, n),  # 越大越好
            "defect": np.random.normal(2, 0.5, n),  # 越小越好
        }
    )
    # 人为制造一个明显最优：param1=5, param2=5 时 strength=max, defect=min
    best_idx = 25
    df.loc[best_idx, "strength"] = 60.0
    df.loc[best_idx, "defect"] = 0.1
    df.loc[best_idx, "param1"] = 5.0
    df.loc[best_idx, "param2"] = 5.0

    req = AnalysisRequest(
        task="multi_objective",
        data=df,
        target_col="",
        feature_cols=["param1", "param2"],
        params={
            "objectives": [
                {"col": "strength", "direction": "maximize"},
                {"col": "defect", "direction": "minimize"},
            ],
            "weights": [1.0, 1.0],
        },
    )
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
    req = AnalysisRequest(
        task="quantile_regression",
        data=df,
        target_col="y",
        feature_cols=["x"],
        params={"quantile": 0.5},
    )
    result = quantile_regression(req)
    assert result.status == "ok"
    coef = result.tables["coefficients"]
    x_row = coef[coef["变量"] == "x"]
    beta_x = float(x_row["系数"].iloc[0])
    # 中位数回归斜率应接近 3.0
    assert 2.6 < beta_x < 3.4, f"中位数回归斜率应接近 3.0, 实际={beta_x:.3f}"


# ── 属性控制图边缘情况 ──


def test_attribute_chart_types():
    """p/np/c/u 四种属性控制图均应正常返回 + p/c 图中心线数值正确。"""
    np.random.seed(42)

    # ── p-chart: 不良率 p=0.05, n=50 常数样本量 ──
    df_p = pd.DataFrame(
        {
            "batch": np.repeat(range(1, 21), 50),
            "defect": np.random.binomial(1, 0.05, 1000),
        }
    )
    req = AnalysisRequest(
        task="spc_attribute",
        data=df_p,
        target_col="defect",
        feature_cols=["batch"],
        params={"chart_type": "p"},
    )
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "p"
    # p-chart: CL = p_bar ≈ 0.05 (允许 ±0.02)
    cl_p = r.metadata["cl"]
    assert 0.03 < cl_p < 0.07, f"p-chart CL 应接近 0.05, 实际={cl_p:.4f}"

    # ── c-chart: 缺陷数 λ=4 ──
    df_c = pd.DataFrame(
        {
            "unit": range(1, 26),
            "defects": np.random.poisson(4, 25),
        }
    )
    req = AnalysisRequest(
        task="spc_attribute", data=df_c, target_col="defects", params={"chart_type": "c"}
    )
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "c"
    # c-chart: CL = c_bar ≈ 4 (允许 ±1)
    cl_c = r.metadata["cl"]
    assert 3.0 < cl_c < 5.0, f"c-chart CL 应接近 4, 实际={cl_c:.4f}"

    # ── u-chart: 单位缺陷率 ──
    df_u = pd.DataFrame(
        {
            "batch": np.repeat(range(1, 16), 2),
            "defects": np.random.poisson(2, 30),
        }
    )
    req = AnalysisRequest(
        task="spc_attribute",
        data=df_u,
        target_col="defects",
        feature_cols=["batch"],
        params={"chart_type": "u"},
    )
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "u"

    # ── np-chart: 不良数（固定样本量） ──
    df_np = pd.DataFrame(
        {
            "batch": np.repeat(range(1, 21), 50),
            "defect": np.random.binomial(1, 0.05, 1000),
        }
    )
    req = AnalysisRequest(
        task="spc_attribute",
        data=df_np,
        target_col="defect",
        feature_cols=["batch"],
        params={"chart_type": "np"},
    )
    r = attribute_chart(req)
    assert r.status == "ok"
    assert r.metadata["chart_type"] == "np"
    assert 1 <= r.metadata["n_points"] <= 30


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
    req = AnalysisRequest(
        task="spc_xbar", data=df, target_col="val", feature_cols=["子组"], params={}
    )
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
    req = AnalysisRequest(
        task="survival_analysis", data=df, target_col="time", feature_cols=["event"]
    )
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
    req = AnalysisRequest(task="spc_cusum", data=df, target_col="val", params={"k": 0.5, "h": 5.0})
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
    df = pd.DataFrame(
        {
            "factor": ["A"] * 80 + ["A"] * 20 + ["B"] * 30 + ["B"] * 70,
            "outcome": ["X"] * 80 + ["Y"] * 20 + ["X"] * 30 + ["Y"] * 70,
        }
    )
    req = AnalysisRequest(
        task="contingency", data=df, target_col="factor", feature_cols=["outcome"]
    )
    r = contingency_analysis(req)
    assert r.status == "ok"
    p_val = r.metadata["p_value"]
    # 强关联应显著
    assert p_val < 0.001, f"Expected p<0.001 for strong association, got p={p_val:.4f}"
    # Cramér's V 应在 0.2-0.6
    if "effect" in r.metadata and r.metadata["effect"] is not None:
        assert 0.2 < r.metadata["effect"] < 0.6, f"Cramér's V={r.metadata['effect']:.3f}"


# ── EWMA 控制图正确性 ──


def test_ewma_chart_stable_data():
    """EWMA: 稳定正态数据下渐近控制限包含均值，λ=0.2 应无违规。"""
    np.random.seed(42)
    n = 200
    data = np.random.normal(10, 1, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(task="spc_ewma", data=df, target_col="val", params={"lam": 0.2, "L": 2.7})
    result = ewma_chart(req)
    assert result.status == "ok"
    mu = result.metadata["mu"]
    ucl = result.metadata["ucl_asym"]
    lcl = result.metadata["lcl_asym"]
    assert lcl < mu < ucl, f"EWMA 渐近控制限应包含均值: LCL={lcl:.3f}, μ={mu:.3f}, UCL={ucl:.3f}"
    # 稳定过程应极少违规（≤2 个）
    violations = result.metadata["violations"]
    assert violations <= 2, f"稳定过程 EWMA 违规应≤2, 实际={violations}"


# ── 非参数控制图正确性 ──


def test_spc_nonparametric_normal_limits():
    """非参数控制图: 正态数据下控制限应接近 ±3σ (μ±3σ)。"""
    np.random.seed(42)
    n = 500
    data = np.random.normal(10, 1, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(task="spc_nonparametric", data=df, target_col="val")
    result = spc_nonparametric(req)
    assert result.status == "ok"
    ucl = result.metadata["ucl"]
    lcl = result.metadata["lcl"]
    assert ucl is not None and lcl is not None, "双侧非参数控制图应有 UCL 和 LCL"
    # 正态数据下，UCL 应接近 10+3=13, LCL 应接近 10-3=7 (±1.5 容差)
    assert 11.5 < ucl < 14.5, f"UCL 应接近 13, 实际={ucl:.3f}"
    assert 5.5 < lcl < 8.5, f"LCL 应接近 7, 实际={lcl:.3f}"
    # 违规率应 < 1%
    assert result.metadata["n_violations"] <= 5, f"违规点过多: {result.metadata['n_violations']}"


# ── 趋势预测正确性 ──


def test_trend_forecast_known_slope():
    """趋势预测: y=10+0.5*t+ε 应恢复斜率≈0.5。"""
    np.random.seed(42)
    n = 100
    t = np.arange(n)
    y = 10.0 + 0.5 * t + np.random.normal(0, 1.0, n)
    df = pd.DataFrame({"t": t, "val": y})

    req = AnalysisRequest(
        task="trend_forecast", data=df, target_col="val", params={"forecast_steps": 5}
    )
    result = trend_forecast(req)
    assert result.status == "ok"
    slope = result.metadata["slope"]
    # 斜率应接近 0.5
    assert 0.40 < slope < 0.60, f"斜率应接近 0.5, 实际={slope:.4f}"
    # 线性趋势 R² 应较高
    assert result.metadata["r_squared"] > 0.85, (
        f"R² 应 > 0.85, 实际={result.metadata['r_squared']:.3f}"
    )


# ── 异常检测正确性 ──


def test_anomaly_detect_iqr():
    """异常检测: 干净数据标记≤5%; 注入3个极端离群值应全部检出。"""
    np.random.seed(42)
    n = 200
    data = np.random.normal(0, 1, n)
    df_clean = pd.DataFrame({"val": data})

    # Part 1: 干净数据 IQR 应标记 ≤5%
    req = AnalysisRequest(
        task="anomaly_detect", data=df_clean, target_col="val", params={"method": "iqr"}
    )
    result = anomaly_detect(req)
    assert result.status == "ok"
    anomaly_rate = result.metadata["anomaly_count"] / n
    assert anomaly_rate <= 0.05, f"干净数据 IQR 异常率应≤5%, 实际={anomaly_rate:.2%}"

    # Part 2: 注入 3 个极端离群值 (50, -50, 100)
    data_out = data.copy()
    data_out[0] = 50.0
    data_out[1] = -50.0
    data_out[2] = 100.0
    df_out = pd.DataFrame({"val": data_out})

    req2 = AnalysisRequest(
        task="anomaly_detect", data=df_out, target_col="val", params={"method": "iqr"}
    )
    result2 = anomaly_detect(req2)
    assert result2.status == "ok"
    assert result2.metadata["anomaly_count"] >= 3, (
        f"注入 3 个极端离群值至少应检出 3 个, 实际={result2.metadata['anomaly_count']}"
    )


# ── 变点检测正确性 ──


def test_change_point_detect_known_shift():
    """变点检测: 前50点 μ=10, 后50点 μ=18 应在位置~50检测到变点。"""
    np.random.seed(42)
    # 使用较大的均值偏移 (10→18) 确保变点信号强于随机波动
    first_half = np.random.normal(10, 1, 50)
    second_half = np.random.normal(18, 1, 50)
    data = np.concatenate([first_half, second_half])
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(
        task="change_point",
        data=df,
        target_col="val",
        params={"n_changepoints": 3, "min_segment": 10},
    )
    result = change_point_detect(req)
    assert result.status == "ok"
    assert result.metadata["n_changepoints"] >= 1, "应检测到至少 1 个变点"
    # 至少有一个变点接近位置 50 (±15)
    near_50 = any(abs(cp - 50) <= 15 for cp in result.metadata["changepoints"])
    assert near_50, f"应在位置 50±15 内检测到变点, 实际变点={result.metadata['changepoints']}"


# ── Bootstrap 置信区间正确性 ──


def test_bootstrap_ci_contains_mean():
    """Bootstrap CI: n=500 N(100,10) 的 95% CI 应包含真值 100。"""
    np.random.seed(42)
    n = 500
    true_mean = 100.0
    data = np.random.normal(true_mean, 10, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(
        task="bootstrap_ci",
        data=df,
        target_col="val",
        params={"statistic": "mean", "n_bootstrap": 2000, "ci_level": 0.95, "random_state": 42},
    )
    result = bootstrap_ci(req)
    assert result.status == "ok"
    ci_lower = result.metadata["ci_lower"]
    ci_upper = result.metadata["ci_upper"]
    assert ci_lower <= true_mean <= ci_upper, (
        f"95% Bootstrap CI [{ci_lower:.4f}, {ci_upper:.4f}] 应包含真值 {true_mean}"
    )
    point_est = result.metadata["point_estimate"]
    assert abs(point_est - true_mean) < 2.0, f"点估计应接近 {true_mean}, 实际={point_est:.3f}"


# ── 中位数置信区间正确性 ──


def test_median_ci_contains_zero():
    """中位数 CI: n=100 N(0,1) 的 95% CI 应包含 0。"""
    np.random.seed(42)
    n = 100
    data = np.random.normal(0, 1, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(task="median_ci", data=df, target_col="val", params={"ci_level": 0.95})
    result = median_ci(req)
    assert result.status == "ok"
    ci_lower = result.metadata["ci_lower"]
    ci_upper = result.metadata["ci_upper"]
    assert ci_lower <= 0 <= ci_upper, f"95% 中位数 CI [{ci_lower:.4f}, {ci_upper:.4f}] 应包含 0"
    median = result.metadata["median"]
    assert abs(median) < 0.5, f"中位数应接近 0, 实际={median:.4f}"


# ── Gage R&R 正确性 ──


def test_gage_rr_reasonable():
    """Gage R&R: 10部件×3操作员×2重复, %GRR<30%, 分量和一致。"""
    np.random.seed(42)

    n_parts = 10
    n_operators = 3
    n_reps = 2
    # 部件真实值有明显差异
    part_true = np.array([10, 12, 14, 16, 18, 20, 22, 24, 26, 28])

    rows = []
    for p_idx, p_true in enumerate(part_true):
        part_name = f"P{p_idx + 1}"
        for op_idx in range(n_operators):
            op_name = f"OP{op_idx + 1}"
            op_bias = (op_idx - 1) * 0.1  # 微小操作员偏差
            for rep in range(n_reps):
                measured = p_true + op_bias + np.random.normal(0, 0.15)
                rows.append({"部件": part_name, "操作员": op_name, "测量值": measured})

    df = pd.DataFrame(rows)

    req = AnalysisRequest(
        task="gage_rr",
        data=df,
        target_col="测量值",
        feature_cols=["部件", "操作员"],
        params={"part_col": "部件", "operator_col": "操作员"},
    )
    result = gage_rr(req)
    assert result.status == "ok"

    grr_sv = result.metadata["grr_sv"]
    assert grr_sv < 30.0, f"%GRR 应 < 30%, 实际={grr_sv:.1f}%"

    # 分量和一致性: EV² + AV² ≈ GRR², GRR² + PV² ≈ TV²
    ev = result.metadata["ev"]
    av = result.metadata["av"]
    grr = result.metadata["grr"]
    pv = result.metadata["pv"]
    tv = result.metadata["tv"]

    grr_from_components = np.sqrt(ev**2 + av**2)
    assert abs(grr - grr_from_components) < 1e-6, (
        f"GRR 分量和不一致: GRR={grr:.6f}, sqrt(EV²+AV²)={grr_from_components:.6f}"
    )
    tv_from_components = np.sqrt(grr**2 + pv**2)
    assert abs(tv - tv_from_components) < 1e-6, (
        f"TV 分量和不一致: TV={tv:.6f}, sqrt(GRR²+PV²)={tv_from_components:.6f}"
    )
    assert result.metadata["ndc"] >= 1, f"ndc 应 ≥ 1, 实际={result.metadata['ndc']}"


# ── 容许区间正确性 ──


def test_tolerance_interval_coverage():
    """容许区间: n=500 N(10,1) 99%覆盖/95%置信区间应包含约99%数据。"""
    np.random.seed(42)
    n = 500
    true_mu = 10.0
    data = np.random.normal(true_mu, 1.0, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(
        task="tolerance_interval",
        data=df,
        target_col="val",
        params={"coverage": 0.99, "confidence": 0.95, "side": "two-sided"},
    )
    result = tolerance_interval(req)
    assert result.status == "ok"

    lower = result.metadata["lower"]
    upper = result.metadata["upper"]
    in_interval = np.sum((data >= lower) & (data <= upper))
    coverage_actual = in_interval / n

    # 理论上 ≥ 0.99, 样本有限允许 ≥ 0.97
    assert coverage_actual >= 0.97, (
        f"容许区间应覆盖≥97%数据, 实际={coverage_actual:.2%} ([{lower:.3f}, {upper:.3f}])"
    )
    assert lower < true_mu < upper, f"容许区间应包含均值 {true_mu}"


# ── 响应面分析正确性 ──


def test_response_surface_known_optimum():
    """响应面分析：线性 y=3*x1+2*x2+noise，最大化方向最优区域应在边界。"""
    from smartsuite.engine.doe_opt import response_surface_analysis

    np.random.seed(42)
    n = 60
    x1 = np.random.uniform(0, 10, n)
    x2 = np.random.uniform(0, 10, n)
    y = 3.0 * x1 + 2.0 * x2 + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})

    req = AnalysisRequest(
        task="response_surface",
        data=df,
        target_col="y",
        feature_cols=["x1", "x2"],
        params={"direction": "maximize"},
    )
    result = response_surface_analysis(req)
    assert result.status == "ok", f"响应面分析失败: {result.messages}"
    opt_x1 = result.metadata["optimal_x1"]
    opt_x2 = result.metadata["optimal_x2"]
    assert opt_x1 > 7.0, f"线性最大化时 x1 应接近上界 10, 实际={opt_x1:.2f}"
    assert opt_x2 > 7.0, f"线性最大化时 x2 应接近上界 10, 实际={opt_x2:.2f}"
    assert result.metadata["direction"] == "maximize"
    assert result.metadata["r_squared"] > 0.8, (
        f"强线性关系 R² 应 > 0.8, 实际={result.metadata['r_squared']:.3f}"
    )


# ── DOE 分析正确性 ──


def test_doe_analysis_known_effects():
    """DOE 分析：(A) 平衡 2^2 全因子验证已知效应 (B) 不平衡设计验证 p 值正常（P1 修复）。"""
    from smartsuite.engine.doe_opt import doe_analysis

    np.random.seed(42)

    # ── Part A: 平衡 2^2 全因子 (每组合 5 次重复 → 20 行) ──
    levels = [-1, 1]
    balanced_rows = []
    for x1_val in levels:
        for x2_val in levels:
            for _rep in range(5):
                # y = 2.5*A - 1.5*B + noise  →  效应 A≈+5, B≈-3
                y_val = 2.5 * x1_val - 1.5 * x2_val + np.random.normal(0, 0.3)
                balanced_rows.append({"A": x1_val, "B": x2_val, "y": y_val})
    df_bal = pd.DataFrame(balanced_rows)

    req_bal = AnalysisRequest(
        task="doe_analysis",
        data=df_bal,
        target_col="y",
        feature_cols=["A", "B"],
    )
    result_bal = doe_analysis(req_bal)
    assert result_bal.status == "ok"
    effects_bal = result_bal.tables["effect_estimates"]

    eff_a = float(effects_bal[effects_bal["因子"] == "A"]["主效应"].iloc[0])
    eff_b = float(effects_bal[effects_bal["因子"] == "B"]["主效应"].iloc[0])
    assert 3.5 < eff_a < 6.5, f"因子 A 效应应≈5, 实际={eff_a:.3f}"
    assert -4.5 < eff_b < -1.5, f"因子 B 效应应≈-3, 实际={eff_b:.3f}"
    assert result_bal.metadata["significant_count"] >= 2, (
        f"两个因子效应显著，实际显著数={result_bal.metadata['significant_count']}"
    )

    # ── Part B: 不平衡设计 — 因子 A 有 8 个低水平, 2 个高水平, 效应=+5 ──
    unbalanced_rows = []
    for _ in range(8):
        y_val = -2.5 + np.random.normal(0, 0.3)
        unbalanced_rows.append({"A": -1, "y": y_val})
    for _ in range(2):
        y_val = 2.5 + np.random.normal(0, 0.3)
        unbalanced_rows.append({"A": 1, "y": y_val})
    df_unbal = pd.DataFrame(unbalanced_rows)

    req_unbal = AnalysisRequest(
        task="doe_analysis",
        data=df_unbal,
        target_col="y",
        feature_cols=["A"],
    )
    result_unbal = doe_analysis(req_unbal)
    assert result_unbal.status == "ok"
    effects_unbal = result_unbal.tables["effect_estimates"]

    eff_unbal = float(effects_unbal[effects_unbal["因子"] == "A"]["主效应"].iloc[0])
    assert eff_unbal > 1.0, f"不平衡设计效应方向应为正, 实际={eff_unbal:.3f}"

    p_unbal = float(effects_unbal[effects_unbal["因子"] == "A"]["p值"].iloc[0])
    assert not np.isnan(p_unbal), "不平衡设计 p 值不应为 NaN (P1 修复)"
    # 强真实效应应被正确识别为显著 — p 值可能因四舍五入显示为 0.0000
    assert p_unbal < 0.05, f"强效应应显著, p={p_unbal:.4f}"


# ── ROC 分析正确性 ──


def test_roc_perfect_classifier():
    """ROC 分析：完美分离的分类器 AUC > 0.95。"""
    from smartsuite.engine.doe_opt import roc_analysis

    np.random.seed(42)
    n = 100
    # 类别 0: 低分 [0, 0.4]; 类别 1: 高分 [0.6, 1.0] — 完全无重叠
    scores = np.concatenate(
        [
            np.random.uniform(0.0, 0.4, n // 2),
            np.random.uniform(0.6, 1.0, n // 2),
        ]
    )
    labels = np.concatenate([np.zeros(n // 2, dtype=int), np.ones(n // 2, dtype=int)])
    df = pd.DataFrame({"score": scores, "label": labels})

    req = AnalysisRequest(
        task="roc_analysis",
        data=df,
        target_col="label",
        feature_cols=["score"],
    )
    result = roc_analysis(req)
    assert result.status == "ok"
    auc_val = result.metadata["auc"]
    assert auc_val > 0.95, f"完美分离分类器 AUC 应 > 0.95, 实际={auc_val:.4f}"
    assert result.metadata["auc_label"] == "优秀", (
        f"AUC 判读应为'优秀', 实际='{result.metadata['auc_label']}'"
    )


# ── Logistic 回归正确性 ──


def test_logistic_regression_separated_data():
    """Logistic 回归：(A) 良好分离数据 OR>2 (B) 完美分离数据触发收敛警告。"""
    from smartsuite.engine.doe_opt import logistic_regression

    np.random.seed(42)

    # ── Part A: 良好分离 (x 越大越倾向 class 1), 非完美分离 ──
    n_a = 100
    x_a = np.random.uniform(0, 10, n_a)
    # 轻微噪声使边界不完全分离，但 x 是强预测因子
    y_a = (x_a + np.random.normal(0, 0.8, n_a) > 5).astype(int)
    df_a = pd.DataFrame({"x": x_a, "y": y_a})

    req_a = AnalysisRequest(
        task="logistic_regression",
        data=df_a,
        target_col="y",
        feature_cols=["x"],
    )
    result_a = logistic_regression(req_a)
    assert result_a.status == "ok"
    coef_a = result_a.tables["coefficients"]
    x_row = coef_a[coef_a["变量"] == "x"]
    or_val = float(x_row["OR (Odds Ratio)"].iloc[0])
    assert or_val > 2.0, f"强预测因子 x 的 OR 应 > 2, 实际={or_val:.3f}"

    # ── Part B: 完美分离 — 高分组与低分组区间零重叠 ──
    n_b = 100
    x_b = np.concatenate(
        [
            np.random.uniform(0.1, 4.0, n_b // 2),  # class 0: x 全部 < 4
            np.random.uniform(6.0, 10.0, n_b // 2),  # class 1: x 全部 > 6
        ]
    )
    y_b = np.concatenate([np.zeros(n_b // 2, dtype=int), np.ones(n_b // 2, dtype=int)])
    df_b = pd.DataFrame({"x": x_b, "y": y_b})

    req_b = AnalysisRequest(
        task="logistic_regression",
        data=df_b,
        target_col="y",
        feature_cols=["x"],
    )
    result_b = logistic_regression(req_b)
    assert result_b.status == "ok"
    # 完美分离应触发收敛问题：model_converged=False 或 messages 含警告
    not_converged = not result_b.metadata.get("model_converged", True)
    has_warning = any("未收敛" in msg or "完美分离" in msg for msg in result_b.messages)
    assert not_converged or has_warning, (
        f"完美分离数据应触发收敛警告, converged={result_b.metadata.get('model_converged')}, "
        f"messages={result_b.messages}"
    )


# ── 决策树特征重要性 ──


def test_decision_tree_feature_importance():
    """决策树：已知 x1 驱动 y，内置重要性之和≈1 且首要因子应为 x1。"""
    from smartsuite.engine.root_cause import decision_tree_analysis

    np.random.seed(42)
    n = 300
    x1 = np.random.uniform(0, 10, n)
    x2 = np.random.normal(0, 1, n)  # 噪声
    x3 = np.random.uniform(-5, 5, n)  # 噪声
    # y 主要由 x1 驱动
    y = 3.0 * x1 + np.random.normal(0, 1.5, n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3, "y": y})

    req = AnalysisRequest(
        task="decision_tree", data=df, target_col="y", feature_cols=["x1", "x2", "x3"]
    )
    result = decision_tree_analysis(req)
    assert result.status == "ok"

    fi = result.tables["feature_importance"]
    # 内置重要性 (Gini) 应求和≈1
    gini_sum = float(fi["内置重要性"].sum())
    assert 0.95 < gini_sum < 1.05, f"内置重要性之和应≈1, 实际={gini_sum:.4f}"

    # 最关键因子应为 x1
    top_factor = fi.sort_values("综合重要性", ascending=False).iloc[0]
    assert top_factor["因子"] == "x1", f"期望首要因子为 x1, 实际为 {top_factor['因子']}"
    assert result.metadata["top_factor"] == "x1"


# ── VIF 共线性诊断 ──


def test_vif_detects_collinearity():
    """VIF: x2≈x1+微小噪声 时 VIF(x2)>5，独立变量 VIF≤5。"""
    from smartsuite.engine.root_cause import vif_analysis

    np.random.seed(42)
    n = 200
    x1 = np.random.normal(0, 1, n)
    x2 = x1 + np.random.normal(0, 0.02, n)  # 与 x1 强共线
    x3 = np.random.normal(0, 1, n)  # 独立变量
    df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3})

    req = AnalysisRequest(task="vif", data=df, target_col="", feature_cols=["x1", "x2", "x3"])
    result = vif_analysis(req)
    assert result.status == "ok"

    vif_table = result.tables["vif_table"]
    vif_dict = {}
    for _, row in vif_table.iterrows():
        vif_dict[row["变量"]] = float(row["VIF"])

    assert vif_dict["x2"] > 5.0, f"共线变量 x2 的 VIF 应>5, 实际={vif_dict['x2']:.2f}"
    assert vif_dict["x3"] < 5.0, f"独立变量 x3 的 VIF 应≤5, 实际={vif_dict['x3']:.2f}"
    assert result.metadata["high_vif_count"] >= 1


# ── 二项比例置信区间 ──


def test_proportion_ci_contains_true_p():
    """比例置信区间: n=100, 成功=30, Wilson 95%CI 应包含真值 p=0.3。"""
    from smartsuite.engine.root_cause import proportion_ci

    np.random.seed(42)
    # 构造 30 个 1 和 70 个 0
    data_vals = [1] * 30 + [0] * 70
    np.random.shuffle(data_vals)
    df = pd.DataFrame({"outcome": data_vals})

    req = AnalysisRequest(
        task="proportion_ci",
        data=df,
        target_col="outcome",
        feature_cols=[],
        params={"success_value": 1},
    )
    result = proportion_ci(req)
    assert result.status == "ok"

    p_hat = result.metadata["p_hat"]
    assert 0.28 < p_hat < 0.32, f"p_hat 应接近 0.3, 实际={p_hat:.4f}"

    wilson_lower, wilson_upper = result.metadata["wilson_ci"]
    assert wilson_lower <= 0.3 <= wilson_upper, (
        f"Wilson 95%CI [{wilson_lower:.4f}, {wilson_upper:.4f}] 应包含真值 0.3"
    )

    cp_lower, cp_upper = result.metadata["clopper_pearson_ci"]
    assert cp_lower <= 0.3 <= cp_upper, (
        f"Clopper-Pearson 95%CI [{cp_lower:.4f}, {cp_upper:.4f}] 应包含真值 0.3"
    )


# ── 方差齐性检验 ──


def test_variance_test_detects_heterogeneity():
    """方差齐性检验: 等方差组 Levene p>0.05；异方差组 Levene p<0.05。"""
    from smartsuite.engine.root_cause import variance_test

    np.random.seed(42)
    n = 100
    # 等方差两组
    g1_eq = np.random.normal(10, 1, n)
    g2_eq = np.random.normal(12, 1, n)
    df_eq = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n,
            "val": np.concatenate([g1_eq, g2_eq]),
        }
    )
    req_eq = AnalysisRequest(
        task="variance_test",
        data=df_eq,
        target_col="val",
        feature_cols=["group"],
        params={"group_col": "group"},
    )
    r_eq = variance_test(req_eq)
    assert r_eq.status == "ok"
    levene_p_eq = r_eq.metadata["levene_p"]
    assert levene_p_eq is not None, "Levene 检验应返回 p 值"
    assert levene_p_eq > 0.05, f"等方差数据 Levene p 应>0.05, 实际={levene_p_eq:.4f}"

    # 异方差两组
    g1_uneq = np.random.normal(10, 1, n)
    g2_uneq = np.random.normal(12, 4, n)  # 方差差 16 倍
    df_uneq = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n,
            "val": np.concatenate([g1_uneq, g2_uneq]),
        }
    )
    req_uneq = AnalysisRequest(
        task="variance_test",
        data=df_uneq,
        target_col="val",
        feature_cols=["group"],
        params={"group_col": "group"},
    )
    r_uneq = variance_test(req_uneq)
    assert r_uneq.status == "ok"
    levene_p_uneq = r_uneq.metadata["levene_p"]
    assert levene_p_uneq is not None, "Levene 检验应返回 p 值"
    assert levene_p_uneq < 0.05, f"异方差数据 Levene p 应<0.05, 实际={levene_p_uneq:.4f}"


# ── Cohen's Kappa 一致性 ──


def test_cohens_kappa_high_agreement():
    """Cohen's Kappa: 两评定者 90% 一致时 κ 应 > 0.7。"""
    from smartsuite.engine.root_cause import cohens_kappa

    np.random.seed(42)
    n = 200
    # 评定者 1: 随机 A/B 各半
    rater1 = np.random.choice(["A", "B"], n)
    # 评定者 2: 90% 与 rater1 一致, 10% 随机翻转
    rater2 = rater1.copy()
    flip_idx = np.random.choice(n, size=int(n * 0.10), replace=False)
    for i in flip_idx:
        rater2[i] = "B" if rater1[i] == "A" else "A"

    df = pd.DataFrame({"rater1": rater1, "rater2": rater2})

    req = AnalysisRequest(
        task="cohens_kappa", data=df, target_col="", feature_cols=["rater1", "rater2"]
    )
    result = cohens_kappa(req)
    assert result.status == "ok"

    kappa = result.metadata["kappa"]
    assert kappa > 0.7, f"90% 一致率下 κ 应>0.7, 实际 κ={kappa:.4f}"


# ── Cronbach's Alpha 信度 ──


def test_cronbach_alpha_high_reliability():
    """Cronbach's α: 高相关题项 α>0.8；随机独立题项 α≈0。"""
    from smartsuite.engine.root_cause import cronbach_alpha

    np.random.seed(42)
    n = 200
    # 高相关题项: 所有题项基于同一潜在因子
    latent = np.random.normal(50, 10, n)
    items_corr = pd.DataFrame(
        {
            "item1": latent + np.random.normal(0, 3, n),
            "item2": latent + np.random.normal(0, 3, n),
            "item3": latent + np.random.normal(0, 3, n),
            "item4": latent + np.random.normal(0, 4, n),
            "item5": latent + np.random.normal(0, 4, n),
        }
    )

    req_high = AnalysisRequest(
        task="cronbach_alpha", data=items_corr, target_col="", feature_cols=list(items_corr.columns)
    )
    r_high = cronbach_alpha(req_high)
    assert r_high.status == "ok"
    alpha_high = r_high.metadata["alpha"]
    assert alpha_high > 0.8, f"高相关题项 Cronbach α 应>0.8, 实际={alpha_high:.4f}"

    # 随机独立题项: α 应接近 0
    items_rand = pd.DataFrame({f"r{i}": np.random.normal(50, 10, n) for i in range(1, 6)})
    req_low = AnalysisRequest(
        task="cronbach_alpha", data=items_rand, target_col="", feature_cols=list(items_rand.columns)
    )
    r_low = cronbach_alpha(req_low)
    assert r_low.status == "ok"
    alpha_low = r_low.metadata["alpha"]
    assert alpha_low < 0.3, f"随机独立题项 Cronbach α 应接近 0, 实际={alpha_low:.4f}"


# ── 分布特征摘要 ──


def test_distribution_summary_normal_data():
    """分布特征摘要: 对正态数据应返回非 None 的描述统计量。"""
    from smartsuite.engine.root_cause import distribution_summary

    np.random.seed(42)
    n = 500
    data = np.random.normal(100, 15, n)
    df = pd.DataFrame({"measure": data})

    req = AnalysisRequest(
        task="distribution_summary", data=df, target_col="measure", feature_cols=[]
    )
    result = distribution_summary(req)
    assert result.status == "ok"

    desc = result.metadata["descriptive"]
    assert desc is not None, "描述统计字典不应为 None"
    # 核心统计量应存在
    for key in ["均值", "标准差", "偏度", "峰度"]:
        assert key in desc, f"描述统计应包含「{key}」"
        assert isinstance(desc[key], (int, float)), f"「{key}」应为数值"
    assert desc["样本量"] == n
    # 均值应接近 100
    assert 97 < desc["均值"] < 103, f"均值应≈100, 实际={desc['均值']:.2f}"

    # best_fit 应存在
    assert result.metadata["best_fit"] is not None, "应报告最佳拟合分布"


# ── 正态性评估 ──


def test_normality_check_discriminates():
    """正态性评估: 正态数据应判为正态，指数数据应判为非正态。"""
    from smartsuite.engine.root_cause import normality_check

    np.random.seed(42)
    n = 500
    normal_data = np.random.normal(0, 1, n)
    exp_data = np.random.exponential(1, n)
    df = pd.DataFrame({"normal_col": normal_data, "exp_col": exp_data})

    req = AnalysisRequest(
        task="normality_check", data=df, target_col="normal_col", feature_cols=["exp_col"]
    )
    result = normality_check(req)
    assert result.status == "ok"

    results_table = result.tables["normality_results"]
    normal_row = results_table[results_table["列名"] == "normal_col"].iloc[0]
    exp_row = results_table[results_table["列名"] == "exp_col"].iloc[0]

    # 正态列应通过检验
    assert "正态" in str(normal_row["正态性"]), f"正态数据应判定为正态, 实际={normal_row['正态性']}"

    # 指数列应被识别为非正态
    assert "非正态" in str(exp_row["正态性"]), f"指数数据应被识别为非正态, 实际={exp_row['正态性']}"


# ── 统计功效分析 ──


def test_power_analysis_effect_size_monotonic():
    """统计功效: effect_size=0.2 的 required_n 应 > effect_size=0.8 的 required_n。"""
    from smartsuite.engine.root_cause import power_analysis

    # 大效应量: 所需样本少
    req_big = AnalysisRequest(
        task="power_analysis",
        data=pd.DataFrame(),
        target_col="",
        feature_cols=[],
        params={
            "effect_size": 0.8,
            "alpha": 0.05,
            "target_power": 0.80,
            "mode": "required_n",
            "test_type": "ttest",
        },
    )
    r_big = power_analysis(req_big)
    assert r_big.status == "ok"
    n_big = r_big.metadata["required_n"]

    # 小效应量: 所需样本多
    req_small = AnalysisRequest(
        task="power_analysis",
        data=pd.DataFrame(),
        target_col="",
        feature_cols=[],
        params={
            "effect_size": 0.2,
            "alpha": 0.05,
            "target_power": 0.80,
            "mode": "required_n",
            "test_type": "ttest",
        },
    )
    r_small = power_analysis(req_small)
    assert r_small.status == "ok"
    n_small = r_small.metadata["required_n"]

    assert n_small > n_big, f"小效应量(e=0.2)所需N({n_small}) 应大于大效应量(e=0.8)所需N({n_big})"

    # 效应量 0.8 所需样本量应约为 26 (每组)
    assert 20 <= n_big <= 35, f"effect_size=0.8 时每组约需 26 个样本, 实际={n_big}"


# ── 异常共识检测 ──


def test_outlier_consensus_low_false_positive():
    """异常共识: 对干净正态数据(N=500), 高置信异常应 ≤ 5%。"""
    from smartsuite.engine.spc_monitor import outlier_consensus

    np.random.seed(42)
    n = 500
    data = np.random.normal(100, 10, n)
    df = pd.DataFrame({"val": data})

    req = AnalysisRequest(task="outlier_consensus", data=df, target_col="val", feature_cols=[])
    result = outlier_consensus(req)
    assert result.status == "ok"

    high_conf = result.metadata["high_confidence_count"]
    total_flagged = result.metadata["total_flagged"]
    # 干净正态数据中 Z-score>3 理论约 0.27%, IQR 约 0.7%, 投票≥2 应极少
    assert high_conf <= n * 0.05, f"干净正态数据高置信异常应≤5%({n * 0.05:.0f}), 实际={high_conf}"
    # 总标记不应过多 (任意一种方法标记的)
    assert total_flagged <= n * 0.10, (
        f"干净正态数据总标记应≤10%({n * 0.10:.0f}), 实际={total_flagged}"
    )


# ── 分组箱线图 ──


def test_box_chart_group_statistics():
    """分组箱线图: 2 组数据应返回含样本量/均值/中位数等统计的 group_statistics 表。"""
    from smartsuite.engine.spc_monitor import box_chart

    np.random.seed(42)
    n = 50
    df = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n,
            "val": np.concatenate(
                [
                    np.random.normal(100, 10, n),
                    np.random.normal(115, 8, n),
                ]
            ),
        }
    )

    req = AnalysisRequest(task="box_chart", data=df, target_col="val", feature_cols=["group"])
    result = box_chart(req)
    assert result.status == "ok"

    stats = result.tables["group_statistics"]
    assert len(stats) == 2, f"应有 2 组统计, 实际={len(stats)} 行"

    # 应包含核心统计列
    for col in ["分组", "样本量", "均值", "中位数", "标准差", "IQR"]:
        assert col in stats.columns, f"group_statistics 应包含「{col}」列"

    # 元数据应记录分组数
    assert result.metadata["n_groups"] == 2


# ── 散点图正确性 ──


def test_scatter_plot_linear_fit_known_slope():
    """散点图线性拟合: y = 3.0 + 2.0*x + ε → 斜率≈2.0, R²>0.9。"""
    np.random.seed(42)
    n = 100
    x = np.random.uniform(0, 10, n)
    y = 3.0 + 2.0 * x + np.random.normal(0, 0.3, n)
    df = pd.DataFrame({"x": x, "y": y})

    req = AnalysisRequest(
        task="scatter_plot", data=df, target_col="y", feature_cols=["x"], params={"fit": "linear"}
    )
    result = scatter_plot(req)
    assert result.status == "ok"
    r2 = result.metadata["r_squared"]
    assert r2 is not None, "线性拟合应返回 R²"
    assert r2 > 0.9, f"R² 应 > 0.9, 实际={r2:.3f}"
    assert result.metadata["fit_type"] == "linear"


def test_scatter_plot_no_fit():
    """散点图无拟合: status=ok, r_squared=None。"""
    np.random.seed(42)
    n = 30
    x = np.random.uniform(0, 10, n)
    y = np.random.normal(50, 5, n)
    df = pd.DataFrame({"x": x, "y": y})

    req = AnalysisRequest(
        task="scatter_plot", data=df, target_col="y", feature_cols=["x"], params={"fit": "none"}
    )
    result = scatter_plot(req)
    assert result.status == "ok"
    assert result.metadata["r_squared"] is None, "无拟合时 R² 应为 None"


def test_scatter_plot_insufficient_data():
    """散点图数据不足: 少于3点应返回 error。"""
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})

    req = AnalysisRequest(task="scatter_plot", data=df, target_col="y", feature_cols=["x"])
    result = scatter_plot(req)
    assert result.status == "error"
    assert len(result.messages) > 0


# ── 参数消费验证 (commit 2405507 新增参数通道) ──


def test_vif_custom_threshold():
    """VIF: 自定义 threshold 参数应影响判定结果。"""
    from smartsuite.engine.root_cause import vif_analysis

    np.random.seed(42)
    n = 200
    x1 = np.random.normal(0, 1, n)
    x2 = x1 + np.random.normal(0, 0.1, n)  # 中等共线性
    x3 = np.random.normal(0, 1, n)
    df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3})

    # 严格阈值 (threshold=1.5) 应检测到更多高 VIF 变量
    req_strict = AnalysisRequest(
        task="vif",
        data=df,
        target_col="",
        feature_cols=["x1", "x2", "x3"],
        params={"threshold": 1.5},
    )
    result_strict = vif_analysis(req_strict)
    assert result_strict.status == "ok"

    # 宽松阈值 (threshold=100) 应检测不到高 VIF 变量
    req_loose = AnalysisRequest(
        task="vif",
        data=df,
        target_col="",
        feature_cols=["x1", "x2", "x3"],
        params={"threshold": 100},
    )
    result_loose = vif_analysis(req_loose)
    assert result_loose.status == "ok"
    assert result_loose.metadata["high_vif_count"] == 0


def test_proportion_ci_custom_ci_level():
    """比例置信区间: ci_level=0.90 应产生比 0.95 更窄的区间。"""
    from smartsuite.engine.root_cause import proportion_ci

    df = pd.DataFrame({"y": [1] * 30 + [0] * 70})

    req_95 = AnalysisRequest(
        task="proportion_ci", data=df, target_col="y", params={"ci_level": 0.95}
    )
    req_90 = AnalysisRequest(
        task="proportion_ci", data=df, target_col="y", params={"ci_level": 0.90}
    )
    r95 = proportion_ci(req_95)
    r90 = proportion_ci(req_90)
    assert r95.status == "ok" and r90.status == "ok"

    w95 = r95.metadata["wilson_ci"]
    w90 = r90.metadata["wilson_ci"]
    width_95 = w95[1] - w95[0]
    width_90 = w90[1] - w90[0]
    assert width_90 < width_95, "90% CI 应比 95% CI 更窄"


def test_proportion_ci_invalid_ci_level():
    """比例置信区间: ci_level 超出 (0,1) 应返回 error。"""
    from smartsuite.engine.root_cause import proportion_ci

    df = pd.DataFrame({"y": [1] * 10 + [0] * 10})

    req = AnalysisRequest(task="proportion_ci", data=df, target_col="y", params={"ci_level": 1.5})
    result = proportion_ci(req)
    assert result.status == "error"
    assert "ci_level" in result.messages[0]


def test_distribution_summary_custom_bins():
    """分布特征摘要: bins 参数必须真正改变直方图分箱数（Round-2 批次D #2d）。

    此前仅断言 status=='ok'——bins 参数是否生效完全未验证（若被静默忽略，
    bins=5 与 bins=20 会得到相同分箱数）。现直接比较两种 bins 下直方图
    Rectangle patch 数量：5 vs 20 必须不同且各自匹配请求值。
    """
    from matplotlib.patches import Rectangle

    from smartsuite.engine.root_cause import distribution_summary

    np.random.seed(42)
    df = pd.DataFrame({"y": np.random.normal(100, 15, 200)})

    def _bin_count(bins):
        result = distribution_summary(
            AnalysisRequest(
                task="distribution_summary", data=df, target_col="y", params={"bins": bins}
            )
        )
        assert result.status == "ok", f"bins={bins} 失败: {result.messages}"
        ax = result.figures[0].axes[0]
        return len([p for p in ax.patches if isinstance(p, Rectangle)])

    n5 = _bin_count(5)
    n20 = _bin_count(20)
    assert n5 == 5, f"bins=5 应产生 5 个直方柱，实际 {n5}"
    assert n20 == 20, f"bins=20 应产生 20 个直方柱，实际 {n20}"
    assert n5 != n20, "bins 参数未生效（5 与 20 分箱数相同）"


def test_distribution_summary_invalid_bins():
    """分布特征摘要: bins 为负数应返回 error。"""
    from smartsuite.engine.root_cause import distribution_summary

    np.random.seed(42)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 100)})

    req = AnalysisRequest(task="distribution_summary", data=df, target_col="y", params={"bins": -5})
    result = distribution_summary(req)
    assert result.status == "error"
    assert "bins" in result.messages[0]


def test_normality_check_custom_alpha():
    """正态性评估: alpha 参数必须真正改变判定（Round-2 批次D #2e）。

    此前仅断言两个 alpha 都返回 ok——alpha 是否参与判定完全未验证。
    现用极端 alpha 验证生效性：对同一正态样本（SW p≈0.66），
    alpha=0.001 → 判「正态 ✓」（normal_count=1），
    alpha=0.99  → 判「非正态」（normal_count=0），判定随 alpha 翻转。
    """
    from smartsuite.engine.root_cause import normality_check

    np.random.seed(42)
    n = 100
    data = np.random.normal(0, 1, n)
    df = pd.DataFrame({"x": data})

    req_lo = AnalysisRequest(
        task="normality_check", data=df, target_col="x", params={"alpha": 0.001}
    )
    req_hi = AnalysisRequest(
        task="normality_check", data=df, target_col="x", params={"alpha": 0.99}
    )
    r_lo = normality_check(req_lo)
    r_hi = normality_check(req_hi)
    assert r_lo.status == "ok" and r_hi.status == "ok"
    # alpha 生效：宽松阈值判正态、严苛阈值判非正态（同一数据）
    assert r_lo.metadata["normal_count"] == 1, (
        f"alpha=0.001 应判正态: {r_lo.tables['normality_results'].to_dict('records')}"
    )
    assert r_hi.metadata["normal_count"] == 0, (
        f"alpha=0.99 应判非正态: {r_hi.tables['normality_results'].to_dict('records')}"
    )
    assert r_lo.metadata["normal_count"] != r_hi.metadata["normal_count"], (
        "alpha 参数未生效（两种阈值判定相同）"
    )


def test_normality_check_ad_test_functional():
    """正态性评估: Anderson-Darling 检验应产生非 None 结果。"""
    from smartsuite.engine.root_cause import normality_check

    np.random.seed(42)
    df = pd.DataFrame({"x": np.random.normal(0, 1, 200)})

    req = AnalysisRequest(task="normality_check", data=df, target_col="x")
    result = normality_check(req)
    assert result.status == "ok"

    table = result.tables["normality_results"]
    ad_cell = str(table.iloc[0]["Anderson-Darling"])
    assert ad_cell != "N/A", f"AD 检验应产生有效结果，实际={ad_cell}"
    assert "A-D stat=" in ad_cell, f"AD 检验应包含统计量，实际={ad_cell}"


def test_scatter_plot_group_col_equals_x_col():
    """审查 2026-08-19 #1.2：分组列与 X 列相同（含重复列选择）时不得崩溃。"""
    np.random.seed(42)
    n = 30
    df = pd.DataFrame(
        {
            "x": np.random.uniform(0, 10, n),
            "y": 3.0 + 2.0 * np.random.uniform(0, 10, n) + np.random.normal(0, 0.3, n),
        }
    )
    req = AnalysisRequest(
        task="scatter_plot",
        data=df,
        target_col="y",
        feature_cols=["x"],
        params={"fit": "linear", "group_col": "x"},
    )
    result = scatter_plot(req)
    assert result.status == "ok", f"group_col==x_col 崩溃: {result.messages}"
    assert result.metadata.get("fit_type") == "linear"

    # 分组列与 Y 列相同同样不应崩溃
    req2 = AnalysisRequest(
        task="scatter_plot",
        data=df,
        target_col="y",
        feature_cols=["x"],
        params={"fit": "none", "group_col": "y"},
    )
    result2 = scatter_plot(req2)
    assert result2.status == "ok", f"group_col==y_col 崩溃: {result2.messages}"


def test_box_chart_params_group_col_honored(sample_two_group_data):
    """审查 2026-08-19 #2.17：params.group_col 应被引擎消费（此前 UI 选择无效）。"""
    from smartsuite.engine.exploratory import box_chart

    req = AnalysisRequest(
        task="box_chart",
        data=sample_two_group_data,
        target_col="强度",
        feature_cols=["强度"],
        params={"mode": "facet", "group_col": "工艺"},
    )
    result = box_chart(req)
    assert result.status == "ok", f"box_chart 失败: {result.messages}"
    assert result.metadata.get("group_col") == "工艺"
    assert result.metadata.get("n_groups") == 2


def test_box_chart_group_col_missing_column():
    """审查 2026-08-19 #2.10：group_col 指向不存在列应返回明确错误。"""
    from smartsuite.engine.exploratory import box_chart

    df = pd.DataFrame({"v": np.random.normal(0, 1, 20), "g": ["A"] * 10 + ["B"] * 10})
    req = AnalysisRequest(
        task="box_chart",
        data=df,
        target_col="v",
        feature_cols=["v"],
        params={"group_col": "不存在的列"},
    )
    result = box_chart(req)
    assert result.status == "error"
    assert any("不存在的列" in m for m in result.messages)


def test_decision_tree_string_params_convertible():
    """审查 2026-08-19 #1.4：字符串 max_depth/random_state 应被安全转换。"""
    from smartsuite.engine.root_cause import decision_tree_analysis

    np.random.seed(1)
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, 40),
            "x2": np.random.normal(0, 1, 40),
            "y": np.random.normal(0, 1, 40),
        }
    )
    req = AnalysisRequest(
        task="decision_tree",
        data=df,
        target_col="y",
        feature_cols=["x1", "x2"],
        params={"max_depth": "3", "random_state": "42"},
    )
    result = decision_tree_analysis(req)
    assert result.status == "ok", f"字符串参数应可转换: {result.messages}"
    assert len(result.tables["feature_importance"]) == 2


# ── 审查 2026-08-19 SPC 修复回归 ──


def test_spc_xbar_numeric_x_axis_ordered():
    """Round-2 批次D #8：np.int64 数值 X 轴必须按数值序而非字典序渲染。

    数据 X 列用 np.int64（Excel/CSV 读取默认类型）并作为 feature_cols[0] 横坐标。
    引擎修复前 sorted() 的 isinstance(v,(int,float)) 在 numpy>=2 下漏判 np.int64，
    退回字符串字典序 [1,10,11,12,2,...]，图表与违规标签顺序错乱。
    此处直接断言：① 图表 X 轴刻度标签为数值序（'10' 排在 '2' 之后）；
    ② 违规表 '违规子组' 标签逐行数值序；③ 保留控制限数值断言。
    """
    from smartsuite.engine.spc_monitor import xbar_r_chart

    np.random.seed(3)
    x = pd.Series(np.arange(1, 13), dtype="int64")  # np.int64（触发旧 bug 的类型）
    y = np.random.normal(50, 2, 12)
    y[10] = 58.0  # x=11 离群点 → 应触发 规则1 违规
    df = pd.DataFrame({"x": x, "y": y})
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="y", feature_cols=["x"], params={})
    result = xbar_r_chart(req)
    assert result.status == "ok", f"spc_xbar 失败: {result.messages}"

    # ① 数值断言：控制限有限且 LCL < CL < UCL
    cl = float(result.tables["control_limits"].iloc[0]["CL"])
    ucl = float(result.tables["control_limits"].iloc[0]["UCL"])
    lcl = float(result.tables["control_limits"].iloc[0]["LCL"])
    assert np.isfinite(ucl) and np.isfinite(lcl)
    assert lcl < cl < ucl

    # ② X 轴顺序：刻度标签必须数值序（'10' 在 '2' 之后）
    ax = result.figures[0].axes[0]
    labels = [t.get_text() for t in ax.get_xticklabels()]
    assert labels == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"], (
        f"np.int64 X 轴应按数值序，实际: {labels}"
    )
    assert labels.index("10") > labels.index("2"), f"X 轴出现字典序: {labels}"

    # ③ 违规表 '违规子组' 标签逐行数值序（x=11 离群点应被检出）
    tbl = result.tables.get("violations", pd.DataFrame())
    assert len(tbl) > 0, "x=11 离群点应被检出违规"
    if "违规子组" in tbl.columns:
        for _, row in tbl.iterrows():
            parts = [
                p.strip() for p in str(row["违规子组"]).replace("…", "").split(",") if p.strip()
            ]
            nums = [int(p) for p in parts if p.isdigit()]
            if len(nums) > 1:
                assert nums == sorted(nums), f"违规子组标签非数值序: {nums}"


def test_spc_xbar_i_chart_violation_visible():
    """审查 #2.3：I 图（全 n=1）检出违规时，违规表不得为空字符串。"""
    from smartsuite.engine.spc_monitor import xbar_r_chart

    np.random.seed(5)
    # 前 25 点正常 + 1 个离群点
    y = np.random.normal(50, 1, 26)
    y[25] = 58.0  # 明显离群（>3σ）
    df = pd.DataFrame({"x": range(1, 27), "y": y})
    req = AnalysisRequest(
        task="spc_xbar", data=df, target_col="y", feature_cols=[], params={"group_col": "x"}
    )
    result = xbar_r_chart(req)
    assert result.status == "ok"
    tbl = result.tables.get("violations", pd.DataFrame())
    assert len(tbl) > 0, "离群点应被检出"
    # 违规子组标签非空（I 图路径此前为空字符串）
    if "违规子组" in tbl.columns:
        assert all(str(v).strip() != "" for v in tbl["违规子组"]), "I 图违规子组标签不应为空"
    assert "规则1" in str(tbl["规则"].tolist())


def test_spc_ewma_l_invalid_rejected():
    """审查 #2.8：EWMA 的 L<=0 应报错而非 30/30 全违规 status=ok。"""
    from smartsuite.engine.spc_monitor import ewma_chart

    np.random.seed(3)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 30)})
    req = AnalysisRequest(
        task="spc_ewma", data=df, target_col="y", feature_cols=[], params={"lam": 0.2, "L": 0}
    )
    result = ewma_chart(req)
    assert result.status == "error"
    assert any("L" in m for m in result.messages)


def test_spc_nonparametric_constant_column_rejected():
    """审查 #2.5：常量列不得输出"过程稳定 CL=nan"。"""
    from smartsuite.engine.spc_monitor import spc_nonparametric

    df = pd.DataFrame({"y": [5.0] * 12})
    req = AnalysisRequest(task="spc_nonparametric", data=df, target_col="y", feature_cols=[])
    result = spc_nonparametric(req)
    assert result.status == "error"
    assert any("常量" in m for m in result.messages)


def test_spc_attribute_p_chart_rejects_percentage_data():
    """审查 2026-08-19 #2.8：p 图遇百分比/超 [0,1] 数据应报错而非 NaN 控制限。"""
    from smartsuite.engine.spc_monitor import attribute_chart

    np.random.seed(2)
    df = pd.DataFrame(
        {
            "x": range(1, 21),
            "y": np.random.uniform(1, 8, 20),  # 百分比型不良率 (1-8%)
        }
    )
    req = AnalysisRequest(
        task="spc_attribute",
        data=df,
        target_col="y",
        feature_cols=[],
        params={"chart_type": "p", "group_col": "x"},
    )
    result = attribute_chart(req)
    assert result.status == "error"
    assert any("0/1" in m for m in result.messages)


def test_spc_attribute_p_chart_binary_string_column():
    """审查 2026-08-19 #2.8：合格/不合格 二值串列应映射 0/1 后正常出图。"""
    from smartsuite.engine.spc_monitor import attribute_chart

    np.random.seed(4)
    n = 60
    df = pd.DataFrame(
        {
            "x": np.repeat(range(1, 13), 5),
            "y": np.where(np.random.rand(n) < 0.1, "不合格", "合格"),
        }
    )
    req = AnalysisRequest(
        task="spc_attribute",
        data=df,
        target_col="y",
        feature_cols=["x"],
        params={"chart_type": "p", "group_col": "x"},
    )
    result = attribute_chart(req)
    assert result.status == "ok", f"二值串列应可出图: {result.messages}"
    assert result.metadata["chart_type"] == "p"


def test_spc_xbar_grouped_multi_violation_label_correct_group():
    """Round-2 M1：分组 multi 模式下违规表标签必须对应正确分组（此前 B 组违规显示 A 组行）。"""
    from smartsuite.engine.spc_monitor import xbar_r_chart

    np.random.seed(9)
    n = 10
    rows = []
    for g in ["A", "B"]:
        for sub in range(1, n + 1):
            mu = 58.0 if (g == "B" and sub == n) else 50.0
            for _ in range(4):
                rows.append({"g": g, "sub": sub, "y": np.random.normal(mu, 1.0)})
    df = pd.DataFrame(rows)
    r = xbar_r_chart(
        AnalysisRequest(
            task="spc_xbar",
            data=df,
            target_col="y",
            feature_cols=[],
            params={"group_col": "g", "subgroup_col": "sub"},
        )
    )
    assert r.status == "ok", f"spc_xbar 失败: {r.messages}"
    tbl = r.tables.get("violations", pd.DataFrame())
    if len(tbl) > 0 and "违规子组" in tbl.columns and "分组" in tbl.columns:
        b_rows = tbl[tbl["分组"] == "B"]
        for _, row in b_rows.iterrows():
            labels = [x for x in str(row["违规子组"]).split(",") if x.strip()]
            assert labels, "B 组违规标签不应为空"


def test_xbar_all_n1_groups_sigma_ddof1():
    """X-bar (分组 + 全 n=1)：σ 回退路径必须用 ddof=1（审查 #P1-1）。

    分组且每组 1 点时 MR 池化为空，σ 由子组均值的样本标准差估计；
    此前分组分支用 ddof=1 而非分组分支用 ddof=0（spc_charts.py 468 vs 479），
    现统一 ddof=1。手工交叉验证：std([1,5,9], ddof=1) = 4。
    """
    from smartsuite.engine.spc_monitor import xbar_r_chart

    df = pd.DataFrame({"g": ["A", "B", "C"], "y": [1.0, 5.0, 9.0]})
    req = AnalysisRequest(
        task="spc_xbar", data=df, target_col="y", feature_cols=[], params={"group_col": "g"}
    )
    r = xbar_r_chart(req)
    assert r.status == "ok", f"应可计算: {r.messages}"
    expected_sigma = float(np.std([1.0, 5.0, 9.0], ddof=1))  # = 4.0
    assert abs(r.metadata["sigma_xbar"] - expected_sigma) < 1e-9, (
        f"σ 应使用 ddof=1: got {r.metadata['sigma_xbar']}, expected {expected_sigma}"
    )
    assert abs(r.metadata["ucl_x"] - (5.0 + 3 * expected_sigma)) < 1e-9
    assert abs(r.metadata["lcl_x"] - (5.0 - 3 * expected_sigma)) < 1e-9


def test_change_point_strict_accuracy():
    """变点检测定位精度：固定 seed 下偏差 ≤3 点（审查 #R2 声明与测试对齐）。

    实测 seed=7 时偏差为 -1；测试锁定 ±3 提供余量，防实现漂移导致定位退化。
    """
    from smartsuite.engine.detection import change_point_detect

    scenarios = [
        # (真实变点位置, 数据构造)
        (100, lambda rng: np.concatenate([rng.normal(100, 2, 100), rng.normal(116, 2, 100)])),
        (80, lambda rng: np.concatenate([rng.normal(10, 0.5, 80), rng.normal(12, 0.5, 80)])),
        (
            100,
            lambda rng: np.concatenate(
                [rng.normal(100, 2, 100), rng.normal(116, 2, 100), rng.normal(90, 2, 100)]
            ),
        ),
    ]
    for true_cp, make in scenarios:
        rng = np.random.default_rng(7)
        df = pd.DataFrame({"x": make(rng)})
        r = change_point_detect(
            AnalysisRequest(
                task="change_point",
                data=df,
                target_col="x",
                params={"min_segment": 15, "n_changepoints": 5},
            )
        )
        assert r.status == "ok"
        assert r.metadata["changepoints"], f"应检测到变点 (true={true_cp})"
        # 至少一个变点落在真实位置 ±3
        assert any(abs(cp - true_cp) <= 3 for cp in r.metadata["changepoints"]), (
            f"定位偏差过大: true={true_cp}, detected={r.metadata['changepoints']}"
        )
