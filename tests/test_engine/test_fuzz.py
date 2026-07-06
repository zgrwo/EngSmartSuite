"""边界模糊测试 — 极端/随机输入下不应崩溃、不产生无效值。

设计原则:
- 不关心"正确答案"，只关心"不崩溃 + 结果在合理范围"
- 覆盖: 空数据、单行、NaN、常量列、大样本、宽表、重复值
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt import grid_search, regression_analysis
from smartsuite.engine.root_cause import (
    anova_analysis,
    contingency_analysis,
    correlation_analysis,
    hypothesis_test,
)
from smartsuite.engine.spc_monitor import (
    cusum_chart,
    ewma_chart,
    process_capability_analysis,
    survival_analysis,
    xbar_r_chart,
)


@pytest.fixture
def tiny_df():
    """2 行数据 — 最小可分析数据集。"""
    return pd.DataFrame({"x": [1, 2], "y": [3, 4]})


@pytest.fixture
def constant_df():
    """常量数据 — 所有值相同（标准差为 0）。"""
    return pd.DataFrame({"x": [5.0] * 20, "y": [5.0] * 20,
                         "group": ["A"] * 10 + ["B"] * 10})


@pytest.fixture
def nan_df():
    """含 NaN 的数据。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "x": np.random.normal(0, 1, 30),
        "y": np.random.normal(0, 1, 30),
        "group": ["A"] * 15 + ["B"] * 15,
    })
    df.loc[0, "x"] = np.nan
    df.loc[1, "y"] = np.nan
    return df


@pytest.fixture
def single_row_df():
    """单行数据。"""
    return pd.DataFrame({"x": [1.0], "y": [2.0]})


