# SmartSuite 分析方法决策树

> 当用户描述一个分析需求时，按此树推荐方法。完整开发规范见 `CLAUDE.md`，操作陷阱见 `skills/smartsuite-dev.md`，API 签名见 `docs/api-reference.md`。

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
│   ├── 有 DOE 实验矩阵 → doe_analysis
│   ├── 二分类结果预测 → logistic_regression
│   ├── 自动变量选择 → lasso_regression
│   ├── 抗异常值建模 → robust_regression
│   └── 中位数/分位数建模 → quantile_regression
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
    ├── 异常点(单方法快速) → anomaly_detect (iqr/zscore/grubbs/isoforest)
    ├── 异常点(多方法投票) → outlier_consensus
    ├── 结构性变化 → change_point
    ├── 趋势预测 → trend_forecast
    ├── 两变量关系可视化 → scatter_plot
    ├── 寿命/可靠度 → survival_analysis
    ├── 样本量规划 → power_analysis
    ├── 二分类区分力 → roc_analysis
    ├── 合格率估计 → proportion_ci
    ├── 量表信度 → cronbach_alpha
    └── 非参数区间 → bootstrap_ci / median_ci
```

## 典型工作流链

```
1. 要因筛选:  correlation → vif → regression → decision_tree
2. 类别分析:  anova → (显著时) hypothesis_test (Tukey HSD)
3. 非参数:    normality_check → (非正态) kruskal + bootstrap_ci + median_ci
4. SPC 全流程: spc_xbar → process_capability → trend_forecast → anomaly_detect
5. DOE 优化:  doe_analysis → regression → response_surface → grid_search → multi_objective
```
