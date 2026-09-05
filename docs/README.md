# docs/ — 项目文档

> 项目文档根（2026-09-05 按职责分类重组，原 rules/ 合并至此）。
> 顶层宪法见 [AGENTS.md](../AGENTS.md)；编码陷阱见 [skills/](../skills/)；审查报告统一放 `logs/reports/`（不入库）。

## 分类导航

| 类别 | 文档 | 内容 |
| :--- | :--- | :--- |
| [governance/](governance/) | 治理与基础 | 术语表、文档职责、项目结构、哨兵契约、陷阱清单 |
| [specification/](specification/) | 技术规格 | 项目概述、功能规格、函数签名唯一信源 |
| [user-manual/](user-manual/) | 用户手册 | 每个函数的详细示例 + 结果解读 |
| [adr/](adr/) | 架构决策记录 | ADR-001 三层架构 / ADR-002 Web UI 替代 Excel / ADR 模板 |

## 约定

- 新增文档须登记 [project-structure.md](governance/project-structure.md) 目录树
- 文档数字/计数一律链接到 [api-reference.md](specification/api-reference.md)，禁止硬编码（verify-docs 检查强制）
- 本地工作产物（设计/计划文档、审查报告 → `logs/reports/`）不入库