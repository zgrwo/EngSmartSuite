# 哨兵契约 L1-L5 与 NaN/Inf 守卫

> **来源**：VibeCodingTemplate 的 excel-dna-project 技能（L1-L5 表）与 guard-checklist 文档，
> 经多个子项目（「初始实现防御不足 5×15轮」）验证的防御编程核心契约。
> 本文件是语言无关的契约定义；本仓为纯 Python 项目，落地映射见下方 Python 列。

## 为什么需要

初始实现只考虑正常路径、未系统处理退化输入，是每个数值/数据处理项目最昂贵的高频返工源
（本仓历史：边界模糊缺陷反复出现在 4 层测试防线的③层之前）。哨兵契约把
"无效输入 → 显式哨兵值（不抛异常、不静默传播、不依赖未定义行为）"固化为可执行规范。

## L1-L5 哨兵契约

| 层级 | 职责 | ✅ DO | ❌ DON'T | 违反后果 |
| :--- | :--- | :--- | :--- | :--- |
| **L1 守卫** | 类型转换前 | 显式检查 `NaN`/`Inf`/`None`（`math.isnan` / `np.isfinite` / `is None`） | 依赖运行时未定义行为（如 `int(nan)`、`float(None)`） | 未定义行为 / 静默损坏 |
| **L2 哨兵** | 不可转换值 | 返回类型零值哨兵：数值→`NaN`、`int`→0、`bool`→False、字符串→`""` | 抛异常或返回非零值 | 调用方误判 |
| **L3 外部信号** | `None`/空集合/缺省列 | 返回哨兵（语义：无有效值，跳过该元素） | 抛异常或静默赋默认值 | 外部输入处理异常 |
| **L4 已知取舍** | 哨兵与真实值不可区分（0 既可能是真值也可能是"无效"） | 文档说明该取舍（见 falsy-pitfalls.md）；调用方前置类型判断 | 依赖「0 表示错误」的隐含语义 | 数据误判 |
| **L5 最终边界** | 未知类型的转换失败 | 已知类型走 L2 哨兵；**未知类型必须显式失败**（抛异常或返回错误码，由入口层兜底） | `return None` 静默替代 | 脏数据传播 |

### 核心决策：哨兵 vs 异常

- **热路径 / 数值计算**：无效输入 → **返回哨兵值**（`NaN`），避免 try-catch 开销
- **入口边界（Web API / CLI / 外部转换）**：已知类型走哨兵；**未知类型必须显式失败**（L5），
  由入口包装层转错误信号（本仓：engine 返回 `AnalysisResult(status="error", messages=[中文错误])`，
  由 orchestrator 兜底，见 skills/smartsuite-dev.md 陷阱 5）
- **业务规则违规**（非退化输入）：应抛异常或返回错误码，不应用哨兵掩盖

## NaN/Inf 守卫清单

> 新增或修改的引擎函数必须逐项确认；未通过任何一项 = 不允许合入。复制到 PR 描述逐项勾选。

### 输入守卫（静默传播阻断）

- [ ] **NaN 输入** → 返回 `NaN`，不继续计算（**集合内 NaN/Inf 元素 → 跳过该元素**（L3 语义），
  仅全部元素无效才返回 NaN：`mean([1, nan, 3]) == 2`）
- [ ] **+Inf / -Inf 输入** → 返回 `NaN`（集合内元素同上，跳过）
- [ ] **None / 空字符串** → 返回 `""` 或 `NaN`（按类型）
- [ ] **空数组/集合** → 返回 `NaN` 或空结果，不抛异常

### 计算守卫（防御完整性）

- [ ] **除零** → 返回 `NaN`（L2 哨兵语义：返回类型零值哨兵）
- [ ] **负数开方 / 非正对数** → 返回 `NaN`
- [ ] **溢出**（结果 `isinf`）→ 替换为 `NaN`（L2 哨兵语义）
- [ ] **空集合统计** → 返回 `NaN`（有意的例外：Sum→0、Product→1，对齐业务语义并注释）
- [ ] **单元素方差**（n=1）→ 返回 `NaN` 或 0（视 ddof，显式处理）

### 输出守卫（结果验证）

- [ ] **结果 Inf** → 替换为 `NaN`
- [ ] **中间 NaN 传播** → 最终结果应为 `NaN`（不吞没）
- [ ] **数组/矩阵结果** → 不含 `Inf`（可用 `np.isfinite` 断言确认）

### 异常过滤（异常过滤器）

- [ ] **无裸 `except:`**（红线规则：`except Exception:` 必须记录日志）
- [ ] **排除不可恢复异常**：`except (MemoryError, KeyboardInterrupt, SystemExit)` 不捕获
- [ ] **不吞没异常**：catch 块必须有日志 / 重抛 / 返回错误值

## Python 落地映射

| 场景 | 哨兵值 | 示例 |
|------|--------|------|
| 数值转换失败 | `float("nan")` / `math.nan` | `safe_float`（engine/_utils.py） |
| None/缺失 | `""` 或 `None`（按列类型） | data_io 预处理跳过空值 |
| 未知类型（L5） | `raise`（由入口转错误） | `AnalysisResult(status="error")` |
| falsy 判断 | 用 `is not None` 而非 `if x:` | 见 falsy-pitfalls.md |

## 快速自查命令

```bash
# 裸异常捕获检查（必须返回空，输出为空即通过）
python scripts/verify_docs.py

# Falsy 模式审计（0/空/False 误判风险）
python scripts/falsy_audit.py

# 手册声称值实跑验证（CLAIM 标记 → verify_manual_claims）
python scripts/verify_manual_claims.py

# 边界模糊测试防线（空数据/单行/全NaN/常量列/共线/n>5000）
pytest tests/test_engine/test_edge_cases.py -q
```

## 维护规则

- 本契约变更必须同步 `skills/smartsuite-dev.md` 的陷阱清单与修复模板
- 新踩哨兵/守卫坑 → 追加到 `AGENTS.md`「历史经验」并登记 `tooling-pitfalls.md`（如属工具链问题）
