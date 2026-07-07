# SmartExcel-Suite: data_io.py 数据处理管道审查报告

**审查日期**: 2026-07-08
**审查范围**: `smartsuite/services/data_io.py` (393 行)
**审查重点**: NaN 与空数据处理、One-Hot 编码边界情况、validate_data 警告消息与实际行为一致性

---

## 发现摘要

共发现 **9 个问题**，按严重程度分级：

| 级别 | 数量 | 说明 |
|------|------|------|
| P1 (高) | 2 | 可能导致分析静默失败或产生错误结果 |
| P2 (中) | 5 | 警告消息不准确、行为不一致或功能缺失 |
| P3 (低) | 2 | 设计瑕疵或健壮性不足 |

---

## P1: 高优先级问题

### P1-1: 全 NaN 数值列的警告消息与实际填充行为不一致

**位置**: `validate_data` L46 vs `preprocess_data` L132-L138

**问题描述**:
`validate_data` 检测到缺失值时向用户发出的警告消息为:
> "分析中将自动填充（数值型用中位数，类别型标记为'缺失'）"

但对于全部为 NaN 的数值列，`preprocess_data` 的实际行为是填充 **0**，而非中位数:

```python
# preprocess_data L130-L137
valid_vals = df[col].dropna()
if len(valid_vals) == 0:
    logger.warning("列「%s」全部为非数值，填充为 0", col)
    df[col] = df[col].fillna(0)  # 填充 0，不是中位数!
    imputation_log[col] = n_missing
```

通过验证脚本实测确认:
- 输入: `df = pd.DataFrame({"x": [nan, nan, nan], "y": [1.0, 2.0, 3.0]})`
- `validate_data` 输出: `"检测到 3 个缺失值，分析中将自动填充（数值型用中位数，类别型标记为'缺失'）"`
- `preprocess_data` 实际输出: `x` 列被填充为 `[0.0, 0.0, 0.0]`，且产生 `unknown_cat_warnings`

**影响**: 用户收到"用中位数填充"的虚假承诺，实际填充值却是 0。对于工艺参数列（如温度、压力），0 与中位数的差异可能极大，直接导致分析结果偏差。

**根因**: `validate_data` 和 `preprocess_data` 之间缺乏共享的填充策略描述。`validate_data` 的警告文本硬编码了理想路径的描述，未反映降级策略（退回到 0 填充）。

**为什么现有测试没捕获**: `test_imputation_fills_missing` 仅测试了部分 NaN（`[1.0, 2.0, None, 4.0, 5.0]`），未测试全部为 NaN 的极端情况。`test_fuzz.py` 虽然有针对引擎层的 NaN 测试，但未覆盖 `preprocess_data` 的全 NaN 输入测试。

---

### P1-2: 高基数列（>50 唯一值）仅发出 logger.warning，无用户可见警告

**位置**: `preprocess_data` L90-L94

**问题描述**:
```python
if n_unique > 50:
    logger.warning(
        "列「%s」有 %d 个唯一值，One-Hot 编码将产生 %d 个虚拟列，"
        "建议先分组归并或降维处理", col, n_unique, n_unique - 1
    )
```

这是一个 `logger.warning()` 调用，仅写入日志文件，不会出现在:
- CLI 输出的警告列表
- Web UI 的 `data_warnings` 列表中
- `unknown_cat_warnings` 返回结构中

通过验证脚本实测确认: 100 个唯一值的类别列产生 99 个虚拟列，仅有一条日志级别的警告，CLI 和 Web UI 中均无任何提示。

**影响**: 用户上传包含高基数列（如产品 ID 有 500 个唯一值）的数据集后，系统静默生成大量虚拟列，可能导致:
- 内存激增（对 Web 服务端是 DoS 风险）
- 模型维度灾难，回归/分类模型过拟合且不可解释
- 用户完全不知情

**根因**: 高基数检查放在 `logger.warning` 而非返回的警告结构中。`preprocess_data` 返回了 `imputation_log` 和 `unknown_cat_warnings` 两个警告通道，但高基数警告未纳入其中任何一种。

**为什么现有测试没捕获**: 测试中构造的特征列最多只有 3 个类别水平（如"组A/组B/组C"），从未测试 >50 唯一值的场景。

---

## P2: 中优先级问题

### P2-1: 类别型列的 NaN 填充不在 imputation_log 中记录

**位置**: `preprocess_data` L88

**问题描述**:
```python
col_str = df[col].fillna("(缺失)").astype(str)
```

类别列的 NaN 填充为 `"(缺失)"` 字符串，是一种插补行为，但不记录到 `imputation_log`。只有数值列的 NaN 填充（中位数或 0）被记录。

