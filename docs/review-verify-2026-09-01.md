# review-2026-09-01.md 问题真伪复核记录（实例 + 源码逐项验证）

> 复核日期：2026-09-01 · 复核方式：源码逐行阅读 + 最小复现实例（Python 3.14 / pandas 3.0.3 / sklearn 1.8.0）
> 结论标记：✅ 属实（与报告一致） / ⚠️ 部分属实（机制真但影响/数量有出入） / ❌ 不属实

---

## P0 组

| # | 报告结论 | 复核结论 | 证据 |
|---|---------|---------|------|
| N-1 | datetime64 未处理 → json.dumps TypeError → 500 | ⚠️ **部分属实** | ①机制真：`web/api.py:76-96 _serialize_table` 的 lambda 对 datetime64 走 `else col`，实测 `values.tolist()` 产出 `datetime` 对象，`json.dumps` 抛 `TypeError: Object of type datetime is not JSON serializable`。②影响不实：a) 序列化调用在 `run_analysis` per-target `try/except`（api.py:185-222）内，实测异常被吞为 `status="error"` 结果 + HTTP 200，不是 500；b) 可达性未证实——engine/ 全目录无 datetime 运算，预处理把 datetime 特征 `to_numeric` 转 int64（实测），RAW_CAT 任务的引擎输出表中也未出现 datetime 列（10 个 RAW_CAT 任务全测）。结论：真实代码缺陷但当前 41 任务不可达、不会 500，属防御性缺口 |
| C-1 | 0 列 DataFrame 上 sort_values → KeyError | ✅ 属实（潜在） | `data_io.py:194` `pd.DataFrame([]).sort_values("缺失率(%)")` 实测 `KeyError '缺失率(%)'`。报告自述"未来 auto_report 接入时触发"，属实为潜在缺陷（当前 auto_report 已调用该函数但输入通常有列） |
| C-2 | `_validate_output_path` 在 try 外 → 裸 PermissionError | ✅ 属实 | `reporter.py:74/151/185` 三处调用均在其 `try:`（75/152/192）之前（实测代码顺序）。auto_report（audit.py:434）直接调用 `to_html` 无包装，异常会原样上抛 |
| T-1 | `test_power_analysis_p0_equals_p1_rejected` 函数体为空 | ✅ 属实 | AST 验证：函数 1615-1616 行，仅 docstring，0 条非文档语句；`pytest` 实测 **pass**（空转） |
| T-2 | xbar 偏移测试只验结构不验检出 | ✅ 属实（证据更强） | `test_r_reference.py:284-300` 仅断言 `status=="ok"` 与 `"ucl_x" in metadata`。实测引擎对 `data[19]+=3.0` 返回 `is_stable=True`、`xbar_violations={}`——**注入偏移实际未被检出，测试仍 pass**。报告建议的 `assert not metadata["is_stable"]` 若照加会直接红（需同时加大注入偏移） |
| G-1 | verify_manual_claims 无失败计数/无 sys.exit | ✅ 属实 | grep 全文件 0 个 `sys.exit`/`SystemExit`，无 fail 计数器；`rpt()` 仅拼文本到 buf；结尾 `print("Done.")`。且 .github/workflows 与 verify_all.py 均不调用该脚本，门禁完全 inert |

## P1 组

