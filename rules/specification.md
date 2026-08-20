# EngSmartSuite — 项目规格文档

> 版本：v1.1 | 最后更新：2026-08-19 | 状态：功能完备，Web UI 稳定

## 1. 项目概述

**EngSmartSuite**（工艺数据分析工具箱）是一个将 Python 统计分析能力与 Web UI 交互体验深度整合的工具，提供 40 个统计分析方法，覆盖要因分析、DOE/优化、SPC 控制图、过程能力、异常检测、可靠性/MSA、探索性分析等 7 大领域。

### 核心价值

- 40 个工艺统计分析方法，覆盖从要因分析到可靠性工程
- Web UI + CLI + Python API 三种使用方式
- 4 层测试防线：数值正确性→数学不变量→边界模糊→差分测试
- 中文工艺语言结论，非统计专业用户也能理解

### 目标用户

- 制造业工艺工程师（需要分析良率/缺陷/参数优化）
- 质量工程师（SPC/MSA/过程能力）
- 数据分析师（需要统计方法但不想写 R/Python）

## 2. 功能规格

### 2.1 分析方法清单（40 个）

| 领域 | 方法 | 说明 |
|------|------|------|
| **要因筛选** | correlation | Pearson/Spearman 相关矩阵 |
| | anova | 单因素/多因素方差分析 + Tukey HSD |
| | hypothesis_test | t 检验/Mann-Whitney/Wilcoxon 等 |
| | decision_tree | 决策树特征重要性 |
| | vif | 方差膨胀因子（多重共线性） |
| | contingency | 卡方检验/Fisher 精确检验 |
| | proportion_ci | 比例置信区间 |
| | variance_test | 方差齐性检验（Levene/Bartlett） |
| **信度诊断** | cohens_kappa | 评定者一致性（Cohen's κ） |
| | cronbach_alpha | 信度分析（Cronbach α） |
| | distribution_summary | 分布特征摘要 |
| | normality_check | 正态性评估（Shapiro-Wilk/AD/KS） |
| | power_analysis | 统计功效分析 |
| **建模优化** | regression | 多元线性回归（OLS）+ 诊断 |
| | response_surface | 响应曲面分析 |
| | grid_search | 网格搜索寻优 |
| | multi_objective | 多目标优化（Pareto） |
| | doe_analysis | DOE 效应估计（全因子/部分因子） |
| | roc_analysis | ROC/AUC 分析 |
| | logistic_regression | Logistic 回归 |
| | lasso_regression | Lasso 回归 |
| | robust_regression | 稳健回归（Huber） |
| | quantile_regression | 分位数回归 |
| **过程监控** | spc_xbar | X-bar R/S 控制图 |
| | spc_attribute | p/np/c/u 计数控制图 |
| | spc_cusum | CUSUM 累积和控制图 |
| | spc_ewma | EWMA 指数加权控制图 |
| | process_capability | 过程能力 Cp/Cpk/Pp/Ppk（可选 Box-Cox 转换） |
| | trend_forecast | 趋势预测（线性/移动平均） |
| | anomaly_detect | 异常检测（IQR/Z-score/Grubbs/Isolation Forest） |
| | change_point | 变点检测（CUSUM 二元分割） |
| | outlier_consensus | 异常共识（多方法投票） |
| | box_chart | 分组箱线图 |
| | scatter_plot | 散点图（含拟合） |
| | spc_nonparametric | 非参数控制图（分布拟合法） |
| **高级分析** | bootstrap_ci | Bootstrap 置信区间 |
| | median_ci | 中位数置信区间 |
| | gage_rr | 量具 R&R（MSA） |
| | tolerance_interval | 统计容许区间 |
| | survival_analysis | 生存分析（Kaplan-Meier） |

### 2.2 关键技术特性

