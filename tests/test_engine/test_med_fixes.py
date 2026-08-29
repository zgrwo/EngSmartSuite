"""MED 修复回归测试 — 三个已知 MED 问题的红-绿验证。

对应问题（2026-08-29 全量数值验证）:
- MED-1: hypothesis_test 白名单含 cohens_d/correlation 但静默落入独立双样本 t 检验
- MED-2: doe_analysis docstring 承诺交互效应但仅做单因子主效应
- MED-3: process_capability Box-Cox 变换后规格限非正 → 整体丢弃双侧能力指数
"""

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


# ═══════════════════════════════════════════════════════════
# MED-1: hypothesis_test cohens_d / correlation 分支
# ═══════════════════════════════════════════════════════════


def _make_two_group_data(seed=7):
    rng = np.random.RandomState(seed)
    g1 = rng.normal(5, 1, 30)
    g2 = rng.normal(5.5, 1, 30)
    return pd.DataFrame({"y": np.concatenate([g1, g2]), "grp": ["A"] * 30 + ["B"] * 30})


class TestMed1CohensD:
    """test=cohens_d 应返回 Cohen's d 效应量（不检验），而非静默跑 t 检验。"""

    def test_cohens_d_not_falling_back_to_ttest(self):
        df = _make_two_group_data()
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["grp"],
                params={"test": "cohens_d", "group_col": "grp"},
            )
        )
        assert r.status == "ok"
        # 必须命中 cohens_d 专属分支：effect_name 应含 Cohen's d 且非独立样本 t 检验
        assert r.metadata.get("test") == "效应量 Cohen's d (A vs B)", (
            f"test 应为 '效应量 Cohen's d'，实际: {r.metadata.get('test')}"
        )
        # 无显著性检验 → 不应有 p_value 或应为 None
        assert r.metadata.get("p_value") is None
        d = r.metadata.get("effect_size")
        assert d is not None and np.isfinite(d)
        # 与手工公式交叉验证: d = (mean1-mean2)/pooled_sd (Hedges' g)
        g1 = df[df["grp"] == "A"]["y"].values
        g2 = df[df["grp"] == "B"]["y"].values
        n1, n2 = len(g1), len(g2)
        sp = np.sqrt(
            ((n1 - 1) * np.std(g1, ddof=1) ** 2 + (n2 - 1) * np.std(g2, ddof=1) ** 2)
            / (n1 + n2 - 2)
        )
        expected = (np.mean(g1) - np.mean(g2)) / sp
        correction = 1 - 3 / (4 * (n1 + n2) - 9)  # Hedges' g
        diff = abs(d - expected * correction)
        assert diff < 1e-3, f"Cohen's d: {d} vs {expected * correction}"

    def test_cohens_d_has_ci(self):
        df = _make_two_group_data()
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["grp"],
                params={"test": "cohens_d", "group_col": "grp"},
            )
        )
        ci = r.metadata.get("effect_size_ci")
        assert ci is not None, "cohens_d 应报告 95% CI"
        lo, hi = ci
        assert lo < hi, f"CI 顺序错误: {ci}"


class TestMed1Correlation:
    """test=correlation 应返回相关显著性检验（r + p），而非静默跑 t 检验。"""

    def test_correlation_not_falling_back_to_ttest(self):
        rng = np.random.RandomState(11)
        x = rng.normal(0, 1, 60)
        y = 0.8 * x + rng.normal(0, 0.5, 60)  # 强相关
        df = pd.DataFrame({"x": x, "y": y})
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["x"],
                params={"test": "correlation"},
            )
        )
        assert r.status == "ok"
        assert "相关" in r.metadata.get("test", ""), (
            f"test 应含'相关'，实际: {r.metadata.get('test')}"
        )
        # 与 scipy 独立重算对比
        from scipy.stats import pearsonr

        ref_r, ref_p = pearsonr(x, y)
        assert abs(r.metadata["statistic"] - ref_r) < 1e-4, (
            f"r: {r.metadata['statistic']} vs {ref_r}"
        )
        assert abs(r.metadata["p_value"] - ref_p) < 1e-4, f"p: {r.metadata['p_value']} vs {ref_p}"
        assert r.metadata["p_value"] < 0.05, "强相关应显著"

    def test_correlation_ci(self):
        rng = np.random.RandomState(11)
        x = rng.normal(0, 1, 60)
        y = 0.8 * x + rng.normal(0, 0.5, 60)
        df = pd.DataFrame({"x": x, "y": y})
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["x"],
                params={"test": "correlation"},
            )
        )
        ci = r.metadata.get("effect_size_ci")
        assert ci is not None
        lo, hi = ci
        assert 0 < lo < hi <= 1.0, f"r 的 95% CI 应落在 (0,1]: {ci}"


# ═══════════════════════════════════════════════════════════
# MED-2: doe_analysis 交互效应
# ═══════════════════════════════════════════════════════════


