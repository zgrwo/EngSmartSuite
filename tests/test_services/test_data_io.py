"""data_io 服务层函数单测（data_io.py）。

背景：test_quality_guard 缺测检测要求公共函数有测试引用——
auto_generate_subgroup_col / infer_group_col / preprocess_for_task
此前仅被 Web/CLI 路径间接调用，本文件补直接单测。
"""

import numpy as np
import pandas as pd

from smartsuite.services.data_io import (
    auto_generate_subgroup_col,
    infer_group_col,
    infer_hypothesis_group_col,
    preprocess_for_task,
    prepare_spc_subgroup_col,
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
    enc, cols, _, _ = preprocess_for_task(df, ["批次"], "anova", raw_cat_tasks={"anova"})
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
    out2, feat2, _, _ = preprocess_for_task(
        df, ["a", "g"], "box_chart", None, raw_cat_tasks={"box_chart"}
    )
    assert np.isinf(out2["a"]).sum() == 0, "RAW_CAT 路径也不应残留 Inf"


def test_preprocess_data_cat_map_roundtrip():
    """Round-2 P3：cat_map 回填 known_cat_map 不得产生全 NaN 参照列。"""
    from smartsuite.services.data_io import preprocess_data

    df = pd.DataFrame({"city": ["A", "B", "C", "A", "B"] * 2, "y": [1.0] * 10})
    enc1, cols1, cat_map, _, _ = preprocess_data(df, ["city"], categorical_cols={"city"})
    enc2, cols2, _, _, _ = preprocess_data(
        df, ["city"], categorical_cols={"city"}, known_cat_map=cat_map
    )
    assert not enc2.isna().any().any(), f"回填产生 NaN 列: {list(enc2.columns)}"
    assert len(cols1) == len(cols2), f"列数不一致: {cols1} vs {cols2}"


# ── 共用编排函数（CLI/Web 双路一致，审查 #P2）──


def test_prepare_spc_subgroup_col_generates_when_missing():
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    df2, params = prepare_spc_subgroup_col(df, {})
    assert params.get("group_col") == params.get("subgroup_col")
    assert params["group_col"] in df2.columns, "应自动生成子组列"


def test_prepare_spc_subgroup_col_keeps_existing_group():
    df = pd.DataFrame({"y": [1.0, 2.0]})
    df2, params = prepare_spc_subgroup_col(df, {"group_col": "g"})
    assert params["group_col"] == "g"
    assert df2.equals(df), "已有 group_col 时不应改数据"


def test_infer_hypothesis_group_col_appends_feature():
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0], "组": ["A", "B", "A", "B"]})
    feats, params = infer_hypothesis_group_col(df, ["y", "组"], [], {})
    assert params.get("group_col") == "组"
    assert "组" in feats, "分组列应追加到特征列表"


def test_infer_hypothesis_group_col_no_group_preserved():
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "g": ["A", "B", "C"]})
    feats, params = infer_hypothesis_group_col(df, ["y"], [], {})
    assert params == {} and feats == ["y"], "无二分类列时应保持原样"


# ── 校验/预处理/推荐边界补测（应用层 100% 覆盖专项）──


def test_validate_data_empty_df_raises():
    """空 DataFrame → ValidationError 中文提示（data_io.py:17-18）。"""
    import pytest

    from smartsuite.core.exceptions import ValidationError
    from smartsuite.services.data_io import validate_data

    with pytest.raises(ValidationError) as ei:
        validate_data(pd.DataFrame(), "y", [])
    assert "数据为空" in str(ei.value)


def test_validate_data_tiny_sample_warning():
    """n<3 行 → 样本量过小告警（data_io.py:36-38）。"""
    from smartsuite.services.data_io import validate_data

    msgs = validate_data(pd.DataFrame({"y": [1.0, 2.0]}), "y", [])
    assert any("样本量过小" in m for m in msgs)


def test_preprocess_data_high_cardinality_warns():
    """类别列 >50 唯一值 → 记录 One-Hot 膨胀警告（data_io.py:92-100）。"""
    import pandas as pd

    from smartsuite.services.data_io import preprocess_data

    df = pd.DataFrame({"批次": [f"B{i}" for i in range(60)], "y": range(60)})
    df_enc, feats, cat_map, _, _ = preprocess_data(df, ["批次", "y"], {"批次"})
    assert len([c for c in feats if c.startswith("批次_")]) >= 50


def test_preprocess_data_known_cat_map_alignment():
    """known_cat_map 对齐：缺失类别补 0 列 + 未知类别记警告（data_io.py:105-126）。

    运行时调用方均不传 known_cat_map（仅历史对齐能力），此处直测对齐行为。
    """
    import pandas as pd

    from smartsuite.services.data_io import preprocess_data

    df = pd.DataFrame({"产线": ["A", "B", "A", "B"], "y": [1, 2, 3, 4]})
    df_enc, feats, cat_map, _, unknown = preprocess_data(
        df, ["产线"], {"产线"}, known_cat_map={"产线": ["A", "B", "C"]}
    )
    assert any("C" in c for c in feats), "缺失的已知类别 C 应补 0 列"
    assert unknown, "数据外类别应产生未知类别警告"


def test_missing_pattern_flags_high_cardinality_and_zero_variance():
    """缺失模式分析：高基数列与零方差列检出（data_io.py:227-243）。

    回归锚点（pandas 3 兼容）：自然构造的字符串列在 pandas 3 默认 str dtype，
    判别逻辑必须同样识别（此前元组缺 "str" 导致高基数检测静默失效）。
    """
    from smartsuite.services.data_io import missing_pattern_analysis

    df = pd.DataFrame(
        {
            "批次": [f"B{i}" for i in range(60)],
            "常量": [5] * 60,
            "y": range(60),
        }
    )
    info = missing_pattern_analysis(df)
    hc = info["high_cardinality_columns"]
    assert (hc["列名"] == "批次").any(), "高基数列应被检出"
    assert "常量" in info["zero_variance_columns"], "零方差列应被检出"


