# SmartSuite 深度自查 Prompt

> **可复用审查 Prompt** — 覆盖 20 个维度：架构、算法、实现、注册链、数据管道、输出层、Web/CLI、模板、测试 4 防线、文档 5 文件、跨切面 5 类、DRY、死代码、可观测、发布。每次发版全量跑，日常 diff 模式。
>
> **协作定位**：`CLAUDE.md`（架构入口）→ `skills/smartsuite-dev.md`（陷阱+模板）→ **本文档**（审查清单）→ `.claude/known-issues.md`（误判豁免）
>
> 项目概况：`~9,000 Python + ~470 JS + 42 YAML` | `39 methods` | `web/ → services/ → engine/` | `4 层防线`

---

## 〇、审查前置

### 0.1 严重度

| 等级 | 含义 | 阻断？ | 示例 |
|------|------|:-----:|------|
| **P0** | 数值错误/崩溃/安全漏洞/数据丢失 | ✅ | Cpk 公式错、空数据 Crash、XSS |
| **P1** | 功能缺陷/误导消息/注册不一致 | ✅ | 缺参考线、异常误翻译、键不匹配 |
| **P2** | 缺防护/缺文档/代码异味 | 建议 | 缺 float()、裸 except |
| **P3** | 风格/优化建议 | 否 | 命名、注释格式 |

### 0.2 环境验证（审查前必跑）

```bash
python --version                       # ≥ 3.10
python -c "import smartsuite; print('OK')"
python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY), 'tasks')"  # 预期 39
python scripts/verify_consistency.py
ruff check smartsuite/
```

### 0.3 误判速查（审查前必读 `.claude/known-issues.md`）

| EX | 模式 | 结论 |
|----|------|------|
| EX-02 | doe_opt 跨模块导入 spc_monitor | ✅ 同属 engine 包 |
| EX-07 | Lenth PSE 单次 trim | ✅ Lenth (1989) 原始定义 |
| EX-08 | `model.model.endog` | ✅ statsmodels 公开属性 |
| EX-09 | anomaly_detect 裸 except | ✅ import 在 try 外 |
| EX-10 | app.js title 未转义 | ✅ 后端数值字段 |
| EX-06 | PDF 字体"硬编码" | ✅ 4 平台 fallback 链 |

### 0.4 变更分流

```bash
git diff --name-only <last-review-commit>..HEAD
# engine/**     → §1+§2+§3+§7(①②③)         services/** → §1+§4+§5
# web/**        → §4+§6                       tests/**    → §7
# docs/**       → §8                          templates/** → §6.4
# pyproject.toml → §4+§9.4+§13               setup_offline* → §9.3+§13
```

---

## 一、架构与结构

### 1.1 三层分离

```bash
grep -rn "from smartsuite\.engine" smartsuite/web/            # 应无输出（禁止）
grep -rn "import xlwings\|import flask" smartsuite/engine/     # 应无输出（禁止）
grep -rn "from smartsuite\.services" smartsuite/engine/        # 应无输出（反向依赖）
grep -rn "from scipy import stats" smartsuite/engine/ | grep -v "as sp_stats"  # 应无输出
```

- [ ] `web/` 不直接 import `engine/`；`engine/` 不含 xlwings/flask
- [ ] `services/` 是唯一桥接层；`engine/` 子模块间引用合理（见 EX-02）
- [ ] `from scipy import stats as sp_stats` 约定一致

### 1.2 数据契约

```bash
# 引擎公开函数签名 + __all__ 一致性
python -c "
from smartsuite.engine import __all__ as e
from smartsuite.services.orchestrator import TASK_REGISTRY as r
m = set(e) - set(r.keys()) - {'__all__'}; x = set(r.keys()) - set(e)
print(f'missing={m}, extra={x}') if m or x else print('✅ 一致')
"
```

- [ ] 全部公开函数: `(AnalysisRequest) -> AnalysisResult`
- [ ] `summary` 使用中文工艺语言；`tables` 键名与 `api-reference.md` 一致
- [ ] 错误返回 `AnalysisResult(status="error", messages=[...])`

### 1.3 模块清单同步

```bash
ls -R smartsuite/ && ls -R tests/  # 对照 CLAUDE.md 源码树逐条核对
```

- [ ] CLAUDE.md 源码树/测试树与实际目录一致；`CONTEXT.md` 术语与代码一致

### 1.4 基础设施

