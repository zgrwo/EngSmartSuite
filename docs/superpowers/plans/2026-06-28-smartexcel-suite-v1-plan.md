# SmartSuite V1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 SmartSuite V1 —— 三层分离的 Python 工艺数据分析工具箱，含 14 个分析引擎函数 + 编排服务 + 三格式报告输出 + Excel 交互层。

**Architecture:** 严格三层分离：`engine/`（纯 Python 分析，零 Excel 依赖）→ `services/`（编排+报告，唯一桥接层）→ `excel/`（xlwings 交互，很薄）。数据进出通过 `AnalysisRequest` / `AnalysisResult` 契约。

**Tech Stack:** Python 3.10+, pandas, numpy, scipy, statsmodels, scikit-learn, matplotlib, seaborn, xlwings, python-pptx, reportlab, PyYAML, pytest

---

## 文件结构

```
smartsuite/
├── __init__.py
├── cli.py                          # CLI 入口 (Task 13)
├── core/
│   ├── __init__.py
│   ├── contracts.py                # AnalysisRequest, AnalysisResult (Task 1)
│   └── exceptions.py               # 分层异常体系 (Task 2)
├── engine/
│   ├── __init__.py
│   ├── root_cause.py               # 5 个分析函数 (Task 3-5)
│   ├── doe_opt.py                  # 5 个分析函数 (Task 6-7)
│   └── spc_monitor.py              # 4 个分析函数 (Task 8-9)
├── services/
│   ├── __init__.py
│   ├── data_io.py                  # Excel 数据读写+校验 (Task 11)
│   ├── orchestrator.py             # Task 路由+编排 (Task 11)
│   └── reporter.py                 # Excel/PDF/PPT 输出 (Task 11)
└── excel/
    ├── __init__.py
    ├── addin.py                    # xlwings 加载项入口 (Task 12)
    ├── ribbon.py                   # Ribbon XML 定义 (Task 12)
    └── dialogs.py                  # 对话框交互 (Task 12)

tests/
├── __init__.py
├── conftest.py                     # 共享 fixtures (Task 1)
├── test_engine/
│   ├── test_root_cause.py
│   ├── test_doe_opt.py
│   └── test_spc_monitor.py
├── test_services/
│   ├── test_orchestrator.py
│   └── test_reporter.py
└── test_integration.py             # 端到端集成测试 (Task 14)

templates/
└── example_anova.yaml              # 示例模板 (Task 13)
```

---

### Task 1: 项目基础 — 数据契约与测试基础设施

**Files:**
- Create: `smartsuite/__init__.py`
- Create: `smartsuite/core/__init__.py`
- Create: `smartsuite/core/contracts.py`
- Create: `smartsuite/engine/__init__.py`
- Create: `smartsuite/services/__init__.py`
- Create: `smartsuite/excel/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建所有 `__init__.py` 文件**

```bash
touch smartsuite/__init__.py
touch smartsuite/core/__init__.py
touch smartsuite/engine/__init__.py
touch smartsuite/services/__init__.py
touch smartsuite/excel/__init__.py
touch tests/__init__.py
```

Run: `python -c "import smartsuite; print('OK')"`
Expected: `OK`

- [ ] **Step 2: 编写数据契约 dataclass**

```python
# smartsuite/core/contracts.py
from dataclasses import dataclass, field
from typing import Any
import pandas as pd
from matplotlib.figure import Figure


@dataclass
class AnalysisRequest:
    """分析请求 — Excel 层与引擎层之间的唯一数据入口合约。"""
    task: str
    data: pd.DataFrame
    target_col: str
    feature_cols: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """分析结果 — 引擎层与 Reporter 层之间的唯一数据出口合约。"""
    task: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    figures: list[Figure] = field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    messages: list[str] = field(default_factory=list)
```

- [ ] **Step 3: 验证 contracts 可导入**

Run: `python -c "from smartsuite.core.contracts import AnalysisRequest, AnalysisResult; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 编写共享测试 fixtures**

```python
# tests/conftest.py
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_doe_data() -> pd.DataFrame:
    """注塑 DOE 实验数据：料温、模温、注射压力、保压时间 → 强度、不良率"""
    np.random.seed(42)
    n = 30
    return pd.DataFrame({
        "料温": np.random.uniform(180, 220, n),
        "模温": np.random.uniform(40, 80, n),
        "注射压力": np.random.uniform(60, 100, n),
        "保压时间": np.random.uniform(5, 15, n),
        "强度": np.random.normal(45, 3, n),
        "不良率": np.random.beta(2, 98, n) * 100,
    })


@pytest.fixture
def sample_spc_data() -> pd.DataFrame:
    """过程监控数据：30 个子组，每组 5 个样本"""
    np.random.seed(42)
    rows = []
    for subgroup in range(1, 31):
        for sample in range(1, 6):
            rows.append({"子组": subgroup, "样本": sample,
                         "测量值": np.random.normal(10.0, 0.5)})
    return pd.DataFrame(rows)


@pytest.fixture
def sample_two_group_data() -> pd.DataFrame:
    """两组对比数据：新旧工艺"""
    np.random.seed(42)
    old = pd.DataFrame({"工艺": "旧工艺", "强度": np.random.normal(44, 3, 20)})
    new = pd.DataFrame({"工艺": "新工艺", "强度": np.random.normal(47, 3, 20)})
    return pd.concat([old, new], ignore_index=True)
```

- [ ] **Step 5: 运行测试确保 infrastructure 正常**

Run: `pytest tests/ -v`
Expected: `no tests ran` (fixtures 加载正常)

- [ ] **Step 6: Commit**

```bash
git add smartsuite/ tests/ pyproject.toml
git commit -m "feat: project foundation — contracts, fixtures, package init"
```

---

### Task 2: 分层异常体系

**Files:**
- Create: `smartsuite/core/exceptions.py`

- [ ] **Step 1: 创建异常类**

```python
# smartsuite/core/exceptions.py
class SmartSuiteError(Exception):
    """SmartSuite 所有异常的基类。"""
    pass


class DataSelectionError(SmartSuiteError):
    """Excel 交互层 — 数据选区无效。"""
    pass


class ValidationError(SmartSuiteError):
    """Data I/O 层 — 数据校验不通过。"""
    pass


class AnalysisError(SmartSuiteError):
    """分析引擎层 — 分析计算失败。"""
    pass


class ConvergenceError(AnalysisError):
    """分析引擎层 — 模型未收敛。"""
    pass


class OutputError(SmartSuiteError):
    """Reporter 层 — 报告输出失败。"""
    pass
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from smartsuite.core.exceptions import DataSelectionError, ValidationError, AnalysisError, ConvergenceError, OutputError; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add smartsuite/core/exceptions.py
git commit -m "feat: layered exception hierarchy"
```

---

### Task 3: 引擎层 — 要因分析：相关性矩阵

