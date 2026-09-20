# EngSmartSuite 路线图

> 单一维护者项目（zgrwo）+ AI 协作。本文件公开方向与决策门，避免"猜测优先级"。
> 最后更新：2026-09-19

## 当前状态

- v1.3.1：42 个分析方法，1015 项测试，覆盖率 90%，4 层测试防线 + 文档数值对账门禁。
- 类型检查：mypy 全覆盖 `src/smartsuite`（core/services/engine/web/cli），CI 软门禁。
- 测试告警：`filterwarnings = ["error", ...]` 白名单制，全量 0 告警。
- 已知短板：社区回路（单一维护者）、英文/国际化未启动。

## 2026 Q4

- [ ] 文档站上线（mkdocs-material + GitHub Pages）并实现手册按章拆页 —— 仓库侧已完成，待首次 Pages 部署
- [x] uv 锁文件 + 可复现 CI；pyDOE3 替换死依赖
- [x] mypy 覆盖 core + services；性能基准周更（benchmarks/ + Benchmarks workflow）
- [x] 类型检查扩展至 engine/ 及 web/、cli（2026-09-19 全覆盖，零豁免）
- [x] 测试告警清零（error 白名单制，2026-09-19）
- [x] 巨石模块 `root_cause.py` 拆分为子包（3,999 行 → 10 文件，公开 API 不变，2026-09-19）
- [x] 巨石模块 `spc_charts.py` / `doe_opt.py` 同模式拆分为子包（2,220/2,471 行 → 8/6 文件，公开 API 不变，2026-09-19）
- [x] 子包 lint 豁免收敛：B905（`zip(strict=True)`）/B007 清零，仅保留 N803（统计符号 `X`）与 SIM108（风格）并注明理由（2026-09-19）
- [x] 覆盖率洼地 `engine/__init__.py` 补齐（平台分支 pragma 化后 100%，2026-09-19）
- [x] 覆盖率门禁 70 → 85，并在 PR quality.yml 增设覆盖率门禁（2026-09-19）

## 2027 H1

- [ ] 第 2 位维护者路径：至少 2 名外部贡献者、3 个合并 PR 后开放 triage 权限

## 决策门（满足条件才启动，启动前写 ADR）

| 决策 | 触发条件 | 状态 |
|---|---|---|
| 发布 PyPI | uv.lock 稳定 ≥2 个 releases，且 Release 安装类 Issue ≥1 个月为零 | ⏳ 未触发 |
| 英文/国际化 | ≥3 个来自非中文用户的 Issue 或功能请求 | ⏳ 未触发 |
| 第二维护者 | 外部合并 PR ≥3 且贡献者 ≥2 人 | ⏳ 未触发 |

## 适合新贡献者的任务（good first issue 候选）

> 开工流程、开发环境与提交前必检见 [CONTRIBUTING.md](CONTRIBUTING.md#第一个-pr约-15-分钟)。
> 选好一条后请开 Issue 认领，避免两人同时动同一处。

1. 为 `benchmarks/` 增加 `process_capability` 与 `correlation` 两个基准任务
2. 为 `templates/` 增加模板参数自动校验脚本的测试用例
3. 补 `docs/gallery.md` 中缺失方法的示例图与一句话解读
4. 把「常见参数误用」小节推广到 01–03 / 09–10 章节：方法章节已于 2026-09-19（C5）完成，可直接沿用同一模式
   —— 先实跑采集真实输出，再用 `tests/services/test_manual_usage_pitfalls.py` 的双向契约断言兜住
