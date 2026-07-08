"""工作流编排 — 按 task 字段路由到对应引擎函数。"""
import logging
from dataclasses import replace

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.exceptions import SmartSuiteError
from smartsuite.engine import GROUP_COLORS  # noqa: F401 — re-export for web layer
from smartsuite.engine import (
    anomaly_detect,
    anova_analysis,
    attribute_chart,
    bootstrap_ci,
    box_chart,
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
    spc_nonparametric,
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
    "spc_nonparametric": spc_nonparametric,
    "process_capability": process_capability_analysis,
    "trend_forecast": trend_forecast,
    "anomaly_detect": anomaly_detect,
    "change_point": change_point_detect,
    "spc_attribute": attribute_chart,
    "power_analysis": power_analysis,
    "normality_check": normality_check,
    "outlier_consensus": outlier_consensus,
    "bootstrap_ci": bootstrap_ci,
    "box_chart": box_chart,
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
    # 要因分析
    "correlation": {"method": "pearson"},
    "anova": {"alpha": 0.05, "interactions": 0},
    "hypothesis_test": {"alpha": 0.05, "test": "ttest_ind"},
    "decision_tree": {"max_depth": 5},
    "vif": {},
    "contingency": {"alpha": 0.05},
    "proportion_ci": {},
    "variance_test": {"alpha": 0.05, "group_col": None},
    "cohens_kappa": {},
    "cronbach_alpha": {},
    "distribution_summary": {},
    "normality_check": {},
    "power_analysis": {"mode": "required_n", "test_type": "ttest",
                       "effect_size": 0.5, "alpha": 0.05, "target_power": 0.80},
    # DOE / 优化
    "regression": {"model_type": "linear"},
    "response_surface": {"direction": "maximize"},
    "grid_search": {"ranges": None, "direction": "maximize", "n_points": 10},
    "multi_objective": {"objectives": None},
    "doe_analysis": {"alpha": 0.05},
    "roc_analysis": {},
    "logistic_regression": {"threshold": 0.5},
    "lasso_regression": {"alpha_lasso": None, "l1_ratio": 1.0},
    "robust_regression": {},
    "quantile_regression": {"quantile": 0.5},
    # 过程监控
    "spc_xbar": {"subgroup_col": "子组"},
    "spc_attribute": {"chart_type": "p"},
    "spc_cusum": {"k": 0.5, "h": 5.0},
    "spc_ewma": {"lam": 0.2, "L": 2.7},
    "spc_nonparametric": {"side": "two-sided"},
    "process_capability": {"usl": None, "lsl": None},
    "trend_forecast": {"forecast_steps": 5},
    "anomaly_detect": {"method": "iqr"},
    "change_point": {"min_segment": 10, "n_changepoints": 5},
    "outlier_consensus": {},
    "box_chart": {"mode": "facet"},
    "bootstrap_ci": {"statistic": "mean", "n_bootstrap": 2000, "ci_level": 0.95},
    "median_ci": {"ci_level": 0.95},
    "gage_rr": {"part_col": None, "operator_col": None, "tolerance": None, "sigma_multiplier": 5.15},
    "tolerance_interval": {"coverage": 0.99, "confidence": 0.95, "side": "two-sided"},
    "survival_analysis": {},
}


