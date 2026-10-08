"""独立双样本 t 检验的方差假设（Welch）与自由度展示。

对应第三轮复核 P2-4（logs/reports/verify-round3/R3-复核清单.md）：

`hypothesis.py` 原实现 `sp_stats.ttest_ind(g1, g2)` **未传 `equal_var`** → 恒为
合并方差（Student）t 检验；全仓 grep `equal_var|welch` 零命中。

实测不等方差 + 不等 n（n1=10, s=1 vs n2=60, s=8）：

    scipy Welch   p = 0.5990
    scipy Student p = 0.8267      ← 原实现落在这里

修复取向：默认 Welch（现代实践与 scipy 1.15+ 的默认一致），并**披露**方差齐性判定
（Levene）与 Welch 自由度，让用户知道用的是哪个口径。
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _two_group_frame(s1, s2, n1, n2, d=2.0, seed=7):
    rng = np.random.default_rng(seed)
    g1 = rng.normal(0.0, s1, n1)
    g2 = rng.normal(d * s1, s2, n2)
    return (
        pd.DataFrame({"y": np.concatenate([g1, g2]), "grp": ["A"] * n1 + ["B"] * n2}),
        g1,
        g2,
    )


def _run(df, **params):
    return orchestrate(
        AnalysisRequest(
            task="hypothesis_test",
            data=df,
            target_col="y",
            feature_cols=["grp"],
            params={"test": "ttest_ind", **params},
        )
    )


class TestWelchIsUsed:
    """p 值必须等于 scipy 的 Welch 结果（而非 Student）。"""

    def test_unequal_variance_matches_scipy_welch(self):
        df, g1, g2 = _two_group_frame(s1=1.0, s2=8.0, n1=10, n2=60)
        r = _run(df)
        assert r.status == "ok"
        reported = float(r.tables["test_results"].iloc[0]["p值"])
        welch = float(sp_stats.ttest_ind(g1, g2, equal_var=False).pvalue)
        student = float(sp_stats.ttest_ind(g1, g2, equal_var=True).pvalue)
        assert reported == pytest.approx(welch, abs=1e-4), (
            f"报告 p={reported}，应为 Welch {welch:.4f}（Student 为 {student:.4f}）"
        )
        assert abs(reported - student) > 1e-3, "本例 Student 与 Welch 应有可辨差异"

    def test_equal_variance_also_matches_welch(self):
        """方差齐时也用 Welch——避免"先检验后选择"带来的 I 类错误膨胀。"""
        df, g1, g2 = _two_group_frame(s1=1.0, s2=1.0, n1=40, n2=40, d=0.6)
        r = _run(df)
        reported = float(r.tables["test_results"].iloc[0]["p值"])
        welch = float(sp_stats.ttest_ind(g1, g2, equal_var=False).pvalue)
        assert reported == pytest.approx(welch, abs=1e-4)

    def test_test_name_says_welch(self):
        df, _, _ = _two_group_frame(s1=1.0, s2=8.0, n1=10, n2=60)
        r = _run(df)
        assert "Welch" in r.tables["test_results"].iloc[0]["检验方法"]

    def test_levene_pvalue_disclosed(self):
        df, g1, g2 = _two_group_frame(s1=1.0, s2=8.0, n1=10, n2=60)
        r = _run(df)
        note = str(r.tables["test_results"].iloc[0]["方差齐性"])
        expected = float(sp_stats.levene(g1, g2, center="median").pvalue)
        assert f"{expected:.4f}" in note, f"方差齐性说明应含 Levene p 值，实际: {note}"

    def test_unequal_variance_emits_warning_message(self):
        """方差不齐应主动告知用户（影响结论解读）。"""
        df, _, _ = _two_group_frame(s1=1.0, s2=8.0, n1=10, n2=60)
        r = _run(df)
        assert any("不齐" in m or "Levene" in m for m in r.messages), r.messages

    def test_equal_variance_is_silent(self):
        """方差齐时不应打扰用户。"""
        df, _, _ = _two_group_frame(s1=1.0, s2=1.0, n1=40, n2=40)
        r = _run(df)
        assert r.messages == [], f"齐性时应无警告，实际: {r.messages}"

    def test_welch_df_is_disclosed_and_differs_from_pooled(self):
        """自由度列必须反映 Welch–Satterthwaite 近似（非 n1+n2−2）。"""
        df, g1, g2 = _two_group_frame(s1=1.0, s2=8.0, n1=10, n2=60)
        r = _run(df)
        reported = float(r.tables["test_results"].iloc[0]["自由度"])
        welch_df = float(sp_stats.ttest_ind(g1, g2, equal_var=False).df)
        assert reported == pytest.approx(welch_df, abs=0.01)
        assert reported != pytest.approx(10 + 60 - 2, abs=0.5), "不应是合并方差自由度"


class TestOtherTestsUnaffected:
    """非 t 检验分支不得被本次改动影响。"""

    def test_mannwhitney_still_matches_scipy(self):
        df, g1, g2 = _two_group_frame(s1=1.0, s2=8.0, n1=20, n2=20)
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["grp"],
                params={"test": "mannwhitney"},
            )
        )
        reported = float(r.tables["test_results"].iloc[0]["p值"])
        assert reported == pytest.approx(float(sp_stats.mannwhitneyu(g1, g2).pvalue), abs=1e-4)
        assert "Mann-Whitney" in r.tables["test_results"].iloc[0]["检验方法"]

    def test_auto_selection_selects_welch_for_normal_data(self):
        """auto 在数据正态时选 t 检验，应当选到 Welch。"""
        df, _, _ = _two_group_frame(s1=1.0, s2=8.0, n1=40, n2=40, d=0.6, seed=3)
        r = orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["grp"],
                params={"test": "auto"},
            )
        )
        assert r.status == "ok"
        assert "Welch" in r.tables["test_results"].iloc[0]["检验方法"]
