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
| **B1** | **清洗** | 可安全移除后继续，结论不受影响 | 移除 + `messages` 披露**数量与列名** | **`±Inf`** |
| **B2** | **降级** | 主路径不可用，存在等价次路径 | 走次路径 + **结果与图表标注降级** | PPF 失败 → 经验分位数；Box-Cox 失败 → 原尺度 |
| **B3** | **近似** | 无精确解，用渐近/近似 | 计算 + **标注所用口径** | 超大 n 的 c4 渐近式；偏 η² |

### 缺失值（`NaN`）不属于 B1 —— 免披露

**2026-10-09 口径裁定**：B1 的判据是「**这个值是不是缺失**」，据此把两类值分开：

| 值 | 归类 | 处置 | 理由 |
|:---|:---|:---|:---|
| `NaN` | **缺失语义**（见 `sentinel-contract.md` L4） | 丢弃后继续，**不产生 `messages`** | 用户留空 / 采集失败；`dropna()` 静默丢弃已是全库既有语义，逐处弹消息只会变成噪音 |
| `±Inf` | **B1 清洗** | 移除 **+ 披露数量与列名** | "看起来像数据、数值上不合法"（除零 / 溢出），用户看不到也想不到，必须点名 |

落地实现（`engine/_guard.py`，唯一执行点）：

- `partition_finite` 的计数**只数 `±Inf`**（`np.isinf`），但返回的掩码仍是 `isfinite`
  —— 即 `NaN` 仍被剔除，只是**不进披露的数字**；
- `non_finite_detail` / `clean_frame` 的文案只点名 `±Inf`，与计数严格同名同量；
- `clean_frame(drop_nan=False)` 供 `correlation` 这类需要"成对完整观测"口径的调用方
  保留 `NaN`。