**Files:**
- Create: `tests/test_engine/test_root_cause.py`
- Create: `smartsuite/engine/root_cause.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_engine/test_root_cause.py
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause import correlation_analysis


def test_correlation_analysis_basic(sample_doe_data):
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = correlation_analysis(req)

    assert result.task == "correlation"
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables
    corr = result.tables["correlation_matrix"]
    assert corr.shape[0] >= 5
    assert corr.values.min() >= -1.0
    assert corr.values.max() <= 1.0
    assert len(result.summary) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_root_cause.py::test_correlation_analysis_basic -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: 实现相关性分析函数**

```python
# smartsuite/engine/root_cause.py
import numpy as np
import pandas as pd
from scipy import stats
from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def correlation_analysis(req: AnalysisRequest) -> AnalysisResult:
    """Pearson 相关性矩阵分析，含 p 值。"""
    cols = req.feature_cols + [req.target_col]
    cols = [c for c in cols if c in req.data.columns]
    corr = req.data[cols].corr()

    # p 值矩阵
    pmat = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for c1 in cols:
        for c2 in cols:
            mask = req.data[c1].notna() & req.data[c2].notna()
            if mask.sum() >= 3:
                _, p = stats.pearsonr(req.data.loc[mask, c1], req.data.loc[mask, c2])
                pmat.loc[c1, c2] = p
            else:
                pmat.loc[c1, c2] = np.nan

    target_corr = corr[req.target_col].drop(req.target_col).sort_values(ascending=False)
    top_factor = target_corr.index[0] if len(target_corr) > 0 else "N/A"
    top_value = target_corr.iloc[0] if len(target_corr) > 0 else 0

    return AnalysisResult(
        task="correlation",
        tables={"correlation_matrix": corr, "p_values": pmat.astype(float)},
        summary=f"与「{req.target_col}」相关性最强的因子是「{top_factor}」(r={top_value:.3f})",
        metadata={"target_correlations": target_corr.to_dict()},
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_engine/test_root_cause.py::test_correlation_analysis_basic -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_engine/test_root_cause.py smartsuite/engine/root_cause.py
git commit -m "feat: correlation analysis with p-values"
```

---

### Task 4: 引擎层 — 要因分析：ANOVA

**Files:**
- Modify: `tests/test_engine/test_root_cause.py`
- Modify: `smartsuite/engine/root_cause.py`

- [ ] **Step 1: 写失败测试**

在 `test_root_cause.py` 追加:

```python
from smartsuite.engine.root_cause import anova_analysis


def test_anova_basic(sample_doe_data):
    req = AnalysisRequest(
        task="anova",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"alpha": 0.05},
    )
    result = anova_analysis(req)

    assert result.task == "anova"
    assert result.status in ("ok", "warning")
    assert "anova_table" in result.tables
    assert len(result.summary) > 0
    assert "r_squared" in result.metadata
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_root_cause.py::test_anova_basic -v`
Expected: FAIL (anova_analysis not defined)

- [ ] **Step 3: 实现 ANOVA 函数**

在 `root_cause.py` 追加:

```python
import statsmodels.api as sm
from statsmodels.formula.api import ols


def anova_analysis(req: AnalysisRequest) -> AnalysisResult:
    """多因子 ANOVA 方差分析。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if req.target_col not in req.data.columns:
        return AnalysisResult(task="anova", status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中"])

    formula = f"Q('{req.target_col}') ~ " + " + ".join(f"Q('{c}')" for c in cols)
    model = ols(formula, data=req.data).fit()
    anova_table = sm.stats.anova_lm(model, typ=2)

    alpha = req.params.get("alpha", 0.05)
    sig_factors = []
    for col in cols:
        try:
            p_val = anova_table.loc[f"Q('{col}')", "PR(>F)"]
            if p_val < alpha:
                sig_factors.append(f"{col}(p={p_val:.4f})")
        except KeyError:
            pass

    summary = f"显著影响「{req.target_col}」的因子: {', '.join(sig_factors)}" if sig_factors \
        else f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})"

    coef_df = pd.DataFrame({
        "变量": model.params.index, "系数": model.params.values,
        "标准误": model.bse.values, "t值": model.tvalues.values, "p值": model.pvalues.values,
    })

    return AnalysisResult(
        task="anova",
        tables={"anova_table": anova_table, "coefficients": coef_df},
        summary=summary,
        metadata={"r_squared": model.rsquared, "r_squared_adj": model.rsquared_adj},
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_engine/test_root_cause.py::test_anova_basic -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/root_cause.py tests/test_engine/test_root_cause.py
git commit -m "feat: ANOVA analysis engine"
```

---

### Task 5: 引擎层 — 要因分析：假设检验 + 决策树 + VIF

**Files:**
- Modify: `tests/test_engine/test_root_cause.py`
- Modify: `smartsuite/engine/root_cause.py`

- [ ] **Step 1: 写三个新测试**

在 `test_root_cause.py` 追加:

```python
from smartsuite.engine.root_cause import hypothesis_test, decision_tree_analysis, vif_analysis


def test_hypothesis_test_two_sample(sample_two_group_data):
    req = AnalysisRequest(
        task="hypothesis_test", data=sample_two_group_data,
        target_col="强度", feature_cols=["工艺"],
        params={"test": "ttest_ind", "group_col": "工艺"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok"
    assert "p_value" in result.metadata
    assert len(result.summary) > 0


def test_decision_tree(sample_doe_data):
    req = AnalysisRequest(
        task="decision_tree", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
        params={"max_depth": 3},
    )
    result = decision_tree_analysis(req)
    assert result.status == "ok"
    assert "feature_importance" in result.tables
    fi = result.tables["feature_importance"]
    assert "重要性" in fi.columns
    assert len(fi) >= 1


def test_vif_analysis(sample_doe_data):
    req = AnalysisRequest(
        task="vif", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = vif_analysis(req)
    assert result.status == "ok"
    assert "vif_table" in result.tables
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_root_cause.py -v -k "test_hypothesis or test_decision or test_vif"`
Expected: 3 FAIL

- [ ] **Step 3: 实现三个函数**

在 `root_cause.py` 追加:

```python
from sklearn.tree import DecisionTreeRegressor
from statsmodels.stats.outliers_influence import variance_inflation_factor


def hypothesis_test(req: AnalysisRequest) -> AnalysisResult:
    """两样本假设检验 (t-test / Mann-Whitney U)。"""
    group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=[f"分组列需要恰好 2 个水平，当前有 {len(groups)} 个"])

    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()
    test_type = req.params.get("test", "ttest_ind")

    if test_type == "mannwhitney":
        stat, p = stats.mannwhitneyu(g1, g2)
        test_name = "Mann-Whitney U 检验"
    else:
        stat, p = stats.ttest_ind(g1, g2)
        test_name = "独立样本 t 检验"

    alpha = req.params.get("alpha", 0.05)
    conclusion = "存在显著差异" if p < alpha else "未发现显著差异"

    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量": [stat], "p值": [p],
            "显著性水平": [alpha],
            "结论": [f"{groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})"],
        })},
        summary=f"{groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})",
        metadata={"test": test_name, "statistic": stat, "p_value": p, "alpha": alpha},
    )


def decision_tree_analysis(req: AnalysisRequest) -> AnalysisResult:
    """决策树特征重要性分析。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    df = req.data[[req.target_col] + cols].dropna()
    X = df[cols]
    y = df[req.target_col]
    max_depth = req.params.get("max_depth", 5)

    tree = DecisionTreeRegressor(max_depth=max_depth, random_state=42)
    tree.fit(X, y)

    fi = pd.DataFrame({"因子": cols, "重要性": tree.feature_importances_})
    fi = fi.sort_values("重要性", ascending=False).reset_index(drop=True)
    top = fi.iloc[0] if len(fi) > 0 else None

    return AnalysisResult(
        task="decision_tree",
        tables={"feature_importance": fi},
        summary=f"关键影响因子: {top['因子']} (重要性={top['重要性']:.3f})" if top is not None
            else "分析完成",
        metadata={"top_factor": top["因子"] if top is not None else None},
    )


