# EngSmartSuite 改善计划（第三轮 · 基于实测复核）

> 制定日期：2026-09-24
> 证据基线：`logs/reports/verify-round3/R3-复核清单.md`（8 项断言逐条实测）+ 第一轮四维度审计
> 工作区 HEAD：`64fe560`，`git status` 干净
> 适用范围：本计划替代 `logs/reports/EngSmartSuite_评估报告_源码验证与改善计划.md`（其 Phase A/B 已基本执行完毕）

---

## 零、计划的核心判断

前两轮改善（Phase A/B）修的是**单个缺陷**：CSV 编码、空串参数、error_id、惰性导入、拆分巨石。
本轮复核暴露出的是**一类缺陷**——同一个反模式在不同模块反复出现：

| 现象 | 实例 |
|---|---|
| **错误归因**：引擎知道真实原因，出口把它抹成泛化文案 | `OverflowError → "数据中可能存在极端值"`（A2）；`±Inf → "常量列（标准差为 0）"`（R2 已证实） |
| **边界处理逐函数手抄，覆盖不全** | 279 处 `status="error"` 早退；`drop_non_finite` 覆盖 6 个模块、漏 6 个 |
| **文档承诺 > 实现** | `_validate_output_path` 声称校验目录却不校验（A5）；手册 §9.2 验证日期早于仓库首个提交（A8）；`crossval` 注释写"R 参考"但文件自认无 R 参考值 |
| **测试是同义反复** | `test_cp_cpk_values` 用整体 σ 校验组内 σ 口径的 Cp（A1） |

**因此本计划的排序原则是：先定契约，再修个体，再建裁判，最后才做架构收口。**

理由：在边界契约（怎么清洗、怎么降级、怎么报错、怎么标注口径）确立之前动手修个体，
修出来的仍是第 4 种手抄风格。**而边界契约本身也是"消解错误归因"的唯一根治手段**——
错误归因的根因是"引擎内部知道原因、出口只有 12 个泛化条目"，不是某处映射表写错。

---

## 一、问题总账（按证据强度排序）

> **状态口径**：`✅已修` = 有复现测试且全量回归通过；`🔄进行中`；`⏳待办`。
> 每个 `✅已修` 条目必须能指到测试文件与实测证据，否则不得标记完成。
> 状态随实施更新——**本表是进度的唯一来源**（见 §十二 执行台账）。

### P0 — 静默错误 / 崩溃

| ID | 问题 | 证据 | 影响 | 状态 |
|---|---|---|---|---|
| **P0-1** | `spc_xbar` 子组 n≥380 时 `math.gamma` 溢出崩溃，且报"数据中可能存在极端值" | 端到端复现 n=380/400/500 全 error | 大子组 X-bar 图完全不可用；误导排查方向 | ✅已修 |
| **P0-2** | `survival_analysis` 文本事件列按字典序判定失效 | 复现 `Fail/Pass`→60 事件（真值 40）、`NG/OK`、`异常/正常` 同样反 | 可靠性结论**整体反转**，status 仍 `ok` | ✅已修 |
| **P0-3** | Cp/Cpk 置信区间用 `dof=n−1`，而 σ 来自 MR 法（`df_eff≈0.606(n−1)`） | 20000 次蒙特卡洛实测 df_eff=60.0(n=100)；CI 半宽低估 1.28 倍 | Cpk 下限虚高 → 放行判据失真 | ✅已修 |
| **P0-4** | `compare_digest` 遇非 ASCII 抛 TypeError → 500 HTML | 实测 `'é'`/`'中'` 均抛；全项目无 `errorhandler` | 无凭据即可触发 500 刷日志 | ✅已修 |

### P1 — 一致性与诚信

| ID | 问题 | 证据 | 状态 |
|---|---|---|---|
| **P1-1** | ANOVA 偏 η² 以 `η²` 为键输出，却用经典 η² 阈值解读 | 实测引擎值精确等于偏 η²（0.3365 vs 经典 0.3264） | ✅已修 |
| **P1-2** | `_validate_output_path` 文档承诺安全检查，实现为零 | `reporter.py:20-30` 逐行读毕 | ✅已修 |
| **P1-3** | 手册 §9.2 验证对照表：日期 2026-07-08 早于仓库首个提交 2026-08-16（39 天） | `git log --reverse` 首行；2026-07 提交数 = 0 | ✅已修 |
| **P1-4** | `crossval` 自认无 R 参考值，但 docstring 写满 `R 参考: qcc(...)` | 文件头 vs 类 docstring 自相矛盾 | ✅已修 |
| **P1-5** | Box-Cox 文档称"仅 CLI/模板"，实际无任何模板包含它 | 全仓 grep：templates/ 无 `transform` | ✅已修 |
| **P1-6** | ±Inf 清洗覆盖 6 模块漏 6 模块，且漏的地方**错误归因** | 实测只有 `spc_xbar` 误报"常量列"；cusum/ewma/capability 已正确报"有效数据不足" | ✅已修（xbar_r 已接入；其余经复测无需改） |
| **P1-7** | `setup_logging` 默认写包相对路径 → wheel 安装后写到 site-packages | `__init__.py:28` `dirname(__file__)/../../logs` | ✅已修 |

### P2 — 能力缺口（分优先级做，或诚实声明）

| ID | 缺口 | 相对 Minitab/JMP | 状态 |
|---|---|---|---|
| P2-1 | Gage R&R 无 ANOVA 方差分解（无交互项、无 F/p、无方差分量 CI） | AIAG 现代标准 | ✅已修 |
| P2-2 | Weibull 忽略删失数据（代码自认"结果有偏"） | 可靠性模块不可用于真实场景 | ✅已修 |
| P2-3 | ANOVA 只有 Type II SS（Minitab 默认 Type III） | 不平衡设计结论可能不同 | ✅已修 |
| P2-4 | t 检验无 Welch（全仓 `equal_var` 零命中） | Behrens-Fisher 场景 p 值失真 | ✅已修 |
| P2-5 | 过程能力无子组/池化 within-σ；Pp/Ppk 无 CI | 能力分析完整度 | ✅已修 |
| P2-6 | np/c 图不等样本量时无校验却给常数限 | 静默错误限 | ✅已修 |

### P3 — 门禁与交付（低风险改进）

| ID | 问题 | 状态 |
|---|---|---|
| P3-1 | 413/404/405 无 JSON errorhandler（前端已补偿，API 消费者受影响） | ✅已修 |
| P3-2 | `_data_path` 无目录归属校验（仅靠 cookie 签名） | ✅已修 |
| P3-3 | 前端 988 行单文件、20 个全局、11 处内联 onclick → CSP 被迫 `'unsafe-inline'` | ✅已修 |
| P3-4 | 前端三组任务分类学硬编码无守卫（`app.js:773-793`） | ✅已修 |
| P3-5 | 真值断言仅约 6%（约 15–20 处 / 1399 项） | 🔄 已补 6 组外部/覆盖率检验 |
| P3-6 | `tests/security`、`tests/crossval` 不在 PR quick job | ✅已修 |

---

## 二、阶段划分与顺序（为什么是这个顺序）

```
P1 边界契约   ← 你要求的"先规范边界处理"，也是根治错误归因的前提
      ↓
P2 个体修复   ← 在统一契约内修 P0/P1，避免产生第 4 种风格
      ↓
P3 外部裁判   ← 修完立刻用外部真值钉住，防止回归（"不建裁判不算修完"）
      ↓
P4 架构收口   ← 声明式参数 Spec（一次投资解决 4 件事）
      ↓
P5 能力纵深 + 门禁 + 交付
```

**与常见排序的差异**：把"建裁判"放在"修个体"之后而非之前。
理由：裁判的价值在于**锁住**已修好的状态。若先建裁判，会把当前错误行为一并冻结成"基准"，
后续修复还要反复改基准。先修后钉，返工最少。

---

## 三、阶段 P1：边界契约规范化

> 目标：让"退化输入怎么处理"从**每个函数各自决定**变成**一处声明、一处执行**。

### P1.1 定义边界分级（写入文档）

新建 `docs/governance/boundary-contract.md`，明确四级处置：

| 级别 | 语义 | 处置 | 示例 |
|---|---|---|---|
| **L1 拒绝** | 无法给出有意义结果 | `status="error"` + 唯一 `code` + 中文工艺术语 | 常量列做能力分析、USL ≤ LSL |
| **L2 清洗** | 可安全移除后继续 | 移除 + `messages` 披露数量 | NaN、±Inf |
| **L3 降级** | 主路径不可用，有等价次路径 | 走次路径 + **在结果与图表标题中标注降级** | PPF 失败 → 经验分位数；Box-Cox 失败 → 原尺度 |
| **L4 近似** | 无精确解，用渐近/近似 | 计算 + **标注口径** | 大 n 的 c4 渐近式；偏 η² |

**关键新增要求**：**L3/L4 必须在输出里可见**。当前 `nonparametric.py` 的 PPF 回退只写 `logger.debug`，
图表标题仍写"拟合=Weibull"——这是本计划要消灭的模式。

### P1.2 建立 `engine/_guard.py`（边界规范唯一执行点）

```python
# 目标结构（示意）
class BoundaryIssue:            # 一条边界处置记录
    level: Literal["L1","L2","L3","L4"]
    code: str                   # 机器可读，如 "E_NON_FINITE_DROPPED"
    detail: str                 # 中文工艺术语，面向用户
    column: str = ""

def clean_series(s, *, column="") -> tuple[pd.Series, list[BoundaryIssue]]
def clean_frame(df, cols, *, column="") -> tuple[pd.DataFrame, list[BoundaryIssue]]
def require_n(n, minimum, *, what="") -> BoundaryIssue | None
def require_non_constant(s, *, what="") -> BoundaryIssue | None
def positive_finite(value, name) -> tuple[float|None, BoundaryIssue|None]
def asymptotic_c4(n) -> float          # n≥380 的稳定路径
```

**这一步直接消灭 P1-6**：清洗不再是"逐函数记得调用"，而是引擎入口统一执行。

### P1.3 错误归因修复（根治，非补丁）

给 `AnalysisResult` 增加机器可读字段：

```python
code: str = ""        # 如 "E_SUBGROUP_TOO_LARGE"、"E_NON_FINITE_DROPPED"
```

配套：
- `core/exceptions.py` 中**从未被 raise 的** `AnalysisError` / `ConvergenceError` / `DataSelectionError`
  做出决定：**删除**（推荐，避免死代码给虚假的体系感）。
- `ERROR_DETAIL_MAP` 从"主路径"降为"兜底"。引擎抛出的领域错误走 `code`，
  `orchestrator` 只在**未预期异常**时查表。
- Web/CLI/手册的错误展示增加 `code`（可折叠），便于用户反馈时定位。

**验收**：P0-1 的用户可见文案从
`数值溢出，数据中可能存在极端值` 变为
`子组大小 n=400 超出当前实现上限（380）；请将子组拆分至 ≤380 个观测，或改用 I-MR 图`
（或直接修好让它不再报错——见 P2）。

### P1.4 口径披露

抽 `engine/_sigma.py`：

```python
def within_sigma_mr(x) -> float          # mean(MR)/1.128，I 图口径
def within_sigma_subgroup(s) -> float    # S̄/c4，子组口径
def within_sigma_range(rbar, n) -> float # R̄/d2，X-bar/R 口径
def overall_sigma(x) -> float            # ddof=1
```

每个调用点显式选择，并在 summary 中披露（如"Cp 基于移动极差法组内 σ（假定行序=时间序）"）。
**不是"统一成一个 σ"**（复核 A7 已证明各不相同是正确设计），而是**让选择显式可审计**。

**P1 验收清单**：
- [ ] `docs/governance/boundary-contract.md` 落地，含 L1–L4 定义与全量退化输入清单
- [ ] `engine/_guard.py` 建立，且被至少 3 个模块接入（capability / spc_xbar / reliability）
- [ ] `AnalysisResult.code` 落地，至少 6 个高频错误码
- [ ] 死异常类处置完毕（删除或启用，无中间态）
- [ ] 现有 1396 项测试全绿，无回归

---

## 四、阶段 P2：个体修复（在 P1 契约内）

按"影响 × 可验证性"排序，每项**先写复现测试（红）→ 修复 → 绿 + 无回归**。

| 序 | ID | 动作 | 复现测试 |
|---|---|---|---|
| 1 | **P0-1** | `we_rules.py` c4 改对数域 `lgamma` 差分；超大 n 走渐近式并在 summary 标注 L4 | `n=380/400/500/5000` 断言 `status=="ok"` 且 c4 与独立路径一致 |
| 2 | **P0-3** | `capability.py` χ² 区间改 `df_eff ≈ 0.606(n−1)`（MR 口径）；或显式标注"CI 为整体 σ 近似" | 蒙特卡洛：实测覆盖率达到名义 95%（当前约 78%） |
| 3 | **P0-2** | survival 文本事件列**不再猜**：要求显式声明或用配置化映射，歧义时 L1 拒绝 | `Fail/Pass`、`NG/OK`、`异常/正常` 断言要么正确、要么明确报错 |
| 4 | **P0-4** | `require_csrf` 先 `isinstance` + `encode()` 归一，再 `compare_digest` | 非 ASCII token 断言 403（非 500） |
| 5 | **P1-6** | 接入 `_guard.clean_series` 到剩余 6 个模块 | 每个模块一组含 ±Inf 数据，断言披露正确、**不再归因为"常量列"** |
| 6 | **P1-1** | ANOVA 键改 `偏 η²`，同时输出经典 `η²`；阈值按口径给出 | 对照 statsmodels 断言两者都正确 |
| 7 | **P1-2** | `_validate_output_path` 二选一：真校验，或删承诺并改名 `_prepare_output_path` | 后者：断言同名函数不再出现在安全相关命名空间 |
| 8 | **P1-7** | `setup_logging` 默认不再写包相对路径（改 `SMARTSUITE_LOG_DIR` 或平台日志目录） | wheel 安装模拟：断言不在 site-packages 建 logs/ |
| 9 | **P2-4** | `ttest_ind` 默认 `equal_var=False` + Levene 预检 | 不等方差算例断言 p 与 scipy Welch 一致 |
| 10 | **P2-6** | np/c 图不等样本量 → L1 拒绝或改变限 | 不等 n 数据断言拒绝/变限 |
| 11 | **P3-1** | 加 `@app.errorhandler`：404/405/413/500 在 `/api/*` 返回 JSON | 断言 4 类状态码 `Content-Type: application/json` |
| 12 | **P3-2** | `_data_path` 增加目录归属硬校验 | 越界路径断言被拒 |

---

## 五、阶段 P3：验证锚定（锁住已修状态）

这是第一轮评价里指出的**最大差距**：验证是内向闭环。本阶段补外环。

### P3.1 参考值金标准（已落地，可空跑）

```
tests/golden/
├── __init__.py
├── _loader.py                    # 参考值装载器：有值则对账、无值则 skip + 缺口披露
├── reference.json                # 外部参考值表（当前为空占位，schema 已定义）
├── test_reference_loader.py      # 装载器自测 + UNANCHORED_METHODS 局限登记（19 项）
└── test_spc_msa_golden.py        # 教科书公式独立复算（26 项）—— 无需任何外部工具
```

设计要点：**参考值与测试解耦**。`reference.json` 有值时自动逐个对账并进入 PR 门禁；
无值时对应用例 skip 且**在 `UNANCHORED_METHODS` 中显式登记局限**，由断言保证
清单不与实际状态漂移。将来若补入任何来源的参考值，**只需往 JSON 填数，不改测试代码**。

### P3.2 第三方工具验证：**已决定放弃**（2026-09-24）

**决定：本项目不使用任何第三方统计工具做数值验证。**

先厘清一个常见误解：那些工具在本项目中**从来不是依赖，只是文字**。实测确认：

| 检查 | 结果 |
|---|---|
| `pyproject.toml` 依赖 | 无任何统计工具运行时绑定 |
| `src/` 中外部工具调用代码 | 空 |
| 仓库内 `.R` / `.Rmd` 脚本 | 无 |
| 测试中执行外部工具（subprocess/os.system） | 空 |
| CI（7 个 workflow）安装外部工具 | 空 |

⇒ 清除相关字样对代码质量**零影响**。唯一值得保留的是 `capability.py:36`
对某统计软件包口径的**文献引用**（属论证依据，非验证依赖），已保留。

**该决定留下的局限（如实记录，非待办）**：

独立第二实现能抓"公式转写错、常数错位、口径误用"，但抓不到
**"教材理解本身有偏差"** —— 例如 X-bar 不等子组的加权方式、Gage R&R 嵌套设计、
ANOVA 不平衡设计的 SS 选择。这类问题**目前只能靠人工复核与文献引用**。

该局限由 `tests/golden/test_reference_loader.py` 的 `UNANCHORED_METHODS`
（10 项，逐条写明具体缺什么依据）**持续披露**，并有断言防止清单被
"清空成无缺口"或与实际状态漂移。

> **决策锚点**：`test_no_third_party_tool_pending_work_left` 与
> `test_registry_reasons_are_not_pending_todos` 两条断言把该决定固化在代码里 ——
> 若日后重新考虑引入外部工具，必须显式修改这两条断言，
> 而不是悄悄让待办表述回流。

### P3.3 覆盖率结论（已完成）

对 `capability` 的 CI 做**蒙特卡洛覆盖率检验**：重复 2000 次抽样，统计
"真 Cp 落入报告 CI 的比例"是否达到名义 95%。
**这是把"A1 同义反复"彻底替换掉的正确测试形态** —— 它检验估计量的统计性质，
不是"我和另一个错误公式是否接近"。实测：**改前 ≈0.78 → 改后 0.95**（P0-3）。


### P3.3 测试强度自检

- 一次性运行变异测试（`mutmut`/`cosmic-ray`），**不入常态门禁**，产出一份
  "哪些测试是装饰品"的报告，据此决定后续测试投入。
- `verify_manual_claims.py` 扩展：不只对数值，还要对**口径声明**（σ 类型、SS 类型、
  CI 方法）做双向校验。

---

## 六、阶段 P4：架构收口（声明式参数 Spec）

**这是单点杠杆最高的改动**，一次投资解决四件事：

```python
@engine_task(
    key="process_capability",
    group="过程监控",
    label="过程能力Cp/Cpk",
    params=Spec(
        usl=Opt(Finite, gt=0, label="规格上限 (USL)", hint="USL > LSL"),
        lsl=Opt(Finite, gt=0, label="规格下限 (LSL)"),
        target=Opt(Finite, label="目标值"),
        transform=Opt(Choice("boxcox"), default=None, label="正态化变换"),
    ),
    require=[RequireTarget(kind=NUMERIC), RequireN(3), RequireNonConstant()],
    cross=[Rule("usl > lsl", code="E_SPEC_INVERTED", msg="规格上下限颠倒")],
)
def process_capability_analysis(req, p: Params) -> AnalysisResult: ...
```

一次性收益：

| 收益 | 对应问题 |
|---|---|
| 参数校验/强转/NaN-Inf 拒绝/中文错误消息集中一处 | P1-6；279 处手抄；`capability.py` 180 行防御头 → 5 行 |
| `code` 由 `Spec` 自动产生，不再靠 12 条泛化映射 | P0-1 的错误归因根治 |
| `DEFAULT_PARAMS` / `TASK_PARAMS` / `PARAM_META` / `PARAM_LABELS` / `PARAM_HINTS` **五份 → 一份派生** | 前端 SSOT 漂移 |
| `api-reference.md` 的参数段可生成 | 文档漂移；Box-Cox 类"文档有、代码不可达" |
| 新增方法成本 **8 步 → 1 步** | AGENTS.md 八步注册清单可废止 |

**验收**：
- engine 的 `status="error"` 早退从 **279 → <80**
- 裸 `ValueError` 从 **43 → <10**

### ⚠️ 验收判据的修正（第十二轮实测后）

迁移两个任务后实测发现，**`status="error"` 计数不是本阶段合适的进度指标**：

| 事实 | 实测值 |
|:---|:---|
| 当前全引擎早退总数 | **282** |
| 其中**参数校验类**（可迁到 `Spec`） | 约 **54** |
| 其余 | 约 228 处**依赖数据**的检查（样本量/常量列/结构），**迁不走** |
| 每次任务迁移的代价 | **+1** 处 `Spec` 早退（`PARAM_SPEC.validate()` 的失败分支） |

