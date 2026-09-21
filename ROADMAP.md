# EngSmartSuite 路线图

> 单一维护者项目（zgrwo）+ AI 协作。本文件公开方向与决策门，避免"猜测优先级"。
> 最后更新：2026-09-21

## 当前状态

- v1.4.0：42 个分析方法，982 项测试（口径：`pytest tests/ --collect-only`，2026-09-21 在 `v1.4.0` worktree 复核；同口径 `v1.3.1` = 954，`main` = 1263），覆盖率 90.04%（v1.4.0 CI 实测），4 层测试防线 + 文档数值对账门禁。
- 类型检查：mypy 全覆盖 `src/smartsuite`（core/services/engine/web/cli），CI 软门禁。
- 测试告警：`filterwarnings = ["error", ...]` 白名单制，全量 0 告警。
- 已知短板：社区回路（单一维护者）、英文/国际化未启动。

## 2026 Q4

- [x] 文档站上线（mkdocs-material + GitHub Pages）并实现手册按章拆页（2026-09-19 首次部署成功，站点可访问）
- [x] uv 锁文件 + 可复现 CI；pyDOE3 替换死依赖
- [x] mypy 覆盖 core + services；性能基准周更（benchmarks/ + Benchmarks workflow）
- [x] 类型检查扩展至 engine/ 及 web/、cli（2026-09-19 全覆盖，零豁免）
- [x] 测试告警清零（error 白名单制，2026-09-19）
- [x] 巨石模块 `root_cause.py` 拆分为子包（3,999 行 → 10 文件，公开 API 不变，2026-09-19）
- [x] 巨石模块 `spc_charts.py` / `doe_opt.py` 同模式拆分为子包（2,220/2,471 行 → 8/6 文件，公开 API 不变，2026-09-19）
- [x] 子包 lint 豁免收敛：B905（`zip(strict=True)`）/B007 清零，仅保留 N803（统计符号 `X`）与 SIM108（风格）并注明理由（2026-09-19）
- [x] 覆盖率洼地 `engine/__init__.py` 补齐（平台分支 pragma 化后 100%，2026-09-19）
- [x] 覆盖率门禁 70 → 85，并在 PR quality.yml 增设覆盖率门禁（2026-09-19）
- [x] 数据可信性收紧：CSV 编码静默乱码、audit 双重截断、numpy 类型、空串参数、error_id（2026-09-19，待随 1.4.1 发版）
- [x] 巨石模块 `detection.py` / `inverse.py` 拆分为子包（1,099/2,082 行 → 5/8 文件，公开 API 不变，2026-09-21）
- [x] 上传临时文件去进程级状态：专用目录 + mtime TTL 扫描（`web/app.py`，2026-09-21）
- [x] 部署形态决策：维持单机/单用户（[ADR-003](docs/adr/0003-deployment-scope-single-user.md)，2026-09-21）
- [x] 非 UTF-8 编码策略定向：自动探测经实测否证，改为 BOM 确定性判定 + 用户显式声明（[ADR-004](docs/adr/0004-csv-encoding-strategy.md)，2026-09-21）

## 2027 H1

- [ ] 第 2 位维护者路径：至少 2 名外部贡献者、3 个合并 PR 后开放 triage 权限

## 决策门（满足条件才启动，启动前写 ADR）

| 决策 | 触发条件 | 状态 |
|---|---|---|
| 发布 PyPI | uv.lock 稳定 ≥2 个 releases，且 Release 安装类 Issue ≥1 个月为零 | ⏳ 未触发 |
| 英文/国际化 | ≥3 个来自非中文用户的 Issue 或功能请求 | ⏳ 未触发 |
| 第二维护者 | 外部合并 PR ≥3 且贡献者 ≥2 人 | ⏳ 未触发 |
| 非 UTF-8 编码探测（charset-normalizer/chardet） | 出现繁体（Big5）来源的真实用户数据或误读报告 | ✅ 已评估并定向：自动探测经实测否证（GBK/Big5 短样本不可分），改走 BOM 判定 + 显式声明（[ADR-004](docs/adr/0004-csv-encoding-strategy.md)，2026-09-21） |

## 适合新贡献者的任务（good first issue 候选）

> 开工流程、开发环境与提交前必检见 [CONTRIBUTING.md](CONTRIBUTING.md#第一个-pr约-15-分钟)。
> 选好一条后请开 Issue 认领，避免两人同时动同一处。

1. 为 `benchmarks/` 增加 `process_capability` 与 `correlation` 两个基准任务
2. 为 `templates/` 增加模板参数自动校验脚本的测试用例
3. 补 `docs/gallery.md` 中缺失方法的示例图与一句话解读
4. 把「常见参数误用」小节推广到 01–03 / 09–10 章节：方法章节已于 2026-09-19（C5）完成，可直接沿用同一模式
   —— 先实跑采集真实输出，再用 `tests/services/test_manual_usage_pitfalls.py` 的双向契约断言兜住
