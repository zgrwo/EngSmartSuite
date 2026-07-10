---
name: smartsuite-dev
description: SmartSuite 项目开发技能 — 工艺数据分析工具箱的代码规范、常见陷阱、修复模板与最佳实践。当在此项目中新增分析函数、修复 SPC/DOE/要因分析相关问题、修改 Web UI 参数面板、或处理 PALETTE/前端-后端一致性时使用。
---

# SmartSuite 开发技能

> **面向 AI 编程助手**：本项目是工艺数据分析工具箱（39 个分析方法，Flask Web UI + Python API），约 9,000 行 Python 代码 + 470 行 JavaScript。本文档提炼自 126 次 commit 中反复出现的 bug 模式和修复规范。
>
> **协作文档**：开发规范 → `CLAUDE.md` | 术语 → `CONTEXT.md` | 决策树 → `docs/skill.md` | API → `docs/api-reference.md`

## 触发条件

当任务涉及以下任一模块时，应加载本技能：
- `smartsuite/engine/` — 引擎层（spc_monitor / root_cause / doe_opt）
- `smartsuite/web/` — Web UI 层（app.js / api.py / app.py）
- `smartsuite/services/` — 桥接层（orchestrator / data_io）
- `smartsuite/engine/_palette.py` — 可视化配色
- `docs/user-manual.md` — 用户手册
- `tests/` — 测试文件

## 架构速查

```
web/ → services/ → engine/
        services/ ← 唯一桥接层，web 不可直接 import engine/
```

- 引擎函数统一签名：`(AnalysisRequest) -> AnalysisResult`
- `AnalysisResult` 必须包含 `summary`（中文工艺语言）、`tables`（dict[str, DataFrame]）、`figures`（list[Figure]）
- 错误消息使用中文工艺术语，不暴露 Python traceback

---

## 🔴 高发陷阱（按频率排序）

### 陷阱 1：PALETTE 键错误

**现象**：`KeyError: 'secondary'` → 误导为"数据中缺少必要的列"

**根因**：`PALETTE` 是嵌套字典，各组有不同的二级键。访问不存在的键会触发 `KeyError`，被 orchestrator 误翻译。

**检查方法**：在写入 `PALETTE["X"]["Y"]` 前，确认 `Y` 存在于 `_palette.py` 中对应组的定义。

**PALETTE 有效键速查**：
```
data:       primary, secondary, tertiary, scatter, line
target:     primary, fill, band
anomaly:    primary, fill, line          ← 没有 "secondary"！
control:    primary                       ← 金黄色控制限
spec:       primary, secondary, tertiary, target
center:     primary, secondary
judge:      good, warn, bad
contrast:   a, b, c, d
direction:  positive, negative, zero
cmap:       correlation, response, sequential, heatmap
misc:       grid, background, edge
```

**修复模板**：
```python
# ❌ 错误
color=PALETTE["anomaly"]["secondary"]  # 不存在

# ✅ 正确 — 先用脚本验证键存在
color=PALETTE["spec"]["secondary"]     # 橙色警告线
# 或
color=PALETTE["anomaly"]["primary"]    # 红色异常线
```

### 陷阱 2：前端列约束与引擎不一致

**现象**：Web UI 要求选 X 列，但引擎根本不使用 `feature_cols`；或要求选 Y，但引擎不需要 `target_col`。

**检查清单**（每次修改引擎函数签名后必查）：
1. 该函数使用 `req.target_col` 吗？→ 如果不使用，应加入 `_noTargetNeeded`
2. 该函数使用 `req.feature_cols` 吗？→ 如果不使用，应加入 `_yOnlyTasks`
3. 手册协同要求与 `_yOnlyTasks` / `_noTargetNeeded` 一致吗？

**关键代码位置**：`app.js` 第 328-348 行