**算术结论**：即使 54 处参数校验全部迁移，下限也只到约 250 —— **`<80` 在"早退式"架构下不可达**。

要真正大幅下降，必须改变**失败传播方式**：让迁移后的任务**抛 `SmartSuiteError`**
（`core/exceptions.py` 已有 `ValidationError`），由编排层统一转结果 ——
`orchestrator.py` 已有 `except SmartSuiteError → build_error_result()` 的完整通路。
那样每次迁移是 **−N 处早退、0 处新增**。

**代价**：现有直接调用引擎的测试期待 `status="error"` 返回值，改为抛出后需同步改写
（首个异常式迁移需评估影响面）。

**修正后的验收判据**（可测量、可达成）：

| 判据 | 目标 |
|:---|:---|
| 参数校验**手写重复**从引擎消除 | 54 处 → 0（全部走 `Spec`） |
| 五份平行字典删除 | 前端 4 份 + `DEFAULT_PARAMS` 全部由 `Spec` 派生 |
| 早退计数 | 作为**参考**而非硬指标。实测（第十三轮）：异常式迁移后为 **283**（起点 287）—— 因为剩下 ~228 处是数据质量守卫，**这部分是合法的防御代码，不该为凑数而删** |
| 新增方法注册步数 | 8 步 → 1 步（声明 `Spec` + 注册） |

> **记录原因**：原判据（279→<80）是**未做迁移时的估算**。实测 54 vs 282 的构成后
> 才看清：早退的主体是**数据相关检查**，不是参数校验。
> 计划允许被实测修正 —— 但必须**显式改写并说明原因**，不得默默放过。
- `app.js` 的 `TASK_PARAMS`/`PARAM_META`/`PARAM_LABELS`/`PARAM_HINTS` 四份平行字典**删除**，
  改由 `/api/tasks` 下发

### 执行进度（2026-09-24，第十轮）

| 步骤 | 状态 | 说明 |
|:---|:---|:---|
| ① 建声明式契约基础设施 | ✅ **已完成** | `core/param_spec.py`：`Spec` / `Req`·`Opt` / 6 个校验器 / `CrossRule` / 内省。双轨期只新增，不改引擎。`tests/core/test_param_spec.py` 55 项 |
| ② 首个任务迁移（范式） | ✅ **已完成**（第十一轮） | `process_capability` 的纯参数校验已迁到 `PARAM_SPEC`；45 项迁移对拍测试（含"迁移前行为快照"与 11 组输入的双向一致性）。该任务 `status="error"` **12 → 6** |
| ③ 逐任务迁移 | ✅ **完成**（36/36 个有参数的任务；另有 6 个任务无参数可迁）（第二十轮建共享字段库后**批量推进**：已完成 **36** 个 —— `process_capability`、`spc_attribute`、`power_analysis`、`contingency`、`normality_check`、`median_ci`、`variance_test`、`doe_analysis`、`trend_forecast`、`vif`、`distribution_summary`、`decision_tree`、`proportion_ci`、`quantile_regression`、`response_surface`、`change_point`、`correlation`、`logistic_regression`、`spc_nonparametric`、`spc_cusum`、`spc_ewma`、`lasso_regression`、`multi_objective`、`anomaly_detect`、`anova`、`grid_search`、`spc_xbar`、`scatter_plot`、`tolerance_interval`、`bootstrap_ci`、`gage_rr`、`box_chart`、`hypothesis_test`、`doe_design`、`inverse_solve`、`regression`）。**派生标签覆盖率 100%**（114/114 个默认参数槽位）—— 这是步骤④ 的前置条件 | 每个任务一个独立增量，可中断。异常式通路已于第十三轮验证；本轮 `power_analysis` **早退 17 → 7**。**迁移的直接收益**：① 该任务校验收口；② 其标签/提示自动从手写字典切到 `Spec`（派生素材 10 → 19 条） |
| ④ 删除五份平行字典 | ✅ **完成**（第二十八轮） | ✅ `TASK_PARAMS`（45 行）已删 → `/api/tasks` 下发。✅ `PARAM_LABELS`(36 行)/`PARAM_HINTS`(11 行)/`PARAM_META`(167 行) 共 **214 行**已删 —— 标签/提示/选项全部改为后端派生（覆盖 114/114 个参数槽位）。保留 `COLUMN_PARAMS`（4 个列选择器）：**纯 UI 关注点**，取决于运行时数据列，`Spec` 无从知晓。`params.js` 684 → **451 行**。守卫：`scripts/check_params_panel.mjs` + `tests/scripts/test_params_panel.py`（半运行时冒烟）+ `test_web_ui_guards.py` 的反向断言 |

**基线已量化**（第十轮实测）：`status="error"` **287** 处、`raise ValueError` **44** 处
（与计划写的 279 / 43 略有出入 —— 因期间 P2 新增了校验。以实测为准）。

> ⚠️ **诚实说明**：本阶段原估 8–12 天，目前只完成了基础设施（①）。
> ②–④ 是逐任务的机械迁移，每步独立可验证，但**总量大**。
> 在 ③ 完成前，`status="error"` 的计数**不会下降** —— 因为手写校验仍在。
> 任何"已完成架构收口"的说法在此刻都是不实的。

---

## 七、阶段 P5：能力纵深 / 门禁 / 交付

### P5.1 能力纵深（按用户价值，不按数量）

1. **删失 Weibull MLE**（对数似然含删失）→ 可靠性模块从"不可用"到"可用"；
   顺带 B10 + 百分位寿命 CI + Greenwood SE。**这一项价值高于其余全部。**
2. **Gage R&R 的 ANOVA 法**（交互项 + F/p + 方差分量 CI）→ AIAG 标准；顺带解决不平衡设计的静默 `mode()`。
3. **Type III SS 选项** + 偏 η² 正确标注（P1-1 已含）。
4. **子组/池化 within-σ + Pp/Ppk CI**。
5. **ARL/OC 曲线**（EWMA/CUSUM 的 λ-L 选择依据）。

### P5.2 门禁

- `tests/security`、`tests/crossval` 纳入 PR quick job（现在只在 full 矩阵跑）。
- 前端三组任务分类学改由 `/api/tasks` 下发，加守卫。
- 413/404/405 JSON 契约测试（P3-1 的验证）。

### P5.3 交付形态

- 前端切 ES modules（原生 ESM，不引入打包器）：`api.js` / `state.js` / `render.js` / `params.js`。
- 消灭 11 处内联 onclick（改事件委托）→ CSP 去掉 `'unsafe-inline'`，补 `frame-ancestors`。
- Playwright 冒烟 3–5 条（上传→选列→跑分析→表格渲染）。
- **Web 端报告导出入口**（现在 `to_html/to_pdf/to_ppt/export_workbook` 全是 CLI 专有）。

### P5.4 诚信修复（零成本，立即做）

- 手册 §9.2 改为脚本生成的表格，或删除（P1-3）。
- `crossval` 的 "R 参考" 注释删除或改为真实参考（P1-4）。
- Box-Cox 三选一：接入 Spec/前端，或加模板，或从文档删除（P1-5）。
- `pyproject.toml` classifier `Development Status: 5` → `4 - Beta`，或补一张
  **与 Minitab/JMP 的能力对照表**（P2 缺口清单已备好）。

---

## 八、边界情况总清单（P1.1 的输入）

以下是本次复核与审计中**实际观察到**的退化输入，P1 必须逐条给出 L1–L4 定级并测试：

| 类别 | 退化输入 | 当前行为 | 应为 |
|---|---|---|---|
| 非有限值 | `±Inf` 混入目标列 | 6 模块清洗、6 模块漏且误报"常量列" | L2 统一清洗 + 披露 |
| 非有限值 | `NaN` 参数（`k=nan`、`h=inf`） | 部分有 `is_positive_finite` 守卫 | L1 统一拒绝 |
| 规模 | 子组 n≥380 | `OverflowError` → 误报"极端值" | 修好（P0-1），超大 n 走 L4 渐近 |
| 规模 | 行数 >100k / 列数 >500 | Web 层 L1 拒绝 | 保持 |
| 规模 | 子组 n 不一致 | 取 `min(n)` 但 `R̄` 用全量 → 控制限偏高 | L1 拒绝或按 nᵢ 加权 |
| 常量 | 目标列唯一值 ≤1 | 各模块行为不一（有的拒绝、有的返回 None 且 ok） | L1 统一拒绝 |
| 样本量 | n<3 / n<5 / 单行 / 空 DataFrame | 逐函数各自判 | L1 统一 + 各方法最小 n 表 |
| 编码 | 事件列文本 2 值 | 字典序猜（P0-2） | L1 要求显式声明 |
| 编码 | 事件列数值非 {0,1} | 已收紧为 L1 拒绝 ✅ | 保持 |
| 缺失 | 列存在但全 NaN | 部分走 `dropna` 后触发 n 下限 | L1 明确"整列为空" |
| 类型 | 目标列为 object（字符串数字） | `preprocess` 自动转中位数并披露 | 保持 + 披露强化 |
| 数值 | 微尺度（~1e-10） | 已修（相对阈值）✅ | 保持 |
| 数值 | 极端量级导致 lgamma/gamma 溢出 | P0-1 | L4 |
| 文件 | UTF-16/Big5 无 BOM | 已修为 L1 明确报错 ✅ | 保持 |
| 文件 | 混合 dtype 列 → parquet | 已修为转 string ✅ | 保持 |
| 并发 | 上传文件被清理线程删除（TOCTOU） | 已修 ✅ | 保持 |

**注意**：清单里 **7 条是"保持"**——这轮计划不是推翻既有边界处理，
而是把已有的正确做法**提取成共享契约**，让剩下 9 条不再各自为政。

---

## 九、验收与节奏

### 每项的固定流程

```
1. 写复现测试 → 确认 FAILS（红）
2. 修复
3. 确认 PASSES（绿）
4. 跑 python scripts/verify_all.py（无回归）
5. 保留复现测试
6. 更新 boundary-contract.md（若边界语义有变）
```

### 阶段收口门禁

```bash
ruff check src/smartsuite/ scripts/ tests/
ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/
mypy  # 全量 src/smartsuite
pytest tests/ -q                      # 期望全绿（2026-09-24 实测 1824 passed / 4 skipped）
python scripts/verify_all.py          # 上述四步的一键入口（另含 compileall + falsy 审计）
python scripts/verify_manual_claims.py
```

> **本轮补记**：`verify_all.py` 是本计划自己定义的验收命令，但在前八轮里我
> **只跑了它包含的单项，从未跑过它本身**。第九轮实测通过（见台账）——
> 教训：**计划里写下的验收命令要真的执行，不能只执行"看起来等价"的子集**。
> 它额外覆盖 `compileall`（语法/导入）与 `falsy_audit`（falsy 陷阱审计）两步。

### 预算（单人维护，业余时间）

| 阶段 | 估时 | 可否中断 |
|---|---|---|
| P1 边界契约 | 3–5 天 | 可（每接入一个模块即一个可交付增量） |
| P2 个体修复 | 5–7 天 | 可（12 项互相独立，按序做） |
| P3 外部裁判 | 4–6 天 | 可（每个方法一个参考值是独立增量） |
| P4 架构收口 | 8–12 天 | 可（逐任务迁移，双轨期两套并存） |
| P5 纵深/门禁/交付 | 持续 | 是 |

### 明确不做（延续既有 YAGNI 决策）

- 不重写。4.3 万行带根因注释的工艺知识是本项目最稀缺资产。
- 不引入打包器/前端框架（原生 ESM 足够）。
- 不引入 Redis/作业队列/插件生态/i18n（延续前一轮决策）。
- 不把变异测试设为常态门禁（一次性诊断即可）。

---

## 十、完成后的预期状态

| 维度 | 计划制定时 | 目标 | 当前 |
|---|---|---|---|
| 边界处理 | 逐函数手抄，覆盖 50% | 一处声明、一处执行，100% | ✅ **已达标（第三十八轮收口完成）**：`_utils` 的旧清洗函数（`drop_non_finite` / `drop_non_finite_rows` / `non_finite_note`）**已删除**，全包内旧调用点实测 **0**（起点 23 处 / 7 个模块）。7 个模块全部改走 `engine/_guard.py`；进度清单 `docs/governance/guard-migration.md` 已由「进度表」转为「收口记录」。**顺带兑现**：各任务 `metadata["boundary_codes"]` 现在给出机器可读错误码（格式 `E_<域>_<原因>`），迁移前只有中文文案、上游只能做子串匹配 |
| 错误诊断 | 数据中可能存在极端值 | `code` + 可执行建议 | ✅ **已改（第三十一轮）**：12 条映射从「单一病因断言」改为「现象 + 两支建议」，带稳定分流标记 `[数据]` / `[内部]`；`AttributeError` 明标为引擎缺陷、不再让用户核列名；兜底文案不再断言数据完整性。**注**：`BoundaryIssue.code` 仍只接入 `spc_xbar`（见下一行的如实标注） |
| 真值断言 | ~6% | ≥25% | 🔄 **大幅推进，仍未达标（第 42 轮）**。**先厘清口径**（此前我自己混用过三种）：原判据是「有独立真值的测试 / 全部测试」= 约 15–20 / 1399 ≈ 6%；第四十二轮实测三种口径分别为 **11.2%**（真值/测试函数，原判据）、**39.5%**（真值/数值类断言）、5.4%（真值/全部断言）。**本轮完成的关键里程碑：零真值断言的任务 21 → 0**（42/42 任务都有真值断言）。新增 `tests/engine/test_task_truth_assertions.py`（17 项）——按**任务**组织，每个任务一条由数学唯一确定… |
| 对齐 Minitab | 能力/可靠性/GRR 有明显缺口 | 可靠性可用；GRR 补 ANOVA 法；缺口表公开 | ✅ **已完成，且原始判断被实测推翻**：新增 `docs/governance/minitab-alignment.md`（含 A/B/C/D 四级验证标注）+ `tests/engine/test_minitab_alignment.py`（**40 项**）。**实测后修正了本行的原始描述**：不是「有明显缺口」，而是**对齐面很宽** ——XBR_CONSTANTS 与 Minitab 标准常数表逐值一致（A 级）、`Cp`/`Pp`/`%Tolerance`/`ndc`/ANOVA 方差分量与 CI 均已实现并与公式对账（B 级）、判定阈值对齐 AIAG（C 级）。**真实缺口只剩 5 处**（误分类概率 / `%Process` /能力报告内正态性检验 / Box-Cox 变换后指数 / VDA 5），且每处都写明了「为什么不补」 |
| 新增方法成本 | 8 步 | 1 步 | ✅ **已达标（第 42 轮）**：新增 `scripts/new_task.py` 脚手架 —— **一条命令**完成引擎桩 / `__all__` / `TASK_SPECS` 注册 / YAML 模板 / 测试骨架（刻意先红）/ api-reference 六步，并**打印剩余人工项**；配 `--check` 守门（逐项核对既有 42 个任务的登记完整度）。**最关键的一步不在原 8 步清单里**：`static/app.js` 曾有三份手写任务集合（`_noTargetNeeded`/`_yOnlyTasks`/`_xOptionalTasks`），新增任务忘改则**Web 上静默不可用**（用户看到「请至少选择一个 X 列」）。第 42 轮已改为 `TaskSpec` 声明 `y_only`/`x_optional` → `derive()` 派生 → `/api/tasks` 下发 → 前端只读，**结构上不可能漂移** |
| 文档诚信 | 4 处承诺 > 实现 | 0 处 | ✅ **已修**：A5（`_validate_output_path` 改名 + 真实校验）、A8（手册 §9.2 伪对照表重写 + 删除 R 参考措辞）、A1（`test_cp_cpk_values` 同义反复已换真值断言）、P1-4（`crossval` 的 8 处 R 参考改写为独立第二实现） |

---

## 十一、破坏性变更与行为变更清单（供 commit message 引用）

> **为什么要单独列**：`CHANGELOG.md` 由 release-please 从 **conventional commits**
> 自动生成，**不得手改**（`scripts/verify_docs.py` 有版本一致性门禁）。
> 因此"哪些改动会改变用户可见结果"必须在**计划里**记清楚，
> 提交时才能写出带 `!` 与 `BREAKING CHANGE:` 的 commit message。
>
> 本清单**随实施累积**，每条都注明"用户会看到什么不同"。

### A. 破坏性变更（需 minor 版本 + `!`）

| # | 变更 | 用户会看到什么不同 |
|:--|:---|:---|
| A1 | **`hypothesis_test` 的独立双样本 t 检验默认改为 Welch** | `test=ttest_ind` 的 **p 值与自由度会变**（实测不等方差 + 不等 n：0.8267 → 0.5990）。`test_results` 表新增「自由度」「方差齐性」两列；方差不齐时 `messages` 多一条告知 |
| A2 | **ANOVA 的 `η²` 改为经典口径**（偏 η² 移至「偏 η²」列） | 同名列的数值变小（经典 η² ≤ 偏 η²） |
| A3 | **`survival_analysis` 拒绝语义歧义的文本事件列** | 事件列若为 "是/否"、"1/0" 等有歧义的文本编码，**由"猜测"改为明确拒绝**（原先按字典序静默解析） |
| A4 | **属性控制图（np/c）拒绝不等子组大小** | 原先静默取平均/首个，现有明确报错 |

### B. 行为变更（不破坏接口，但结果或文案会变）

| # | 变更 | 用户会看到什么不同 |
|:--|:---|:---|
| B1 | **CSP 收紧**：`script-src` 与 `style-src` 不再允许 `'unsafe-inline'` | 若在页面里注入自定义脚本/内联样式，会被浏览器拦截（内置 UI 已全部改为外部文件 + class 切换） |
| B2 | **`setup_logging` 默认日志目录** | 由"包内目录"改为 `SMARTSUITE_LOG_DIR` → `cwd/logs` |
| B3 | **参数错误文案包含参数名** | 例如「参数「规格上限 (USL)」应为有限数值」—— 便于定位是哪个参数 |
| B4 | **`chart_type` 归一化**；不存在的 `n_col` 被拒绝 | 拼写变体仍可用，但完全无法识别的取值由"静默回落"改为明确拒绝 |
| B5 | **10 处"静默降级"改为明确拒绝** | `vif.threshold`、`distribution_summary.bins`、`scatter_plot.fit`、`bootstrap_ci.n_bootstrap`、`decision_tree.max_depth`、`grid_search.n_points`、`box_chart.mode`、`doe_design.center_points`/`n_runs`/`replicates`/`seed`。**原先非法值静默回落默认值**（用户以为生效了），现报错 |
| B6 | **`scatter_plot.show_ci` / `box_chart.show_stats`** | 无法识别的取值由"静默当作 True"改为明确拒绝；`box_chart.show_stats` 的**默认值表示**由布尔 `True` 改为字符串 `"true"`（二者等价） |
| B7 | **`gage_rr` 新增 `%P/T`** | 给 `tolerance` 时新增 `pt_ratio` / `pt_percent` 输出；`judge` 改为取 `%GRR` 与 `%P/T` 中**更差者**（AIAG 对两者用同一套阈值） |
| B8 | **错误文案改为"现象 + 两支建议"** | `error_messages.py` 的 12 条映射不再断言病因，带 `[数据]` / `[内部]` 分流标记 |

### C. 新增能力（不改变既有行为）

- `metadata["boundary_codes"]`：机器可读边界处置码（格式 `E_<域>_<原因>`），
  覆盖 7 个模块；迁移前只有中文文案。
- `docs/governance/minitab-alignment.md`：与 Minitab 的口径对照（含 A/B/C/D 四级验证标注与 5 处如实缺口）。
- `docs/governance/guard-migration.md`：`_guard` 收口记录。

---

## 十二、执行台账

> **本节是进度的唯一来源**，跨会话接力时先读这里。
> 规则：只记**有测试或实测证据**的完成项；无证据的改动不得进"已完成"区。

### 已完成（有证据）