- [ ] `_palette.py`：所有 hex 颜色有效，各组键名语义清晰，cmap 在 matplotlib 中存在
- [ ] `_constants.py`：SPC 常数表（A₂/D₃/D₄/A₃/B₃/B₄/c₄/d₂/d₃）按子组大小正确；效应量阈值与文献一致（Cohen 0.2/0.5/0.8, η² 0.01/0.06/0.14）；α=0.05 一致使用
- [ ] `engine/__init__.py`：matplotlib 全局配置在所有入口生效；中文字体有 fallback 链；`__all__` 与 TASK_REGISTRY 一致

### 1.5 死代码检测 `[NEW]`

```bash
# 搜索仅定义未调用的函数（vulture 或手工）
grep -rn "^def " smartsuite/engine/ | awk '{print $2}' | sed 's/(.*//' | sort > /tmp/defs.txt
grep -rn "\.(" smartsuite/engine/ | grep -oP '\w+(?=\()' | sort -u > /tmp/calls.txt
comm -23 /tmp/defs.txt /tmp/calls.txt

# 搜索 TODO/FIXME/HACK 注释
grep -rn "TODO\|FIXME\|HACK\|XXX" smartsuite/ --include="*.py" | grep -v "test\|__pycache__"
# 搜索 _ 前缀但仍在 __all__ 中导出的函数
grep -rn "^def _" smartsuite/engine/ | grep -v "__init__"
```

- [ ] 是否有仅定义从未调用的函数？（对照 EX-01/EX-03 模式）
- [ ] 是否有未清理的 TODO/FIXME/HACK 标记？
- [ ] `_(参照)` 哨兵等标记是否仍无触发路径？
- [ ] 是否有 import 后未使用的模块？

---

## 二、算法正确性

### 2.1 39 方法公式审查（逐一核对）

```bash
pytest tests/test_engine/test_correctness.py -v --tb=short
grep -rn "手写\|手工\|custom impl" smartsuite/engine/   # 标记手写算法
```

| # | 函数 | 关键验证 | 参考实现 |
|---|------|---------|---------|
| 1 | `correlation` | r 符号正确；t 分布 df=n-2 | `scipy.stats.pearsonr/spearmanr/kendalltau` |
| 2 | `anova` | F=MSB/MSW；η²=SSB/SST；Welch df | `scipy.stats.f_oneway` |
| 3 | `hypothesis_test` | t 等方差/不等方差选择；MW U 统计量 | `scipy.stats.ttest_ind/mannwhitneyu` |
| 4 | `decision_tree` | 重要性归一化 [0,1]；节点纯度 | `sklearn.tree.DecisionTreeRegressor` |
| 5 | `vif` | VIF=1/(1-R²)；条件指数 | `statsmodels...variance_inflation_factor` |
| 6 | `contingency` | χ²；Cramér's V；期望频数≥5 | `scipy.stats.chi2_contingency` |
| 7 | `proportion_ci` | Wilson/Binomial/Agresti-Coull | `statsmodels...proportion_confint` |
| 8 | `variance_test` | Levene/Bartlett/Brown-Forsythe | `scipy.stats.levene/bartlett` |
| 9 | `cohens_kappa` | Kappa SE；加权 Kappa 权重矩阵 | `sklearn.metrics.cohen_kappa_score` |
| 10 | `cronbach_alpha` | α=k/(k-1)×(1-Σσ²_i/σ²_t) | 手工验算 |
| 11 | `distribution_summary` | Fisher vs Pearson 峰度；偏度 SE=√(6/n) | `scipy.stats.skew/kurtosis` |
| 12 | `normality_check` | SW W；AD A²；D'Agostino K² | `scipy.stats.shapiro/anderson/normaltest` |
| 13 | `power_analysis` | Cohen d/f 效应量转换；非中心 λ | `statsmodels.stats.power` |
| 14 | `regression` | OLS 系数；R²/AdjR²；DW 上下界 | `statsmodels.OLS` |
| 15 | `response_surface` | 编码 vs 实际；驻点判别（max/min/saddle） | statsmodels + 手工特征值 |
| 16 | `grid_search` | 分辨率；边界；最值方向 | 手工验算 |
| 17 | `multi_objective` | Pareto 前沿；加权和/ε-约束 | 手工验算 |
| 18 | `doe_analysis` | 效应=2×(ȳ_h-ȳ_l)；Lenth PSE 单次 trim（EX-07） | 手工（Lenth 1989） |
| 19 | `roc_analysis` | AUC 梯形法则；Youden=Se+Sp-1 | `sklearn.metrics.roc_auc_score` |
| 20 | `logistic_regression` | 对数似然；Hosmer-Lemeshow | `statsmodels.Logit` |
| 21 | `lasso_regression` | 正则化路径；CV λ 选择（1-SE/min） | `sklearn.linear_model.LassoCV` |
| 22 | `robust_regression` | Huber M-估计；IRLS 收敛 | `statsmodels.RLM` |
| 23 | `quantile_regression` | ρ_τ(u) 损失函数 | `statsmodels.QuantReg` |
| 24 | `spc_xbar` | A₂/D₃/D₄ 查表值；R 图 LCL≥0 | ASTM/ISO 常数表 |
| 25 | `spc_attribute` | p 图限=p̄±3√(p̄(1-p̄)/n)；Laney p' | 手工验算 |
| 26 | `spc_cusum` | k=Δ/2, h=4~5σ；FIR | Montgomery (2012) |
| 27 | `spc_ewma` | λ 平滑；限=μ₀±Lσ√(λ/(2-λ)) | Montgomery (2012) |
| 28 | `process_capability` | Cp=(USL-LSL)/6σ；Cpk=min(USL-μ,μ-LSL)/3σ | 手工验算 |
| 29 | `trend_forecast` | Holt-Winters 平滑；MAPE | `statsmodels.tsa.holtwinters` |
| 30 | `anomaly_detect` | IsolationForest contamination；异常阈值 | `sklearn.ensemble.IsolationForest` |
| 31 | `change_point` | PELT 惩罚；BIC/MBIC | `ruptures` 库（手写实现） |
| 32 | `outlier_consensus` | 3 方法投票（Z=3/IQR=1.5/MAD=3） | 手工验算 |
| 33 | `bootstrap_ci` | BCa 加速 a；百分位数 vs 基本法 | `scipy.stats.bootstrap` |
| 34 | `median_ci` | Mood's test；Walsh 平均 | 手工验算 |
| 35 | `gage_rr` | %StudyVar=100×σ_g/σ_t；NDC=√2×σ_p/σ_g | AIAG MSA 手册 |
| 36 | `tolerance_interval` | k 因子（正态/非参数）；置信 vs 覆盖 | `scipy.stats.norm.ppf` + ISO 16269-6 |
| 37 | `survival_analysis` | KM 单调递减；log-rank χ² | `lifelines.KaplanMeierFitter` |
| 38 | `box_chart` | IQR=Q3-Q1；须=1.5×IQR；缺口=1.58×IQR/√n | `matplotlib.pyplot.boxplot` |
| 39 | `scatter_plot` | OLS/LOWESS 拟合线；R² 标注 | `scipy.stats.linregress` |
| 40 | `spc_nonparametric` | 分位数控制限；分布拟合（4 种） | scipy 分位数 + `scipy.stats.kstest` |

