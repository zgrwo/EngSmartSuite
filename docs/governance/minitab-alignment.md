# 与 Minitab 的口径对照（含实测证据与如实缺口）

> **本文档的用途**：把"本引擎的算法口径与 Minitab 是否一致"从**传闻**变成**可核对的表**。
>
> **为什么需要它**：改善计划里曾把这一项的现状写成「能力/可靠性/GRR **有明显缺口**」——
> 那是**计划初期的印象**。第三十四轮逐项实测后，实际情形是：
> **对齐面很宽**，缺口集中在少数明确的几处，且都能说清"缺什么、为什么不补"。
>
> 本文档的每一条都标了**验证方式**与**位置**，读者可自行复核。
> 由 `tests/engine/test_minitab_alignment.py` 锁定 —— 它同时断言**已对齐项不得退化**
> 与**已声明的缺口确实仍缺**（若哪天补上了，测试会失败并提醒更新本表）。

## 一、验证方式的分级（先说清可信度）

| 级别 | 含义 | 本表用到的 |
|:---|:---|:---|
| **A** | 与**公开的 Minitab 文档/常数表**逐值一致 | `XBR_CONSTANTS` 对 Minitab 标准控制图常数表 |
| **B** | 与**教科书闭式公式**逐项对账（解析真值） | `Pp = 12/(6σ)`、`Cp = 12/(6σ_within)`、`%P/T = 6σ_GRR/公差` |
| **C** | 与**AGAI/AIAG 手册**的判定阈值一致 | Gage R&R 的 10/30 判定分档、`ndc ≥ 5` 判据 |
| **D** | **仅口径同名**，未做数值对账（明确标注） | 见下表"未对账"列 |

> ⚠️ **没有做的一件事**：本机**未安装 Minitab**，故**不存在**"与 Minitab 跑同一数据比数值"
> 的验证。上表 A/B/C 三种都是**与公开规范/公式**对账，不是与 Minitab 软件对账。
> 这与本项目对 R 的处理一致（无 R 环境 → 退化为独立第二实现并如实标注）。

### 口径补充：描述性统计的偏度/峰度 = Minitab 的 **Adjusted** 口径

适用任务：`distribution_summary`（`descriptive_stats` 表）与 `normality_check`（`normality_results` 表）。
之前本表未列此条，而两处口径**确实不同**，故补上（审查 2026-10-09 P2-7）。

| 口径 | 本引擎 | pandas | Excel | scipy（**默认**） | Minitab |
|:---|:---|:---|:---|:---|:---|
| 偏度 | `bias=False`（G1） | `Series.skew()` 同 | `SKEW` 同 | `skew(bias=True)` 不同 | **Adjusted** 同 |
| 峰度（超额，正态基准 = 0） | `bias=False`（G2） | `Series.kurtosis()` 同 | `KURT` 同 | `kurtosis(bias=True)` 不同 | **Adjusted** 同 |

**两种估计量的差随 n 减小而放大**（同一列取前 n 行、两种口径对比实测）：

| n | 偏度 `bias=False` | 偏度 `bias=True` | 相对差 | 峰度 `bias=False` | 峰度 `bias=True` | 相对差 |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 0.834728 | 0.809475 | 3.12% | 0.993085 | 0.778871 | **27.50%** |
| 137 | 0.809928 | 0.801033 | 1.11% | 1.029730 | 0.949053 | 8.50% |
| 1000 | 0.897880 | 0.896532 | 0.15% | 1.880867 | 1.865482 | 0.82% |

> **结论**：本引擎与 **Minitab（Adjusted）/ pandas / Excel** 一致，与 **scipy 默认**不一致。
> 报告或对账时**必须写明用的是哪一个** —— 小样本下峰度相对差可达两位数百分比，
> 足以让"与 scipy 对不上"被误判成缺陷。
> 口径来源：`root_cause/distribution.py` 的 `distribution_summary()`（`descriptive_stats` 的
> `偏度`/`峰度` 两行取 `Series.skew()` / `Series.kurtosis()`）与 `normality_check()`（同名变量）。
> 钉住用例：`tests/engine/test_task_truth_assertions.py` 的
> `test_normal_check_rejects_grossly_non_normal_data` —— 38 个 0 + 2 个 100 的数据断言
> 偏度 `= 4.292`（实测 `bias=False` = 4.292145，而 `bias=True` = 4.129483，差 3.9%），
> 即该用例锁的正是**偏差校正口径**（改口径会立刻红）。

## 二、过程能力（`process_capability`）

Minitab 的「能力分析（正态）」输出与引擎对照：