| 日期 | 条目 | 改动 | 证据（测试 / 实测） |
|---|---|---|---|
| 2026-09-24 | **规范建立** | 新增 `docs/governance/boundary-contract.md`（B0–B3 契约 + 20 条边界清单 + 错误码命名规范） | `verify_docs.py --strict` 通过 |
| 2026-09-24 | **执行点** | 新增 `src/smartsuite/engine/_guard.py`（`BoundaryIssue`/`BoundaryReport`/`partition_finite`/`clean_series`/`clean_frame`/`check_n`/`check_non_constant`/`check_finite_param`/`explain_undefined_sigma`） | `tests/engine/test_boundary_guard.py` 36 项 |
| 2026-09-24 | **P0-1** c4 溢出崩溃 | `we_rules.py` 新增对数域 `c4()`，`_xbar_s_constants` 改用它 | `tests/guards/test_boundary_contract.py` 的 `TestC4Primitive`（ASTM 表 + 独立 lgamma 路径，n 至 100000）；实测 n=380/400/500 由 error → ok |
| 2026-09-24 | **P0-2** 事件列语义 | `reliability.py` 新增 `_EVENT_TRUE_ALIASES`/`_EVENT_FALSE_ALIASES` + `_resolve_event_value` + `_encode_text_event_column`；新增 `params.event_value` 显式声明 | `tests/engine/test_survival_event_semantics.py` 31 项；实测 `Fail/Pass` 由 75（真值 25）→ 拒绝或按声明算 25 |
| 2026-09-24 | **P0-3** Cp/Cpk CI 自由度 | `capability.py` 新增 `_mr_dof_eff()`（0.606(n−1)），χ² 与 Bissell 均改用它 | `tests/engine/test_capability_ci_coverage.py` 11 项；**实测覆盖率由约 0.78 → 名义 0.95** |
| 2026-09-24 | **P0-4** CSRF 非 ASCII | `web/app.py` 新增 `_csrf_tokens_match()`（先 encode 再 constant-time 比较） | `test_boundary_contract.py::TestCsrfTokenComparison` 5 项；实测 `'é'`/`'中'` 由 500 → 403 JSON |
| 2026-09-24 | **P3-1** API 错误契约 | `web/app.py` 新增 `errorhandler`（400/403/404/405/413/500）→ `/api/*` 一律 JSON；CSP 补 `frame-ancestors 'none'` + `X-Frame-Options` | 同上（断言 `Content-Type: application/json`） |
| 2026-09-24 | **P1-6** 错误归因 | `xbar_r.py` 接入 `partition_finite` + `explain_undefined_sigma`；非有限 σ 先于常量判据归因 | `test_boundary_contract.py::TestInfNotBlamedAsConstant`；实测 +Inf 不再报"常量列（标准差为 0）" |
| 2026-09-24 | **源码防线** | `test_boundary_contract.py::TestBoundaryContractSourceGuard`：禁止"报常量却无判别路径"、禁止"清洗却不披露" | 2 项源码级 AST/正则断言 |
| 2026-09-24 | **回归验证** | — | 全量 **1525 passed / 4 skipped / 0 failed**；`ruff check` + `format` 通过；`mypy` 66 文件零问题；`test_quality_guard` 零 FAIL；`verify_docs --strict` 通过 |
| 2026-09-24 | **P1-2** 报告路径文档谎言 | `reporter.py` 改名 `_prepare_output_path`，补真实校验（空路径／目标已是目录／父路径是文件），docstring 如实描述；**有意不加目录白名单**（CLI 导出任意路径是合法需求） | `tests/services/test_output_path.py` 20 项（含"不得再承诺未实现检查"的文档防线） |
| 2026-09-24 | **P1-7** 日志写入 site-packages | `__init__.py` 新增 `LOG_DIR_ENV` + `_default_log_dir()`：`SMARTSUITE_LOG_DIR` → cwd/logs，**不再用包相对路径**；降级链保留但记日志说明落点 | `tests/services/test_logging_setup.py` 8 项（模拟包在他处时断言不写包目录） |
| 2026-09-24 | **P1-1** 偏 η² 冒充 η² | `anova.py` 同时输出经典 `η²` 与 `偏 η²`；展示按经典口径 + 经典阈值（口径一致）；增强表增列 | `tests/engine/test_anova_effect_size.py` 12 项；实测两口径与 statsmodels 复算逐位一致（rel<1e-9） |
| 2026-09-24 | **P2-4** 无 Welch | `hypothesis.py` 默认 Welch（`equal_var=False`）+ Levene 方差齐性检验 + Welch–Satterthwaite 自由度；结果表新增「自由度」「方差齐性」列 | `tests/engine/test_welch_ttest.py` 9 项；实测不等方差算例 p 由 0.8267（Student）→ **0.5990（= scipy Welch）** |
| 2026-09-24 | **P1-3** 手册伪造的验证表 | `docs/user-manual/09-result-verification.md` 整章重写：删掉"验证日期 2026-07-08"（早于仓库首个提交 39 天）与 `... (全部任务)` 占位；改为**可执行**的四条复核路径 + 明确写出"没验证什么" | 新增 9.1（真正的差分验证在哪）/ 9.2（四层防线强度如实说明）/ 9.3（用户可自跑）/ 9.4（验证边界） |
| 2026-09-24 | **P1-4** `crossval` 虚假 "R 参考" | 8 处声明全部改写；**实测确认本机无 R**（`Rscript` 不存在，`R` 仅 PowerShell `Invoke-History` 别名）→ 按预案退化为独立第二实现并逐处标注来源 | 新增 3 条**真值断言**：回归 R²/系数对 statsmodels（rel 1e-9 / 1e-6）、Cp 对组内σ(MR 法)、Pp 对整体σ；并加"自相关数据下 Cp≠Pp"的口径分歧防线 |
| 2026-09-24 | **P2-6** np/c 图常数限假设 | `attribute.py` 新增 `_unequal_sample_sizes()`；np/c 分支前置校验样本量一致性，不等即 B0 拒绝并指出正确替代（p/u 图） | `tests/engine/test_attribute_sample_size.py` 9 项；实测不等 n 的 np/c 由静默出限 → 拒绝；p/u 图在不等 n 下仍逐点变限 |
| 2026-09-24 | **P3-2** 会话路径归属 | `web/app.py` 新增 `_is_within_upload_dir()`（`resolve()` + `commonpath`，防同前缀兄弟目录误放行）；analyze 拒读越界路径、upload 拒删越界旧路径 | `tests/services/test_session_path_containment.py` 14 项；实测"session 指向上传目录外的文件"时：读被拒（400）+ 文件**未被删除** |
| 2026-09-24 | **P2-2** 删失 Weibull MLE | `reliability.py` 新增 `_weibull_fit_censored()`（对数域优化 + 复步长梯度 + 中心差分 Hessian → 观测 Fisher 信息）与 `_weibull_percentile_ci()`（对数尺度 delta 法）；新增 B10 与寿命百分位表（B1/B5/B10/B50 + 95%CI）；口径经 `weibull_method` 披露 | `tests/engine/test_weibull_censored.py` 20 项；**实测（300 样本、独立删失 ~42%）朴素 η 误差 ~28%（75 vs 真值 100）→ 本实现 ~5%（95）**；无删失时与 scipy 逐位一致 |
| 2026-09-24 | **P3-6** PR 门禁分层 | `.github/workflows/ci.yml` quick job：新增 `tests/security/`、`tests/crossval/`、`tests/golden/` 三个步骤，并把集成测试从 2/8 文件扩到 7/8（`test_web_e2e.py` 仍由 e2e job 覆盖）。实测增量约 20 秒 | 新增 `tests/scripts/test_ci_layer_coverage.py` 10 项守卫（由目录结构推导覆盖要求）；quick 等价命令实测 **1621 passed / 3 skipped** |
| 2026-09-24 | **P3-4** 前端分类学守卫 | `tests/guards/test_frontend_taxonomy.py`：`_noTargetNeeded` ↔ 后端 `NO_TARGET_TASKS` 严格相等；三组集合的键必须是已注册任务；`NO_DATA_TASKS` ⊆ 免列集合；两组启发式互斥 | 11 项；**变异验证**：从前端移除 `power_analysis` → 2 项 FAIL（还原后全绿） |
| 2026-09-24 | **P3 教科书独立复算**（阶段 P3 首个产物） | 新建 `tests/golden/test_spc_msa_golden.py`：从 Montgomery/AIAG/ASTM 公式**独立推导**的参考值，覆盖此前无独立复算的四类：X-bar/R 控制限（A2/D3/D4 常数手工录入）、CUSUM 递推、EWMA 时变控制限、Gage R&R 方差分量 | 26 项；含"常数表错位防线"（反解 A2 序列须匹配教科书）与 `#SV` 表/元数据自洽检查 |
| 2026-09-24 | **文档守卫缺口**（金标准层附带发现） | `verify_docs.py` 的 `_recursive_dirs` 只覆盖"已声明至少一个子项"的目录 → **新建目录的第一个文件永远漏网**（实测：新增 `tests/golden/` 时该检查无任何输出）。补兜底规则：代码根下、位于未递归子目录内的 `.py` 亦须登记 | `test_verify_docs.py` 新增 4 项自测；**变异验证**：真实仓库建一个未登记的探针目录与 `.py` → 被检出；正常状态零噪音 |
| 2026-09-24 | **P3 参考值装载器**（把"未锚定"记录在案） | `tests/golden/_loader.py` + `reference.json`（schema + 空占位）+ `test_reference_loader.py`。设计：**参考值与测试解耦** —— 有值时自动对账进 PR 门禁，无值时 skip 且**局限显式登记**在 `UNANCHORED_METHODS`（10 项，逐条写明具体缺什么依据），有断言防漂移。**注意：本表记录的是局限，不是待办**（见 P3.2 决策） | 19 项自测；**实测 skip 机制**：临时探针验证缺失参考值时 SKIPPED 且原因精确到 `process_capability/injection_process/cpk`；`independence` 级别非法时 `load_reference()` 报错（防虚假标注） |
| 2026-09-24 | **第三方工具验证：放弃**（P3.2 决策修订） | 先做了"引入 R 一次性生成参考值"的评估，**随后用户决定放弃该路线**。据此清除所有"装某工具生成参考值"的待办表述与工具名；装载器改为**工具中立**（`external-tool` / `independent-implementation` / `hand-transcribed` / `none`），缺口清单更名为 `UNANCHORED_METHODS` 并改述为**局限记录**（非待办）。保留 `capability.py:36` 对某软件包口径的**文献引用**（论证依据，非验证依赖） | 新增 2 条**决策锚点**断言：`test_no_third_party_tool_pending_work_left`（loader/reference.json 不得残留工具名，字符串拼接构造以避免自指）与 `test_registry_reasons_are_not_pending_todos`（缺口说明不得含"待生成/待引入"等待办措辞）。golden 层 43 项全绿 |
| 2026-09-24 | **P3-3 前置：门禁扩容**（关键顺序） | `verify_frontend_params.py` 原先**只读 `app.js` 单文件**。一旦把 `TASK_PARAMS` 拆到新模块，该门禁会**静默失效**（找不到标记或在别处误匹配）—— 属"借道绕过"。改为拼接 `static/*.js` 全部文件，并新增**重复标记检测**（同一标记出现在多文件即报错，防拼接后仅首个生效）。同理扩了 `test_web_ui_guards.py` | 自测从 17 → 23 项；`test_web_ui_guards.py` 10 → 22 项。**先扩门禁再动代码**是唯一正确的执行顺序，本轮再次验证：搬迁后门禁输出 `static/*.js（5 个文件）` 仍在校验 `TASK_PARAMS` |
| 2026-09-24 | **P3-3 前端模块化** | 933 行单文件拆为 5 个 ES module：`util.js`（转义/数值/toast）、`api.js`（CSRF+fetch）、`state.js`（列数据/选择/上传/渲染）、`params.js`（参数系统，原 186-760 行）、`app.js`（分析执行链+事件委托）。**11 处内联 onclick 全部改为 `data-action` + document 级委托**；`index.html` 入口加 `type="module"`；**CSP 的 `script-src` 去掉 `'unsafe-inline'`**（安全收益，用断言锁住） | 新增 `scripts/check_js_modules.mjs`（Node 静态解析：具名导入必须真实存在、相对路径可达、无循环依赖）—— **变异验证**：把 `showToast` 改成 `showTost` → FAIL 并列出可用导出名。新增 `tests/scripts/test_frontend_modules.py` 10 项（Node 缺失时 skip 第 1 层、第 2 层 MIME 始终跑） |
| 2026-09-24 | **P2-1 Gage R&R ANOVA 方差分解** | `engine/reliability.py` 新增 `_anova_variance_components()`：交叉设计四项分解（部件/操作员/**交互**/重复性）+ F/p + Satterthwaite 有效自由度的 95% CI + 交互不显著时的 **pooled 口径**。接入 `gage_rr`：新 `gage_rr_anova` 表、`anova_*` metadata 六项、交互显著性消息。**均值-极差法保留并与之并列**（不替换，便于对照与追溯） | 新增 `tests/engine/test_gage_rr_anova.py` 27 项，含**无偏性标定**（40 次 MC，四分量偏差 ≤2.4 个标准误）、F 检验第一类错误率、池化逻辑一致性、**交互占主导时均值-极差法低估总方差 56%**（0.4512 vs 真值 1.03，ANOVA 1.0721）。顺带修两处既有弱断言（`test_edge_cases.py`、`test_capability_spc_guards.py` 的 AV 用例改为与 ANOVA 分量直接对账） |
| 2026-09-24 | **P2-3 ANOVA Type III 平方和** | `engine/root_cause/anova.py` 新增 `ss_type` 参数（2/3，默认 2 保持向后兼容）+ `_parse_ss_type()` 严格解析；Type III 走**安全内部列名 + `C(name, Sum)` 效应编码**，表行标签映射回与 Type II 相同的 `Q('col')` 形态。新增 `metadata.ss_type/ss_type_name/design_balanced/cell_sizes` 与不平衡披露消息；`task_spec` 注册默认值；前端 `params.js` 加 `ss_type` 下拉 | 新增 `tests/engine/test_anova_ss_type.py` 25 项。**关键发现**：statsmodels 的 `anova_lm(typ=3)` **不会**自动改用效应编码 —— treatment 编码下数值是错的（实测平衡设计 a 的 SS：3.1962 vs 正确 3.7398；不平衡设计 2.0283 vs 3.4159）。另有"结论翻转"夹具（Type II p=0.021 显著 / Type III p=0.079 不显著，扫描 400 个设计筛出） |
| 2026-09-24 | **P2-5 子组/池化 within-σ + Pp/Ppk CI** | `engine/capability.py` 新增 `_pooled_within_sigma()` 与 `_pool_groups()`：`subgroup_col`（按列池化，**不受行序影响**）/ `subgroup_size`（按行序切子组）/ 默认移动极差法三选一；`_cp_confidence_interval` 与 `_cpk_confidence_interval` 增加 `dof` 参数以复用于 Pp/Ppk（避免两份公式漂移）。新增 `metadata.within_sigma_method / pp_ci / ppk_ci`；`task_spec` 注册两个新参数；前端加中文标签 | 新增 `tests/engine/test_capability_subgroups.py` 26 项：池化 σ **逐位对拍闭式解**、行序不变性（并对照 MR 法**确实**受行序影响）、两路径互证、5 类边界拒绝（列不存在/单组/含单观测组/两者同给/尺寸非法）、**Pp CI 覆盖率实测 800 次**。**附带修一个真 bug**：Cpk<0（均值在规格外）时下限被钳到 0 → **高于点估计**且上下限颠倒（实测 Cpk=−6.19 → CI=(0.0, −5.25)），改为按点估计符号决定钳位方向 |
| 2026-09-24 | **P3 教科书层二期** | 新增 `tests/golden/test_methods_golden.py`：为 P2 阶段新增的四项方法 + 一个附带修复补**独立复算** —— Gage ANOVA 方差分解（教科书 SS 公式逐项算）、**ANOVA Type III（两条独立代数路径：模型 SS 差 vs Frisch–Waugh–Lovell 残差对比）**、池化组内 σ（闭式解）、Pp/Ppk CI（χ² 分位数直接构造）、Cpk<0 的区间钳位回归 | 30 项，含 4 项**参考实现自检**（SS 分解必须精确闭合、池化公式在单组时退化为样本标准差、两条 Type III 路径必须彼此一致）。**独立确认了第六轮的编码修复**：两条独立路径与引擎的 Type III 完全一致（treatment 编码的错误值会被任一路径否定） |
| 2026-09-24 | **A6 补测：413 的 HTTP 路径**（第九轮独立复测发现） | 独立复测脚本 `logs/reports/verify-round3/final_audit_check.py` 在**原审计指出的位置**逐项实测 8 条断言，发现 A6 的真实缺口：`tests/security/` 里**确实没有** 413 测试（原审计记为"部分属实"，我此前未补）。新增 3 项：JSON 413 + 中文提示、超限在解析前拒绝、**CSRF（403）与超限（413）两条防线互不掩盖**。实测确认 413 的 JSON 处理**早已正确**，缺的只是覆盖 | **9/9 独立确认已修**（脚本 exit 0）。复测脚本自身首版有 **3 处误判**，全部修正：① 函数名记错（`spc_xbar` vs `xbar_r_chart`）② 探针漏带 CSRF token 导致拿到 403 而非 413 ③ 日期判据未排除**引用块**（手册里那句"旧版曾声称 验证日期: 2026-07-08"是**警示文本**，被误读为当前主张）。**教训：检查脚本本身也需要自检** |
| 2026-09-24 | **本轮补跑 `verify_all.py`** | 该脚本是本计划自己定义的收口门禁，但前八轮**只跑了它包含的单项，从未跑过它本身**。实测全通过（构建 / 测试 / mypy / 文档 / falsy 审计 / 质量守卫 6 步）。它额外覆盖 `compileall` 与 `falsy_audit` 两步，是我此前未单独验证的 | `[OK] 全量验证通过`（见 `logs/reports/verify-round3/verify_all-r9.txt`）。教训：**计划里写下的验收命令要真的执行，不能只执行"看起来等价"的子集** |
| 2026-09-24 | **P4 阶段2 第一步：声明式参数契约** | 新增 `src/smartsuite/core/param_spec.py`：`Spec` + `Req`/`Opt` 字段 + 6 个校验器（`Finite`/`Integer`/`Choice`/`Text`/`Custom`）+ `CrossRule` 跨字段规则 + `ValidatedParams` 内省（`defaults()`/`labels()`/`hints()` —— 将来是五份平行字典的唯一来源）。**双轨期只新增不改引擎**（按计划"逐任务迁移，两套并存"） | 新增 `tests/core/test_param_spec.py` **55 项**。**错误码按原因分离**（这是 P0-1 错误归因的根治）：`NOT_NUMERIC` / `NOT_FINITE` / `OUT_OF_RANGE` / `NOT_INTEGER` / `NOT_IN_CHOICES` / `EMPTY_TEXT` / `TEXT_TOO_LONG`。**`None` 语义与引擎对齐**（`None` = 未提供 → 用默认值），依据是引擎的 `DEFAULT_PARAMS` **有意注入 `None`** 并据此走 fallback（`reliability.py:378` 有注释为证）。顺带修实现里一个 `used_defaults` 缺陷（只记"没传"，漏了"显式传 None"） |
| 2026-09-24 | **工具启发式的边界（值得记录）** | 质量守卫把 `assert err is not None` 这类行判为"弱断言"，即使同一方法里紧跟 `assert err.code == \"NOT_FINITE\"`。本轮我一度为迎合它而**过度调整测试结构**（甚至写了一个与前两条重复的表驱动用例），随后回退 —— 因为**为工具输出改测试结构是本末倒置**。最终：删掉真正冗余的 `is not None` 守卫（25 → 2 条 WARN），余下 2 条保留并在此说明原因 | 门禁判据是 **FAIL 数 = 0**（实测 0），WARN 不阻断。教训：**WARN 是提示不是命令**；若为消除提示而让测试变差，应停手并记录 |
| 2026-09-24 | **P4 步骤②：迁移 `process_capability`（范式）** | `engine/capability.py` 新增 `PARAM_SPEC`（6 字段 + `usl>lsl` 交叉规则），把约 **55 行手写的 `try/float/isfinite` 重复块**（usl/lsl/target 各一遍、每遍两个错误分支）替换为一次 `PARAM_SPEC.validate()`。同时**删除引擎里重复的 `USL ≤ LSL` 手写校验**（现为 Spec 的交叉规则；保留两份会漂移） | 新增 `tests/engine/test_capability_param_migration.py` **45 项**，含**迁移前行为快照**（锁定全部拒绝路径的确切文案）与**对拍用例**（11 组输入上 `Spec` 与引擎判定必须一致）。测量：`capability.py` 的 `status="error"` **12 → 6**（-50%）、全引擎 **287 → 281**。剩余 6 处全是**依赖数据**的检查（样本量/恒定列/子组结构），按设计留在引擎走 `_guard.py` |
| 2026-09-24 | **P4 步骤④（第十四轮）：删除前端 `TASK_PARAMS`（42 任务默认值）** | 前端 `params.js` 原有 45 行 `TASK_PARAMS` 字面量，与后端 `task_spec.py::TASK_SPECS` 的 `default_params` **逐字重复**，靠 `verify_frontend_params.py` 每次门禁比对维持一致（典型的手工一致性）。现改为：`/api/tasks` 新增 `params` 字段下发 `DEFAULT_PARAMS` → `app.js` 启动时 `fetch` → `hydrateParams()` 灌入 `params.js` 的缓存。**前端 `params.js` 净减 45 行数据**，后端成为唯一事实源，**结构上不可能不一致** | 新增 `tests/integration/test_api_tasks_params.py` **13 项**（含"下发值与 `DEFAULT_PARAMS` 逐任务逐键一致"、"无参数任务下发 `{}` 而非缺失"、"前端不得再出现非空字面量"）。门禁 `verify_frontend_params.py` 重构为**双模式**：`js_path` 指定时保留历史比对逻辑（供合成样例自测），缺省时改查**单一来源架构**（无副本 + 真的调用了 `hydrateParams` + `/api/tasks` 真的下发 `params` + 仍存在的 `INVERSE_PREFIXES` 重复与引擎一致）。门禁自测 4 项按新架构改写（**未删除**，意图保留） |
| 2026-09-24 | **本轮修复的两个自身缺陷（值得记录）** | ① **竞态**：`/api/tasks` 是异步的，若用户在响应到达前就点任务，`hasParams()` 返回 `false` → 面板不显示、直接用引擎默认值开跑（用户以为"该任务没有参数"）。加了 `paramsReady()` 就绪 Promise，点击处理先 `await`。② **误报**：检测"前端又有副本"的正则首版把 `let TASK_PARAMS = {};`（空缓存初始化）和 `TASK_PARAMS = params;`（运行时灌入）都当成违规 —— 而这两种**正是新架构本身**。改为要求字面量**非空**（`\{[^}]+\}`），并立了对照用例钉住 | 教训：**"删除副本"类改动的检测逻辑必须先证明它不会误报新架构的正常形态**。两处都在文档与测试中显式记录 |
| 2026-09-24 | **P4 步骤④续（第十五轮）：参数标签/提示派生通道** | 新增 `services/param_labels.py`：`derive_param_labels()` / `derive_param_hints()` 从各任务的 `PARAM_SPEC`（`Opt(..., label=..., hint=...)`）派生标签与提示，经 `/api/tasks` 的 `param_labels` / `param_hints` 字段下发。**键名不叫 `labels`** —— 那个已被**任务**标签（`TASK_LABELS`）占用，复用会破坏任务按钮渲染。前端改为 `paramLabel()`/`paramHint()` 两个**接口优先、旧字典兜底**的查找函数（`接口 → 手写字典 → PARAM_META.label → 键名`） | 新增 `tests/integration/test_api_tasks_param_labels.py` **20 项**。**关键设计：作用域**——前端查找是 `PARAM_LABELS[k + "@" + task] \|\| PARAM_LABELS[k] \|\| k`，即存在任务级覆盖（`method` 全局"异常检测方法"、`doe_design` 下"设计方法"）。派生逻辑两遍走：值一致→只存全局一条；有冲突→逐任务 `name@task`。该逻辑用**假 Spec** 直接驱动测试（端到端用例走不到冲突分支） |
| 2026-09-24 | **本轮的关键决策：字典暂不删，并量化了原因** | 实测派生覆盖率：`PARAM_LABELS` **7/86**、`PARAM_HINTS` **0/9**（因只有 2/42 任务有 `PARAM_SPEC`）。**此时删字典会丢 79 条标签**（UI 退回英文参数名），属 UX 回归。故本轮只**建通道 + 接线**，把删除推到步骤③ 覆盖之后 —— 那之后删字典**无需再改前端查找逻辑**。该数字已写入计划 §六 步骤④ 行 | ⚠️ 首版测量脚本用 `(?:'([\w@]+)'\|(\w+))\s*:` 匹配全文，把提示文本里的 `格式: ...` / `料温:180,220` 也当成了键（出现"格式"/"料温"等**假键**，虚报为 17 条提示）。改为要求键在**行首或 `, ` 之后**才统计正确。**教训：量化脚本本身也要先验证提取正确性，否则会基于假数据做决策** |
| 2026-09-24 | **P4 步骤③（第十六轮）：迁移 `power_analysis`** | `engine/root_cause/design.py` 新增 `PARAM_SPEC`（9 参数 + 2 个自定义校验器 `_nonzero_effect` / `_open_unit`），替换约 **70 行分散手写校验**。**收敛掉三处真实冗余**：① `alpha` 区间检查**写了两遍**；② `n_groups` 的同一检查**写了四处**（三条模式分支 + 功率曲线分支各一份）；③ `p0`/`p1`/`n_groups` 在多个分支**反复重读**（各 3 次）。迁移后 `design.py` **无任何 `req.params` 直接读取** | 新增 `tests/engine/test_power_analysis_param_migration.py` **50 项**。**测量：该文件早退 17 → 7**（-59%），全引擎 **287 → 273**。**对拍抓出我 3 处错误**：① `current_n` 默认值我写 `None`，实际 `DEFAULT_PARAMS` 是 **30**；② `p0`/`p1` 我写成闭区间 `[0,1]`，实际既有行为是**开区间** `(0,1)`；③ 我误以为 `p0 == p1` 合法，实际有专门检查拒绝（零比例差无意义）。三处都由"与既有行为对拍"的用例抓出，**没有一处流到线上** |
| 2026-09-24 | **本轮的错误消息改进（由既有测试的断言发现）** | 既有测试断言 `"effect_size" in m`（**参数名**），而 `Spec` 的消息只含中文标签（「效应量」）。这暴露一个真实缺口：**CLI / YAML 模板 / 日志里只有英文键名**，`grep effect_size` 必须能搜到，只给中文标签会让命令行用户无法定位。故 `_format_field_message` 改为在标签后附参数名（`参数「效应量」(effect_size) 不能为 0…`），但**标签已含 ASCII 缩写时不重复**（避免 `「规格上限 (USL)」(usl)` 这类冗余） | 该改动影响所有任务的错误文案，已跑全量确认无回归。**记录要点：既有测试的断言常蕴含我未考虑到的使用场景**——这条断言看似"过时"，实则指出了真实缺口 |
| 2026-09-24 | **P4 步骤④前置（第十七轮）：`Choice` 支持选项显示文案** | 补上 `Spec` 的一处**表达力缺口**：原本能声明参数名/标签/提示/可选值，但**不能声明"每个可选值显示什么"**—— 这正是前端 `PARAM_META`（169 行，最后一份大重复）的 23 条 `select` 无法派生的原因（引擎侧只有 `_SUPPORTED_SS_TYPES = (2, 3)` 这类裸值）。现 `Choice` 接受 `(值, 文案)` 候选项：`Choice((2, "Type II（引擎默认）"), (3, "Type III（Minitab/SAS 默认）"))`，并加 `options()`；未写文案的值回落到 `str(值)`（避免为 `p`/`np`/`c`/`u` 硬写文案） | 新增 `tests/core/test_param_spec_choice_options.py` **15 项**；`/api/tasks` 新增 `param_options` 字段（+11 项集成测试），前端查找链接入（接口 → `PARAM_META.options` 兜底）。**给 `power_analysis` 的 `mode`/`test_type` 补了选项文案**，让特性立即产生用户可见价值 |
| 2026-09-24 | **⚠️ 本轮抓到一个我自己引入的功能回归（重要）** | 我最初让选项复用标签那套"值一致就下发全局键"的策略。测试 `test_global_options_never_leak_to_a_different_task` **立刻抓出泄漏**：当时只有 `power_analysis` 迁移了 `mode`，被当作"无冲突"下发全局，导致 **`box_chart.mode`（箱体图布局 `facet`/`overlay`）也渲染出 `required_n`/`achieved`** —— 用户会被提供引擎不认的值。 | **修正：选项一律逐任务作用域化（`name@task`），不设全局兜底。** 理由写入代码注释：**标签/提示搞错只是显示难看**（`alpha` 在 9 个任务里都叫"显著性水平 α"）；**选项搞错是功能错误**。实测有 **12 个参数名被多任务共用**（`alpha` 9 个、`group_col` 8 个、`method` 3 个语义完全不同）。这也说明"复用看似等价的策略"是风险点 —— 两类数据的**错误代价不同**，处理方式就该不同 |
| 2026-09-24 | **P5（第十八轮）：Web 报告导出入口** | 补上一个**产品级缺口**：`reporter.to_html/to_pdf/to_ppt` 与 `audit.export_workbook` 此前**只有 Python API 能用**（CLI 只有 `run`/`list`，Web 无导出端点，我实测确认 `to_html` 等无任何 CLI 调用点）—— 用户跑完分析**拿不到报告文件**。新增：① `services/reporter.py::export_report(result, fmt, path, ...)` 分发器（三种 reporter 签名各异，且 `xlsx` 走另一个模块、粒度也不同，故在桥接层收一处）；② `EXPORT_FORMATS` 格式白名单（扩展名 + MIME 单一事实源）；③ `/api/export` 端点，下载自包含 HTML / PDF / PPT / 多 Sheet Excel | 新增 `tests/integration/test_report_export.py` **21 项**（分发器 15 + 端点 6：附件下载、需先上传、需 CSRF、未知任务、非法格式、分析失败返 400 非 500）。**`xlsx` 的粒度差异已如实处理**：它按 DataFrame + 列信息**自行重跑**全部任务（每任务一个 Sheet），故分发器要求显式给数据与列，缺失时**明确拒绝**而非抛底层异常 |
| 2026-09-24 | **本轮修掉的 3 个自身缺陷（都由测试抓出）** | ① **CSRF 装饰器漏加**：`/api/export` 是写操作却没加 `@require_csrf`，被 `test_export_requires_csrf` 抓出；② **参数解析掩盖鉴权**：首版用 `get_json(silent=True) or {}`，导致"没带 JSON"与"JSON 是空对象"无法区分，无 token 的探测请求先撞 400（参数缺失）而非 403（鉴权）—— 改为 `force=True` 并显式处理 `None`；③ **临时文件句柄泄漏**：用 `send_file` 送临时文件触发 pytest 的 `UnraisableExceptionWarning: Exception ignored in FileIO`，改为"写临时目录 → 读回内存 → 立即删目录 → `make_response`"，临时文件本就不该留下 | 另修 3 处**我测试自身的问题**：上传未带 CSRF token、`jsonify` 转义非 ASCII 导致中文断言失效（需先 `json.loads`）、`xlsx` 用例漏传 `df`。**教训重复出现：`jsonify` 默认把中文转义为 `\uXXXX`，断言中文必须先解码** —— 这在本项目已出现多次 |
| 2026-09-24 | **P5.3（第十九轮）：前端导出链路半运行时冒烟** | 上一轮新增的导出按钮当时只有**静态文本断言** —— 等于"从未执行过那行代码"。计划里写的是 Playwright，但**本环境未安装且安装需下载浏览器**（离线不可行）。折中：新增 `scripts/check_export_flow.mjs`，用 Node + 最小 DOM 桩**真实加载 `app.js`**，调用其导出函数并断言行为（事件委托接线、fetch 请求体、Content-Disposition 解析、Blob 下载与 `revokeObjectURL`、失败分支显示服务端原因）。**比静态断言强得多，比浏览器弱** —— 这一界限写进脚本头部注释，不冒充浏览器测试 | 新增 `tests/scripts/test_export_flow.py` **4 项**（含"脚本本身不得被掏空"与"若将来装上 Playwright 则本用例失败以提醒升级"）。为可测性把导出链路里的纯逻辑提取为 `parseDownloadFilename` / `downloadBlob`，并加 `rememberRequest` 作为 `_lastRequest` 的**唯一写入点**（顺带消除"多处各自赋值 → 报告反映上一次参数"这类隐患） |
| 2026-09-24 | **冒烟测试抓出的真实缺陷 + 一次自我修正** | ① **`parseDownloadFilename` 首版漏了 RFC 5987 的无引号形态**（`filename*=UTF-8'x.pdf`）：我按"带引号"写正则，冒烟用例直接报错定位。虽然不是当前后端会产出的形态（werkzeug 用 `filename="x"`），但**换了服务器或过一层反代就会踩到**。② 我第一版冒烟脚本试图用 `data-action` 委托驱动成功路径，但 `_lastRequest` 是模块私有状态、无法从外部设置 —— 于是把 `_lastRequest` 的赋值收敛为 `rememberRequest()` 导出函数（这是**正当**的状态管理入口，不是 test-only 后门） | 两次修正都不是"为了让测试通过"而改断言，而是**改进了生产代码**：`downloadBlob` 提取后 blob 释放路径更清晰，`rememberRequest` 消除了多写入点隐患。这符合"测试驱动设计"的初衷 |
| 2026-09-24 | **第二十轮里程碑复盘：换方法（这是本轮最有价值的产出）** | 复盘实测：**42 个任务里只有 7 个有 `PARAM_SPEC`**，而计划总预算 40 轮 —— 按"每轮手工迁一个"**不可能达成目标**。复盘同时找到可批量化的证据：`DEFAULT_PARAMS` 的 **114 个参数槽位里只有 83 个不同参数名**（`alpha` 9 次、`group_col` 8 次、`usl/lsl/target` 各 3 次、`ci_level/random_state/method` 各 3 次）。**结论：不改节奏就必然失败，故改方法** —— 建 `core/param_specs_common.py` 共享字段库，迁移从"重写声明"变为"引用常量" | 新增 `tests/core/test_param_specs_common.py` **16 项**、`tests/engine/test_param_migration_batch1.py` **66 项**（4 个任务一次迁完）。实测该批次：`contingency`/`normality_check`/`median_ci`/`variance_test` 全部完成，全引擎早退 273 → **271** |
| 2026-09-24 | **P4 步骤③ 第三批（第二十一轮）：再迁 4 个任务** | 用第二十轮建的共享字段库继续批量推进：`doe_analysis`（引用 `ALPHA`）、`trend_forecast`、`vif`、`distribution_summary`。**已迁移任务 7 → 11**，全引擎早退 271 → **269**。顺带消除两处重复：① `doe_analysis` 的 `alpha` 原在**因子循环内部**读取并校验（每个因子重读一遍），现提到循环外一次取用 —— 既消除重复，也让「alpha 非法」立刻失败而非跑到第一个因子；② `trend_forecast` 的 `int(steps)` + 两段区间检查（约 16 行）收敛为 `Integer(min=1, max=1000)` （且**拒绝小数** —— 原 `int(5.5)` 会静默截断为 5） | 新增 `tests/engine/test_param_migration_batch2.py` **60 项**。**先取证再改**：迁移前实测 `bins="abc"` → `status=ok`（静默回落自动分箱）作为基线，已写入测试文档 |
| 2026-09-24 | **P4 步骤3 第四批（第二十二轮）：一轮迁 5 个任务** | `decision_tree`（引用 `RANDOM_STATE`）、`proportion_ci`（引用 `CI_LEVEL`）、`quantile_regression`、`response_surface`、`change_point`。**已迁移 11 -> 16**，全引擎早退 269 -> **268**（本批多为单参数任务，收敛行数有限） | 新增 `tests/engine/test_param_migration_batch3.py` **69 项**。顺带：`response_surface` 的 `direction` 从「白名单检查 + 手写错误文案」改为 `Choice`，**并带上可选值的中文文案**供下拉框显示（前端不必再另抄一份选项） |
| 2026-09-24 | **P4 步骤③ 第五批（第二十三轮）：一轮迁 5 个任务，早退降幅最大** | `correlation`、`logistic_regression`、`spc_nonparametric`、`spc_cusum`、`spc_ewma`。**已迁移 16 -> 21**，全引擎早退 268 -> **258**（**单轮 -10**，是至今降幅最大的一轮 —— 因为本批含 `spc_cusum`/`spc_ewma` 两个校验密集模块：前者原有 `float()` 转换 + 四段检查约 40 行，后者约 24 行，现各由一次 `validate_or_raise` 表达） | 新增 `tests/engine/test_param_migration_batch4.py` **75 项**。`spc_cusum`/`spc_ewma` 的 `mu`/`sigma` 是**可选显式覆盖**（不在 `DEFAULT_PARAMS` 里），故 Spec 声明得比默认值表多 —— 对拍断言据此**精确化**为「缺省键必须一致 + 多余键必须是默认 None」 |
| 2026-09-24 | **P4 步骤3 第六批（第二十四轮）：一轮迁 5 个任务** | `lasso_regression`、`multi_objective`、`anomaly_detect`、`anova`、`grid_search`。**已迁移 21 -> 26**，全引擎早退 258 -> **253** | 新增 `tests/engine/test_param_migration_batch5.py` **89 项**。`anova.ss_type` 用 `Choice` 并保留 `"2"/"3"` **别名**（原 `_parse_ss_type` 明确接受字符串写法，只写 `Choice(2,3)` 会让 `"2"` 被拒 —— 那是行为回归） |
| 2026-09-24 | **P4 步骤3 第七批（第二十五轮）：一轮迁 5 个任务** | `spc_xbar`（**零专有声明** —— 4 个参数全来自共享库）、`scatter_plot`、`tolerance_interval`、`bootstrap_ci`、`gage_rr`。**已迁移 26 -> 31**，全引擎早退 253 -> **248** | 新增 `tests/engine/test_param_migration_batch6.py` **113 项**。`spc_xbar` 的 `usl`/`lsl` 原由**动态键循环**读取（`req.params.get(spec_key)`），迁移后改读 Spec 结果，语义不变 |
| 2026-09-24 | **P4 步骤3 第八批（第二十六轮）：迁 2 个大任务，步骤3 基本收口** | `box_chart`（9 参数）、`hypothesis_test`（5 参数，**17 种检验类型**）。**已迁移 31 -> 33**，全引擎早退 248 -> **244**。**剩余仅 3 个**：`doe_design`(8)、`inverse_solve`(18)、`regression`(死参数待决策)；另有 6 个任务 `DEFAULT_PARAMS` 为空（`cohens_kappa`/`cronbach_alpha`/`roc_analysis`/`robust_regression`/`outlier_consensus`/`survival_analysis` —— 无可迁参数） | 新增 `tests/engine/test_param_migration_batch7.py` **73 项**。**`hypothesis_test` 的 `alpha` 原在 14 个分支各读一次**（重复读取+转换），现只在函数开头取一次；`test` 的 17 种取值与前端 `params.js` 的中文文案一致，并由 `test_test_type_set_matches_engine_whitelist` 与引擎白名单**双向钉住** |
| 2026-09-24 | **P4 步骤3 收尾（第二十七轮）：最后 3 个任务，步骤3 完成** | `doe_design`(8 参数，完整迁移)、`inverse_solve`(18 参数，**只声明不校验**)、`regression`(1 个透传)。**已迁移 33 -> 36/36**，全引擎早退 244 -> **241**。**关键里程碑：派生标签覆盖 114/114 个默认参数槽位（无缺口）** | 新增 `tests/engine/test_param_migration_batch8.py` **72 项**，其中 `test_every_default_param_slot_has_a_derived_label` 是**步骤④ 的前置断言** —— 只要有一个槽位没被派生覆盖，删前端字典就会让那个参数在界面上没有标签 |
| 2026-09-24 | **P4 步骤4 完成（第二十八轮）：删掉前端全部手写平行字典** | 删除 `PARAM_LABELS`(36 行) + `PARAM_HINTS`(11 行) + `PARAM_META`(167 行) = **214 行**；`params.js` 684 -> **451 行**。参数标签/提示/选项全部改为后端派生下发。保留 `COLUMN_PARAMS`（4 个列选择器）—— 它是**纯 UI 关注点**：「该选哪一列」取决于运行时加载的数据列，`Spec` 无从知晓，也不属于「与后端重复的事实」 | 新增 `scripts/check_params_panel.mjs` + `tests/scripts/test_params_panel.py`（**9 项**）—— 用 Node + DOM 桩**真实加载** `params.js`，载荷由 Python 的 `derive_param_*` **真实生成**。**为什么必须做半运行时冒烟**：静态文本断言无法证明「删了字典后面板还能渲染」—— 而「字典删了、派生漏了、参数在界面上变成英文键名或退化成文本框」正是本步骤的最大风险，且那种情况下测试会全绿 |
| 2026-09-24 | **style-src 收紧完成（第二十九轮）：CSP 不再有任何 unsafe-inline** | 关键认知：**CSP3 起 `style-src` 的 `'unsafe-inline'` 同样覆盖行内 style 属性** —— 要收紧它就必须先把行内样式改成 class。全仓实测只有 **7 处**需要改（模板 3 + app.js 4）：display:none 三处 → `.is-hidden`；错误提示色三处 → `.empty-hint.is-error`；矩阵按值着色一处 → `.cell-strong`/`.cell-normal` 两档；分组背景色一处 → 5 个静态 `data-group` 规则。**CSP 终态：default-src self；img-src self + data:；style-src self；script-src self；frame-ancestors none** | 顺带修掉 3 处 JS 联动：原用 `element.style.display` 判可见性（读的是**内联**值），改 class 后那 3 处判定会**静默失效**（面板该显示时不显示）→ 一并改为 `classList.contains('is-hidden')`。另：引擎侧 `style=` 多在 matplotlib 代码里（渲成 PNG，与 CSP 无关），`_serialize_table` 产出 JSON 而非 HTML —— 故真实风险面只有那 7 处 |
| 2026-09-24 | **三个待决策项全部落定（第三十轮）** | ① **`regression.model_type`：我此前判错了**。取证 api-reference.md 明写「保留参数，当前仅支持 OLS」—— 引擎不读它是**有意设计**，不是缺陷（我第二十四轮记成「未接线的参数（缺陷）」属**误判**）。真正的毛病是我第二十七轮写的界面文案：标签「回归模型类型」暗示可选，提示里还有「台账」这种**内部词**。已改为「模型类型（保留）」+ 面向用户的诚实说明。② **`gage_rr.tolerance`：补实现 %P/T**。取证 api-reference.md 列出它、docstring 写「用于 %P/T 计算」，但 AST 扫描证实从不被读。按「文档已承诺→补实现」处理。③ **`show_ci`/`show_stats`：修根因**（见下条） | ② 的公式**经权威出处核实**：JMP《Gauge RR Option》——「a % of Tolerance column ... computed as 100*(Variation/Tolerance)」，其中 Variation = k·σ（k 默认 6）。故 %P/T = 100·(6·σ_GRR/公差)，**分子取 GRR 的 σ**（不是总变异 σ）——我最初按另一种流派的定义写，核实后确认用 σ_GRR。判定改为**取 %GRR 与 %P/T 中更差者**（AIAG 对两者用同一套阈值） |
| 2026-09-24 | **P1「错误归因」治理（第三十一轮）：从病因断言改为两支建议** | 审计点名的「错误归因」根因在 `services/error_messages.py`：12 条映射把异常类型逐一翻译成**确定的病因断言**（例如「数值溢出，数据中可能存在极端值」「数据可能存在常数列」「请确认数据列名和格式正确」）。但同一异常类型在引擎里可能多种成因，其中相当一部分**与数据无关**：`OverflowError` 也可能是 `math.gamma(n)` 在 n≥380 溢出（**子组大小**问题，历史上正是这样把 n 的问题误报成数据有极端值） | 改法：每条先说**现象**（中性、可核对），再给**两支行动**，并用稳定标记分流 ——`[数据] …请检查…` 与 `[内部] …若数据正常则可能是引擎缺陷，请凭错误编号反馈`。`AttributeError` 直接标为「通常为引擎缺陷」并**删掉**「请确认数据列名」（它把内部对象类型错误说成了用户的列名问题）；兜底文案不再断言「请检查数据完整性」，改为如实说明成因未归类。新增 `tests/services/test_error_attribution.py` **47 项**（含端到端注入异常验证） |
| 2026-09-24 | **P1-6 边界披露：我先误报了一次，然后量出真相（第三十二轮）** | 为落实「一处声明、一处执行」，先统计手写边界处理：**138 处 / 26 文件**，但细分后真正的**清洗调用点只有 23 处 / 7 文件**（其余 115 处是内联 `np.isfinite` **数值计算**，不是清洗，不该迁移）。进一步我写扫描器核对「取出的剔除数量有没有被用到」，报出 **7 处静默清洗**（capability/exploratory/reliability/distribution） | **那 7 处是假阳性**：扫描器用**固定行窗口**（调用点后 40 行），而 `capability.py` 的 `n_inf` 在**第 369 行**被使用 —— 距调用点 **41 行**，只差一行就出了窗口。改用 **AST 作用域**判定后：**真实缺口 0**（23 处全部正确披露）。端到端实测确认：`⚠ 「y」含 3 个非有限值（±Inf 视为缺失），已剔除后分析`。**教训：报出缺陷前先确认扫描器本身没问题** —— 固定窗口是脆弱判据（一行的差距翻转结论），作用域才是正确粒度 |
| 2026-09-24 | **第①层补强：只用解析解（第三十三轮）** | 先实测了真值层的真实构成（此前只有「约 6%」这类估算）：约 1289 条数值断言中，具体数值真值 **97 条（7.5%）**、与另一实现比 151、弱界 84、同义反复风险 20、结构断言 **937**。故本轮补的不是更多断言，而是**更强的一类断言** | 新增 `tests/engine/test_analytical_truths.py` **17 项**，**完全不与另一个库比** ——只用解析解，因为「与另一实现比接近」查不出**两者共有的错误**。三类：① 退化情形（完美线性 → `R²=1` 且系数恰为 `(3,7)`；两组逐点相同 → `p=1`；`y=2x` → `r=1`；常量列 → 相关性无定义须拒绝）；② 闭式公式逐项对账（`Pp = 12/(6σ_overall)`；`%P/T = 6σ_GRR/公差`；Wilson / Clopper-Pearson 在 `p̂=1` 的闭式上下限；X-bar 控制限的对称式）；③ 只依赖**关系**不依赖数值（`Cpk ≤ Cp`、完全居中时 `Cpk == Cp`、`p` 随组间分离单调下降、`R²` 随噪声单调下降） |
| 2026-09-24 | **Minitab 对齐：实测推翻了计划里的原始判断（第三十四轮）** | 计划里本项写的是「能力/可靠性/GRR **有明显缺口**」—— 那是**初期印象**。逐项实测后实际情形是**对齐面很宽**：`XBR_CONSTANTS` 与 Minitab 标准控制图常数表**逐值一致**（n=2..10 的 A2/D3/D4 全对，含 `D3=0` 恰在 `n≤6` 这一结构性事实）；`Cp`/`Cpk`/`Pp`/`Ppk`/`Cpm` + 四个 CI、Gage R&R 的 ANOVA 表/方差分量/%Contribution/%SV/%Tolerance/ndc **全部已实现**且与公式对账；判定阈值对齐 AIAG | 交付两份：① `docs/governance/minitab-alignment.md` —— 口径对照表，**先说清可信度分级**（A=公开常数表、B=教科书闭式、C=AIAG 阈值、D=仅口径同名），并**明确声明本机未安装 Minitab**（不存在软件间数值对账，与 R 的处理同一原则）；② `tests/engine/test_minitab_alignment.py` **40 项** —— **一半断言「已对齐项不得退化」，另一半断言「已声明的缺口确实仍缺」**。后者是关键设计：对照表若只写已对齐，会随时间膨胀成宣传页；缺口与已对齐一样需要被维护 |
| 2026-09-24 | **`_guard` 收口：首个模块迁移完成 + 进度清单化（第三十五轮）** | 计划把本项标为 ⏳ 未达标（执行点已建，仅 `spc_xbar.py` 一处接入）。本轮迁移 **`capability.py`**：`drop_non_finite` + `non_finite_note` + `warn_msgs: list[str]` → `clean_series(report=...)` + `BoundaryReport` + `report.messages()`。**收益不止少写几行**：迁移后错误码在**一处**产出，`metadata` 新增 `boundary_codes`（机器可读，格式 `E_<域>_<原因>`）—— 迁移前只有中文文案，上游做分流只能对文案做子串匹配（脆弱且随文案改动失效） | 四类处置配了码：`E_DATA_NON_FINITE_DROPPED`（清洗）、`E_CAPABILITY_DATA_NOT_NORMAL`（B3 近似）、`E_CAPABILITY_SUBGROUP_SIGMA_CAVEAT`（口径假设）、`E_CAPABILITY_BOXCOX_FAILED` 与 `..._TRANSFORMED_SPEC_NONPOSITIVE`（B2 降级）。**先写 13 项行为锁定测试**（干净数据不得有清洗提示、±Inf 恰好一条披露含数量、常量列仍拒绝、样本量不足仍拒绝、子组提示的触发条件……），**迁移前后都必须通过** ——迁移是重构，正确性判据是「可观测行为一字不变」。迁移后 21 项全绿 |
| 2026-09-24 | **`_guard` 收口第二轮：又迁 2 个模块 + 通用断言清单化（第三十六轮）** | 迁移 `root_cause/modeling.py`（`clean_frame`）与 `root_cause/distribution.py`（`clean_series`），各配 `BoundaryReport` 与 `report.codes()`。`modeling.py` 新增码 `E_DECISION_TREE_OVERFIT_WARNING`。旧清洗调用点 **23 → 20**；已迁移模块 **4 个**，待迁移 3 个 / 20 处 | 新增**清单驱动的通用断言**（`TestMigratedModulesActuallyUseTheGuard`）：对清单里每个「已迁移」模块施加同一组结构断言（已导入 `_guard`、无旧清洗调用、无手写披露文案），故**迁移推进时不必新增测试文件**。另加一条防退化断言：清单里的模块名必须对应真实文件（否则参数化断言会跑 0 次而全绿） |
| 2026-09-24 | **`_guard` 收口第三轮：迁入 2 个模块，待迁移降至 1 个（第三十七轮）** | 迁移 `exploratory.py`（`median_ci` / `bootstrap_ci` 用 `clean_series`，`box_chart` 用 `clean_frame`，共 3 处）与 `reliability.py`（`gage_rr` 用 `clean_frame`，`tolerance_interval` 用 `clean_series`，共 2 处）。旧清洗调用点 **20 → 15**；已迁移 **6 个模块**，**待迁移仅剩 `root_cause/hypothesis.py` 一个模块（15 处）** | 本轮进展快的原因不是"批量改"，而是前两轮已把两件事做完：① 迁移清单 + 通用断言已就位（迁完只需改清单，测试自动跟随）；② `capability.py` 的迁移范式可复制。**清单驱动的断言在本轮又发挥作用**：迁完后立刻报出清单过期（声称 20 处、实际 15 处），把"忘了更新进度"变成一次测试失败而非静默偏差 |
| 2026-09-24 | **`_guard` 收口完成：7/7 模块，旧实现删除（第三十八轮）** | 迁移 `root_cause/hypothesis.py`（5 个函数 / 15 处 —— 全项目最大的面）后，旧清洗调用点 **15 → 0**。三个旧函数已从 `_utils.py` 删除，`tests/engine/test_utils.py` 的 4 个旧用例移除（等价行为由 `clean_series` / `clean_frame` 的用例覆盖）。**边界处理硬指标由 🔄 转为 ✅ 已达标** | 两处设计决策值得记录：① **每个清洗点自带一个 `report`，不跨分支共用** —— 起因是实测发现 `tests/engine/test_welch_ttest.py` 断言「方差齐性时 `messages == []`」，共用会把**未执行分支**的处置带进结果；② 迁移中用**行号锚定 + 倒序编辑**（而非字符串匹配）—— 前两次尝试因缩进/空格差异导致半迁移 + 文件损坏，只能 `git checkout` 重做。**教训：对缩进敏感的大文件，字符串匹配脆弱；行号 + 倒序才是可靠做法** |
| 2026-09-24 | **新增「破坏性变更与行为变更清单」一节（第三十九轮）** | 收尾时发现：本会话累积的行为变更**只存在于对话里**，仓库中没有任何汇总。而 `CHANGELOG.md` 由 release-please 从 conventional commits 生成、**不得手改**（`verify_docs.py` 有版本一致性门禁）—— 于是"哪些改动会改变用户可见结果"在提交前无处可查，commit message 很可能漏掉 `BREAKING CHANGE:` | 新增 `improvement-plan.md` §十一：分 A（破坏性，需 minor + `!`）/ B（行为变更）/ C（新增能力）三类，**每条都写明"用户会看到什么不同"**。A 类 4 条（Welch 默认、ANOVA η² 口径、生存分析文本事件列、属性图不等子组）、B 类 8 条、C 类 3 条。并补 `tests/guards/test_boundary_disclosure.py` 的 `TestBreakingChangesAreRecorded`（10 项）：断言已知变更**必须在册**、必须有一列说明用户可见差异、必须写明 CHANGELOG 不得手改 |
| 2026-09-24 | **末轮（第四十轮）：逐条核验原目标的 8 项审计断言 —— 全部实测通过** | 原目标第 (1) 条要求"逐条实测复核 8 项断言"。末轮不只查证据是否留在仓库，而是**逐条跑活体测试**：A1 `c4` 精度 → `TestC4NumericStability`（含 n≥380 对数域）；A2 ANOVA 偏 η² 冒充 η² → `test_anova_ss_type.py`（Type II/III 翻转夹具）；A3 内联 `onclick` → 实测模板 **0 处**内联事件处理器、JS 侧 9 处事件委托；A4 `_validate_output_path` → `test_output_path.py` 20 项；A5 413 无测试 → `app.py` 有 `@app.errorhandler(413)` + `test_web_security.py` 断言 JSON 413；A6 三套 σ 口径 → 每套各自与闭式对账且 `within_sigma_method` 显式披露；A7 §9.2 对照表 → 已重写为"四层防线 + 如实告知真值占比"；A8 `test_cp_cpk_values` → 同义反复已换真值断言。**8/8 通过（162 项专项测试）** | 原目标第 (2) 条（计划文档）与第 (3) 条（按序实施）已完成到可交付状态，未达标项**已逐条如实标注**（见 §十 硬指标表）：真值断言 7.5%（目标 25%）、新增方法成本、真浏览器路径、5 处 Minitab 缺口。**末轮还做了稳定性验证**：全量回归**连跑两遍**，结果完全一致（各 2956 passed / 4 skipped），排除"偶发通过" |
| 2026-09-24 | **⑧ `survival_analysis` 收口到 `_guard` —— 并修掉一个真实缺陷（第 41 轮）** | 收口本身是「消除手抄」（3 处手写字符串列表 → `BoundaryReport`），但实测发现入口**只做 `dropna()`、没有非有限值清洗**，后果有二：① `±Inf` 使 Weibull MLE 失败 → `weibull_shape`/`weibull_scale` **静默变 `None`** 而 `messages` 为空（用户不知道参数为何缺失）；② `+Inf` 在 KM 排序里落到最右端，被当作「活得最久」的观测 —— 实测把中位数由 **77.06 抬到 86.38**（点估计被污染） | 修法：入口加 `clean_frame(report=...)`；三条既有警告改为带码（`E_SURVIVAL_WEIBULL_MLE_NOT_CONVERGED` / `..._TOO_FEW_EVENTS` / `..._HIGH_CENSORING`）；`metadata` 暴露 `boundary_codes`。**先写 16 项复现测试**（含「剔除后中位数应与干净数据一致」这条直指污染的断言），修后 16/16 绿、既有 334 项无回归。**自我更正一次**：我首版断言「剔除 ±Inf 后形状参数与干净情形**完全一致**」→ 失败（1.3574 vs 1.3800）—— 原因很朴素：剔除 3 个观测后样本从 40 变 37，MLE 自然不同。「剔除污染值」不等于「回到原样本」，故判据改为「接近（5% 内）」 |
| 2026-09-24 | **⑨ 真浏览器路径落地（第 41 轮）：改用系统 Edge + CDP，绕开 Playwright** | 计划 P5.3 写的是「Playwright 冒烟 3–5 条」，一直标着"本环境不可用（需下载浏览器）"。第 41 轮实测发现**不必下载任何东西**：Windows 自带 Edge，而 `msedge.exe --remote-debugging-port` 暴露完整的 CDP，Node 22+ 又内置了 `WebSocket` 与 `fetch` —— 于是可以**零依赖**驱动真浏览器 | 新增 `scripts/check_browser_smoke.mjs`（启动 Flask + Edge，CDP 导航/求值/截图）+ `tests/scripts/test_browser_smoke.py`（pytest 包装，无 Edge 时优雅 skip）。**5 组断言**：① ESM + 渲染（页面必须渲染出任务入口）② **CSP 生效**（动态插入的内联脚本必须被拦截 —— 这是第三十九轮收紧 CSP 最需要的回归证据）③ 端到端（浏览器内 `csrf → upload → analyze`，严格线性数据 R² 必须为 1）④ DOM 变更 ⑤ 无 JS 异常 / 无 CSP 违规。实测：51 个任务入口、R²=1、2 表格 1 图表、0 异常、0 违规，并产出 750×485 真实渲染 PNG |
| 2026-09-24 | **② 新增方法成本 8 步 → 1 步（第 42 轮）** | 先实测 8 步里哪些**已被自动化**：第 3 步（`TASK_SPECS` 一条 → `derive()` 派生 7 个结构）与第 4 步（参数默认值由 `/api/tasks` 下发）早已自动。**但真正的隐性成本不在那 8 步里** —— `static/app.js` 另有三份手写任务集合（`_noTargetNeeded` / `_yOnlyTasks` / `_xOptionalTasks`）。新增任务忘改则**不报错、不失败**，只是该任务在 Web 上永远跑不起来 | 两件事：① `TaskSpec` 增加 `y_only` / `x_optional` **显式声明**（曾试图用 AST 推导"是否读 feature_cols"，但 `inverse_solve` 读了它却仍可在只给 Y 时运行 —— 故这是策略、不是可推导的事实），`derive()` 派生 → `/api/tasks` 下发 → 前端 `hydrateParams` 接收、`app.js` 只读；② `scripts/new_task.py` 脚手架 + `--check` 守门。实测派生值 15 + 4 与原前端**逐字一致**（迁移无行为变化）|
| 2026-09-24 | **① 真值断言：零真值任务 21 → 0（第 42 轮）** | 实测发现比"总占比不够"更值得处理的事实：**42 个任务里有 21 个完全没有真值断言** —— 它们的全部测试都只在查结构（有没有表、键在不在、status 是不是 ok），**数值错了不会被发现**。故本轮按**任务**组织补真值，而非按断言数堆量 | 新增 `tests/engine/test_task_truth_assertions.py`（17 项），每个任务一条**由数学唯一确定**的断言，只用三类真值：① 闭式公式（`κ=(p_o−p_e)/(1−p_e)` 实测 `p_o=0.6`/`p_e=0.5`/`κ=0.2` 精确；`α=1`（完全共线）；`[1..5]` 的 σ=√2.5、偏度=0；正交因子 VIF≈1）；② 退化情形（完美分离 → AUC=1；两组逐点相同 → Levene/Bartlett p=1；40×50+3×200 → 异常点恰好 3 个；30×10+30×30 → 变点落在 29±2；38×0+2×100 → 偏度 4.292 判非正态）；③ 只依赖关系（功效所需样本量随效应量单调下降 394→26；`fit=linear` 比 `fit=none` 多画线；Pareto 前沿期望值 ∈[0,1]；Huber 比 OLS 更抗离群；分位回归的 pinball 损失小于 OLS 解） |
| 2026-09-24 | **本轮我错了三次 + 一次口径混用（第 42 轮，全部留档）** | ① 把**比例**（0.02）当地标列传给 p 图，断言 `CL=0.035` → 失败（实测 0.00035）。查 `api-reference.md` 第 268 行确认 `n_col` 是「**样本量列**」→ 目标列应为**不良数**，**是我的数据构造错了**；② 用**完全无噪声**的 `y=5+2x` 断言分位回归系数精确复原 → 失败（引擎报「拟合失败」）。无噪声时残差恒 0，`τ=0.5` 的最优化问题退化 —— 也不是缺陷；③ 改用对称噪声再断言精确复原 → 仍失败（实测 2.2176）。有限样本下 `τ=0.5` 的解**不唯一**（拟合面在近零残差处不可微）；④ 我的测量脚本**漏了任务归属**：只用 `AnalysisRequest(task=…)` 字面量识别任务，而新测试走 `_run("task", …)` 辅助函数 → 21 个任务的归属全丢，指标看似没变化 | ①②③ 都改为**记录正确的事实**：① 改传不良数（并注明来源行号）；②③ 放弃"精确复原系数"，改用分位回归的**定义性质** ——中位数回归的残差中位数 ≈0（实测 4.6e-5）、以及 pinball 损失必小于 OLS 解（实测 14.35 vs 31.92）；④ 修扫描器后真实数字才出来（零真值任务 21 → 0）。**教训（第三次同款）**：扫描器自身有缺陷时，指标会"看起来没变" ——报数字前必须先证明扫描器能看见东西 |
| 2026-09-24 | **守卫的正确演进方向是「消灭一份清单」，不是「写得更严」（第 42 轮）** | `tests/guards/test_frontend_taxonomy.py` 原本的工作是**比对两份手抄清单**（前端集合 vs 后端 `NO_TARGET_TASKS`）。第 42 轮收口后前端那份不存在了，该测试 9 项全红 —— 但**不该**把它改得更严，而应改为对着**唯一来源**断言 | 重写为：① 防回流（前端不得再出现那三个集合的声明）② 端点下发的集合必须**逐字等于** `derive(TASK_SPECS)`③ 语义约束（键有效、两组互斥、无需数据的任务不被拦）④ 守卫自身对篡改敏感（保留 `_extract_set` 的自测）。**这条已提炼为原则**：当守卫的职责是"比对两份清单"时，说明存在重复；正确的下一步是消除重复，而非加固比对 |
| 2026-09-24 | **本轮我犯了 4 个操作/判断错误，全部留档（第 42 轮）** | ① 脚手架重建整个 `__all__` → **抹掉了块内行内注释**（`ruff format --check` 不报警，但那是破坏性的：注释承载"为什么公开"）；② 用 `git checkout -- src/smartsuite/engine/ …` 清理探针时**误伤 `task_spec.py`**，把 ② 的字段改动一起回滚（只能重做）；③ 桩里带了 `from __future__ import annotations`，追加到文件中部 → `SyntaxError`，整个模块失效；④ 断言「`y_only` 不得与 `no_target` 并存」→ **实测证伪**（`doe_design`/`power_analysis`/`inverse_solve` 三者同时在两组，因为"Y 不是必需"与"X 不是必需"是两个独立维度） | ①②③ 已修（`__all__` 改原地插入、`git checkout` 只用于明确单文件、桩去掉 `__future__` 并在注释里写明原因）；④ 把断言反转为**记录事实**并注明两个维度独立。**教训补充**：`git checkout -- <目录>` 与 `git stash -u` 同级危险 ——清理个别文件时**必须逐一列名**，不要用目录或通配 |
| 2026-09-24 | **本轮我错了两次（数据构造 + 断言形状），都由实测拦住（留档）** | ① 造冒烟数据时把 `y` 写成 `10 + i*0.5`、`x1` 写成 `i % 7` —— 两者**独立**，R² 实测 0.0065，而我的断言写"R² 应接近 1"。**是数据构造错了，不是引擎错**；② 按 `{status, tables, metadata}` **顶层**断言 analyze 响应 → 全部 undefined；实测真实形状是 `{results: [{status, tables, metadata, charts, summary, target}]}`。③ 另有一处自家误报：我故意注入内联脚本验证 CSP，它必然产生一条 CSP 违规日志，而第 5 组断言"不得有 CSP 违规"把**探针自身**算成了问题 | 三处都改了：① 数据改为严格线性 `y = 3*x1 + 10`；② 断言改按实测形状（并加图表数/表格数）；③ 在探针之后 `take()` 清空日志，使第 5 组只检查"正常使用页面时"的违规。**这是本会话第 N 次"先跑探针再下结论"救场** —— 计划里那条纪律继续有效 |
| 2026-09-24 | **顺带补全 `api-reference.md` 的参数与口径（第三十九轮）** | 复核时发现 `hypothesis_test` 的 `params` 行列了 `test`/`alpha`/`group_col`，**却没有 `popmean`/`popmedian`** —— 而下面「支持的检验类型」表里明确引用了它们。另：`ttest_ind` 那一行仍写"独立样本 t 检验"，未反映第三十八轮的 Welch 口径 | 两处已补：params 行加上两个参数（含默认值 0），`ttest_ind` 行标注"**默认 Welch**"，并在口径说明开头加一条（含指向用户手册 04 的链接 —— 该手册早已记录了 Welch 变更与 Student 对照值）。**这条也说明 SSOT 的边界**：手册记了、api-reference 漏了，两处都是"签名与口径的唯一信源"的一部分，仍会漂移 |
| 2026-09-24 | **一次 `git stash -u` 事故 —— 以及由此暴露的真实缺口（留档）** | 为判定 Welch 失败是否由我引入，我用 `git stash push -u` 暂存改动。`-u` **把从未提交的新文件也一起暂存了**（本会话新建的测试与文档全部在内），于是 HEAD 状态下那些文件"不存在" —— 我误以为它们丢了。所幸 `git stash pop` 完整恢复 | **教训：`git stash -u` 会带走未跟踪文件**；在"改动从未提交"的长会话里，它等价于一次高风险的全量回滚。判定"是否我引入的回归"应改用 `git worktree` 或先 `git add` 再 stash。**该事故还暴露一个真实缺口**：`hypothesis_test` 的 `PARAM_SPEC`（第二十六轮的成果）**从未提交**，在 stash 往返中丢失 → 19 项测试失败。本轮按测试要求重建（17 种检验类型的中文文案 + `alpha`/`group_col`/`popmean`/`popmedian`），其中 `popmean`/`popmedian` 的默认值由 `Spec.defaults() == DEFAULT_PARAMS[task]` 对拍断言校正为 **0**（我首版写 `None`） |
| 2026-09-24 | **顺带补上 `ttest_ind` 的 Welch 口径（测试早已存在）** | `tests/engine/test_welch_ttest.py`（未跟踪的新文件）断言独立双样本 t 检验**默认用 Welch** 并披露 Levene 判定与 Welch 自由度，而实现一直用 Student（`sp_stats.ttest_ind(g1, g2)` 未传 `equal_var`，scipy 默认 `equal_var=True`）——实测不等方差 + 不等 n 时报告 p=0.8267（Student）而非 0.5990（Welch）。**测试一直失败，只是被前面 15 项 PARAM_SPEC 失败掩盖了** | 按测试的设计意图实现：`equal_var=False` + Levene（`center="median"`）+表格新增「自由度」（Welch–Satterthwaite）与「方差齐性」两列 + 方差不齐时主动告知（B3：口径选择须可见）。9 项测试全绿。**注意这是行为变更**（p 值会变），应进 CHANGELOG 的破坏性/行为变更一节 |
| 2026-09-24 | **如实标注一处「不计入」而非悄悄排除（第三十七轮）** | `reliability.py` 的 `survival_analysis` 有另一套披露通路 —— `warn_msgs: list[str]` + 3 处 `append`（"失效观测仅 N 个"、"未做 Weibull 参数估计"等）。它**不是非有限值清洗**，故按本清单的口径（统计 `_utils` 清洗函数的调用点）确实不该计入 | 但"不计入"很容易变成"看不见"。故在 `guard-migration.md` 里**显式增设一节**记录它，并写明：该通路与 `capability.py` 迁移前的形态**同构**（都是"手写 list 收集文案、只有文本没有错误码"），可按同一范式收口。**纪律：把东西排除在统计之外时，必须在文档里说明它被排除了以及为什么** ——否则统计口径会慢慢变成"只统计已经做完的部分" |
| 2026-09-24 | **新断言立刻抓到一个真问题：`xbar_r.py` 披露文案有两份** | 通用断言报出 `spc_charts/xbar_r.py` 标为已迁移却仍引用 `_utils` 的披露函数。实测查明：`xbar_r.py` 用 `partition_finite`（**合理** —— 它需要「剔除后按组聚合」的语义，不适合直接走 `clean_series`），但**文案是另拼的**，与 `clean_series` 内联那句**逐字相同** —— 即同一句话在两个模块里各写一遍，格式一旦改动就会漂移 | 把构造集中为 `_guard.non_finite_detail()`（唯一构造处），`clean_series` 与 `xbar_r.py` 都调它；新增 4 项断言锁定「`clean_series` 写进 report 的文案逐字等于 `non_finite_detail`」。**注意 `clean_frame` 的文案刻意不同**（多列/按行语义：含 N **行**非有限值），未强行合并 |
| 2026-09-24 | **第三次「当前状态被硬写进测试」（同一类错误连续三轮）** | `test_migration_cost_is_measured_not_guessed` 里硬写着「调用点数 ≥ 15、文件数 ≥ 5」，本轮迁完两个模块后实际降到 3 个文件 → **失败**。这与第三十五轮的「扫描器样本硬写」、第三十二轮的「固定行窗口」是**同一类**：把易变的状态固化进断言 | 改为与**清单声明的待迁移数对账**（`len(sites) == _pending_site_total()`），迁移推进时断言自动跟随，同时仍能抓住「清单过期」与「扫描器失准」两种漂移。**已把这条提炼为通用纪律**：断言里出现「当前有多少 / 至少有多少」这类数字时，先问它会不会随正常推进而变 —— 会变就要从**清单读**，不要写死 |
| 2026-09-24 | **迁移暴露了「清单缺失」：测试里硬写的样本立刻失效（留档）** | 迁完 `capability.py` 后，`tests/guards/test_boundary_disclosure.py` 的「扫描器必须真的看到调用点」断言**立刻失败** —— 它把 `capability.py` 硬写成「必须含旧清洗调用点」的样本。同一条断言在上一轮（第三十二轮）才刚建立，当时那个硬写是对的 | 新建 `docs/governance/guard-migration.md` 作为**迁移进度的单一事实源**，测试从中读出「已迁移 / 待迁移」两集合，并**双向断言**：待迁移的必须仍有旧调用点（否则扫描器失效或清单过期）、已迁移的**不得**再有旧调用点（否则迁移被回退）。**教训：把「当前状态」硬写进测试，等于把测试变成一次性快照** ——应写成「从状态清单读 + 双向核对」，这样迁移推进时测试自动跟随 |
| 2026-09-24 | **又一次假设被实测证伪：干净数据也有边界码** | 我断言「干净数据（无 ±Inf、无子组）不应有任何边界码」→ **失败**：实测得到 `['E_CAPABILITY_SUBGROUP_SIGMA_CAVEAT']`。原因是**无子组时引擎用移动极差法**，那是一个真实的口径假设（隐含「数据行序 = 采样时间顺序」，排序或筛选后失真），本就该记一条 B3 | 断言改为「干净数据无**清洗**码」，并把「无子组必有口径码」一并钉住。**这是本项目第六次「我以为的关系被实测证伪」**（第三十一/三十三/三十四/三十五轮）——计划里已把它写成固定纪律：涉及公式、口径、常数、状态组合，**先跑探针再下结论** |
| 2026-09-24 | **本轮又两次把「方法差异」误判为「缺陷」（留档）** | ① 我先断言 `kruskal_wallis` 缺效应量 → **看漏了**（它的 metadata 里确有 `effect_size`）；② 我把 Gage R&R 的 `tv` 与 `anova_variance_components` 混着求和，报出 **0.1477 的缺口** → 实测查明：**引擎同时给出两套口径**，均值-极差法（`grr²=ev²+av²`、`tv²=grr²+pv²` 精确成立）与 ANOVA 法（交互项单列）**各自自洽但不可混算**；Minitab 同样区分这两种方法 | ② 已在对照表里专设一节写明「两套口径不可混算」并给出实测数字（`tv²=3.0375` vs ANOVA 分量和 `3.1852`），测试里也加了专门断言。**本轮累计已 5 次把「我以为的关系/公式」当成事实**（第三十一/三十三/三十四轮各若干次）——**凡涉及公式、口径、常数，一律先跑探针**，这条已成为本计划里重复次数最多的教训 |
| 2026-09-24 | **本轮我错了三次，全被实测拦住（留档）** | ① 以为「无子组时 `Cp == Pp`」→ **实测证伪**（该数据 `Cp=0.752` vs `Pp=1.095`，因引擎无子组时用**移动极差法**估组内 σ）；② 以为「组内 σ 不大于整体 σ」恒成立 → **实测证伪**（该数据 `σ_mr=2.66` 大于 `σ_overall=1.83`，因相邻行差分放大了逐点抖动）；③ 把 Wilson 下界在 `p̂=1` 的**代数化简写错**成 `(n−z²)/(n+z²)`（给 0.6777），而展开 `p̃ − h` 后与引擎**逐位一致**（0.8388748419） | 三次都是我以为的公式/关系与实际不符，且三次都由**探针**而不是由推理拦住。①② 已把断言改为实测成立的方向并注明原因；③ 改为用**未化简**的闭式对账，并在注释里写明「中间代数步骤要落回公式本身核对，别信任化简」。**这三条与第三十一轮那次（把 `x not in (...)` 误读为 `bool(x)`）是同一类** ——凡涉及公式与真值，先跑探针再下结论 |
| 2026-09-24 | **但确实补上了一个真盲区：既有守卫只认内联形态** | `tests/guards/test_boundary_contract.py` 的 `_INPUT_CLEANUP` 正则写的是 `^\s*(\w+)\s*=\s*\1\[np\.isfinite\(\1\)\]` —— 只匹配**内联**写法 `x = x[np.isfinite(x)]`，而实际代码用的是**函数调用**写法 `x, n = drop_non_finite(x)`。所以一个**新增**的、忘披露的调用点**不会被任何守卫拦住** | 新增 `tests/guards/test_boundary_disclosure.py`（12 项）：AST 作用域判定 + 「扫描器必须真的看到调用点」的自证断言（否则零违规与扫描器失效无法区分）+ 行为锁定（含 ±Inf 的 5 个任务必须披露、无 ±Inf 时不得给假提示）+ **如实记录两份清洗实现仍并存**（含结果等价证明与迁移代价断言）。**经变异测试**：把 `capability.py` 的披露注掉后，行为测试与源码守卫**都失败** |
| 2026-09-24 | **顺带实测了两项此前只有估算的数字** | ① **测试覆盖率**：实测 **92.74%**（9419 语句 / 684 未覆盖）—— 此前计划里没有这个数字，只有「真值断言约 6%」这类估算。② **手工一致性残留**：见上一行。 | 覆盖率 92.74% 说明「有没有测到」不是短板，**「测得对不对」才是** ——这与手册 §9.2 的如实告知一致（第①层独立真值占比不高、第②层多为弱不变量）。故后续若还有轮次，收益在**真值断言**而非覆盖率 |
| 2026-09-24 | **同时如实标注两处「指标行」未达标（避免计划自我美化）** | 复核硬指标表时发现两行的 🔄 标记**高估了完成度**：① 「边界处理…执行点已建，已接入 spc_xbar」—— 实测全引擎**只有 1 个文件**import 了 `_guard`，距「一处声明、一处执行、100%」极远，应标 ⏳ **未达标**而非进行中；② 「错误诊断…code 已落地，尚未接入 AnalysisResult」—— 本轮改了文案层，但 `code` 仍只接入一处，故该行的另一半也如实标注 | 把 ① 改为「⏳ 未达标（如实标注）：执行点已建，但仅 1 处接入」。**这条记录本身是本计划的自我一致性检查** —— 一份改善计划若把自己的进度写得比实测乐观，就复制了它要修的那个毛病（承诺大于实现） |
| 2026-09-24 | **修的是根因，不是症状：`Choice` 的别名只对字符串生效** | 两个布尔开关的静默降级（`maybe`/`123` 被当作 True）不是引擎写得松，而是 **`Choice.check` 把别名解析关在 `isinstance(raw, str)` 分支里** —— 于是无法声明「布尔 `True` 也是 `'true'` 的别名」，也就无法用 `Choice` 收口。这是**既有的表达力缺口**：任何「表单布尔 vs 引擎字符串」的参数都会踩到 | 修法：让非字符串输入也查别名（并加类型守卫，避免对布尔键调 `.strip()`）。随后两个参数改用共享的 `BOOL_SWITCH`（值集 `true`/`false`，`True`/`False`/`1`/`0` 经别名归一到字符串）。**受牵连的两处守卫也一并更新**：共享库「不含任何枚举字段」的判据改为「除白名单外不含枚举」+ 新增「白名单不得成为僵尸豁免」断言 —— **判据没有被削弱**：加任何新枚举字段仍会失败，必须显式改白名单 |
| 2026-09-24 | **本轮一次自我更正（留档）：我误判了一行布尔表达式** | 我读了 `scatter_plot` 里 `show_ci = show_ci.lower() not in ("false","0","no","")` 后，断言它是**真值陷阱**（以为非空字符串恒真 → `'false'` 会被当作开启），并在代码注释里写成缺陷。随后用探针实测：`"false".lower() not in (...)` 就是 `False` —— **旧逻辑是对的**，我把它误读成对整个字符串求布尔值了 | 已在注释里更正，并改为**冗余而非 bug** 的表述（`Choice` 收口后那串多写法白名单再也不会命中，故简化为直比，行为等价）。**教训：读一行布尔表达式时要把求值粒度看清 —— `x not in (...)` 不是 `bool(x)`**；断言「这里有 bug」之前先跑一次探针。本轮正是探针拦住了我写进注释的错误声明 |
| 2026-09-24 | **一处「静态 class 无法表达动态值」的处理（分组背景色）** | 分组底色原经 CSS 变量注入（模板写 `style` 属性）。改 class 时发现：`data-*` 属性**无法驱动 background**（CSS3 的 `attr()` 只能用于 content）；而动态注入 `<style>` 又会重新引入 unsafe-inline | 解法：查实 `GROUP_COLORS` 是**固定 5 项** → 安全地固化为静态 `data-group` 规则。**代价是颜色出现了第二份来源**（引擎常量 + CSS），而漂移时界面只是颜色不好看、不会有测试失败 —— 故补 `test_wf_group_colors_match_engine` 双向校验（逐项一致 + 无孤儿规则）。**该守卫经变异测试验证**：把 CSS 色值改成 #deadbe 后确实失败 |
| 2026-09-24 | **另两处修正：手册的 R 措辞 + 文档诚信整项收口** | ① 手册 §9.2 原写「**正在做的**补救：引入外部参考值（**R 或**独立第二实现）」—— 用户已决定**放弃 R 验证**，且台账 P1-4 早已把 crossval 的 8 处 R 参考改写为独立第二实现。该措辞既过时又与决定矛盾，已改为如实描述**已做完的**三件事（独立第二实现 / 统计性质检验 / 外部裁判层），并显式写明「本项目不含任何 R 输出数值」。② 文档诚信项（原写「4 处均未修」）经逐条核对**已全部闭合** | ① 是本轮唯一与用户决定不一致的文档残留（全仓搜索确认；tooling-pitfalls.md 的命中是 pip-audit 语境、无关）。② A5/A8/A1/P1-4 四条在**既往轮次**已分别修完，但汇总表未回填 —— 属「修了没记账」，故本轮补齐 |
| 2026-09-24 | **本轮顺带发现：手写字典里的提示**本身就写错了** | ① `ranges` 原写「格式: 料温:180,220; 模具温度:40,80」（**字符串**格式），而引擎要的是 **dict** `{列名: (下限, 上限)}` —— 我第二十四轮实测 `ranges='x1:-2,2'` 时被 `AttributeError: str has no attribute items` 抓出；② `objectives` 原写「格式: 强度:maximize; ...」（字符串），而引擎要的是**字典列表** `[{"col":..., "direction":...}]` | 两份提示现都来自 `Spec`（第二十四轮声明时已按实测形态写对），与引擎实际读取的形态一致。**这正说明手写副本的问题不是「懒得同步」，而是「副本本身就是错的却没人发现」** —— 单一事实源的价值在此 |
| 2026-09-24 | **删除被有效守卫拦住的三处测试引用（并升级为更强断言）** | ① `test_web_ui_guards.py` 的回退链守卫断言「接口 → 手写字典 → 键名」三层都在 —— 删除后它立刻失败（**这正是守卫应有的行为**）。已更新为「接口 → 键名」并**新增反向断言**：`PARAM_LABELS`/`PARAM_HINTS`/`PARAM_META` 不得复活，且 `COLUMN_PARAMS` 不得被误删。② `test_verify_frontend_params.py` 的两条可达性用例原从拼接的 JS 里正则抓 `PARAM_META.test.options`，改为核对**真正的单一事实源** `derive_param_options()` —— 它测的就是 `/api/tasks` 下发给用户能选到的值，比抓前端字面量更直接 | ①② 都不是「测试碍事就改测试」：守卫拦住的正是它该拦的东西（一份事实消失了），故更新为校验**新契约**并补上回归保护 |
| 2026-09-24 | **`inverse_solve` 的取舍：它已经是「可见降级」，故不做批量拒绝** | 实测它的参数处理（`engine/inverse/_params.py`）**本就满足 B2/B3 契约**：`model='bogus'` → 「取值无效（bogus），可选：auto/linear/poly/gpr/gbm/rate」；`weight_mode='bogus'` → 「已回退默认 std」；`max_starts=0` → 「应为正整数，已按 1 处理」—— **每条降级都写进用户可见的 `messages`** | 故本轮**只声明标签/提示/选项**（步骤④ 需要），非枚举字段一律透传、不改变既有校验语义。理由：反演求解是**交互式试参数**场景，一次说清所有可调项比逐个报错更贴合；且批量拒绝会**破坏已符合契约的行为**。新增 `test_engine_degradations_are_user_visible` 把这条性质钉住 |
| 2026-09-24 | **`doe_design` 迁移修掉 4 处静默降级 + 1 处错误归因** | ① `center_points`：`-1`/`2.5`/`"abc"` **都 ok**（非 BB/CCD 分支完全不读它）；② `n_runs`：`0`/`"abc"` **都 ok**（非 fractional/PB 分支不读它）；③ `replicates=2.5` → `int()` 静默截断为 2；④ `alpha=inf` → `_is_num(inf) and inf > 0` 为真，被接受；⑤ `seed=-1` → 被报成「**数据格式或数值范围不符合分析要求**」，真实原因是 `np.random.RandomState(-1)` 抛 `Seed must be between 0 and 2**32-1` | ①②③⑤ 由 `Integer` 一次表达（`center_points` min=0、`n_runs` min=1、`replicates` min=1、`seed` min=0）；④ 由 `CrossRule` 表达（`Choice` 无法表达「枚举或数值」的多形态，故 alpha 声明为透传 + 跨字段规则）。**至此本计划共记录并修掉 10 处「静默降级/无校验」型缺陷** |
| 2026-09-24 | **本轮发现一处「ruff 自动清理删掉仍在用的导入」** | 把 `hypothesis_test` 里的 `alpha` 收敛为一次取用后，`ruff --fix` 判定 `from smartsuite.engine._utils import safe_float as _safe_float` **「未使用」并删除** —— 但模块内 4 个 `_ht_*` 辅助函数仍在用它。ruff 按**模块级**统计引用，看不到（它认为）已不再需要的情形 | 症状是运行时 `NameError: name '_safe_float' is not defined`（被编排层泛化成「分析计算过程中出现异常」）。已恢复导入并**写明注释解释为何必须保留**。教训：**重构后跑 `ruff --fix` 要复查它删了什么** —— 自动清理不是无副作用的重排。同理，本轮把「批量替换同形文本」限制在函数作用域内做，否则会误改辅助函数（本轮也发生过，被 ruff 的 F821 抓出） |
| 2026-09-24 | **又一处静默降级：`box_chart.mode` 无白名单** | 实测 `mode='grid'` / `'FACET_'` 都返回 `ok` 并**静默按 facet 执行** （用户以为切换了布局）。已由 `Choice(('facet','分面'),('nested','嵌套'))` 收口 | 这是本计划记录的第 **7** 处「无校验/静默降级」型缺陷（前 6 处：`vif.threshold`、`bins`、`fit`、`n_bootstrap`、`max_depth=inf`、`n_points`）。它们呈现同一模式：**引擎用 `if x == 字面量` 分支，于是拼错的值静默落到 else** |
| 2026-09-24 | **本轮发现 3 个「未接线的参数」/ 静默降级** | ① **`gage_rr.tolerance` 是死参数**：AST 扫描证实 `gage_rr()` 只读 `part_col`/`operator_col`，**完全不读 `tolerance`**，但它就在 `DEFAULT_PARAMS` 里、文档字符串也写「用于 %P/T 计算」—— 与 `regression.model_type` 同族。② **`scatter_plot.fit` 无白名单**：拼错（`"lin"`/`"poly"`）静默落到「不拟合」分支，用户以为画了趋势线。已修（`Choice`）。③ **`bootstrap_ci.n_bootstrap` 静默夹紧**：实测 `50`/`0`/`-5` → 100、`20000` → 10000、`"abc"`/`inf` → 2000，用户毫不知情。已修（`Integer(100,10000)`） | ①②③ 各自配了钉住现状/改进的用例。`tolerance` 按「精准修改」**不改语义**（需先决定补实现还是删假参数），声明为**透传**字段 —— 给它加校验只会让一个无效参数看起来「被支持」 |
| 2026-09-24 | **一处「该修但本轮不修」的取舍：`show_ci` 的静默降级** | `scatter_plot.show_ci` 是**混合类型**参数：默认值是字符串 `"true"`，但布尔 `True` 也被既有测试使用；引擎归一是 `str.lower() not in ("false","0","no","")` —— 于是 `"maybe"`/`"yes"`/`123` 都**静默变成 True**（用户以为关掉了置信带却还在显示） | 我一度想用 `Choice` 收口，实测**它不支持布尔**（别名解析在字符串归一之前），强上会让布尔输入被拒 —— 那是行为回归。故本轮声明为**透传**字段保持既有宽容语义，并把「拼错静默生效」写成 `test_show_ci_silent_degradation_is_recorded` 钉住（修好后该用例会失败并提醒更新计划）。**这属于「需要类型归一能力」的独立改动**，与 `gauge_rr.tolerance` 一并留在台账 |
| 2026-09-24 | **本轮修掉一处「错误归因」，用的是 `CrossRule`** | `lasso_regression` 的 `l1_ratio=0`（纯 Ridge）时 sklearn 抛 `ValueError: Automatic alpha grid generation is not supported for l1_ratio=0`，而该异常被 orchestrator 泛化翻译成误导性的「**数据格式或数值范围不符合分析要求**」—— 真实原因是**参数组合**问题，用户会去查数据，而数据没问题（boundary-contract 禁止错误归因） | 用 `Spec.cross(CrossRule(...))` 在参数层拦下，给出可操作的中文提示（「请同时指定 α，或把 l1_ratio 设为大于 0」），并保留「给出 α 后纯 Ridge 合法」的组合语义。**这是 `CrossRule` 在 P4 中的首次实战使用** |
| 2026-09-24 | **本轮我又错了两处，都很典型** | ① **`multi_objective` 没有顶层 `direction`**：我误以为引擎读了顶层键而默认值表漏了，就往 `task_spec.py` 加了一项；核对源码发现 `direction` 藏在**每个 objective 字典**里（`obj.get("direction", "maximize")`）—— 加了会造出「前端能设、引擎不看」的假参数，正是本轮在 `regression.model_type` 上发现的那类缺陷，已撤回。② **`objectives`/`weights` 的形态写错**：我写成「逗号分隔字符串」，实测是**字典列表**与**数值列表**。另有两处测试夹具错：`ranges` 是 dict 不是字符串、孤立森林需数值特征列 | 教训两条：**「引擎读了 `params`」≠「读的是顶层同名键」**；**声明一个参数的形态前，必须先看引擎怎么用它**（`params.get(x)` 之后的那几行）。本轮也再添一次「批量替换吞掉多行 Python 结构」的事故（PowerShell 替换把 `Spec(` 行删除），改用「定位块边界 + 整块替换」后解决 |
| 2026-09-24 | **本轮我又错了两次，都由核对源码/测试抓出** | ① **`spc_ewma.lam` 的上界是闭区间**：我按 `(0,1)` 写 Spec，源码实为 `if not 0 < lam <= 1` —— λ=1 表示「只看最新点」，是合法的极端平滑。② **`correlation.control_vars` 默认是 `[]` 而非 `None`**：`Spec.defaults()` 的对拍立刻报错。另有 2 处**测试断言错层**：`method="SPEARMAN"` 应被 `Choice` 大小写归一接受、`method=""` 应被编排层归一为「未提供」——我把两者都放进了「拒绝」清单 | 这两类错误在 23 轮里已重复出现多次，**规律很清楚**：「边界的开闭」与「默认值的具体形态」**不能靠推断**，只能读源码或跑对拍。故本批把 `Spec.defaults()` 对拍写成了批量测试的固定项（见 `test_defaults_are_subset_of_default_params`）|
| 2026-09-24 | **本轮发现：`regression.model_type` 是「未接线的参数」** | AST 扫描 `regression_analysis()` 发现它**不读取任何 `params`**，而 `DEFAULT_PARAMS['regression'] = {'model_type': 'linear'}` —— 即前端能选 `model_type`、引擎完全不看。这是「参数不可达」的**镜像问题**（此前修的是「引擎有、前端不可达」；这是「前端可设、引擎不用」） | 按「精准修改」原则本轮**不处理**：需先确认 `model_type` 该被读（补实现）还是该从 `DEFAULT_PARAMS` 移除（删假参数）—— 那是独立决策。已用 `test_regression_function_ignores_all_params` 把现状**钉住**：一旦它被改动，该用例立刻失败并提醒更新计划 |
| 2026-09-24 | **一次「测试固化了坏行为」的发现与修正** | `test_decision_tree_max_depth_inf_no_overflow_error` 断言 `max_depth=inf` 应返回 `status=='ok'`，其**真实意图**是「不得出现『数值溢出，数据中可能存在极端值』这类与用户参数无关的提示」（审查 2026-09-22 发现 5）。但它把**静默降级**（`_safe_int(inf)` 回落默认值 5）一起固化了下来 —— 那条断言保护的是「不报误导错」，副作用是「也不报任何错」 | 迁移后用 `Integer(min=1)` 明确拒绝 `inf`（B0），并把该用例改为**同时保留原意图与修正行为**：断言错误 + 文案含 `max_depth` + **不含「数值溢出」** + 合法值仍正常。**教训：回归测试写「期望现象」时，要问一句「这个现象背后是正确行为，还是被固化的缺陷」** |
| 2026-09-24 | **本轮修掉两处「静默降级」（boundary-contract 明令禁止）** | ① **`vif.threshold` 此前完全没有校验**：实测 `"abc"` 静默回落默认 5（用户以为用了自己的阈值）、`inf` 使 `vif_data["VIF"] > inf` 恒假 → 判定表全空，且 `if threshold <= xmax` 恒假 → **阈值参考线不显示**、`-1` 把全部变量判为高 VIF。② **`distribution_summary.bins` 非整数静默回落自动分箱**（`bins="abc"` → 用户以为自己设了 15 个箱）。两处迁移后都**明确拒绝**（B0），并各配一条对拍用例记录「迁移前被静默接受」 | 两次都是**有意改变行为**，已在测试文件里显式记录而非默默改掉。未提供/`None` 仍走原语义（自动分箱），保持不变 |
| 2026-09-24 | **批量迁移的主防线再次生效（`bins` 默认值）** | 我把 `distribution_summary.bins` 的默认值写成 `None`（想表达「自动分箱」），`test_defaults_match_default_params` 立刻报 `{'bins': None} != {'bins': 15}` —— 实际 `DEFAULT_PARAMS` 是 **15**（前端面板初值）。改为 15，并保留「不传则自动分箱」的语义 | 这是本计划中**第三次**由该对拍断言抓出默认值错误（前两次：`power_analysis.current_n` 应为 30 而非 None；共享库 `GROUP_COL` 应为 None 而非空串）。**结论：`Spec.defaults() == DEFAULT_PARAMS[task]` 值得在每个迁移任务上重复**，已固化为批量测试的固定项 |
| 2026-09-24 | **共享库的判据 + 被它挡下的两个错误** | 共享的判据是**严格**的：只有标签、提示、校验器、默认值**全部相同**才能进库。两条被挡下的：① **`side` 不该共享** —— 我按 "two-sided/one-sided" 写进库，核对源码发现 `spc_nonparametric` 实际是 `two-sided/upper/lower`，而 `tolerance_interval` 同名参数是另一套含义；② **`group_col` 的默认值各任务不同** —— 我统一写了 `""`，对拍用例立刻报 `DEFAULT_PARAMS[variance_test][group_col] == None`（实测 6 个任务用 `None`，仅 `process_capability` 有意用 `""`）。**最终决定：本库不含任何枚举字段**（值集就是语义本身，风险太高） | 这两条都**由测试抓出**，没有流到线上。它们的价值还在于：把"可共享"的边界写成了可执行断言（`test_side_is_not_shared_because_value_sets_differ`、`test_library_has_no_enum_fields_at_all`），而不是靠注释约束 |
| 2026-09-24 | **⚠️ 本轮发现并修掉一个已存在的真实缺陷：Spec 跨任务泄漏** | `param_labels._spec_for_task(func_path)` 按**模块路径**取 `PARAM_SPEC`，但一个模块常含多个任务（`exploratory.py` 有 4 个、`association.py` 有 3 个…）。后果：**同模块的其他任务继承邻居的 Spec** —— `cohens_kappa` 拿到 `contingency` 的 `alpha` 标签、`proportion_ci` 拿到 `variance_test` 的 `group_col`、`box_chart` 拿到 `median_ci` 的 `ci_level`。这与第十七轮的"选项跨任务泄漏"是同族问题：**共用的东西被当成了自己的** | 修法：`PARAM_SPEC` 改为**按任务注册**（`PARAM_SPECS = {"task_key": Spec(...)}`），新增 `spec_for_task(task_key)`；模块级 `PARAM_SPEC` 仅在"该模块独占一个任务"时可信。新增 `tests/services/test_param_spec_registry.py` **11 项**，其中一条逐任务断言"没有自己 Spec 的任务必须返回 `None`"。**影响面**：标签错只是显示问题，但**选项错是功能问题**（用户被提供引擎不认的值）—— 该路径同样受影响，故必须修 |
| 2026-09-24 | **一次失败的方法选择（值得记录）** | 清理 `design.py` 死代码时，我用 PowerShell 脚本做**批量字符串替换**，结果破坏缩进（删掉 `if` 块体后剩空块），文件语法错误。**回退重做**，改用精确的 `edit` 工具分 5 步完成 | 教训：**批量脚本适合"结构一致的重复"，不适合"缩进敏感的 Python 块删除"**。该文件的三处 `n_groups` 检查缩进层级各不相同，脚本模式匹配必然踩坑。回退依据：`git checkout -- <file>` 恢复基线（该项目 15 轮未提交，基线即工作区起点） |
| 2026-09-24 | **架构发现：`param_spec` 必须放 `core/` 而非 `services/`** | 原写在 `services/param_spec.py`；迁移时发现**分层红线禁止 engine 依赖 services**（`test_layer_boundaries.py` 的 `("engine", ("services","web"))`）。参数契约需被 engine 与 services **同时**使用，`core/` 是唯一两者都可依赖的位置。故搬到 `core/param_spec.py`，并把 numpy 换成 stdlib `math.isfinite`（core 层定位为"仅 stdlib+pandas+pydantic"的轻量契约层） | 测试同步移至 `tests/core/test_param_spec.py`（55 项全绿）。**搬家时发生一次操作事故**：`[IO.File]::WriteAllText((Resolve-Path $dst), ...)` 中 `Resolve-Path` 对**不存在的文件**会失败 → 写入静默失败而原文件已删（凭上下文重建）。**教训：写新路径不要用 `Resolve-Path`**（对不存在目标无效），应用 `[IO.Path]::GetFullPath()` 或先 `New-Item` |
| 2026-09-24 | **P4 步骤③：迁移 `spc_attribute`** | `engine/spc_charts/attribute.py` 新增 `PARAM_SPEC`（`chart_type` 枚举 + 4 个透传字段），替换 `params.get("chart_type", "p")`。**修两个行为缺陷**：① `chart_type=None` 不再报"不支持的图表类型: None"（违反"`None` = 未提供"约定且归因误导），改为回落默认；② `"P"` / `"p "` 等大小写/空白变体现在被接受（`Choice` 自带归一）。**顺带修一个迁移外缺陷**：显式指定但**不存在**的 `n_col` 原被静默忽略并回落到行数（控制限就此错掉且无提示），现明确拒绝 —— 违反 boundary-contract 的"禁止静默降级"。**并消除重复**：`p`/`u` 两图各写一份**逐字相同**的零样本量检查，合并为一处 | 新增 `tests/engine/test_attribute_param_migration.py` **45 项**（含 p/np/c/u 四类可运行、归一化变体、非法拒绝列全选项、`Spec`↔引擎双向对拍）。**指标如实记录**：`attribute.py` 早退 **11 → 12**（`Spec` 失败分支 +1、`n_col` 新检查 +1、合并 −1）—— 见下方"验收判据修正" |
| 2026-09-24 | **验收判据的修正（重要）** | 第十二轮实测揭示：**`status="error"` 计数不是本阶段合适的进度指标**。全引擎 282 处早退中，只有约 **54** 处是参数校验类（可迁 `Spec`），其余约 228 处是**依赖数据**的检查（样本量/常量列/结构），且每次迁移还 **+1** 处 `Spec` 早退。算术上 `<80` 在"早退式"架构下**不可达**。已在计划 §六 显式改写验收判据，并指明正道：让迁移后的任务**抛 `SmartSuiteError`** 由编排层统一转结果（`orchestrator.py` 已有完整通路），那样每次迁移 **−N 且 0 新增** | 判据修正为：参数校验手写重复 54 → 0、五份平行字典删除、早退计数降为**参考指标**、新增方法注册 8 步 → 1 步。**记录原因**：原判据是未做迁移时的估算；实测构成后才看清主体是数据相关检查。计划允许被实测修正，但必须**显式改写并说明原因**，不得默默放过 |

