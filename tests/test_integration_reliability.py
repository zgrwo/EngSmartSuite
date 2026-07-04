"""可靠性数据集集成测试。"""
import os

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
    r = orchestrate(AnalysisRequest(
        task="survival_analysis", data=rel_df,
        target_col="观测时间",
        feature_cols=["故障", "产品型号"],
    ))
    assert r.status == "ok"
    assert r.metadata["n_events"] > 0
    assert r.metadata["n_censored"] > 0


def test_survival_logrank(rel_df):
    """两组生存曲线比较 (选取两种产品)。"""
    sub = rel_df[rel_df["产品型号"].isin(["Motor-A", "Motor-B"])]
    r = orchestrate(AnalysisRequest(
        task="survival_analysis", data=sub,
        target_col="观测时间",
        feature_cols=["故障", "产品型号"],
    ))
    assert r.status == "ok"
    if "logrank_test" in r.tables:
        assert r.tables["logrank_test"] is not None


def test_distribution_on_life(rel_df):
    """寿命数据的分布拟合（应偏向 Weibull）。"""
    r = orchestrate(AnalysisRequest(
        task="distribution_summary", data=rel_df,
        target_col="观测时间", feature_cols=[],
    ))
    assert r.status == "ok"


def test_bootstrap_on_life(rel_df):
    """Bootstrap 中位寿命。"""
    r = orchestrate(AnalysisRequest(
        task="bootstrap_ci", data=rel_df,
        target_col="观测时间", feature_cols=[],
        params={"statistic": "median", "n_bootstrap": 300},
    ))
    assert r.status == "ok"


def test_correlation_reliability(rel_df):
    """工况参数与寿命的相关性。"""
    r = orchestrate(AnalysisRequest(
        task="correlation", data=rel_df,
        target_col="观测时间",
        feature_cols=["温度", "负载", "振动", "占空比", "电压"],
    ))
    assert r.status == "ok"
