# SmartSuite

> 工艺数据分析工具箱 —— 在 Excel 中选择数据，点击按钮，得到分析结果和报告。无需离开 Excel，无需编写代码。

## 这是什么？

SmartSuite 是面向制造工艺工程师的 Python+Excel 数据分析插件。它把 Python 生态强大的统计分析能力（pandas、scipy、statsmodels、scikit-learn）封装为 Excel 功能区按钮，让你用熟悉的 Excel 界面完成从数据到结论的全流程。

**你不再需要：**
- 在 Minitab 和 Excel 之间来回搬运数据
- 每次分析都写 Python 脚本
- 把结果手动复制粘贴到 PPT 汇报材料

**你现在可以：** 选中数据 → 点按钮 → 得到分析结论 + 图表 + 报告（Excel/PDF/PPT）。

---

## 什么时候使用？

### 场景一：出了问题，要找原因（要因分析）

> "这周的不良率突然升高了，是料温的问题？模温？还是注射压力？"

| 分析方法 | 它能回答什么 | 什么时候用 |
|---------|------------|-----------|
| **相关性分析** | 哪些工艺参数与不良率/强度最相关 | 刚拿到数据，快速扫描所有因子的影响力 |
| **ANOVA** | 原料类型/机台/操作工 是否对质量有显著影响 | 判断某个类别因子（如材料牌号）是不是关键 |
| **假设检验** | 新旧工艺有没有"真的"差异 | 工艺变更前后对比、设备 A vs B 对比 |
| **决策树** | 如果多个参数都在变，哪个才是真正的根源 | 因子多、交互复杂、相关性分析不够直观时 |
| **VIF 共线性诊断** | 你的参数之间是否互相纠缠 | 建模之前检查"假相关"（两个参数实际是同一个东西） |

### 场景二：要找最优参数（DOE / 优化）

> "温度和压力调到多少，强度最高、不良率最低、成本还能接受？"

| 分析方法 | 它能回答什么 | 什么时候用 |
|---------|------------|-----------|
| **回归建模** | 建立 Y = f(X₁, X₂, …) 的数学公式 | 需要量化"参数变 1 单位，结果变多少" |
| **响应面分析** | 生成 3D 曲面图，可视化最优区域 | 有两个关键参数需要同时优化时（如温度+压力） |
| **网格搜索** | 在参数范围内自动找到最优组合 | 已经有回归模型，需要精确的最优值 |
| **多目标优化** | 同时优化强度和成本（一个升一个降怎么办） | 质量、成本、效率三者需要权衡时 |
| **DOE 效应分析** | 全因子/部分因子实验中，哪些效应最强 | 分析正式 DOE 实验矩阵的数据 |

### 场景三：要持续监控（过程控制）

> "产线是不是稳定的？会不会快要出问题了？"

| 分析方法 | 它能回答什么 | 什么时候用 |
|---------|------------|-----------|
| **SPC 控制图** | 过程是否受控，有没有异常点 | 日检/批检数据的日常监控 |
| **过程能力 Cp/Cpk** | 你的工艺是否能稳定满足规格要求 (Cp/Cpk ≥ 1.33?) | 客户审核、质量体系认证、新模具验收 |
| **趋势预测** | 接下来几天参数会往哪个方向漂 | 参数逐渐偏离目标值，需要提前干预 |
| **异常检测** | 这一批数据里有没有离群点 | 大量数据中快速找出"不对劲"的那几行 |

---

## 怎么安装和使用？

### 方式 A：Web 界面（推荐，零安装）

**最简单的方式——浏览器打开即可使用**：

```bash
pip install smartsuite
cd SmartExcel-Suite
python smartsuite/web/app.py
```

浏览器打开 `http://127.0.0.1:5050`，上传 Excel → 选列 → 点按钮 → 看结果。

> 📖 完整 Web UI 操作手册见 **[用户操作手册](docs/user-manual.md)**

### 方式 B：Python 脚本（灵活定制）

```python
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

df = pd.read_excel("数据.xlsx")
result = orchestrate(AnalysisRequest("correlation", df, "不良率", ["料温","模温"]))
print(result.summary)   # 中文工艺语言结论
print(result.tables)    # 数据表格
print(result.figures)   # matplotlib 图表
```

### 方式 C：命令行

```bash
smartsuite list                              # 列出所有方法
smartsuite run 模板.yaml -i 数据.xlsx         # 用模板运行
```

### 方式 D：Excel 功能区（需要 xlwings）

见 **[用户操作手册](docs/user-manual.md)** 中的 Excel 加载项配置说明。

---

## 怎么用？

### 方式一：Web 界面（推荐，零代码） 🆕

1. 启动：`python smartsuite/web/app.py`，浏览器打开 `http://127.0.0.1:5050`
2. **上传数据** — 点击右上角"📂 打开 Excel 文件"
3. **选列** — 左侧面板标记 Y（目标）、X（因子）、类别
4. **点按钮** — 5 组 39 个分析方法，一键运行
5. **看结果** — 表格 + 内嵌图表即时显示

> 📖 详见 **[用户操作手册](docs/user-manual.md)** — 分析决策树、39 个方法逐一详解、结果解读指南、排错 FAQ

### 方式二：Excel 功能区（零代码）

1. **打开你的数据文件** —— Excel 工作表，第一行为表头

2. **点击功能区 "工艺分析" 标签**

3. **选择分析方法**：
   - **要因分析** → 相关性分析 / ANOVA / 假设检验
   - **DOE/优化** → 回归建模 / 响应面分析 / 最优搜索
   - **过程监控** → SPC 控制图 / 过程能力