| 2026-09-24 | **P4 步骤③ 续：验证"抛异常式迁移"通路（第十三轮）** | 新增 `core/exceptions.py::ParamValidationError`（携带 `code` / `field_name`）与 `Spec.validate_or_raise()`；两个已迁移任务改用之，各自的 `Spec` 失败早退**归零**。`build_error_result` 对参数错误**原样呈现精确文案**（不加"分析执行失败:"前缀 —— 参数错误是用户可直接修正的输入问题，不是执行失败），并把提示换成 **"请修正上述参数后重试"**（原先"如问题持续出现，请联系开发者"是错误指引）。**端到端实测**：引擎抛 `ParamValidationError(code=E_PARAM_NOT_NUMERIC, field=usl)` → 编排层产出 `status=error` + 三条消息（精确文案 / 修正提示 / 错误编号） | 迁移对拍文件改为**双层验证**：引擎层 `pytest.raises(ParamValidationError)`、编排层 `status=="error"`。受影响的既有回归防线 6 项（`test_capability_subgroups` 2、`test_capability_spc_guards` 3、`test_fuzz` 1）改走编排层 —— 那也正是 Web/CLI 的真实路径，比直接调引擎更贴近用户。**全量 1967 passed** |
| 2026-09-24 | **发现并钉住一处"两层语义差异"（有意，非缺陷）** | `usl=""`（空串）在两层行为不同：编排层经 `_normalize_empty_params`（审查 2026-09-19 E11）把空串替换为该参数的**默认值**（`usl` 默认 `None`）→ 不报错，这正是"Web 表单清空输入框"的语义；而引擎层直接调用则 `float(')` 失败 → `NOT_NUMERIC` → 抛异常。两者都对，因为**表单语义归一是编排层职责**，引擎只认规范值。已用两条互为对照的用例分别钉住，避免日后有人"修"掉其中一层 | 该差异最初表现为我的一条测试失败（`usl=' 应被拒绝，实际 ok`），追查后确认是**我的测试断言错层**，不是引擎缺陷。这正是"先验证再断言"的价值 |
**P1-5 的处置**：README 对 Box-Cox 的描述已在此前批次改为"仅 Python API/CLI 参数，未接入 Web 面板"，
并在「已知限制」中写明能力边界 —— 属"改承诺使其与实际一致"，不做无用户价值的面板接入。

