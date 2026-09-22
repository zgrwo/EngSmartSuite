"""应用服务层 — 数据 I/O、工作流编排、报告生成、过程审计。

审查 2026-09-19 B2 第②层：本包原在导入期全量 re-export 四个子模块，使
`import smartsuite.services.data_io`（只需 pandas）连带拉起 audit → engine →
sklearn/statsmodels/matplotlib。现改为 PEP 562 模块级 `__getattr__` 按需解析：
`from smartsuite.services import orchestrate` 仍然可用，但只加载 orchestrate
所在的子模块。

注意：子模块导入（`from smartsuite.services import audit`、`import
smartsuite.services.audit`）不经过本函数，由导入系统直接解析。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # mypy 需要显式符号；运行时不执行
    from smartsuite.services.audit import (
        auto_report,
        batch_analyze,
        export_workbook,
        process_audit,
    )
    from smartsuite.services.data_io import (
        missing_pattern_analysis,
        preprocess_data,
        recommend_analysis,
        validate_data,
    )
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate
    from smartsuite.services.reporter import to_excel, to_html, to_pdf, to_ppt

__all__ = [
    "orchestrate",
    "TASK_REGISTRY",
    "to_excel",
    "to_pdf",
    "to_ppt",
    "to_html",
    "preprocess_data",
    "validate_data",
    "missing_pattern_analysis",
    "recommend_analysis",
    "process_audit",
    "batch_analyze",
    "auto_report",
    "export_workbook",
]

# 公开名 → 所属子模块（唯一事实源：新增再导出时只改这里）
_EXPORT_SOURCES: dict[str, str] = {
    "orchestrate": "smartsuite.services.orchestrator",
    "TASK_REGISTRY": "smartsuite.services.orchestrator",
    "to_excel": "smartsuite.services.reporter",
    "to_pdf": "smartsuite.services.reporter",
    "to_ppt": "smartsuite.services.reporter",
    "to_html": "smartsuite.services.reporter",
    "preprocess_data": "smartsuite.services.data_io",
    "validate_data": "smartsuite.services.data_io",
    "missing_pattern_analysis": "smartsuite.services.data_io",
    "recommend_analysis": "smartsuite.services.data_io",
    "process_audit": "smartsuite.services.audit",
    "batch_analyze": "smartsuite.services.audit",
    "auto_report": "smartsuite.services.audit",
    "export_workbook": "smartsuite.services.audit",
}


def __getattr__(name: str):
    """按需解析本层公开导出（PEP 562）；结果写回 globals 以便下次直取。"""
    module_path = _EXPORT_SOURCES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    attr = getattr(import_module(module_path), name)
    globals()[name] = attr
    return attr


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
