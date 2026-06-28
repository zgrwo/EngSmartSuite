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

from smartsuite.engine.doe_opt import (
    doe_analysis,
    grid_search,
    multi_objective_opt,
    regression_analysis,
    response_surface_analysis,
)
from smartsuite.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    decision_tree_analysis,
    hypothesis_test,
    vif_analysis,
)
from smartsuite.engine.spc_monitor import (
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