> 口径沿革（两次反复，留档以免第三次返工）：本契约原 B1 行写「`NaN`、`±Inf`」两者；
> 过程中一度按"只计 ±Inf"改过又被回退；最终按上述 L4/B1 拆分定稿，
> 并由 `tests/engine/test_boundary_guard.py`（`TestPartitionFinite`）与
> `tests/engine/test_trend_nonfinite.py`（NaN 静默用例）钉住。

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
| 1 | `±Inf` 混入目标列 | B1 | 剔除 + 披露数量与列名 | `E_DATA_NON_FINITE_DROPPED` | ✅已规范（`_guard` 唯一执行点，2026-10-09 全覆盖） |
| 2 | 参数为非有限值（`k=nan`、`h=inf`） | B0 | 拒绝 + 指出参数名与实际值 | `E_PARAM_NON_FINITE` | ✅已规范（声明式参数契约 `core/param_spec.py` 的 `Finite` 校验统一拒绝；引擎级另有 `_guard.check_finite_param`。实测 9/9：`spc_cusum k=nan`、`spc_cusum h=inf`、`spc_ewma lam=nan`、`process_capability usl=inf`、`normality_check alpha=nan`、`box_chart usl=inf`、`bootstrap_ci ci_level=nan`、`tolerance_interval coverage=inf`、`gage_rr sigma_multiplier=nan` 全部 `status=error` 且点名参数与实际值，2026-10-09 收尾实测） |
| 3 | 子组 n ≥ 380（c4 溢出） | B3 | 走对数域稳定路径；若仍不可行则 B0 | `E_NUMERIC_GAMMA_OVERFLOW` | ✅已规范（**原登记"当前崩溃 + 误报"已过期**：实现在 `spc_charts/we_rules.py::c4()`，`n ≥ 380` 走对数域。2026-10-09 实测 `c4(379)=0.9993388`、`c4(380)=0.9993406`、`c4(400)=0.9993736`、`c4(500)=0.9994991`、`c4(2000)=0.9998749` 全部有限且 ∈(0,1]） |
| 4 | 子组大小不一致 | B0/B2 | 拒绝并给拆分建议，或按 nᵢ 加权 / 最小 n 口径估计，**须显式声明** | `E_DESIGN_UNEQUAL_SUBGROUP` | ✅已规范（**原登记"当前静默取 min(n)"实测不成立**：`spc_xbar` 取 min(n) 的同时在 `messages` 与图表标题标注「子组大小不一致…控制限基于最小子组大小估计」，`metadata.subgroup_size` 如实回报最小 n；`spc_attribute` 的 np/c 图 **B0 拒绝**并建议改 p/u 图；p/u 图逐点变限（不降级）；`process_capability(subgroup_col=)` 按 nᵢ−1 自由度池化、含单观测子组时拒绝，`subgroup_size` 的非整数倍余数披露。由 `test_boundary_contract.py::TestUnequalSubgroupIsDisclosed` 钉住） |
| 5 | 目标列唯一值 ≤ 1（常量列） | B0 | 拒绝 + 说明"无变异" | `E_DATA_CONSTANT_COLUMN` | ✅已规范（`_guard.degenerate_column_code` **单一实现**：门禁判据在修复前源码上命中 **19 处**手写 `nunique(...) <= 1` 判据 → **17 处收口**、2 处具名例外（判的是计数而非观测列：子组大小一致性 `spc_charts/xbar_r.py:151`、设计单元平衡性 `root_cause/anova.py`）；三级口径（常量 / 整列为空 / 有效观测不足）由 `degenerate_column_reason` 统一出文案，源码级门禁 `test_boundary_contract.py::TestDegenerateColumnAttributionSSOT`，2026-10-09 收尾） |
| 6 | 有效样本量 < 方法下限 | B0 | 拒绝 + 给出该方法的**具体**最小 n | `E_DATA_INSUFFICIENT_N` | ⚠待规范（**部分达标**，2026-10-09 实测：`spc_cusum`「每组至少需要 5 个点」、`bootstrap_ci`/`median_ci`「至少5个点」、`process_capability`「至少需要 3 个观测值」均给出**具体**下限；但 `spc_ewma`/`trend_forecast`/`normality_check`/`regression` 在 n=3 时 `status=ok` 且**无任何下限提示** —— 这些方法没有登记最小 n，用户无从判断样本是否够用。逐函数各自判的现状仍在） |
| 7 | 列存在但全为 NaN | B0 | 拒绝 + 明确"整列为空"（区别于"样本不足"） | `E_DATA_EMPTY_COLUMN` | ✅已规范（`_guard.degenerate_column_code`，2026-10-09 P2-3；公开发布后全库判据统一走它） |
| 8 | 事件列文本 2 值，语义不明 | B0 | 拒绝 + 要求显式声明失效值 | `E_DESIGN_EVENT_AMBIGUOUS` | ✅已规范（`reliability.py::survival_analysis`：取值不在已知词汇内时拒绝并给两条可执行路径。2026-10-09 实测：事件列 `['B','A']` → `status=error`「事件列「e」的文本取值 ['B', 'A'] 语义不明确…① 用参数 event_value 显式声明失效标记…② 改为 0/1 编码」；`['失效','未失效']`/`['是','否']` 语义明确故正常放行） |
| 9 | 事件列数值非 {0,1} | B0 | 拒绝 + 列出实际取值 | `E_DESIGN_EVENT_ENCODING` | ✅已规范（`reliability.py:696-707`） |
| 10 | 因子水平数 > 200 | B0 | 拒绝 + 建议改回归或分箱 | `E_SCALE_TOO_MANY_LEVELS` | ✅已规范（`anova.py:74-85`） |
| 11 | 行数 > 100k / 列数 > 500 | B0 | 拒绝（Web 层） | `E_SCALE_ROWS` / `E_SCALE_COLS` | ✅已规范（`config.py`） |
| 12 | 微尺度数据（~1e-10） | B3 | 用相对阈值判决；展示走 `round_for_display` | — | ✅已规范（`test_micro_scale_guards.py`） |
| 13 | UTF-16/Big5 无 BOM | B0 | 拒绝 + 要求转 UTF-8 或显式声明编码 | — | ✅已规范（`data_io.py`，ADR-0004） |
| 14 | 混合 dtype 列 → parquet | B1 | 转 string + 披露 | — | ✅已规范（`_parquet_safe`） |
| 15 | 上传文件被清理线程删除（TOCTOU） | B0 | 专项 400（非裸 500） | — | ✅已规范（`app.py:408`） |
| 16 | `PPF` 失败回退经验分位数 | B2 | 回退 + **图表标题标注** | `E_NUMERIC_PPF_FALLBACK` | ✅已规范（提交 `716bce9`：`spc_charts/nonparametric.py:142-160` 把回退写进 `messages`、`:302-303` 在**图表标题**加「⚠ 控制限=经验分位数（PPF 不可用）」、`:355` 暴露机器可读回退标记） |
| 17 | Box-Cox 变换失败 | B2 | 用原尺度 + 披露（当前已披露 ✅） | — | ✅已规范（`capability.py:212`） |
| 18 | 正态性两处判据不一致（SW p<0.01 vs `sw or ad`） | B3 | 统一判据或标注口径 | `E_NUMERIC_NORMALITY_RULE` | ✅已规范（判决口径已单一：`root_cause/distribution.py` 以 Shapiro-Wilk p>α 为**唯一**判据，Anderson-Darling 在表内单元格（`:358`）与 summary（`:391-392`）**两处**标注「仅作参考，不参与判决」，超出临界值表时写成开区间；2026-10-09 实测 summary 原文即「判据: Shapiro-Wilk p>α；Anderson-Darling 仅作参考，不参与判决」） |
| 19 | 数值溢出（通用） | B0 | 拒绝 + **指出哪个参数/数据的量级** | `E_NUMERIC_OVERFLOW` | ⚠待规范（**部分达标**，2026-10-09 实测 ×1e300：`_guard.check_magnitude` 已接线 12 处（`doe.py`/`response_surface.py`/`regression.py`/`anomaly.py`/`trend.py`/`cusum.py`/`ewma.py`/`nonparametric.py`/`outlier.py`/`distribution.py`×2/`inference.py`）→ 这些任务给出「量级」+「单位换算/中心化」建议；但 `bootstrap_ci`/`median_ci`/`spc_xbar`/`box_chart`/`survival_analysis`/`grid_search`/`scatter_plot`/`tolerance_interval`/`cronbach_alpha`/`cohens_kappa`/`proportion_ci` 在 ×1e300 下仍 `status=ok` **且无任何量级披露**（结论不可信）；`gage_rr`/`lasso_regression`/`decision_tree` 由 orchestrator 兜底为「数值溢出/数据格式或数值范围」泛化文案（不是引擎主动归因）；`spc_attribute` 给出「总体不良率=6e98」这类**误导性**数值。原登记的「误报『极端值』」字样已从消息中消失，但量级归因仍未全覆盖） |
| 20 | 多组 log-rank（>2 组） | B2 | 静默不做的现状 → 明确披露"未做" | `E_DESIGN_LOGRANK_SKIPPED` | ✅已规范（提交 `716bce9`：`reliability.py:1497-1499` 生成「分组数为 N（> 2），本次**未做** log-rank 组间比较」的说明，`:1637-1643` 作为 B2 处置并入 `messages` 与 `boundary_codes`，`metadata.logrank_skipped_reason` 同时给出机器可读原因） |
| 21 | **量级上界**（`log10 max|s| > 150`，`Σy²` 溢出为 Inf） | B0 | 拒绝 + 点名量级 + 建议单位换算/中心化 | `E_SCALE_EXTREME_MAGNITUDE` | ✅已规范（`_guard.check_magnitude`，2026-10-09 P1-4；10 个任务接线） |
| 22 | 结果表渗出 inf/nan（出口保洁） | B0 | 出口后置断言：表内非有限即拒绝 | `E_NUMERIC_OUTPUT_NON_FINITE` / `E_NUMERIC_MODEL_DEGENERATE` | ⚠部分规范（**实现在，接线未覆盖**：`_guard.check_tables_finite` 已实现并有出口断言，但**仅 7/42 个任务接入** —— `doe_analysis` / `regression` / `lasso_regression` / `robust_regression` / `quantile_regression` / `response_surface` / `process_capability`；其余 35 个任务尚无出口保洁，实测反例：`process_capability` ×1e153 曾如实渗出 `inf` 且 `status=ok`（R2BD-01 已修）。接入清单与本行状态由 `test_boundary_contract.py::TestCheckTablesFiniteCoverageIsDeclared` **双向钉住**，2026-10-09 收尾） |
| 23 | 切片/分组后的退化列（全 NaN / 单有效值） | B0 | 归因优先级：整列为空 → 样本不足 → 常量 → 非有限 → 兜底（**与 `_guard.degenerate_column_code` 的实现同序，改动须同步**） | `E_DATA_EMPTY_COLUMN` / `E_DATA_INSUFFICIENT_N` / `E_DATA_CONSTANT_COLUMN` | ✅已规范（`_guard.degenerate_column_code` 单一实现 + `degenerate_column_reason` 单一文案源；17 处手写判据收口，2026-10-09 收尾。顺序台账曾与实现**互相颠倒**（R2BD-09），现由 `test_boundary_contract.py::TestAttributionOrderMatchesGuard` 逐序比对） |
| 24 | 分组列 / 子组列名不存在于数据中 | B0 | 拒绝 + 列出可用列 | `E_DESIGN_COLUMN_NOT_FOUND` | ✅已规范（`spc_cusum`/`spc_ewma`/`spc_xbar` 已前置校验，2026-10-09 P2-4） |
| 25 | 反解建模的特征列退化（历史中整列为空 / 常量 / 单观测） | B1 | 剔除该列 + 披露**列名与真实原因** | `E_DATA_EMPTY_COLUMN` / `E_DATA_INSUFFICIENT_N` / `E_DATA_CONSTANT_COLUMN` | ✅已规范（`inverse/_models.py::_fit_forward` 经 `first_degenerate_reason` 归因后写入 `BoundaryReport` → `messages` + `metadata.boundary_codes`；此前只写 `logger.warning`，2026-10-09 收尾） |
| 26 | 反解 auto 候选因规模被削减（n≥500 / poly 展开超限） | B2 | 走次路径 + 披露跳过了哪些候选 | `E_SCALE_AUTO_CANDIDATE_SKIPPED` | ✅已规范（`inverse/_models.py::_auto_candidates` 的说明此前仅入日志，现并入报告；2026-10-09 收尾） |
| 27 | 来料/输出无法按后缀配对 → 共用 / 顺序配对 | B2 | 回退 + 披露配对明细 | `E_DESIGN_PAIRING_FALLBACK` | ✅已规范（`inverse/_models.py::_fit_rate_forward`；配对方式决定每个输出用哪一列来料，2026-10-09 收尾） |
| 28 | 速率模型时间列无效（缺失或为 0）的行被剔除 | B1 | 剔除 + 披露剔除行数与剩余行数 | `E_DATA_INVALID_TIME_DROPPED` | ✅已规范（`inverse/_models.py::_fit_rate_forward`；速率 = (来料−输出)/t，t 无效时该行不可用。此前仅 `logger.warning`，2026-10-09 收尾） |
| 29 | 速率模型逐输出剔除含缺失/非有限特征的行 | B1 | 剔除 + 点名**输出列**与行数 | `E_DATA_INCOMPLETE_ROWS_DROPPED` | ✅已规范（`inverse/_models.py::_fit_rate_forward`；各输出实际参与拟合的行数可能不同。此前仅 `logger.warning`，2026-10-09 收尾） |
| 30 | 投票制任务中某个方法不可用（IsolationForest 初始化/拟合失败） | B2 | 走剩余方法 + **披露未参与的方法名与投票成员数变化** | `E_NUMERIC_METHOD_UNAVAILABLE` | ✅已规范（`detection/outlier.py::outlier_consensus`：原实现只写 `logger.debug` 且把该列照常渲染为「否」，用户无法分辨「未运行」与「未发现」（审查 2026-10-09 R2BD-04）。现四处可见：`messages` + `boundary_codes` + 结果表该列写「未参与」+ `metadata.voting_methods` 回报成员数；日志升为 WARNING。由 `tests/engine/test_outlier_consensus_degradation.py` 钉住） |

