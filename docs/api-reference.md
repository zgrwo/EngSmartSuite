# SmartSuite API Reference

> 全部 39 个分析函数的完整参考。数据契约定义在 `smartsuite/core/contracts.py`。
> 开发规范 → `CLAUDE.md` | 开发陷阱 → `skills/smartsuite-dev.md` | 场景选择 → `docs/skill.md` | 术语 → `CONTEXT.md`

## 数据契约

### AnalysisRequest

```python
@dataclass
class AnalysisRequest:
    task: str                    # 任务类型键 (如 "anova", "correlation")
    data: pd.DataFrame           # 输入数据
    target_col: str              # 目标列名 (Y)
    feature_cols: list[str]      # 因子列名 (X)
    params: dict[str, Any]       # 方法特定参数
```

### AnalysisResult

```python
@dataclass
class AnalysisResult:
    task: str                    # 任务类型键
    tables: dict[str, pd.DataFrame]  # 结果表字典
    figures: list[Figure]        # matplotlib 图表列表
    summary: str                 # 中文工艺语言结论
    metadata: dict[str, Any]     # 结构化元数据
    status: str                  # "ok" | "error"
    messages: list[str]          # 警告/错误消息
```

---

## 一、要因分析 (Root Cause)

### correlation_analysis
- **Task Key**: `correlation`
- **描述**: 相关性矩阵分析（Pearson/Spearman/Kendall），含 Bonferroni 多重比较校正和显著性标记
- **params**: `method` ("pearson"|"spearman"|"kendall"), `control_vars` (偏相关控制变量)
- **返回**: `correlation_matrix`, `p_values_raw`, `p_values_corrected`, `annotated_matrix`
- **图**: 热力图 + 散点矩阵 + 偏相关对比柱状图

### anova_analysis
- **Task Key**: `anova`
- **描述**: 多因子 ANOVA 方差分析，含效应量 (η²/ω²)、Levene 方差齐性检验、Shapiro-Wilk 正态性检验、Tukey HSD 事后比较
- **params**: `alpha` (默认 0.05), `interactions` (是否包含两两交互)
- **返回**: `anova_enhanced`, `coefficients`, `posthoc_tukey`
- **图**: 箱线图 + 交互效应图

### hypothesis_test
- **Task Key**: `hypothesis_test`
- **描述**: 多种假设检验，含效应量和统计功效
- **params**: `test` (默认 "ttest_ind"), `alpha` (0.05), `group_col`
- **支持的检验类型**:

| test 值 | 描述 | 额外参数 |
|---------|------|---------|
| `ttest_ind` | 独立样本 t 检验 | `group_col` |
| `ttest_paired` | 配对 t 检验 | — |
| `ttest_1samp` | 单样本 t 检验 | `popmean` |
| `mannwhitney` | Mann-Whitney U 检验 | `group_col` |
| `wilcoxon_paired` | 配对 Wilcoxon 符号秩 | — |
| `wilcoxon_1samp` | 单样本 Wilcoxon | `popmedian` |
| `kruskal_wallis` | Kruskal-Wallis H 检验 | `group_col` |
| `friedman` | Friedman 检验 | — |
| `mcnemar` | McNemar 检验 | — |
| `cochran_q` | Cochran Q 检验 | — |
| `ks` | Kolmogorov-Smirnov 双样本 | `group_col` |
| `mann_kendall` | Mann-Kendall 趋势检验 | — |
| `jonckheere` | Jonckheere-Terpstra 趋势 | `group_col` |
| `auto` | 自动选择 (Shapiro-Wilk → t/MWU) | `group_col` |

### decision_tree_analysis
- **Task Key**: `decision_tree`
- **描述**: 决策树特征重要性分析，含内置重要性 (Gini) + 排列重要性 + 交叉验证
- **params**: `max_depth` (默认 5), `random_state` (42)
- **返回**: `feature_importance` (含综合重要性排序)
- **图**: 重要性对比柱状图 + 决策树结构图

### vif_analysis
- **Task Key**: `vif`
- **描述**: 方差膨胀因子 (VIF) — 多元共线性诊断
- **params**: 无
- **返回**: `vif_table` (VIF > 5 标记为高风险)
- **图**: VIF 柱状图 (阈值线 = 5)

### contingency_analysis
- **Task Key**: `contingency`
- **描述**: 列联表分析 — Chi-square（含小期望频数标注）+ Cramér's V / Odds Ratio（2×2 表）
- **params**: `alpha` (0.05)
- **返回**: `contingency_table`, `expected_frequencies`
- **图**: 堆叠柱状图

### proportion_ci
- **Task Key**: `proportion_ci`
- **描述**: 二项比例置信区间 — Wilson Score + Clopper-Pearson 精确方法
- **params**: `success_value` (可指定"成功"标签)
- **返回**: `proportion_ci`
- **图**: Wilson vs Clopper-Pearson 区间对比

