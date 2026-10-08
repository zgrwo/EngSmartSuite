"""ANOVA 效应量口径测试（经典 η² vs 偏 η²）。

对应第三轮复核 P1-1（logs/reports/verify-round3/R3-复核清单.md）：

`anova.py` 的 `_eta_squared` 只计算 **偏 η²**（SS_effect/(SS_effect+SS_residual)），
却以键名 `η²` 输出，而 `_effect_interpretation` 用的是 `_constants.py` 里的
**Cohen 经典 η² 阈值**（0.01/0.06/0.14）。多因子设计中偏 η² > 经典 η²，
**效应量被系统性夸大**。

实测（双因子含交互，n=240，statsmodels typ=2 复算）：

| 效应 | 经典 η² | 偏 η² | 夸大 |
|---|---|---|---|
| f1 | 0.3264 | 0.3365 | +3% |
| f2 | 0.0249 | 0.0373 | **+50%** |
| f1×f2 | 0.0050 | 0.0077 | **+54%** |

本文件用**独立复算**（statsmodels）钉住两个口径都正确，并断言阈值只作用于经典 η²。
"""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.formula.api import ols

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _two_factor_frame(seed: int = 5, n: int = 240):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "f1": np.repeat(["A", "B", "C"], n // 3),
            "f2": np.tile(np.repeat(["X", "Y"], n // 6), 3),
        }
    )
    df["y"] = (
        10.0
        + df["f1"].map({"A": 0.0, "B": 1.2, "C": 0.1}).to_numpy()
        + df["f2"].map({"X": 0.0, "Y": 0.15}).to_numpy()
        + rng.normal(0, 0.8, len(df))
    )
    return df


def _independent_eta(df):
    """独立复算：statsmodels typ=2 的 SS 表 → 经典 η² 与偏 η²。

    返回以**引擎侧键名**（`Q('f1')` / `Q('f1'):Q('f2')`）为键的字典，
    便于与 `metadata["effect_sizes"]` 直接对齐。
    """
    model = ols("y ~ C(f1) * C(f2)", data=df).fit()
    tbl = sm.stats.anova_lm(model, typ=2)
    ss_total = tbl["sum_sq"].sum()
    ss_res = tbl.loc["Residual", "sum_sq"]

    def _to_engine_key(statsmodels_idx: str) -> str:
        # "C(f1)" → "Q('f1')"；"C(f1):C(f2)" → "Q('f1'):Q('f2')"
        parts = statsmodels_idx.split(":")
        return ":".join(f"Q('{p[p.index('(') + 1 : -1]}')" for p in parts)

    return {
        _to_engine_key(idx): (
            tbl.loc[idx, "sum_sq"] / ss_total,
            tbl.loc[idx, "sum_sq"] / (tbl.loc[idx, "sum_sq"] + ss_res),
        )
        for idx in tbl.index
        if idx != "Residual"
    }


def _run_anova(df):
    return orchestrate(
        AnalysisRequest(
            task="anova",
            data=df,
            target_col="y",
            feature_cols=["f1", "f2"],
            params={"interactions": 1},
        )
    )


class TestBothEtaSquaredReported:
    """metadata 必须同时给出两个口径，且各自正确。"""

    def test_metadata_has_both_keys(self):
        r = _run_anova(_two_factor_frame())
        assert r.status == "ok"
        for key, vals in r.metadata["effect_sizes"].items():
            assert "η²" in vals, f"{key} 缺经典 η²"
            assert "偏 η²" in vals, f"{key} 缺偏 η²"

    def test_classic_eta_matches_independent_recompute(self):
        df = _two_factor_frame()
        r = _run_anova(df)
        ref = _independent_eta(df)
        for idx, (classic, _partial) in ref.items():
            got = r.metadata["effect_sizes"][idx]["η²"]
            assert got == pytest.approx(classic, rel=1e-9), f"{idx} 经典 η² 不符"

    def test_partial_eta_matches_independent_recompute(self):
        df = _two_factor_frame()
        r = _run_anova(df)
        ref = _independent_eta(df)
        for idx, (_classic, partial) in ref.items():
            got = r.metadata["effect_sizes"][idx]["偏 η²"]
            assert got == pytest.approx(partial, rel=1e-9), f"{idx} 偏 η² 不符"

    def test_partial_exceeds_classic_in_multifactor(self):
        """多因子下偏 η² 严格大于经典 η² —— 这正是混用阈值的危害来源。"""
        r = _run_anova(_two_factor_frame())
        for key, vals in r.metadata["effect_sizes"].items():
            assert vals["偏 η²"] > vals["η²"], f"{key}: 偏 η² 应大于经典 η²"


class TestTableColumns:
    """增强表必须两列都出，且解读只作用于经典 η²。"""

    def test_table_has_partial_column(self):
        r = _run_anova(_two_factor_frame())
        cols = list(r.tables["anova_enhanced"].columns)
        assert "η²" in cols and "偏 η²" in cols, f"表列缺失: {cols}"

    def test_table_values_match_metadata(self):
        r = _run_anova(_two_factor_frame())
        tbl = r.tables["anova_enhanced"]
        for _, row in tbl.iterrows():
            src = row["来源"]
            if src == "Residual":
                continue
            es = r.metadata["effect_sizes"][src]
            assert float(row["η²"]) == pytest.approx(es["η²"], rel=1e-9)
            assert float(row["偏 η²"]) == pytest.approx(es["偏 η²"], rel=1e-9)

    @pytest.mark.parametrize(
        "classic,expected_label",
        [
            (0.005, "可忽略"),  # < 0.01
            (0.03, "小"),  # [0.01, 0.06)
            (0.10, "中"),  # [0.06, 0.14)
            (0.30, "大"),  # >= 0.14
        ],
    )
    def test_interpretation_uses_classic_thresholds(self, classic, expected_label):
        """解读标签必须按**经典 η²** 的 Cohen 阈值给出（两者口径一致才成立）。"""
        from smartsuite.engine.root_cause._shared import _effect_interpretation

        assert _effect_interpretation(classic) == expected_label


class TestSingleFactorUnchanged:
    """单因子设计下两口径相等——既有单因子用例的行为不得改变。"""

    def test_single_factor_two_eta_are_equal(self):
        rng = np.random.default_rng(9)
        df = pd.DataFrame(
            {
                "g": np.repeat(["A", "B", "C"], 40),
            }
        )
        df["y"] = df["g"].map({"A": 10.0, "B": 11.0, "C": 10.2}).to_numpy() + rng.normal(
            0, 0.7, len(df)
        )
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["g"],
                params={"interactions": 0},
            )
        )
        assert r.status == "ok"
        for key, vals in r.metadata["effect_sizes"].items():
            assert vals["η²"] == pytest.approx(vals["偏 η²"], rel=1e-9), (
                f"{key}: 单因子下两口径应相等"
            )

    def test_single_factor_eta_matches_independent(self):
        rng = np.random.default_rng(9)
        df = pd.DataFrame({"g": np.repeat(["A", "B", "C"], 40)})
        df["y"] = df["g"].map({"A": 10.0, "B": 11.0, "C": 10.2}).to_numpy() + rng.normal(
            0, 0.7, len(df)
        )
        model = ols("y ~ C(g)", data=df).fit()
        tbl = sm.stats.anova_lm(model, typ=2)
        ss_total = tbl["sum_sq"].sum()
        expected = tbl.loc["C(g)", "sum_sq"] / ss_total
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["g"],
                params={"interactions": 0},
            )
        )
        assert r.metadata["effect_sizes"]["Q('g')"]["η²"] == pytest.approx(expected, rel=1e-9)
