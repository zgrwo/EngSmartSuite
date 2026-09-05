# skills/ — AI 编码技能目录

本目录包含两类技能：**项目自带技能**（领域陷阱 / 决策树 / 三位审查专家）与
**第三方过程技能**（Superpowers，来源 [obra/superpowers](https://github.com/obra/superpowers)）。

## 项目自带技能

- `smartsuite-dev.md` — 7 大高发陷阱 + 5 套修复模板（**修改源码前必读**）
- `analysis-decision-tree.md` — 分析方法决策树 → 选方法
- `architecture-reviewer.md` / `refactoring-guardian.md` / `project-plan-review.md` — 重构生命周期三位专家

## 第三方过程技能（Superpowers，英文原版）

来源：[obra/superpowers](https://github.com/obra/superpowers)（MIT），引入日期 2026-08-16。
**内容保持上游原样，不做本地改写**（便于上游更新）。

| 目录 | 触发时机 |
|------|----------|
| `brainstorming/` | 任何创造性工作前：探索意图、需求、设计后再实现 |
| `writing-plans/` | 有多步任务的规格后、动代码前：写执行计划 |
| `test-driven-development/` | 实现功能/修 Bug 前：先写测试 |
| `systematic-debugging/` | 遇到 bug/测试失败时：系统性调试而非猜测 |
| `verification-before-completion/` | 声称工作完成前：运行验证命令，证据先行 |
| `subagent-driven-development/` | 用计划驱动多子代理执行大任务时 |

> 与 `docs/governance/tooling-pitfalls.md` 的分工：本目录存技能（怎么做），陷阱清单存工具坑（什么别做）。