### 2.2 参考比对

- [ ] 所有手写算法与 scipy/statsmodels 参考值在 1e-6 容差内一致（小样本+大样本）
- [ ] 无依赖第三方库私有 API（注意区分公开属性如 `.endog`，见 EX-08）
- [ ] scipy/statsmodels 版本更新是否影响签名兼容？（如 `ndtr`，commit `d85ac0f`）

---

## 三、实现质量

### 3.1 输入防护

```bash
grep -rn "params\.get.*alpha\|usl\|lsl\|target\|threshold\|quantile" smartsuite/engine/
pytest tests/test_engine/test_fuzz.py -v
pytest tests/test_engine/test_edge_cases.py -v
```

- [ ] 所有 `params.get()` 数值参数有 `float()` try/except 防护（已知 EX-05 豁免）
- [ ] 空 DF / 单行 / 全 NaN / 常量列 / 共线 / n>5000 / 空 feature_cols → 优雅降级

### 3.2 异常处理

```bash
grep -rn "except Exception" smartsuite/engine/ smartsuite/services/     # 逐条审查
grep -n "except\|KeyError\|ValueError\|TypeError" smartsuite/services/orchestrator.py
```

- [ ] 裸 `except Exception` 逐条审查合理性（见 EX-09 模式）
- [ ] KeyError 在引擎内转为中文消息，非依赖 orchestrator 翻译
- [ ] 参数越界/除零有前置校验；orchestrator 异常翻译表（L181-196）映射正确

### 3.3 7 大陷阱排查

| # | 陷阱 | 检查命令 | ☐ |
|---|------|---------|---|
| 1 | PALETTE 键错误 | `grep -rn "PALETTE\[" smartsuite/engine/` → 逐一验证键存在于 `_palette.py` | ☐ |
| 2 | 列约束不一致 | 比对 `_noTargetNeeded`/`_yOnlyTasks` 与引擎实际 `target_col`/`feature_cols` 使用 | ☐ |
| 3 | SPC 颜色约定 | 控制限=金黄虚线 / 规格限=红实线 / 目标值=灰点线 | ☐ |
| 4 | `float()` 无防护 | 同 §3.1 | ☐ |
| 5 | orchestrator 误翻译 | KeyError 不能翻译为"数据中缺少必要的列" | ☐ |
| 6 | 参数标签语义 | `PARAM_META` 共享 key 多任务语义一致，不一致用 `key@task_name` | ☐ |
| 7 | statsmodels 兼容 | `model.params`→`np.asarray()`；`sum(axis=None)`→`.sum().sum()` | ☐ |

