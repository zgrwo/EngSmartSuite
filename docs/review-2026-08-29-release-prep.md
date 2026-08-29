# EngSmartSuite 发行前全量深度审查（第二轮）

| 元数据 | 值 |
|---|---|
| 审查日期 | 2026-08-29 |
| 本地审查基线 | `8aae3b1` docs: 修正手册数值漂移并同步文档声明与硬校验 |
| 远端基线 | `origin/main = 030c656`（**v1.2.2 已发行**，2026-08-29） |
| 上一轮报告 | `docs/review-2026-08-29.md` |
| 审查方法 | 门禁全量重跑 + 上轮 R1-R20 逐项复核 + 发行产物实构建核验（`pip wheel`） |

## 1. 版本拓扑（发行准备的第一事实）

```
  c43be41 (修复 3 个 MED 问题)
     ├── 030c656  chore: release 1.2.2  (#25)  ← 远端 main（已打 tag v1.2.2，仅含 c43be41）
     └── b9d32e6  fix(engine): 收敛裸异常+SPC 守卫   ┐
           └── 274c65f  test: 补 Dunn/DOE/宽表用例   ├── 本地 main（3 commit 未推送 = 待发版本内容）
                 └── 8aae3b1  docs: 手册漂移+硬校验   ┘
```

- **v1.2.2 已上线**，内容为 c43be41；本地 3 个提交（上一轮审查修复批次，共 181+ 行新增）**尚未推送、未发行**。
- 本地 3 提交均未触碰版本文件（pyproject/`__init__.py`/manifest/CHANGELOG）→ rebase 到 `origin/main` 无版本冲突。
- 下一次版本将由 release-please 自动推导：`fix(engine)` → **v1.2.3**（`test:`/`docs:` 进 CHANGELOG，不 bump）。

## 2. 门禁实测结果（本地 8aae3b1）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 全量验证 | `python scripts/verify_all.py` | ✅ **PASS**（构建/测试/文档/Falsy/质量守卫全过） |
| 单元/集成测试 | `pytest tests/ -q` | ✅ **670 passed / 4 skipped**（较上轮 +6） |
| 代码风格 | `ruff check` | ✅ 全绿（81 文件已格式化） |
| 文档一致性 | `python scripts/verify_docs.py --strict` | ✅ PASS（上轮 R1 已解除） |
| 注册一致性 | `scripts/verify_consistency.py` | ✅ **65/65 PASS** |
| 跨层一致性 | `scripts/verify_cross_consistency.py` | ✅ ALL PASS |
| 环境诊断 | `scripts/doctor.py` | ✅ 21/21 PASS |
| 手册数值 | `scripts/verify_manual_claims.py` | ✅ 通过（含新增 §7.6/§8.1 硬校验） |
| Falsy 审计 | `scripts/falsy_audit.py` | ✅ 0 HIGH |
| 测试质量守卫 | `scripts/test_quality_guard.py` | ✅ PASS |

## 3. 上轮问题（R1-R20）处置复核

| 项 | 处置 | 复核证据 |
|---|---|---|
| R1 test_data_u.xlsx 破门禁 | ✅ 已修复 | verify_docs --strict PASS；git status 干净 |
| R2 手册 RMSE=2.495 漂移 | ✅ 已修复+防再漂 | `user-manual.md:1281`=1.2415；`verify_manual_claims.py` 新增 §7.6 硬校验（tol 0.001） |
| R3 detection 裸异常入消息 | ✅ 已修复 | `detection.py:758-761` 中文文案，无 `{e}` |
| R4 crossval_r 虚假"R 对比" | ✅ 已修复声明 | `project-structure.md` 改为"不再声称 R 参考" |
| R5/R6 doe_opt `str(e)` 泄漏 | ✅ 已修复 | `doe_opt.py:1134,1194`="计算异常（详见日志）" |
| R7 手册 §8.1 bootstrap CI 漂移 | ✅ 已修复+防再漂 | 硬校验 4.2491/4.1740/4.3244 已入 `verify_manual_claims.py` |
| R8 Dunn 分支零覆盖 | ✅ 已补测 | `test_root_cause.py__test_hypothesis_kruskal_n_posthoc_triggered`（含 C(3,2)=3 行断言） |
| R9 弱断言/恒真断言 | ✅ 已硬化 | `test_invariants.py`（+73/-40）、`test_orchestrator.py`（+30） |
| R10 fuzz 宽表/重复值承诺 | ✅ 已补例 | `test_fuzz.py` +54 行 |
| R11 CLI/Web 编排重复 | ⚠️ 未处理 | 架构性建议，非发行阻断（差分测试兜底） |
| R12 kappa 表名 | ✅ 已修复 | api-reference 正确 |
| R13 reporter 字体 except 无日志 | ✅ 已修复 | `reporter.py:96` 补 `logger.warning(..., exc_info=True)` |
| R14 spc 浮点 truthiness | ✅ 已修复 | `spc_charts.py` `if ucl_2s is not None:` |
| R15 web 空数据降级进引擎 | ⚠️ 未处理 | 低风险设计项，非发行阻断 |
| R16/R17 巨型文件/重型初始化 | ⚠️ 未处理 | 设计取舍，非发行阻断 |
| R18 cli.py 缺席架构图 | ✅ 已修复 | `AGENTS.md:73` 第五入口 |
| R19 "40 任务"过时文案 | ✅ 已修复 | `ci.yml`→41 任务门禁 |
| R20 bootstrap random_state 缺失 | ✅ 已修复 | `api-reference.md:322` 补全 |