```javascript
// _noTargetNeeded: 不需要选择 Y 列
const _noTargetNeeded = new Set([
    'vif', 'cohens_kappa', 'cronbach_alpha', 'power_analysis',
]);

// _yOnlyTasks: 不需要选择 X 列（仅需 Y）
const _yOnlyTasks = new Set([
    'process_capability', 'trend_forecast', 'anomaly_detect',
    'power_analysis', 'spc_nonparametric',
    'distribution_summary', 'normality_check', 'proportion_ci',
    'bootstrap_ci', 'median_ci', 'tolerance_interval', 'change_point',
    'spc_xbar', 'spc_cusum', 'spc_ewma', 'spc_attribute',
]);
```

### 陷阱 3：SPC 控制限/规格限颜色约定

**规则**（全局统一，触犯即 bug）：
- **控制限 (UCL/LCL/CL)**：`PALETTE["control"]["primary"]`（金黄 #d4a017），**虚线 `--`**
- **规格限 (USL/LSL)**：`PALETTE["anomaly"]["primary"]`（红 #e31a1c），**实线 `-`**
- **目标值 (Target)**：`PALETTE["direction"]["zero"]`（灰 #969696），点线 `:`
- **±2σ/±1σ 警告线**：保持原样（橙色/灰色点线，辅助参考）

所有 7 个 SPC 函数必须遵守：xbar_r_chart, attribute_chart, cusum_chart, ewma_chart, process_capability_analysis, spc_nonparametric, box_chart。

### 陷阱 4：`float()` 参数转换无防护

**场景**：前端参数输入框默认值 `''` 导致 `type="text"`（非 `number`），用户可能输入非数值。

**修复模板**：
```python
# ❌ 危险
usl = float(req.params.get("usl"))

# ✅ 安全 — 三处均需防护（USL/LSL/Target）
usl = req.params.get("usl")
if usl is not None:
    try:
        usl_val = float(usl)
    except (ValueError, TypeError):
        usl_val = None
    if usl_val is not None:
        ax.axhline(usl_val, ...)
```

**影响范围**：xbar_r_chart, process_capability_analysis, logistic_regression（threshold 参数）。

### 陷阱 5：orchestrator 异常消息误翻译

**现象**：引擎 `KeyError` → 用户看到"数据中缺少必要的列"（完全误导）。

**根因**：`orchestrator.py` 第 181-196 行的异常类型映射表把所有 `KeyError` 都翻译为列缺失。

**正确做法**：引擎函数内部用 `AnalysisResult(status="error", messages=[...])` 返回明确的中文错误，而非依赖 orchestrator 翻译。

```python
# ✅ 引擎内部直接返回清晰错误
if subgroup_col not in req.data.columns:
    return AnalysisResult(
        task="spc_xbar", status="error",
        messages=[f"子组列「{subgroup_col}」不存在于数据中。可用列: {list(req.data.columns)[:10]}"],
    )
```

### 陷阱 6：前端参数标签语义错误

**案例**：`spc_nonparametric` 的 `side` 参数，前端选项写"上侧 (越大越好)"，实际引擎中 `upper` 表示"只设上限，越小越好"。

**根因**：`PARAM_META` 的 `side` 被多个任务共享，但语义不同（tolerance_interval vs spc_nonparametric）。

**修复模式**：使用任务特定覆写 `key@task_name`：
```javascript
// 通用定义（tolerance_interval 使用）
side: {
    type: 'select', label: '检验侧',
    options: [['two-sided', '双侧'], ['upper', '单侧上限'], ['lower', '单侧下限']]
},

// spc_nonparametric 任务特定覆写
'side@spc_nonparametric': {
    type: 'select', label: '控制限方向',
    options: [
        ['two-sided', '双侧 (通用品质指标)'],
        ['upper', '单侧上限 (越小越好: 颗粒度、缺陷率)'],
        ['lower', '单侧下限 (越大越好: 得率、强度)']
    ]
},
```

### 陷阱 7：statsmodels 兼容性

- `model.params` 可能返回 numpy 数组而非 pandas Series → 用 `np.asarray(model.params)` 不用 `.values`
- pandas 新版本 `sum(axis=None)` → 跨版本应链式调用 `.sum().sum()`
- statsmodels 警告消息含 `'failed'` 词 → 不要按此关键词判断分析失败

