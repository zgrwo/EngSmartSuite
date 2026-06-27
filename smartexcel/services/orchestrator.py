"""工作流编排 — 按 task 字段路由到对应引擎函数。"""
from smartexcel.core.contracts import AnalysisRequest, AnalysisResult
from smartexcel.engine import (
    correlation_analysis, anova_analysis, hypothesis_test,
    decision_tree_analysis, vif_analysis,
    regression_analysis, response_surface_analysis, grid_search,
    multi_objective_opt, doe_analysis,
    xbar_r_chart, process_capability_analysis, trend_forecast, anomaly_detect,
)

TASK_REGISTRY = {
    "correlation": correlation_analysis,
    "anova": anova_analysis,
    "hypothesis_test": hypothesis_test,
    "decision_tree": decision_tree_analysis,
    "vif": vif_analysis,
    "regression": regression_analysis,
    "response_surface": response_surface_analysis,
    "grid_search": grid_search,
    "multi_objective": multi_objective_opt,
    "doe_analysis": doe_analysis,
    "spc_xbar": xbar_r_chart,
    "process_capability": process_capability_analysis,
    "trend_forecast": trend_forecast,
    "anomaly_detect": anomaly_detect,
}

DEFAULT_PARAMS = {
    "anova": {"alpha": 0.05},
    "hypothesis_test": {"alpha": 0.05, "test": "ttest_ind"},
    "decision_tree": {"max_depth": 5},
    "regression": {"model_type": "linear"},
    "response_surface": {"direction": "maximize"},
    "grid_search": {"direction": "maximize", "n_points": 10},
    "spc_xbar": {"subgroup_col": "子组"},
    "trend_forecast": {"forecast_steps": 5},
    "anomaly_detect": {"method": "iqr"},
}


def orchestrate(req: AnalysisRequest) -> AnalysisResult:
    """路由分析请求到对应引擎函数，注入默认参数。"""
    if req.task not in TASK_REGISTRY:
        return AnalysisResult(
            task=req.task, status="error",
            messages=[f"未知的分析任务「{req.task}」, 支持: {list(TASK_REGISTRY.keys())}"]
        )

    defaults = DEFAULT_PARAMS.get(req.task, {})
    merged = {**defaults, **req.params}
    req.params = merged

    try:
        return TASK_REGISTRY[req.task](req)
    except Exception as e:
        return AnalysisResult(task=req.task, status="error", messages=[str(e)])