**两处breaking change（按"正确性优先"决策执行，需进 CHANGELOG 并升 minor）**：

1. **`hypothesis_test` 的 `ttest_ind` 口径变更**：统计量由 Student 变为 Welch。
   实测手册 §4.3 的示例数据统计量 **12.60 → 10.92**（p 值仍 <0.0001，结论不变）。
   已同步：手册 §4.3 表格 + 口径说明框、`scripts/verify_manual_claims.py` 参考值、
   `tests/integration/test_workflows.py` 的独立复算。
2. **`anova` 的 `η²` 语义变更**：由偏 η² 变为经典 η²（新增 `偏 η²` 键保留原值）。
   单因子设计下两者相等，故既有单因子用例不受影响；多因子用户会看到 `η²` 变小
   （这是修正，不是回归）。

**两处对计划自身的修正**（诚实记录）：

- P1-6 写"覆盖 6 模块漏 6 模块"。实测复测表明**只有 `spc_xbar` 存在错误归因**，
  `spc_cusum`/`spc_ewma`/`process_capability` 已正确报"有效数据不足"。
  **静态推断的范围需要用运行验证收窄。**
- P1-2 计划里写"二选一：真校验，或删承诺"。实际执行时发现**"真校验"与"目录白名单"
  是两件事**：白名单会伤害 CLI 用户，而空路径/目标是目录/父路径是文件这三类
  才是真会失败且报错误导的场景。故改为"做真实有用的校验 + 不加白名单"。

