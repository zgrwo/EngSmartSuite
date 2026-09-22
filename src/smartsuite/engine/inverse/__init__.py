"""工艺参数反解子包（原 inverse.py，2026-09-21 拆分，公开 API 不变）。

模块划分（依赖方向无环）：
- `_roles`    角色识别与行拆分
- `_params`   参数解析（含 `_DEFAULT_*` / 枚举元组等任务级默认值）
- `_models`   前向模型与速率模型拟合
- `_bounds`   边界、尺度与权重规整
- `_solver`   单条请求求解与可达性采样
- `_report`   公式、表格与图窗
- `solve`     公开入口 `inverse_parameter_solve`

**`INVERSE_*` 常量故意不从本包再导出**：它们定义在 `engine/_constants.py`，被上方各
模块直接导入使用。若在此再导出，`monkeypatch.setattr(smartsuite.engine.inverse, "INVERSE_X", v)`
只改到包属性、改不动消费模块的同名全局 —— 是"看起来打上了补丁"的假修补。
需要覆盖时必须打到消费模块（见 `tests/engine/test_inverse.py`）。
"""

from smartsuite.engine.inverse._roles import DEFAULT_PREFIXES
from smartsuite.engine.inverse.solve import inverse_parameter_solve

__all__ = [
    "inverse_parameter_solve",
    "DEFAULT_PREFIXES",
]
