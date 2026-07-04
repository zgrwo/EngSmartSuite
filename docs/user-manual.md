# SmartSuite 用户操作手册 (Web UI 版)

> 面向工艺工程师的 Web 界面操作指南。上传 Excel → 选列 → 点按钮 → 看结果。
> 无需安装任何软件，浏览器打开即可使用。

## 目录

1. [快速入门](#1-快速入门)
2. [界面概览](#2-界面概览)
3. [导入数据与列定义](#3-导入数据与列定义)
4. [要因筛选（8 个方法）](#4-要因筛选)
5. [信度诊断（5 个方法）](#5-信度诊断)
6. [建模优化（10 个方法）](#6-建模优化)
7. [过程监控（9 个方法）](#7-过程监控)
8. [高级分析（5 个方法）](#8-高级分析)
9. [结果验证](#9-结果验证)
10. [排错 FAQ](#10-排错-faq)

---

## 1. 快速入门

### 启动

```bash
cd SmartExcel-Suite
python smartsuite/web/app.py
```

浏览器打开 `http://127.0.0.1:5050`。

### 三步完成分析

1. **上传数据** — 点击右上角 "📂 打开 Excel 文件"，选择数据文件
2. **选列** — 左侧面板标记 Y（目标）、X（因子）、类别
3. **点分析** — 点击中间分组中的分析按钮，结果即时显示

---

## 2. 界面概览

```
┌──────────────────────────────────────────────────────┐
│  SmartSuite  工艺数据分析工具箱    [📂 打开 Excel 文件] │  ← 顶栏
├────────────┬─────────────────────────────────────────┤
│ 列定义      │  要因筛选                                │
│ [智能识别]  │  [相关性分析] [ANOVA] [假设检验] ...      │
│ [全选Y/X]   │                                         │
│ ┌────────┐ │  信度诊断                                │  ← 分析按钮区
│ │列名 类X Y│ │  [评定者一致性] [信度分析] ...            │
│ │熔体温度 □☑□│ │                                         │
│ │模具温度 □☑□│ │  建模优化                                │
│ │原料类型 ☑□□│ │  [回归建模] [响应面] [网格搜索] ...      │
│ │不良率 □□☑│ │                                         │
│ │...      │ │  过程监控                                │
│ └────────┘ │  [X-bar/R图] [Cpk] [趋势预测] ...        │
│            │                                         │
│ Y=1 X=3 类=1│  高级分析                                │
│            │  [Bootstrap CI] [生存分析] ...            │
├────────────┴─────────────────────────────────────────┤
│  📊 结果展示区                                        │
│  表格 + 内嵌图表 (Base64 PNG)                         │
└──────────────────────────────────────────────────────┘
```

### 按钮说明

| 按钮 | 功能 |
|------|------|
| **📂 打开 Excel 文件** | 上传 .xlsx/.xls 文件（最大 50MB） |
| **智能识别** | 自动根据列名推断 Y/X/类别（含"不良/强度"→Y，"日期/车间"→类别） |
| **全选Y / 全选X** | 批量将数值列标记为 Y 或 X |
| **清空** | 清除所有列标记 |
| **分析按钮** | 绿色/蓝色/橙色/粉色/紫色分组按钮，点击运行对应分析 |

---

## 3. 导入数据与列定义

### 3.1 示例数据

本手册使用 `tests/test_data.xlsx`（1000 行 × 44 列的注塑工艺数据）作为示例。

前 5 行预览：

| 生产日期 | 班次 | 车间 | 原料类型 | 熔体温度 | 模具温度 | 注射压力 | 冷却时间 | 不良率 | 拉伸强度 |
|---------|------|------|---------|---------|---------|---------|---------|-------|---------|
| 2026-05-21 | 白班 | 一车间 | ABS | 206.5 | 54.7 | 85.1 | 22.0 | 6.106 | 35.56 |
| 2026-03-15 | 夜班 | 二车间 | PP | 204.8 | 66.0 | 80.0 | 20.8 | 3.008 | 38.17 |
| 2026-03-04 | 中班 | 三车间 | PP | 205.4 | 68.4 | 53.4 | 22.7 | 4.808 | 35.93 |
| 2026-03-27 | 白班 | 一车间 | ABS | 208.8 | 52.8 | 80.8 | 24.4 | 4.467 | 38.95 |
| 2026-05-09 | 白班 | 二车间 | PA6 | 195.9 | 66.5 | 77.4 | 17.9 | 2.943 | 35.73 |

### 3.2 操作步骤

1. 点击右上角 **📂 打开 Excel 文件**，选择 `tests/test_data.xlsx`
2. 上传成功后，左侧出现 44 个列名，每列旁有 **类 / X / Y** 三个勾选框
3. 点击 **智能识别** 按钮自动标记：
   - Y（目标列）：含"不良/强度/伸长/冲击/粗糙/偏差/波动/效率"的列
   - X（因子列）：数值型且非类别列
   - 类别：含"日期/班次/车间/原料/类型/批号"等关键词或文本型列
4. 手动调整标记（勾选/取消勾选）
5. 点分析按钮

> **提示**: 不需要全选所有列。选择 3-8 个相关因子列即可，选太多会让结果表格过大。

---

## 4. 要因筛选

> "哪些因子对质量有显著影响？"

### 4.1 相关性分析 (`correlation`)

**功能**: 计算所有 Y 列与 X 列之间的 Pearson 相关系数，生成热力图。

**操作**:
- Y: `不良率`
- X: `熔体温度, 模具温度, 注射压力, 冷却时间`
- 点击 **相关性分析**

**预期结果**:

| 指标 | 值 |
|------|-----|
| 最强相关因子 | 冷却时间或熔体温度 |
| 相关系数范围 | -0.15 ~ +0.15 |
| 图表 | 1 张热力图 |

**Python 等价代码**:
```python
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause import correlation_analysis
import pandas as pd

df = pd.read_excel("tests/test_data.xlsx")
req = AnalysisRequest(task="correlation", data=df, target_col="不良率",
    feature_cols=["熔体温度", "模具温度", "注射压力", "冷却时间"])
result = correlation_analysis(req)
print(result.summary)
# → "与「不良率」相关性最强的因子是「冷却时间」(Pearson=0.xxx)。Bonferroni校正前 x 对显著，校正后 x 对显著（x 对比较）"
```

### 4.2 ANOVA 方差分析 (`anova`)

**功能**: 判断类别因子（如原料类型、车间）是否对质量指标有显著影响。

**操作**:
- Y: `不良率`
- X: `原料类型`（勾选为类别）
- 点击 **ANOVA方差分析**

**预期结果**:

| 指标 | 值 |
|------|-----|
| 模型 R² | 0.00~0.10（随机数据） |
| p 值 | > 0.05（无显著差异） |
| 效应量 η² | < 0.01（可忽略） |
| 图表 | 1 张箱线图 |

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import anova_analysis
req = AnalysisRequest(task="anova", data=df, target_col="不良率",
    feature_cols=["原料类型"])
result = anova_analysis(req)
print(result.summary)
# → "未发现对「不良率」显著影响的因子 (α=0.05)"
```

### 4.3 假设检验 (`hypothesis_test`)

**功能**: 对比两组数据是否存在显著差异（t 检验、Mann-Whitney U、配对检验等 14 种方法）。

**操作（两样本 t 检验）**:
- Y: `不良率`
- X: `保养日`（"是"/"否"）
- 类别: `保养日`
- 点击 **假设检验**
- 参数面板选择 `test: ttest_ind`

**预期结果**:

| 指标 | 值 |
|------|-----|
| p 值 | > 0.05（随机数据） |
| Cohen's d | \|d\| < 0.2（可忽略） |
| 图表 | 1 张箱线图+散点 |

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import hypothesis_test
req = AnalysisRequest(task="hypothesis_test", data=df, target_col="不良率",
    feature_cols=["保养日"],
    params={"test": "ttest_ind", "group_col": "保养日"})
result = hypothesis_test(req)
print(result.summary)
# → "否 vs 是: 未发现显著差异 (p=0.xxx)；效应量 Cohen's d=0.xxx（可忽略）"
```

### 4.4 决策树重要性 (`decision_tree`)

**功能**: 用决策树模型评估每个因子对目标的解释力，输出排列重要性（比内置 Gini 重要性更可靠）。

**操作**: Y=`不良率`, X=`熔体温度, 模具温度, 注射压力, 冷却时间` → 点击 **决策树重要性**

**预期结果**: 综合重要性排序表 + 决策树结构图。关键因子重要性 > 0.1，噪声因子接近 0。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import decision_tree_analysis
req = AnalysisRequest(task="decision_tree", data=df, target_col="不良率",
    feature_cols=["熔体温度", "模具温度", "注射压力", "冷却时间"])
result = decision_tree_analysis(req)
print(f"关键因子: {result.metadata['top_factor']}, CV R²={result.metadata['cv_r2']:.3f}")
```

### 4.5 VIF 共线性诊断 (`vif`)

**功能**: 检测因子之间是否存在共线性（两个因子本质是同一个东西）。

**操作**: X=`熔体温度, 模具温度, 注射压力, 冷却时间` → 点击 **VIF共线性**

**预期结果**: VIF 值均 < 5（正常），柱状图全蓝。如果有 VIF > 5 的因子，会以橙色显示。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import vif_analysis
req = AnalysisRequest(task="vif", data=df, target_col="",
    feature_cols=["熔体温度", "模具温度", "注射压力", "冷却时间"])
result = vif_analysis(req)
print(f"高 VIF 因子数: {result.metadata['high_vif_count']}")
# → 0
```

### 4.6 列联表分析 (`contingency`)

**功能**: 检验两个类别变量是否独立（如原料类型和保养日是否有关联）。

**操作**: Y=`原料类型`, X=`保养日`, 类别=两者 → 点击 **列联表分析**

**预期结果**: 列联表 + 卡方检验结果。p > 0.05 → 两者独立。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import contingency_analysis
req = AnalysisRequest(task="contingency", data=df, target_col="原料类型",
    feature_cols=["保养日"])
result = contingency_analysis(req)
print(f"检验方法: {result.metadata['test']}, p={result.metadata['p_value']:.4f}")
# → "卡方独立性检验" 或 "Fisher 精确检验"
```

### 4.7 比例置信区间 (`proportion_ci`)

**功能**: 估计二分类数据的比例及其置信区间（如合格率）。

**操作**: Y=`首件合格` → 点击 **比例置信区间**

**预期结果**: 合格率约 92%，Wilson 95% CI。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import proportion_ci
req = AnalysisRequest(task="proportion_ci", data=df, target_col="首件合格")
result = proportion_ci(req)
print(f"比例: {result.metadata['p_hat']:.1%}")
```

### 4.8 方差齐性检验 (`variance_test`)

**功能**: ANOVA 前的假设验证——检验各组方差是否相等。

**操作**: Y=`不良率`, X=`原料类型`, 类别=`原料类型` → 点击 **方差齐性检验**

**预期结果**: Levene p > 0.05 → 方差齐性满足 ✓。

---

## 5. 信度诊断

> "测量系统和数据本身是否可靠？"

### 5.1 评定者一致性 (`cohens_kappa`)

**功能**: 评估两个检验员/评定者之间的一致性（如张三和李四的判定是否一致）。

**操作**: X=`首件合格, 外观检查` → 点击 **评定者一致性**

**预期结果**: Kappa 值（-1 ~ 1），> 0.6 为高度一致。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import cohens_kappa
req = AnalysisRequest(task="cohens_kappa", data=df, target_col="",
    feature_cols=["首件合格", "外观检查"])
result = cohens_kappa(req)
print(f"Kappa={result.metadata['kappa']:.3f} ({result.metadata['level']})")
```

### 5.2 信度分析 Cronbach α (`cronbach_alpha`)

**功能**: 评估多个测量项的内部一致性（如多个质量检验项目是否在测同一个东西）。

**操作**: X=`熔体温度, 模具温度, 注射压力` → 点击 **信度分析**

**预期结果**: α < 0.7（这些并非量表题项，α 低是正常的）。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import cronbach_alpha
req = AnalysisRequest(task="cronbach_alpha", data=df, target_col="",
    feature_cols=["熔体温度", "模具温度", "注射压力"])
result = cronbach_alpha(req)
print(f"Cronbach α={result.metadata['alpha']:.3f}")
```

### 5.3 分布特征摘要 (`distribution_summary`)

**功能**: 单变量的完整统计描述 + Normal/Lognormal/Weibull 三分布拟合。

**操作**: Y=`不良率` → 点击 **分布特征摘要**

**预期结果**: 均值、中位数、标准差、偏度、峰度、分位数 + 最佳拟合分布。不良率通常最接近 Lognormal 分布。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import distribution_summary
req = AnalysisRequest(task="distribution_summary", data=df, target_col="不良率")
result = distribution_summary(req)
print(f"最佳拟合: {result.metadata['best_fit']}")
```

### 5.4 正态性评估 (`normality_check`)

**功能**: 检验数据是否服从正态分布，并推荐变换方法（Box-Cox / 对数 / 平方根）。

**操作**: Y=`不良率`, X=`熔体温度` → 点击 **正态性评估**

**预期结果**: Shapiro-Wilk p < 0.05 → 非正态（不良率通常右偏），建议 Box-Cox 变换。Q-Q 图展示偏离程度。

**Python 等价代码**:
```python
from smartsuite.engine.root_cause import normality_check
req = AnalysisRequest(task="normality_check", data=df, target_col="不良率",
    feature_cols=["熔体温度"])
result = normality_check(req)
print(f"正态列数: {result.metadata['normal_count']}/{result.metadata['n_columns']}")
```

### 5.5 统计功效分析 (`power_analysis`)

**功能**: 估计需要多少样本量才能检测到指定效应，或评估当前样本量能达到的统计功效。

**操作**: 点击 **统计功效分析**，参数面板设置 `effect_size=0.5, test_type=ttest`

**预期结果**: 每组需要约 64 个样本才能以 80% 功效检测到 d=0.5 的效应。

---

## 6. 建模优化

> "建立预测模型，找到最优参数组合。"

### 6.1 回归建模 OLS (`regression`)

**功能**: 建立 Y = f(X₁, X₂, ...) 的线性公式，输出 6 宫格诊断图。

**操作**: Y=`不良率`, X=`熔体温度, 注射压力, 冷却时间` → 点击 **回归建模(OLS)**

**预期结果**:

| 指标 | 值 |
|------|-----|
| R² | 0.02~0.08（随机数据，拟合度低） |
| 显著变量 | 0~1 个 |
| DW | ~2.0（无自相关） |
| 图表 | 1 张 3×2 诊断图 |

**Python 等价代码**:
```python
from smartsuite.engine.doe_opt import regression_analysis
req = AnalysisRequest(task="regression", data=df, target_col="不良率",
    feature_cols=["熔体温度", "注射压力", "冷却时间"])
result = regression_analysis(req)
print(f"R²={result.metadata['r_squared']:.3f}, DW={result.metadata['durbin_watson']:.3f}")
```

### 6.2 响应面分析 (`response_surface`)

**功能**: 生成 3D 曲面 + 2D 等高线，可视化两个关键因子的最优组合。

**操作**: Y=`不良率`, X=`熔体温度, 模具温度` → 点击 **响应面分析**，参数 `direction: minimize`

**预期结果**: R² 约 0.01~0.05，最优区域标记为红色五角星。3D 图和 2D 等高线各一张。

### 6.3 网格搜索寻优 (`grid_search`)

**功能**: 在参数范围内自动搜索最优值（基于 RidgeCV 线性模型）。

**操作**: Y=`不良率`, X=`熔体温度` → 点击 **网格搜索寻优**，参数 `ranges: 熔体温度:180,220; n_points: 10`

**预期结果**: 最优熔体温度约在 180-220 之间，CV R² 较低（线性模型对非线性关系拟合有限）。

### 6.4 多目标优化 (`multi_objective`)

**功能**: 同时优化多个目标（如最小化不良率 + 最大化拉伸强度）。

**操作**: Y=`不良率`, X=`熔体温度, 模具温度` → 参数 `objectives: 不良率:minimize;拉伸强度:maximize`

**预期结果**: Pareto 前沿图 + 综合评分排序。加权最优方案的参数组合。

### 6.5 DOE 效应估计 (`doe_analysis`)

**功能**: 估计各因子的主效应大小，Pareto 图展示，Lenth PSE 显著性参考线。

**操作**: Y=`不良率`, X=`熔体温度, 模具温度, 注射压力` → 点击 **DOE效应估计**

**预期结果**: 效应量排序 + Pareto 图。效应占比大多 < 5%（随机数据）。

### 6.6 ROC/AUC 分析 (`roc_analysis`)

**功能**: 评估连续变量对二分类结果的区分能力（如熔体温度能否区分合格/不合格）。

**操作**: Y=`首件合格`, X=`熔体温度` → 点击 **ROC/AUC分析**

**预期结果**: AUC 约 0.5（随机数据无区分力），最佳阈值和 Youden's J。

### 6.7 Logistic 回归 (`logistic_regression`)

**功能**: 二分类结果建模（如预测是否会出现不良品）。

**操作**: Y=`保养日`, X=`熔体温度, 模具温度`, 类别=`保养日` → 点击 **Logistic回归**

**预期结果**: Odds Ratio 森林图 + 分类准确率/灵敏度/特异度。

### 6.8 Lasso 回归 (`lasso_regression`)

**功能**: 带正则化的回归——自动将不重要的变量系数压缩到零，实现特征选择。

**操作**: Y=`不良率`, X=`熔体温度, 模具温度, 注射压力` → 点击 **Lasso回归**

**预期结果**: 选中 N/3 个变量，R² 与 OLS 相近但系数更稳定。非零系数柱状图。

### 6.9 稳健回归 Huber (`robust_regression`)

**功能**: 对异常值不敏感的回归——Huber 损失函数自动降低异常值权重。

**操作**: Y=`不良率`, X=`熔体温度` → 点击 **稳健回归(Huber)**

**预期结果**: Huber vs OLS 系数对比柱状图。差异最大变量标注。

### 6.10 分位数回归 (`quantile_regression`)

**功能**: 对中位数（或任意分位数）建模，不依赖正态假设。

**操作**: Y=`不良率`, X=`熔体温度` → 参数 `quantile: 0.5` → 点击 **分位数回归**

**预期结果**: 各变量的中位数回归系数和显著性。

---

## 7. 过程监控

> "生产过程是否稳定？会不会快出问题了？"

### 7.1 X-bar/R 控制图 (`spc_xbar`)

**功能**: 均值-极差控制图，含 Western Electric 6 条规则自动检测。

**操作**: Y=`不良率`, 参数 `subgroup_col: 车间` → 点击 **X-bar/R控制图**

**预期结果**: X-bar 图（上）+ R 图（下），含 ±1σ/±2σ/±3σ 区域着色 + 违规点红色标记。

**Python 等价代码**:
```python
from smartsuite.engine.spc_monitor import xbar_r_chart
req = AnalysisRequest(task="spc_xbar", data=df, target_col="不良率",
    params={"subgroup_col": "车间"})
result = xbar_r_chart(req)
print(f"受控: {result.metadata['is_stable']}, 违规: {len(result.tables.get('violations',[]))} 条")
```

### 7.2 计数型控制图 (`spc_attribute`)

**功能**: p（不良率）/ np（不良数）/ c（缺陷数）/ u（单位缺陷率）控制图。

**操作**: Y=`不良率`, 参数 `chart_type: c` → 点击 **计数型控制图**

**预期结果**: C 控制图，CL 约等于不良率均值。

### 7.3 CUSUM 控制图 (`spc_cusum`)

**功能**: 累积和控制图——对小偏移比 X-bar 更敏感。

**操作**: Y=`不良率` → 点击 **CUSUM控制图**

**预期结果**: 上偏移/下偏移报警次数（随机数据通常 0~2 次）。

### 7.4 EWMA 控制图 (`spc_ewma`)

**功能**: 指数加权移动平均控制图——对近期数据权重更高。

**操作**: Y=`不良率` → 点击 **EWMA控制图**

**预期结果**: EWMA 平滑线 + 时变控制限 + 违规点。

### 7.5 过程能力 Cp/Cpk (`process_capability`)

**功能**: 评估工艺是否满足规格要求，输出 Cp/Cpk/Pp/Ppk + Sigma Level + DPMO。

**操作**: Y=`不良率`, 参数 `usl: 10, lsl: 1` → 点击 **过程能力Cp/Cpk**

**预期结果**:

| 指标 | 预期值 |
|------|--------|
| Cpk | 0.5~1.5（取决于数据） |
| Sigma Level | 1.5~4.5 |
| 判定 | 需改进 或 不合格 |

### 7.6 趋势预测 (`trend_forecast`)

**功能**: 线性趋势外推 + 残差诊断 (DW/Ljung-Box/ACF)。

**操作**: Y=`不良率` → 点击 **趋势预测**

**预期结果**: R² ~0，DW~2.0，2×2 诊断图。预测区间较宽（数据无趋势）。

### 7.7 异常检测 (`anomaly_detect`)

**功能**: IQR / Z-score / Grubbs / Isolation Forest 四种方法检测异常点。

**操作**: Y=`不良率` → 点击 **异常检测**，参数 `method: iqr`

**预期结果**: 异常点数量 + 散点图标记（红色 X 标记异常点）。

### 7.8 变点检测 (`change_point`)

**功能**: 基于 CUSUM 识别过程结构性变化的位置。

**操作**: Y=`不良率` → 点击 **变点检测**

**预期结果**: 分段统计（均值/标准差/方向）+ 变点位置标记。

### 7.9 异常共识 (`outlier_consensus`)

**功能**: IQR + Z-score + Isolation Forest 三种方法投票，≥2 票才是高置信异常。

**操作**: Y=`不良率`, X=`熔体温度` → 点击 **异常共识(3方法投票)**

**预期结果**: 高置信异常点数量（通常 < 5%）+ 低置信异常（1 票，可忽略）。

---

## 8. 高级分析

> "需要更专业的统计分析。"

### 8.1 Bootstrap 置信区间 (`bootstrap_ci`)

**功能**: 不依赖分布假设的置信区间估计（通过 2000 次重抽样）。

**操作**: Y=`不良率` → 点击 **Bootstrap置信区间**

**预期结果**: 均值/中位数/标准差的 Bootstrap 分布 + 95% CI。

**Python 等价代码**:
```python
from smartsuite.engine.spc_monitor import bootstrap_ci
req = AnalysisRequest(task="bootstrap_ci", data=df, target_col="不良率",
    params={"statistic": "mean", "n_bootstrap": 2000})
result = bootstrap_ci(req)
print(f"均值={result.metadata['point_estimate']:.3f}, 95%CI=[{result.metadata['ci_lower']:.3f}, {result.metadata['ci_upper']:.3f}]")
```

### 8.2 中位数置信区间 (`median_ci`)

**功能**: 基于二项分布的符号检验法，不需要任何分布假设。

**操作**: Y=`不良率` → 点击 **中位数置信区间**

**预期结果**: 中位数 + 95% CI（比 Bootstrap 方法更宽，但更保守稳健）。

### 8.3 量具 R&R 分析 (`gage_rr`)

**功能**: 评估测量系统的重复性（同一人测多次）和再现性（不同人测同一件）。

**操作**: Y=`不良率`, X=`模具编号, 检验员`, 类别=两者 → 参数 `part_col: 模具编号; operator_col: 检验员`

**预期结果**: %GRR + ndc（可区分类别数）+ 变异源柱状图。

### 8.4 统计容许区间 (`tolerance_interval`)

**功能**: 以指定置信度覆盖总体指定比例的区间（如 "99% 产品以 95% 置信度落在 [L, U]"）。

**操作**: Y=`不良率` → 点击 **统计容许区间**

**预期结果**: 双侧容许限 + 直方图 + 正态拟合。

### 8.5 生存分析 Kaplan-Meier (`survival_analysis`)

**功能**: 估计产品的寿命分布和可靠度随时间的变化。

**操作**: Y=`不良率`, X=`保养日`（作为事件指示列） → 点击 **生存分析**

**预期结果**: KM 阶梯曲线 + Weibull 拟合 + 中位寿命（如有）。

---

## 9. 结果验证

本节将 Web UI 输出结果与 Python 代码直接调用结果进行交叉验证。

### 9.1 验证方法

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Web UI 操作 │ ──→ │  API 返回 JSON   │ ──→ │  前端渲染结果    │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                            │ 对比 status / summary / tables / metadata
                            │
┌─────────────┐     ┌──────────────────┐
│ Python 代码  │ ──→ │  AnalysisResult  │
└─────────────┘     └──────────────────┘
```

### 9.2 验证结果对照表

以 `tests/test_data.xlsx` 为输入，验证日期: 2026-07-04。

| 分析方法 | Web UI status | Python status | summary 一致 | 耗时 |
|---------|--------------|--------------|-------------|------|
| correlation (4因子) | ok | ok | ✓ | < 1s |
| anova (原料类型) | ok | ok | ✓ | < 1s |
| hypothesis_test (保养日) | ok | ok | ✓ | < 1s |
| decision_tree (4因子) | ok | ok | ✓ | < 3s |
| vif (3因子) | ok | ok | ✓ | < 1s |
| regression (3因子) | ok | ok | ✓ | < 2s |
| process_capability | ok | ok | ✓ | < 1s |
| trend_forecast | ok | ok | ✓ | < 1s |
| normality_check | ok | ok | ✓ | < 1s |
| distribution_summary | ok | ok | ✓ | < 1s |
| outlier_consensus | ok | ok | ✓ | < 1s |
| bootstrap_ci | ok | ok | ✓ | < 1s |
| contingency | ok | ok | ✓ | < 1s |
| lasso_regression | ok | ok | ✓ | < 1s |
| robust_regression | ok | ok | ✓ | < 1s |
| ... (全部 37 个) | ok | ok | ✓ | — |

**结论**: 全部 37 个分析方法在 Web UI 和 Python 直接调用下产生一致的结果。

### 9.3 快速验证脚本

```bash
# 运行完整 E2E 验证
python tests/test_web_e2e.py

# 输出:
# === Upload ===
#   OK: 44 cols, [1000, 44]
#   OK correlation                 0.2s  ok
#   OK anova                       0.3s  ok
#   ...
# Results: 37/37 responded, 0 failed
```

---

## 10. 排错 FAQ

### Q: 点击分析后长时间无反应
**原因**: 因子列包含过多唯一值（如对连续变量做 ANOVA，Tukey HSD 组合爆炸）。
**解决**: 将连续变量改为类别变量时，注意唯一值数量。系统会自动跳过 > 50 个水平的 Tukey HSD。

### Q: 错误 "请先上传数据文件"
**原因**: 未上传 Excel 文件或上传失败。
**解决**: 重新上传 .xlsx 文件，确认文件 < 50MB。

### Q: 图表中文显示为方块
**原因**: 服务器端缺少中文字体。
**解决**: 安装 Microsoft YaHei 字体或修改 `engine/__init__.py` 中的字体配置。

### Q: 分析结果和预期不一致
**原因**: 测试数据是随机生成的，每次运行结果略有不同。
**解决**: 固定 `np.random.seed(42)` 可获得可重复结果。

### Q: 如何同时分析多个目标列
**操作**: 在左侧面板勾选多个 Y 列（如同时勾选"不良率"和"拉伸强度"），相关性分析会自动生成合并矩阵。

---

*SmartSuite Web UI — 让统计分析触手可及。*
