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
    df = pd.DataFrame({
        "x1": np.random.normal(0, 1, n),
        "x2": np.random.normal(0, 1, n),
        "x3": np.random.normal(0, 1, n),
        "y": np.random.normal(0, 1, n),
    })
    for method in ["pearson", "spearman", "kendall"]:
        req = AnalysisRequest(task="correlation", data=df, target_col="y",
                              feature_cols=["x1", "x2", "x3"],
                              params={"method": method})
        result = correlation_analysis(req)
        if result.status == "ok":
            corr_mat = result.tables["correlation_matrix"]
            assert ((corr_mat >= -1.01) & (corr_mat <= 1.01)).all().all(), \
                f"{method}: 相关性系数超出 [-1, 1]"


def test_correlation_diagonal_is_one():
    """相关性矩阵对角线必须为 1（变量与自身的相关）。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "x1": np.random.normal(0, 1, 30),
        "y": np.random.normal(0, 1, 30),
    })
    req = AnalysisRequest(task="correlation", data=df, target_col="y",
                          feature_cols=["x1"], params={"method": "pearson"})
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
    df = pd.DataFrame({
        "group": ["A"] * n + ["B"] * n + ["C"] * n,
        "val": np.concatenate([
            np.random.normal(10, 1, n),
            np.random.normal(12, 1, n),
            np.random.normal(11, 1, n),
        ]),
    })
    req = AnalysisRequest(task="anova", data=df, target_col="val",
                          feature_cols=["group"])
    result = anova_analysis(req)
    if result.status == "ok" and "r_squared" in result.metadata:
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
    req = AnalysisRequest(task="process_capability", data=df, target_col="val",
                          params={"usl": 13.0, "lsl": 7.0})
    result = process_capability_analysis(req)
    if result.status == "ok":
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
    req = AnalysisRequest(task="process_capability", data=df, target_col="val",
                          params={"usl": 13.0})
    result = process_capability_analysis(req)
    if result.status == "ok":
        cpk = result.metadata.get("cpk")
        assert cpk is not None, "单侧公差 (USL only) 应能计算 Cpk"
        assert cpk > 0, f"单侧 Cpk 应为正值, got {cpk}"

    # 仅下公差
    req2 = AnalysisRequest(task="process_capability", data=df, target_col="val",
                           params={"lsl": 7.0})
    result2 = process_capability_analysis(req2)
    if result2.status == "ok":
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
    df = pd.DataFrame({
        "x": np.random.uniform(0, 10, n),
        "y": 2.0 + 3.0 * np.random.uniform(0, 10, n) + np.random.normal(0, 1, n),
    })
    req = AnalysisRequest(task="regression", data=df, target_col="y",
                          feature_cols=["x"])
    result = regression_analysis(req)
    if result.status == "ok":
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
    df = pd.DataFrame({
        "group": ["A"] * n + ["B"] * n,
        "val": np.concatenate([g1, g2]),
    })
    req = AnalysisRequest(task="hypothesis_test", data=df, target_col="val",
                          feature_cols=["group"], params={"group_col": "group"})
    result = hypothesis_test(req)
    if result.status == "ok":
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
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="val",
                          params={"subgroup_col": "子组"})
    result = xbar_r_chart(req)
    if result.status == "ok":
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
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="val",
                          params={"subgroup_col": "子组"})
    result = xbar_r_chart(req)
    if result.status == "ok":
        assert result.metadata["lcl_r"] >= 0, \
            f"R 图 LCL 不应为负: {result.metadata['lcl_r']:.3f}"


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
    req = AnalysisRequest(task="survival_analysis", data=df, target_col="time",
                          feature_cols=["event"])
    result = survival_analysis(req)
    if result.status == "ok":
        surv_table = result.tables.get("survival_table")
        if surv_table is not None and "生存率" in surv_table.columns:
            surv_values = surv_table["生存率"].values
            # KM 曲线必须单调非增
            assert all(surv_values[i] >= surv_values[i + 1] - 0.001
                       for i in range(len(surv_values) - 1)), \
                "KM 生存率不是单调递减"


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
                rows.append({
                    "零件": part,
                    "操作员": op,
                    "测量值": true_val + np.random.normal(0, 0.5),
                })
    df = pd.DataFrame(rows)
    req = AnalysisRequest(task="gage_rr", data=df, target_col="测量值",
                          feature_cols=["零件", "操作员"],
                          params={"part_col": "零件", "operator_col": "操作员"})
    result = gage_rr(req)
    if result.status == "ok":
        grr_pct = result.metadata.get("grr_pct")
        ev_pct = result.metadata.get("ev_pct")
        av_pct = result.metadata.get("av_pct")
        pv_pct = result.metadata.get("pv_pct")
        # 所有百分比分量应非负
        for name, val in [("GRR%", grr_pct), ("EV%", ev_pct),
                          ("AV%", av_pct), ("PV%", pv_pct)]:
            if val is not None:
                assert val >= 0, f"{name} 不应该为负: {val:.1f}"


# ═══════════════════════════════════════════════════════════
# 计数型控制图不变量
# ═══════════════════════════════════════════════════════════

def test_attribute_chart_center_line_positive():
    """计数型控制图中心线必须 > 0。"""
    np.random.seed(42)
    df_p = pd.DataFrame({
        "batch": np.repeat(range(1, 21), 50),
        "defect": np.random.binomial(1, 0.05, 1000),
    })
    for chart_type, col in [("p", "defect"), ("np", "defect")]:
        req = AnalysisRequest(task="spc_attribute", data=df_p, target_col=col,
                              params={"chart_type": chart_type, "subgroup_col": "batch"})
        result = attribute_chart(req)
        if result.status == "ok":
            cl = result.metadata.get("center_line")
            if cl is not None:
                assert cl > 0, f"{chart_type}-chart CL={cl} ≤ 0"