- **AnalysisRequest/AnalysisResult 契约**：所有引擎函数统一签名
- **TASK_REGISTRY 路由**：40 个任务统一注册，Web/CLI 共享
- **PALETTE 统一配色**：所有可视化使用统一配色方案
- **中文工艺结论**：summary 字段输出中文工艺语言解读
- **优雅降级**：PPT 失败→Excel，不丢分析结果

## 3. 架构规格

### 3.1 四层架构

```
smartsuite/
├── core/          # ① 数据契约层：仅 pandas+pydantic（AnalysisRequest 为 Pydantic BaseModel）
│   ├── contracts.py    # AnalysisRequest / AnalysisResult
│   └── exceptions.py   # 分层异常体系（3 层）
│
├── engine/        # ③ 分析引擎层：纯 Python，零 xlwings/flask 依赖
│   ├── root_cause.py   # 要因分析
│   ├── doe_opt.py      # DOE/优化
│   ├── spc_charts.py   # SPC 控制图
│   ├── capability.py   # 过程能力
│   ├── detection.py    # 异常检测
│   ├── reliability.py  # 可靠性/MSA
│   └── exploratory.py  # 探索性分析
│
├── services/      # ② 应用服务层：唯一桥接层
│   ├── orchestrator.py # TASK_REGISTRY + DEFAULT_PARAMS
│   ├── data_io.py      # 数据读写 + 预处理（支持 Excel/CSV）
│   ├── reporter.py     # 多格式输出
│   └── audit.py        # 综合审计
│
└── web/           # Web UI 层 (Flask)
    ├── app.py          # Flask 入口 + TASK_GROUPS
    ├── api.py          # REST API
    └── templates/static/
```

### 3.2 依赖规则

- `services/` 是唯一桥接层，engine 和 web 通过它通信
- `web/` 依赖 `services/`，不直接依赖 `engine/`
- `engine/` 零外部依赖（xlwings/flask 等）
- 引擎函数签名：`(AnalysisRequest) -> AnalysisResult`

## 4. 质量规格

### 4.1 测试体系（4 层防线）

| 层 | 文件 | 验证内容 | 覆盖率 |
|---|---|---|---|
| ① 数值正确性 | test_correctness.py | 与 scipy/statsmodels 对比 | 40/40 (100%) |
| ② 数学不变量 | test_invariants.py | p∈[0,1]、Cpk≤Cp、R²≥0 | 关键函数 |
| ③ 边界模糊 | test_fuzz.py | 空数据/单行/全NaN/常量列 | 全部 |
| ④ 差分测试 | test_differential.py | CLI vs Web 数值一致 | 全部 |

### 4.2 已知限制

- matplotlib 后端：CLI 需延迟导入，避免 Agg 后端冲突
- scipy 兼容性：kstest 字符串分布名需改为 frozen dist cdf
- pandas FutureWarning：sum(axis=None) 需改为 sum().sum()
- statsmodels 警告：含 'failed' 单词导致 verify_consistency 误判

## 5. 历史演化摘要

| 阶段 | commits | 关键事件 |
|------|---------|----------|
| 项目初始化 | ~5 | 规格/配置/脚手架 |
| 引擎开发 | ~20 | 40 个分析方法实现 |
| Web UI | ~15 | Flask + 前端参数面板 |
| 审查修复期 | ~50 | 15+ 轮代码审查，falsy 陷阱/统计修正 |
| 文档完善 | ~20 | 用户手册 39 方法六段式结构 |
| CI/CD | ~10 | 分层 pipeline（quick/full/quality/consistency） |

**总计**：~120 commits

## 6. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web 框架 | Flask | 轻量，适合单用户本地使用 |
| 可视化 | matplotlib | 工艺图表标准化，非交互式 |
| 统计库 | scipy + statsmodels | 覆盖全部 40 方法 |
| 数据契约 | Pydantic v2 BaseModel | 数据验证 + 类型安全 |
| 配置驱动 | YAML 模板 | 重复分析可复用，不硬编码 |
