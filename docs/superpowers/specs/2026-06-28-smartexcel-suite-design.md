# SmartExcel Suite — 工艺数据分析工具箱 设计规范

> 版本: V1.0 | 日期: 2026-06-28 | 状态: 已确认

---

## 1. 问题陈述

### 1.1 当前痛点

制造工艺工程师日常需要做大量数据分析（要因分析、参数优化、过程监控），目前：

- **Excel 手工操作**：能处理简单的图表和透视表，但无法做 ANOVA、回归建模、多目标优化等高级分析
- **Python 手写脚本**：分析能力强，但每次写代码繁琐，非编程背景的同事无法使用
- **Minitab/JMP**：功能强但授权昂贵，数据需要在 Excel 和专业软件之间来回搬运

### 1.2 目标

开发一个 Python + Excel 深度集成的分析工具箱，让工艺工程师 **在 Excel 里选择数据 → 点按钮 → 得到分析结果和报告**，无需离开 Excel 也无需编写代码。

### 1.3 核心用户

- **主要用户**：工艺工程师（自己 + 团队同事）
- **技术水平**：熟悉 Excel，不要求编程背景
- **使用频率**：每周 3-5 次（DOE 分析、月度质量报告、异常排查）

---

## 2. 解决方案

### 2.1 核心思路

**三层混合架构**：独立 Python 分析引擎 + xlwings Excel 交互层 + 应用服务编排层。

- **分析引擎是纯 Python 包**，可独立测试、可 CLI 调用、可 Jupyter 使用
- **Excel 交互层很薄**，xlwings 只负责数据进出（Range → DataFrame → Range）
- **服务层做桥接**：参数校验、工作流路由、多格式报告输出

### 2.2 用户故事

1. **要因分析**：选中产线数据，点"要因分析"，自动输出 ANOVA 表 + 相关性矩阵 + 决策树特征重要性 + 一句话结论（工艺语言）
2. **DOE 优化**：选中实验结果，选因子和目标列，点"响应面分析"，输出 3D 响应面图 + 最优参数组合 + 回归方程
3. **SPC 监控**：选中过程数据列，点"控制图"，输出 X-bar/R 图 + Cp/Cpk 计算 + 异常点标记
4. **报告导出**：分析完成后，一键导出为 Excel 图表 Sheet / PDF 报告 / PPT 汇报材料
5. **模板复用**：固定分析（如每月质量报告）存为 YAML 模板，下次一键加载运行

---

## 3. 架构设计

### 3.1 三层架构

```
┌─────────────────────────────────────────────┐
│  ① Excel 交互层 (smartsuite/excel/)          │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Ribbon   │ │ 对话框/   │ │ 结果写入      │ │
│  │ 菜单按钮  │ │ 侧边面板   │ │ Sheet/图表    │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
├─────────────────────────────────────────────┤
│  ② 应用服务层 (smartsuite/services/)         │
│  ┌─────────────────────────────────────────┐ │
│  │ data_io      数据读取 & 参数校验          │ │
│  │ orchestrator 工作流编排                   │ │
│  │ reporter     Excel图表 / PDF / PPT       │ │
│  └─────────────────────────────────────────┘ │
├─────────────────────────────────────────────┤
│  ③ 分析引擎层 (smartsuite/engine/)           │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ root_cause│ │ doe_opt  │ │ spc_monitor  │ │
│  │ ANOVA     │ │ 响应面   │ │ SPC 控制图    │ │
│  │ 假设检验  │ │ 多目标   │ │ Cp/Cpk       │ │
│  │ 决策树    │ │ 最优搜索 │ │ 趋势预测      │ │
│  │ 相关性    │ │ 回归建模 │ │ 异常检测      │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
└─────────────────────────────────────────────┘
```

### 3.2 层间约束

