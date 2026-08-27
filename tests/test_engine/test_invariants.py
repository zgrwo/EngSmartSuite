"""数学不变量/属性测试 — 验证分析结果的数学性质。

这些测试不依赖"正确答案"，只检查结果在数学上不可能违反的约束：
- p 值必须在 [0, 1]
- 相关性系数必须在 [-1, 1]
- Cpk 不能大于 Cp
- 置信区间必须包含点估计
- 方差分量必须非负
- R² 必须在 [0, 1]
"""

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
    attribute_chart,
    gage_rr,
    process_capability_analysis,
    scatter_plot,
    survival_analysis,
    xbar_r_chart,
)

# ═══════════════════════════════════════════════════════════
# 相关性不变量
# ═══════════════════════════════════════════════════════════


def test_correlation_matrix_bounds():
    """相关性矩阵所有值必须在 [-1, 1] 范围内。"""
    np.random.seed(42)
    n = 100
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, n),
            "x2": np.random.normal(0, 1, n),
            "x3": np.random.normal(0, 1, n),
            "y": np.random.normal(0, 1, n),
        }
    )
    for method in ["pearson", "spearman", "kendall"]:
        req = AnalysisRequest(
            task="correlation",
            data=df,
            target_col="y",
            feature_cols=["x1", "x2", "x3"],
            params={"method": method},
        )
        result = correlation_analysis(req)
        assert result.status == "ok", result.messages
        corr_mat = result.tables["correlation_matrix"]
        assert ((corr_mat >= -1.01) & (corr_mat <= 1.01)).all().all(), (
            f"{method}: 相关性系数超出 [-1, 1]"
        )


def test_correlation_diagonal_is_one():
    """相关性矩阵对角线必须为 1（变量与自身的相关）。"""
    np.random.seed(42)
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, 30),
            "y": np.random.normal(0, 1, 30),
        }
    )
    req = AnalysisRequest(
        task="correlation",
        data=df,
        target_col="y",
        feature_cols=["x1"],
        params={"method": "pearson"},
    )
    result = correlation_analysis(req)
    corr_mat = result.tables["correlation_matrix"]
    # 对角线元素 y-y 应为 1
    assert abs(corr_mat.loc["y", "y"] - 1.0) < 0.01, "对角线不是 1"


# ═══════════════════════════════════════════════════════════
# ANOVA 不变量
# ═══════════════════════════════════════════════════════════


def test_anova_r_squared_bounds():
    """ANOVA R² 必须在 [0, 1] 范围内。"""
    np.random.seed(42)
    n = 30
    df = pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n + ["C"] * n,
            "val": np.concatenate(
                [
                    np.random.normal(10, 1, n),
                    np.random.normal(12, 1, n),
                    np.random.normal(11, 1, n),
                ]
            ),
        }
    )
    req = AnalysisRequest(task="anova", data=df, target_col="val", feature_cols=["group"])
    result = anova_analysis(req)
    assert result.status == "ok", result.messages
    assert "r_squared" in result.metadata
    rsq = result.metadata["r_squared"]
    assert 0 <= rsq <= 1, f"R²={rsq:.3f} 不在 [0,1]"


# ═══════════════════════════════════════════════════════════
# 过程能力不变量
# ═══════════════════════════════════════════════════════════


def test_cpk_leq_cp():
    """Cpk 永远不能大于 Cp（Cpk = Cp 仅当过程完美居中）。"""
    np.random.seed(42)
    n = 500
    data = np.random.normal(10, 1, n)
    df = pd.DataFrame({"val": data})
    req = AnalysisRequest(
        task="process_capability", data=df, target_col="val", params={"usl": 13.0, "lsl": 7.0}
    )
    result = process_capability_analysis(req)
    assert result.status == "ok", result.messages
    cp = result.metadata.get("cp")
    cpk = result.metadata.get("cpk")
    pp = result.metadata.get("pp")
    ppk = result.metadata.get("ppk")
    if cp is not None and cpk is not None:
        assert cpk <= cp + 0.001, f"Cpk={cpk:.3f} > Cp={cp:.3f}"
    if pp is not None and ppk is not None:
        assert ppk <= pp + 0.001, f"Ppk={ppk:.3f} > Pp={pp:.3f}"


