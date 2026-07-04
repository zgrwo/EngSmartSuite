"""化工批次数据集集成测试 — 端到端工作流验证。"""
import os

import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import missing_pattern_analysis, recommend_analysis
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture(scope="module")
def chemical_df():
    """加载化工批次数据集。"""
    path = os.path.join(os.path.dirname(__file__), "test_chemical_data.xlsx")
    if not os.path.exists(path):
        pytest.skip("test_chemical_data.xlsx not found")
    return pd.read_excel(path)


def test_chemical_data_loaded(chemical_df):
    """验证化工数据集加载正确。"""
    assert len(chemical_df) == 300
    assert "收率" in chemical_df.columns
    assert "纯度" in chemical_df.columns


def test_chemical_correlation(chemical_df):
    """收率与工艺参数的相关性分析。"""
    req = AnalysisRequest(
        task="correlation", data=chemical_df, target_col="收率",
        feature_cols=["实际温度", "温度偏差", "压力", "搅拌速度", "反应时间", "pH值"],
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_regression(chemical_df):
    """收率回归分析。"""
    req = AnalysisRequest(
        task="regression", data=chemical_df, target_col="收率",
        feature_cols=["实际温度", "压力", "搅拌速度", "反应时间", "pH值", "终点纯度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "r_squared" in result.metadata


def test_chemical_anova(chemical_df):
    """催化剂类型对收率的 ANOVA。"""
    req = AnalysisRequest(
        task="anova", data=chemical_df, target_col="收率",
        feature_cols=["催化剂类型"],
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_hypothesis_auto(chemical_df):
    """自动选择检验类型的工作流（二分类变量）。"""
    req = AnalysisRequest(
        task="hypothesis_test", data=chemical_df, target_col="收率",
        feature_cols=["外观检查"],
        params={"test": "auto", "group_col": "外观检查"},
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "p_value" in result.metadata


def test_chemical_capability(chemical_df):
    """过程能力分析。"""
    req = AnalysisRequest(
        task="process_capability", data=chemical_df, target_col="纯度",
        params={"usl": 99.5, "lsl": 95.0, "target": 97.5},
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_trend(chemical_df):
    """收率趋势预测。"""
    req = AnalysisRequest(
        task="trend_forecast", data=chemical_df, target_col="收率",
        params={"forecast_steps": 5},
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_normality(chemical_df):
    """正态性评估。"""
    req = AnalysisRequest(
        task="normality_check", data=chemical_df, target_col="收率",
        feature_cols=["实际温度", "压力", "反应时间", "pH值", "纯度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_outlier_consensus(chemical_df):
    """多方法异常共识。"""
    req = AnalysisRequest(
        task="outlier_consensus", data=chemical_df, target_col="收率",
        feature_cols=["实际温度", "压力"],
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_bootstrap(chemical_df):
    """Bootstrap 置信区间。"""
    req = AnalysisRequest(
        task="bootstrap_ci", data=chemical_df, target_col="收率",
        params={"statistic": "mean", "n_bootstrap": 500},
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_chemical_recommendation(chemical_df):
    """智能分析推荐。"""
    result = recommend_analysis(chemical_df, target_col="收率")
    assert "recommendations" in result
    assert len(result["recommendations"]) >= 3


def test_chemical_missing_analysis(chemical_df):
    """缺失模式分析。"""
    result = missing_pattern_analysis(chemical_df)
    assert result["total_rows"] == 300
    assert "summary" in result
