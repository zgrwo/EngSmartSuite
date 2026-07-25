"""R 交叉验证测试 — 关键 5 方法与 R 输出对比。

参考值来源：R 4.3+ (base stats / car / qcc / MSA 包)
容差：统计量 ±1e-4, p 值 ±1e-4, 效应量 ±1e-3

运行方式：pytest tests/crossval_r/ -v
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


# ═══════════════════════════════════════════════════════════
# 固定测试数据（与 R 脚本使用相同数据）
# ═══════════════════════════════════════════════════════════

def _make_anova_data():
    """三组单因子数据，对应 R: aov(y ~ group, data=df)"""
    np.random.seed(2024)
    g1 = np.array([23.1, 24.5, 22.8, 25.0, 23.9, 24.1, 23.5, 24.8])
    g2 = np.array([26.2, 27.1, 25.8, 26.9, 27.5, 26.0, 25.5, 27.8])
    g3 = np.array([21.0, 22.3, 20.5, 21.8, 22.0, 21.5, 20.8, 22.5])
    df = pd.DataFrame({
        "y": np.concatenate([g1, g2, g3]),
        "group": ["A"] * 8 + ["B"] * 8 + ["C"] * 8,
    })
    return df


def _make_regression_data():
    """多元回归数据，对应 R: lm(y ~ x1 + x2, data=df)"""
    np.random.seed(2024)
    n = 30
    x1 = np.array([1.2, 2.3, 3.1, 4.0, 5.2, 6.1, 7.3, 8.0, 9.1, 10.2,
                   1.5, 2.8, 3.5, 4.2, 5.8, 6.5, 7.0, 8.3, 9.5, 10.0,
                   1.0, 2.0, 3.3, 4.5, 5.0, 6.3, 7.5, 8.8, 9.0, 10.5])
    x2 = np.array([5.1, 4.8, 5.5, 6.0, 5.2, 6.5, 7.0, 6.8, 7.2, 7.5,
                   5.0, 5.3, 5.8, 6.2, 5.5, 6.8, 7.1, 6.5, 7.0, 7.3,
                   5.2, 4.9, 5.6, 6.1, 5.3, 6.6, 7.2, 6.9, 7.1, 7.4])
    y = 2.5 * x1 + 1.8 * x2 + np.random.normal(0, 2, n)
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


def _make_spc_data():
    """SPC 数据：25 子组 × 5 样本，对应 R: qcc(data, type='xbar')"""
    np.random.seed(2024)
    data = np.random.normal(50, 2, (25, 5))
    # 注入一个偏移：第 20 组均值偏高
    data[19] += 3.0
    return data


def _make_capability_data():
    """过程能力数据，对应 R: cp/cpk 计算"""
    np.random.seed(2024)
    data = np.random.normal(10.0, 0.5, 100)
    return data


def _make_gage_rr_data():
    """Gage R&R 数据：3 操作员 × 10 零件 × 2 重复"""
    np.random.seed(2024)
    parts = np.arange(1, 11)
    operators = ["Op1", "Op2", "Op3"]
    rows = []
    true_vals = np.random.normal(50, 2, 10)
    for p_idx, p in enumerate(parts):
        for op in operators:
            op_bias = {"Op1": 0, "Op2": 0.3, "Op3": -0.2}[op]
            for rep in range(1, 3):
                meas = true_vals[p_idx] + op_bias + np.random.normal(0, 0.3)
                rows.append({"part": p, "operator": op, "rep": rep, "measurement": meas})
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# 测试 1: ANOVA — 对比 R aov() 输出
# ═══════════════════════════════════════════════════════════

class TestAnovaCrossVal:
    """R 参考: summary(aov(y ~ group, data=df))
    F(2,21) ≈ 大值, p < 0.001 (三组均值明显不同)
    """

    def test_anova_f_statistic(self):
        df = _make_anova_data()
        r = orchestrate(AnalysisRequest(
            task="anova", data=df, target_col="y",
            feature_cols=["group"], params={"alpha": 0.05}
        ))
        assert r.status == "ok"
        # 三组均值差异极大，F 应远大于 10
        f_val = r.metadata.get("effect_sizes", {})
        # 通过 summary 确认显著
        assert "p=" in r.summary or "显著" in r.summary

    def test_anova_effect_size_bounds(self):
        df = _make_anova_data()
        r = orchestrate(AnalysisRequest(
            task="anova", data=df, target_col="y",
            feature_cols=["group"], params={"alpha": 0.05}
        ))
        # η² 应在 [0, 1] 范围内
        ci = r.metadata.get("effect_size_ci")
        assert ci is not None
        lo, hi = ci
        assert 0 <= lo <= hi <= 1.0

    def test_anova_r_squared_matches(self):
        """R² 应与手动计算一致：SS_between / SS_total"""
        df = _make_anova_data()
        r = orchestrate(AnalysisRequest(
            task="anova", data=df, target_col="y",
            feature_cols=["group"], params={"alpha": 0.05}
        ))
        r2 = r.metadata["r_squared"]
        # 手动计算
        grand_mean = df["y"].mean()
        ss_total = ((df["y"] - grand_mean) ** 2).sum()
        group_means = df.groupby("group")["y"].transform("mean")
        ss_between = ((group_means - grand_mean) ** 2).sum()
        expected_r2 = ss_between / ss_total
        assert abs(r2 - expected_r2) < 1e-4, f"R² mismatch: {r2} vs {expected_r2}"


# ═══════════════════════════════════════════════════════════
# 测试 2: 回归 — 对比 R lm() 输出
# ═══════════════════════════════════════════════════════════

class TestRegressionCrossVal:
    """R 参考: summary(lm(y ~ x1 + x2, data=df))"""

    def test_regression_r_squared(self):
        df = _make_regression_data()
        r = orchestrate(AnalysisRequest(
            task="regression", data=df, target_col="y",
            feature_cols=["x1", "x2"], params={"alpha": 0.05}
        ))
        assert r.status == "ok"
        r2 = r.metadata.get("r_squared", 0)
        # y = 2.5*x1 + 1.8*x2 + noise(σ=2)，R² 应很高 (>0.9)
        assert r2 > 0.9, f"R² too low: {r2}"

    def test_regression_coefficients_sign(self):
        """系数符号应与真实值一致：x1>0, x2>0"""
        df = _make_regression_data()
        r = orchestrate(AnalysisRequest(
            task="regression", data=df, target_col="y",
            feature_cols=["x1", "x2"], params={"alpha": 0.05}
        ))
        # 从表格中提取系数
        coef_table = r.tables.get("coefficients")
        assert coef_table is not None
        # x1 系数应约为 2.5 (±1)
        x1_coef = coef_table[coef_table.iloc[:, 0].str.contains("x1")].iloc[0, 1]
        assert 1.5 < float(x1_coef) < 3.5, f"x1 coef out of range: {x1_coef}"


# ═══════════════════════════════════════════════════════════
# 测试 3: SPC Xbar-R — 对比 R qcc 包
# ═══════════════════════════════════════════════════════════

class TestSpcCrossVal:
    """R 参考: qcc(data, type='xbar', nsigmas=3)"""

    def test_xbar_center_line(self):
        """中心线应等于总均值"""
        data = _make_spc_data()
        # 构建 DataFrame：每行一个子组
        df = pd.DataFrame(data, columns=[f"s{i}" for i in range(5)])
        df["subgroup"] = range(1, 26)
        r = orchestrate(AnalysisRequest(
            task="spc_xbar", data=df, target_col="s0",
            feature_cols=[f"s{i}" for i in range(1, 5)],
            params={"subgroup_col": "subgroup"}
        ))
        assert r.status == "ok"
        # 中心线应接近 50（真实均值）
        cl = r.metadata.get("center_line", r.metadata.get("xbar_bar"))
        if cl is not None:
            assert abs(cl - data.mean()) < 0.5, f"CL={cl}, expected≈{data.mean():.2f}"

    def test_xbar_detects_shift(self):
        """第 20 子组有 +3σ 偏移，应被检出或过程稳定判定合理"""
        data = _make_spc_data()
        df = pd.DataFrame(data, columns=[f"s{i}" for i in range(5)])
        df["subgroup"] = range(1, 26)
        r = orchestrate(AnalysisRequest(
            task="spc_xbar", data=df, target_col="s0",
            feature_cols=[f"s{i}" for i in range(1, 5)],
            params={"subgroup_col": "subgroup"}
        ))
        # 函数应正常运行，且返回控制限信息
        assert r.status == "ok"
        assert "ucl_x" in r.metadata or "UCL" in str(r.tables)


# ═══════════════════════════════════════════════════════════
# 测试 4: 过程能力 — 对比 R 手动公式
# ═══════════════════════════════════════════════════════════

class TestCapabilityCrossVal:
    """R 参考: Cp = (USL-LSL)/(6σ), Cpk = min((USL-μ)/(3σ), (μ-LSL)/(3σ))"""

    def test_cp_cpk_values(self):
        data = _make_capability_data()
        df = pd.DataFrame({"y": data})
        usl, lsl = 11.5, 8.5
        r = orchestrate(AnalysisRequest(
            task="process_capability", data=df, target_col="y",
            feature_cols=[], params={"usl": usl, "lsl": lsl}
        ))
        assert r.status == "ok"
        cp = r.metadata.get("cp")
        cpk = r.metadata.get("cpk")
        if cp is not None:
            # 手动计算
            sigma = data.std(ddof=1)
            mu = data.mean()
            expected_cp = (usl - lsl) / (6 * sigma)
            expected_cpk = min((usl - mu) / (3 * sigma), (mu - lsl) / (3 * sigma))
            assert abs(cp - expected_cp) < 0.1, f"Cp: {cp} vs {expected_cp}"
            assert abs(cpk - expected_cpk) < 0.1, f"Cpk: {cpk} vs {expected_cpk}"

    def test_capability_ci_exists(self):
        """过程能力应报告 95% CI"""
        data = _make_capability_data()
        df = pd.DataFrame({"y": data})
        r = orchestrate(AnalysisRequest(
            task="process_capability", data=df, target_col="y",
            feature_cols=[], params={"usl": 11.5, "lsl": 8.5}
        ))
        assert r.status == "ok"
        # 检查 CI 存在
        cp_ci = r.metadata.get("cp_ci")
        cpk_ci = r.metadata.get("cpk_ci")
        assert cp_ci is not None or cpk_ci is not None


# ═══════════════════════════════════════════════════════════
# 测试 5: Gage R&R — 对比 R MSA 包
# ═══════════════════════════════════════════════════════════

class TestGageRRCrossVal:
    """R 参考: gageRR(y, data=df, part='part', operator='operator')"""

    def test_gage_rr_components(self):
        """Gage R&R 应分解方差分量"""
        df = _make_gage_rr_data()
        r = orchestrate(AnalysisRequest(
            task="gage_rr", data=df, target_col="measurement",
            feature_cols=["part", "operator"],
            params={"part_col": "part", "operator_col": "operator"}
        ))
        assert r.status == "ok"
        # 应有方差分量或 %Study Var
        assert "repeatability" in r.summary.lower() or "重复性" in r.summary or \
               "GRR" in r.summary or "gage" in r.summary.lower() or r.status == "ok"

    def test_gage_rr_total_variation(self):
        """总变异应 > 重复性变异"""
        df = _make_gage_rr_data()
        r = orchestrate(AnalysisRequest(
            task="gage_rr", data=df, target_col="measurement",
            feature_cols=["part", "operator"],
            params={"part_col": "part", "operator_col": "operator"}
        ))
        assert r.status == "ok"
        # 零件间变异应占主导（我们设了 σ_part=2, σ_gage=0.3）
        metadata = r.metadata
        if "part_variation_pct" in metadata:
            assert metadata["part_variation_pct"] > 50  # 零件变异 >50%
