# EngSmartSuite 路线图

> 单一维护者项目（zgrwo）+ AI 协作。本文件公开方向与决策门，避免"猜测优先级"。
> 最后更新：2026-09-18

## 当前状态

- v1.3.0：42 个分析方法，1033 项测试，覆盖率 89%，4 层测试防线 + 文档数值对账门禁。
- 已知短板：无类型检查（engine/web）、无性能回归基线（本计划补齐中）。

## 2026 Q4

- [ ] 文档站上线（mkdocs-material + GitHub Pages）并实现手册按章拆页 —— 仓库侧已完成，待首次 Pages 部署
- [ ] uv 锁文件 + 可复现 CI；pyDOE3 替换死依赖
- [ ] mypy 覆盖 core + services；性能基准周更
- [ ] 类型检查扩展至 engine/（第一批：_utils/_constants/capability/detection）

## 2027 H1

- [ ] mypy 扩展至 web/ 与 cli
- [ ] 覆盖率洼地 `engine/__init__.py`（52%）补齐
- [ ] 第 2 位维护者路径：至少 2 名外部贡献者、3 个合并 PR 后开放 triage 权限

## 决策门（满足条件才启动，启动前写 ADR）

| 决策 | 触发条件 | 状态 |
|---|---|---|
| 发布 PyPI | uv.lock 稳定 ≥2 个 releases，且 Release 安装类 Issue ≥1 个月为零 | ⏳ 未触发 |
| 英文/国际化 | ≥3 个来自非中文用户的 Issue 或功能请求 | ⏳ 未触发 |
| 第二维护者 | 外部合并 PR ≥3 且贡献者 ≥2 人 | ⏳ 未触发 |

## 适合新贡献者的任务（good first issue 候选）

1. 给 `web/` 的路由处理函数补类型注解（mypy 分批推进的前置）
2. 为 `benchmarks/` 增加 `process_capability` 与 `correlation` 两个基准任务
3. 手册某方法章节补充"常见参数误用"小节（每章 ≤30 行，附实际输出）
4. 为 `templates/` 增加模板参数自动校验脚本的测试用例
5. 补 docs/gallery.md 中缺失方法的示例图与一句话解读