def test_recommend_analysis_detects_implicit_dates():
    """object 列内容为日期 → 启发式识别为日期列（data_io.py:291-297）。

    回归锚点（pandas 3 兼容）：自然字符串列默认 str dtype，日期探测必须同样触达。
    """
    import pandas as pd

    from smartsuite.services.data_io import recommend_analysis

    df = pd.DataFrame(
        {
            "日期": [f"2024-01-{d:02d}" for d in range(1, 13)],
            "y": range(12),
        }
    )
    rec = recommend_analysis(df, target_col="y")
    assert rec["data_profile"]["has_dates"] is True, "隐式日期列应被识别"


def test_recommend_analysis_recommends_anova_and_high_card():
    """类别列 2-10 水平 → 推荐 ANOVA；高基数列 → 推荐预处理（data_io.py:367-380, 449-458）。

    回归锚点（pandas 3 兼容）：自然字符串列默认 str dtype，类别列识别必须同样生效。
    """
    import pandas as pd

    from smartsuite.services.data_io import recommend_analysis

    df = pd.DataFrame(
        {
            "产线": (["L1", "L2", "L3"] * 20),
            "批次": [f"B{i}" for i in range(60)],
            "y": range(60),
        }
    )
    rec_df = recommend_analysis(df, target_col="y")["recommendations"]
    anova_rows = rec_df[rec_df["推荐分析"] == "anova"]
    assert len(anova_rows) > 0, "应推荐 ANOVA"
    assert "产线" in anova_rows.iloc[0]["原因"]
    assert any("高基数" in str(x) for x in rec_df["推荐分析"]), "高基数列应推荐预处理"


def test_recommend_analysis_date_probe_failure_swallowed(monkeypatch):
    """日期解析试探异常 → 静默跳过，不影响推荐（data_io.py:298-299）。"""
    import pandas as pd

    from smartsuite.services.data_io import recommend_analysis

    def _boom(*args, **kwargs):
        raise TypeError("模拟解析崩溃")

    monkeypatch.setattr(pd, "to_datetime", _boom)
    df = pd.DataFrame({"备注": [f"note{i}" for i in range(10)], "y": range(10)})
    rec = recommend_analysis(df, target_col="y")
    assert rec["data_profile"]["has_dates"] is False, "解析试探失败不应误判日期列"


def test_infer_group_col_finds_binary_in_pandas3_str_dtype():
    """二分类字符串列（pandas 3 str dtype）→ infer_group_col 应识别（data_io.py:527-533）。

    回归锚点：pandas 3 默认 str dtype，此前判别元组缺 "str" 导致二分组列
    无法被推断为 hypothesis_test 的分组列（静默降级为 None）。
    """
    df = pd.DataFrame({"工艺": ["旧工艺"] * 5 + ["新工艺"] * 5, "强度": range(10)})
    assert infer_group_col(df, ["工艺"], categoricals=None) == {"group_col": "工艺"}


def test_auto_generate_subgroup_col_uuid_collision_retried(monkeypatch):
    """UUID 列名冲突 → while 重试直至唯一（data_io.py:506-508）。"""
    import pandas as pd

    import smartsuite.services.data_io as dio

    calls = {"n": 0}
    real_uuid4 = dio.uuid.uuid4

    class FakeHex:
        def __init__(self, h):
            self._h = h

        @property
        def hex(self):
            return self._h

    def fake_uuid4():
        calls["n"] += 1
        if calls["n"] <= 2:
            return FakeHex("aaaaaaaa")  # 前两次同名，模拟冲突
        return real_uuid4()

    monkeypatch.setattr(dio.uuid, "uuid4", fake_uuid4)
    df = pd.DataFrame({"y": range(10), "_自动子组_aaaaaaaa": ["x"] * 10})
    df2, params = dio.auto_generate_subgroup_col(df, {})
    assert calls["n"] >= 3, "应重试生成唯一列名"
    assert params["subgroup_col"] in df2.columns
    assert params["subgroup_col"] != "_自动子组_aaaaaaaa"


def test_prepare_spc_subgroup_col_falls_back_on_generate_failure(monkeypatch):
    """子组生成失败 → 静默回退原始数据与参数（data_io.py:544-548）。"""
    import pandas as pd

    import smartsuite.services.data_io as dio

    def _boom(df, params):
        raise ValueError("生成失败")

    monkeypatch.setattr(dio, "auto_generate_subgroup_col", _boom)
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
    df2, params = dio.prepare_spc_subgroup_col(df, {})
    assert df2.equals(df) and "group_col" not in params, "失败应回退默认行为"


def test_infer_hypothesis_group_col_appends_external_group(monkeypatch):
    """分组列不在特征列表 → 追加到 feature_cols（data_io.py:563-564 防御分支）。

    infer_group_col 正常只从 features 内返回候选，此分支为防御性兜底，
    以 monkeypatch 模拟外部来源分组列直测。
    """
    import pandas as pd

    import smartsuite.services.data_io as dio

    monkeypatch.setattr(
        dio, "infer_group_col", lambda df, feats, categoricals=None: {"group_col": "产线"}
    )
    df = pd.DataFrame({"强度": [1, 2, 3, 4], "产线": ["A", "B", "A", "B"]})
    feats, params = dio.infer_hypothesis_group_col(df, ["强度"], None, {})
    assert params.get("group_col") == "产线"
    assert "产线" in feats, "外部分组列应被追加"
