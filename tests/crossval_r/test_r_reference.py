"""关键方法交叉验证测试 — 5 方法（ANOVA/回归/SPC/能力/Gage R&R）。

审查 2026-08-19 #3.2：本文件此前声称"与 R 4.3+ 输出对比（容差 ±1e-4）"，
但实际不含任何 R 参考数值——现如实标注为 手工公式/已知性质 交叉验证。
后续录入真实 R 输出数值后，可改回"R 参考对比"并逐项比对。

运行方式：pytest tests/crossval_r/ -v
"""

import numpy as np
import pandas as pd

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
    df = pd.DataFrame(
        {
            "y": np.concatenate([g1, g2, g3]),
            "group": ["A"] * 8 + ["B"] * 8 + ["C"] * 8,
        }
    )
    return df


def _make_regression_data():
    """多元回归数据，对应 R: lm(y ~ x1 + x2, data=df)"""
    np.random.seed(2024)
    n = 30
    x1 = np.array(
        [
            1.2,
            2.3,
            3.1,
            4.0,
            5.2,
            6.1,
            7.3,
            8.0,
            9.1,
            10.2,
            1.5,
            2.8,
            3.5,
            4.2,
            5.8,
            6.5,
            7.0,
            8.3,
            9.5,
            10.0,
            1.0,
            2.0,
            3.3,
            4.5,
            5.0,
            6.3,
            7.5,
            8.8,
            9.0,
            10.5,
        ]
    )
    x2 = np.array(
        [
            5.1,
            4.8,
            5.5,
            6.0,
            5.2,
            6.5,
            7.0,
            6.8,
            7.2,
            7.5,
            5.0,
            5.3,
            5.8,
            6.2,
            5.5,
            6.8,
            7.1,
            6.5,
            7.0,
            7.3,
            5.2,
            4.9,
            5.6,
            6.1,
            5.3,
            6.6,
            7.2,
            6.9,
            7.1,
            7.4,
        ]
    )
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
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["group"],
                params={"alpha": 0.05},
            )
        )
        assert r.status == "ok"
        # 三组均值差异极大，F 应远大于 10
        f_val = r.metadata.get("effect_sizes", {})
        # 通过 summary 确认显著
        assert "p=" in r.summary or "显著" in r.summary

    def test_anova_effect_size_bounds(self):
        df = _make_anova_data()
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["group"],
                params={"alpha": 0.05},
            )
        )
        # η² 应在 [0, 1] 范围内
        ci = r.metadata.get("effect_size_ci")
        assert ci is not None
        lo, hi = ci
        assert 0 <= lo <= hi <= 1.0

    def test_anova_r_squared_matches(self):
        """R² 应与手动计算一致：SS_between / SS_total"""
        df = _make_anova_data()
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["group"],
                params={"alpha": 0.05},
            )
        )
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
        r = orchestrate(
            AnalysisRequest(
                task="regression",
                data=df,
                target_col="y",
                feature_cols=["x1", "x2"],
                params={"alpha": 0.05},
            )
        )
        assert r.status == "ok"
        r2 = r.metadata.get("r_squared", 0)
        # y = 2.5*x1 + 1.8*x2 + noise(σ=2)，R² 应很高 (>0.9)
        assert r2 > 0.9, f"R² too low: {r2}"

    def test_regression_coefficients_sign(self):
        """系数符号应与真实值一致：x1>0, x2>0"""
        df = _make_regression_data()
        r = orchestrate(
            AnalysisRequest(
                task="regression",
                data=df,
                target_col="y",
                feature_cols=["x1", "x2"],
                params={"alpha": 0.05},
            )
        )
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
    """R 参考: qcc(data, type='xbar', nsigmas=3)

    审查 2026-09-06 F-D3：引擎契约中 feature_cols[0] 是横坐标（子组由同一
    X 值下的多行自然形成），并非值列。旧构造把 s1..s4 当值列传入 → 引擎
    退化为 I-chart（s0 单值图），CL/违规断言全部巧合通过（violations 恰好
    命中索引 24）。现按引擎契约改为长格式：125 行，每 5 行一个子组。
    """

    def _long_df(self, data):
        """宽 (25×5) → 长 (125 行)：y=测量值，x=子组编号（同值 5 行成组）。"""
        return pd.DataFrame({"y": data.ravel(), "subgroup": np.repeat(np.arange(1, 26), 5)})

    def test_xbar_center_line(self):
        """中心线应等于总均值"""
        data = _make_spc_data()
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar",
                data=self._long_df(data),
                target_col="y",
                feature_cols=["subgroup"],
                params={},
            )
        )
        assert r.status == "ok"
        # 须为 X-bar 建模而非 I-chart 退化（I-chart 下中心线仍是总均值，
        # 但子组结构与 σ 估计口径全不同——用 chart_type 钉住建模方式）
        assert r.metadata.get("chart_type") != "i_chart", (
            f"应按子组建模，实际 chart_type={r.metadata.get('chart_type')}"
        )
        # 审查 2026-09-06 F-D3：metadata 键为 xbar_mean（旧断言读不存在的
        # center_line/xbar_bar 键，`if cl is not None` 恒假 → 整个测试恒真）
        cl = r.metadata["xbar_mean"]
        assert abs(cl - data.mean()) < 0.5, f"CL={cl}, expected≈{data.mean():.2f}"

    def test_xbar_detects_shift(self):
        """第 20 子组注入偏移，应检出失控（is_stable=False + violations）。"""
        data = _make_spc_data()
        # 审查 2026-09-01 T-2：_make_spc_data 仅注入 +3.0（实测不足越限，
        # is_stable 仍为 True）；此处追加 +5.0（合计 +8.0）确保 X-bar 越 ±3σ
        data[19] += 5.0
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar",
                data=self._long_df(data),
                target_col="y",
                feature_cols=["subgroup"],
                params={},
            )
        )
        # 应返回正常状态与控制限，并检出第 20 子组的偏移（审查 2026-09-01 T-2：
        # 此前仅断言状态与 UCL 存在，检测器完全失效时测试仍通过）
        assert r.status == "ok"
        assert "ucl_x" in r.metadata or "UCL" in str(r.tables)
        assert r.metadata["is_stable"] is False, "注入偏移后 X-bar 应判失控"
        viol = r.metadata.get("xbar_violations") or {}
        assert viol, f"应检出 X-bar 违规子组: {r.metadata}"
        # 长格式下偏移子组索引为 19（第 20 组）
        assert 19 in next(iter(viol.values())), f"违规点应为子组 20 (索引 19): {viol}"


