# SmartSuite AI Agent Skill

> 为 AI 编程助手提供的领域知识文件。帮助 Agent 理解项目结构、分析领域和常见任务模式。

## 项目定位

SmartSuite 是**工艺数据分析工具箱**，面向制造工艺工程师。核心价值：将 Python 统计分析封装为 Excel 按钮 + 中文结果。

- **用户**: 工艺工程师（非程序员）
- **界面**: Excel 功能区（主力） + CLI（辅助） + Web UI（可选）
- **语言**: 代码用英文，用户界面用中文
- **版本**: V1 — 不做实时采集、多人协作、深度学习、多语言、云部署

## 领域术语速查

完整术语表见 `CONTEXT.md`。

| 中文术语 | 英文/代码标识 | 说明 |
|---------|-------------|------|
| 分析请求 | `AnalysisRequest` | 引擎层唯一入口，dataclass |
| 分析结果 | `AnalysisResult` | 引擎层唯一出口，dataclass |
| 要因分析 | Root Cause | 找出影响质量的关键因子 |
| 工艺参数 | Process Parameter / feature_cols | 自变量 X |
| 质量指标 | Quality Characteristic / target_col | 因变量 Y |
| 任务类型 | task | TASK_REGISTRY 中的键名 |
| 分析模板 | template | YAML 文件，描述一次完整分析 |

## 架构约束（不可违反）

```
smartsuite/excel/     ← 唯一可 import xlwings 的层
smartsuite/services/  ← 唯一桥接层
smartsuite/engine/    ← 纯 Python，零 Excel 依赖
smartsuite/web/       ← Flask，依赖 services/，不直接依赖 engine/
```

- `engine/` 禁止 `import xlwings`
- `excel/` 禁止 `import sklearn` / `import statsmodels`
- 引擎函数签名: `(AnalysisRequest) -> AnalysisResult`
- 错误消息使用中文工艺术语
- 引擎模块按领域划分，不按算法拆分

## 任务路由表

`smartsuite/services/orchestrator.py` 中的 `TASK_REGISTRY` 映射 task key → 引擎函数。

### 要因分析 (root_cause.py)

| Task Key | 函数 | 中文名 | 适用场景 |
|----------|------|--------|---------|
| `correlation` | `correlation_analysis` | 相关性分析 | 快速扫描因子影响力 |
| `anova` | `anova_analysis` | 方差分析 | 类别因子显著性 |
| `hypothesis_test` | `hypothesis_test` | 假设检验 | 两组/多组对比 |
| `decision_tree` | `decision_tree_analysis` | 决策树 | 非线性因子重要性 |
| `vif` | `vif_analysis` | 共线性诊断 | 建模前检查 |
| `contingency` | `contingency_analysis` | 列联表 | 两类别变量独立性 |
| `proportion_ci` | `proportion_ci` | 比例置信区间 | 合格率估计 |
| `variance_test` | `variance_test` | 方差齐性检验 | ANOVA 前提验证 |
| `cohens_kappa` | `cohens_kappa` | 评定者一致性 | 两个检验员一致性 |
| `cronbach_alpha` | `cronbach_alpha` | 信度分析 | 量表内部一致性 |
| `distribution_summary` | `distribution_summary` | 分布摘要 | 单变量全貌 |
| `normality_check` | `normality_check` | 正态性评估 | 分布诊断+变换建议 |
| `power_analysis` | `power_analysis` | 功效分析 | 样本量规划 |

### DOE/优化 (doe_opt.py)

| Task Key | 函数 | 中文名 |
|----------|------|--------|
| `regression` | `regression_analysis` | 线性回归 |
| `response_surface` | `response_surface_analysis` | 响应面分析 |
| `grid_search` | `grid_search` | 网格搜索 |
| `multi_objective` | `multi_objective_opt` | 多目标优化 |
| `doe_analysis` | `doe_analysis` | DOE 效应分析 |
| `roc_analysis` | `roc_analysis` | ROC 曲线 |
| `logistic_regression` | `logistic_regression` | Logistic 回归 |
| `lasso_regression` | `lasso_regression` | Lasso 回归 |
| `robust_regression` | `robust_regression` | 稳健回归 |
| `quantile_regression` | `quantile_regression` | 分位数回归 |

### 过程监控 (spc_monitor.py)

