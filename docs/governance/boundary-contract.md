# 边界处理契约（B0–B3）

> **本文件与 [sentinel-contract.md](sentinel-contract.md) 的分工**：
> - `sentinel-contract.md` 定义 **值级** 哨兵语义（L1–L5）：一个 `NaN`、一个转换失败的值应该**变成什么**。
> - 本文件定义 **输入级** 处置级别（B0–B3）：一个退化**输入**（含 Inf 的列、常量列、超大子组、歧义编码）
>   应该被**拒绝 / 清洗 / 降级 / 近似**，以及**用户必须看到什么**。
>
> 两者互补，不重叠。本文件不重新定义哨兵值。

## 为什么需要

第三轮复核（`logs/reports/verify-round3/R3-复核清单.md`）发现同一个反模式反复出现：
**引擎内部知道真实原因，但出口把它抹成泛化文案。**

| 真实原因 | 用户看到的 | 证据 |
|---|---|---|
| 子组 n=400 超出 `math.gamma` 能力 | `数值溢出，数据中可能存在极端值` | P0-1，端到端复现 |
| 列中含 `+Inf` 导致分组 σ 不可算 | `所有分组标准差均为零（常量数据）` | R2 已证实 |
| 非有限值被剔除 | 部分模块静默、部分披露 | 覆盖 6/12 模块 |

根因不是某处映射表写错，而是**没有"边界处置"这一层概念**——
每个函数各自决定要不要清洗、清洗后要不要说、说不说得出原因。本契约把这一层固定下来。

## B0–B3 处置级别

| 级别 | 名称 | 语义 | 输出要求 | 典型场景 |
|:---|:---|:---|:---|:---|
| **B0** | **拒绝** | 无法给出有意义结果 | `status="error"` + `code` + 中文工艺术语 + **可执行建议** | 常量列做能力分析；`USL ≤ LSL`；事件列编码歧义 |
| **B1** | **清洗** | 可安全移除后继续，结论不受影响 | 移除 + `messages` 披露**数量与列名** | `NaN`、`±Inf` |
| **B2** | **降级** | 主路径不可用，存在等价次路径 | 走次路径 + **结果与图表标注降级** | PPF 失败 → 经验分位数；Box-Cox 失败 → 原尺度 |
| **B3** | **近似** | 无精确解，用渐近/近似 | 计算 + **标注所用口径** | 超大 n 的 c4 渐近式；偏 η² |

### 两条硬性要求

1. **B2/B3 必须在用户可见处标注。**
   反例（现状）：`spc_charts/nonparametric.py` 的 PPF 回退只写 `logger.debug`，
   而图表标题仍写"拟合=Weibull"——用户以为看到的是理论分布控制限。
   **禁止**任何只在 `logger.debug` 里说明的降级。

2. **禁止错误归因。**
   若处置原因不是 X，就不允许输出关于 X 的提示。
   反例（现状）：`+Inf` 导致 σ 不可算，却提示"常量数据（标准差为零）"——
   用户按提示去查常量列，永远查不到原因。
   **B0 的 `code` 字段就是为此存在的**：它让真实原因可以穿透到出口，
   而不是被压进 12 条泛化文案里。

## `code` 命名规范

```
E_<域>_<原因>
```

| 前缀 | 域 |
|---|---|
| `E_DATA_` | 数据内容（非常量、非有限、空列） |
| `E_PARAM_` | 参数取值（越界、类型、互斥） |
| `E_SCALE_` | 规模（行数、列数、子组大小、水平数） |
| `E_DESIGN_` | 设计/结构（列缺失、编码歧义、不平衡） |
| `E_NUMERIC_` | 数值（溢出、奇异、不收敛） |

已登记的错误码见下方「边界清单」表。新增必须在此登记。

## 边界清单（B0–B3 全量）

> 状态：`✅已规范` = 现有行为已符合契约；`⚠待规范` = 本轮计划要改。