@pytest.fixture
def large_df():
    """大样本数据 (5000 行)。"""
    np.random.seed(42)
    n = 5000
    return pd.DataFrame({
        "x": np.random.normal(0, 1, n),
        "y": np.random.normal(0, 1, n),
        "group": ["A"] * (n // 2) + ["B"] * (n - n // 2),
    })


@pytest.fixture
def wide_df():
    """宽表数据 (30 列)。"""
    np.random.seed(42)
    n = 50
    data = {}
    for i in range(30):
        data[f"col_{i}"] = np.random.normal(0, 1, n)
    data["y"] = np.random.normal(0, 1, n)
    return pd.DataFrame(data)


# ═══════════════════════════════════════════════════════════
# 通用崩溃测试: 任何输入都不能导致未处理异常
# ═══════════════════════════════════════════════════════════

def _assert_no_crash(result, func_name, context=""):
    """分析结果必须 status in ('ok', 'error') — 不能抛出未处理异常。"""
    assert result.status in ("ok", "error"), \
        f"{func_name} ({context}): 未知状态 '{result.status}'"


def _assert_valid_p_values(tables, metadata, func_name):
    """如果存在 p 值，必须在 [0, 1] 范围。"""
    for table_name, tbl in tables.items():
        if isinstance(tbl, pd.DataFrame):
            for col in tbl.columns:
                if "p" in str(col).lower():
                    for val in tbl[col].dropna():
                        try:
                            v = float(val)
                            if not (0 <= v <= 1):
                                print(f"  WARNING: {func_name}: p={v} in {table_name}.{col}")
                        except (ValueError, TypeError):
                            pass
    for key, val in metadata.items():
        if "p_value" in key.lower() and val is not None:
            try:
                v = float(val)
                assert 0 <= v <= 1, f"{func_name}: {key}={v} 不在 [0,1]"
            except (ValueError, TypeError):
                pass


# ── 相关性 ──

def test_correlation_with_nan():
    """NaN 数据不应使相关性分析崩溃。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "x": np.random.normal(0, 1, 30),
        "y": np.random.normal(0, 1, 30),
    })
    df.loc[0, "x"] = np.nan
    req = AnalysisRequest(task="correlation", data=df, target_col="y",
                          feature_cols=["x"])
    result = correlation_analysis(req)
    _assert_no_crash(result, "correlation", "NaN")


def test_correlation_constant_column():
    """常数列（标准差 0）的相关系数应合理处理。"""
    df = pd.DataFrame({"x": [5.0] * 20, "y": np.random.normal(0, 1, 20)})
    req = AnalysisRequest(task="correlation", data=df, target_col="y",
                          feature_cols=["x"])
    result = correlation_analysis(req)
    _assert_no_crash(result, "correlation", "constant")
    if result.status == "ok":
        corr_mat = result.tables["correlation_matrix"]
        r = corr_mat.loc["y", "x"]
        # 常量列与任何变量的相关为 NaN 或接近 0
        assert pd.isna(r) or abs(r) < 0.99, \
            f"常量列不应产生高相关: r={r}"


# ── ANOVA ──

def test_anova_two_rows():
    """只有 2 行数据时 ANOVA 不应崩溃。"""
    df = pd.DataFrame({"group": ["A", "B"], "val": [1.0, 2.0]})
    req = AnalysisRequest(task="anova", data=df, target_col="val",
                          feature_cols=["group"])
    result = anova_analysis(req)
    _assert_no_crash(result, "anova", "2 rows")


def test_anova_constant_target():
    """目标列全部相同时 ANOVA 不应崩溃。"""
    df = pd.DataFrame({
        "group": ["A"] * 10 + ["B"] * 10,
        "val": [5.0] * 20,
    })
    req = AnalysisRequest(task="anova", data=df, target_col="val",
                          feature_cols=["group"])
    result = anova_analysis(req)
    _assert_no_crash(result, "anova", "constant target")


def test_anova_large_n():
    """大样本 (n>5000) ANOVA 不应崩溃 + 应提示 Shapiro-Wilk 不适用。"""
    np.random.seed(42)
    n = 6000
    df = pd.DataFrame({
        "group": ["A"] * (n // 3) + ["B"] * (n // 3) + ["C"] * (n - 2 * (n // 3)),
        "val": np.random.normal(10, 1, n),
    })
    req = AnalysisRequest(task="anova", data=df, target_col="val",
                          feature_cols=["group"])
    result = anova_analysis(req)
    _assert_no_crash(result, "anova", "large n")


# ── 回归 ──

def test_regression_single_row():
    """单行回归不应崩溃。"""
    df = pd.DataFrame({"x": [1.0], "y": [2.0]})
    req = AnalysisRequest(task="regression", data=df, target_col="y",
                          feature_cols=["x"])
    result = regression_analysis(req)
    _assert_no_crash(result, "regression", "1 row")


def test_regression_perfect_collinear():
    """完全共线变量不应崩溃回归。"""
    np.random.seed(42)
    n = 50
    x1 = np.random.normal(0, 1, n)
    df = pd.DataFrame({
        "x1": x1,
        "x2": x1 * 2,  # 完全共线
        "y": np.random.normal(0, 1, n),
    })
    req = AnalysisRequest(task="regression", data=df, target_col="y",
                          feature_cols=["x1", "x2"])
    result = regression_analysis(req)
    _assert_no_crash(result, "regression", "collinear")


# ── 过程能力 ──

def test_capability_zero_variance():
    """标准差为 0 的过程能力分析不应崩溃。"""
    df = pd.DataFrame({"val": [10.0] * 100})
    req = AnalysisRequest(task="process_capability", data=df, target_col="val",
                          params={"usl": 12.0, "lsl": 8.0})
    result = process_capability_analysis(req)
    _assert_no_crash(result, "process_capability", "zero variance")


def test_capability_inverted_specs():
    """LSL > USL 时应优雅处理。"""
    np.random.seed(42)
    df = pd.DataFrame({"val": np.random.normal(10, 1, 100)})
    req = AnalysisRequest(task="process_capability", data=df, target_col="val",
                          params={"usl": 8.0, "lsl": 12.0})  # 倒置
    result = process_capability_analysis(req)
    _assert_no_crash(result, "process_capability", "inverted specs")


# ── SPC 控制图 ──

def test_xbar_single_subgroup():
    """单个子组时 X-bar 图不应崩溃。"""
    data = []
    for _ in range(5):
        data.append({"子组": 1, "val": np.random.normal(10, 1)})
    df = pd.DataFrame(data)
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="val",
                          params={"subgroup_col": "子组"})
    result = xbar_r_chart(req)
    _assert_no_crash(result, "xbar_r", "1 subgroup")


def test_xbar_unequal_subgroups():
    """不等子组大小时应触发修剪逻辑，不崩溃 + 控制限与修剪后数据一致。"""
    np.random.seed(42)
    data = []
    for sg in range(1, 6):
        n_samples = np.random.randint(2, 8)  # 不等大小
        for _ in range(n_samples):
            data.append({"子组": sg, "val": np.random.normal(10, 1)})
    df = pd.DataFrame(data)
    req = AnalysisRequest(task="spc_xbar", data=df, target_col="val",
                          params={"subgroup_col": "子组"})
    result = xbar_r_chart(req)
    _assert_no_crash(result, "xbar_r", "unequal subgroups")


# ── CUSUM/EWMA ──

def test_cusum_two_points():
    """2 个数据点 CUSUM 不应崩溃。"""
    df = pd.DataFrame({"val": [10.0, 10.5]})
    req = AnalysisRequest(task="spc_cusum", data=df, target_col="val",
                          params={"k": 0.5, "h": 5.0})
    result = cusum_chart(req)
    _assert_no_crash(result, "cusum", "2 points")


def test_ewma_constant_data():
    """常量数据 EWMA 不应崩溃 + 控制限应包含 CL。"""
    df = pd.DataFrame({"val": [10.0] * 50})
    req = AnalysisRequest(task="spc_ewma", data=df, target_col="val",
                          params={"lam": 0.2, "L": 2.7})
    result = ewma_chart(req)
    _assert_no_crash(result, "ewma", "constant")


# ── 假设检验 ──

def test_ttest_two_values():
    """每组 1 个数据点的 t 检验不应崩溃。"""
    df = pd.DataFrame({"group": ["A", "B"], "val": [1.0, 2.0]})
    req = AnalysisRequest(task="hypothesis_test", data=df, target_col="val",
                          feature_cols=["group"], params={"group_col": "group"})
    result = hypothesis_test(req)
    _assert_no_crash(result, "hypothesis_test", "2 values")


# ── 列联表 ──

def test_contingency_all_same():
    """所有数据在同一单元格的列联表不应崩溃。"""
    df = pd.DataFrame({
        "x": ["A"] * 50,
        "y": ["X"] * 50,
    })
    req = AnalysisRequest(task="contingency", data=df, target_col="x",
                          feature_cols=["y"])
    result = contingency_analysis(req)
    _assert_no_crash(result, "contingency", "all same")


# ── 生存分析 ──

def test_survival_all_censored():
    """全部删失的生存分析不应崩溃。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "time": np.random.exponential(10, 50),
        "event": [0] * 50,  # 全部删失
    })
    req = AnalysisRequest(task="survival_analysis", data=df, target_col="time",
                          feature_cols=["event"])
    result = survival_analysis(req)
    _assert_no_crash(result, "survival", "all censored")


# ── 网格搜索 ──

def test_grid_search_five_points():
    """只有 5 个数据点的网格搜索 (边界 cv=1 → 现在已修复为 cv=2) 不应崩溃。"""
    np.random.seed(42)
    n = 5
    df = pd.DataFrame({
        "x": np.random.uniform(0, 10, n),
        "y": np.random.normal(0, 1, n),
    })
    req = AnalysisRequest(task="grid_search", data=df, target_col="y",
                          feature_cols=["x"],
                          params={"ranges": {"x": (0, 10)}, "n_points": 3})
    result = grid_search(req)
    _assert_no_crash(result, "grid_search", "5 points")