| Minitab 输出 | 引擎 | 位置 | 验证 | 说明 |
|:---|:---|:---|:---|:---|
| `Cp` | ✅ | `metadata["cp"]` | **B** | `= (USL−LSL)/(6σ_within)`，见下"σ 口径" |
| `Cpk` | ✅ | `metadata["cpk"]` | **B** | 完全居中时等于 `Cp`（闭式，已断言） |
| `Pp` | ✅ | `metadata["pp"]` | **B** | `= (USL−LSL)/(6σ_overall)`，`σ_overall` 用 `ddof=1` |
| `Ppk` | ✅ | `metadata["ppk"]` | **B** | 同上 |
| `Cpm` | ✅ | `metadata["cpm"]` | D | 需给 `target`；未与 Minitab 数值对账 |
| `Cp`/`Cpk`/`Pp`/`Ppk` 的 95% CI | ✅ | `cp_ci` 等 | D | `Cp` 用 `df_eff ≈ 0.606(n−1)`（移动极差口径）；未与 Minitab 对账 |
| 观测的 `PPM` | ✅ | `metadata["dpmo"]` | D | 名称是 `dpmo`（历史命名），实为 PPM |
| `σ` 水平 | ✅ | `metadata["sigma_level"]` | D | 按 `3·Cpk` 口径 |
| 正态性检验（AD 统计量 + p） | ❌ | — | — | **缺口**（见第四节） |
| Box-Cox / Johnson 变换 | 🔶 | `boxcox_lambda` | — | **仅给 λ**，未做变换后的能力指数（缺口） |

### σ 口径（本节最容易被误读的一处）

引擎与 Minitab 都有"组内 σ"与"整体 σ"两套口径，但**无子组时的组内 σ 估计方式**必须说清：

- 引擎：`subgroup_col` / `subgroup_size` 都未给时 → **移动极差法** `σ̂ = mean(|diff|)/1.128`，
  并在 `metadata["within_sigma_method"] = "moving_range"` 中标明；同时给出**用户可见提示**
  （"隐含数据行序 = 采样时间顺序"假设，排序或筛选后该估计会失真）。
- Minitab：无子组时用 **MR-bar/d2**（同一个量），故此口径**一致**。

实测（`y = [50,52,48,51,49,53,47,50,51,49]`，USL/LSL = 56/44）：

```
σ_overall = 1.8257418584  (ddof=1)     → Pp = 1.0954451150   手算 12/(6σ) = 1.0954451150 ✓
σ_within  = 2.6595744681  (移动极差)   → Cp = 0.7520000000   手算 12/(6σ) = 0.7520000000 ✓
```

> ⚠️ **`Cp` 与 `Pp` 的大小关系不是不变量**。本数据上 `Cp < Pp`（因相邻行差分放大了逐点抖动），
> 而"组内 σ 通常小于整体 σ"的直觉在别的数据上可能反过来。
> 故不要用 `Cp > Pp` 当合理性检查 —— 引擎的两者都各自与自己的 σ 口径对账（上表 B 级）。

## 三、Gage R&R（`gage_rr`）

Minitab「Crossed Gage R&R Study」的输出清单（来源：[Minitab 官方文档](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/interpret-the-results/all-statistics-and-graphs/)）与引擎对照：

| Minitab 输出 | 引擎 | 位置 | 验证 |
|:---|:---|:---|:---|
| ANOVA 表：`DF` / `SS` / `MS` / `F` / `P` | ✅ | `anova_df` / `anova_f_tests` / `gage_rr_anova` 表 | B（教科书公式，`tests/golden`） |
| 方差分量 `VarComp` | ✅ | `anova_variance_components` | B |
| `%Contribution` | ✅ | `gage_rr_results` 表"贡献率(%)"列 | B（`VarComp/总方差×100`） |
| `StdDev` / `Study Var` | ✅ | 同表"标准差"/"5.2σ变异"列 | B |
| `%Study Var (%SV)` | ✅ | 同表"%SV"列 + `grr_sv` | B |
| `%Tolerance` | ✅ | `pt_ratio` / `pt_percent` | **B** —— 第三十轮补实现，公式经 Minitab 文档核实 |
| 各分量的 95% CI | ✅ | `anova_ci95` | D（χ² 口径，未与 Minitab 对账） |
| `Number of distinct categories` | ✅ | `ndc` + `ndc` 表 | B（`⌊1.41·PV/GRR⌋`） |
| 判定分档 | ✅ | `judge` | **C**（`<10` 优秀 / `<30` 临界 / 否则不合格；AIAG 口径） |
| `%Process (SV/Proc)` | ❌ | — | **缺口**（需"历史 σ"输入，未实现） |
| 误分类概率（联合/条件） | ❌ | — | **缺口**（见第四节） |
| VDA 5 不确定度分解 | ❌ | — | **缺口**（不在本项目范围） |

实测（10 部件 × 3 操作员 × 3 重复，`tolerance = 5.0`）：`pt_ratio` 与手算 `6·grr/5` 逐位一致；
`ndc = 12`（≥ 5，判"临界"因 `%SV = 11.1` 落在 10–30 档）。