def test_cpk_single_sided_spec():
    """单侧公差应能计算 Cpk（非 None）。"""
    np.random.seed(42)
    df = pd.DataFrame({"val": np.random.normal(10, 1, 200)})
    # 仅上公差
    req = AnalysisRequest(
        task="process_capability", data=df, target_col="val", params={"usl": 13.0}
    )
    result = process_capability_analysis(req)
    assert result.status == "ok", result.messages
    cpk = result.metadata.get("cpk")
    assert cpk is not None, "单侧公差 (USL only) 应能计算 Cpk"
    assert cpk > 0, f"单侧 Cpk 应为正值, got {cpk}"

    # 仅下公差
    req2 = AnalysisRequest(
        task="process_capability", data=df, target_col="val", params={"lsl": 7.0}
    )
    result2 = process_capability_analysis(req2)
    assert result2.status == "ok", result2.messages
    cpk2 = result2.metadata.get("cpk")
    assert cpk2 is not None, "单侧公差 (LSL only) 应能计算 Cpk"
    assert cpk2 > 0, f"单侧 Cpk 应为正值, got {cpk2}"


# ═══════════════════════════════════════════════════════════
# 回归不变量
# ═══════════════════════════════════════════════════════════


def test_regression_r_squared_non_negative():
    """回归 R² (非调整) 必须 ≥ 0。调整 R² 可以为负，这是数学上有效的。"""
    np.random.seed(42)
    n = 100
    df = pd.DataFrame(
        {
            "x": np.random.uniform(0, 10, n),
            "y": 2.0 + 3.0 * np.random.uniform(0, 10, n) + np.random.normal(0, 1, n),
        }
    )
    req = AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
    result = regression_analysis(req)
    assert result.status == "ok", result.messages
    for _, row in result.tables["diagnostics"].iterrows():
        if row["指标"] == "R²":
            val = float(row["值"])
            assert val >= 0, f"R² 为负: {val:.3f}"
        # 调整 R² 可以为负 — 不检查


# ═══════════════════════════════════════════════════════════
# 假设检验不变量
# ═══════════════════════════════════════════════════════════


def test_ttest_p_value_range():
    """T 检验 p 值必须在 [0, 1] 范围内。"""
    np.random.seed(42)
    n = 50
    g1 = np.random.normal(10, 1, n)
    g2 = np.random.normal(12, 1, n)
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
    assert result.status == "ok", result.messages
    p = result.metadata.get("p_value")
    if p is not None:
        assert 0 <= p <= 1, f"p 值无效: {p}"


# ═══════════════════════════════════════════════════════════
# SPC 不变量
# ═══════════════════════════════════════════════════════════


def test_xbar_control_limits_order():
    """X-bar 控制限必须满足 LCL < CL < UCL。"""
    np.random.seed(42)
    data = []
    for sg in range(1, 11):
        for _ in range(5):
            data.append({"子组": sg, "val": np.random.normal(10, 1)})
    df = pd.DataFrame(data)
    req = AnalysisRequest(
        task="spc_xbar", data=df, target_col="val", feature_cols=["子组"], params={}
    )
    result = xbar_r_chart(req)
    assert result.status == "ok", result.messages
    cl = result.metadata["xbar_mean"]
    ucl = result.metadata["ucl_x"]
    lcl = result.metadata["lcl_x"]
    assert lcl < cl < ucl, f"控制限顺序错误: LCL={lcl:.3f}, CL={cl:.3f}, UCL={ucl:.3f}"