def vif_analysis(req: AnalysisRequest) -> AnalysisResult:
    """方差膨胀因子 — 多元共线性诊断。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    df = req.data[cols].dropna()
    X = sm.add_constant(df)
    vif_data = pd.DataFrame({
        "变量": X.columns,
        "VIF": [variance_inflation_factor(X.values, i) for i in range(X.shape[1])],
    })
    high_vif = vif_data[vif_data["VIF"] > 5]
    warning = f"注意: {len(high_vif)} 个变量 VIF>5，存在共线性风险" if len(high_vif) > 0 \
        else "所有变量 VIF<=5，无明显共线性"

    return AnalysisResult(
        task="vif", tables={"vif_table": vif_data}, summary=warning,
        metadata={"high_vif_count": len(high_vif)},
    )
```

- [ ] **Step 4: 运行全部 root_cause 测试**

Run: `pytest tests/test_engine/test_root_cause.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/root_cause.py tests/test_engine/test_root_cause.py
git commit -m "feat: hypothesis test, decision tree, VIF analysis"
```

---

### Task 6: 引擎层 — DOE/优化：回归建模

**Files:**
- Create: `tests/test_engine/test_doe_opt.py`
- Create: `smartsuite/engine/doe_opt.py`

- [ ] **Step 1: 写回归建模失败测试**

```python
# tests/test_engine/test_doe_opt.py
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt import regression_analysis


def test_regression_analysis_linear(sample_doe_data):
    req = AnalysisRequest(
        task="regression",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"model_type": "linear"},
    )
    result = regression_analysis(req)
    assert result.status == "ok"
    assert "coefficients" in result.tables
    assert "r_squared" in result.metadata
    assert result.metadata["r_squared"] >= 0
    assert len(result.summary) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_doe_opt.py::test_regression_analysis_linear -v`
Expected: FAIL

- [ ] **Step 3: 实现回归建模**

```python
# smartsuite/engine/doe_opt.py
import numpy as np
import pandas as pd
import statsmodels.api as sm
from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def regression_analysis(req: AnalysisRequest) -> AnalysisResult:
    """线性回归建模 (OLS)。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < len(cols) + 2:
        return AnalysisResult(task="regression", status="error",
            messages=[f"有效样本量({len(df)})不足，需要至少{len(cols)+2}条"])

    X = sm.add_constant(df[cols])
    y = df[req.target_col]
    model = sm.OLS(y, X).fit()

    coef_df = pd.DataFrame({
        "变量": X.columns,
        "系数": model.params.values,
        "标准误": model.bse.values,
        "t值": model.tvalues.values,
        "p值": model.pvalues.values,
    })

    sig_vars = coef_df[(coef_df["p值"] < 0.05) & (coef_df["变量"] != "const")]

    return AnalysisResult(
        task="regression",
        tables={"coefficients": coef_df},
        summary=f"R²={model.rsquared:.4f}, 调整R²={model.rsquared_adj:.4f}, 显著变量: {len(sig_vars)}/{len(cols)}",
        metadata={
            "r_squared": model.rsquared,
            "r_squared_adj": model.rsquared_adj,
            "f_statistic": model.fvalue,
            "f_pvalue": model.f_pvalue,
            "significant_vars": sig_vars["变量"].tolist(),
        },
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_engine/test_doe_opt.py::test_regression_analysis_linear -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/doe_opt.py tests/test_engine/test_doe_opt.py
git commit -m "feat: regression analysis engine (OLS)"
```

---

### Task 7: 引擎层 — DOE/优化：响应面 + 多目标优化 + 最优搜索 + DOE 分析

**Files:**
- Modify: `tests/test_engine/test_doe_opt.py`
- Modify: `smartsuite/engine/doe_opt.py`

- [ ] **Step 1: 写四个新测试**

在 `test_doe_opt.py` 追加:

```python
from smartsuite.engine.doe_opt import (
    response_surface_analysis, grid_search, multi_objective_opt, doe_analysis,
)


def test_response_surface(sample_doe_data):
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={"direction": "maximize"},
    )
    result = response_surface_analysis(req)
    assert result.status == "ok"
    assert len(result.figures) >= 1
    assert "coefficients" in result.tables


def test_grid_search_optimization(sample_doe_data):
    req = AnalysisRequest(
        task="grid_search", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={
            "ranges": {"料温": [180, 220], "模温": [40, 80]},
            "direction": "maximize", "n_points": 10,
        },
    )
    result = grid_search(req)
    assert result.status == "ok"
    assert "optimal_params" in result.metadata


def test_multi_objective_optimization(sample_doe_data):
    req = AnalysisRequest(
        task="multi_objective", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={
            "objectives": [
                {"col": "强度", "direction": "maximize"},
                {"col": "不良率", "direction": "minimize"},
            ],
            "weights": [0.5, 0.5],
        },
    )
    result = multi_objective_opt(req)
    assert result.status == "ok"
    assert "optimal_params" in result.metadata


