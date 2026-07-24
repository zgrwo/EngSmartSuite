# ADR-001: 采用三层分离架构

**日期**: 2026-06-28
**状态**: 已确认（2026-07-05 修订：Excel 交互层已移除，由 Web/CLI 层替代；详见 ADR-002）

## 上下文

SmartSuite 需要在用户界面和 Python 分析引擎之间建立清晰边界。如果引擎直接依赖 UI 框架（xlwings/Flask），会导致引擎代码与特定界面耦合，无法独立测试和复用。

## 决策

采用三层分离架构：用户界面层（Web/CLI）→ 应用服务层（编排+报告）→ 分析引擎层（纯 Python）。引擎层只通过 `AnalysisRequest` / `AnalysisResult` 数据契约与外界通信。

## 原因

1. 引擎可脱离 UI 框架独立测试（pytest 直接构造 DataFrame 输入）
2. 支持多个界面入口（Web UI 或 CLI）而引擎层零改动复用
3. 分层异常处理，每层只需关心自己的错误类型
4. 符合 skills-main/codebase-design 的深度模块原则：每个模块接口小、实现深

## 约束

- `smartsuite/engine/` 禁止 `import xlwings`、`import flask`
- 唯一桥接层是 `smartsuite/services/`
- Web/CLI 层通过 `smartsuite/services/orchestrator.py` 间接调用引擎

## 演进

- **2026-06-28**: 初始版本，定义 Excel 交互层（xlwings）
- **2026-07-04**: 移除 Excel 交互层（物理删除 `smartsuite/excel/`），Web UI 和 CLI 成为用户界面入口。详见 ADR-002
