"""data_io 服务层函数单测（data_io.py）。

背景：test_quality_guard 缺测检测要求公共函数有测试引用——
auto_generate_subgroup_col / infer_group_col / preprocess_for_task
此前仅被 Web/CLI 路径间接调用，本文件补直接单测。
（read_excel_range 依赖 xlwings/Excel 环境，豁免，见 test_quality_guard.py）
"""

import numpy as np
import pandas as pd

from smartsuite.services.data_io import (
    auto_generate_subgroup_col,
    infer_group_col,
    preprocess_for_task,
)


# ── auto_generate_subgroup_col（SPC 缺子组列自动生成）──


def test_auto_generate_subgroup_col_creates_column():
    df = pd.DataFrame({"y": range(1, 21)})
    df2, params = auto_generate_subgroup_col(df, {})
    col = params["subgroup_col"]
    assert col in df2.columns
    assert df2[col].nunique() >= 2  # 至少 2 个子组
    assert len(df2) == 20  # 行数不变


def test_auto_generate_subgroup_col_does_not_mutate_input():
    df = pd.DataFrame({"y": range(1, 21)})
    cols_before = list(df.columns)
    auto_generate_subgroup_col(df, {})
    assert list(df.columns) == cols_before


# ── infer_group_col（假设检验分组列推断）──


def test_infer_group_col_finds_binary_column():
    df = pd.DataFrame({"y": [1, 2, 3, 4], "批次": ["A", "B", "A", "B"]})
    assert infer_group_col(df, ["批次"]) == {"group_col": "批次"}


def test_infer_group_col_returns_none_without_binary():
    df = pd.DataFrame({"y": [1, 2, 3], "批次": ["A", "B", "C"]})
    assert infer_group_col(df, ["批次"]) is None


# ── preprocess_for_task（任务感知预处理）──


def test_preprocess_for_task_raw_cat_keeps_original_column():
    df = pd.DataFrame({"y": [1, 2, 3], "批次": ["A", "B", "A"]})
    enc, cols, _, _ = preprocess_for_task(
        df, ["批次"], "anova", raw_cat_tasks={"anova"}
    )
    assert "批次" in cols  # 原始类别列保留
    assert enc["批次"].tolist() == ["A", "B", "A"]


def test_preprocess_for_task_encodes_without_raw_cat():
    df = pd.DataFrame({"y": [1, 2, 3], "批次": ["A", "B", "A"]})
    enc, cols, _, _ = preprocess_for_task(df, ["批次"], "regression")
    assert "批次" not in cols  # 被 one-hot 编码替换
    assert len(enc) == 3  # 行数不变
def test_preprocess_for_task_removes_inf():
    """审查 2026-08-19 #1.5：预处理应把 ±Inf 转为 NaN（dropna 不过滤 Inf）。"""
    from smartsuite.services.data_io import preprocess_for_task

    df = pd.DataFrame({"a": [1.0, np.inf, -np.inf, np.nan, 5.0], "g": ["A", "A", "B", "B", "B"]})
    out, feat, log, _ = preprocess_for_task(df, ["a"], "regression", None)
    assert np.isinf(out["a"]).sum() == 0, "预处理后不应残留 Inf"
    # RAW_CAT 分支同样清洗
    out2, feat2, _, _ = preprocess_for_task(df, ["a", "g"], "box_chart", None,
                                            raw_cat_tasks={"box_chart"})
    assert np.isinf(out2["a"]).sum() == 0, "RAW_CAT 路径也不应残留 Inf"


def test_preprocess_data_cat_map_roundtrip():
    """Round-2 P3：cat_map 回填 known_cat_map 不得产生全 NaN 参照列。"""
    from smartsuite.services.data_io import preprocess_data

    df = pd.DataFrame({"city": ["A", "B", "C", "A", "B"] * 2, "y": [1.0] * 10})
    enc1, cols1, cat_map, _, _ = preprocess_data(df, ["city"], categorical_cols={"city"})
    enc2, cols2, _, _, _ = preprocess_data(df, ["city"], categorical_cols={"city"},
                                           known_cat_map=cat_map)
    assert not enc2.isna().any().any(), f"回填产生 NaN 列: {list(enc2.columns)}"
    assert len(cols1) == len(cols2), f"列数不一致: {cols1} vs {cols2}"