---

## 🟢 最佳实践模板

### 模板 1：新增引擎函数

```python
def new_analysis(req: AnalysisRequest) -> AnalysisResult:
    """功能描述（中文）。关键输出指标。

    参数 (params):
        param1: 含义 (默认值)
        param2: 含义 (默认值)

    数据要求:
        target_col: Y 列描述
        feature_cols[0]: X 列描述
    """
    # 1. 数据提取与校验
    data = req.data[req.target_col].dropna()
    if len(data) < MIN_SAMPLES:
        return AnalysisResult(
            task="new_task", status="error",
            messages=[f"有效数据不足(至少{MIN_SAMPLES}个点)"],
        )

    # 2. 参数提取（带默认值 + float 防护）
    alpha = req.params.get("alpha", 0.05)
    if not isinstance(alpha, (int, float)):
        try:
            alpha = float(alpha)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="new_task", status="error",
                messages=[f"参数 alpha 值无效: {alpha}"],
            )

    # 3. 核心计算
    # ...

    # 4. 图表渲染（使用 PALETTE）
    fig = Figure(figsize=(10, 6))
    ax = fig.add_subplot(111)
    ax.axhline(cl, color=PALETTE["control"]["primary"], linestyle="--",
               linewidth=1.5, label=f"CL={cl:.4f}")
    # ...

    # 5. 返回模型
    return AnalysisResult(
        task="new_task",
        tables={"main_table": pd.DataFrame({...})},
        figures=[fig],
        summary=f"中文工艺结论。关键指标={value:.4f}",
        metadata={"key": value},
    )
```

### 模板 2：新增分析方法的 11 步注册链

```
□ 1. engine/xxx.py           — 实现 AnalysisRequest → AnalysisResult
□ 2. engine/__init__.py      — 导出函数名
□ 3. orchestrator.py         — TASK_REGISTRY 注册
□ 4. orchestrator.py         — DEFAULT_PARAMS 添加默认值
□ 5. orchestrator.py         — TASK_LABELS + TASK_GROUPS 添加条目
□ 6. app.js                  — TASK_PARAMS 添加参数默认值
□ 7. templates/              — 创建 YAML 模板
□ 8. tests/                  — 至少覆盖 4 层防线中的 2 层（correctness + invariants 必做）
□ 9. docs/api-reference.md   — 更新 API 参考
□ 10. docs/skill.md          — 更新决策树（如引入新分析场景）
□ 11. docs/user-manual.md    — 更新用户手册（如面向用户的新方法）
```

### 模板 3：box_chart / SPC 函数新增 USL/LSL/UCL/CL 参数

当 SPC/图表函数需要新增参考线参数时，三处同步修改：

**引擎端**：
```python
# 提取参数并安全转换
def _draw_ref_lines(ax):
    for val, color, style, label in _ref_lines:
        ax.axhline(val, color=color, linestyle=style, linewidth=1.0, alpha=0.8, label=label)
    if _ref_lines:
        ax.legend(fontsize=6, loc="upper right")

_ref_lines: list[tuple[float, str, str, str]] = []
for key, color, style in [
    ("usl", PALETTE["anomaly"]["primary"], "-"),     # 红色实线
    ("lsl", PALETTE["anomaly"]["primary"], "-"),     # 红色实线
    ("ucl", PALETTE["control"]["primary"], "--"),    # 黄色虚线
    ("lcl", PALETTE["control"]["primary"], "--"),    # 黄色虚线
    ("cl",  PALETTE["control"]["primary"], "--"),    # 黄色虚线
]:
    val = req.params.get(key)
    if val is not None:
        try:
            _ref_lines.append((float(val), color, style, key.upper()))
        except (ValueError, TypeError):
            pass
```

**前端 TASK_PARAMS**：
```javascript
task_name: { ..., usl: '', lsl: '', ucl: '', lcl: '', cl: '', target: '' },
```