### ⚠️ 引擎同时给出**两套口径**，它们**不可混算**

| 口径 | 字段 | 内部恒等式（实测精确成立） |
|:---|:---|:---|
| 均值-极差法 | `ev` / `av` / `grr` / `pv` / `tv` | `grr² = ev² + av²`；`tv² = grr² + pv²` |
| ANOVA 法 | `anova_variance_components`（`part`/`operator`/`interaction`/`repeatability`） | 分量非负、可加 |

**两者的「部件间」分量不是同一个数**：极差法不含交互项（把它并入 `pv`），
ANOVA 法把交互项**单列**。实测同一数据上 `tv² = 3.0375`，而 ANOVA 分量之和 `= 3.1852`
（差 `0.1477`，恰为交互项与 `part` 口径差之和）。

> 我第一版对照表把两者混着求和，报出一个"缺口" —— **实测查明那不是缺陷**：
> Minitab 同样区分「X-bar and R 法」与「ANOVA 法」，两种方法的方差分量本来就不相等。
> 故查阅时**必须按同一口径内部对账**，不要跨口径相加
> （`tests/engine/test_minitab_alignment.py` 对此有专门断言）。

## 四、如实列出的缺口（含"为什么不补"）

| 缺口 | 影响 | 为什么不补 |
|:---|:---|:---|
| **Gage R&R 误分类概率** | 无法回答"有多大比例的好件被误判为坏件" | 需要正态假设下的积分 + 与规格限的联合计算；属独立方法，非"对齐既有输出" |
| **能力分析的正态性检验（AD）** | 用户无法在同一个报告里确认"用正态能力指数是合适的" | 引擎**已有** `normality_check` 任务，用户可自行先跑；缺的是"同一报告内提示"，属 UI 整合 |
| **`%Process (SV/Proc)`** | 有历史 σ 的用户拿不到该口径 | 需新增输入参数与口径分支；价值低于前三项 |
| **Box-Cox 变换后的能力指数** | 只给了 λ，没给变换后的 `Cp/Cpk` | 变换后指数需回代规格限，实现与验证成本高 |
| **VDA 5** | 汽车行业部分客户要求 | 超出"工艺数据分析工具箱"的定位 |

### 关于"未做数值对账"的四项

`Cpm`、`sigma_level`、`dpmo`、以及各 CI 的**具体数值**只有 D 级验证（口径已知、未与 Minitab 对账）。
原因：**本机无 Minitab**。若将来能拿到 Minitab 输出，应优先补这四项 —— 它们是"口径对但数值可能差"
的高风险区（例如 `sigma_level` 有的工具用 `3·Cpk`、有的用含 1.5σ 漂移的口径）。

## 五、SPC 控制图常数（`spc_xbar` / `spc_attribute`）

`engine/_constants.py` 的 `XBR_CONSTANTS` 与 **Minitab 标准控制图常数表**逐值一致（**A 级**）：

| n | A2 | d2 | D4 | D3 |
|---:|---:|---:|---:|---:|
| 2 | 1.880 | 1.128 | 3.267 | — |
| 3 | 1.023 | 1.693 | 2.574 | — |
| 5 | 0.577 | 2.326 | 2.114 | — |

实测 `XBR_CONSTANTS[2] = (1.88, 0, 3.267)`、`[3] = (1.023, 0, 2.574)`、`[5] = (0.577, 0, 2.114)`
（元组为 `(A2, D3, D4)`）。第三位 `0` 即 `D3`：Minitab 表中 `n < 7` 时 `D3 = 0`（R 图下界为 0），一致。

> 补充：`c4(n)` 在大子组（`n ≥ 380`）下 `math.gamma` 会溢出，引擎改用**对数域**计算
> （见 `tests/guards/test_boundary_contract.py` 的 `TestC4NumericStability`）——
> 这是 Minitab 不必面对的实现细节（它用查表 + 插值），属**实现路径不同、数值一致**。

## 六、如何自行复核本表

```bash
# 钉住本表全部断言（已对齐项 + 已声明缺口）
pytest tests/engine/test_minitab_alignment.py -v

# 教科书公式对账（B 级验证的出处）
pytest tests/golden/ -v

# 独立第二实现对账（statsmodels / scipy）
pytest tests/crossval/ -v
```

## 七、本表维护约定

1. **补上一个缺口后**，把该行从第四节移到对应方法表，并**更新** `test_minitab_alignment.py`
   （它断言"已声明缺口仍缺"，补上会让它失败 —— 这是有意的提醒）。
2. **新增 D 级条目时**，必须写明"与什么口径对齐、未与什么对账"。
3. **不得**把"口径同名"写成"已对齐" —— 本表的价值全在区分这两者。
