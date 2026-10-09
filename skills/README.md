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

### 已知差异：上游子集分发导致的**悬空引用**（不在本地改写修复）

Superpowers 是**按需子集**引入的（只取本项目用到的那几个技能目录），因此上游技能正文里
指向**未引入目录**的相对链接在本地是断的。这类断链**不修**（改了就破坏"保持上游原样、
便于上游更新"的前提），而是登记在此，供读者按上游仓库自取：

| 位置 | 悬空引用 | 说明 |
|------|----------|------|
| `subagent-driven-development/SKILL.md`（4 处：正文 + 2 处流程图节点） | `../requesting-code-review/code-reviewer.md` | 上游的 `requesting-code-review` 技能目录**未引入** → 本地无此文件（审查 2026-10-09 P3-8）。需要"最终整支代码审查"的提示词时，用本目录的 `task-reviewer-prompt.md` / `re-review-prompt.md`，或按需从 [obra/superpowers](https://github.com/obra/superpowers) 取该文件 |
| 同上 | `superpowers:requesting-code-review`（技能名引用） | 同上，是上游技能命名空间的引用，本地无对应技能 |

> 这两条**不会**被 CI 拦下：`scripts/verify_docs.py` 的链接检查只覆盖 `skills/*.md`（顶层单文件），
> 不含子目录；`mkdocs.yml` 也未收录 `skills/`。故**发现新的上游悬空引用时请补登本表**——
> 没有门禁替你看着。