### 3.4 DRY 审查 `[NEW]`

> 39 个函数共享参数提取→校验→计算→图表→返回 boilerplate，重复是 bug 温床。

```bash
# 检测相似代码块（手工抽样比对各函数结构）
grep -c "AnalysisResult(" smartsuite/engine/*.py
grep -c "req.params.get" smartsuite/engine/*.py
grep -c "plt.close\|plt.clf" smartsuite/engine/*.py
```

- [ ] `float()` 防护模式是否在 39 个函数中一致？是否应抽取为公共 `_safe_float()`？
- [ ] 参考线绘制（USL/LSL/UCL/LCL/CL/Target）是否在每个 SPC 函数中重复实现？
- [ ] `AnalysisResult` 错误返回模式是否一致？是否应抽取为 `_error_result(task, msg)`？
- [ ] Figure 创建+关闭是否每个函数都手工管理？
- [ ] 抽样对比 3 个函数的 body 结构，相似度 > 70% 应考虑抽取公共模板

### 3.5 魔法数字审查 `[NEW]`

```bash
# 搜索代码中的硬编码数值
grep -rn "= 0\.05\|= 1\.96\|= 1\.5\|= 3[^0-9.]\|= 10[^0-9.]" smartsuite/engine/ | grep -v "_constants\|test\|__pycache__\|#\|alpha\|p_value"
```

- [ ] 统计阈值是否全部归入 `_constants.py`？（α=0.05, Z=1.96, IQR 须长=1.5, Z 异常=3, 类别检测≤10）
- [ ] 是否有散落在函数体内的硬编码数值应提升为常量？
- [ ] matplotlib 样式参数（figsize, dpi, linewidth, fontsize）是否一致？

### 3.6 类型注解完整性 `[NEW]`

> CLAUDE.md 声明使用 PEP 604 语法（`list[str]` | `dict[str, pd.DataFrame]`）。

```bash
# 检查公开函数是否有完整类型注解
grep -rn "^def [^_]" smartsuite/engine/ | grep -v "->"
# 检查 Any 过度使用
grep -rn ": Any\|-> Any" smartsuite/engine/ smartsuite/services/ | wc -l
```

- [ ] 全部 39 个引擎公开函数是否有返回值类型注解 `-> AnalysisResult`？
- [ ] `dict[str, Any]` 是否可用更精确的类型替代？
- [ ] `req.params.get("key")` 的返回类型推断是否正确？

### 3.7 废弃 API

```bash
grep -rn "sum(axis=None)" smartsuite/ --include="*.py"
grep -rn "\.append(" smartsuite/ --include="*.py" | grep -v "list\.\|\.pyc"
grep -rn "inplace=True" smartsuite/ --include="*.py"
```

- [ ] 无不安全的 `sum(axis=None)`、`DataFrame.append()`、`scipy.stats.mode()` 旧签名
- [ ] `scipy.stats.ndtr` 签名与新版本兼容

---

## 四、注册链与前后端一致性

### 4.1 11 步检查表 + 键集合一致性

```bash
python -c "
from smartsuite.services.orchestrator import TASK_REGISTRY, DEFAULT_PARAMS, TASK_LABELS, TASK_GROUPS
r = set(TASK_REGISTRY); p = set(DEFAULT_PARAMS); l = set(TASK_LABELS)
g = set(v for vs in TASK_GROUPS.values() for v in vs)
print(f'REGISTRY={len(r)} PARAMS={len(p)} LABELS={len(l)} GROUPS={len(g)}')
if r != p: print(f'❌ REGISTRY≠PARAMS: {r^p}')
if r != l: print(f'❌ REGISTRY≠LABELS: {r^l}')
if g - r: print(f'❌ GROUPS 孤立任务: {g-r}')
import os
for t in r:
    if f'example_{t}.yaml' not in os.listdir('templates/'):
        print(f'⚠️ 缺模板: example_{t}.yaml')
print('✅ 全部一致' if r==p==l and not (g-r) else '')
"
```

- [ ] 11 步注册链逐条确认（详见 `CLAUDE.md` 新增方法清单）
- [ ] `TASK_REGISTRY` = `DEFAULT_PARAMS` = `TASK_LABELS`（39/39）
- [ ] `TASK_GROUPS` 无孤立任务；`TASK_PARAMS`(JS) ⊆ TASK_REGISTRY；`PARAM_META` 覆写 task_name 有效