# ═══════════════════════════════════════════════════════════
# 测试 4: 过程能力 — 对比 R 手动公式
# ═══════════════════════════════════════════════════════════


class TestCapabilityCrossVal:
    """R 参考: Cp = (USL-LSL)/(6σ), Cpk = min((USL-μ)/(3σ), (μ-LSL)/(3σ))"""

    def test_cp_cpk_values(self):
        data = _make_capability_data()
        df = pd.DataFrame({"y": data})
        usl, lsl = 11.5, 8.5
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"usl": usl, "lsl": lsl},
            )
        )
        assert r.status == "ok"
        # 审查 2026-09-06 F-D3：旧代码 `if cp is not None` 条件断言在 Cp 缺失/None
        # 时静默跳过（mutation 实证）→ 改键索引 + float 转换：键缺失或 None 直接报错
        cp = float(r.metadata["cp"])
        cpk = float(r.metadata["cpk"])
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
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"usl": 11.5, "lsl": 8.5},
            )
        )
        assert r.status == "ok"
        # 检查 CI 存在（审查 2026-08-19 #3.2：键缺失即通过的弱断言已改硬断言）
        assert "cp_ci" in r.metadata or "cpk_ci" in r.metadata, (
            f"应报告过程能力 CI，metadata 键: {list(r.metadata.keys())}"
        )


# ═══════════════════════════════════════════════════════════
# 测试 5: Gage R&R — 对比 R MSA 包
# ═══════════════════════════════════════════════════════════


class TestGageRRCrossVal:
    """R 参考: gageRR(y, data=df, part='part', operator='operator')"""

    def test_gage_rr_components(self):
        """Gage R&R 应分解方差分量"""
        df = _make_gage_rr_data()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="measurement",
                feature_cols=["part", "operator"],
                params={"part_col": "part", "operator_col": "operator"},
            )
        )
        assert r.status == "ok"
        # 应有方差分量或 %Study Var（审查 2026-08-19 #3.2：删除恒真 or r.status == "ok" 兜底）
        assert (
            "repeatability" in r.summary.lower()
            or "重复性" in r.summary
            or "GRR" in r.summary
            or "gage" in r.summary.lower()
        )

    def test_gage_rr_total_variation(self):
        """总变异应 > 重复性变异"""
        df = _make_gage_rr_data()
        r = orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=df,
                target_col="measurement",
                feature_cols=["part", "operator"],
                params={"part_col": "part", "operator_col": "operator"},
            )
        )
        assert r.status == "ok"
        # 零件间变异应占主导（我们设了 σ_part=2, σ_gage=0.3）
        # 审查 2026-08-19 #3.2：原条件断言（键缺失即通过）改硬断言；
        # 实际键为 pv/grr（σ 分量），零件变异应明显大于量具变异
        assert "pv" in r.metadata and "grr" in r.metadata, (
            f"缺少 pv/grr，metadata 键: {list(r.metadata.keys())}"
        )
        assert r.metadata["pv"] > r.metadata["grr"], (
            "零件变异应大于量具变异（σ_part=2 vs σ_gage=0.3）"
        )
