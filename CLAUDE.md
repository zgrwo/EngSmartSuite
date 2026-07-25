# CLAUDE.md — EngSmartSuite

工艺数据分析工具箱，将 Python 统计分析能力与 Excel 交互体验深度整合。

> **本文件是 AI 编程助手的首要入口**。架构红线与工作流见 [agents.md](agents.md)，编码细节按需加载 Skill，领域术语见 [rules/context.md](rules/context.md)。

## 文档路由

| 目的 | 文件 | 何时查阅 |
|:---|:---|:---|
| **项目宪法** (红线+工作流) | [agents.md](agents.md) | 始终 |
| API 签名 (40 函数) | [rules/api-reference.md](rules/api-reference.md) | 修改 UDF 签名时 |
| 领域术语 | [rules/context.md](rules/context.md) | 不确定术语含义时 |
| 用户手册 | [rules/user-manual.md](rules/user-manual.md) | 了解函数用法时 |
| 编码规范 + 陷阱 | [skills/smartsuite-dev.md](skills/smartsuite-dev.md) | 修改 Python 源码前 |
| 分析方法决策树 | [skills/analysis-decision-tree.md](skills/analysis-decision-tree.md) | 为用户推荐方法时 |
| 架构审查 | [skills/architecture-reviewer.md](skills/architecture-reviewer.md) | 架构变更时 |
| 重构护栏 | [skills/refactoring-guardian.md](skills/refactoring-guardian.md) | 重构时 |
| 统计审查 | [rules/statistics-review.md](rules/statistics-review.md) | 修改统计逻辑时 |
| Falsy 陷阱 | [rules/falsy-pitfalls.md](rules/falsy-pitfalls.md) | 涉及条件判断时 |

## 架构分层

```
web/ (Flask UI) → services/ (桥接层) → engine/ (纯 Python 分析引擎) → core/ (数据契约)
```

- `web/` 禁止直接 `import engine/` — 必须通过 `services/orchestrator.py`
- `engine/` 禁止导入 `flask` 或 `xlwings`
- 所有引擎函数签名：`(AnalysisRequest) -> AnalysisResult`

## 红线

- **禁止修改** Public API 签名（40 个分析函数接口冻结）
- **提交前** 运行 `pytest && ruff check src/`
- **git push** 前必须获得用户明确同意
- **信息 SSOT**：每个事实只在一处定义，其余仅链接引用

## 常用命令

```bash
pytest                                  # 运行测试
pytest tests/ -x -q                     # 快速运行（遇错即停）
ruff check src/smartsuite/              # 代码检查
python run_server.py                    # 启动 Web UI
python -m smartsuite.cli list           # 列出所有分析方法
bash scripts/verify-docs.sh             # 文档一致性验证
python scripts/verify-manual.py         # 手册示例验证
python scripts/falsy_audit.py           # Falsy 模式审计
```

## 参考

| 文档 | 角色 |
|:---|:---|
| [agents.md](agents.md) | 项目宪法（红线+工作流+会话管理） |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南 |
| [README.md](README.md) | 用户入口（安装+功能速览） |