| # | 报告结论 | 复核结论 | 证据 |
|---|---------|---------|------|
| N-2 | sigma_multiplier 裸 float() 不防 NaN/Inf | ✅ 属实 | `reliability.py:268-269` `float(...)` + `except (ValueError, TypeError)`；`float("nan")/float("inf")` 实测不抛异常，代码路径无 `isfinite` 守卫，`ev_pct = ev * sigma_mult` 静默传播 |
| N-3 | contamination 字符串 → sklearn ValueError → 每次失败 | ✅ 属实（有同族新发现） | `detection.py:744` 无 safe_float。实测 `method="isolation_forest", contamination="0.05"` → InvalidParameterError → 引擎兜底 `status="error"`（每次都失败）；float 0.05 → ok。**新发现**：`contamination="auto"`（sklearn 合法）会在 summary 的 `f"(污染率={contamination:.1%})"` 格式化上抛 ValueError → 被 orchestrator 泛化为"数据格式不符合…"，属同族字符串参数未转换漏洞 |
| C-3 | 5 处 raise ValueError 被 orchestrator 泛化吞掉 | ❌ **不属实**（当前 HEAD） | doe_opt.py 5 处 raise：L1940/2054/2063/2066 均在 `doe_design` 内部 `try`→`except ValueError`（L2355）捕获，实测 taguchi 14/20 三水平因子返回引擎自拟消息"实验设计生成失败…"而非泛化文案；L775 `_desirability` 的调用方 `multi_objective_opt` 在调用前已校验 direction（L854-862），实测非法 direction 返回"优化方向…无效，请使用 'maximize' 或 'minimize'"。orchestrator 的 ValueError 泛化映射机制存在（L262-296）但所列 5 处均到不了它 |
| T-3 | 条件断言仅 1 处（非 7 处） | ⚠️ **部分属实**（口径依赖） | 若口径=“`if key in r.metadata` 守卫”则确实仅 1 处（L303）✅；若放宽到"表格列/存在性守卫绕过断言"则还有 `test_edge_cases.py:1639`（`if effects is not None and "主效应" in effects.columns`，无兜底 else，列改名即静默跳过）。"仅 1 处"低估了同族风险 |
| T-4 | = T-2 别名 | ✅ 属实 | 同 T-2 证据 |
| G-2 | ruff 版本漂移 + 注释失实 | ✅ 属实 | `.pre-commit-config.yaml:47` `rev: v0.16.2`，line 45 注释声称"与 pyproject.toml 一致"；`pyproject.toml:49` `ruff==0.16.3` |
| G-3/G-4 | verify_consistency 硬编码 True + 阈值 30<41 | ✅ 属实 | `verify_consistency.py:51-63`：`check("smartsuite package importable", True)` 等硬编码；`len(engine_all) >= 30`、`len(TASK_REGISTRY) >= 30` 均低于实际 41 |
| S-1 | task 无类型校验 → unhashable → 500 | ✅ 属实 | Flask test client 实测：`POST /api/analyze {"task": ["correlation"], ...}` → `TypeError: cannot use 'list' as a dict key`（app.py:334 `task not in TASK_REGISTRY`）→ **HTTP 500**（应 400）。抛错点实际在 334 行注册表成员检查而非 324 行（后者仅 targets 为空时求值），机制一致 |
| D-1 | 手册 6 组"10 个方法"实为 11 | ✅ 属实 | user-manual.md:14 "建模优化（10 个方法）"，实际 6.1-6.11 共 **11** 节；TASK_GROUPS「建模优化」= 11 任务，4 组合计 41；TOC 求和 8+5+10+12+5=40 为根因 |
| D-2 | E2E 示例 40/40 | ✅ 属实 | user-manual.md:1753 `# Results: 40/40 responded, 0 failed`，与同页"全部 41 个"结论（1737-1739）矛盾 |
| D-4 | skill 缺 doe_design | ✅ 属实 | skills/smartsuite-dev.md:85-87 列 5 项，缺 `doe_design`；app.js:501-503 有 6 项含 `doe_design`（另注：skill 引用的代码行号 418-439 也已过期，实际 501） |

## P2 组

| # | 报告结论 | 复核结论 | 证据 |
|---|---------|---------|------|
| C-4 | `if not categorical_cols:` falsy-trap | ✅ 属实 | data_io.py:67；docstring 承诺"为 None 则自动检测"，空 set 也触发自动检测。web/CLI 调用方均传 None 或经转换，暂无实际踩坑路径（潜在） |
| C-5 | 空 df 时 pd.cut 抛 ValueError | ✅ 属实 | `auto_generate_subgroup_col`（data_io.py:472 起）`pd.cut(range(0), bins=2)` 实测 `ValueError: Cannot cut empty array`（pandas 3.0.3）；当前需 0 行 df 才触发（潜在） |
| C-6 | reporter 循环 plt.close 仅 happy path | ✅ 属实（影响存疑） | reporter.py:65/139/174/273 均在 savefig 成功后 close；异常中断即跳过。引擎 Figure 均 `from matplotlib.figure import Figure` 直接创建（无 pyplot manager），实际泄漏风险被夸大 |
| C-7 | audit `_close_figures` 用 fig.clear() | ✅ 属实（影响存疑） | audit.py:17-21 `fig.clear()`。同理，引擎 Figure 不注册 pyplot，无 FigureManager 引用，"内存泄漏"论断在引擎场景不成立 |
| C-8 | 警告文案"已丢弃"≠实际"归入参照组" | ✅ 属实 | api.py:158 文案"已丢弃: {extra_cats}"；data_io.py:112-118 实际将未知类别行归入 drop_first 参照组（日志原文"已归入参照组"），数据行未删除，文案误导 |
| C-9 | Cook's D except 缺 exc_info | ✅ 属实 | doe_opt.py:166 `logger.warning("Cook's D 计算失败 ...: %s", e)` 无 `exc_info=True` |
| C-10 | c4 内联 1e-10 未引用 EPSILON | ✅ 属实 | spc_charts.py:31 `c4 = max(c4, 1e-10)`；`_constants.py:13 EPSILON = 1e-10` 值相同未引用 |
| S-2 | cleanup TOCTOU | ✅ 属实（自认可接受） | app.py:76-99 锁内快照→锁外遍历→锁内删除，OSError 兜底存在，与报告"可接受"描述一致 |
| S-3 | SESSION_COOKIE_SECURE=False | ✅ 属实 | app.py:155，注释已标注本地 HTTP 设计 |
| S-4 | targets/features 无上限 | ✅ 属实 | analyze 路由无数量上限（仅上传端 max_cols=500，app.py:269 有列级限制） |
| A-1 | to_excel xlwings 鸭子类型遗留 | ✅ 属实 | reporter.py:32-69 参数 `workbook` 走 `.sheets.add/.range`，无 xlwings import、无类型标注，docstring 已声明弃用路径（audit.export_workbook 为替代） |
| A-2 | api.py 顶层 import pyplot | ✅ 属实 | api.py:8 |
| A-3 | RAW_CAT_TASKS 函数体内延迟导入 | ✅ 属实 | api.py:139（run_analysis 内部） |
| T-5 | 测试数据相对路径依赖 cwd | ✅ 属实（文件名小偏差） | 实际在 `tests/test_services/test_diff_cli_web.py:33-36`（报告省略子目录）；test_web_e2e.py:119 `open("tests/test_data.xlsx")` 同。另注意 diff 测试用 `pytest.skip` 兜底——cwd 错时静默跳过 41 项 L4 差分而非失败 |
| G-5 | "严格"声明与 ≤5 表/≤3 图容差矛盾 | ✅ 属实 | verify_cross_consistency.py:411 `tables_mismatch > 5 or figs_mismatch > 3` 才非零退出 |
| G-6 | generate_images 无退出码约束 | ✅ 属实 | generate_images.py:155-177 打印成功/失败数后无 sys.exit，main 直接返回 |
| G-7 | manifest 解析失败静默跳过版本检查 | ✅ 属实 | verify_docs.py:339-346 `manifest_version = ""`，后续 `if manifest_version and ...` 两处漂移检查全部静默跳过 |
| G-8 | quality.yml ruff 0.16.2 + format 不含 tests/ | ✅ 属实 | quality.yml:111 `pip install ruff==0.16.2`；:113 `ruff format --check src/smartsuite/ scripts/`（无 tests/；ci.yml:109 的 ruff check 含 tests/） |

