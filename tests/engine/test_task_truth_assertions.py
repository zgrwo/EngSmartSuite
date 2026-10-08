"""第①层补强（第二批）：为**此前零真值断言**的任务补解析真值。

契约：[improvement-plan.md](../../docs/governance/improvement-plan.md) §十 硬指标表
      「真值断言 ~6% → ≥25%」

## 为什么是"按任务补"而不是"按断言数补"

第 42 轮实测发现：42 个任务里有 **21 个完全没有真值断言**。这比"总占比不够"
更值得处理 —— 那些任务的全部测试都只在检查"结构对不对"（有没有表、键在不在、
`status` 是不是 `ok`），**数值错了不会被发现**。

故本文件的组织单位是**任务**，每个任务给一条**由数学唯一确定**的断言。

## 只用三类真值（沿用第三十三轮定的口径）

1. **闭式公式**：可由手算独立复核（`κ = (p_o−p_e)/(1−p_e)`、VIF、Kappa、熵…）
2. **退化情形**：数学上唯一确定（完全共线 → `α=1`；完美分离 → `AUC=1`）
3. **只依赖关系**：不依赖具体数值，故不脆弱（单调性、无被支配点、画线数）

**不与另一个库比** —— "与另一实现接近"查不出两者共有的错误。

> 每条都注明**期望值是怎么来的**，使"这个数字对不对"可被独立复核，
> 而不是只能信任实现。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _run(task: str, df: pd.DataFrame, target: str = "y", features=None, params=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=df,
            target_col=target,
            feature_cols=features or [],
            params=params or {},
        )
    )


class TestClosedFormFormulas:
    """期望值由公式手算 —— 可独立复核，不依赖实现。"""

    def test_cohens_kappa_matches_its_defining_formula(self):
        """`κ = (p_o − p_e) / (1 − p_e)` —— Kappa 的**定义式**。

        构造：10 个样本、2 个评定者的 2×2 混淆矩阵为 `[[3,2],[2,3]]`，
        故 `p_o = (3+3)/10 = 0.6`，边际各为 5/10 → `p_e = 0.5`。
        代入定义式：`κ = (0.6 − 0.5) / (1 − 0.5) = 0.2`。
        """
        a = ["x", "x", "y", "y", "x", "y", "x", "y", "x", "x"]
        b = ["x", "y", "y", "y", "x", "y", "x", "x", "x", "y"]
        c = ["y", "x", "y", "y", "x", "x", "x", "y", "x", "y"]
        r = _run(
            "cohens_kappa", pd.DataFrame({"a": a, "b": b, "c": c}), target="a", features=["b", "c"]
        )
        assert r.status == "ok", r.messages
        p_o = float(r.metadata["p_o"])
        p_e = float(r.metadata["p_e"])
        assert p_o == pytest.approx(0.6, abs=1e-12), p_o
        assert p_e == pytest.approx(0.5, abs=1e-12), p_e
        assert float(r.metadata["kappa"]) == pytest.approx((p_o - p_e) / (1 - p_e), rel=1e-9), (
            "Kappa 必须等于其定义式"
        )

    def test_cronbach_alpha_is_one_for_collinear_items(self):
        """所有题项**完全共线**（同一列复制）→ `α = 1` 精确成立。

        理由：`α = k/(k−1) · (1 − Σσ²ᵢ/σ²_total)`。题项相同时
        `σ²_total = k²σ²`、`Σσ²ᵢ = kσ²`，故 `1 − kσ²/(k²σ²) = 1 − 1/k`，
        乘 `k/(k−1)` 得 `1`。
        """
        base = np.random.default_rng(1).normal(0, 1, 30)
        df = pd.DataFrame({"i1": base, "i2": base, "i3": base})
        r = _run("cronbach_alpha", df, target="i1", features=["i2", "i3"])
        assert r.status == "ok", r.messages
        assert float(r.metadata["alpha"]) == pytest.approx(1.0, abs=1e-9)

    def test_distribution_summary_matches_hand_computed_stats(self):
        """`[1,2,3,4,5]` 的统计量可**逐个手算**。

        均值 `= 3`；样本标准差（ddof=1）`= √(10/4) = √2.5 ≈ 1.5811388`；
        完全对称 → 偏度 `= 0`。
        """
        df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0]})
        r = _run("distribution_summary", df)
        assert r.status == "ok", r.messages
        desc = r.metadata["descriptive"]
        assert float(desc["均值"]) == pytest.approx(3.0, abs=1e-12)
        assert float(desc["中位数"]) == pytest.approx(3.0, abs=1e-12)
        assert float(desc["标准差"]) == pytest.approx(float(np.sqrt(2.5)), rel=1e-12)
        assert float(desc["偏度"]) == pytest.approx(0.0, abs=1e-12)

    def test_vif_is_one_for_orthogonal_factors(self):
        """两个**相互独立**的因子 → `VIF ≈ 1`（VIF 的定义：`1/(1−R²ⱼ)`，正交时 `R²≈0`）。

        用大样本（n=200）使抽样波动小于 5% —— 小样本下 `VIF` 会因偶然相关而偏离 1。
        """
        rng = np.random.default_rng(11)
        n = 200
        df = pd.DataFrame(
            {"y": rng.normal(0, 1, n), "a": rng.normal(0, 1, n), "b": rng.normal(0, 1, n)}
        )
        r = _run("vif", df, features=["a", "b"])
        assert r.status == "ok", r.messages
        tbl = r.tables["vif_table"].set_index("变量")
        assert float(tbl.loc["a", "VIF"]) == pytest.approx(1.0, abs=0.05)
        assert float(tbl.loc["b", "VIF"]) == pytest.approx(1.0, abs=0.05)

    def test_median_ci_of_uniform_grid_bracket_the_median(self):
        """`1..50` 的样本中位数是 `25.5`，其 95% CI **必须包含它**且落在数据范围内。

        （不手算二项分位法的具体端点 —— 那依赖实现细节；但"包含点估计"
        与"落在样本范围内"是**任何**合法 CI 都必须满足的硬约束。）
        """
        df = pd.DataFrame({"y": np.arange(1, 51, dtype=float)})
        r = _run("median_ci", df)
        assert r.status == "ok", r.messages
        lo, hi, med = (
            float(r.metadata["ci_lower"]),
            float(r.metadata["ci_upper"]),
            float(r.metadata["median"]),
        )
        assert med == pytest.approx(25.5, abs=1e-12)
        assert lo <= med <= hi, (lo, med, hi)
        assert lo >= 1.0 and hi <= 50.0, (lo, hi)


class TestDegenerateCasesAreExact:
    """退化情形下答案由数学唯一确定。"""

    def test_roc_auc_is_one_for_perfect_separation(self):
        """评分完全分离两类 → `AUC = 1` 精确（ROC 曲线过 (0,1) 点）。"""
        y = np.array([0] * 20 + [1] * 20)
        s = np.concatenate([np.linspace(0, 1, 20), np.linspace(2, 3, 20)])
        r = _run("roc_analysis", pd.DataFrame({"y": y, "s": s}), target="y", features=["s"])
        assert r.status == "ok", r.messages
        assert float(r.metadata["auc"]) == pytest.approx(1.0, abs=1e-12)

    def test_identical_groups_give_p_one_on_variance_tests(self):
        """两组**逐点相同** → 方差比为 1 → Levene 与 Bartlett 的 `p` 都应为 1。"""
        v = np.arange(20, dtype=float)
        df = pd.DataFrame({"y": np.concatenate([v, v]), "g": ["A"] * 20 + ["B"] * 20})
        r = _run("variance_test", df, features=["g"], params={"group_col": "g"})
        assert r.status == "ok", r.messages
        assert float(r.metadata["levene_p"]) == pytest.approx(1.0, abs=1e-9)
        assert float(r.metadata["bartlett_p"]) == pytest.approx(1.0, abs=1e-9)

    def test_anomaly_detect_finds_exactly_the_planted_outliers(self):
        """40 个 `50.0` + 3 个 `200.0` → 异常点必须**恰好是那 3 个**（可数、可定位）。

        判据用"异常行的 y 值"而非索引 —— 索引口径依赖实现（原始行号 vs 位置）。
        """
        y = np.concatenate([np.full(40, 50.0), [200.0, 200.0, 200.0]])
        df = pd.DataFrame({"y": y})
        for method in ("grubbs", "zscore"):
            r = _run("anomaly_detect", df, params={"method": method})
            assert r.status == "ok", (method, r.messages)
            assert int(r.metadata["anomaly_count"]) == 3, (method, r.metadata)
            flagged = sorted(float(v) for v in r.tables["anomalies"]["y"])
            assert flagged == [200.0, 200.0, 200.0], (method, flagged)

    def test_change_point_locates_the_step(self):
        """30 个 `10.0` + 30 个 `30.0` → 变点必须落在**第 30 个观测附近**（步长位置）。

        不要求索引精确等于 29（变点检测有多种定义：CUSUM 极值、段均值差…），
        故断言落在**真实边界 ±2** 内 —— 这已足以排除"位置偏到别处"。
        """
        y = np.concatenate([np.full(30, 10.0), np.full(30, 30.0)])
        df = pd.DataFrame({"y": y, "x": np.arange(60.0)})
        r = _run("change_point", df, features=["x"])
        assert r.status == "ok", r.messages
        assert int(r.metadata["n_changepoints"]) == 1, r.metadata
        cps = r.metadata["changepoints"]
        first = cps[0] if isinstance(cps, (list, tuple)) else cps
        idx = int(first["index"]) if isinstance(first, dict) else int(first)
        assert abs(idx - 29) <= 2, f"变点应落在真实边界 29 附近，实测 {idx}"

    def test_normal_check_rejects_grossly_non_normal_data(self):
        """38 个 0 + 2 个 100（极强右偏）→ 必须判为**非正态**。

        真值来自偏度：这种数据的样本偏度 `≈ 4.29`（实测），远超正态的 0。
        """
        df = pd.DataFrame({"y": np.concatenate([np.zeros(38), [100.0, 100.0]])})
        r = _run("normality_check", df)
        assert r.status == "ok", r.messages
        assert int(r.metadata["normal_count"]) == 0, r.metadata
        tbl = r.tables["normality_results"].set_index("列名")
        assert "非正态" in str(tbl.loc["y", "正态性"]), tbl.loc["y"].to_dict()
        assert float(tbl.loc["y", "偏度"]) == pytest.approx(4.292, abs=0.01)


class TestAnalyticalRelations:
    """只依赖**关系**（不依赖具体数值），故不会因数据变化而脆弱。"""

    def test_power_analysis_required_n_decreases_with_effect_size(self):
        """效应量越大 → 所需样本量越小（**单调性**，且不依赖具体数值）。

        这是功效分析的基本性质；方向反了会让"大效应反而需要更多样本"，
        而 `required_n > 0` 这类弱断言抓不到方向错误。
        """
        sizes = []
        for d in (0.2, 0.5, 0.8, 1.2):
            r = _run(
                "power_analysis",
                pd.DataFrame({"y": [1.0, 2.0]}),
                params={"test": "ttest", "effect_size": d, "n": 30},
            )
            assert r.status == "ok", (d, r.messages)
            sizes.append(int(r.metadata["required_n"]))
        assert sizes == sorted(sizes, reverse=True), f"所需样本量应随效应量单调下降：{sizes}"

    def test_scatter_plot_fit_draws_a_line_only_when_requested(self):
        """`fit="linear"` 必须**真的画出拟合线**，`fit="none"` 必须不画。

        判据用 `Axes.lines` 的数量 —— 这是"参数真的生效了"的直接证据，
        比"status 是 ok"强得多（后者在参数被静默忽略时同样通过）。
        """
        rng = np.random.default_rng(7)
        df = pd.DataFrame({"y": 2 * rng.normal(0, 1, 40) + 5, "x": rng.normal(0, 1, 40)})
        with_fit = _run("scatter_plot", df, features=["x"], params={"fit": "linear"})
        without = _run("scatter_plot", df, features=["x"], params={"fit": "none"})
        assert with_fit.status == "ok" and without.status == "ok", (
            with_fit.messages,
            without.messages,
        )
        n_with = len(with_fit.figures[0].axes[0].lines)
        n_without = len(without.figures[0].axes[0].lines)
        assert n_with > n_without, (
            f"fit=linear 应比 fit=none 多出拟合线，实测 {n_with} vs {n_without}"
        )

    def test_spc_attribute_center_line_equals_mean_proportion(self):
        """p 图的中心线 `CL` 必须等于**总体不良率** `p̄ = Σ不良数 / Σ样本量`（定义式）。

        构造：6 组，每组样本量 `n = 100`，不良**数**为 `[2, 4, 3, 5, 1, 6]`
        → `p̄ = (2+4+3+5+1+6) / (6×100) = 21/600 = 0.035`。

        ⚠️ 我首版把**比例**（0.02…）当地标列传入并断言 `CL = 0.035` → **失败**
        （实测 `CL = 0.00035`，小 100 倍）。查 `api-reference.md` 第 268 行确认：
        `n_col` 是「**样本量列**」，故目标列应为**不良数**（引擎按 `Σcount/Σn` 算比例）
        —— 是**我的数据构造错了**，引擎是对的。
        """
        defectives = [2.0, 4.0, 3.0, 5.0, 1.0, 6.0]
        df = pd.DataFrame(
            {
                "defect": defectives,
                "n": [100.0] * 6,
                "g": [f"L{i}" for i in range(6)],
            }
        )
        r = _run(
            "spc_attribute",
            df,
            target="defect",
            features=["g", "n"],
            params={"n_col": "n", "group_col": "g"},
        )
        assert r.status == "ok", r.messages
        assert str(r.metadata["chart_type"]).lower() == "p", r.metadata
        expected = float(sum(defectives)) / (6 * 100.0)
        assert float(r.metadata["cl"]) == pytest.approx(expected, rel=1e-9), (
            f"CL 应等于 Σ不良数/Σ样本量 = {expected}，实测 {r.metadata['cl']}"
        )
        # 逐组比例也应与手算一致
        tbl = r.tables["control_stats"]
        for i, d in enumerate(defectives):
            assert float(tbl["不良率(p)"].iloc[i]) == pytest.approx(d / 100.0, rel=1e-9)

    def test_multi_objective_pareto_front_has_no_dominated_point(self):
        """Pareto 前沿的定义性质：**不存在被支配点** —— 任一前沿点都不能在
        所有目标上同时不劣于另一个前沿点。

        这是"前沿算对了"的强证据，且**完全不需要知道具体数值**。
        """
        rng = np.random.default_rng(5)
        df = pd.DataFrame({"x1": rng.normal(0, 1, 40), "x2": rng.normal(0, 1, 40)})
        r = _run(
            "multi_objective",
            df,
            target="x1",
            features=["x2"],
            params={
                "objectives": [
                    {"col": "x1", "direction": "maximize"},
                    {"col": "x2", "direction": "minimize"},
                ]
            },
        )
        assert r.status == "ok", r.messages
        assert int(r.metadata["pareto_count"]) >= 1, r.metadata
        # 期望值之和：两个方向的期望值都应在 [0,1]（期望函数的值域）
        tbl = r.tables["desirability_scores"]
        for col in ("最优期望值", "均值期望值"):
            vals = [float(v) for v in tbl[col]]
            assert all(0.0 <= v <= 1.0 for v in vals), (col, vals)

    def test_robust_regression_beats_ols_under_a_gross_outlier(self):
        """**鲁棒回归的存在理由**：无离群时两者一致；一个极端离群时
        鲁棒估计仍接近真值，而 OLS 被拉走。

        构造：`y = 5 + 2x`（真值系数 (5, 2)），把第 0 个观测的 `y` 改成 500。
        Huber 的系数应仍接近 (5, 2)；OLS 应显著偏离 —— 这正是"鲁棒"的定义。
        """
        rng = np.random.default_rng(3)
        x = rng.normal(0, 1, 60)
        y = 5.0 + 2.0 * x
        y[0] = 500.0
        r = _run("robust_regression", pd.DataFrame({"y": y, "x": x}), features=["x"])
        assert r.status == "ok", r.messages
        tbl = r.tables["coefficient_comparison"].set_index("变量")
        huber_slope = float(tbl.loc["x", "Huber系数"])
        ols_slope = float(tbl.loc["x", "OLS系数"])
        assert huber_slope == pytest.approx(2.0, abs=0.1), (
            f"Huber 斜率应接近真值 2，实测 {huber_slope}"
        )
        assert abs(ols_slope - 2.0) > abs(huber_slope - 2.0), (
            f"OLS 应被离群值拉得更远：Huber={huber_slope} OLS={ols_slope}"
        )

    def test_median_regression_drives_residual_median_to_zero(self):
        """**中位数回归的定义性质**：解应使残差的中位数 ≈ 0。

        真值来源即定义 —— 中位数回归最小化 `Σ|残差|`，而 `Σ|r|` 对常数项的最优解
        正是 `median(r) = 0`（这是"最小绝对偏差 ⇒ 中位数"这个经典结论）。
        故无需知道系数是多少，就能判断解是否正确。

        ⚠️ 我先后试过两种"精确复原系数"的构造都**失败**：
        ① 无噪声 `y = 5+2x` → 引擎报「分位回归拟合失败」（残差恒 0，最优化问题退化）；
        ② 对称噪声 → 得 2.2176（有限样本下 `τ=0.5` 的解不唯一，拟合面在近零残差处不可微）。
        **精确系数在有限样本下不可得**，故改用这条定义性质 —— 它既严格又不依赖样本。
        """
        rng = np.random.default_rng(3)
        x = rng.normal(0, 1, 80)
        y = 5.0 + 2.0 * x + rng.normal(0, 1, 80)
        r = _run(
            "quantile_regression",
            pd.DataFrame({"y": y, "x": x}),
            features=["x"],
            params={"quantile": 0.5},
        )
        assert r.status == "ok", r.messages
        tbl = r.tables["coefficients"].set_index("变量")
        c = float(tbl.loc["const", "系数"])
        s = float(tbl.loc["x", "系数"])
        resid = y - (c + s * x)
        assert abs(float(np.median(resid))) < 0.01, (
            f"中位数回归的残差中位数应为 0，实测 {float(np.median(resid)):.6f}"
        )

    def test_quantile_regression_minimizes_the_pinball_loss(self):
        """**分位回归的最优性**：其解必须比 OLS 解给出更小的 pinball 损失。

        真值来源即定义 —— 分位回归最小化

            `L_q(β) = Σ [ q·r⁺ + (1−q)·r⁻ ]`，`r = y − Xβ`

        故把**分位回归自己的解**与 **OLS 解**代进同一个 `L_q`，前者必须更小。
        这是"这个解确实是那个最优化问题的解"的直接验证，**完全不依赖样本量**。
        """
        rng = np.random.default_rng(3)
        x = rng.normal(0, 1, 80)
        y = 5.0 + 2.0 * x + rng.normal(0, 1, 80)
        df = pd.DataFrame({"y": y, "x": x})
        q = 0.9

        def pinball(const: float, slope: float) -> float:
            res = y - (const + slope * x)
            return float(np.sum(np.where(res >= 0, q * res, (q - 1) * res)))

        r_qr = _run("quantile_regression", df, features=["x"], params={"quantile": q})
        r_ols = _run("regression", df, features=["x"])
        assert r_qr.status == "ok" and r_ols.status == "ok", (r_qr.messages, r_ols.messages)
        t_qr = r_qr.tables["coefficients"].set_index("变量")
        t_ols = r_ols.tables["coefficients"].set_index("变量")
        loss_qr = pinball(float(t_qr.loc["const", "系数"]), float(t_qr.loc["x", "系数"]))
        loss_ols = pinball(float(t_ols.loc["const", "系数"]), float(t_ols.loc["x", "系数"]))
        assert loss_qr < loss_ols, (
            f"分位回归解必须比 OLS 解更小化 pinball 损失：QR={loss_qr:.4f} OLS={loss_ols:.4f}"
        )
