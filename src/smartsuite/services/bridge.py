"""引擎能力出口 — 供上层（`web/`）取用定义在 `engine/` 的公开能力。

审查 2026-09-19 B4：`web/api.py` 的表格展示需要引擎的 `round_for_display`
（`engine/_utils.py`），但 web 不得直接导入 engine（AGENTS.md 红线），此前只能
借道 `services/orchestrator.py` 并挂 `# noqa: F401` 才不被判为未使用——调用方
看不出这个名字归属谁，也没有任何检查能阻止借道继续蔓延。

本模块把这类「上层确实需要的引擎能力」集中为**命名出口**：

- 每个名字必须来自引擎的公开实现且保持**同一对象**（不做包装），否则展示口径
  会在两处漂移（`round_for_display` 是 Web/HTML/CLI 共用的量纲感知舍入口径）；
- 只登记确实被上层需要的名字，不做路过式 re-export；
- 由 `tests/guards/test_layer_boundaries.py` 锁住以上两条。

注意：导入本模块会拉起引擎包（`engine/__init__` 配置 Agg 后端 + 扫描中文字体）。
这是 web 的固有成本（分析与出图都在引擎完成），但**不要**从不需要分析的路径导入
本模块，那会白付绘图栈开销（见 `tests/guards/test_lazy_imports.py`）。
"""

from smartsuite.engine._utils import round_for_display

__all__ = ["round_for_display"]
