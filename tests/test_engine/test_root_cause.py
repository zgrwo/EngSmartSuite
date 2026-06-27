from smartexcel.core.contracts import AnalysisRequest
from smartexcel.engine.root_cause import correlation_analysis


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
