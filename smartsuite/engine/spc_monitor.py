"""SPC 监控与统计分析模块（统一入口）。

本模块为向后兼容保留，实际实现已拆分至：
- spc_charts: SPC 控制图 (X-bar/R, 属性图, CUSUM, EWMA, 非参数)
- capability: 过程能力分析 (Cp/Cpk, Sigma 水平)
- detection: 异常/变化点检测 (趋势预测, 变化点, 异常检测, 离群点)
- reliability: 可靠性/MSA (Gage R&R, 容差区间, 生存分析)
- exploratory: 探索性分析 (箱线图, 散点图, 中位数 CI, Bootstrap CI)
"""

# SPC 控制图
# 过程能力
from smartsuite.engine.capability import process_capability_analysis

# 异常/变化点检测
from smartsuite.engine.detection import (
    anomaly_detect,
    change_point_detect,
    outlier_consensus,
    trend_forecast,
)

# 探索性分析
from smartsuite.engine.exploratory import (
    bootstrap_ci,
    box_chart,
    median_ci,
    scatter_plot,
)

# 可靠性/MSA
from smartsuite.engine.reliability import (
    gage_rr,
    survival_analysis,
    tolerance_interval,
)
from smartsuite.engine.spc_charts import (
    attribute_chart,
    cusum_chart,
    ewma_chart,
    spc_nonparametric,
    xbar_r_chart,
)

__all__ = [
    # SPC 控制图
    "xbar_r_chart",
    "attribute_chart",
    "cusum_chart",
    "ewma_chart",
    "spc_nonparametric",
    # 过程能力
    "process_capability_analysis",
    # 异常/变化点检测
    "trend_forecast",
    "change_point_detect",
    "anomaly_detect",
    "outlier_consensus",
    # 可靠性/MSA
    "gage_rr",
    "tolerance_interval",
    "survival_analysis",
    # 探索性分析
    "box_chart",
    "scatter_plot",
    "median_ci",
    "bootstrap_ci",
]
