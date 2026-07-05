# SmartSuite

> 工艺数据分析工具箱 —— 上传 Excel，点按钮，得到分析结论 + 图表 + 报告。

SmartSuite 将 Python 生态的统计分析能力（pandas、scipy、statsmodels、scikit-learn）封装为 Web 界面和 Python API，让你无需编写代码即可完成从数据到结论的全流程。

**你不再需要：** 在 Minitab 和 Excel 之间搬运数据 · 每次分析都写 Python 脚本 · 手动复制粘贴到 PPT。

**你现在可以：** 上传 Excel → 选列 → 点按钮 → 得到中文分析结论 + 图表 + 报告。

---

## 三大使用场景

### 场景一：要因分析 — "什么在影响质量？"

> "这周不良率突然升高了，是料温？模温？还是注射压力？"

| 分析方法 | 回答什么问题 |
|---------|------------|
| **相关性分析** | 扫描所有因子的影响力排名 |
| **ANOVA** | 原料类型/机台/操作工是否有显著影响 |
| **假设检验** | 新旧工艺有没有"真的"差异 |
| **决策树** | 多因子交互时找到真正根源 |
| **VIF 共线性** | 参数之间是否互相纠缠（假相关） |
| *等 13 个方法* | 列联表、方差齐性、比例CI、评定者一致性… |

### 场景二：DOE/优化 — "最优参数是多少？"

> "温度和压力调到多少，强度最高、不良率最低？"

| 分析方法 | 回答什么问题 |
|---------|------------|
| **回归建模** | 建立 Y = f(X₁, X₂, …) 数学公式 |
| **响应面分析** | 3D 曲面可视化最优区域 |
| **网格搜索** | 参数范围内自动找到最优组合 |
| **多目标优化** | 质量、成本、效率三者权衡 |
| **DOE 效应分析** | 全因子/部分因子实验效应排序 |
| *等 10 个方法* | Logistic回归、Lasso、稳健回归、分位数回归… |

### 场景三：过程监控 — "产线是否稳定？"

> "产线是不是稳定的？会不会快要出问题了？"

| 分析方法 | 回答什么问题 |
|---------|------------|
| **SPC 控制图** | 过程是否受控，有无异常点 |
| **过程能力 Cp/Cpk** | 工艺能否稳定满足规格 (Cpk ≥ 1.33?) |
| **趋势预测** | 接下来参数会往哪个方向漂 |
| **异常检测** | 批量数据中快速找出"不对劲"的行 |
| *等 16 个方法* | CUSUM/EWMA、非参数控制图、生存分析、变点检测… |

---

## 快速开始

### 方式一：Web 界面（推荐）

```bash
pip install smartsuite[web]
cd SmartExcel-Suite
python smartsuite/web/app.py
```

浏览器打开 `http://127.0.0.1:5050` → 上传 Excel → 选列 → 点按钮 → 看结果。

> 📖 完整操作指南见 **[用户操作手册](docs/user-manual.md)**

### 方式二：Python API（灵活定制）

```bash
pip install smartsuite
```

```python
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

df = pd.read_excel("数据.xlsx")
result = orchestrate(AnalysisRequest(
    task="anova",
    data=df,
    target_col="不良率",
    feature_cols=["料温", "模温", "注射压力"],
    params={"alpha": 0.05}
))
print(result.summary)   # 中文工艺语言结论
print(result.tables)    # 数据表格
print(result.figures)   # matplotlib 图表
```

> 📋 全部 39 个分析方法的参数和返回值见 **[API 参考文档](docs/api-reference.md)**

### 可选依赖组

| 安装命令 | 包含 | 适用场景 |
|---------|------|---------|
| `pip install smartsuite` | pandas, numpy, scipy, statsmodels, scikit-learn, matplotlib | Python API / 纯分析 |
| `pip install smartsuite[web]` | + flask, pyarrow | Web UI |
| `pip install smartsuite[report]` | + python-pptx, reportlab | 导出 PPT/PDF 报告 |
| `pip install smartsuite[all]` | 全部 | 开发/完整功能 |

---

## 输出格式

| 格式 | 用途 | 调用方式 |
|------|------|---------|
| **Web UI** | 在线查看，表格+图表即时呈现 | 浏览器 |
| **HTML 报告** | 自包含报告，可分享 | `to_html(result, "报告.html")` |
| **PDF 报告** | 正式归档、审核 | `to_pdf(result, "报告.pdf")` |
| **PPT 报告** | 会议汇报、管理层展示 | `to_ppt(result, "报告.pptx")` |
| **Excel 工作簿** | 数据+图表在同一文件 | `to_excel(result, workbook)` |

---

## 文档导航

### 核心文档

| 文档 | 读者 | 内容 |
|------|------|------|
| **[用户操作手册](docs/user-manual.md)** | 工艺工程师 | Web UI 操作指南、39 个方法详解、结果解读、排错 FAQ |
| **[API 参考](docs/api-reference.md)** | 开发者 / 高级用户 | 全部 39 个分析函数的参数、返回值、Task Key |
| **[领域术语](CONTEXT.md)** | 所有人 | 项目统一术语定义 |
| **[开发者指南](CLAUDE.md)** | AI / 开发者 | 架构约束、代码风格、测试策略、常见陷阱 |
| **[AI Agent 知识](docs/skill.md)** | AI 助手 | 分析决策树、工作流模式、问题诊断 |

### 开发者文档

| 文档 | 读者 | 内容 |
|------|------|------|
| **[架构决策记录](docs/adr/)** | 架构师 | 2 项架构决策（三层分离、Web UI 替代 Excel 层） |
| **[代码审查模板](docs/contributing/code-review-prompt.md)** | 审查者 | 可复用的深度审查 prompt 模板 |

---

## 帮助与反馈

- 🧪 生成测试数据：`python scripts/generate_test_data.py`
- ✅ 运行一致性验证：`python scripts/verify_consistency.py`
- 🔍 列出所有方法：`python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY), 'tasks')"`

---

*SmartSuite — 让 Python 的统计分析能力服务于每一位工艺工程师。*