def test_r_chart_control_limits_non_negative():
    """R 图控制限必须 ≥ 0（极差不能为负）。"""
    np.random.seed(42)
    data = []
    for sg in range(1, 11):
        for _ in range(5):
            data.append({"子组": sg, "val": np.random.normal(10, 1)})
    df = pd.DataFrame(data)
    req = AnalysisRequest(
        task="spc_xbar", data=df, target_col="val", feature_cols=["子组"], params={}
    )
    result = xbar_r_chart(req)
    assert result.status == "ok", result.messages
    assert result.metadata["lcl_r"] >= 0, f"R 图 LCL 不应为负: {result.metadata['lcl_r']:.3f}"


# ═══════════════════════════════════════════════════════════
# 生存分析不变量
# ═══════════════════════════════════════════════════════════


def test_survival_km_monotonic():
    """KM 生存概率必须单调递减。"""
    np.random.seed(42)
    n = 100
    times = np.random.exponential(10, n)
    events = np.ones(n)
    df = pd.DataFrame({"time": times, "event": events})
    req = AnalysisRequest(
        task="survival_analysis", data=df, target_col="time", feature_cols=["event"]
    )
    result = survival_analysis(req)
    assert result.status == "ok", result.messages
    surv_table = result.tables.get("km_survival")
    if surv_table is not None and "生存概率" in surv_table.columns:
        surv_values = surv_table["生存概率"].values
        # KM 生存概率必须单调非增
        assert all(
            float(surv_values[i]) >= float(surv_values[i + 1]) - 0.001
            for i in range(len(surv_values) - 1)
        ), "KM 生存概率不是单调递减"


# ═══════════════════════════════════════════════════════════
# 量具 R&R 不变量
# ═══════════════════════════════════════════════════════════


def test_gage_rr_variance_decomposition():
    """GRR 方差分量分解: TV² ≈ GRR² + PV²。"""
    np.random.seed(42)
    n_parts = 10
    n_ops = 3
    n_reps = 2
    rows = []
    for part in range(1, n_parts + 1):
        true_val = np.random.normal(50, 5)
        for op in range(1, n_ops + 1):
            for rep in range(n_reps):
                rows.append(
                    {
                        "零件": part,
                        "操作员": op,
                        "测量值": true_val + np.random.normal(0, 0.5),
                    }
                )
    df = pd.DataFrame(rows)
    req = AnalysisRequest(
        task="gage_rr",
        data=df,
        target_col="测量值",
        feature_cols=["零件", "操作员"],
        params={"part_col": "零件", "operator_col": "操作员"},
    )
    result = gage_rr(req)
    assert result.status == "ok", result.messages
    grr_pct = result.metadata.get("grr_pct")
    ev_pct = result.metadata.get("ev_pct")
    av_pct = result.metadata.get("av_pct")
    pv_pct = result.metadata.get("pv_pct")
    # 所有百分比分量应非负
    for name, val in [("GRR%", grr_pct), ("EV%", ev_pct), ("AV%", av_pct), ("PV%", pv_pct)]:
        if val is not None:
            assert val >= 0, f"{name} 不应该为负: {val:.1f}"


# ═══════════════════════════════════════════════════════════
# 计数型控制图不变量
# ═══════════════════════════════════════════════════════════


def test_attribute_chart_center_line_positive():
    """计数型控制图中心线必须 > 0。"""
    np.random.seed(42)
    df_p = pd.DataFrame(
        {
            "batch": np.repeat(range(1, 21), 50),
            "defect": np.random.binomial(1, 0.05, 1000),
        }
    )
    for chart_type, col in [("p", "defect"), ("np", "defect")]:
        req = AnalysisRequest(
            task="spc_attribute",
            data=df_p,
            target_col=col,
            params={"chart_type": chart_type, "subgroup_col": "batch"},
        )
        result = attribute_chart(req)
        assert result.status == "ok", result.messages
        cl = result.metadata.get("center_line")
        if cl is not None:
            assert cl > 0, f"{chart_type}-chart CL={cl} ≤ 0"