def test_doe_factorial_analysis(sample_doe_data):
    req = AnalysisRequest(
        task="doe_analysis", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={"design_type": "full_factorial"},
    )
    result = doe_analysis(req)
    assert result.status == "ok"
    assert "effect_estimates" in result.tables
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_doe_opt.py -v -k "test_response or test_grid or test_multi or test_doe_factorial"`
Expected: 4 FAIL

- [ ] **Step 3: 实现四个函数**

在 `doe_opt.py` 追加:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


def response_surface_analysis(req: AnalysisRequest) -> AnalysisResult:
    """响应面分析 — 拟合二次模型并生成 3D 曲面图。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(task="response_surface", status="error",
            messages=["响应面分析需要至少 2 个因子"])

    c1, c2 = cols[0], cols[1]
    df = req.data[[req.target_col, c1, c2]].dropna()
    X1, X2 = df[c1].values, df[c2].values
    y = df[req.target_col].values

    X = np.column_stack([np.ones(len(df)), X1, X2, X1**2, X2**2, X1*X2])
    try:
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return AnalysisResult(task="response_surface", status="error",
            messages=["响应面模型未能求解"])

    xi = np.linspace(X1.min(), X1.max(), 30)
    yi = np.linspace(X2.min(), X2.max(), 30)
    XI, YI = np.meshgrid(xi, yi)
    ZI = beta[0] + beta[1]*XI + beta[2]*YI + beta[3]*XI**2 + beta[4]*YI**2 + beta[5]*XI*YI

    fig = Figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection='3d')
    ax.plot_surface(XI, YI, ZI, cmap='viridis', alpha=0.8)
    ax.scatter(X1, X2, y, color='red', s=30)
    ax.set_xlabel(c1); ax.set_ylabel(c2); ax.set_zlabel(req.target_col)

    opt_idx = np.unravel_index(
        np.argmax(ZI) if "min" not in req.params.get("direction", "maximize") else np.argmin(ZI),
        ZI.shape)

    return AnalysisResult(
        task="response_surface",
        tables={"coefficients": pd.DataFrame({
            "项": ["截距", c1, c2, f"{c1}²", f"{c2}²", f"{c1}×{c2}"], "系数": beta
        })},
        figures=[fig],
        summary=f"响应面分析完成，最优区域: {c1}={XI[opt_idx]:.1f}, {c2}={YI[opt_idx]:.1f}",
        metadata={"optimal_x1": float(XI[opt_idx]), "optimal_x2": float(YI[opt_idx]),
                  "optimal_z": float(ZI[opt_idx])},
    )


def grid_search(req: AnalysisRequest) -> AnalysisResult:
    """网格搜索 — 在范围内搜索最优参数。"""
    ranges = req.params.get("ranges", {})
    n_points = req.params.get("n_points", 10)
    direction = req.params.get("direction", "maximize")

    grids = {col: np.linspace(lo, hi, n_points) for col, (lo, hi) in ranges.items()}
    mesh = np.meshgrid(*grids.values(), indexing='ij')
    points = np.column_stack([g.ravel() for g in mesh])
    col_names = list(ranges.keys())

    df = req.data[col_names + [req.target_col]].dropna()
    from sklearn.linear_model import Ridge
    model = Ridge(alpha=1.0).fit(df[col_names].values, df[req.target_col].values)
    predictions = model.predict(points)

    best_idx = np.argmax(predictions) if direction == "maximize" else np.argmin(predictions)
    best = {col_names[i]: points[best_idx, i] for i in range(len(col_names))}

    return AnalysisResult(
        task="grid_search",
        summary=f"最优参数: {best}, 预测值: {predictions[best_idx]:.4f}",
        metadata={"optimal_params": best, "optimal_value": float(predictions[best_idx])},
    )


def multi_objective_opt(req: AnalysisRequest) -> AnalysisResult:
    """多目标优化 — 加权期望函数法。"""
    objectives = req.params.get("objectives", [])
    weights = req.params.get("weights", [1.0] * len(objectives))
    weights = np.array(weights) / np.sum(weights)

    scores = np.zeros(len(req.data))
    for obj, w in zip(objectives, weights):
        vals = req.data[obj["col"]].dropna().values
        if obj.get("direction", "maximize") == "maximize":
            desirability = (vals - vals.min()) / (vals.max() - vals.min() + 1e-10)
        else:
            desirability = (vals.max() - vals) / (vals.max() - vals.min() + 1e-10)
        scores += w * desirability

    best_idx = np.argmax(scores)
    best_params = {c: req.data[c].iloc[best_idx]
                   for c in req.feature_cols if c in req.data.columns}

    return AnalysisResult(
        task="multi_objective",
        summary=f"综合评分最优: {best_params}, 得分: {scores[best_idx]:.4f}",
        metadata={"optimal_params": best_params, "composite_score": float(scores[best_idx])},
    )


def doe_analysis(req: AnalysisRequest) -> AnalysisResult:
    """DOE 全因子分析 — 估计主效应。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    df = req.data[[req.target_col] + cols].dropna()

    effects = []
    grand_mean = df[req.target_col].mean()
    for col in cols:
        median = df[col].median()
        hi = df[df[col] > median][req.target_col].mean()
        lo = df[df[col] <= median][req.target_col].mean()
        effect = hi - lo
        effects.append({"因子": col, "主效应": effect, "效应占比": abs(effect) / grand_mean})

    effects_df = pd.DataFrame(effects).sort_values("主效应", key=abs, ascending=False)
    top_name = effects_df["因子"].iloc[0] if len(effects_df) > 0 else "N/A"
    top_val = effects_df["主效应"].iloc[0] if len(effects_df) > 0 else 0

    return AnalysisResult(
        task="doe_analysis",
        tables={"effect_estimates": effects_df},
        summary=f"最强主效应: {top_name} (效应={top_val:.3f})",
        metadata={"grand_mean": grand_mean, "top_effect_factor": top_name},
    )
```

- [ ] **Step 4: 运行全部 DOE 测试**

Run: `pytest tests/test_engine/test_doe_opt.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/doe_opt.py tests/test_engine/test_doe_opt.py
git commit -m "feat: response surface, grid search, multi-obj opt, DOE analysis"
```

---

### Task 8: 引擎层 — 过程监控：SPC 控制图 + 过程能力

**Files:**
- Create: `tests/test_engine/test_spc_monitor.py`
- Create: `smartsuite/engine/spc_monitor.py`

- [ ] **Step 1: 写 SPC 测试**

```python
# tests/test_engine/test_spc_monitor.py
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.spc_monitor import xbar_r_chart, process_capability_analysis


def test_xbar_r_chart(sample_spc_data):
    req = AnalysisRequest(
        task="spc_xbar", data=sample_spc_data,
        target_col="测量值", feature_cols=["子组"],
        params={"subgroup_col": "子组"},
    )
    result = xbar_r_chart(req)
    assert result.status == "ok"
    assert len(result.figures) >= 1
    assert "control_limits" in result.tables


def test_process_capability(sample_spc_data):
    req = AnalysisRequest(
        task="process_capability", data=sample_spc_data,
        target_col="测量值",
        params={"usl": 12.0, "lsl": 8.0},
    )
    result = process_capability_analysis(req)
    assert result.status == "ok"
    cpk = result.metadata.get("cpk", 0)
    assert isinstance(cpk, (int, float))
    assert "cp" in result.metadata
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_spc_monitor.py -v`
Expected: 2 FAIL

- [ ] **Step 3: 实现 SPC 控制图和过程能力**

