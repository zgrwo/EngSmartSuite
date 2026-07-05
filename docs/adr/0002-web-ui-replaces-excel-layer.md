# ADR-002: Web UI 替换 Excel 交互层

**日期**: 2026-07-04
**状态**: 已确认

## 上下文

ADR-001 最初定义了 Excel 交互层（xlwings），位于 `smartsuite/excel/`。随着项目演进，Web UI（`smartsuite/web/`）和 CLI（`smartsuite/cli.py`）成为主要的用户界面入口，Excel xlwings 层不再维护。

## 决策

移除 `smartsuite/excel/` 目录（物理删除所有 .py 源文件），Web/CLI 层直接作为三层架构的用户界面层。

## 原因

1. Web UI 提供更丰富的交互体验（文件上传、列定义面板、智能识别、结果可视化）
2. CLI 支持 YAML 模板驱动的批量分析，更适合自动化工作流
3. xlwings Excel add-in 需要 Windows + Office 环境，限制部署灵活性
4. 维护单一用户界面路径降低复杂度

## 影响

- `smartsuite/excel/` 目录保留为空壳（仅 `__pycache__`），供未来可能的 Excel 集成预留
- ADR-001 约束更新：引擎层禁止 `import xlwings` 和 `import flask`
- 用户界面层现在包括 `smartsuite/web/`（Flask）和 `smartsuite/cli.py`（YAML 模板驱动）
