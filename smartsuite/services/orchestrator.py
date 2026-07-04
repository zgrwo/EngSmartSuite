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
    except Exception as e:
        logger.exception("分析任务 %s 执行失败: %s", req.task, str(e)[:200])
        # 将异常转为中文工艺术语，不暴露原始 traceback
        err_cls = type(e).__name__
        detail_map = {
            "ValueError": "数据格式不符合分析要求，请检查目标列和因子列的数据类型",
            "KeyError": f"数据中缺少必要的列，请确认列名是否正确",
            "TypeError": "数据类型不匹配，请确保所有因子列为数值型或类别型",
            "IndexError": "数据索引异常，请检查数据是否包含空行或异常索引",
            "MemoryError": "数据量过大超出内存限制，请减少数据行数或列数",
            "LinAlgError": "矩阵运算失败，数据可能存在严重共线性或数值异常",
            "ConvergenceError": "模型未能收敛，请检查数据质量或调整分析参数",
        }
        detail = detail_map.get(err_cls, "分析计算过程中出现异常，请检查数据完整性")
        return AnalysisResult(
            task=req.task, status="error",
            messages=[
                f"分析执行失败 ({err_cls}): {detail}",
                "如问题持续出现，请联系开发者并提供数据样本",
            ],
        )