```python
# smartsuite/engine/spc_monitor.py
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def xbar_r_chart(req: AnalysisRequest) -> AnalysisResult:
    """X-bar 和 R 控制图。"""
    subgroup_col = req.params.get("subgroup_col", "子组")
    subgroups = req.data.groupby(subgroup_col)[req.target_col]
    xbar = subgroups.mean()
    r = subgroups.max() - subgroups.min()

    xbar_bar = xbar.mean()
    r_bar = r.mean()
    n = subgroups.count().iloc[0] if len(subgroups) > 0 else 5
    A2, D3, D4 = 0.577, 0, 2.114  # n=5 常数

    fig = Figure(figsize=(10, 8))
    ax1 = fig.add_subplot(211)
    ax1.plot(xbar.index, xbar.values, 'o-', markersize=4)
    ax1.axhline(xbar_bar, color='green', linestyle='-', label=f'CL={xbar_bar:.3f}')
    ax1.axhline(xbar_bar + A2 * r_bar, color='red', linestyle='--')
    ax1.axhline(xbar_bar - A2 * r_bar, color='red', linestyle='--')
    ax1.set_title('X-bar 控制图'); ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(212)
    ax2.plot(r.index, r.values, 'o-', markersize=4, color='orange')
    ax2.axhline(r_bar, color='green', linestyle='-', label=f'CL={r_bar:.3f}')
    ax2.axhline(D4 * r_bar, color='red', linestyle='--')
    ax2.axhline(D3 * r_bar, color='red', linestyle='--')
    ax2.set_title('R 控制图'); ax2.legend(fontsize=8)

    xbar_ooc = (xbar > xbar_bar + A2 * r_bar) | (xbar < xbar_bar - A2 * r_bar)

    limits = pd.DataFrame({
        "统计量": ["X-bar", "R"],
        "CL": [xbar_bar, r_bar],
        "UCL": [xbar_bar + A2 * r_bar, D4 * r_bar],
        "LCL": [xbar_bar - A2 * r_bar, D3 * r_bar],
    })

    return AnalysisResult(
        task="spc_xbar",
        tables={"control_limits": limits}, figures=[fig],
        summary=f"X-bar 控制图: 失控点 {xbar_ooc.sum()} 个",
        metadata={"xbar_mean": float(xbar_bar), "r_mean": float(r_bar),
                  "xbar_ooc_count": int(xbar_ooc.sum())},
    )


def process_capability_analysis(req: AnalysisRequest) -> AnalysisResult:
    """过程能力分析 Cp/Cpk/Pp/Ppk。"""
    data = req.data[req.target_col].dropna()
    usl = req.params.get("usl")
    lsl = req.params.get("lsl")

    mu, sigma = data.mean(), data.std(ddof=1)
    mr = np.abs(np.diff(data.values))
    within_sigma = np.mean(mr) / 1.128

    cp = (usl - lsl) / (6 * within_sigma) if usl and lsl else None
    cpk_val = min((usl - mu) / (3 * within_sigma), (mu - lsl) / (3 * within_sigma)) \
        if usl and lsl else None

    judge = "合格" if cpk_val and cpk_val >= 1.33 else ("需改进" if cpk_val else "未提供规格限")

    return AnalysisResult(
        task="process_capability",
        tables={"capability": pd.DataFrame({
            "指标": ["Cp", "Cpk"], "值": [cp, cpk_val]
        })},
        summary=f"Cpk={cpk_val:.3f}, {judge}" if cpk_val else judge,
        metadata={"cp": cp, "cpk": cpk_val, "mean": float(mu), "std": float(sigma)},
    )
```

- [ ] **Step 4: 运行 SPC 测试**

Run: `pytest tests/test_engine/test_spc_monitor.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/spc_monitor.py tests/test_engine/test_spc_monitor.py
git commit -m "feat: SPC control chart and process capability"
```

---

### Task 9: 引擎层 — 过程监控：趋势预测 + 异常检测

**Files:**
- Modify: `tests/test_engine/test_spc_monitor.py`
- Modify: `smartsuite/engine/spc_monitor.py`

- [ ] **Step 1: 写测试**

在 `test_spc_monitor.py` 追加:

```python
from smartsuite.engine.spc_monitor import trend_forecast, anomaly_detect


def test_trend_forecast(sample_spc_data):
    subgroup_means = sample_spc_data.groupby("子组")["测量值"].mean().reset_index()
    req = AnalysisRequest(
        task="trend_forecast", data=subgroup_means,
        target_col="测量值", params={"forecast_steps": 5},
    )
    result = trend_forecast(req)
    assert result.status == "ok"
    assert "forecast" in result.tables
    assert len(result.tables["forecast"]) >= 5


def test_anomaly_detect(sample_spc_data):
    req = AnalysisRequest(
        task="anomaly_detect", data=sample_spc_data,
        target_col="测量值", params={"method": "iqr"},
    )
    result = anomaly_detect(req)
    assert result.status == "ok"
    assert "anomaly_count" in result.metadata
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_engine/test_spc_monitor.py -v -k "test_trend or test_anomaly"`
Expected: 2 FAIL

- [ ] **Step 3: 实现趋势预测和异常检测**

在 `spc_monitor.py` 追加:

```python
from sklearn.linear_model import LinearRegression


def trend_forecast(req: AnalysisRequest) -> AnalysisResult:
    """简单线性趋势预测。"""
    data = req.data[req.target_col].dropna()
    steps = req.params.get("forecast_steps", 5)
    X = np.arange(len(data)).reshape(-1, 1)
    y = data.values

    model = LinearRegression().fit(X, y)
    future_X = np.arange(len(data), len(data) + steps).reshape(-1, 1)
    predictions = model.predict(future_X)
    conf = 1.96 * np.std(y - model.predict(X))

    forecast_df = pd.DataFrame({
        "步数": range(1, steps + 1),
        "预测值": predictions,
        "下限": predictions - conf,
        "上限": predictions + conf,
    })

    trend_dir = "上升" if model.coef_[0] > 0 else "下降"
    return AnalysisResult(
        task="trend_forecast",
        tables={"forecast": forecast_df},
        summary=f"趋势{trend_dir}(斜率={model.coef_[0]:.4f}/步), 预测{steps}步",
        metadata={"slope": float(model.coef_[0]), "forecast_steps": steps},
    )


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """IQR / Z-score 异常检测。"""
    data = req.data[req.target_col].dropna()
    method = req.params.get("method", "iqr")

    if method == "iqr":
        Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
        IQR = Q3 - Q1
        mask = (data < Q1 - 1.5 * IQR) | (data > Q3 + 1.5 * IQR)
    else:
        z = np.abs((data - data.mean()) / data.std())
        mask = z > 3

    idx = data.index[mask]
    anomalies = req.data.loc[idx] if mask.sum() > 0 else pd.DataFrame()

    return AnalysisResult(
        task="anomaly_detect",
        tables={"anomalies": anomalies},
        summary=f"检测到 {mask.sum()} 个异常点 (方法: {method})",
        metadata={"anomaly_count": int(mask.sum()), "method": method},
    )
```

- [ ] **Step 4: 运行全部 SPC 测试**

Run: `pytest tests/test_engine/test_spc_monitor.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add smartsuite/engine/spc_monitor.py tests/test_engine/test_spc_monitor.py
git commit -m "feat: trend forecast and anomaly detection"
```

---

### Task 10: 引擎层 — 导出公共 API

**Files:**
- Modify: `smartsuite/engine/__init__.py`

- [ ] **Step 1: 注册引擎公开 API**

