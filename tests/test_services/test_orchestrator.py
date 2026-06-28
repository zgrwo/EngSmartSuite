from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def test_orchestrate_anova(sample_doe_data):
    req = AnalysisRequest(
        task="anova", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = orchestrate(req)
    assert result.task == "anova"
    assert result.status in ("ok", "warning", "error")


def test_orchestrate_correlation(sample_doe_data):
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables


def test_orchestrate_unknown_task(sample_doe_data):
    req = AnalysisRequest(
        task="unknown_method", data=sample_doe_data,
        target_col="强度", feature_cols=["料温"],
    )
    result = orchestrate(req)
    assert result.status == "error"