### 本轮新发现的文档谎言（复核实为 4 处 → 实为 5 处）

复核清单 A8 记了 4 处"文档承诺 > 实现"。执行 P1-5 时又撞出第 5 处，且它比前 4 处更严重：

> **`README.md:96` 声称「测量系统分析 | Gage R&R（X-bar & R 法，ANOVA 方差分解）」，
> 但实测 `reliability.py` 的 `gage_rr` 完全没有 ANOVA 方差分解** ——
> 只有均值-极差法（EV/AV/PV/GRR/ndc），无交互项、无 F/p、无方差分量 CI。
> `README.md:95` 对 Box-Cox 的描述同样失实（说"仅 CLI/模板"，但无任何模板含它），
> `README.md:98` 对 Weibull 未提"忽略删失"这一关键限制。

已修：README 模块速览表如实标注，并把「已知限制」从 3 条纯环境说明
扩充为包含 4 条**功能性边界**（Weibull 忽略删失 / Gage R&R 无 ANOVA 法 /
Cp 组内 σ 用 MR 法且假定行序=时间序 / ANOVA 仅 Type II）。
**一张诚实的限制表比一个虚假的绿勾更能建立工程师的信任**——这是本轮最具复用价值的动作。

### 提交建议（已逐条通过 `scripts/validate-commit-msg.sh`）