```python
# smartsuite/engine/__init__.py
"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

from smartsuite.engine.root_cause import (
    correlation_analysis, anova_analysis, hypothesis_test,
    decision_tree_analysis, vif_analysis,
)
from smartsuite.engine.doe_opt import (
    regression_analysis, response_surface_analysis, grid_search,
    multi_objective_opt, doe_analysis,
)
from smartsuite.engine.spc_monitor import (
    xbar_r_chart, process_capability_analysis, trend_forecast, anomaly_detect,
)

__all__ = [
    "correlation_analysis", "anova_analysis", "hypothesis_test",
    "decision_tree_analysis", "vif_analysis",
    "regression_analysis", "response_surface_analysis", "grid_search",
    "multi_objective_opt", "doe_analysis",
    "xbar_r_chart", "process_capability_analysis", "trend_forecast", "anomaly_detect",
]
```

- [ ] **Step 2: 运行全部引擎测试**

Run: `pytest tests/test_engine/ -v`
Expected: 14 PASS

- [ ] **Step 3: Commit**

```bash
git add smartsuite/engine/__init__.py
git commit -m "refactor: export engine public API"
```

---

### Task 11: 服务层 — Data I/O + Orchestrator + Reporter

**Files:**
- Create: `smartsuite/services/data_io.py`
- Create: `smartsuite/services/orchestrator.py`
- Create: `smartsuite/services/reporter.py`
- Create: `tests/test_services/test_orchestrator.py`
- Create: `tests/test_services/test_reporter.py`
- Modify: `smartsuite/services/__init__.py`

- [ ] **Step 1: 写 Orchestrator 测试**

```python
# tests/test_services/test_orchestrator.py
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def test_orchestrate_anova(sample_doe_data):
    req = AnalysisRequest(
        task="anova", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = orchestrate(req)
    assert result.task == "anova"
    assert result.status in ("ok", "warning", "error")


def test_orchestrate_correlation(sample_doe_data):
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables


def test_orchestrate_unknown_task(sample_doe_data):
    req = AnalysisRequest(
        task="unknown_method", data=sample_doe_data,
        target_col="强度", feature_cols=["料温"],
    )
    result = orchestrate(req)
    assert result.status == "error"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_services/test_orchestrator.py -v`
Expected: 3 FAIL

- [ ] **Step 3: 实现服务层三个模块**

```python
# smartsuite/services/data_io.py
"""Data I/O — Excel 数据读写与校验。"""
import pandas as pd
from smartsuite.core.exceptions import ValidationError


def read_excel_range(sheet, range_addr: str | None = None) -> pd.DataFrame:
    """从 Excel 选区读取 DataFrame。"""
    if range_addr:
        data_range = sheet.range(range_addr)
    else:
        data_range = sheet.range("A1").expand()
    df = data_range.options(pd.DataFrame, header=True).value
    if df is None or df.empty:
        raise ValidationError("所选区域无有效数据")
    return df


def validate_data(df: pd.DataFrame, target_col: str,
                  feature_cols: list[str]) -> list[str]:
    """校验数据列存在性、类型、缺失值。返回警告消息。"""
    messages = []
    missing = [c for c in [target_col] + feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"以下列不存在于数据中: {missing}")

    for col in feature_cols + [target_col]:
        if df[col].dtype == 'object':
            try:
                pd.to_numeric(df[col])
            except (ValueError, TypeError):
                messages.append(f"列「{col}」包含非数值数据")

    null_count = df[[target_col] + feature_cols].isnull().sum().sum()
    if null_count > 0:
        messages.append(f"检测到 {null_count} 个缺失值，分析中将自动排除")

    return messages
```

```python
# smartsuite/services/orchestrator.py
"""工作流编排 — 按 task 字段路由到对应引擎函数。"""
from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine import (
    correlation_analysis, anova_analysis, hypothesis_test,
    decision_tree_analysis, vif_analysis,
    regression_analysis, response_surface_analysis, grid_search,
    multi_objective_opt, doe_analysis,
    xbar_r_chart, process_capability_analysis, trend_forecast, anomaly_detect,
)

TASK_REGISTRY = {
    "correlation": correlation_analysis,
    "anova": anova_analysis,
    "hypothesis_test": hypothesis_test,
    "decision_tree": decision_tree_analysis,
    "vif": vif_analysis,
    "regression": regression_analysis,
    "response_surface": response_surface_analysis,
    "grid_search": grid_search,
    "multi_objective": multi_objective_opt,
    "doe_analysis": doe_analysis,
    "spc_xbar": xbar_r_chart,
    "process_capability": process_capability_analysis,
    "trend_forecast": trend_forecast,
    "anomaly_detect": anomaly_detect,
}

DEFAULT_PARAMS = {
    "anova": {"alpha": 0.05},
    "hypothesis_test": {"alpha": 0.05, "test": "ttest_ind"},
    "decision_tree": {"max_depth": 5},
    "regression": {"model_type": "linear"},
    "response_surface": {"direction": "maximize"},
    "grid_search": {"direction": "maximize", "n_points": 10},
    "spc_xbar": {"subgroup_col": "子组"},
    "trend_forecast": {"forecast_steps": 5},
    "anomaly_detect": {"method": "iqr"},
}


def orchestrate(req: AnalysisRequest) -> AnalysisResult:
    """路由分析请求到对应引擎函数，注入默认参数。"""
    if req.task not in TASK_REGISTRY:
        return AnalysisResult(
            task=req.task, status="error",
            messages=[f"未知的分析任务「{req.task}」, 支持: {list(TASK_REGISTRY.keys())}"]
        )

    defaults = DEFAULT_PARAMS.get(req.task, {})
    merged = {**defaults, **req.params}
    req.params = merged

    try:
        return TASK_REGISTRY[req.task](req)
    except Exception as e:
        return AnalysisResult(task=req.task, status="error", messages=[str(e)])
```