| Task Key | 函数 | 中文名 |
|----------|------|--------|
| `spc_xbar` | `xbar_r_chart` | X-bar/R 控制图 |
| `spc_attribute` | `attribute_chart` | 属性控制图 |
| `spc_cusum` | `cusum_chart` | CUSUM 控制图 |
| `spc_ewma` | `ewma_chart` | EWMA 控制图 |
| `process_capability` | `process_capability_analysis` | 过程能力 |
| `trend_forecast` | `trend_forecast` | 趋势预测 |
| `anomaly_detect` | `anomaly_detect` | 异常检测 |
| `change_point` | `change_point_detect` | 变点检测 |
| `outlier_consensus` | `outlier_consensus` | 异常共识 |
| `bootstrap_ci` | `bootstrap_ci` | Bootstrap CI |
| `median_ci` | `median_ci` | 中位数 CI |
| `gage_rr` | `gage_rr` | 量具 R&R |
| `tolerance_interval` | `tolerance_interval` | 容许区间 |
| `survival_analysis` | `survival_analysis` | 生存分析 |

## 常见工作流模式

### 模式 1: 要因筛选 → 建模验证
```
correlation → vif → regression → decision_tree
```
目的：从多个候选因子中筛选关键因子，建立预测模型。

### 模式 2: 类别因子分析
```
anova → (如果显著) → hypothesis_test (Tukey HSD 事后比较)
```
目的：判断类别因子（材料、机台）是否有影响，并找出哪些水平之间有差异。

### 模式 3: 非参数替代路径
```
normality_check → 如果非正态 → kruskal_wallis + bootstrap_ci + median_ci
```
目的：当数据不满足正态性假设时，用非参数方法得到可靠结论。

### 模式 4: SPC 全流程
```
spc_xbar → process_capability → trend_forecast → anomaly_detect
```
目的：从控制图监控 → 能力评估 → 趋势预警 → 异常排查。

### 模式 5: DOE 优化全流程
```
doe_analysis → regression → response_surface → grid_search → multi_objective
```
目的：从效应筛选 → 建模 → 可视化 → 寻优 → 多目标权衡。

### 模式 6: 数据质量诊断
```
missing_pattern_analysis → recommend_analysis → 按推荐顺序执行
```
目的：先了解数据质量，再根据数据结构智能选择分析方法。

## 异常处理约定

1. **引擎函数**: 内部 try/except 捕获异常，返回 `AnalysisResult(status="error", messages=[...])`
2. **编排器**: `orchestrate()` 是最后防线，使用异常类型映射表将异常转为中文消息
3. **错误消息语言**: 所有 `messages` 内容使用中文工艺术语
4. **优雅降级**: 图表生成失败不影响数值结果；子分析失败不影响其他分析

## YAML 模板约定

```yaml
task: <TASK_REGISTRY key>     # 必需
target_col: "<列名>"           # 必需（部分 task 可为空）
feature_cols:                  # 可选
  - "<列1>"
  - "<列2>"
params:                        # 可选
  <key>: <value>
```

模板文件存放在 `templates/` 目录，命名规范: `example_<task_key>.yaml`。

## 测试模式

- **正确性测试**: `test_correctness.py` — 已知标准答案，断言统计量在容差范围内
- **边缘情况**: `test_edge_cases.py` — 空数据、NaN、极值、零方差
- **集成测试**: `test_master_integration.py` — 全部 37 个 task 参数化运行
- **工作流测试**: `test_workflows.py` — 多步骤串联场景
- **领域集成**: `test_integration_chemical.py` 等 — 特定行业数据端到端

## 新增功能 Checklist

当用户要求添加新的分析方法时：

1. [ ] 在对应引擎文件实现 `(AnalysisRequest) -> AnalysisResult` 函数
2. [ ] 包含 `summary` 字段（中文工艺语言结论）
3. [ ] 在 `engine/__init__.py` 导出
4. [ ] 在 `TASK_REGISTRY` 注册（如果适用）
5. [ ] 添加 `DEFAULT_PARAMS`（如果适用）
6. [ ] 创建 YAML 模板到 `templates/`
7. [ ] 添加正确性测试到 `test_correctness.py`
8. [ ] 添加集成测试到 `test_master_integration.py`
9. [ ] 更新 `docs/api-reference.md`

## 常见陷阱

- **`model.params.values`**: 新版 statsmodels 的 `.params` 可能返回 numpy 数组，使用 `np.asarray(model.params)` 替代
- **导入规范**: `from scipy import stats` 后添加 `sp_stats = stats`，不要在函数内重复导入
- **图表初始化**: 在 `figures.append()` 之前确保 `figures = [fig]` 已初始化
- **Cochran Q 二值化**: 使用 `_binary_encode()` 工具函数，不要直接访问 `uv[1]`
- **Tukey HSD**: 使用公开 API (`tukey.pvalues`/`tukey.meandiffs`/`tukey.reject`)，不要访问 `_results_table`
