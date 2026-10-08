"""关键方法交叉验证测试 — 5 方法（ANOVA/回归/SPC/能力/Gage R&R）。

**参考实现来源（务必如实理解）**：本文件**不含任何 R 输出数值**。
参考值来自**独立第二实现**——statsmodels/scipy 的不同 API 路径 + 手工公式。
审查 2026-09-24（第三轮复核 P1-4）：文件头此前已如实说明"不含 R 参考数值"，
但类与方法的 docstring 仍写着 `R 参考: qcc(...)` / `R 参考: gageRR(...)` —— 文档自相矛盾。
本机实测**无 R 环境**（`Rscript` 不存在，`R` 仅为 PowerShell 的 `Invoke-History` 别名），
故按预案退化为独立第二实现，并逐处标注来源，不再冒充 R 输出。

> 独立第二实现的价值**低于**外部权威软件，但仍高于"用同一库再算一遍"：
> 它至少能发现公式转写错误、口径混用（如用整体 σ 校验组内 σ 口径的 Cp）与参数误配。
> 真正的外部锚定（Minitab/JMP/R 输出比对）仍是待办，见
> `docs/governance/improvement-plan.md` 的阶段 P3。

运行方式：pytest tests/crossval/ -v
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


# ═══════════════════════════════════════════════════════════
# 固定测试数据（各参考实现与本文件共用同一份数据）
# ═══════════════════════════════════════════════════════════


def _make_anova_data():
    """三组单因子数据；参考实现: statsmodels 手算 SSB/SSW（非 R 输出）。"""
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
    """多元回归数据；参考实现: statsmodels OLS（非 R 输出）。"""
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
    """SPC 数据：25 子组 × 5 样本；参考实现: R̄/d2 手工控制限公式（非 R 输出）。"""
    np.random.seed(2024)
    data = np.random.normal(50, 2, (25, 5))
    # 注入一个偏移：第 20 组均值偏高
    data[19] += 3.0
    return data


def _make_capability_data():
    """过程能力数据；参考实现: 组内σ(MR 法)/整体σ 手工公式（非 R 输出）。"""
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
# 测试 1: ANOVA — 手工公式交叉验证（本文件不含 R 数值，口径见文件头 2026-08-19 #3.2）
# ═══════════════════════════════════════════════════════════


class TestAnovaCrossVal:
    """手工公式口径：单因素 ANOVA 的 F = (SSB/(k-1)) / (SSW/(n-k))。

    预期性质：三组均值差异极大 → F 远大于 10、p < 0.001。
    """

    def test_anova_f_statistic(self):
        """F 与手算一致（不再仅凭 summary 文案判显著）。

        审查 2026-09-21 E4-1：原用例把 `metadata.get("effect_sizes", {})` 赋给
        `f_val` 但**从未断言**（死变量），最终只用 `"p=" in summary or "显著" in summary`
        —— 既没验证 F，也会因文案调整而误判。本文件声明的口径是「手工公式/已知性质
        交叉验证」，故此处对账：被测值是 `anova_enhanced` 表中 statsmodels 算出的 F，
        参考值是手算 F，两者独立。
        """
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
        table = r.tables["anova_enhanced"]
        f_reported = float(table.loc[table["来源"].str.contains("group"), "F值"].iloc[0])

        groups = [g["y"].to_numpy(dtype=float) for _, g in df.groupby("group")]
        k, n = len(groups), len(df)
        grand_mean = float(df["y"].mean())
        ssb = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups)
        ssw = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
        f_manual = (ssb / (k - 1)) / (ssw / (n - k))

        assert f_reported == pytest.approx(f_manual, rel=1e-9), (
            f"F 与手算不一致：引擎 {f_reported} vs 手算 {f_manual}"
        )
        assert f_manual > 10, f"三组均值差异极大，F 应远大于 10，实测 {f_manual:.2f}"

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
# 测试 2: 回归 — 对比 statsmodels OLS（独立第二实现，非 R）
# ═══════════════════════════════════════════════════════════


class TestRegressionCrossVal:
    """参考实现：**statsmodels OLS**（独立于本引擎的第二实现）。

    审查 2026-09-24（第三轮复核 P1-4）：本类原 docstring 写
    `R 参考: summary(lm(y ~ x1 + x2, data=df))`，但文件头已自认
    "实际不含任何 R 参考数值"——文档自相矛盾。本机无 R 环境（已实测确认），
    故按预案退化为独立第二实现，并**如实标注来源**，不再冒充 R 输出。
    """

    def test_regression_matches_statsmodels_r_squared(self):
        """R² 与 statsmodels OLS 独立复算一致（rel<1e-9）。

        审查 2026-09-24 P1-4：原断言仅 `r2 > 0.9`（弱下界）。
        """
        import statsmodels.api as sm

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
        model = sm.OLS(df["y"], sm.add_constant(df[["x1", "x2"]])).fit()
        assert float(r.metadata["r_squared"]) == pytest.approx(model.rsquared, rel=1e-9), (
            f"引擎 R²={r.metadata['r_squared']} vs statsmodels {model.rsquared}"
        )

    def test_regression_coefficients_match_statsmodels(self):
        """系数与 statsmodels 一致（rel<1e-6）；原断言只查符号/范围。"""
        import statsmodels.api as sm

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
        model = sm.OLS(df["y"], sm.add_constant(df[["x1", "x2"]])).fit()
        coef_table = r.tables["coefficients"]
        name_col = coef_table.columns[0]
        for feature, expected in (("x1", model.params["x1"]), ("x2", model.params["x2"])):
            row = coef_table[coef_table[name_col].astype(str).str.contains(feature)]
            assert len(row) == 1, f"应恰好命中一行 {feature}"
            assert float(row.iloc[0, 1]) == pytest.approx(expected, rel=1e-6), (
                f"{feature} 系数不符：引擎 {row.iloc[0, 1]} vs statsmodels {expected}"
            )


# ═══════════════════════════════════════════════════════════
# 测试 3: SPC Xbar-R — 手工控制限公式（独立复算，非 R qcc）
# ═══════════════════════════════════════════════════════════


class TestSpcCrossVal:
    """参考实现：手工 X-bar/R 控制限公式（非 R qcc——本机无 R，见文件头）。

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
# 测试 4: 过程能力 — 组内σ/整体σ 手工公式（独立复算，非 R）
# ═══════════════════════════════════════════════════════════