## 第 4 节（初审误判撤回）复核

| 项 | 撤回结论 | 复核 | 证据 |
|----|---------|------|------|
| 原 T-1（AssertionError 拼写） | ❌ REFUTED | ✅ 撤回正确 | `AssertionError` 是内置正确拼写且被真实使用（test_edge_cases.py:699 等 5+ 处）；差分测试死因是旧文件 `_diff_cli_web.py` 不符 pytest `test_*.py` 收集规则（现 test_diff_cli_web.py 头注释自述） |
| 原 D-3（project-structure 缺 engine 模块） | ❌ REFUTED | ✅ 撤回正确 | 逐项比对 project-structure.md：engine/ 13 个文件（12 模块 + `__init__.py`）全部出现，无遗漏 |
| 原 T-3（"同批共 7 处"） | ⚠️ PARTIAL | ✅ 撤回方向正确 | 见上 P1 组 T-3——"1 处"仅对 `in r.metadata` 口径成立 |

## 第 5 节（测试覆盖）抽核

| 层 | 报告 | 抽核结果 |
|----|-------|---------|
| L1 数值正确性 40/41 | doe_design 缺已知答案测试 | ✅ 属实——tests/test_engine/test_doe_design.py 30+ 测试全为结构/正交(_assert_orthogonal)/水平平衡/维度断言，无与标准正交表逐值对照的"已知答案" |
| L2 ~16/41 | 22 个方法无专属不变量测试 | 未逐项核验（存在 test_invariants.py，粗查可信） |
| L3 41/41 | 边界全量循环 | 抽核 test_edge_cases.py:699-771 确有 41 任务循环（空数据/全 NaN/单行/n=6000）并逐任务断言 |
| L4 41/41 | CLI/Web 差分 | 参数化测试存在（test_diff_cli_web.py）；注意其 fixture 对数据文件缺失用 skip 兜底（见 T-5），cwd 不符时整层静默跳过 |

## 复核中新发现（报告未覆盖，供参考）

1. `anomaly_detect` + `contamination="auto"`（sklearn 合法值）会在 summary `f"(污染率={contamination:.1%})"` 格式化上抛 ValueError → 泛化为误导文案（与 N-3 同族）。
2. T-2 注入偏移（subgroup 20 全体 +3.0，σ=2）实际**不足以越限**（is_stable=True），报告建议的断言按现有数据会红——修复时需同时加大偏移（如 +6 或控制图参数收紧）。
3. skill smartsuite-dev.md 引用的 app.js 行号（418-439）已过期（实际 501 起）。
4. diff parity 测试文件模块 docstring 自述 "40 methods"，与 41 任务参数化不一致（历史文案残留）。

---

### 汇总

| 组 | 属实 | 部分属实 | 不属实 |
|----|------|---------|--------|
| P0（6 项） | 5（C-1/C-2/T-1/T-2/G-1） | 1（N-1） | — |
| P1（12 项） | 10（N-2/N-3/T-4/G-2/G-3/G-4/S-1/D-1/D-2/D-4） | 1（T-3） | 1（C-3） |
| P2（19 项） | 19 | — | — |
| 第 4 节撤回 | 3/3 撤回成立 | — | — |

**主要纠偏**：N-1 影响被夸大（不会 500、当前不可达）；C-3 五项 ValueError 全部到不了 orchestrator 泛化层（代码已内部兜底/预校验），按当前 HEAD 应判不属实；T-3 "仅 1 处"口径偏窄。