## 4. 🚨 本次新发现：发行阻断级打包缺陷

**证据（实构建核验）**：`pip wheel .` 产出 `smartsuite-1.2.1-py3-none-any.whl`（175KB），解包后**缺少三件 Web 资产**：

| 源码文件 | wheel 内 |
|---|---|
| `smartsuite/web/templates/index.html` | ❌ 缺失 |
| `smartsuite/web/static/app.js` | ❌ 缺失 |
| `smartsuite/web/static/style.css` | ❌ 缺失 |

**影响**：`render_template("index.html")`（`web/app.py:186`）在 Flask 默认 `templates/` 目录下找不到模板 → **从 wheel 安装 `smartsuite[web]` 后 Web UI 首次访问即 `jinja2.TemplateNotFound`，整个界面不可用**。sdist 同理（MANIFEST.in 的 `graft templates` 只覆盖仓库根部 YAML 模板，不含 `smartsuite/web/` 下资产）。

**根因**：`pyproject.toml` 无 `[tool.setuptools.package-data]` 声明；MANIFEST.in 未覆盖包内资源。

**修复建议（发行前必须）**：
```toml
[tool.setuptools.package-data]
"smartsuite.web" = ["templates/*", "static/*"]
```
修复后重建 wheel 验证三文件在包内。

## 5. 发行就绪检查单

| # | 项 | 状态 |
|---|---|---|
| 1 | 门禁全绿（含文档/一致性/守卫） | ✅ 已核 |
| 2 | 上轮 R 系列缺陷修复并复核 | ✅ 已核（R11/R15/R16/R17 为非阻断设计项） |
| 3 | wheel/sdist 含 Web 资产 | ❌ **未达**（P0 阻断，见 §4） |
| 4 | 版本号一致性（pyproject=`__init__.py`=manifest） | ✅ 1.2.1 三处一致 |
| 5 | 本地 3 个修复提交推送/合入远端 | ⚠️ 待执行（rebase 到 `origin/main` 应为 fast-forward、无版本冲突） |
| 6 | Conventional Commits 规范 | ✅ fix/test/docs 合规，release-please 可用 |
| 7 | 下一版本推导 | ✅ 将自动产生 **v1.2.3**（fix → patch） |
| 8 | 发行后 smoke 验证 | ⚠️ 建议：空 venv `pip install .[all]` → `run_server.py` → 打开首页/跑一个分析 |

## 6. 结论

代码质量面无发行阻断：上轮 R1-R20 中 16 项已修复并复核通过，4 项非阻断设计项存留；全部门禁绿。**唯一也是必须处理的发行阻断项是 wheel/sdist 缺失 Web 资产（§4）**——这是纯代码/文档审查无法发现、只有实构建产物核验才能暴露的缺陷。处理顺序：① 修 `package-data` → 重建 wheel 确认 → ② rebase+推送本地审查批 → ③ release-please 产出 v1.2.3 → ④ 发行后 wheel 安装 smoke。

---
*依据：`c43be41..8aae3b1` 实仓库核验 + `pip wheel` 实构建 + 全部门禁重跑（2026-08-29）。*