```python
# smartsuite/services/reporter.py
"""Reporter — 多格式报告输出：Excel 图表 / PDF / PPT。"""
import io
import os
from smartsuite.core.contracts import AnalysisResult
from smartsuite.core.exceptions import OutputError


def to_excel(result: AnalysisResult, workbook,
             sheet_name: str = "分析结果") -> str:
    """将分析结果写入 Excel 新 Sheet。"""
    try:
        ws = workbook.sheets.add(sheet_name, after=workbook.sheets[-1])
        r = 1
        ws.range(f"A{r}").value = "分析结论"; ws.range(f"A{r}").font.bold = True
        r += 1
        ws.range(f"A{r}").value = result.summary
        r += 2
        for name, df in result.tables.items():
            ws.range(f"A{r}").value = name; ws.range(f"A{r}").font.bold = True
            r += 1
            ws.range(f"A{r}").value = df
            r += len(df) + 2
        for i, fig in enumerate(result.figures):
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            pic = workbook.sheets.add(f"图表_{i+1}", after=workbook.sheets[-1])
            pic.pictures.add(buf, left=pic.range("A1").left,
                             top=pic.range("A1").top, width=600, height=450)
        return sheet_name
    except Exception as e:
        raise OutputError(f"Excel 输出失败: {e}") from e


def to_pdf(result: AnalysisResult, output_path: str) -> str:
    """生成 PDF 报告。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader

        c = canvas.Canvas(output_path, pagesize=A4)
        w, h = A4
        y = h - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, f"分析报告: {result.task}")
        y -= 30
        c.setFont("Helvetica", 11)
        c.drawString(50, y, result.summary)
        y -= 50

        for name, df in list(result.tables.items())[:5]:
            if y < 150:
                c.showPage(); y = h - 50
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, name); y -= 18
            c.setFont("Helvetica", 8)
            for _, row in df.head(15).iterrows():
                c.drawString(55, y, str(row.to_dict())); y -= 12

        for fig in result.figures[:3]:
            if y < 350:
                c.showPage(); y = h - 50
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            c.drawImage(ImageReader(buf), 50, y - 300, width=450, height=300)
            y -= 320

        c.save()
        return output_path
    except Exception as e:
        raise OutputError(f"PDF 输出失败: {e}") from e


def to_ppt(result: AnalysisResult, output_path: str,
           template_path: str | None = None) -> str:
    """生成 PPT 报告。"""
    try:
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation(template_path) if template_path and os.path.exists(template_path) \
            else Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11), Inches(2))
        txBox.text_frame.text = f"分析报告: {result.task}\n\n{result.summary}"

        for fig in result.figures:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            slide.shapes.add_picture(buf, Inches(0.5), Inches(0.5),
                                     Inches(12), Inches(6.5))

        prs.save(output_path)
        return output_path
    except Exception as e:
        raise OutputError(f"PPT 输出失败: {e}") from e
```

- [ ] **Step 4: 更新服务层 `__init__.py`**

```python
# smartsuite/services/__init__.py
"""应用服务层 — 数据 I/O、工作流编排、报告生成。"""
from smartsuite.services.orchestrator import orchestrate, TASK_REGISTRY
from smartsuite.services.reporter import to_excel, to_pdf, to_ppt
from smartsuite.services.data_io import read_excel_range, validate_data

__all__ = ["orchestrate", "TASK_REGISTRY", "to_excel", "to_pdf", "to_ppt",
           "read_excel_range", "validate_data"]
```

- [ ] **Step 5: 写 Reporter 集成测试**

```python
# tests/test_services/test_reporter.py
import tempfile, os
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def test_reporter_pdf_output(sample_doe_data):
    from smartsuite.services.reporter import to_pdf
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = to_pdf(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        os.unlink(path)


def test_reporter_ppt_output(sample_doe_data):
    from smartsuite.services.reporter import to_ppt
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={"direction": "maximize"},
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        out = to_ppt(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000
    finally:
        os.unlink(path)
```

- [ ] **Step 6: 运行全部服务层测试**

Run: `pytest tests/test_services/ -v`
Expected: 5 PASS

- [ ] **Step 7: Commit**

```bash
git add smartsuite/services/ tests/test_services/
git commit -m "feat: data IO, orchestrator, reporter (Excel/PDF/PPT)"
```

---

### Task 12: Excel 交互层 — xlwings 加载项

**Files:**
- Create: `smartsuite/excel/addin.py`
- Create: `smartsuite/excel/ribbon.py`
- Create: `smartsuite/excel/dialogs.py`

- [ ] **Step 1: 创建 Ribbon XML**

```python
# smartsuite/excel/ribbon.py
RIBBON_XML = """
<customUI xmlns="http://schemas.microsoft.com/office/2006/01/customui">
  <ribbon>
    <tabs>
      <tab id="smartsuite_tab" label="工艺分析">
        <group id="root_cause_group" label="要因分析">
          <button id="btn_correlation" label="相关性分析"
                  onAction="run_correlation" imageMso="TableAnalyze" size="large" />
          <button id="btn_anova" label="ANOVA方差分析"
                  onAction="run_anova" imageMso="ShowReportFilterPage" size="large" />
          <button id="btn_hypothesis" label="假设检验"
                  onAction="run_hypothesis_test" imageMso="CreateQueryFromWizard" size="large" />
        </group>
        <group id="doe_group" label="DOE/优化">
          <button id="btn_regression" label="回归建模"
                  onAction="run_regression" imageMso="ChartTrendline" size="large" />
          <button id="btn_rsm" label="响应面分析"
                  onAction="run_response_surface" imageMso="Chart3DSurfaceChart" size="large" />
          <button id="btn_optimize" label="最优搜索"
                  onAction="run_grid_search" imageMso="TargetInv" size="large" />
        </group>
        <group id="spc_group" label="过程监控">
          <button id="btn_spc" label="SPC控制图"
                  onAction="run_spc" imageMso="ChartLine" size="large" />
          <button id="btn_capability" label="过程能力"
                  onAction="run_process_capability" imageMso="PivotChart" size="large" />
        </group>
        <group id="report_group" label="报告输出">
          <button id="btn_excel_report" label="Excel报告"
                  onAction="run_report_excel" imageMso="FileSave" size="large" />
          <button id="btn_ppt_report" label="PPT报告"
                  onAction="run_report_ppt" imageMso="FilePublishAsPptx" size="large" />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>
"""
```

- [ ] **Step 2: 创建对话框模块**

```python
# smartsuite/excel/dialogs.py
"""对话框交互 — 列选择和参数配置。"""
import xlwings as xw


def select_columns_dialog(sheet, title: str = "选择分析列") -> dict:
    """弹窗引导用户选择目标列和因子列。"""
    used_range = sheet.range("A1").expand()
    headers = used_range.rows[0].value or []
    header_str = ", ".join(str(h) for h in headers if h)

    target = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入目标列名 (Y):", title
    )
    if not target:
        return {}

    features_str = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入因子列名 (X), 逗号分隔:", title
    )
    if not features_str:
        return {}

    return {"target": str(target).strip(),
            "features": [f.strip() for f in features_str.split(",")]}
```

- [ ] **Step 3: 创建加载项入口**

```python
# smartsuite/excel/addin.py
"""xlwings 加载项入口 — 注册 Ribbon 按钮回调。"""
import os
import xlwings as xw
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import read_excel_range, validate_data
from smartsuite.services.orchestrator import orchestrate
from smartsuite.services.reporter import to_excel, to_ppt


def _prepare_request(sheet, target, features, task, **params):
    df = read_excel_range(sheet)
    validate_data(df, target, features)
    return AnalysisRequest(task=task, data=df, target_col=target,
                           feature_cols=features, params=params)


def _run_and_report(task, output="excel", **params):
    wb = xw.Book.caller()
    sheet = wb.sheets.active
    from smartsuite.excel.dialogs import select_columns_dialog
    dlg = select_columns_dialog(sheet, title=f"配置: {task}")
    if not dlg:
        return
    req = _prepare_request(sheet, dlg["target"], dlg["features"], task, **params)
    result = orchestrate(req)

    if output == "excel":
        to_excel(result, wb, sheet_name=f"{task}_结果")
    elif output == "ppt":
        path = os.path.join(os.path.expanduser("~"), "Desktop", f"{task}_report.pptx")
        to_ppt(result, path)
        xw.apps.active.api.MsgBox(f"PPT 报告已保存至: {path}")

    if result.status == "error":
        xw.apps.active.api.MsgBox("; ".join(result.messages))
    else:
        xw.apps.active.api.MsgBox(result.summary)


def run_correlation():
    _run_and_report("correlation")

def run_anova():
    _run_and_report("anova")

def run_hypothesis_test():
    _run_and_report("hypothesis_test")

def run_regression():
    _run_and_report("regression")

def run_response_surface():
    _run_and_report("response_surface")

def run_grid_search():
    _run_and_report("grid_search")

def run_spc():
    _run_and_report("spc_xbar")

def run_process_capability():
    _run_and_report("process_capability")

def run_report_excel():
    xw.apps.active.api.MsgBox("请先运行一项分析，结果将自动输出到新 Sheet。")

def run_report_ppt():
    xw.apps.active.api.MsgBox("请先运行一项分析（如响应面），选择 PPT 输出。")


if __name__ == "__main__":
    xw.serve()
```

