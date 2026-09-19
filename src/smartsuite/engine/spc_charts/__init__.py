"""SPC 控制图子包（原 spc_charts.py，2026-09-19 拆分）。"""

from smartsuite.engine.spc_charts.attribute import attribute_chart
from smartsuite.engine.spc_charts.cusum import cusum_chart
from smartsuite.engine.spc_charts.ewma import ewma_chart
from smartsuite.engine.spc_charts.nonparametric import spc_nonparametric
from smartsuite.engine.spc_charts.xbar_r import xbar_r_chart

__all__ = [
    "attribute_chart",
    "cusum_chart",
    "ewma_chart",
    "spc_nonparametric",
    "xbar_r_chart",
]