```
fix(engine)!: spc_xbar 大子组 c4 溢出崩溃与错误归因
fix(engine)!: survival 事件列不再按字典序猜测失效值
fix(engine)!: 独立双样本 t 检验默认改为 Welch
fix(engine): Cp/Cpk 置信区间改用 MR 估计量有效自由度
feat(engine): 新增边界处理契约与 _guard 执行点
fix(web): CSRF 非 ASCII token 不再 500 且 API 错误契约统一 JSON
fix(services): 报告路径改名并补真实校验
fix(services): 日志默认落点不再写 site-packages
fix(engine)!: ANOVA 的 η² 改为经典口径并同时输出偏 η²
docs: 修正 Gage R&R/Box-Cox/Weibull 的能力声明
```

3 条带 `!` = breaking change，由 release-please 自动升 minor 并写入 CHANGELOG
（**不要手改 CHANGELOG.md**，该文件由 release-please 生成，手写会被覆盖）。

> ⚠️ **工具链陷阱（新增）**：Windows 上用 PowerShell 管道喂 `validate-commit-msg.sh`
> 会因 BOM 导致**全部 FAIL**（假红）。必须写 UTF-8 文件后传路径：
> `[IO.File]::WriteAllBytes($tmp, [Text.Encoding]::UTF8.GetBytes($msg))` 再
> `bash scripts/validate-commit-msg.sh $tmp`。本项目无 `sh`，用
> `D:\Program Files\Git\bin\bash.exe`。

