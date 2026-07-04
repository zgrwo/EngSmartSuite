# SmartSuite AI Agent 领域知识

> 帮助 AI 编程助手在工艺数据分析场景中推荐方法、串联工作流、诊断问题。
> 开发规范见 `CLAUDE.md`，API 参考见 `docs/api-reference.md`，术语见 `CONTEXT.md`。

## 项目定位

工艺数据分析工具箱，面向制造工艺工程师。39 个分析方法，Web UI（`python smartsuite/web/app.py`）+ Python API。V1 不做实时采集、深度学习、云部署。

## 分析方法决策树

**这是本文件的核心**——当用户描述一个分析需求时，按此树推荐方法：

```
用户的问题是什么？
├── "哪个因子影响最大？"
│   ├── 因子是连续数值 → correlation
│   ├── 因子是类别 → anova
│   ├── 因子多且交互复杂 → decision_tree
│   └── 确认因子间是否独立 → vif
│
├── "两组/多组有差异吗？"
│   ├── 两组数值对比 → hypothesis_test (ttest_ind / mannwhitney)
│   ├── 配对前后对比 → hypothesis_test (ttest_paired / wilcoxon_paired)
│   ├── 多组对比(非参数) → hypothesis_test (kruskal_wallis / friedman)
│   ├── 两类别变量独立 → contingency
│   ├── 两检验员一致性 → cohens_kappa
│   └── 多组方差相等 → variance_test
│
├── "最优参数是什么？"
│   ├── 建立 Y=f(X) 公式 → regression
│   ├── 两参数可视化最优区 → response_surface
│   ├── 精确搜索最优值 → grid_search
│   ├── 质量+成本权衡 → multi_objective
│   └── 有 DOE 实验矩阵 → doe_analysis
│
├── "过程稳定吗？"
│   ├── 日常监控 → spc_xbar
│   ├── 计数型数据 → spc_attribute
│   ├── 检测微小偏移 → spc_cusum / spc_ewma
│   ├── 非正态数据 → spc_nonparametric
│   └── 分组看分布 → box_chart
│
├── "能力够不够？"
│   ├── 有规格限 → process_capability (Cp/Cpk)
│   ├── 覆盖比例保证 → tolerance_interval
│   └── 测量系统评估 → gage_rr
│
└── "数据有什么特征？"
    ├── 单变量全貌 → distribution_summary
    ├── 正态性 + 变换建议 → normality_check
    ├── 异常点(多方法投票) → outlier_consensus
    ├── 结构性变化 → change_point
    ├── 趋势预测 → trend_forecast
    ├── 寿命/可靠度 → survival_analysis
    ├── 样本量规划 → power_analysis
    └── 二分类区分力 → roc_analysis
```

## 工作流模式

Agent 应理解这 5 条典型的多步骤分析链：

```
1. 要因筛选:  correlation → vif → regression → decision_tree
2. 类别分析:  anova → (显著时) hypothesis_test (Tukey HSD)
3. 非参数:    normality_check → (非正态) kruskal + bootstrap_ci + median_ci
4. SPC 全流程: spc_xbar → process_capability → trend_forecast → anomaly_detect
5. DOE 优化:  doe_analysis → regression → response_surface → grid_search → multi_objective
```

## 关键约定

**异常处理** — 引擎函数返回 `AnalysisResult(status="error", messages=[...])`；`orchestrate()` 用异常类型映射表将 Python 异常转为中文消息；图表失败不影响数值结果。

**预处理差异** — Web UI 走 `preprocess_data()`（中位数填充 + One-Hot），与裸调引擎结果差约 ~0.002。验证一致性时两边应走相同预处理路径。

**常见陷阱速查** — 因子水平 >50 时 Tukey HSD 自动跳过（防超时）；图表中文需 Microsoft YaHei 字体；`np.asarray(model.params)` 不用 `.values`（statsmodels 兼容性）。