def orchestrate(req: AnalysisRequest) -> AnalysisResult:
    """路由分析请求到对应引擎函数，注入默认参数。

    Note: dataclass replace() 执行浅拷贝，req.data (DataFrame) 以引用共享。
    引擎函数不应修改输入的 DataFrame；如需修改应自行 .copy()。
    """
    if req.task not in TASK_REGISTRY:
        return AnalysisResult(
            task=req.task, status="error",
            messages=[f"未知的分析任务「{req.task}」, 支持: {list(TASK_REGISTRY.keys())}"]
        )

    # ── 集中列存在性检查：在分派到引擎函数之前验证 target_col ──
    if req.target_col and req.target_col not in req.data.columns:
        return AnalysisResult(
            task=req.task, status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中。"
                      f"可用列: {list(req.data.columns)[:20]}"
                      + ("…" if len(req.data.columns) > 20 else "")]
        )

    defaults = DEFAULT_PARAMS.get(req.task, {})
    merged = {**defaults, **req.params}
    # 规范化: JS 端空字符串 '' → Python None (修复 Web/CLI 参数桥接)
    # 仅对默认值为 None 的参数做此转换，保留 explicit '' 的语义
    merged = {k: (None if v == '' and defaults.get(k) is None else v)
              for k, v in merged.items()}
    req = replace(req, params=merged)

    try:
        return TASK_REGISTRY[req.task](req)
    except SmartSuiteError as e:
        logger.warning("分析任务 %s SmartSuite异常: %s", req.task, str(e)[:200])
        return AnalysisResult(
            task=req.task, status="error",
            messages=[f"分析执行失败: {str(e)}", "如问题持续出现，请联系开发者"],
        )
    except Exception as e:
        logger.exception("分析任务 %s 执行失败: %s", req.task, str(e)[:200])
        # 将异常转为中文工艺术语，不暴露原始 traceback
        err_cls = type(e).__name__
        detail_map = {
            "ValueError": "数据格式不符合分析要求，请检查目标列和因子列的数据类型",
            "KeyError": "数据中缺少必要的列，请确认列名是否正确",
            "TypeError": "数据类型不匹配，请确保所有因子列为数值型或类别型",
            "IndexError": "数据索引异常，请检查数据是否包含空行或异常索引",
            "MemoryError": "数据量过大超出内存限制，请减少数据行数或列数",
            "LinAlgError": "矩阵运算失败，数据可能存在严重共线性或数值异常",
            "OverflowError": "数值溢出，数据中可能存在极端值，请检查数据范围",
            "RuntimeError": "计算过程出现运行时错误，请检查参数设置是否合适",
            "AttributeError": "数据结构异常，请确认数据列名和格式正确",
            "FileNotFoundError": "找不到指定的文件，请检查文件路径",
            "ZeroDivisionError": "计算中遇到除零错误，数据可能存在常数列或标准差为零",
            "ImportError": "缺少必要的依赖库，请确认已安装完整的 smartsuite[all]",
        }
        detail = detail_map.get(err_cls, "分析计算过程中出现异常，请检查数据完整性")
        return AnalysisResult(
            task=req.task, status="error",
            messages=[
                f"分析执行失败: {detail}",
                "如问题持续出现，请联系开发者并提供数据样本",
            ],
        )


# ── 任务标签和分组（Web/CLI 共享）──
TASK_LABELS = {
    # 要因分析
    "correlation": "相关性分析", "anova": "ANOVA方差分析",
    "hypothesis_test": "假设检验", "decision_tree": "决策树重要性",
    "vif": "VIF共线性", "contingency": "列联表分析",
    "proportion_ci": "比例置信区间", "variance_test": "方差齐性检验",
    "cohens_kappa": "评定者一致性", "cronbach_alpha": "信度分析(Cronbach α)",
    "distribution_summary": "分布特征摘要", "normality_check": "正态性评估",
    "power_analysis": "统计功效分析",
    # DOE/优化
    "regression": "回归建模(OLS)", "response_surface": "响应面分析",
    "grid_search": "网格搜索寻优", "multi_objective": "多目标优化",
    "doe_analysis": "DOE效应估计", "roc_analysis": "ROC/AUC分析",
    "logistic_regression": "Logistic回归", "lasso_regression": "Lasso回归",
    "robust_regression": "稳健回归(Huber)", "quantile_regression": "分位数回归",
    # 过程监控
    "spc_xbar": "X-bar/R控制图", "spc_attribute": "计数型控制图(p/np/c/u)",
    "spc_cusum": "CUSUM控制图", "spc_ewma": "EWMA控制图",
    "process_capability": "过程能力Cp/Cpk", "trend_forecast": "趋势预测",
    "anomaly_detect": "异常检测", "change_point": "变点检测",
    "outlier_consensus": "异常共识(3方法投票)",
    "bootstrap_ci": "Bootstrap置信区间", "median_ci": "中位数置信区间",
    "gage_rr": "量具R&R分析", "tolerance_interval": "统计容许区间",
    "survival_analysis": "生存分析(Kaplan-Meier)",
    "box_chart": "分组箱线图",
    "spc_nonparametric": "非参数控制图(分布拟合法)",
}

TASK_GROUPS = {
    "要因筛选": ["correlation", "anova", "hypothesis_test", "decision_tree",
                 "vif", "contingency", "proportion_ci", "variance_test"],
    "信度诊断": ["cohens_kappa", "cronbach_alpha", "distribution_summary",
                 "normality_check", "power_analysis"],
    "建模优化": ["regression", "response_surface", "grid_search", "multi_objective",
                 "doe_analysis", "roc_analysis", "logistic_regression",
                 "lasso_regression", "robust_regression", "quantile_regression"],
    "过程监控": ["spc_xbar", "spc_attribute", "spc_cusum", "spc_ewma",
                 "process_capability", "trend_forecast", "anomaly_detect",
                 "change_point", "outlier_consensus", "box_chart",
                 "spc_nonparametric"],
    "高级分析": ["bootstrap_ci", "median_ci", "gage_rr", "tolerance_interval",
                 "survival_analysis"],
}

# ── 需要保留原始类别列的任务（不做 One-Hot 编码）──
# 这些引擎函数自行处理因子水平，Web 层通过此常量判断是否跳过预处理
RAW_CAT_TASKS: set[str] = {"box_chart", "anova", "variance_test", "contingency",
                            "cohens_kappa", "hypothesis_test"}
