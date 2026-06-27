from smartexcel.core.contracts import AnalysisRequest
from smartexcel.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    decision_tree_analysis,
    hypothesis_test,
    vif_analysis,
)


def test_correlation_analysis_basic(sample_doe_data):
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = correlation_analysis(req)

    assert result.task == "correlation"
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables
    corr = result.tables["correlation_matrix"]
    assert corr.shape[0] >= 5
    assert corr.values.min() >= -1.0
    assert corr.values.max() <= 1.0
    assert len(result.summary) > 0


def test_anova_basic(sample_doe_data):
    req = AnalysisRequest(
        task="anova",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"alpha": 0.05},
    )
    result = anova_analysis(req)

    assert result.task == "anova"
    assert result.status in ("ok", "warning")
    assert "anova_table" in result.tables
    assert len(result.summary) > 0
    assert "r_squared" in result.metadata


def test_hypothesis_test_two_sample(sample_two_group_data):
    req = AnalysisRequest(
        task="hypothesis_test", data=sample_two_group_data,
        target_col="强度", feature_cols=["工艺"],
        params={"test": "ttest_ind", "group_col": "工艺"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok"
    assert "p_value" in result.metadata
    assert len(result.summary) > 0


def test_decision_tree(sample_doe_data):
    req = AnalysisRequest(
        task="decision_tree", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
        params={"max_depth": 3},
    )
    result = decision_tree_analysis(req)
    assert result.status == "ok"
    assert "feature_importance" in result.tables
    fi = result.tables["feature_importance"]
    assert "重要性" in fi.columns
    assert len(fi) >= 1


def test_vif_analysis(sample_doe_data):
    req = AnalysisRequest(
        task="vif", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = vif_analysis(req)
    assert result.status == "ok"
    assert "vif_table" in result.tables