| # | 退化输入 | 级别 | 期望行为 | `code` | 现状 |
|---|---|---|---|---|---|
| 1 | `±Inf` 混入目标列 | B1 | 剔除 + 披露数量与列名 | `E_DATA_NON_FINITE_DROPPED` | ⚠待规范（覆盖 6/12 模块） |
| 2 | 参数为非有限值（`k=nan`、`h=inf`） | B0 | 拒绝 + 指出参数名与实际值 | `E_PARAM_NON_FINITE` | ⚠待规范（部分模块有守卫） |
| 3 | 子组 n ≥ 380（c4 溢出） | B3 | 走对数域稳定路径；若仍不可行则 B0 | `E_NUMERIC_GAMMA_OVERFLOW` | ⚠待规范（当前崩溃 + 误报） |
| 4 | 子组大小不一致 | B0 | 拒绝并给拆分建议（或按 nᵢ 加权，需显式声明） | `E_DESIGN_UNEQUAL_SUBGROUP` | ⚠待规范（当前静默取 min(n)） |
| 5 | 目标列唯一值 ≤ 1（常量列） | B0 | 拒绝 + 说明"无变异" | `E_DATA_CONSTANT_COLUMN` | ⚠待规范（各模块不一致） |
| 6 | 有效样本量 < 方法下限 | B0 | 拒绝 + 给出该方法的**具体**最小 n | `E_DATA_INSUFFICIENT_N` | ⚠待规范（逐函数各自判） |
| 7 | 列存在但全为 NaN | B0 | 拒绝 + 明确"整列为空"（区别于"样本不足"） | `E_DATA_EMPTY_COLUMN` | ⚠待规范 |
| 8 | 事件列文本 2 值，语义不明 | B0 | 拒绝 + 要求显式声明失效值 | `E_DESIGN_EVENT_AMBIGUOUS` | ⚠待规范（当前字典序猜，P0-2） |
| 9 | 事件列数值非 {0,1} | B0 | 拒绝 + 列出实际取值 | `E_DESIGN_EVENT_ENCODING` | ✅已规范（`reliability.py:696-707`） |
| 10 | 因子水平数 > 200 | B0 | 拒绝 + 建议改回归或分箱 | `E_SCALE_TOO_MANY_LEVELS` | ✅已规范（`anova.py:74-85`） |
| 11 | 行数 > 100k / 列数 > 500 | B0 | 拒绝（Web 层） | `E_SCALE_ROWS` / `E_SCALE_COLS` | ✅已规范（`config.py`） |
| 12 | 微尺度数据（~1e-10） | B3 | 用相对阈值判决；展示走 `round_for_display` | — | ✅已规范（`test_micro_scale_guards.py`） |
| 13 | UTF-16/Big5 无 BOM | B0 | 拒绝 + 要求转 UTF-8 或显式声明编码 | — | ✅已规范（`data_io.py`，ADR-0004） |
| 14 | 混合 dtype 列 → parquet | B1 | 转 string + 披露 | — | ✅已规范（`_parquet_safe`） |
| 15 | 上传文件被清理线程删除（TOCTOU） | B0 | 专项 400（非裸 500） | — | ✅已规范（`app.py:408`） |
| 16 | `PPF` 失败回退经验分位数 | B2 | 回退 + **图表标题标注** | `E_NUMERIC_PPF_FALLBACK` | ⚠待规范（仅 debug 日志） |
| 17 | Box-Cox 变换失败 | B2 | 用原尺度 + 披露（当前已披露 ✅） | — | ✅已规范（`capability.py:212`） |
| 18 | 正态性两处判据不一致（SW p<0.01 vs `sw or ad`） | B3 | 统一判据或标注口径 | `E_NUMERIC_NORMALITY_RULE` | ⚠待规范 |
| 19 | 数值溢出（通用） | B0 | 拒绝 + **指出哪个参数/数据的量级** | `E_NUMERIC_OVERFLOW` | ⚠待规范（当前误报"极端值"） |
| 20 | 多组 log-rank（>2 组） | B2 | 静默不做的现状 → 明确披露"未做" | `E_DESIGN_LOGRANK_SKIPPED` | ⚠待规范（当前静默） |

## 契约的执行点

**唯一实现**：`src/smartsuite/engine/_guard.py`

新增或修改引擎函数时，**不得**再手写清洗/校验循环；必须经 `_guard` 的下列入口：

| 函数 | 用途 |
|---|---|
| `clean_series(s, column=, report=)` | B1 单列非有限值清洗（入口） |
| `clean_frame(frame, cols, report=)` | B1 多列按行清洗（入口） |
| `check_n(n, minimum, what=, report=)` | B0 样本量下限 |
| `check_non_constant(s, what=, report=)` | B0 常量列 |
| `check_magnitude(s, what=, report=)` | B0 量级上界（`E_SCALE_EXTREME_MAGNITUDE`：平方和溢出会让判决静默翻转） |
| `check_finite_param(value, name, report=)` | B0 参数非有限 |
| `check_tables_finite(tables, what=, code=, report=)` | B0 输出侧后置断言（结果表出现 inf/nan 即拒绝；判据来自 `non_finite_tables`） |
| `explain_undefined_sigma(values, column=, what=)` | σ 不可估计时的**正确归因**（常量 → 非有限值 → 样本量 → 兜底） |
| `BoundaryIssue` / `BoundaryReport.messages()` | 处置记录 → 中文 `messages`（`BoundaryReport.codes()` 给机器可读错误码） |

> 本表即 `_guard` 的**全部**对外执行点（`partition_finite` / `non_finite_detail` / `non_finite_tables`
> 属内部原语与文案构造，不直接调用）。新增执行点时必须同步本表 —— 该表曾失真：登记了全库 0 匹配的
> `c4_asymptotic(n)` 与 `to_messages(issues)`（审查 2026-10-09 P2-1），同时漏登记真实存在的
> `explain_undefined_sigma` / `check_magnitude` / `check_tables_finite`。

> **B3 的「超大 n 的 c4 稳定计算」不在 `_guard` 内**：实现在
> `src/smartsuite/engine/spc_charts/we_rules.py` 的 `c4()`（`n ≥ 380` 走对数域）。
> 原表此处登记的 `c4_asymptotic(n)` 是全库 0 匹配的失真符号（见上）。

**守卫**：`tests/guards/test_boundary_contract.py` 断言
(a) 已接入模块遇到退化输入时披露正确；
(b) 任何模块**不得**对 `+Inf` 输入报出"常量列"字样（错误归因回归防线）。

## 维护规则

- 本契约变更必须同步：`logs/reports/verify-round3/R3-复核清单.md`（证据）、
  `docs/governance/improvement-plan.md`（计划状态）、`skills/smartsuite-dev.md`（陷阱清单）。
- 新增边界处置 → 必须在「边界清单」表登记 `code` 与级别。
- 本文件是**唯一**边界级别定义处；其他文档只链接引用，不复制表格。
