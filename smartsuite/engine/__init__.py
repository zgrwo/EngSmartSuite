"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

# ── 引擎层全局 matplotlib 配置（必须在任何 Figure 创建之前执行）──
import matplotlib

matplotlib.use("Agg")

try:
    matplotlib.font_manager.fontManager.addfont("C:/Windows/Fonts/msyh.ttc")
    matplotlib.rcParams["font.family"] = "Microsoft YaHei"
except Exception:
    matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

# ── 统一可视化样式 ──
from smartsuite.engine._palette import get_palette_style

_palette_style = get_palette_style()
for key, val in _palette_style.items():
    matplotlib.rcParams[key] = val

from smartsuite.engine.doe_opt import (
    doe_analysis,
    grid_search,
    lasso_regression,
    logistic_regression,
    multi_objective_opt,
    quantile_regression,
    regression_analysis,
    response_surface_analysis,
    robust_regression,
    roc_analysis,
)
from smartsuite.engine.root_cause import (
    anova_analysis,
    cohens_kappa,
    contingency_analysis,
    correlation_analysis,
    cronbach_alpha,
    decision_tree_analysis,
    distribution_summary,
    hypothesis_test,
    normality_check,
    power_analysis,
    proportion_ci,
    variance_test,
    vif_analysis,
)
from smartsuite.engine.spc_monitor import (
    anomaly_detect,
    attribute_chart,
    bootstrap_ci,
    box_chart,
    change_point_detect,
    cusum_chart,
    ewma_chart,
    gage_rr,
    median_ci,
    outlier_consensus,
    process_capability_analysis,
    spc_nonparametric,
    survival_analysis,
    tolerance_interval,
    trend_forecast,
    xbar_r_chart,
)

__all__ = [
    "correlation_analysis", "anova_analysis", "contingency_analysis",
    "cohens_kappa", "cronbach_alpha",
    "hypothesis_test",
    "decision_tree_analysis", "vif_analysis", "power_analysis", "normality_check",
    "distribution_summary",
    "proportion_ci", "variance_test",
    "regression_analysis", "response_surface_analysis", "grid_search",
    "multi_objective_opt", "doe_analysis", "roc_analysis",
    "logistic_regression", "lasso_regression",
    "robust_regression", "quantile_regression",
    "xbar_r_chart", "attribute_chart", "cusum_chart", "ewma_chart", "change_point_detect",
    "process_capability_analysis", "trend_forecast", "anomaly_detect",
    "outlier_consensus", "bootstrap_ci", "box_chart", "gage_rr", "tolerance_interval",
    "spc_nonparametric",
    "survival_analysis", "median_ci",
]
