# Falsy 陷阱检查清单

> 新增/修改 engine/ 函数前必须逐项确认

## 核心规则

Python 中 `if x:` 对以下值判假：`0`, `0.0`, `""`, `[]`, `{}`, `None`, `False`

**统计代码中 0 是有效值**（效应量=0、均值=0、计数=0），不能用 `if x:` 检查。

## 检查项

### 数值变量（必须用 `is not None`）

```python
# ❌ 错误
if effect_size:
    report(effect_size)

# ✅ 正确
if effect_size is not None:
    report(effect_size)
```

### 可选参数（必须用 `is not None`）

```python
# ❌ 错误
if alpha:
    threshold = alpha

# ✅ 正确
if alpha is not None:
    threshold = alpha
```

### 布尔变量（可以直接 `if x:`）

```python
# ✅ 安全（布尔值）
if is_significant:
    ...
if use_s_chart:
    ...
```

### 集合/列表（可以直接 `if x:`）

```python
# ✅ 安全（空列表 = 无数据）
if violations:
    report_violations(violations)
if cols:
    process(cols)
```

## 高风险变量名（遇到必须用 `is not None`）

| 变量名模式 | 原因 |
|-----------|------|
| `*_shape`, `*_scale` | Weibull 参数，>0 但可能 None |
| `cp`, `cpk`, `ppm` | 过程能力指数，0 是有效值 |
| `threshold`, `tolerance` | 阈值，0 是有效值 |
| `effect_size`, `statistic` | 效应量，0 表示无效应 |
| `sigma`, `mean`, `std`, `var` | 统计量，0 是有效值 |
| `offset`, `shift` | 偏移量，0 是有效值 |

## 审计命令

```bash
python scripts/falsy_audit.py
```

验收标准：零 HIGH 风险警告。

## 历史教训

Phase 0 审计发现 14 项历史 falsy 修复，根因均为 `if x:` 对数值 0 误判。
典型案例：`if weibull_shape:` 在 β=0（理论上不可能但拟合失败时可能）时跳过报告。
