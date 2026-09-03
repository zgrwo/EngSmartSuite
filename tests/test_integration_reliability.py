"""可靠性数据集集成测试。"""

import os

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture(scope="module")
def rel_df():
    path = os.path.join(os.path.dirname(__file__), "test_reliability_data.xlsx")
    if not os.path.exists(path):
        pytest.skip("test_reliability_data.xlsx not found")
    return pd.read_excel(path)


def test_reliability_data_loaded(rel_df):
    assert len(rel_df) == 200
    assert "观测时间" in rel_df.columns
    assert "故障" in rel_df.columns


def test_survival_analysis(rel_df):
    r = orchestrate(
        AnalysisRequest(
            task="survival_analysis",
            data=rel_df,
            target_col="观测时间",
            feature_cols=["故障", "产品型号"],
        )
    )
    assert r.status == "ok"
    assert r.metadata["n_events"] > 0
    assert r.metadata["n_censored"] > 0


def test_survival_logrank(rel_df):
    """两组生存曲线比较 (选取两种产品)。"""
    sub = rel_df[rel_df["产品型号"].isin(["Motor-A", "Motor-B"])]
    r = orchestrate(
        AnalysisRequest(
            task="survival_analysis",
            data=sub,
            target_col="观测时间",
            feature_cols=["故障", "产品型号"],
        )
    )
    assert r.status == "ok"
    if "logrank_test" in r.tables:
        assert r.tables["logrank_test"] is not None


def test_distribution_on_life(rel_df):
    """寿命数据的分布拟合（应偏向 Weibull）。"""
    r = orchestrate(
        AnalysisRequest(
            task="distribution_summary",
            data=rel_df,
            target_col="观测时间",
            feature_cols=[],
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① 描述统计均值/样本量与原始数据独立重算一致（原始统计量回查）；
    # ② 候选分布非空且每行 KS p ∈ [0,1]
    desc = r.metadata["descriptive"]
    raw = rel_df["观测时间"].dropna()
    assert desc["样本量"] == len(raw) == 200
    assert desc["均值"] == pytest.approx(float(raw.mean()), abs=1e-9)
    fits = r.tables["distribution_fits"]
    assert len(fits) >= 3
    assert pd.to_numeric(fits["KS p"], errors="coerce").notna().all()
    assert (pd.to_numeric(fits["KS p"], errors="coerce").between(0, 1)).all()


def test_bootstrap_on_life(rel_df):
    """Bootstrap 中位寿命。"""
    r = orchestrate(
        AnalysisRequest(
            task="bootstrap_ci",
            data=rel_df,
            target_col="观测时间",
            feature_cols=[],
            params={"statistic": "median", "n_bootstrap": 300},
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # 点估计 ≈ 原始中位数（数据右截尾于 3000，中位数恰为截尾值），CI 包含原始中位数
    raw_median = float(rel_df["观测时间"].median())
    md = r.metadata
    assert md["n"] == len(rel_df) == 200
    assert md["point_estimate"] == pytest.approx(raw_median, abs=1e-9)
    assert md["ci_lower"] <= raw_median <= md["ci_upper"]
    assert md["ci_lower"] <= md["ci_upper"]


def test_correlation_reliability(rel_df):
    """工况参数与寿命的相关性。"""
    feats = ["温度", "负载", "振动", "占空比", "电压"]
    r = orchestrate(
        AnalysisRequest(
            task="correlation",
            data=rel_df,
            target_col="观测时间",
            feature_cols=feats,
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① 每列 r ∈ [-1,1]、校正 p ∈ [0,1]；② 引擎 r 与测试内独立重算
    # （逐对 dropna 后的皮尔逊相关系数，与引擎 pairwise-complete 语义一致）对照
    tc = r.metadata["target_correlations"]
    tp = r.metadata["target_p_adjusted"]
    assert set(tc) == set(feats)
    manual = {}
    for f in feats:
        pair = rel_df[["观测时间", f]].dropna()
        manual[f] = float(np.corrcoef(pair["观测时间"], pair[f])[0, 1])
        assert abs(tc[f]) <= 1
        assert 0 <= tp[f] <= 1
        assert tc[f] == pytest.approx(manual[f], abs=1e-9)
    # ③ 最强相关因子应被引擎识别为温度（数据事实：|r_温度|≈0.466 ≫ 其余 <0.09）
    assert max(manual, key=lambda k: abs(manual[k])) == "温度"
    assert abs(tc["温度"]) > 0.3