class TestMed2Interaction:
    def test_doe_analysis_detects_interaction(self):
        """y = 2A + 3B + 5AB（真实交互系数=5 → 效应≈10）应被检出。"""
        rng = np.random.RandomState(42)
        A = rng.choice([-1, 1], 40)
        B = rng.choice([-1, 1], 40)
        y = 2 * A + 3 * B + 5 * A * B + rng.normal(0, 0.1, 40)
        df = pd.DataFrame({"y": y, "A": A, "B": B})
        r = orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=df,
                target_col="y",
                feature_cols=["A", "B"],
                params={"alpha": 0.05},
            )
        )
        assert r.status == "ok"
        eff = r.tables["effect_estimates"]
        # 交互项应出现在效应表中（因子名含 × 或 : 分隔的两因子）
        inter_rows = eff[eff["因子"].astype(str).str.contains(r"×|:|x", case=False, regex=True)]
        assert len(inter_rows) >= 1, f"应包含交互效应行，实际因子: {list(eff['因子'])}"
        inter_effect = float(inter_rows.iloc[0]["主效应"])
        # 真实交互效应 = 2*5 = 10
        assert 8 < inter_effect < 12, f"交互效应应≈10，实际={inter_effect:.3f}"
        assert inter_rows.iloc[0]["显著"] == "是", "强交互应标记显著"

    def test_doe_analysis_no_spurious_interaction(self):
        """y = 2A + 3B + 噪声（无交互）→ 交互效应应≈0 且不显著。"""
        rng = np.random.RandomState(42)
        A = rng.choice([-1, 1], 40)
        B = rng.choice([-1, 1], 40)
        y = 2 * A + 3 * B + rng.normal(0, 1, 40)
        df = pd.DataFrame({"y": y, "A": A, "B": B})
        r = orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=df,
                target_col="y",
                feature_cols=["A", "B"],
                params={"alpha": 0.05},
            )
        )
        eff = r.tables["effect_estimates"]
        inter_rows = eff[eff["因子"].astype(str).str.contains(r"×|:|x", case=False, regex=True)]
        assert len(inter_rows) == 1
        inter_effect = float(inter_rows.iloc[0]["主效应"])
        assert abs(inter_effect) < 3, f"无交互数据交互效应应≈0，实际={inter_effect:.3f}"

    def test_doe_analysis_existing_main_effects_preserved(self):
        """修复不得破坏现有主效应输出（test_correctness 回归保护）。"""
        rng = np.random.RandomState(42)
        levels = [-1, 1]
        rows = []
        for a in levels:
            for b in levels:
                for _ in range(5):
                    y = 2.5 * a - 1.5 * b + rng.normal(0, 0.3)
                    rows.append({"A": a, "B": b, "y": y})
        df = pd.DataFrame(rows)
        r = orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=df,
                target_col="y",
                feature_cols=["A", "B"],
                params={"alpha": 0.05},
            )
        )
        eff = r.tables["effect_estimates"]
        eff_a = float(eff[eff["因子"] == "A"]["主效应"].iloc[0])
        eff_b = float(eff[eff["因子"] == "B"]["主效应"].iloc[0])
        assert 3.5 < eff_a < 6.5
        assert -4.5 < eff_b < -1.5


# ═══════════════════════════════════════════════════════════
# MED-3: process_capability Box-Cox 规格限回退
# ═══════════════════════════════════════════════════════════


class TestMed3BoxCoxSpecLimits:
    def test_boxcox_negative_lam_spec_limits_fallback(self):
        """λ<0 时小规格限变换后为负 → 应回退原始数据而非丢弃全部能力指数。"""
        rng = np.random.RandomState(3)
        data = rng.lognormal(0, 0.4, 200)  # 右偏 → Box-Cox λ<0
        df = pd.DataFrame({"y": data})
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"usl": 4.0, "lsl": 0.3, "transform": "boxcox"},
            )
        )
        assert r.status == "ok"
        # 不得整体丢弃：cp/cpk 应仍可计算（回退到原始尺度）
        cp = r.metadata.get("cp")
        cpk = r.metadata.get("cpk")
        assert cp is not None and np.isfinite(cp), f"cp 不应为 None: {cp}"
        assert cpk is not None and np.isfinite(cpk), f"cpk 不应为 None: {cpk}"
        # 回退后应与不做变换的结果一致（同一原始尺度）
        r_ref = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"usl": 4.0, "lsl": 0.3},
            )
        )
        assert abs(cp - r_ref.metadata["cp"]) < 1e-6, (
            f"回退 cp={cp} 应等于无变换 cp={r_ref.metadata['cp']}"
        )
        # 应有明确警告告知用户回退原因
        assert any("Box-Cox" in m or "回退" in m for m in r.messages), f"应有回退警告: {r.messages}"

    def test_boxcox_normal_case_still_transforms(self):
        """规格限均变换为正的常规场景不受影响（仍走变换域）。"""
        rng = np.random.RandomState(5)
        data = rng.lognormal(0, 0.4, 200)
        df = pd.DataFrame({"y": data})
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"usl": 8.0, "lsl": 1.5, "transform": "boxcox"},
            )
        )
        assert r.status == "ok"
        lam = r.metadata.get("boxcox_lambda")
        # 此场景规格限较大，变换后仍为正 → 应保留变换
        assert lam is not None, "正常场景应保留 Box-Cox 变换"
        # 真实数值断言：λ 与 scipy 独立重算一致
        from scipy.stats import boxcox as scipy_boxcox

        _, ref_lam = scipy_boxcox(data)
        lam_diff = abs(lam - ref_lam)
        assert lam_diff < 1e-6, f"λ: {lam} vs {ref_lam}"
        # 变换域下 cp 应为有限值（双侧规格均变换为正）
        cp = r.metadata.get("cp")
        assert cp is not None
        assert 0 < cp < 10, f"cp 应为合理有限值: {cp}"
