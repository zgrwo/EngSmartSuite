# `_guard` 迁移清单（边界处理「一处声明、一处执行」）

> **本文件是迁移进度的单一事实源。** 由
> `tests/guards/test_boundary_disclosure.py` 与
> `tests/engine/test_capability_guard_migration.py` 读取并断言。
>
> **为什么需要它**：本轮（第三十五轮）迁移 `capability.py` 后，
> `test_boundary_disclosure.py` 里那条"扫描器自证"断言**立刻失败** ——
> 因为它把 `capability.py` 硬写成"必须含清洗调用点"的样本。
> 每迁一个模块就要改一次测试，是**清单缺失**的症状。
>
> 契约：[boundary-contract.md](boundary-contract.md) ·
> 计划：[improvement-plan.md](improvement-plan.md) 硬指标表

## 背景

引擎里曾有两套并存的清洗实现：

| 实现 | 位置 | 是否产出**披露** | 是否产出**错误码** |
|:---|:---|:---|:---|
| `drop_non_finite` / `drop_non_finite_rows` | `engine/_utils.py` | 否（调用方需自己接 `non_finite_note`） | 否 |
| `clean_series` / `clean_frame` | `engine/_guard.py` | 是（`BoundaryReport`） | 是（`BoundaryIssue.code`） |

逐点核对过：**23 处调用点在迁移前都正确披露了**（AST 作用域判定，零缺口）——
所以这不是缺陷修复，而是**设计收口**：把"记得披露"变成"结构上必然披露"，
并顺带获得机器可读的错误码（手抄形态下只有中文文案，上游只能做子串匹配）。

## 迁移进度

| 模块 | 状态 | 旧调用点数 | 说明 |
|:---|:---|---:|:---|
| `capability.py` | ✅ **已迁移**（第三十五轮） | 1 | 用 `clean_series` + `BoundaryReport`；并在 `metadata["boundary_codes"]` 暴露错误码 |
| `spc_charts/xbar_r.py` | ✅ 已接入（更早） | 0 | `_guard` 的最早接入点，作为范式 |
| `root_cause/hypothesis.py` | ✅ **已迁移**（第三十八轮） | 15 | 5 个函数 / 15 处；**每个清洗点自带一个 report**（不跨分支共用，原因见该文件注释） |
| `exploratory.py` | ✅ **已迁移**（第三十七轮） | 3 | `median_ci` / `bootstrap_ci` 用 `clean_series`，`box_chart` 用 `clean_frame` |
| `reliability.py` | ✅ **已迁移**（第三十七轮） | 2 | `gage_rr` 用 `clean_frame`，`tolerance_interval` 用 `clean_series`；`survival_analysis` 的独立披露通路已于**第 41 轮**收口（见下） |
| `root_cause/modeling.py` | ✅ **已迁移**（第三十六轮） | 1 | `clean_frame` + `BoundaryReport`；新增码 `E_DECISION_TREE_OVERFIT_WARNING` |
| `root_cause/distribution.py` | ✅ **已迁移**（第三十六轮） | 1 | `clean_series` + `BoundaryReport` |
| `detection/trend.py` | ✅ **已迁移**（2026-10-09 审查 P1-2） | 0（见下注） | `trend_forecast` 用 `clean_series` + `BoundaryReport`；成功/失败两条路径均披露 |

**已迁移：8 个模块。**

> ⚠️ **本表的「0 个调用点」不等于全覆盖（2026-10-09 审查 P2-1 的要点）**
>
> 本表统计的是「**曾用 `_utils.drop_non_finite` 系旧清洗函数的模块**」的迁移进度。
> 那批模块确实已 100% 收口（旧函数已从 `_utils.py` 删除）。
>
> 但 `detection/trend.py` 属**另一类**：它自己写 `req.data[col].dropna()` ——
> **从未用过旧清洗函数**，故一直不在本表视野内。2026-10-09 审查实测发现，
> 同类「自己 `dropna()` / `np.isfinite` 掩码」的引擎模块还有 **28 个**，
> 其中 4 个任务（`anomaly_detect` / `correlation` / `doe_analysis` / `change_point`）
> 对 ±Inf 输入**静默不披露**（`status=ok` 且 `messages` 为空）。
>
> 故请这样读本表：**「0 调用点」是「旧清洗函数已消灭」的 0，
> 不是「B1 披露已全覆盖」的 0。** 未迁移清单见审查报告 P2-1；
> `detection/trend.py` 是这批里的第一个（2026-10-09 修）。

### 收口完成（第三十八轮）

全包内 `drop_non_finite` / `drop_non_finite_rows` 调用点实测 **0**；三个旧函数（含 `non_finite_note`）已从 `_utils.py` 删除；`tests/engine/test_utils.py` 里针对它们的 4 个用例已移除（等价行为由 `clean_series` / `clean_frame` 的用例覆盖）。判据（调用点数降到 0）已达成 —— 本清单由「迁移进度表」转为「**已完成的收口记录**」。

### 原「已知未纳入」的一处已收口（第 41 轮）

`reliability.py` 的 **`survival_analysis`** 原有一套独立披露通路
（手写 `list[str]` + 3 处 `append`），**不是**非有限值清洗，故当时不计入调用点数。
第 41 轮已按同一范式收口，并**顺带修掉一个真实缺陷**：

- 入口原先**只做 `dropna()`、没有非有限值清洗** → `±Inf` 使 Weibull MLE 失败、
  `weibull_shape`/`weibull_scale` 静默变 `None` 而 `messages` 为空；
  且 `+Inf` 在 KM 排序里落到最右端被当作「活得最久」，实测把中位数由 77.06 抬到 86.38
- 现走 `clean_frame(report=...)`，披露 + 错误码一并产出
- 三条既有警告也改为带码：
  `E_SURVIVAL_WEIBULL_MLE_NOT_CONVERGED`（B2）、
  `E_SURVIVAL_TOO_FEW_EVENTS` / `E_SURVIVAL_HIGH_CENSORING`（B3）
- `metadata["boundary_codes"]` 已暴露
- 复现测试：`tests/engine/test_survival_nonfinite.py`（16 项）

## 判据（可测量，故"完成"可判定）

本项**完成**的判据是唯一的、可自动核对的：

```bash
pytest tests/guards/test_boundary_disclosure.py -q
```

其中 `TestLegacyCleanersAreStillDuplicated::test_migration_cost_is_measured_not_guessed`
断言"旧调用点数 ≥ 15"。当该数字降到 **0**（即 `_utils` 的清洗函数不再被任何模块调用）时，
应把该断言改为 `== 0`、删除 `_utils` 的两个函数，并把本表所有行标为 ✅。

> ⚠️ **不要**在迁移到一半时删除 `_utils` 的函数 —— 那会让未迁移模块报 `ImportError`。
> 顺序必须是：先全部迁完，再删旧实现。
