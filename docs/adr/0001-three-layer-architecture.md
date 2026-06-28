# ADR-001: 采用三层分离架构

**日期**: 2026-06-28
**状态**: 已确认

## 上下文

SmartSuite 需要在 Excel 交互和 Python 分析引擎之间建立清晰边界。如果引擎直接依赖 xlwings，会导致引擎代码与 Excel 耦合，无法独立测试和复用。

## 决策

采用三层分离架构：Excel 交互层（xlwings）→ 应用服务层（编排+报告）→ 分析引擎层（纯 Python）。引擎层只通过 `AnalysisRequest` / `AnalysisResult` 数据契约与外界通信。

## 原因

1. 引擎可脱离 Excel 独立测试（pytest 直接构造 DataFrame 输入）
2. 未来如果需要 Web 界面或 CLI 入口，引擎层零改动即复用
3. 分层异常处理，每层只需关心自己的错误类型
4. 符合 skills-main/codebase-design 的深度模块原则：每个模块接口小、实现深

## 约束

- `smartsuite/engine/` 禁止 `import xlwings`
- `smartsuite/excel/` 禁止 `import sklearn` / `import statsmodels`
- 唯一桥接层是 `smartsuite/services/`