### variance_test
- **Task Key**: `variance_test`
- **描述**: 方差齐性检验 — Levene (中位数, 推荐) + Bartlett (需正态)
- **params**: `group_col`, `alpha` (0.05)
- **返回**: `variance_tests`, `group_statistics`

### cohens_kappa
- **Task Key**: `cohens_kappa`
- **描述**: Cohen's Kappa — 两个评定者之间的一致性评估
- **params**: 无 (使用 `feature_cols[0]` 和 `feature_cols[1]` 作为评定者)
- **返回**: `agreement_matrix`, `kappa_result`

### cronbach_alpha
- **Task Key**: `cronbach_alpha`
- **描述**: Cronbach's α — 内部一致性信度分析，含"删除该项后α"变化
- **params**: 无 (feature_cols 视为量表题项)
- **返回**: `alpha_summary`, `item_analysis`

### distribution_summary
- **Task Key**: `distribution_summary`
- **描述**: 分布特征摘要 — 描述性统计 + Normal/Lognormal/Weibull 拟合
- **params**: 无
- **返回**: `descriptive_stats`, `distribution_fits`
- **图**: 直方图 + 多元分布拟合曲线

### normality_check
- **Task Key**: `normality_check`
- **描述**: 正态性评估 — Shapiro-Wilk + Anderson-Darling，推荐变换方法
- **params**: 无
- **返回**: `normality_results` (含偏度/峰度/建议变换)
- **图**: Q-Q 子图矩阵

### power_analysis
- **Task Key**: `power_analysis`
- **描述**: 统计功效分析 — 估计所需样本量 (`required_n`) 或已达功效 (`achieved`)
- **params**: `effect_size` (0.5), `alpha` (0.05), `target_power` (0.80), `mode`, `test_type` ("ttest"|"anova"|"proportion")
- **返回**: `power_result`
- **图**: 功效曲线 (required_n 模式)

---

## 二、DOE / 优化 (DOE & Optimization)

