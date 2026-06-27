"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

from smartexcel.engine.doe_opt import (
    doe_analysis,
    grid_search,
    multi_objective_opt,
    regression_analysis,
    response_surface_analysis,
)
from smartexcel.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    decision_tree_analysis,
    hypothesis_test,
    vif_analysis,
)
from smartexcel.engine.spc_monitor import (
    anomaly_detect,
    process_capability_analysis,
    trend_forecast,
    xbar_r_chart,
)

__all__ = [
    "correlation_analysis", "anova_analysis", "hypothesis_test",
    "decision_tree_analysis", "vif_analysis",
    "regression_analysis", "response_surface_analysis", "grid_search",
    "multi_objective_opt", "doe_analysis",
    "xbar_r_chart", "process_capability_analysis", "trend_forecast", "anomaly_detect",
]
