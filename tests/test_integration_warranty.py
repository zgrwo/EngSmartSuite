"""保修数据集集成测试。"""
import os, pytest, pandas as pd, numpy as np
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture(scope="module")
def war_df():
    path = os.path.join(os.path.dirname(__file__), "test_warranty_data.xlsx")
    if not os.path.exists(path):
        pytest.skip("test_warranty_data.xlsx not found")
    return pd.read_excel(path)


def test_warranty_data_loaded(war_df):
    assert len(war_df) == 1000
    assert "保修索赔" in war_df.columns


def test_logistic_warranty(war_df):
    r = orchestrate(AnalysisRequest(
        task="logistic_regression", data=war_df, target_col="保修索赔",
        feature_cols=["环境温度", "湿度", "每日循环", "运行小时"],
    ))
    assert r.status == "ok"
    assert r.metadata["accuracy"] > 0.5


def test_correlation_warranty(war_df):
    r = orchestrate(AnalysisRequest(
        task="correlation", data=war_df, target_col="满意度",
        feature_cols=["维修费用", "维修工时", "运行小时", "环境温度"],
    ))
    assert r.status == "ok"


def test_contingency_warranty(war_df):
    r = orchestrate(AnalysisRequest(
        task="contingency", data=war_df, target_col="保修索赔",
        feature_cols=["粉尘等级"],
    ))
    assert r.status == "ok"


def test_proportion_warranty(war_df):
    r = orchestrate(AnalysisRequest(
        task="proportion_ci", data=war_df, target_col="保修索赔",
        feature_cols=[], params={"success_value": 1},
    ))
    assert r.status == "ok"


def test_anova_warranty(war_df):
    r = orchestrate(AnalysisRequest(
        task="anova", data=war_df, target_col="满意度",
        feature_cols=["产品型号", "区域"],
    ))
    assert r.status == "ok"