### regression_analysis
- **Task Key**: `regression`
- **描述**: 线性回归 OLS，含标准化系数 (β)、Durbin-Watson、Breusch-Pagan 异方差检验、Cook's D 影响点诊断
- **params**: `model_type` (保留参数，当前仅支持 OLS)
- **返回**: `coefficients`, `diagnostics`
- **图**: 6 宫格诊断图 (Residual vs Fitted / Q-Q / Scale-Location / Cook's D / Leverage / Actual vs Predicted)

### response_surface_analysis
- **Task Key**: `response_surface`
- **描述**: 响应面分析 — 二次模型 + 3D 曲面 + 2D 等高线 + 最优点标记
- **params**: `direction` ("maximize"|"minimize")
- **返回**: `coefficients`, `model_fit`
- **图**: 3D 曲面 (左) + 2D 填充等高线 (右)

### grid_search
- **Task Key**: `grid_search`
- **描述**: 网格搜索最优参数 — RidgeCV 模型 + 交叉验证
- **params**: `ranges` (必需: {col: (lo, hi)}), `n_points` (默认 10), `direction`
- **返回**: `top_candidates`
- **图**: 2D 等高线 (2 参数) 或预测值柱状图 (1 参数)

### multi_objective_opt
- **Task Key**: `multi_objective`
- **描述**: 多目标优化 — 加权期望函数法 + Pareto 前沿 (双目标)
- **params**: `objectives` (必需: [{col, direction, ...}]), `weights`
- **返回**: `desirability_scores`, `optimal_parameters`
- **图**: Pareto 前沿 (双目标) + 方案分解堆叠柱状图

### doe_analysis
- **Task Key**: `doe_analysis`
- **描述**: DOE 主效应与交互效应分析，含 Lenth PSE 显著性参考线
- **params**: `alpha` (0.05)
- **返回**: `effect_estimates` (含 t 值/p 值/效应量解读)
- **图**: Pareto 效应图 + Lenth ME 参考线

### roc_analysis
- **Task Key**: `roc_analysis`
- **描述**: ROC 曲线和 AUC 分析 — 评估连续预测变量对二分类结果的区分能力
- **params**: 无
- **返回**: `roc_points`, `auc_summary`
- **图**: ROC 曲线 + 最佳阈值标记 (Youden's J)

### logistic_regression
- **Task Key**: `logistic_regression`
- **描述**: Logistic 回归 — 二分类建模，输出 Odds Ratio + 分类指标
- **params**: 无
- **返回**: `coefficients` (含 OR + 95%CI), `classification_metrics`
- **图**: OR 森林图

### lasso_regression
- **Task Key**: `lasso_regression`
- **描述**: Lasso/ElasticNet 正则化回归 — 自动变量选择
- **params**: `alpha_lasso` (手动指定 α), `l1_ratio` (1.0=纯Lasso, <1.0=ElasticNet)
- **返回**: `coefficients` (含选中/未选中标记)
- **图**: 非零系数柱状图

### robust_regression
- **Task Key**: `robust_regression`
- **描述**: Huber 稳健回归 — 对异常值不敏感，输出与 OLS 的系数对比
- **params**: 无
- **返回**: `coefficient_comparison`
- **图**: Huber vs OLS 系数对比柱状图

### quantile_regression
- **Task Key**: `quantile_regression`
- **描述**: 分位数回归 — 对非正态/异方差响应建模
- **params**: `quantile` (默认 0.5 = 中位数回归)
- **返回**: `coefficients`

---

## 三、过程监控 (SPC & Monitoring)

### xbar_r_chart
- **Task Key**: `spc_xbar`
- **描述**: X-bar 和 R 控制图，含 Western Electric 6 规则检测和 σ 区域着色
- **params**: `subgroup_col` (默认 "子组")
- **返回**: `control_limits`, `violations` (违规汇总表)
- **图**: X-bar 图 (上) + R 图 (下) — 含区域着色和违规点标记

### attribute_chart
- **Task Key**: `spc_attribute`
- **描述**: 计数型控制图 — p (不良率), np (不良数), c (缺陷数), u (单位缺陷率)
- **params**: `chart_type` ("p"|"np"|"c"|"u"), `subgroup_col`, `n_col` (p/u 图样本量列)
- **返回**: `control_stats`
- **图**: 属性控制图 + 控制限

### cusum_chart
- **Task Key**: `spc_cusum`
- **描述**: CUSUM 累积和控制图 — 对小偏移 (±0.5σ~2σ) 敏感
- **params**: `k` (默认 0.5), `h` (默认 5.0)
- **返回**: `cusum_stats`
- **图**: 原始数据 (上) + C+/C- 累积和 (下)

### ewma_chart
- **Task Key**: `spc_ewma`
- **描述**: EWMA 指数加权移动平均控制图 — 时变控制限
- **params**: `lam` (默认 0.2), `L` (默认 2.7)
- **返回**: `ewma_stats`
- **图**: EWMA + 时变控制限 + 渐近控制限

### process_capability_analysis
- **Task Key**: `process_capability`
- **描述**: 过程能力分析 — Cp/Cpk/Pp/Ppk/Cpm + 95%CI + Sigma Level + DPMO
- **params**: `usl`, `lsl`, `target` (Cpm 目标), `transform` ("boxcox", 要求数据和规格限均为正值)
- **返回**: `capability_indices`, `descriptive_stats`
- **图**: 直方图 + 正态拟合 + 规格限

### trend_forecast
- **Task Key**: `trend_forecast`
- **描述**: 线性趋势预测，含 MAPE/RMSE/MAE 精度指标、Durbin-Watson、Ljung-Box、ACF
- **params**: `forecast_steps` (默认 5)
- **返回**: `forecast`, `accuracy_metrics`
- **图**: 2×2 布局: 趋势+预测 / 残差 / ACF / Actual vs Predicted

### anomaly_detect
- **Task Key**: `anomaly_detect`
- **描述**: 异常检测 — IQR / Z-score (单变量) 或 Isolation Forest (多变量) 或 Grubbs 检验
- **params**: `method` ("iqr"|"zscore"|"grubbs"|"isolation_forest"), `contamination` (IsoForest, 默认 0.05)
- **返回**: `anomalies`
- **图**: 异常点标记散点图 + 阈值线

### change_point_detect
- **Task Key**: `change_point`
- **描述**: 变点检测 — 基于 CUSUM 的二元分割法
- **params**: `min_segment`, `n_changepoints` (默认 5)
- **返回**: `segment_statistics` (含分段均值+标准差+变化方向)
- **图**: 数据 + 分段均值线 + 变点标注

### outlier_consensus
- **Task Key**: `outlier_consensus`
- **描述**: 多方法异常共识 — IQR + Z-score + Isolation Forest 投票 (≥2 票 = 高置信)
- **params**: 无
- **返回**: `anomalies`, `method_counts`
- **图**: 高/低置信异常标记散点图

### box_chart
- **Task Key**: `box_chart`
- **描述**: 分组箱线图 — 按类别因子展示数值分布，支持主分类 + 次分类分面，自动附 ANOVA/Kruskal-Wallis 或 t 检验/MWU 统计检验
- **params**: `mode` ("facet" 分面 | "nested" 嵌套组合标签)
- **feature_cols**: `[主分类列]` 或 `[主分类列, 次分类列]`
- **返回**: `group_statistics` (含各分组均值/中位数/标准差/IQR)；统计检验结果嵌入 summary
- **图**: 分组箱线图 + 散点叠加；次分类 ≤ 8 水平时分面展示

### spc_nonparametric
- **Task Key**: `spc_nonparametric`
- **描述**: 非参数控制图 — 基于最佳拟合分布 (Normal/Lognormal/Weibull) 的 CDF 逆推控制限，不假设正态分布
- **params**: `side` ("two-sided" 双侧 | "upper" 单侧上限 | "lower" 单侧下限)
- **返回**: `control_limits` (含 CL/UCL/LCL + 最佳拟合分布), `violations`
- **图**: 原始数据 + 分布拟合控制限 + 违规点标记

### bootstrap_ci
- **Task Key**: `bootstrap_ci`
- **描述**: Bootstrap 置信区间 — 百分位法，不依赖分布假设
- **params**: `statistic` ("mean"|"median"|"std"), `n_bootstrap` (默认 2000), `ci_level` (默认 0.95)
- **返回**: `bootstrap_ci`
- **图**: Bootstrap 分布直方图 + CI 区间

### median_ci
- **Task Key**: `median_ci`
- **描述**: 中位数置信区间 — 基于二项分布符号检验的非参数方法
- **params**: `ci_level` (默认 0.95)
- **返回**: `median_ci`
- **图**: 直方图 + 中位数 + CI 区间

### gage_rr
- **Task Key**: `gage_rr`
- **描述**: 测量系统分析 (Gage R&R) — X-bar and R 法，评估量具重复性和再现性
- **params**: `part_col`, `operator_col`, `tolerance`, `sigma_multiplier` (默认 5.15)
- **返回**: `gage_rr_results`, `ndc` (可区分类别数)
- **图**: 变异源柱状图 (EV/AV/GRR/PV)

### tolerance_interval
- **Task Key**: `tolerance_interval`
- **描述**: 统计容许区间 — 以指定置信度覆盖总体指定比例的区间
- **params**: `coverage` (默认 0.99), `confidence` (默认 0.95), `side` ("two-sided"|"upper"|"lower")
- **返回**: `tolerance_limits`
- **图**: 直方图 + 正态拟合 + 容许限

### survival_analysis
- **Task Key**: `survival_analysis`
- **描述**: Kaplan-Meier 生存分析 + Weibull 拟合 + Log-rank 检验 (可选分组)
- **params**: 无 (使用 `feature_cols[0]` 为事件列, `feature_cols[1]` 为分组列)
- **返回**: `km_survival`, `logrank_test` (如有分组)
- **图**: KM 阶梯曲线 + Weibull 拟合 + 删失标记

---

## 四、服务层 API

### orchestrate(req: AnalysisRequest) -> AnalysisResult
路由分析请求到对应引擎函数，注入默认参数，统一异常处理。

### TASK_REGISTRY: dict[str, Callable]
全部 39 个 task key → 引擎函数的映射表。Task key 按业务场景分为 5 组（定义在 `smartsuite/services/orchestrator.py` 的 `TASK_GROUPS` 中，`web/app.py` 通过 import 引用）。

### DEFAULT_PARAMS: dict[str, dict]
各 task key 的默认参数。编排器会自动合并用户参数到默认参数之上。

---

## 五、报告导出 API

| 函数 | 签名 | 输出格式 |
|------|------|---------|
| `to_excel` | `(result, workbook, sheet_name="分析结果") -> str` | Excel Sheet |
| `to_pdf` | `(result, output_path) -> str` | PDF 文件 |
| `to_ppt` | `(result, output_path, template_path=None) -> str` | PPTX 文件 |
| `to_html` | `(result, output_path) -> str` | 自包含 HTML |

---

## 六、数据 IO API

| 函数 | 用途 |
|------|------|
| `read_excel_range(sheet, range_addr=None)` | 从 Excel 选区读取 DataFrame |
| `validate_data(df, target_col, feature_cols)` | 校验列存在性、类型、缺失值 |
| `preprocess_data(df, features, categorical_cols=None)` | One-Hot 编码 + 中位数插补 |
| `missing_pattern_analysis(df)` | 缺失模式诊断 + 高基数检测 |
| `recommend_analysis(df, target_col=None)` | 基于数据结构智能推荐分析方法 |

---

## 七、综合服务 API

| 函数 | 用途 |
|------|------|
| `process_audit(df, target_col, feature_cols, ...)` | 一站式 6 项健康检查 |
| `batch_analyze(df, target_col, feature_cols, tasks=None)` | 批量运行多个分析 |
| `auto_report(df, target_col, feature_cols=None, ...)` | 一键自动报告 → HTML |
| `export_workbook(df, target_col, feature_cols, output_path)` | 批量分析 → 多 Sheet Excel |
