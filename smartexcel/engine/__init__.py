"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

from smartexcel.engine.root_cause import (
    correlation_analysis, anova_analysis, hypothesis_test,
    decision_tree_analysis, vif_analysis,
)
from smartexcel.engine.doe_opt import (
    regression_analysis, response_surface_analysis, grid_search,
    multi_objective_opt, doe_analysis,
)
from smartexcel.engine.spc_monitor import (
    xbar_r_chart, process_capability_analysis, trend_forecast, anomaly_detect,
)

__all__ = [
    "correlation_analysis", "anova_analysis", "hypothesis_test",
    "decision_tree_analysis", "vif_analysis",
    "regression_analysis", "response_surface_analysis", "grid_search",
    "multi_objective_opt", "doe_analysis",
    "xbar_r_chart", "process_capability_analysis", "trend_forecast", "anomaly_detect",
]