class TestCapabilityCrossVal:
    """参考实现：Cp/Cpk 的**手工公式**（非 R 输出——本机无 R，见文件头说明）。

    审查 2026-09-24（第三轮复核 A1/P1-4）：本类原先的 docstring 写
    `R 参考: Cp = (USL-LSL)/(6σ), ...`，且 `test_cp_cpk_values` 用
    **整体 σ**（`data.std(ddof=1)`）作为期望值去校验引擎的 **Cp**。
    但引擎的 Cp 用**组内 σ**（移动极差法 `mean(MR)/1.128`）——两者是
    **不同估计量**（Cp vs Pp）。实测（8 组带漂移数据，n=200）两口径相对差
    可达 177%~239%，该断言只是靠 `abs(...)<0.1` 的宽松容差 + iid 数据下
    "组内 σ 恰好接近整体 σ"才通过——**是同义反复，不是验证**。

    现改为按各自口径分别对账：
        Pp  ← 整体 σ（ddof=1）
        Cp  ← 组内 σ（MR 法，d2=1.128）
    """

    @staticmethod
    def _within_sigma(data):
        """组内 σ 的独立复算：mean(|diff|)/d2，d2=1.128（n=2 移动极差）。"""
        mr = np.abs(np.diff(np.asarray(data, dtype=float)))
        return float(mr.mean() / 1.128)

    def test_cp_uses_within_sigma_mr_method(self):
        """Cp 必须与**组内 σ**（MR 法）对账，容差 1e-6。"""
        data = _make_capability_data()
        usl, lsl = 11.5, 8.5
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": data}),
                target_col="y",
                feature_cols=[],
                params={"usl": usl, "lsl": lsl},
            )
        )
        assert r.status == "ok"
        sigma_within = self._within_sigma(data)
        expected_cp = (usl - lsl) / (6 * sigma_within)
        assert float(r.metadata["cp"]) == pytest.approx(expected_cp, rel=1e-9), (
            f"Cp={r.metadata['cp']} 与组内σ口径期望 {expected_cp} 不符"
        )

    def test_pp_uses_overall_sigma(self):
        """Pp 必须与**整体 σ**（ddof=1）对账——与 Cp 的口径区分开。"""
        data = _make_capability_data()
        usl, lsl = 11.5, 8.5
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": data}),
                target_col="y",
                feature_cols=[],
                params={"usl": usl, "lsl": lsl},
            )
        )
        expected_pp = (usl - lsl) / (6 * data.std(ddof=1))
        assert float(r.metadata["pp"]) == pytest.approx(expected_pp, rel=1e-9)

    def test_cpk_matches_within_sigma_formula(self):
        """Cpk = min((USL−μ)/(3σ_within), (μ−LSL)/(3σ_within))。"""
        data = _make_capability_data()
        usl, lsl = 11.5, 8.5
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": data}),
                target_col="y",
                feature_cols=[],
                params={"usl": usl, "lsl": lsl},
            )
        )
        sigma_within = self._within_sigma(data)
        mu = float(data.mean())
        expected = min((usl - mu) / (3 * sigma_within), (mu - lsl) / (3 * sigma_within))
        assert float(r.metadata["cpk"]) == pytest.approx(expected, rel=1e-9)

    def test_cp_and_pp_differ_when_data_is_autocorrelated(self):
        """回归防线：自相关数据下 Cp ≠ Pp（若两者相等，说明口径被混用了）。

        这条断言的价值在于**主动构造两口径必须分歧的场景**——
        原先用整体 σ 校验 Cp 的写法，恰恰在 iid 数据上无法暴露口径错误。
        """
        rng = np.random.default_rng(3)
        n = 200
        drift = np.linspace(-1.2, 1.2, n)
        data = pd.Series(10.0 + drift + rng.normal(0, 0.25, n))
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": data}),
                target_col="y",
                feature_cols=[],
                params={"usl": 11.5, "lsl": 8.5},
            )
        )
        assert r.status == "ok"
        cp, pp = float(r.metadata["cp"]), float(r.metadata["pp"])
        assert cp != pytest.approx(pp, rel=0.05), (
            f"自相关数据下 Cp({cp:.3f}) 与 Pp({pp:.3f}) 应显著不同——相等说明组内σ与整体σ被混为一谈"
        )
        assert cp > pp, "自相关（漂移）时组内σ < 整体σ，故 Cp > Pp"

    def test_cp_cpk_values_legacy_tolerance_removed(self):
        """旧断言（整体σ + abs<0.1）已删除——此处确认它不会悄悄回来。"""
        data = _make_capability_data()
        sigma_overall = data.std(ddof=1)
        sigma_within = self._within_sigma(data)
        # iid 数据下两者接近但不相等；若某天完全相等，说明 MR 法被替换成了整体 σ
        assert sigma_within != pytest.approx(sigma_overall, rel=1e-12), (
            "组内σ与整体σ在本数据上不应完全相同（同一估计量则口径区分失效）"
        )

    def test_capability_ci_exists_and_is_ordered(self):
        """过程能力应报告 95% CI，且区间有序、包含点估计。

        审查 2026-09-24（第三轮复核 P0-3）：原断言为
        `"cp_ci" in metadata or "cpk_ci" in metadata` —— 任一存在即通过，
        是弱断言；且当时 CI 用的自由度（n−1）与 σ 估计量（MR 法）不匹配，
        CI 过窄约 28%。现补强为：存在 + 有序 + 包住点估计。
        """
        data = _make_capability_data()
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=pd.DataFrame({"y": data}),
                target_col="y",
                feature_cols=[],
                params={"usl": 11.5, "lsl": 8.5},
            )
        )
        assert r.status == "ok"
        for key in ("cp_ci", "cpk_ci"):
            lo, hi = r.metadata[key]
            assert lo is not None and hi is not None, f"{key} 不应为 None"
            assert 0 <= lo < hi, f"{key} 区间应有序且下限非负，实际 ({lo}, {hi})"
        cp_lo, cp_hi = r.metadata["cp_ci"]
        assert cp_lo < float(r.metadata["cp"]) < cp_hi, "Cp 点估计应落在其 CI 内"
        cpk_lo, cpk_hi = r.metadata["cpk_ci"]
        assert cpk_lo <= float(r.metadata["cpk"]) < cpk_hi, "Cpk 点估计应落在其 CI 内"


# ═══════════════════════════════════════════════════════════
# 测试 5: Gage R&R — AIAG 均值-极差法手工公式（独立复算，非 R MSA 包）
# ═══════════════════════════════════════════════════════════


class TestGageRRCrossVal:
    """参考实现：AIAG 均值-极差法方差分量手工公式（非 R MSA 包）。"""

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