> 状态列口径：`✅已规范` = 代码已实现且有用例钉住；`⚠待规范` = 契约已登记但实现未达标。
> 上表 21–24 为 2026-10-09 发版前全量审查的修复轮新增/收口项；
> **25–29 为同日发版前收尾轮新增**（`inverse/_models.py` 的日志级降级收口为可见处置）。
>
> ⚠️ 状态列**逐行实测于 2026-10-09 收尾轮**（原 `⚠待规范` 的 #2/#3/#4/#5/#8/#16/#18/#20 实测已达标，
> 登记文案已过期 → 改 `✅已规范` 并写明实现位置与实测证据；#6/#19 实测**部分达标**，保留 `⚠待规范`）。
> 每行实测命令与原始输出见该轮报告；契约状态列本身需随实现更新，不得只依赖历史登记。
>
> 📏 **「已实现」≠「已全覆盖」**（#22 的教训，审查 2026-10-09 R2BD-07）：执行点类的条目
> 若只在**部分任务**接线，状态列必须写成 `⚠部分规范` 并**逐名列出已接入任务**
> （#22 曾写 `✅已规范` 而实际只接 7/42 个任务）。覆盖范围与状态列由门禁
> `test_boundary_contract.py::TestCheckTablesFiniteCoverageIsDeclared` 双向钉住 ——
> 数字来源即该用例的 AST 实测（对每个 `TaskSpec.func_path` 的函数体扫描 `check_tables_finite` 调用），
> 不另抄一份会过期的计数。

