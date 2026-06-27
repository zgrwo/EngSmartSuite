from smartexcel.core.contracts import AnalysisRequest
from smartexcel.engine.doe_opt import (
    regression_analysis,
    response_surface_analysis,
    grid_search,
    multi_objective_opt,
    doe_analysis,
)


def test_regression_analysis_linear(sample_doe_data):
    req = AnalysisRequest(
        task="regression",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"model_type": "linear"},
    )
    result = regression_analysis(req)
    assert result.status == "ok"
    assert "coefficients" in result.tables
    assert "r_squared" in result.metadata
    assert result.metadata["r_squared"] >= 0
    assert len(result.summary) > 0


def test_response_surface(sample_doe_data):
    req = AnalysisRequest(
        task="response_surface",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温"],
        params={"direction": "maximize"},
    )
    result = response_surface_analysis(req)
    assert result.status == "ok"
    assert len(result.figures) >= 1
    assert "coefficients" in result.tables


def test_grid_search_optimization(sample_doe_data):
    req = AnalysisRequest(
        task="grid_search",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温"],
        params={
            "ranges": {"料温": [180, 220], "模温": [40, 80]},
            "direction": "maximize",
            "n_points": 10,
        },
    )
    result = grid_search(req)
    assert result.status == "ok"
    assert "optimal_params" in result.metadata


def test_multi_objective_optimization(sample_doe_data):
    req = AnalysisRequest(
        task="multi_objective",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={
            "objectives": [
                {"col": "强度", "direction": "maximize"},
                {"col": "不良率", "direction": "minimize"},
            ],
            "weights": [0.5, 0.5],
        },
    )
    result = multi_objective_opt(req)
    assert result.status == "ok"
    assert "optimal_params" in result.metadata


def test_doe_factorial_analysis(sample_doe_data):
    req = AnalysisRequest(
        task="doe_analysis",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温"],
        params={"design_type": "full_factorial"},
    )
    result = doe_analysis(req)
    assert result.status == "ok"
    assert "effect_estimates" in result.tables