4. **在弹出的输入框中**：
   - 输入**目标列名** (Y) —— 你想解释/优化的指标，如 "不良率"
   - 输入**因子列名** (X)，逗号分隔 —— 可能的工艺参数，如 "料温, 模温, 注射压力"

5. **查看结果** —— 分析结果自动写入新的工作表，包含：
   - 分析结论（一句话，工艺语言）
   - 数据表格（如 ANOVA 表、相关系数矩阵）
   - 统计图表（如控制图、响应面 3D 图）

6. **导出报告** —— 点击"报告输出"区域的按钮，一键生成 PPT 或 PDF

> **提示：** 对于每月重复的分析（如月度质量报告），可以把配置保存为 YAML 模板，下次用 CLI 一键运行。

### 方式二：YAML 模板 + 命令行（重复性分析）

当你每个月都要对同一份报表做同样的分析时，用模板避免重复配置。

**1. 创建模板文件**（如 `monthly_quality.yaml`）：

```yaml
task: anova
target_col: "不良率"
feature_cols:
  - "料温"
  - "模温"
  - "注射压力"
  - "保压时间"
params:
  alpha: 0.05
output:
  format: [excel, ppt]
```

**2. 运行：**

```bash
smartsuite run monthly_quality.yaml -i 2026年6月质量数据.xlsx -s "注塑车间"
```

**3. 查看所有可用的分析方法：**

```bash
smartsuite list
```

### 方式三：Python 脚本（灵活定制）

```python
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate
from smartsuite.services.reporter import to_ppt

# 1. 读取数据
df = pd.read_excel("质量数据.xlsx")

# 2. 创建分析请求
req = AnalysisRequest(
    task="anova",
    data=df,
    target_col="不良率",
    feature_cols=["料温", "模温", "注射压力", "保压时间"],
    params={"alpha": 0.05}
)

# 3. 运行分析
result = orchestrate(req)

# 4. 查看结论
print(result.summary)   # "显著影响「不良率」的因子: 料温(p=0.003), 模温(p=0.021)"
print(result.tables)    # ANOVA 表、系数表
print(result.figures)   # matplotlib 图表对象

# 5. 导出报告
to_ppt(result, "质量分析报告.pptx")
```

---

## 如何解读结果？

> 📖 完整的 37 个分析方法的解读指南（含效应量、过程能力 Sigma Level 对照表、生存分析解读），请参阅 **[用户操作手册](docs/user-manual.md#结果解读指南)**。

**快速参考**：

| 方法 | 关键指标 | 好/坏的判断 |
|------|---------|------------|
| 相关性分析 | Pearson r, p 值 | \|r\| > 0.5 且 p < 0.05 → 强相关 |
| ANOVA | R², p 值, η² | p < 0.05 → 显著；η² > 0.14 → 大效应 |
| 假设检验 | p 值, Cohen's d | p < 0.05 → 显著；\|d\| > 0.8 → 大效应 |
| 回归建模 | R², p 值, DW | R² > 0.7 → 拟合好；DW ≈ 2 → 无自相关 |
| 过程能力 | Cpk | ≥ 1.33 合格，≥ 1.67 优秀 |
| SPC 控制图 | 违规点数 | 0 违规 → 稳定；> 0 → 需排查 |

---

## 完整分析方法速查

全部 **37 个分析方法**详见 **[API 参考文档](docs/api-reference.md)**。

```bash
$ smartsuite list
  - anomaly_detect      # 异常检测 (IQR / Z-score / Grubbs / Isolation Forest)
  - anova               # 多因子方差分析 + 效应量 + Tukey HSD
  - correlation         # Pearson/Spearman/Kendall 相关性 + 偏相关
  - decision_tree       # 决策树特征重要性 + 排列重要性 + CV
  - doe_analysis        # DOE 主效应 + Lenth PSE 显著性
  - grid_search         # 网格搜索最优参数 (RidgeCV)
  - hypothesis_test     # 14 种检验方法 (t/MWU/Wilcoxon/Friedman...)
  - multi_objective     # 多目标优化 + Pareto 前沿
  - process_capability  # Cp/Cpk/Pp/Ppk/Cpm + DPMO + Sigma Level
  - regression          # OLS 回归 + 诊断 6 宫格
  - response_surface    # 3D 响应面 + 2D 等高线 + 最优点
  - spc_xbar            # X-bar/R 控制图 + Western Electric 6 规则
  - trend_forecast      # 趋势预测 + 残差诊断 + ACF
  - vif                 # 共线性诊断
  ... 共 37 个方法

---

## 输出格式

| 格式 | 用途 | 生成方式 |
|------|------|---------|
| **Excel 图表** | 分析结果+图表嵌入工作簿，数据与结论在同一文件中 | Excel 功能区自动输出 |
| **PDF 报告** | 正式技术报告，归档、审核、质量体系文档 | `to_pdf(result, "报告.pdf")` |
| **PPT 汇报** | 会议汇报、周报月报、管理层展示 | `to_ppt(result, "汇报.pptx")` |

---

## 帮助与反馈

- 📖 **[用户操作手册](docs/user-manual.md)** — 分析决策树、场景工作流、结果解读指南、排错 FAQ
- 📋 **[API 参考文档](docs/api-reference.md)** — 全部 37 个分析函数的参数和返回值
- 🏗️ **[架构设计](docs/adr/0001-three-layer-architecture.md)** — 三层分离架构决策
- 🔧 **开发者指南** — 见 `CLAUDE.md` 和 `CONTEXT.md`
- 🧪 生成测试数据：`python scripts/generate_test_data.py`
- ✅ 运行一致性验证：`python scripts/verify_consistency.py`

---

*SmartSuite — 让 Python 的统计分析能力服务于每一位工艺工程师。*