### 待办队列（按计划顺序，可直接开工）

| 序 | 条目 | 起点 | 验收 |
|---|---|---|---|
| 1 | **P4 步骤②：迁移 `process_capability` 到 `Spec`（范式）** | `engine/capability.py` 的手写校验头（约 180 行） | `Spec` 与手写校验**逐条对拍一致**的测试通过后，才删手写部分；`status="error"` 计数在该任务上下降 |
| 2 | **P4 步骤③④：其余 41 任务迁移 + 删五份平行字典** | 全部 `engine/**` + `web/static/params.js` | 早退 287→<80、裸 `ValueError` 44→<10 |
| 3 | **P5** 前端报告导出入口 | `web/` | ✅ **后端与端点已完成**（第十八轮）。⚠️ **剩余**：前端"导出报告"按钮（用户目前需手动 POST `/api/export`，实际不可用） |
| 3b | **三个待决策项** | `engine/` + `core/` | ✅ **已决（第三十轮）**：`regression.model_type` = 文档化的**保留参数**（非缺陷，只修文案）；`gage_rr.tolerance` = 文档已承诺 `%P/T` → **补实现**；`show_ci`/`show_stats` = 修 `Choice` 的别名表达力缺口（非给引擎打补丁） |
| 4 | **P5.3 前端余项** | `web/` | ✅ **真浏览器路径已落地（第 41 轮）**：Playwright 仍装不了（未装且需下载 Chromium），但**改用系统已装的 Edge** + CDP（`--remote-debugging-port`，Node 22+ 内置 `WebSocket`，**零依赖**）—— 真浏览器验证的核心诉求（JS 真执行 / CSP 生效 / ESM 加载 / DOM 真变）同样达成。新增 `scripts/check_browser_smoke.mjs` + `tests/scripts/test_browser_smoke.py`：实测 51 个任务入口元素渲染、动态内联脚本**被 CSP 拦截**、浏览器内走完 `csrf → upload → analyze`（严格线性数据 **R²=1**、2 表格 1 图表）、DOM 确实变更、**0 条 JS 异常 / 0 条 CSP 违规**；并产出真实渲染截图。原有的 Node + DOM 桩半运行时冒烟**保留**（两者互补：桩抓模块逻辑，真浏览器抓渲染与接线） |

### P3-3 完成记录（2026-09-24）

**改动前**：`app.js` 933 行单文件、20 个顶层全局、11 处内联 `onclick`、
CSP 被迫 `script-src 'self' 'unsafe-inline'`。

**实际切分**（与原施工说明一致）：

| 文件 | 内容 | 依赖 |
|:---|:---|:---|
| `util.js` | `escHtml` / `fmtCellNum` / `showToast` | 无 |
| `api.js` | `getCsrfToken` / `fetchWithCsrf` | 无 |
| `state.js` | 列数据 / `selectedY·X·Cat` / 上传 / `renderCols` / `autoDetect` / `setAll` / `clearAll` | util, api |
| `params.js` | `TASK_PARAMS` / `PARAM_META` / `PARAM_LABELS` / `PARAM_HINTS` / `INVERSE_*` / 因子与请求行编辑器 | util, state |
| `app.js` | 分析执行链 / `renderResults` / 事件委托 / 初始化 | 全部 |

**执行顺序要点**（这是本轮唯一正确的顺序）：

```
① 先扩门禁  verify_frontend_params.py → 扫描 static/*.js 全部 + 重复标记检测
             test_web_ui_guards.py     → 同上，并新增「无内联处理器」断言
② 再改代码  内联 onclick → data-action + document 级委托；入口加 type="module"
③ 后收紧    CSP script-src 去掉 'unsafe-inline'
④ 补验证    scripts/check_js_modules.mjs（Node 静态解析导入/导出/循环依赖）
             tests/scripts/test_frontend_modules.py（含 MIME 分发校验）
```

**验证边界（说实话）**：本项**没有真浏览器验证**。已做到的替代验证是：

- Node 解析每个模块的具名导入/导出（`showTost` 这类拼写错误会 FAIL 并列出可用导出）
- 依赖图无循环
- Flask 以 `text/javascript` 分发全部 5 个模块（ES module 的严格 MIME 要求）
- 静态度量：无内联处理器、入口 `type="module"`、无 CommonJS 混用

**仍未覆盖**：点击行为的真实执行、事件委托在真实 DOM 上的正确性、
`<template>` 与动态插入元素的委托派发。补 Playwright 冒烟后本项才算完全闭环
（已列入待办第 7 项）。

**这为什么可接受**：委托映射表 `ACTIONS` 是纯声明式结构，
"哪个动作对应哪个函数"是静态可读的；真正的风险在"动作名拼写不一致"
（HTML 写 `data-action="pick-file"`、JS 写 `'pick_file'`），
而这已可静态校验 —— `tests/guards/test_web_ui_guards.py` 新增 4 项：

| 断言 | 拦什么 |
|:---|:---|
| `test_all_data_actions_have_handlers` | 模板用了 `data-action` 但 `ACTIONS` 表无此键（点击静默无效） |
| `test_no_unused_action_handlers` | `ACTIONS` 表有键但无处使用（死代码 / 拼写漂移残留） |
| `test_action_names_use_kebab_case` | `pick_file` vs `pick-file` 类不一致 |
| `test_run_task_buttons_carry_task_name` | `run-task` 按钮缺 `data-task`（会 `runAnalysis(undefined)`） |

**变异验证**：把 HTML 的 `data-action="pick-file"` 改成 `pick_file` → 3 项 FAIL；
把 `clear-columns` 改成 `clear-cols` → 2 项 FAIL；还原后 15/15 全绿。

### P3-3 收尾时暴露的"测试自身硬编码单文件"问题（值得记录）

拆完模块后全量回归出现 **9 项失败**，但**没有一项是产品代码的 bug** ——
全部是**测试自身仍硬编码读取 `app.js` 单文件**：

| 失败用例 | 根因 |
|:---|:---|
| `test_verify_frontend_params.py` 中 5 项 | 负向用例变异 `app.js` 文本，但目标内容已迁至 `params.js`，变异不再生效 |
| 同文件另 2 项 | `_app_js_source()` 只读 `app.js` → `ValueError: substring not found` |
| `test_micro_scale_guards.py::test_app_js_fmt_cell_num_execution` | `fmtCellNum` 已迁至 `util.js` |
| `test_web_app_routes.py::test_new_file_selection_resets_encoding_selector` | 正则依赖原内联箭头函数的书写形状 |

> **教训**：门禁与测试的"文件级硬编码"是一种**隐性技术债** ——
> 它不会报错，只在重构时集体暴露。修法是统一的：
> **凡断言前端源码的用例，一律扫描 `static/*.js` 全量**，
> 并新增 `_mutated_static()` 夹具支持"变异整份前端源码"而非变异单个文件。
> 这与本轮开头"先扩门禁再动代码"是同一条纪律的延伸：
> **门禁的作用域必须覆盖代码可能移动的范围。**

### 跨会话接力说明

```
上一会话结束时 → 简述：
  ✅ 已完成：边界契约 + 执行点 + P0×4 + P1×7 + **P2 全部 6 项** + P3-1/2/3/4/6
             + 金标准层（教科书独立复算 26 项 + 装载器 19 项）
             + 放弃第三方工具验证路线的清理（含 2 条决策锚点断言）
             + P3-3 前端模块化（5 个 ES module、0 内联处理器、
               CSP 去掉 script-src unsafe-inline、Node 模块解析校验）
             + P2-1 Gage R&R ANOVA 方差分解  + P2-3 ANOVA Type II/III
             + P2-5 子组/池化 within-σ + Pp/Ppk CI
  🔜 下一步：队列第 1 项（P4 步骤②：迁移 `process_capability` 到 `Spec` —— 范式任务）
  ⚠️ 阶段2 只完成基础设施（步骤①）。步骤②③④未做完前，
     **不得声称"架构收口已完成"**：早退计数 287 与裸 ValueError 44 都还没下降。
  ⚠️ 已决策：不引入任何第三方统计工具做验证；该局限持续记录在
             tests/golden/test_reference_loader.py 的 UNANCHORED_METHODS（10 项）
  📄 关键上下文：boundary-contract.md（规范）→ improvement-plan.md 本节（进度）
  ⚠️ 未提交：含 4 处 breaking change，提交时需 `!` 标记

  📌 操作提醒（本会话踩过四次）：往「执行台账」表追加新行时，
     edit 的 old_string 只取**上一行结尾**，不要整行替换 —— 否则会覆盖上一条记录
     （P3-3 / P2-1 / P2-3 / P2-5 各被覆盖过一次，均已恢复）。
```

### 实现过程中的教训（值得记入方法论）

**手推解析导数连续错两次 → 改用复步长微分。**

实现删失 Weibull MLE 时，我先手推了负对数似然的梯度与 Hessian。连续两版都被
数值校验推翻（第一次漏了 `(β−1)·ln u` 对 a 的贡献项，第二次 `∂²/∂a∂b` 漏了 `+1`）。
第三版改用 **复步长微分** `Im f(x+ih)/h`（无相减消去误差，精度到机器 epsilon）
作为裁判，一次定位到真实错误。

> **结论**：手推多参数二阶导是高风险操作，且**错误会静默产出无效置信区间**
> （第一版的协方差对角为负，若不检查就会输出反向 CI）。
> 正确做法：① 用复步长/数值微分做裁判；② 对 Hessian 做**正定性检查**，
> 不正定就不输出 CI（本实现已加）。这两条已固化为实现要求。

**另一个教训**：测试用例的**数据生成机制**必须与统计假设一致。
初版删失用例用"所有观测在同一时点被删失"，那不是标准随机删失，
会让"删失 MLE 优于朴素估计"这一前提不成立（两者都偏高）。
改用独立删失时点后结论才可复现 —— **测不出来不一定是实现错，可能是夹具不合假设**。

**第三次同类错误（第二轮，金标准层）**：我在 `tests/golden/` 首跑时判定
"Gage R&R 的 PV 用错常数，存在 3.3% 口径偏差"，并把它写成断言。
**该发现不成立，已撤销。** 根因是我用来判定引擎的那个"参考值"
`d2*(g=1, m=10) ≈ 3.18` **来自我自己的未验证推导**，而推导有两处错误
（先给出随 m 递减的错误形式，再给出比标准表高 1.72 倍的位置差形式）。

> **三次错误（删失 Weibull 的手推导数 ×2、本次的极差常数）全部源于同一件事：
> 在验证参考实现之前，先用它去判定被测实现。**
>
> 固化纪律（已写入 `tests/golden/` 模块 docstring 与 `d2star_semantics.py`）：
> **第一步先用已知输出验证参考实现本身**（例如用 Blom 公式复现标准 d2 表，
> 用 scipy 复现无删失 Weibull MLE），**第二步才拿它判定引擎**。
> 没有第一步，"独立参考"只是把作者的错误包装成了权威。

### 第五次同类错误（第四轮 P2-1，代价最大）

实现 Gage R&R 的 ANOVA 方差分解时，我为 `E[MS_int]`（交互均方期望）**连续手推了
三个错误版本**：

| # | 我的推导 | 错在哪 |
|:--|:---|:---|
| 1 | `(1 − 1/r)·σ²_e` | 被认为"r=2 时只有一半"，与 MC（0.9900σ²_e）矛盾 |
| 2 | `(1 − 1/k)·σ²_e` | 同上，仍与 MC 矛盾 |
| 3 | `σ²_int + 0.6σ²_e` | 数值上偶然接近 r=2 的情形，但跨 r 不一致 |

**正确形式是 `E[MS_int] = σ²_int + σ²_e`**，与 n、k、r 都无关
（400 次 MC 标定：0.022284 vs 理论 0.0225；statsmodels `anova_lm` 独立复核 0.022142）。

**同一轮还踩了第二个坑**：测试夹具把**主效应画在内层循环**

```python
for i in range(n_parts):
    for j in range(n_ops):
        oi = rng.normal(0, sd_op)   # ← 每个零件重抽"操作员效应"
```

`op[:, j]` 因此有 n 个不同值 —— 那不是操作员主效应，**而是 part×operator 交互**。
后果：`E[MS_int]` 从 0.0225 涨到 0.2045（13 倍），"无交互"的用例实际生成了强交互，
多个断言失败，我一度判定**引擎实现有偏**并开始改实现。

**判别手法极简**（已写入夹具 docstring）：**主效应的唯一值数应等于其水平数**
（`op` 应只有 k 个不同值，不是 n 个）。

> **本轮净教训**：
> 1. **统计期望不能靠直觉推导** —— 三次手推全错，最终靠"显式数组 MC + statsmodels
>    双验证"定案。凡是期望/方差，**先测再写**。
> 2. **先验证夹具，再判定实现** —— 夹具缺陷会伪装成实现缺陷，且伪装得很像
>    （数值系统性偏高、方向一致），极易导致改坏正确的代码。
> 3. **诊断工具本身要先自检** —— 期间还发现"用 pandas `Series.sub(axis=1)`
>    减列"会按**索引值**而非数值相减（静默给错结果），以及我自己用
>    `cells.mean(axis=(1,2))` 当零件均值时的理解偏差。诊断脚本的错误率不低于被测代码。
>
> 本会话累计：**手推公式错误 5 次**（Weibull 导数 ×2、极差常数 ×1、ANOVA 期望 ×3
> 中有 2 次同类），**夹具错误 2 次**（Weibull 删失设计、Gage 主效应层级）。
> 全部靠"对照已知输出"发现，无一次靠"再想一遍"发现。

### 第六次同类错误（第六轮 P2-3，形态不同）

实现 ANOVA Type III 时，我**以为** `anova_lm(typ=3)` 会自己处理编码问题，
直接照抄文档用法 → 数值错误。实测对比（平衡设计 a 的 SS）：

| 编码 | `typ=3` 结果 | 判定 |
|:---|---:|:---|
| treatment（patsy 默认） | 3.1962 | **错** |
| sum-to-zero（`C(a, Sum)`） | 3.7398 | 正确（与 Type II 在平衡设计下重合，符合定义） |

不平衡设计下差距更大（2.0283 vs 3.4159）。即 **`anova_lm(typ=3)` 按给定编码计算，
不会自动改用效应编码**；照抄"传 typ=3 即可"的用法会得到错数。

**同一轮还有两个夹具错误**：
1. 首版翻转夹具（20/6/6/6、**无交互**）两法都不显著 —— 无法证明"口径改变结论"，
   断言形同虚设。翻转需要"主效应边缘显著 + 强不平衡"的**窄参数带**，
   最终靠**扫描 400 个随机设计**筛出。
2. 沿用搜索脚本选出的 seed，但**搜索脚本与夹具的 RNG 消耗顺序不同**
   （效应值先抽/后抽）→ "搜到的 seed"在夹具里不成立。
   修法：搜索脚本必须与最终夹具**逐行同构**（本轮已把脚本留在
   `logs/reports/verify-round3/p23_flip_search.py` 供核对）。

> **第六次的教训与前五次略有不同**：这次不是"手推公式"，而是
> **"照抄库文档的用法而不验证其数值含义"**。同一类病的另一种形态 ——
> 共同点仍是**没有先与已知输出对照**。
> 判别手法：找一个人为构造的**已知答案**场景（本处 = 平衡设计下 II 与 III 必须相等），
> 先确认库的行为符合该已知量，再用它做裁判。

### 每项收口固定流程

```bash
# 1. 写复现测试 → 确认 FAILS
# 2. 修复 → 确认 PASSES
PYTHONPATH=src python -m pytest tests/ -q            # 全量无回归
python -m ruff check src/smartsuite/ scripts/ tests/
python -m ruff format --check src/smartsuite/ scripts/ tests/ benchmarks/
python -m mypy
python scripts/test_quality_guard.py                 # 零 FAIL
python scripts/verify_docs.py --strict               # 新增文件须同步目录树
# 3. 回写本节台账（含证据），并在 §一 状态列打勾
```

---