### 4.2 参数通道（6 位置一致性）

> `TASK_PARAMS[task]`(JS) → `PARAM_META[key]`(JS) → `PARAM_META[key@task]`(JS) → `DEFAULT_PARAMS[task]`(PY) → `orchestrate()` → `req.params.get()`(引擎)

- [ ] 参数在 6 个位置的默认值/类型/语义一致；`column` 类型空值→跳过；`select` option value 与引擎一致
- [ ] `default=''` → `type="text"` → 引擎必须 `float()` 防护

### 4.3 差分测试

```bash
pytest tests/test_services/test_differential.py -v
pytest tests/test_services/test_manual_parity.py -v
```

- [ ] CLI vs Web 数值一致（容差 < 0.005）；summary + tables 列名/行数相同；四路一致性通过

---

## 五、数据与输出管道

### 5.1 数据管道 (`services/data_io.py`)

- [ ] `validate_data`：列存在性双覆盖（target + features）；非数值转换；缺失值消息准确；样本量阈值合理
- [ ] `preprocess_data`：中位数填充无泄漏；One-Hot 有类别爆炸保护（max_categories）；nunique≤10 阈值合理；`known_cat_map` 正确消费；`_(参照)` 哨兵无触发路径（EX-01/EX-03）
- [ ] CSV 支持正确集成（commit `b2a366d`）；空数据有消息提示；`recommend_analysis` 建议合理

### 5.2 输出层 (`services/reporter.py`)

```bash
grep -n "font\|Font\|ttf\|ttc\|PingFang\|Noto\|SimHei\|msyh" smartsuite/services/reporter.py
```

- [ ] `to_excel/pdf/ppt/html` 签名一致；空 tables/figures 正确处理；HTML 自包含（base64 图）
- [ ] 字体 fallback 链覆盖 Windows/macOS/Linux；无未保护的硬编码路径
- [ ] PPT 失败→Excel 降级；DPI 常量统一（`_CHART_DPI=150`, `_PDF_DPI=200`）；`plt.close(fig)` 防泄漏

### 5.3 综合审计 (`services/audit.py`)

- [ ] `process_audit` 覆盖常用分析组合；`batch_analyze` 部分失败不中断；`auto_report` 结构合理

---

## 六、Web / CLI / 模板

### 6.1 Flask + API (`web/app.py`, `web/api.py`)

- [ ] 所有路由有错误处理（非 500）；`TASK_GROUPS`/`TASK_LABELS` 通过 import 引用非硬编码
- [ ] 文件上传有大小限制 + 类型白名单（.xlsx/.xls/.csv）
- [ ] `run_analysis()` 正确处理 `categorical_cols`；JSON 格式与 `app.js` 匹配；错误消息中文

### 6.2 前端 (`web/static/app.js`)

```bash
grep -n "_noTargetNeeded\|_yOnlyTasks" smartsuite/web/static/app.js
grep -n "TASK_PARAMS\|PARAM_META\|PARAM_LABELS" smartsuite/web/static/app.js
grep -n "escHtml\|innerHTML\|document.write\|eval" smartsuite/web/static/app.js
```

- [ ] 用户列名经 `escHtml()` 转义（XSS）；`_noTargetNeeded`/`_yOnlyTasks` 与引擎一致
- [ ] `getParams()` 空字符串→跳过；`PARAM_META` 任务覆写覆盖所有歧义参数
- [ ] 图表错误兜底；文件下载触发浏览器下载；响应式布局

### 6.3 CLI (`cli.py`)

- [ ] `smartsuite run` 正确加载 YAML 模板；优先级：CLI > YAML > DEFAULT
- [ ] `smartsuite list` 列出 39 方法；`matplotlib.use('Agg')` 在 import 前；CLI vs Web 输出一致

### 6.4 YAML 模板 (`templates/`)

```bash
python -c "
import os, yaml
from smartsuite.services.orchestrator import TASK_REGISTRY
for f in sorted(os.listdir('templates/')):
    if f.endswith('.yaml'):
        try:
            with open(f'templates/{f}') as fh: t = yaml.safe_load(fh)
            if t and 'task' in t and t['task'] not in TASK_REGISTRY:
                print(f'❌ {f}: invalid task \"{t[\"task\"]}\"')
            else: print(f'✅ {f}')
        except Exception as e: print(f'❌ {f}: {e}')
"
```

- [ ] 42 模板全部可解析；task 字段有效；参数与 `DEFAULT_PARAMS` 兼容
- [ ] `example_full_suite.yaml` 包含全部 39 方法；结构一致（task→params→target→features→output）

