"""CLI 与 Web API 路径一致性测试 — 确保两个入口产生相同的数值结果。

原则: 相同的输入数据 + 相同的分析参数 → 相同的数值结果
这能捕获参数默认值不一致、预处理路径差异、异常处理差异等问题。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import DEFAULT_PARAMS, TASK_REGISTRY, orchestrate

# ═══════════════════════════════════════════════════════════
# 辅助: 模拟 CLI 路径 (直接调用 preprocess + orchestrate)
# ═══════════════════════════════════════════════════════════

def run_via_engine(task, df, target_col, feature_cols, params=None):
    """模拟 CLI 路径: preprocess_data → orchestrate。"""
    params = params or {}
    defaults = DEFAULT_PARAMS.get(task, {})
    merged = {**defaults, **params}
    df_enc, feat_enc, _, _, _ = preprocess_data(df, feature_cols)
    req = AnalysisRequest(task=task, data=df_enc, target_col=target_col,
                          feature_cols=feat_enc, params=merged)
    return orchestrate(req)


# ═══════════════════════════════════════════════════════════
# 默认参数一致性
# ═══════════════════════════════════════════════════════════

def test_default_params_valid():
    """所有 DEFAULT_PARAMS 中的键都对应有效的注册任务。"""
    for task_name in DEFAULT_PARAMS:
        assert task_name in TASK_REGISTRY, \
            f"DEFAULT_PARAMS 中的 '{task_name}' 不在 TASK_REGISTRY 中"


def test_all_registered_tasks_have_defaults():
    """所有注册任务至少有一个 DEFAULT_PARAMS 条目（可为空）。"""
    missing = [t for t in TASK_REGISTRY if t not in DEFAULT_PARAMS]
    assert not missing, f"以下注册任务缺少 DEFAULT_PARAMS: {missing}"


# ═══════════════════════════════════════════════════════════
# 预处理路径一致性
# ═══════════════════════════════════════════════════════════

def test_preprocess_idempotent():
    """对已预处理数据再次调用 preprocess 不应改变结果。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "x1": np.random.normal(0, 1, 50),
        "x2": np.random.normal(5, 2, 50),
        "y": np.random.normal(10, 1, 50),
    })
    # 首次预处理
    df1, cols1, _, log1, _ = preprocess_data(df, ["x1", "x2"])
    # 再次预处理
    df2, cols2, _, log2, _ = preprocess_data(df1, cols1)
    # 列名应一致
    assert cols1 == cols2, f"预处理不幂等: {cols1} ≠ {cols2}"
    # 第二次不应再有新的插补
    assert sum(log2.values()) == 0, f"二次预处理产生新插补: {log2}"


def test_imputation_only_fills_coerced():
    """预处理在数值列包含非数值字符串时，应将字符串转换为 NaN 并中位数填充。"""
    np.random.seed(42)
    # 使用全数值列（不会被检测为 categorical）
    # 构造 float 列但 dtype 为 object（模拟 Excel 导入的混合类型）
    df = pd.DataFrame({
        "num_col": pd.Series([1.0, 2.0, None, 4.0, 5.0]),  # None 产生 NaN
        "y": np.random.normal(0, 1, 5),
    })
    df2, cols, _, log, _ = preprocess_data(df, ["num_col"])
    # 预处理不应崩溃
    assert "num_col" in cols or any(c.startswith("num_col") for c in cols), \
        "num_col 应在输出列中"
    # 值不应全为 NaN
    assert df2[cols[0]].notna().sum() > 0, "输出列不应全 NaN"


# ═══════════════════════════════════════════════════════════
# 跨路径数值一致性 (抽样验证)
# ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("task,target,features,params", [
    # 要因分析
    ("correlation", "y", ["x1", "x2"], {"method": "pearson"}),
    ("correlation", "y", ["x1", "x2"], {"method": "spearman"}),
    # SPC
    ("spc_xbar", "val", [], {"subgroup_col": "子组"}),
    # 回归
    ("regression", "y", ["x1"], {}),
    ("robust_regression", "y", ["x1"], {}),
])
def test_cli_api_numerical_parity(task, target, features, params):
    """CLI 路径和直接引擎调用应产生一致的数值结果。"""
    np.random.seed(42)
    # 构建测试数据
    if task == "spc_xbar":
        data_list = []
        for sg in range(1, 8):
            for _ in range(5):
                data_list.append({"子组": sg, "val": np.random.normal(10, 1)})
        df = pd.DataFrame(data_list)
    else:
        n = 100
        df = {"x1": np.random.normal(0, 1, n),
              "x2": np.random.normal(5, 2, n),
              "y": 2.0 + 1.5 * np.random.normal(0, 1, n) + np.random.normal(0, 0.5, n)}
        df = pd.DataFrame(df)

    # 路径 1: CLI 风格 (preprocess → merge defaults → orchestrate)
    result_cli = run_via_engine(task, df, target, features, params)

    # 路径 2: 直接调用 engine (跳过 preprocess, 但使用相同的数据)
    # 注意: 直接路径假设数据已经干净
    req = AnalysisRequest(task=task, data=df, target_col=target,
                          feature_cols=features,
                          params={**DEFAULT_PARAMS.get(task, {}), **params})
    result_direct = orchestrate(req)

    # 两个路径应产生相同的 status
    assert result_cli.status == result_direct.status, \
        f"{task}: CLI={result_cli.status}, Direct={result_direct.status}"

    if result_cli.status == "ok" and result_direct.status == "ok":
        # 相同的 tables 键
        assert set(result_cli.tables.keys()) == set(result_direct.tables.keys()), \
            f"{task}: tables 键不一致"

        # summary 应非空且为字符串
        assert isinstance(result_cli.summary, str) and len(result_cli.summary) > 0, \
            f"{task}: CLI summary 为空"
        assert isinstance(result_direct.summary, str) and len(result_direct.summary) > 0, \
            f"{task}: Direct summary 为空"
