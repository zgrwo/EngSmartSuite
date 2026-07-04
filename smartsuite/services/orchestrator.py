"""工作流编排 — 按 task 字段路由到对应引擎函数。"""
import logging
from dataclasses import replace

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine import (
    anomaly_detect,
    anova_analysis,
    attribute_chart,
    bootstrap_ci,
    change_point_detect,
    cohens_kappa,
    contingency_analysis,
    correlation_analysis,
    cronbach_alpha,
    cusum_chart,
    decision_tree_analysis,
    distribution_summary,
    doe_analysis,
    ewma_chart,
    gage_rr,
    grid_search,
    hypothesis_test,
    lasso_regression,
    logistic_regression,
    median_ci,
    multi_objective_opt,
    normality_check,
    outlier_consensus,
    power_analysis,
    process_capability_analysis,
    proportion_ci,
    quantile_regression,
    regression_analysis,
    response_surface_analysis,
    robust_regression,
    roc_analysis,
    survival_analysis,
    tolerance_interval,
    trend_forecast,
    variance_test,
    vif_analysis,
    xbar_r_chart,
)

logger = logging.getLogger(__name__)

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
    "spc_cusum": cusum_chart,
    "spc_ewma": ewma_chart,
    "process_capability": process_capability_analysis,
    "trend_forecast": trend_forecast,
    "anomaly_detect": anomaly_detect,
    "change_point": change_point_detect,
    "spc_attribute": attribute_chart,
    "power_analysis": power_analysis,
    "normality_check": normality_check,
    "outlier_consensus": outlier_consensus,
    "bootstrap_ci": bootstrap_ci,
    "contingency": contingency_analysis,
    "proportion_ci": proportion_ci,
    "variance_test": variance_test,
    "roc_analysis": roc_analysis,
    "distribution_summary": distribution_summary,
    "gage_rr": gage_rr,
    "tolerance_interval": tolerance_interval,
    "cohens_kappa": cohens_kappa,
    "survival_analysis": survival_analysis,
    "median_ci": median_ci,
    "cronbach_alpha": cronbach_alpha,
    "logistic_regression": logistic_regression,
    "lasso_regression": lasso_regression,
    "robust_regression": robust_regression,
    "quantile_regression": quantile_regression,
}

DEFAULT_PARAMS = {
    "anova": {"alpha": 0.05},
    "hypothesis_test": {"alpha": 0.05, "test": "ttest_ind"},
    "decision_tree": {"max_depth": 5},
    "regression": {"model_type": "linear"},
    "response_surface": {"direction": "maximize"},
    "grid_search": {"direction": "maximize", "n_points": 10},
    "spc_xbar": {"subgroup_col": "子组"},
    "spc_cusum": {"k": 0.5, "h": 5.0},
    "spc_ewma": {"lam": 0.2, "L": 2.7},
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
    req = replace(req, params=merged)

    try:
        return TASK_REGISTRY[req.task](req)
    except Exception:
        logger.exception("分析任务 %s 执行失败", req.task)
        return AnalysisResult(task=req.task, status="error",
                              messages=["分析执行过程中发生内部错误，请联系开发者"])