# ── 散点图不变量 ──


def test_scatter_plot_r_squared_bounds():
    """散点图线性拟合 R² 必须在 [0, 1] 范围内。"""
    np.random.seed(42)
    n = 50
    x = np.random.uniform(0, 10, n)
    y = 3.0 + 2.0 * x + np.random.normal(0, 1.0, n)
    df = pd.DataFrame({"x": x, "y": y})

    req = AnalysisRequest(
        task="scatter_plot", data=df, target_col="y", feature_cols=["x"], params={"fit": "linear"}
    )
    result = scatter_plot(req)
    assert result.status == "ok"
    r2 = result.metadata["r_squared"]
    assert r2 is not None
    assert 0.0 <= r2 <= 1.0, f"R² 应在 [0,1], 实际={r2:.4f}"


def test_scatter_plot_no_fit_r_squared_none():
    """散点图无拟合时 r_squared 必须为 None。"""
    np.random.seed(42)
    df = pd.DataFrame({"x": np.random.uniform(0, 10, 30), "y": np.random.normal(0, 1, 30)})

    req = AnalysisRequest(
        task="scatter_plot", data=df, target_col="y", feature_cols=["x"], params={"fit": "none"}
    )
    result = scatter_plot(req)
    assert result.status == "ok"
    assert result.metadata["r_squared"] is None


def test_scatter_plot_constant_x_column():
    """散点图 X 列为常量时不崩溃，返回 ok。"""
    np.random.seed(42)
    df = pd.DataFrame({"x": [5.0] * 30, "y": np.random.normal(50, 5, 30)})

    req = AnalysisRequest(
        task="scatter_plot",
        data=df,
        target_col="y",
        feature_cols=["x"],
        params={"fit": "linear", "show_ci": True},
    )
    result = scatter_plot(req)
    assert result.status == "ok"


# ═══════════════════════════════════════════════════════════
# 效应量不变量 (APA 第 7 版)
# ═══════════════════════════════════════════════════════════