---

## 七、测试防线

### 7.1 39×4 覆盖率矩阵

```bash
pytest tests/ -v --tb=short 2>&1 | tail -40
echo "=== ① correctness ===" && pytest tests/test_engine/test_correctness.py -q
echo "=== ② invariants  ===" && pytest tests/test_engine/test_invariants.py -q
echo "=== ③ fuzz        ===" && pytest tests/test_engine/test_fuzz.py -q
echo "=== ④ differential===" && pytest tests/test_services/test_differential.py -q
```

| 函数 | ① | ② | ③ | ④ | | 函数 | ① | ② | ③ | ④ |
|------|:-:|:-:|:-:|:-:|------|------|:-:|:-:|:-:|:-:|
| correlation |☐|☐|☐|☐| | grid_search |☐|☐|☐|☐|
| anova |☐|☐|☐|☐| | multi_objective |☐|☐|☐|☐|
| hypothesis_test |☐|☐|☐|☐| | doe_analysis |☐|☐|☐|☐|
| decision_tree |☐|☐|☐|☐| | roc_analysis |☐|☐|☐|☐|
| vif |☐|☐|☐|☐| | logistic_regression |☐|☐|☐|☐|
| contingency |☐|☐|☐|☐| | lasso_regression |☐|☐|☐|☐|
| proportion_ci |☐|☐|☐|☐| | robust_regression |☐|☐|☐|☐|
| variance_test |☐|☐|☐|☐| | quantile_regression |☐|☐|☐|☐|
| cohens_kappa |☐|☐|☐|☐| | spc_xbar |☐|☐|☐|☐|
| cronbach_alpha |☐|☐|☐|☐| | spc_attribute |☐|☐|☐|☐|
| distribution_summary |☐|☐|☐|☐| | spc_cusum |☐|☐|☐|☐|
| normality_check |☐|☐|☐|☐| | spc_ewma |☐|☐|☐|☐|
| power_analysis |☐|☐|☐|☐| | process_capability |☐|☐|☐|☐|
| regression |☐|☐|☐|☐| | trend_forecast |☐|☐|☐|☐|
| response_surface |☐|☐|☐|☐| | anomaly_detect |☐|☐|☐|☐|
| change_point |☐|☐|☐|☐| | outlier_consensus |☐|☐|☐|☐|
| bootstrap_ci |☐|☐|☐|☐| | median_ci |☐|☐|☐|☐|
| gage_rr |☐|☐|☐|☐| | tolerance_interval |☐|☐|☐|☐|
| survival_analysis |☐|☐|☐|☐| | box_chart |☐|☐|☐|☐|
| scatter_plot |☐|☐|☐|☐| | spc_nonparametric |☐|☐|☐|☐|

### 7.2 数学不变量（防线②）

| 函数 | 不变量 | | 函数 | 不变量 |
|------|--------|-|------|--------|
| correlation | r∈[-1,1] | | proportion_ci | CI⊂[0,1] |
| anova/hypothesis_test | p∈[0,1] | | roc_analysis | AUC∈[0,1] |
| vif | VIF≥1 | | cronbach_alpha | α∈[-∞,1] |
| regression | R²∈[0,1]; AdjR²≤R² | | cohens_kappa | κ∈[-1,1] |
| process_capability | Cpk≤Cp; Ppk≤Pp | | contingency | Cramér's V∈[0,1] |
| survival_analysis | KM↓; S(t)∈[0,1] | | decision_tree | Σimp=1; 每个∈[0,1] |
| spc_xbar | R 图 LCL≥0 | | bootstrap_ci | 下界≤上界 |
| spc_attribute | p/np 控制限≥0 | | spc_cusum | CUSUM 初值=0 |
| grid_search | opt∈[min,max] of grid | | | |

- [ ] 每个不变量有测试用例；边界条件下（n=2, σ=0）也通过

### 7.3 边界/模糊/集成/E2E

```bash
pytest tests/test_engine/test_fuzz.py tests/test_engine/test_edge_cases.py -v
pytest tests/test_integration*.py -v
pytest tests/test_web_e2e.py -v 2>&1 || echo "(需服务器运行)"
pytest tests/test_workflows.py -v
```

- [ ] 空 DF/单行/全 NaN/常量列/共线/大样本/不等子组/零方差组 — 全覆盖
- [ ] 7 个集成测试文件通过；E2E 通过（如服务器运行）；随机种子固定可复现
- [ ] assertion 具体（非仅 `assert result is not None`）；错误路径有覆盖

---

## 八、文档

### 8.1 职责边界