通过验证脚本实测确认: 全 NaN 类别列的 `imputation_log` 返回空字典 `{}`，CLI/Web 均不显示类别列 NaN 填充的任何警告。

**影响**: `cli.py` 和 `api.py` 的警告输出仅基于 `imputation_log`，用户不知道类别列中有多少 NaN 被填充。参考类别项可能被解释为实际类别，但实际是"垃圾桶"类别。

**根因**: `imputation_log` 的填充记录仅在数值列分支（`else` 分支，L124-L143）中执行。类别列分支（L87-L123）没有对应的记录逻辑。

**为什么现有测试没捕获**: `test_imputation_fills_missing` 仅测试数值列。无类别列 NaN 处理的专门测试。

---

### P2-2: 全 NaN 类别列产生常数列（全 1），无零方差警告

**位置**: `preprocess_data` L95-L97

**问题描述**:
```python
col_str = df[col].fillna("(缺失)").astype(str)
n_unique = col_str.nunique()
_drop_first = True if n_unique > 1 else False
dummies = pd.get_dummies(col_str, prefix=col, drop_first=_drop_first)
```

当类别列全部为 NaN 时: `fillna("(缺失)")` 使所有值相同 -> `n_unique = 1` -> `_drop_first = False` -> 生成全为 1 的虚拟列。

**影响**: 在回归模型中，常数列与截距项完全共线，导致 OLS 矩阵奇异。`missing_pattern_analysis` 能检测零方差列，但 `preprocess_data` 自身不警告。

**根因**: `preprocess_data` 无零方差检测逻辑。该功能在 `missing_pattern_analysis()` 中（L192-L196），但两函数无调用关系。

**为什么现有测试没捕获**: 无"全 NaN 类别列"的预处理测试。

---

### P2-3: imputation_log 的警告消息文本不准确

**位置**: `api.py` L95-L96, `cli.py` L74-L75

**问题描述**:
```python
data_warnings.append(f"列「{col}」中 {n_coerced} 个非数值已自动转换为中位数")
```

该消息固定显示"转换为中位数"，但在以下场景中不准确:
1. 全非数值列：实际填充 0，不是中位数（对应 P1-1）
2. 类别列 NaN：不被记录（对应 P2-1）
3. 消息说"非数值"，但计数实际是 NaN 数量（来自 `pd.to_numeric(errors='coerce')`），而非"非数值"数量

**影响**: 用户可能误解数据被如何处理。

**根因**: 警告文本在调用方硬编码，与 `preprocess_data` 的实际行为分离。缺少插补策略元数据。

**为什么现有测试没捕获**: 差分测试验证数值一致性，不验证警告消息文本的准确性。

---

### P2-4: `recommend_analysis` 的缺失值检查仅看单列最大值

**位置**: `recommend_analysis` L262-L268

**问题描述**:
```python
missing_pct = df.isna().mean().max() * 100
if missing_pct > 10:
    recommendations.append({...})
```

仅检查缺失率最高的一列是否超 10%，忽视整体数据质量。例如 20 列各 8% 缺失不触发推荐，但整体数据质量问题比单列 15% 缺失更严重。

**影响**: 多列中等缺失率的数据集不被推荐做缺失模式诊断。

**根因**: 缺失检查指标过于简化，未考虑列级缺失率的分布。

**为什么现有测试没捕获**: 无 `recommend_analysis` 逻辑的单元测试。集成测试仅验证推荐列表非空。

---

### P2-5: `known_cat_map` 参数从未被实际调用路径使用，且格式约定不清晰

**位置**: `preprocess_data` L99-L115

**问题描述**:
`known_cat_map` 参数在全代码库所有调用点均传默认值 `None`（`cli.py` L72、`api.py` L57/L93、所有测试）。参数期望格式是虚拟列名列表（如 `["颜色_红", "颜色_蓝"]`），而非类别值列表，文档注释未说明。

**影响**: 该参数是死代码，违反 YAGNI 原则。若将来有人使用，易传入错误格式。该分支（79 行逻辑）从未被测试覆盖。

**根因**: 预设计功能（模型部署时的训练/推理编码对齐），当前版本无此需求。

**为什么现有测试没捕获**: 无测试覆盖 `known_cat_map != None` 的路径。

---

## P3: 低优先级问题

### P3-1: `missing_pattern_analysis` 的缺失模式分析仅取前 20 列

**位置**: `missing_pattern_analysis` L170

**问题描述**: 取 DataFrame 的前 20 列（按列顺序）而非缺失率最高的 20 列。若缺失主要发生在靠后的列（如后期采集字段），模式分析将完全忽略。代码注释显示设计者意识到此问题但选择了简单方案。