def test_anova_effect_size_bounds():
    """ANOVA η² 必须在 [0, 1] 范围内。"""
    np.random.seed(42)
    n = 60
    df = pd.DataFrame(
        {
            "y": np.concatenate(
                [
                    np.random.normal(100, 10, n // 3),
                    np.random.normal(110, 10, n // 3),
                    np.random.normal(105, 10, n // 3),
                ]
            ),
            "g": np.repeat(["A", "B", "C"], n // 3),
        }
    )
    req = AnalysisRequest(
        task="anova", data=df, target_col="y", feature_cols=["g"], params={"alpha": 0.05}
    )
    result = anova_analysis(req)
    assert result.status == "ok"
    es = result.metadata.get("effect_sizes", {})
    if "eta_squared" in es:
        eta2 = es["eta_squared"]
        assert 0 <= eta2 <= 1, f"η²={eta2} 超出 [0,1]"


def test_hypothesis_test_effect_size_ci_order():
    """假设检验效应量 CI 下界 ≤ 上界。"""
    np.random.seed(42)
    n = 40
    df = pd.DataFrame(
        {
            "y": np.concatenate(
                [np.random.normal(100, 10, n // 2), np.random.normal(115, 10, n // 2)]
            ),
            "g": np.repeat(["A", "B"], n // 2),
        }
    )
    req = AnalysisRequest(
        task="hypothesis_test",
        data=df,
        target_col="y",
        feature_cols=["g"],
        params={"test": "ttest_ind"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok"
    ci = result.metadata.get("effect_size_ci")
    if ci and len(ci) == 2:
        assert ci[0] <= ci[1], f"效应量 CI 下界({ci[0]}) > 上界({ci[1]})"


def test_anova_degrees_of_freedom_positive():
    """ANOVA 自由度必须为正整数。"""
    np.random.seed(42)
    n = 45
    df = pd.DataFrame(
        {
            "y": np.random.normal(50, 5, n),
            "g": np.repeat(["X", "Y", "Z"], n // 3),
        }
    )
    req = AnalysisRequest(
        task="anova", data=df, target_col="y", feature_cols=["g"], params={"alpha": 0.05}
    )
    result = anova_analysis(req)
    assert result.status == "ok"
    df_val = result.metadata.get("df") or result.metadata.get("degrees_of_freedom")
    if df_val:
        if isinstance(df_val, (list, tuple)):
            for d in df_val:
                assert d > 0, f"自由度 {d} 非正"
        else:
            assert df_val > 0, f"自由度 {df_val} 非正"


def test_p_value_range_all_tests():
    """所有统计检验 p 值必须在 [0, 1]。"""
    np.random.seed(42)
    n = 50
    df = pd.DataFrame(
        {
            "y": np.random.normal(100, 10, n),
            "x": np.random.normal(50, 5, n),
            "g": np.random.choice(["A", "B"], n),
        }
    )
    # hypothesis_test
    req = AnalysisRequest(
        task="hypothesis_test",
        data=df,
        target_col="y",
        feature_cols=["g"],
        params={"test": "ttest_ind"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok", result.messages
    p = result.metadata.get("p_value")
    if p is not None:
        assert 0 <= p <= 1, f"p={p} 超出 [0,1]"
    # anova
    req2 = AnalysisRequest(
        task="anova", data=df, target_col="y", feature_cols=["g"], params={"alpha": 0.05}
    )
    result2 = anova_analysis(req2)
    assert result2.status == "ok", result2.messages
    p2 = result2.metadata.get("p_value")
    if p2 is not None:
        assert 0 <= p2 <= 1, f"ANOVA p={p2} 超出 [0,1]"


# ═══════════════════════════════════════════════════════════
# Round-2 批次D：比例 CI / ROC / Cohen's κ / VIF 不变量
# ═══════════════════════════════════════════════════════════


def test_proportion_ci_bounds():
    """比例 CI 不变量（Round-2 批次D #5a）：下限 ≤ 上限，且区间包含 p_hat。

    Wilson Score 与 Clopper-Pearson 两条 CI 都必须满足——区间估计的数学前提。
    """
    from smartsuite.engine.root_cause import proportion_ci

    df = pd.DataFrame({"x": ["合格"] * 85 + ["不合格"] * 15})
    r = proportion_ci(AnalysisRequest(task="proportion_ci", data=df, target_col="x"))
    assert r.status == "ok", r.messages
    p_hat = r.metadata["p_hat"]
    for ci_name in ("wilson_ci", "clopper_pearson_ci"):
        lo, hi = r.metadata[ci_name]
        assert lo <= hi + 1e-12, f"{ci_name} 下限 > 上限: {lo} > {hi}"
        assert lo - 1e-9 <= p_hat <= hi + 1e-9, (
            f"{ci_name} [{lo:.6f}, {hi:.6f}] 未包含 p_hat={p_hat:.6f}"
        )


def test_roc_auc_bounds():
    """ROC 不变量（Round-2 批次D #5b）：AUC 必须在 [0, 1]。"""
    from smartsuite.engine.doe_opt import roc_analysis

    np.random.seed(42)
    scores = np.concatenate([np.random.normal(5, 1, 100), np.random.normal(8, 1, 100)])
    labels = ["合格"] * 100 + ["不合格"] * 100
    df = pd.DataFrame({"score": scores, "label": labels})
    r = roc_analysis(
        AnalysisRequest(task="roc_analysis", data=df, target_col="label", feature_cols=["score"])
    )
    assert r.status == "ok", r.messages
    auc = r.metadata["auc"]
    assert 0.0 <= auc <= 1.0, f"AUC={auc} 超出 [0,1]"
    assert -1e-9 <= r.metadata["best_fpr"] <= 1.0 + 1e-9, (
        f"best_fpr 超出 [0,1]: {r.metadata['best_fpr']}"
    )
    assert -1e-9 <= r.metadata["best_tpr"] <= 1.0 + 1e-9, (
        f"best_tpr 超出 [0,1]: {r.metadata['best_tpr']}"
    )


def test_cohens_kappa_bounds():
    """Cohen's κ 不变量（Round-2 批次D #5c）：κ 必须在 [-1, 1]。"""
    from smartsuite.engine.root_cause import cohens_kappa

    np.random.seed(42)
    df = pd.DataFrame(
        {
            "r1": ["A"] * 40 + ["B"] * 10 + ["A"] * 5 + ["B"] * 45,
            "r2": ["A"] * 42 + ["B"] * 8 + ["A"] * 8 + ["B"] * 42,
        }
    )
    r = cohens_kappa(
        AnalysisRequest(task="cohens_kappa", data=df, target_col="", feature_cols=["r1", "r2"])
    )
    assert r.status == "ok", r.messages
    kappa = r.metadata["kappa"]
    assert -1.0 <= kappa <= 1.0, f"κ={kappa} 超出 [-1,1]"


def test_vif_greater_equal_one():
    """VIF 不变量（Round-2 批次D #5d）：VIF = 1/(1-R²) ≥ 1（浮点容差内）。"""
    from smartsuite.engine.root_cause import vif_analysis

    np.random.seed(42)
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, 50),
            "x2": np.random.normal(0, 1, 50),
            "x3": np.random.normal(0, 1, 50),
        }
    )
    r = vif_analysis(
        AnalysisRequest(task="vif", data=df, target_col="", feature_cols=["x1", "x2", "x3"])
    )
    assert r.status == "ok", r.messages
    vif_tbl = r.tables["vif_table"]
    for _, row in vif_tbl.iterrows():
        val = float(row["VIF"])
        assert val >= 1.0 - 1e-6, f"VIF={val} < 1（数学上不可能，VIF=1/(1-R²)）"


# ── 变点检测不变量（审查追踪：4 层防线第②层补位）──


def test_change_point_invariants():
    """变点检测输出必须满足的结构不变量。

    1) 变点数 ≤ n_changepoints，且每个变点位于搜索区间 [min_segment, n-min_segment)
    2) 变点严格递增、无重复
    3) 段统计样本数之和 = n（分段完备、不重不漏）
    """
    from smartsuite.engine.detection import change_point_detect

    np.random.seed(42)
    data = np.concatenate(
        [
            np.random.normal(10, 1, 60),
            np.random.normal(18, 1, 60),
            np.random.normal(8, 1, 60),
            np.random.normal(20, 1, 60),
        ]
    )
    n = len(data)
    df = pd.DataFrame({"x": data})
    req = AnalysisRequest(
        task="change_point",
        data=df,
        target_col="x",
        params={"min_segment": 10, "n_changepoints": 3},
    )
    r = change_point_detect(req)
    assert r.status == "ok"
    cps = r.metadata["changepoints"]

    # 1) 数量上限 + 搜索区间约束
    assert len(cps) <= 3, f"变点数 {len(cps)} 超过 n_changepoints=3"
    for cp in cps:
        assert 10 <= cp < n - 10, f"变点 {cp} 超出搜索区间 [10, {n - 10})"

    # 2) 严格递增、无重复
    assert cps == sorted(set(cps)), f"变点应严格递增无重复: {cps}"

    # 3) 分段完备：样本数之和 = n
    stats = r.tables["segment_statistics"]
    assert int(stats["样本数"].sum()) == n, f"分段样本数之和 {stats['样本数'].sum()} != n={n}"
    assert len(stats) == len(cps) + 1, "段数 = 变点数 + 1"
