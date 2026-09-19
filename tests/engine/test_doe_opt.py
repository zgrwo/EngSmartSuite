import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt import (
    doe_analysis,
    grid_search,
    lasso_regression,
    multi_objective_opt,
    regression_analysis,
    response_surface_analysis,
    roc_analysis,
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


def test_lasso_cv_floor_small_sample():
    """审查 2026-08-19 #1.4：dropna 后仅 4-5 行时 LassoCV cv 不得为 1（InvalidParameterError）。"""

    np.random.seed(1)
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, 6),
            "x2": np.random.normal(0, 1, 6),
            "y": np.random.normal(0, 1, 6),
        }
    )
    df.loc[0:1, "x1"] = np.nan  # dropna 后剩 4 行
    req = AnalysisRequest(
        task="lasso_regression", data=df, target_col="y", feature_cols=["x1", "x2"]
    )
    result = lasso_regression(req)
    # 不再抛 InvalidParameterError（可能因样本过少返回 error，但必须是明确消息而非异常冒泡）
    assert result.status in ("ok", "error")
    assert result.task == "lasso_regression"


def test_roc_all_nan_target():
    """审查 2026-08-19 #1.4：目标/预测列全 NaN → 中文错误而非 IndexError。"""

    df = pd.DataFrame({"score": [np.nan] * 5, "label": [np.nan] * 5})
    req = AnalysisRequest(task="roc_analysis", data=df, target_col="label", feature_cols=["score"])
    result = roc_analysis(req)
    assert result.status == "error"
    assert any("2 个类别" in m or "类别" in m for m in result.messages)


def test_grid_search_nan_ranges_rejected():
    """审查 2026-08-19 #2.1：NaN 上下限必须被明确拒绝（此前静默穿透）。"""
    from smartsuite.engine.doe_opt import grid_search

    np.random.seed(1)
    df = pd.DataFrame(
        {
            "料温": np.random.uniform(170, 190, 30),
            "强度": np.random.normal(50, 5, 30),
        }
    )
    req = AnalysisRequest(
        task="grid_search",
        data=df,
        target_col="强度",
        feature_cols=["料温"],
        params={"ranges": {"料温": [float("nan"), float("nan")]}},
    )
    result = grid_search(req)
    assert result.status == "error"
    assert any("NaN" in m or "无效" in m for m in result.messages)


def test_grid_search_invalid_direction_rejected():
    """审查 2026-08-19 #2.6：direction 拼写错误不得静默反转方向。"""
    from smartsuite.engine.doe_opt import grid_search

    np.random.seed(1)
    df = pd.DataFrame(
        {
            "料温": np.random.uniform(170, 190, 30),
            "强度": np.random.normal(50, 5, 30),
        }
    )
    req = AnalysisRequest(
        task="grid_search",
        data=df,
        target_col="强度",
        feature_cols=["料温"],
        params={"ranges": {"料温": [170, 190]}, "direction": "max"},
    )
    result = grid_search(req)
    assert result.status == "error"
    assert any("direction" in m for m in result.messages)


def test_regression_constant_target_rejected():
    """审查 2026-08-19 #1.4：常量目标列不得输出 "R²=-inf" 与虚假诊断。"""
    from smartsuite.engine.doe_opt import regression_analysis

    df = pd.DataFrame({"x": np.arange(10, dtype=float), "y": np.ones(10)})
    req = AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
    result = regression_analysis(req)
    assert result.status == "error"
    assert any("常量" in m for m in result.messages)


def test_multi_objective_weights_strings_rejected():
    """审查 2026-08-19 #2.6：字符串权重应报错而非 np.sum TypeError。"""
    from smartsuite.engine.doe_opt import multi_objective_opt

    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
    req = AnalysisRequest(
        task="multi_objective",
        data=df,
        target_col="",
        feature_cols=["a"],
        params={"objectives": [{"col": "a", "direction": "maximize"}], "weights": ["1.0", "oops"]},
    )
    result = multi_objective_opt(req)
    assert result.status == "error"
    assert any("权重" in m for m in result.messages)
