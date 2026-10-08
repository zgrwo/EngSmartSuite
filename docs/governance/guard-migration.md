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
| `reliability.py` | ✅ **已迁移**（第三十七轮） | 2 | `gage_rr` 用 `clean_frame`，`tolerance_interval` 用 `clean_series`；**`survival_analysis` 的 `warn_msgs` 通路未纳入本次迁移**（见下） |
| `root_cause/modeling.py` | ✅ **已迁移**（第三十六轮） | 1 | `clean_frame` + `BoundaryReport`；新增码 `E_DECISION_TREE_OVERFIT_WARNING` |
| `root_cause/distribution.py` | ✅ **已迁移**（第三十六轮） | 1 | `clean_series` + `BoundaryReport` |

**已迁移：7 个模块。待迁移：0 个模块 / 0 个调用点 —— 旧清洗函数已删除。**

### 收口完成（第三十八轮）

全包内 `drop_non_finite` / `drop_non_finite_rows` 调用点实测 **0**；三个旧函数（含 `non_finite_note`）已从 `_utils.py` 删除；`tests/engine/test_utils.py` 里针对它们的 4 个用例已移除（等价行为由 `clean_series` / `clean_frame` 的用例覆盖）。判据（调用点数降到 0）已达成 —— 本清单由「迁移进度表」转为「**已完成的收口记录**」。

### 已知未纳入迁移的一处

`reliability.py` 的 **`survival_analysis`** 有另一套披露通路（`warn_msgs: list[str]`，3 处 `append`），**不是**非有限值清洗，故不计入本清单的调用点数。它与 `capability.py` 迁移前的形态同构，可在后续轮次按同一范式收口。

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