**为什么现有测试没捕获**: 测试数据列数少，不触发截断。

---

### P3-2: `validate_data` 对空字符串 target_col 的处理方式不够优雅

**位置**: `validate_data` L33-L35

**问题描述**: 当 `target_col=""` 时（VIF/信度分析等无目标列任务），`"" not in df.columns` 为 True，触发 `ValidationError`。调用方用 `except ValidationError: pass` 静默捕获。若将来移除该 pass，所有无目标列任务将在 Web 路径崩溃。

**为什么现有测试没捕获**: `test_missing_column_validation` 仅测试列不存在时的抛出，未测试 `target_col=""` 边界。

---

## 现有测试覆盖缺口分析

| 测试文件 | 覆盖函数 | 覆盖场景 | 缺失场景 |
|---------|---------|---------|---------|
| test_preprocess_idempotent | preprocess_data | 纯数值列，无 NaN | NaN 列、类别列 |
| test_imputation_fills_missing | preprocess_data | 部分 NaN 数值列 | 全 NaN 数值/类别列、高基数 |
| test_missing_pattern_analysis | missing_pattern_analysis | 小数据集 | 宽表（>20 列） |
| test_missing_column_validation | validate_data | 列缺失 | 空 target_col、全 NaN 列 |
| test_fuzz.py | 引擎层函数 | NaN/常量/小样本 | 未覆盖 preprocess/validate |
| 无 | recommend_analysis | - | 全部场景 |
| 无 | known_cat_map 路径 | - | 全部场景 |
| 无 | 类别列 NaN 填充 | - | 全部场景 |

---

## 验证脚本输出（实测确认）

```
=== TEST 1: All-NaN numeric column ===
validate_data: "检测到 3 个缺失值，分析中将自动填充（数值型用中位数，类别型标记为'缺失'）"
actual fill: x = [0.0, 0.0, 0.0]
unknown_cat_warnings: [('x', {'<全列非数值，已强制填充为0>'}, 3)]
=> MISMATCH: warning says 中位数但实际填充 0

=== TEST 2: All-NaN categorical column ===
imputation_log: {}
=> categorical NaN imputation NOT recorded

=== TEST 3: High-cardinality (100 unique values) ===
encoded cols: 99 dummy columns
=> No user-visible warning, only logger.warning

=== TEST 4: validate_data with empty target_col ===
Exception: ValidationError
=> Caught by callers, validation silently skipped
```

---

## 修复建议优先级

### 立即修复（P1）

1. **P1-1**: `validate_data` 的警告消息应准确反映 `preprocess_data` 的填充策略。
   - 方案 A（推荐）: 将消息改为"分析中将自动处理缺失值"，移除具体策略描述
   - 方案 B: 在 `preprocess_data` 返回中增加填充策略元数据，由调用方动态生成准确警告
   - 同时考虑全 NaN 列填充 0 的替代方案（删除该列、全局中位数、或拒绝处理）

2. **P1-2**: 将高基数警告从 `logger.warning` 升级为用户可见警告。
   - 在 `preprocess_data` 返回的警告结构中增加高基数条目
   - 在 `api.py` 和 `cli.py` 中展示
   - 考虑 >200 唯一值时硬拒绝

### 后续修复（P2）

3. **P2-1**: 类别列 NaN 填充添加 `imputation_log` 记录
4. **P2-2**: 为生成的零方差虚拟列添加检测和警告
5. **P2-3**: 调用方警告文本改为数据驱动
6. **P2-4**: `recommend_analysis` 缺失检查同时考虑缺失列数和缺失率
7. **P2-5**: 移除 `known_cat_map` 参数（遵循 YAGNI）或添加完整测试

### 锦上添花（P3）

8. **P3-1**: `missing_pattern_analysis` 按缺失率排序选取列
9. **P3-2**: `validate_data` 优雅处理空 target_col

---

## 建议新增的测试用例

1. `test_preprocess_all_nan_numeric` -- 全 NaN 数值列填充 0 并产生 unknown_cat_warning
2. `test_preprocess_all_nan_categorical` -- 全 NaN 类别列产生常数列警告
3. `test_preprocess_high_cardinality` -- 高基数类别列产生用户可见警告
4. `test_validate_empty_target` -- 空 target_col 被合理处理
5. `test_preprocess_categorical_nan_logged` -- 类别列 NaN 记录到 imputation_log
6. `test_validate_warning_vs_actual_fill` -- validate_data 消息与 preprocess_data 行为一致
7. `test_recommend_multi_column_missing` -- 多列中等缺失率触发推荐
8. `test_preprocess_known_cat_map` -- known_cat_map 参数功能测试（如需保留）
