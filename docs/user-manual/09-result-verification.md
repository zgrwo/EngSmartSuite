## 9. 结果验证

本节说明**本项目如何保证结果可信**、你**自己如何复核**，以及**验证覆盖到哪里为止**。

> ⚠️ **本节曾包含一份伪造的对照表**（审查 2026-09-24 发现）：旧版 §9.2 声称
> "验证日期: 2026-07-08"，但本仓库的第一个提交是 **2026-08-16** —— 该表不可能
> 由本仓库的执行产生，且用 `... (全部任务)` 省略号替代 42 个任务，无法证实也无法证伪。
> 已按"承诺即可执行，或改承诺"的原则重写：**只保留有脚本支撑、你能自己跑出来的内容**。
> 详见 [improvement-plan.md](../governance/improvement-plan.md) 的 P1-3。

### 9.1 真正的差分验证在哪（自动化，每次 CI 都跑）

结果一致性不是靠人工比对，而是靠两个**自动化**测试文件：

| 测试文件 | 验证什么 | 是否需要手工步骤 |
|---|---|---|
| `tests/services/test_cli_web_parity.py` | **全 42 个方法**：Web API 路径（`web.api.run_analysis`）vs 引擎直调路径 的 status / summary / metadata 标量数值 / 表格值逐项比对 | 否，`pytest tests/` 即覆盖 |
| `tests/integration/test_web_e2e.py` | 真实 HTTP 服务下**全 42 个方法**都能返回 `status=ok` 且 summary 非空 | **是**，需先启动服务器（见 9.3） |

**两者的分工要说清楚**：

- `test_cli_web_parity.py` 做的是**数值等价性**验证（两条调用路径给出同一结果），
  但它走的是进程内调用，不经过 HTTP。
- `test_web_e2e.py` 走**真实 HTTP**（含 CSRF、上传、序列化、会话），
  但它只断言 `status=ok` 与 summary 非空 —— **不比对各方法之间的数值**。

> 也就是说：**没有任何单一测试同时覆盖"HTTP 端到端"与"数值等价"**。
> 这是当前的覆盖边界，已登记为待办（见 [improvement-plan.md](../governance/improvement-plan.md)）。
> 在补上之前，请把两者**都**跑一遍再下"Web 与 Python 一致"的结论。

### 9.2 结果可信度的四层防线

本项目对每个方法的验证分四层，你可以在 `tests/` 下逐层查看：

| 层 | 位置 | 验证内容 | 强度说明 |
|---|---|---|---|
| ① 数值正确性 | `tests/engine/test_correctness.py` | 已知答案 + 手工公式交叉验证 | 约 6% 的测试有**独立真值**（如 `cpk == approx(4/3, abs=0.02)`、手算 KM 中位数） |
| ② 数学不变量 | `tests/engine/test_invariants.py` | p∈[0,1]、Cpk≤Cp、R²≥0、KM 单调递减 | 弱断言为主，**不依赖正确答案** |
| ③ 边界模糊 | `tests/engine/test_edge_cases.py`、`tests/engine/test_boundary_guard.py` | 空数据/单行/全 NaN/常量列/共线/±Inf/大子组 | 退化输入不崩溃 + 处置分级正确 |
| ④ 差分测试 | `tests/services/test_cli_web_parity.py` | Web vs 引擎直调数值一致 | 全 42 方法 |

> ⚠️ **关于①②的强度，需要如实告知**：
> 第①层的"独立真值"占比并不高，第②层的断言多为弱不变量。
> 这意味着"全绿"**不等于"数值都对"**。历史上正是这条缝隙漏过了三个真实缺陷
> （生存分析事件列语义反转、Cp 置信区间偏窄 28%、t 检验缺 Welch），
> 三者都不违反任何既有断言。详见
> [R3-复核清单](../../logs/reports/verify-round3/R3-复核清单.md)。
>
> **已经做的补救**（不是"计划中"）：
>
> 1. **独立第二实现**：`tests/crossval/` 用另一套实现（`statsmodels` / `scipy` /
>    手工公式）独立复算，并逐处标注来源。**本项目不含任何 R 输出数值** ——
>    本机无 R 环境（`Rscript` 不存在），故原「R 参考」声明已全部改写为
>    独立第二实现的来源标注（见 [improvement-plan.md](../governance/improvement-plan.md) 的 P1-4）。
> 2. **统计性质检验**（比"与另一个公式比接近"强，因为它检验的是**性质**而非数值）：
>    `tests/engine/test_capability_ci_coverage.py` 用蒙特卡洛检验置信区间的
>    **覆盖率**是否达标 —— 这类断言能抓住"公式实现一致但统计性质错误"的缺陷
>    （Cp 置信区间偏窄 28% 正是这样漏过去的）。
> 3. **外部裁判层**：`tests/golden/` 从教科书公式**独立推导**控制限 / 累积和 /
>    方差分量，作为"引擎之外"的裁判。

### 9.3 你如何自己复核

#### 方式 A：跑自动化差分（推荐，无需手工步骤）

```bash
# 全 42 方法：Web API 路径 vs 引擎直调路径，逐项比对数值
pytest tests/services/test_cli_web_parity.py -v
```

#### 方式 B：真实 HTTP 端到端（需先启动服务器）

```bash
# 终端 1：启动服务
python src/smartsuite/web/app.py        # → http://127.0.0.1:5050

# 终端 2：跑 E2E
pytest tests/integration/test_web_e2e.py -v
```

预期每个方法一行 `PASSED`（共 42 项）。

> ⚠️ **注意**：若服务器未启动，该模块会**整体 skip**（collection 阶段跳过），
> 输出里出现 `skipped` 而不是 `passed`。看到 skip 不代表通过，请确认服务器在运行。

#### 方式 C：手工对照单个方法

用同一条命令走两个入口，比对 `summary` 与表格数值：

```python
# Python API
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

df = pd.read_excel("tests/data/injection_process.xlsx")
r = orchestrate(AnalysisRequest(
    task="process_capability", data=df, target_col="不良率",
    params={"usl": 10, "lsl": 1},
))
print(r.summary)
print(r.tables["capability_indices"])
```

```bash
# CLI（同一分析，经 YAML 模板）
python -m smartsuite.cli run templates/example_process_capability.yaml \
       --input tests/data/injection_process.xlsx
```

两者应给出相同的 `Cp/Cpk` 数值。

#### 方式 D：复核手册里的数值是否可信

手册各章的"数值结果"段落都有脚本对账，可自行运行：

```bash
python scripts/verify_manual_claims.py
# 输出 scripts/verify_manual_claims_output.txt，逐条列出
# 手册声称值 | 引擎实测值 | 是否一致
```

**任何一条显示 `DIFF` 都说明手册与代码已漂移**，以引擎实测为准并提 issue。

---

### 9.4 验证边界（明确说明"没验证什么"）

诚实说明当前的验证**不覆盖**的部分，以免过度信任：

- **不覆盖**与外部权威软件（Minitab / JMP / R）的数值一致性 ——
  当前参考值来自独立第二实现（scipy/statsmodels）与手工公式，
  不是商用软件的输出比对。
- **不覆盖**前端的运行时行为 —— 无浏览器/jsdom 测试，
  `app.js` 的表单逻辑仅由静态正则断言守护。
- **不覆盖**多用户并发、长时间稳定性、真实工艺数据的分布假设检验。
- **不覆盖** `n > 100000` 行、> 500 列的数据（Web 层显式拒绝）。

---