## 契约的执行点

**唯一实现**：`src/smartsuite/engine/_guard.py`

新增或修改引擎函数时，**不得**再手写清洗/校验循环；必须经 `_guard` 的下列入口：

| 函数 | 用途 |
|---|---|
| `clean_series(s, column=, report=)` | B1 单列非有限值清洗（入口） |
| `clean_frame(frame, cols, report=)` | B1 多列按行清洗（入口） |
| `check_n(n, minimum, what=, report=)` | B0 样本量下限 |
| `check_non_constant(s, what=, report=)` | B0 常量列（三级归因 + `BoundaryIssue`） |
| `degenerate_column_code(s)` | 退化列**单一**归因：`E_DATA_EMPTY_COLUMN` / `E_DATA_INSUFFICIENT_N` / `E_DATA_CONSTANT_COLUMN` / `None`（全库"常量列"判据的唯一实现） |
| `degenerate_column_reason(s, what=)` | 退化列的**原因短语**唯一文案源（各模块只拼自己的后果语） |
| `first_degenerate_reason(frame, cols, label=)` | 逐列检查、首个退化列即拒绝的调用方入口（回归 / VIF / 相关性） |
| `check_magnitude(s, what=, report=)` | B0 量级上界（`E_SCALE_EXTREME_MAGNITUDE`：平方和溢出会让判决静默翻转） |
| `check_finite_param(value, name, report=)` | B0 参数非有限 |
| `check_tables_finite(tables, what=, code=, report=)` | B0 输出侧后置断言（结果表出现 inf/nan 即拒绝；判据来自 `degenerate_tables`，`non_finite_tables` 只是诊断计数）。**当前仅 7/42 个任务接入**，清单见边界清单 #22 |
| `explain_undefined_sigma(values, column=, what=)` | σ 不可估计时的**正确归因**（常量 → 样本量 → 非有限值 → 兜底；其中退化三级与 `degenerate_column_code` **共用同一实现**，故顺序不可与本文件 #23 行互相颠倒） |
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
(b) 任何模块**不得**对 `+Inf` 输入报出"常量列"字样（错误归因回归防线）；
(c) `TestDegenerateColumnAttributionSSOT` —— 源码里不得再出现手写的"常量/无变异"判据
（`nunique(...) <= 1` 一族），且报「常量列」的模块必须能区分三级归因（带**逐行**具名白名单与理由）；
(d) `TestUnequalSubgroupIsDisclosed` —— 子组大小不一致时的最小 n 口径必须披露（契约 #4）。

## 维护规则

- 本契约变更必须同步：`logs/reports/verify-round3/R3-复核清单.md`（证据）、
  `docs/governance/improvement-plan.md`（计划状态）、`skills/smartsuite-dev.md`（陷阱清单）。
- 新增边界处置 → 必须在「边界清单」表登记 `code` 与级别。
- 本文件是**唯一**边界级别定义处；其他文档只链接引用，不复制表格。