### 模板 4：Web UI 参数面板完整流程

当修改/新增参数时，确保三处一致：

```
1. app.js TASK_PARAMS[task] = { key: defaultValue }     ← 控制显示哪些参数
2. app.js PARAM_META[key] = { type, label, options }    ← 控制渲染方式（可选）
3. app.js PARAM_LABELS[key] = '中文标签'                  ← 中文显示名（可选）
4. orchestrator.py DEFAULT_PARAMS[task] = { key: val }  ← Python 端默认值
```

**特别注意**：
- `''` 默认值 → 输入框 `type="text"`，用户可输入非数值 → 引擎必须加 `float()` 防护
- `number` 默认值 → 输入框 `type="number"`，浏览器约束数值输入
- `column` 类型（下拉列选择器）→ 默认值为列名，如果数据无此列则选中"自动"选项 → `getParams()` 会跳过空值
- 参数含义因任务而异时 → 用 `key@task_name` 覆写 `PARAM_META`

### 模板 5：Web UI 前后端一致性验证

```python
# 对比 Web API 路径 vs 引擎直接调用路径
from smartsuite.web.api import run_analysis
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

# 路径 A：直接调引擎（CLI 路径）
req = AnalysisRequest(task=task, data=df, target_col=y, feature_cols=x, params=p)
result_a = orchestrate(req)

# 路径 B：走 Web API（Web UI 路径）
results_b = run_analysis(task, df, targets=[y], features=x, categoricals=cats, params=p)
result_b = results_b[0]

# 比较数值（允许 ~0.002 预处理差异）
```

---

## ⚡ 快速修复清单

| 症状 | 诊断 | 修复 |
|------|------|------|
| "数据中缺少必要的列" | 99% 不是缺列 — 是引擎内部 `KeyError` 或 `ValueError` | 检查 orchestrator 日志中的原始异常类型 |
| 图表不显示参考线 | 参数未传到引擎 / `float()` 转换失败静默跳过 | 验证 `getParams()` 是否正确提取数值 → JSON → `orchestrate()` |
| JS 修改不生效 | 浏览器缓存了旧版 app.js | 重启 Flask + 浏览器 `Ctrl+Shift+R` |
| Python 修改不生效 | Flask 未重启 | 重启 `python smartsuite/web/app.py` |
| `ruff` N806 报错 | 函数内常量用了大写名 | 改名 `_lowercase` 或提升到模块级 |
| 测试失败但代码正确 | 检查是否是 statsmodels/pandas 版本差异 | 查看 CI 日志中的版本号 |
| 新增方法后 Web UI 无反应 | 注册链遗漏 | 逐项检查 11 步清单 |
| `sum(axis=None)` FutureWarning | pandas 弃用 | 改为 `.sum().sum()` 链式调用 |

---

## 🔧 常用命令

```bash
# 运行测试
pytest tests/ -x -q

# 仅运行引擎测试
pytest tests/test_engine/ -x -q

# 代码检查
ruff check smartsuite/

# 一致性校验
python scripts/verify_consistency.py

# 启动 Web UI
python smartsuite/web/app.py

# 列出所有分析方法
python -c "from smartsuite.services.orchestrator import TASK_REGISTRY; print(len(TASK_REGISTRY), 'tasks')"
```

---

## 参考文件索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 开发规范 | `CLAUDE.md` | 架构约束、代码风格、测试策略 |
| 领域术语 | `CONTEXT.md` | 中文术语定义 |
| 决策知识 | `docs/skill.md` | 分析方法决策树 + 工作流 |
| API 参考 | `docs/api-reference.md` | 39 个函数完整签名 |
| 用户手册 | `docs/user-manual.md` | 操作说明 + 六段式示例 |
| 已知问题 | `.claude/known-issues.md` | 豁免清单（审查前必读） |
| 架构决策 | `docs/adr/` | ADR-001 三层架构 / ADR-002 Web UI 替代 Excel |
| 配色方案 | `smartsuite/engine/_palette.py` | PALETTE 字典完整定义 |
