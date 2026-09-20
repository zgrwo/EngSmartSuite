"""核心层共享常量 — 纯数据、无第三方依赖。

审查 2026-09-19 B2/B4：`GROUP_COLORS` 原定义在 `engine/_palette.py`，再经
`engine/__init__.py` 与 `services/orchestrator.py` 两级再导出给 Web UI。该路径会把
整个引擎层（matplotlib/sklearn/statsmodels）拉进 CLI 冷启动，而它本身只是 5 条
「任务分组 → 背景色」映射，属纯数据 → 下沉到 core，由 web/orchestrator 直接引用。
"""

GROUP_COLORS = {
    "要因筛选": "#e8f5e9",  # 浅绿 — data.primary 淡色
    "信度诊断": "#fff8e1",  # 浅黄 — judge.warn 淡色
    "建模优化": "#e3f2fd",  # 浅蓝 — data.primary 淡色
    "过程监控": "#fce4ec",  # 浅红 — anomaly 淡色
    "高级分析": "#f3e5f5",  # 浅紫 — contrast.d 淡色
}