- [ ] **Step 4: 验证架构约束**

```bash
# engine/ 不应包含 xlwings
grep -r "xlwings" smartsuite/engine/ || echo "OK: engine/ clean"
# excel/ 不应包含 sklearn/statsmodels
grep -rE "sklearn|statsmodels" smartsuite/excel/ || echo "OK: excel/ clean"
```

- [ ] **Step 5: Commit**

```bash
git add smartsuite/excel/
git commit -m "feat: Excel addin with ribbon, dialogs, and callbacks"
```

---

### Task 13: CLI 入口 + YAML 模板

**Files:**
- Create: `smartsuite/cli.py`
- Create: `templates/example_anova.yaml`

- [ ] **Step 1: 创建 CLI**

```python
# smartsuite/cli.py
"""CLI 入口 — 命令行直接运行分析。"""
import argparse
import yaml
import pandas as pd
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate, TASK_REGISTRY


def main():
    parser = argparse.ArgumentParser(
        description="SmartSuite — 工艺数据分析工具箱")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="运行分析")
    run_parser.add_argument("template", help="YAML 分析模板路径")
    run_parser.add_argument("--input", "-i", required=True,
                             help="输入 Excel 文件路径")
    run_parser.add_argument("--sheet", "-s", default=0,
                             help="Sheet 名或索引 (默认: 第一个)")

    subparsers.add_parser("list", help="列出支持的分析方法")

    args = parser.parse_args()

    if args.command == "list":
        print("支持的分析方法:")
        for name in sorted(TASK_REGISTRY.keys()):
            print(f"  - {name}")
        return

    if args.command == "run":
        with open(args.template, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        sheet = pd.read_excel(args.input, sheet_name=args.sheet)
        req = AnalysisRequest(
            task=config["task"], data=sheet,
            target_col=config["target_col"],
            feature_cols=config.get("feature_cols", []),
            params=config.get("params", {}),
        )
        result = orchestrate(req)
        print(result.summary)
        for msg in result.messages:
            print(f"  [{result.status}] {msg}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 创建示例模板**

```yaml
# templates/example_anova.yaml
task: anova
target_col: "不良率"
feature_cols:
  - "料温"
  - "模温"
  - "注射压力"
  - "保压时间"
params:
  alpha: 0.05
  interactions: true
output:
  format: [excel, ppt]
```

- [ ] **Step 3: 验证 CLI**

Run: `python -m smartsuite.cli list`
Expected: prints 14 analysis methods

- [ ] **Step 4: Commit**

```bash
git add smartsuite/cli.py templates/example_anova.yaml
git commit -m "feat: CLI entry point and YAML template"
```

---

### Task 14: 集成测试 — 端到端 + 边界条件

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: 写集成测试**

```python
# tests/test_integration.py
"""端到端集成测试。"""
import tempfile, os
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate, TASK_REGISTRY
from smartsuite.services.reporter import to_pdf, to_ppt


def test_full_pipeline_anova_to_pdf(sample_doe_data):
    from smartsuite.services.reporter import to_pdf
    req = AnalysisRequest(
        task="anova", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"alpha": 0.05},
    )
    result = orchestrate(req)
    assert result.status in ("ok", "warning")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        to_pdf(result, path)
        assert os.path.getsize(path) > 100
    finally:
        os.unlink(path)


def test_full_pipeline_rsm_to_ppt(sample_doe_data):
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    assert len(result.figures) >= 1

    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        to_ppt(result, path)
        assert os.path.getsize(path) > 1000
    finally:
        os.unlink(path)


def test_all_tasks_registered():
    """确保所有引擎函数都在 TASK_REGISTRY 中注册。"""
    import smartsuite.engine as eng
    missing = set(eng.__all__) - set(TASK_REGISTRY.keys())
    assert not missing, f"未注册的引擎函数: {missing}"


def test_invalid_task_returns_error():
    import pandas as pd
    req = AnalysisRequest(
        task="nonexistent", data=pd.DataFrame({"a": [1, 2, 3]}), target_col="a")
    result = orchestrate(req)
    assert result.status == "error"


def test_missing_column_error(sample_doe_data):
    req = AnalysisRequest(
        task="anova", data=sample_doe_data,
        target_col="不存在的列", feature_cols=["料温"])
    try:
        from smartsuite.services.data_io import validate_data
        validate_data(req.data, req.target_col, req.feature_cols)
        assert False, "should have raised"
    except Exception:
        pass  # Expected: ValidationError
```

- [ ] **Step 2: 运行全部测试套件**

Run: `pytest tests/ -v`
Expected: all tests PASS (~23 tests)

Run: `ruff check smartsuite/`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end integration and boundary tests"
```

---

### Task 15: 项目收尾

- [ ] **Step 1: 生成覆盖率报告**

Run: `pytest tests/ --cov=smartsuite --cov-report=term`

- [ ] **Step 2: 确认 .gitignore 完整**

确保包含: `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `dist/`, `.ruff_cache/`, `.superpowers/`

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "chore: finalize V1 — polish and final checks"
```

---

## 任务依赖图

```
Task 1 (Contracts + Tests infra)
  └→ Task 2 (Exceptions)
      └→ Task 3 (Correlation)
          └→ Task 4 (ANOVA)
              └→ Task 5 (Hypothesis + Tree + VIF)
                  └→ Task 6 (Regression)
                      └→ Task 7 (RSM + Grid + MultiObj + DOE)
                          └→ Task 8 (SPC + Capability)
                              └→ Task 9 (Trend + Anomaly)
                                  └→ Task 10 (Engine API export)
                                      └→ Task 11 (Services: IO + Orch + Reporter)
                                          └→ Task 12 (Excel addin)
                                              └→ Task 13 (CLI + Template)
                                                  └→ Task 14 (Integration tests)
                                                      └→ Task 15 (Finalize)
```

---

*本计划基于设计规范 `docs/superpowers/specs/2026-06-28-smartsuite-suite-design.md` 编写。*
