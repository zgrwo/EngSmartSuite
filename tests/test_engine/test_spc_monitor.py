from smartexcel.core.contracts import AnalysisRequest
from smartexcel.engine.spc_monitor import (
    xbar_r_chart,
    process_capability_analysis,
    trend_forecast,
    anomaly_detect,
)


def test_xbar_r_chart(sample_spc_data):
    req = AnalysisRequest(
        task="spc_xbar",
        data=sample_spc_data,
        target_col="测量值",
        feature_cols=["子组"],
        params={"subgroup_col": "子组"},
    )
    result = xbar_r_chart(req)
    assert result.status == "ok"
    assert len(result.figures) >= 1
    assert "control_limits" in result.tables


def test_process_capability(sample_spc_data):
    req = AnalysisRequest(
        task="process_capability",
        data=sample_spc_data,
        target_col="测量值",
        params={"usl": 12.0, "lsl": 8.0},
    )
    result = process_capability_analysis(req)
    assert result.status == "ok"
    cpk = result.metadata.get("cpk", 0)
    assert isinstance(cpk, (int, float))
    assert "cp" in result.metadata


def test_trend_forecast(sample_spc_data):
    subgroup_means = sample_spc_data.groupby("子组")["测量值"].mean().reset_index()
    req = AnalysisRequest(
        task="trend_forecast",
        data=subgroup_means,
        target_col="测量值",
        params={"forecast_steps": 5},
    )
    result = trend_forecast(req)
    assert result.status == "ok"
    assert "forecast" in result.tables
    assert len(result.tables["forecast"]) >= 5


def test_anomaly_detect(sample_spc_data):
    req = AnalysisRequest(
        task="anomaly_detect",
        data=sample_spc_data,
        target_col="测量值",
        params={"method": "iqr"},
    )
    result = anomaly_detect(req)
    assert result.status == "ok"
    assert "anomaly_count" in result.metadata
