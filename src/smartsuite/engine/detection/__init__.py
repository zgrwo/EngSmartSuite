"""异常/变化点检测子包（原 detection.py，2026-09-21 拆分，公开 API 不变）。

约定：本包只再导出**公开 API**。私有助手（`_acf_values` / `_ljung_box` /
`_dw_interpretation`）留在定义它们的 `trend` 模块里，白盒测试显式从
`smartsuite.engine.detection.trend` 导入 —— 这样谁依赖内部实现一目了然，
也不会出现"patch 了包属性却不生效"的假修补（私有名不承诺长期兼容，
见 `docs/governance/project-structure.md`）。
"""

from smartsuite.engine.detection.anomaly import anomaly_detect
from smartsuite.engine.detection.change_point import change_point_detect
from smartsuite.engine.detection.outlier import outlier_consensus
from smartsuite.engine.detection.trend import trend_forecast

__all__ = [
    "trend_forecast",
    "change_point_detect",
    "outlier_consensus",
    "anomaly_detect",
]