> `CLAUDE.md`(AI 入口) ≠ `README.md`(用户入口) ≠ `user-manual.md`(操作指南) ≠ `api-reference.md`(签名查阅) ≠ `skill.md`(决策树) ≠ `CONTEXT.md`(术语表)

- [ ] 各文档不跨职责重复；交叉引用链接有效；`CONTEXT.md` 术语与代码一致

### 8.2 API 参考 / 用户手册 / 决策树

```bash
python -c "
from smartsuite.services.orchestrator import TASK_LABELS
with open('docs/api-reference.md', encoding='utf-8') as f: c = f.read()
for t, l in TASK_LABELS.items():
    if t not in c: print(f'❌ api-reference 缺失: {t} ({l})')
"
```

- [ ] `api-reference.md` 覆盖 39 方法（签名 + tables 键名 + 参数与 DEFAULT_PARAMS 一致）
- [ ] `user-manual.md` 39 方法六段式完整；截图与 Web UI 一致；FAQ 覆盖常见问题
- [ ] `skill.md` 决策树覆盖 39 方法入口路径；新增方法（如 scatter_plot）已更新

### 8.3 CLAUDE.md 自洽

- [ ] 参考文件索引指向实际存在的文档；常用命令全部可执行；ruff per-file-ignores 覆盖所有例外

---

## 九、跨切面一致性

### 9.1 PALETTE 配色 + SPC 颜色约定

```bash
grep -rn "PALETTE\[" smartsuite/engine/ --include="*.py" | grep -v "test\|__pycache__"
python -c "from smartsuite.engine._palette import PALETTE; print({k:list(v.keys()) for k,v in PALETTE.items()})"
```