- **engine/** 不得 `import xlwings`
- **excel/** 不得 `import sklearn`
- **services/** 是唯一桥接层
- 引擎层所有函数签名使用 `AnalysisRequest` / `AnalysisResult`，不接 Excel Range 对象

---

## 4. 数据契约

```python
@dataclass
class AnalysisRequest:
    task: str              # "anova" | "correlation" | "doe_rsm" | "spc_xbar" | ...
    data: pd.DataFrame     # 原始数据
    target_col: str        # 目标列 (Y)
    feature_cols: list[str]  # 因子列 (X1, X2, ...)
    params: dict           # 方法参数 (如 alpha, interactions)


@dataclass
class AnalysisResult:
    task: str
    tables: dict[str, pd.DataFrame]  # 多张结果表
    figures: list[Figure]            # matplotlib 图表对象
    summary: str                     # 工艺语言结论
    metadata: dict                   # {r_squared, optimal_params, ...}
    status: str                      # "ok" | "warning" | "error"
    messages: list[str]              # 提示/警告/错误信息
```

---

## 5. 分析引擎模块

### 5.1 要因分析 (root_cause.py)

| 分析项 | 方法 | 输入 | 输出 |
|--------|------|------|------|
| 相关性矩阵 | pandas.corr + scipy | 全部数值列 | 相关系数矩阵 + 显著性标记 |
| ANOVA | statsmodels ols + anova_lm | Y + 多因子 | 方差分析表 + 效应估计 |
| 假设检验 | scipy.stats (t/MWU/chi2) | 两组数据 | p 值 + 效应量 + 结论 |
| 决策树归因 | sklearn DecisionTree | Y + 多因子 | 特征重要性排名 + 树图 |
| 共线性诊断 | statsmodels VIF | 多因子 | VIF 值 + 冗余提示 |

### 5.2 DOE / 优化 (doe_opt.py)

| 分析项 | 方法 | 输入 | 输出 |
|--------|------|------|------|
| 回归建模 | statsmodels OLS | Y + 因子 | 回归方程 + R2 + 残差图 |
| 响应面分析 | numpy meshgrid + matplot3D | 回归模型 | 3D 曲面图 + 等高线图 |
| 多目标优化 | scipy.optimize / 期望函数 | 多目标模型 | Pareto 前沿 + 最优解 |
| 最优搜索 | GridSearch + BayesianOpt | 搜索空间 + 约束 | 最优参数组合 |
| DOE 分析 | 全因子/部分因子 | 实验矩阵 | 主效应 + 交互效应 + Pareto 图 |

### 5.3 过程监控 (spc_monitor.py)

| 分析项 | 方法 | 输入 | 输出 |
|--------|------|------|------|
| SPC 控制图 | matplotlib 自绘 | 过程数据列 | X-bar/R/S/p/np/c/u 图 |
| 过程能力 | numpy + scipy | 数据 + 规格限 | Cp/Cpk/Pp/Ppk + 判定 |
| 趋势预测 | 简单回归 / Holt-Winters | 时序数据 | 预测值 + 置信区间 |
| 异常检测 | IQR / Z-score / LOF | 过程数据 | 异常点标记 + 原因推测 |

---

## 6. 错误处理

| 层级 | 异常类型 | 处理策略 |
|------|---------|---------|
| Excel 层 | DataSelectionError | 弹窗提示，不执行分析 |
| Data I/O 层 | ValidationError | 标记异常列，继续分析有效列 |
| 引擎层 | AnalysisError / ConvergenceError | 标记 status="error"，保留部分结果 |
| Reporter 层 | OutputError | 优雅降级（PPT 失败退 Excel） |

**原则**：
- 不过度阻断 — 标记问题，不抛 traceback
- 工艺语言 — 中文工艺术语，用户可理解
- 优雅降级 — 输出失败时退到可靠格式
- 分层隔离 — 每层只捕获本层的异常

---

## 7. 配置驱动

分析模板存为 YAML，用户可自定义：

```yaml
# templates/my_anova.yaml
task: anova
target_col: "不良率"
feature_cols: ["料温", "模温", "注射压力", "保压时间"]
params:
  alpha: 0.05
  interactions: true
output:
  format: [excel, ppt]
  ppt_template: "templates/月度质量报告.pptx"
```

---

## 8. 测试策略

| 层级 | 类型 | 工具 | 覆盖面 |
|------|------|------|--------|
| engine/ | 单元测试 | pytest + numpy.testing | 每个分析函数的输入输出正确性 |
| services/ | 集成测试 | pytest + tmp_path | Orchestrator 路由 + Reporter 文件生成 |
| excel/ | 手工验证 | 检查清单 | 真实 Excel 端到端流程 |
| 回归 | 数据驱动 | pytest + pandas.testing | 基准 Excel + 已知结果自动比对 |

---

## 9. 部署分发

| 阶段 | 方案 | 目标用户 |
|------|------|---------|
| V1 (当前) | `pip install smartsuite` + `xlwings addin install` | 有 Python 的工程师 |
| V2 | PyInstaller 打包 .exe + 一键安装脚本 | 团队非编程用户 |
| V3 | MSI 安装包 + 共享盘部署 + 自动更新 | 部门级推广 |

---

## 10. 依赖清单

| 类别 | 库 | 用途 |
|------|-----|------|
| Excel 桥接 | xlwings | Ribbon + Range 读写 |
| 数据处理 | pandas, numpy | DataFrame, 矩阵运算 |
| 统计分析 | scipy, statsmodels | 假设检验, ANOVA, 回归 |
| 机器学习 | scikit-learn | 决策树, 特征重要性 |
| 可视化 | matplotlib, seaborn | 统计图, 控制图, 响应面 |
| 报告输出 | python-pptx, reportlab | PPT + PDF |
| 配置解析 | PyYAML | 模板加载 |

---

## 11. 不在范围 (V1)

- 实时数据采集 / MES 接入
- 多人协作 / 权限管理
- Web 仪表板
- AI/ML 深度学习模型
- 多语言国际化
- 云端部署

---

*本规范基于 [skills-main](https://github.com/mattpocock/skills) 工程约定编写。*