- [ ] 每个 `PALETTE["X"]["Y"]` 的 X 和 Y 在 `_palette.py` 中存在
- [ ] 控制限(UCL/LCL/CL)=`control["primary"]`(金黄#d4a017,虚线`--`)
- [ ] 规格限(USL/LSL)=`anomaly["primary"]`(红#e31a1c,实线`-`)
- [ ] 目标值(Target)=`direction["zero"]`(灰#969696,点线`:`)
- [ ] 正/负/零=方向色；好/警告/坏=判级色；cmap 在 matplotlib 中存在

### 9.2 中文结论

```bash
grep -rn "summary=" smartsuite/engine/ --include="*.py" | head -50
```

- [ ] 39 方法 summary 均为中文；精度统一（p≤4位,R²≤3位,Cp/Cpk≤2位）
- [ ] 效应量判定用语统一（强 η²>0.14 / 中>0.06 / 弱≤0.06）
- [ ] SPC 判异描述一致（"超出控制限""连续上升/下降""链""周期"）
- [ ] 无英文变量名混入中文句子

### 9.3 跨平台 + 脚本对称

- [ ] 字体 fallback 链覆盖三平台（见 EX-06）；路径用 `os.path.join`/`pathlib`
- [ ] `run_smartsuite.bat` ↔ `run_smartsuite.sh` 逻辑等价
- [ ] `setup_offline.bat` ↔ `setup_offline.sh` 命令数量/步骤/错误处理一致

### 9.4 依赖版本

```bash
grep -A1 ">=\|<==" pyproject.toml | grep -v "^--$"
pip install --dry-run -e ".[all]" 2>&1 | grep -i "error\|conflict"
```

- [ ] 仅保留下限约束（按 commit `1a89aee`）；无意外上限
- [ ] Python 3.10–3.13 均可安装；`[project.scripts]` 入口点正确

### 9.5 已知问题验证

- [ ] EX-01/EX-03: `cat_map` 哨兵无触发路径（仍成立？）
- [ ] EX-04: spc_nonparametric ±2σ 用 `spec["secondary"]`（已修复，未 regress？）
- [ ] EX-05: threshold/quantile 缺 float() 防护（仍缺失？）
- [ ] EX-06~EX-11: 各豁免仍成立（代码未变更致失效？）

---

## 十、性能与资源

### 10.1 大样本 + 复杂性

- [ ] n>5000, 39 方法均在 30s 内完成；`grid_search` 高分辨率不组合爆炸；`bootstrap_ci` n≥10000 可接受

### 10.2 内存管理

```bash
grep -rn "plt\.close\|plt\.clf\|plt\.cla" smartsuite/ --include="*.py"
# Figure 创建数 vs 关闭数
echo "Figure creates:" && grep -rn "plt\.figure\|plt\.subplots\|Figure(" smartsuite/engine/ --include="*.py" | wc -l
echo "Figure closes:" && grep -rn "plt\.close\|plt\.clf" smartsuite/engine/ --include="*.py" | wc -l
```

- [ ] 每个 Figure 创建有对应 `plt.close()`；批量分析正确清理；Web 长时间运行无泄漏

### 10.3 无头环境

- [ ] `matplotlib.use('Agg')` 在 CLI 和 Web 入口的 import 前设置；无 `plt.show()` 依赖

---

## 十一、安全

### 11.1 Web 安全

- [ ] 文件上传有大小限制 + 类型白名单（.xlsx/.xls/.csv）
- [ ] 列名经 `escHtml()` 转义（见 EX-10）；`/api/download` 有目录穿越防护
- [ ] 错误消息不泄露服务器路径

### 11.2 输入安全

- [ ] YAML 用 `safe_load()`（非 `load()`）；无 pickle 反序列化；无 `eval()`/`exec()`

---

## 十二、可观测性 `[NEW]`

```bash
grep -rn "logger\|logging" smartsuite/engine/ smartsuite/services/ smartsuite/web/ --include="*.py" | grep -v "test\|__pycache__"
grep -rn "print(" smartsuite/engine/ --include="*.py" | grep -v "test\|__pycache__\|#"
```

- [ ] 引擎层有 logger（非 print）记录关键路径（输入参数、样本量、异常、耗时）
- [ ] orchestrator 异常翻译同时记录原始异常（`logger.exception` 或 `logger.error` + traceback）
- [ ] Web API 有请求日志（task + 数据维度 + 耗时 + 状态码）
- [ ] 启动日志记录 Python 版本、依赖版本、matplotlib 后端、字体配置

---

## 十三、发布与工作流 `[NEW]`

### 13.1 打包完整性

```bash
# 模拟全新环境安装验证
pip install --no-deps --no-build-isolation -e .
python -c "from smartsuite.engine import *; print(f'{len([x for x in dir() if not x.startswith(\"_\")])} exports')"
# 验证 setup_offline 流程
setup_offline.bat download 2>&1 | tail -5   # Windows
bash setup_offline.sh download 2>&1 | tail -5  # macOS/Linux
```

- [ ] `pyproject.toml` 中 `[tool.setuptools.packages.find]` 正确包含所有子包
- [ ] `MANIFEST.in` 是否需要（含 templates/、docs/images/ 等非 Python 资源）？
- [ ] `setup_offline download` 生成的 `requirements.txt` 包含完整依赖（无缺失）
- [ ] 一键启动脚本（`run_smartsuite.bat`/`.sh`）在全新克隆后可直接运行

### 13.2 发版检查清单

```bash
git log --oneline -20                         # commit 可读性
git diff origin/main..HEAD --name-only        # 变更范围
```

- [ ] 是否有未提交的本地变更？commit message 是否自包含可追溯？
- [ ] `CHANGELOG.md` 是否需要（或 release notes 是否覆盖了面向用户的变化）？
- [ ] PR template 是否存在（`.github/PULL_REQUEST_TEMPLATE.md`）？
- [ ] 发版 tag 是否与 `pyproject.toml` 版本号一致？

---

## 十四、执行建议

### 日常模式（commit 前，< 2 分钟）

```bash
python scripts/verify_consistency.py
pytest tests/test_engine/test_invariants.py -q
ruff check smartsuite/
```

### Diff 模式（PR 审查）

按 §0.4 变更分流规则选取对应维度 + 运行关联测试：

```bash
git diff --name-only origin/main..HEAD
pytest tests/ -v -k "<related_pattern>" --tb=short
```

### 完整模式（发版前，七遍审查）

```
第一遍 §0.2 环境验证 + §0.4 变更判断
第二遍 §4 注册链全量比对（最易发现遗漏）
第三遍 §1 架构 + §4.2 前后端参数 + §1.4 基础设施 + §1.5 死代码
第四遍 §3 实现质量（7 陷阱 + DRY + 魔法数字 + 类型注解 + 废弃 API）
第五遍 §2 算法正确性（39 方法公式审查）+ §5 数据管道 + §6 Web/CLI/模板
第六遍 §7 测试防线（39×4 矩阵 + 不变量 + 边界/集成/E2E）+ §10 性能 + §11 安全 + §12 可观测
第七遍 §8 文档 + §9 跨切面一致性（PALETTE+结论+跨平台+依赖+已知问题）+ §13 发布
```

### 审查后

- [ ] 问题按 P0-P3 分级（§0.1）；P0/P1 阻断修复
- [ ] 误判同步到 `.claude/known-issues.md`
- [ ] 报告存为 `.claude/code-review-report-YYYY-MM-DD.md`
- [ ] 修复后重跑对应维度验证

---

*随项目演进持续更新。新增方法/架构变更/新陷阱模式/豁免变更后同步修订。*
