"""data_io 服务层函数单测（data_io.py）。

背景：test_quality_guard 缺测检测要求公共函数有测试引用——
auto_generate_subgroup_col / infer_group_col / preprocess_for_task
此前仅被 Web/CLI 路径间接调用，本文件补直接单测。
"""

import codecs
import io

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.exceptions import CsvEncodingError, CsvParseError
from smartsuite.services.data_io import (
    auto_generate_subgroup_col,
    infer_group_col,
    infer_hypothesis_group_col,
    preprocess_data,
    preprocess_for_task,
    prepare_spc_subgroup_col,
    read_csv_with_encoding,
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


def test_preprocess_data_idempotent():
    """预处理幂等：对已预处理数据再次调用不改变列集、不产生新插补。"""
    np.random.seed(42)
    df = pd.DataFrame(
        {
            "x1": np.random.normal(0, 1, 50),
            "x2": np.random.normal(5, 2, 50),
            "y": np.random.normal(10, 1, 50),
        }
    )
    df1, cols1, _, _, _ = preprocess_data(df, ["x1", "x2"])
    _, cols2, _, log2, _ = preprocess_data(df1, cols1)
    assert cols1 == cols2, f"预处理不幂等: {cols1} ≠ {cols2}"
    assert sum(log2.values()) == 0, f"二次预处理产生新插补: {log2}"


def test_preprocess_data_fills_missing_values():
    """特征列 NaN 应被中位数填充，输出不得残留 NaN。"""
    np.random.seed(42)
    df = pd.DataFrame(
        {
            "num_col": pd.Series([1.0, 2.0, None, 4.0, 5.0]),
            "y": np.random.normal(0, 1, 5),
        }
    )
    df2, cols, _, _, _ = preprocess_data(df, ["num_col"])
    assert "num_col" in cols or any(c.startswith("num_col") for c in cols)
    assert df2[cols[0]].isna().sum() == 0, (
        f"预处理后仍有 {df2[cols[0]].isna().sum()} 个 NaN，原始 NaN 未被填充"
    )


def test_preprocess_data_cat_map_roundtrip():
    """Round-2 P3：cat_map 回填 known_cat_map 不得产生全 NaN 参照列。"""
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
    df = pd.DataFrame({"批次": [f"B{i}" for i in range(60)], "y": range(60)})
    df_enc, feats, cat_map, _, _ = preprocess_data(df, ["批次", "y"], {"批次"})
    assert len([c for c in feats if c.startswith("批次_")]) >= 50


def test_preprocess_data_known_cat_map_alignment():
    """known_cat_map 对齐：缺失类别补 0 列 + 未知类别记警告（data_io.py:105-126）。

    运行时调用方均不传 known_cat_map（仅历史对齐能力），此处直测对齐行为。
    """
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


# ── read_csv_with_encoding（审查 2026-09-19 E5：移除 latin-1 静默兜底）──


def test_read_csv_with_encoding_reads_gbk(tmp_path):
    p = tmp_path / "gbk.csv"
    p.write_bytes("强度,温度\n45.1,180\n".encode("gbk"))
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["强度", "温度"]


def test_read_csv_with_encoding_reads_utf8_bom(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("强度,温度\n45.1,180\n".encode("utf-8-sig"))
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["强度", "温度"]


def test_read_csv_with_encoding_reads_utf16_bom(tmp_path):
    """UTF-16（带 BOM）由「报错」改为正确读取（ADR-0004 决策 1）。

    本用例 2026-09-21 由 `test_read_csv_with_encoding_rejects_utf16` 反转而来——
    E5 时代 utf-16 无支持、必须报错；BOM 是文件自描述，现可确定性识别。
    原意图（不得被 latin-1/GBK 静默读成乱码）仍由列名断言守住。
    """
    p = tmp_path / "utf16.csv"
    p.write_bytes("强度,温度\n45.1,180\n".encode("utf-16"))
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["强度", "温度"]


def test_read_csv_with_encoding_rejects_big5(tmp_path):
    """Big5 样本被拒（安全失败）。

    注意样本依赖性（2026-09-21 实测）：本例通过是因为「度」在 GBK 下不可解码。
    换成全部由 GBK 可解码汉字组成的 Big5 表头（如「批號」），当前会被静默误解码。
    该缺口由 `test_big5_short_header_is_silently_misdecoded_as_gbk_known_gap` 钉住。
    """
    p = tmp_path / "big5.csv"
    p.write_bytes("強度,溫度\n45.1,180\n".encode("big5"))
    with pytest.raises(CsvEncodingError, match="无法识别 CSV 文件编码"):
        read_csv_with_encoding(p)


def test_big5_short_header_is_silently_misdecoded_as_gbk_known_gap(tmp_path):
    """**已知缺口**（2026-09-21 实测，待用户决策）：短表头 Big5 被 GBK 静默误解码。

    成因：常用区 Big5 汉字 82.9%（次常用区 98.0%）在 GBK 下**可解码但解成别的字**，
    故 k 个汉字组成的表头约有 0.829^k 概率静默乱码（k=1 ≈ 83%、k=2 ≈ 69%）；
    只有含任一 GBK 不可解码的汉字时才会抛 `CsvEncodingError`（安全失败）。

    复现：`python -c` 把 `批號\nB23\n` 以 Big5 存入文件后调用 `read_csv_with_encoding`。

    **现状出口（2026-09-21 起）**：不声明编码时本用例仍成立；改用 `encoding="big5"`
    （CLI `--encoding big5` / Web 上传面板“文件编码”下拉框）即可正确解码，
    见 `test_explicit_big5_decodes_traditional_header` 与 ADR-0004。
    自动探测方案经实测否证（GBK/Big5 短样本不可分，误判率最高 51.5%），不再计划实施。
    """
    p = tmp_path / "big5_short.csv"
    p.write_bytes("批號\nB23\n".encode("big5"))
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["у腹"], "此处不再乱码 → 编码探测缺口已修复，请更新文档与 ROADMAP"


def test_read_csv_with_encoding_bytesio_reseek():
    """BytesIO 源：utf-8 尝试消耗流位置后，gbk 重试前必须 seek(0)。"""
    buf = io.BytesIO("强度,温度\n45.1,180\n".encode("gbk"))
    df = read_csv_with_encoding(buf)
    assert list(df.columns) == ["强度", "温度"]


def test_read_csv_with_encoding_parse_error(tmp_path):
    """编码可解码但结构非法 → CsvParseError（区别于编码错误）。"""
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n1,2\n1,2,3\n")
    with pytest.raises(CsvParseError, match="无法解析 CSV 文件"):
        read_csv_with_encoding(p)


def test_read_csv_with_encoding_nrows(tmp_path):
    p = tmp_path / "many.csv"
    p.write_bytes(b"a\n" + b"1\n" * 50)
    df = read_csv_with_encoding(p, nrows=10)
    assert len(df) == 10


# ── BOM 确定性判定（ADR-0004）──


def _bom_csv(tmp_path, name: str, text: str, bom: bytes, codec: str):
    """构造「BOM + 指定编码正文」的 CSV 文件（跨平台显式拼 BOM，不依赖本机字节序）。"""
    p = tmp_path / name
    p.write_bytes(bom + text.encode(codec))
    return p


@pytest.mark.parametrize(
    ("bom", "codec"),
    [
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ],
)
def test_utf16_bom_file_reads_correctly(tmp_path, bom, codec):
    """UTF-16 BOM 文件：由「无法识别编码」变为正确读取（ADR-0004 决策 1）。"""
    text = "批號,溫度\nB2301,235\n"
    p = _bom_csv(tmp_path, "u16.csv", text, bom, codec)
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["批號", "溫度"]
    assert df["溫度"].tolist() == [235]


@pytest.mark.parametrize(
    ("bom", "codec"),
    [
        (codecs.BOM_UTF32_LE, "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32-be"),
    ],
)
def test_utf32_bom_not_misread_as_utf16(tmp_path, bom, codec):
    """UTF-32 BOM：长 BOM 必须优先比较，否则被当成 UTF-16 解出乱码（ADR-0004 约束）。"""
    text = "批號,溫度\nB2301,235\n"
    p = _bom_csv(tmp_path, "u32.csv", text, bom, codec)
    df = read_csv_with_encoding(p)
    assert list(df.columns) == ["批號", "溫度"]


def test_utf8_bom_columns_clean(tmp_path):
    """UTF-8 BOM 文件：BOM 不出现在首列名中（既有行为，BOM 改造后不得回归）。"""
    p = tmp_path / "u8.csv"
    p.write_bytes(codecs.BOM_UTF8 + "批号,温度\nB1,235\n".encode())
    assert list(read_csv_with_encoding(p).columns) == ["批号", "温度"]


def test_bom_sniff_does_not_consume_bytesio():
    """BytesIO 源：BOM 嗅探后流位置必须复位，否则后续读取丢首行。"""
    buf = io.BytesIO(codecs.BOM_UTF16_LE + "批號,溫度\nB2301,235\n".encode("utf-16-le"))
    df = read_csv_with_encoding(buf)
    assert list(df.columns) == ["批號", "溫度"]
    assert len(df) == 1


def test_fallback_chain_excludes_utf16_and_utf32():
    """ADR-0004 约束：无 BOM 的自动回退链禁止含 utf-16/utf-32。

    理由（2026-09-21 订正）：回退链**仅在无 BOM 时执行**，而 pandas 的 `utf-16`
    解码器要求 BOM（无 BOM 抛 `UnicodeError`）——该链项永远不可能命中，属死代码。
    早期理由写作「无 BOM 的 GBK 会被 utf-16 静默解码成乱码」，经验证**不成立**
    （审查 R1-6），已同步修正 ADR 与 data_io 注释。
    """
    from smartsuite.services import data_io

    assert data_io._CSV_ENCODINGS == ("utf-8-sig", "utf-8", "gbk")


# ── 显式声明编码（ADR-0004 决策 2）──


def test_explicit_big5_decodes_traditional_header(tmp_path):
    """显式 big5：繁体表头正确解码——报警钉子的正面出路（ADR-0004）。

    对照 test_big5_short_header_is_silently_misdecoded_as_gbk_known_gap：
    不声明编码时仍会静默误解码，声明后结果正确。
    """
    p = tmp_path / "big5.csv"
    p.write_bytes("批號,溫度\nB2301,235\n".encode("big5"))
    df = read_csv_with_encoding(p, encoding="big5")
    assert list(df.columns) == ["批號", "溫度"]
    assert df["溫度"].tolist() == [235]


def test_explicit_encoding_superset_covers_auto_chain():
    """显式白名单必须能表达自动链的每种编码，否则「自动能读、显式不能读」。

    自动链含 "utf-8"，白名单有意用 utf-8-sig 承担该角色（无 BOM 时两者等价，
    含 BOM 时 utf-8-sig 才正确），故按「除 utf-8 外全部逐名覆盖 + utf-8-sig 在位」判定。
    """
    from smartsuite.services import data_io

    assert set(data_io._CSV_ENCODINGS) - {"utf-8"} <= set(data_io.SUPPORTED_CSV_ENCODINGS)
    assert "utf-8-sig" in data_io.SUPPORTED_CSV_ENCODINGS


def test_explicit_unsupported_encoding_rejected_with_options(tmp_path):
    """白名单外编码：中文报错并列出可选项，不得透传 pandas 英文异常。"""
    p = tmp_path / "gbk.csv"
    p.write_bytes("批号,温度\nB1,235\n".encode("gbk"))
    with pytest.raises(CsvEncodingError, match="不支持的编码"):
        read_csv_with_encoding(p, encoding="latin-1")


def test_explicit_encoding_mismatch_reports_chinese_error(tmp_path):
    """声明的编码与实际不符：报错文案需点明「指定编码」并提示改选自动。

    用 utf-8-sig 构造不匹配（Big5 字节不是合法 UTF-8）。
    （订正：早期 docstring 称「utf-16 可静默解码故不能用」，该说法经实测不成立——
    utf-16 对无 BOM 内容同样抛错，见 test_bomless_bytes_are_not_decoded_by_utf16_codec。）
    """
    p = tmp_path / "big5.csv"
    p.write_bytes("批號,溫度\nB2301,235\n".encode("big5"))
    with pytest.raises(CsvEncodingError, match="指定编码"):
        read_csv_with_encoding(p, encoding="utf-8-sig")


def test_explicit_encoding_parse_error_is_parse_not_encoding(tmp_path):
    """显式编码下结构非法：仍抛 CsvParseError（区别于编码错误），与自动路径语义一致。"""
    p = tmp_path / "bad.csv"
    p.write_bytes(b"a,b\n1,2\n1,2,3\n")
    with pytest.raises(CsvParseError):
        read_csv_with_encoding(p, encoding="gbk")


def test_explicit_encoding_applies_to_bytesio_nrows():
    """BytesIO + nrows：显式编码与行数探测组合可用（Web 探测路径）。"""
    body = b"".join(b"B%d,235\n" % i for i in range(20))
    buf = io.BytesIO("批號,溫度\n".encode("big5") + body)
    df = read_csv_with_encoding(buf, nrows=5, encoding="big5")
    assert list(df.columns) == ["批號", "溫度"]
    assert len(df) == 5


def test_bomless_bytes_are_not_decoded_by_utf16_codec():
    """证据锚点（ADR-0004 决策 4 论据）：pandas 的 `utf-16` 解码器**要求 BOM**。

    性质说明：本用例是**外部行为的特征化钉子**（不是 TDD 的红-绿循环）——它的价值
    在于让 ADR 的论据可被 CI 复验，避免文档里的因果陈述再次变成未实测的推测
    （2026-09-21 审查 R1-6 即因此纠错）。

    实测（2026-09-21，奇数 19B 与偶数 18B 均然）：

        pd.read_csv(io.BytesIO(gbk_bytes), encoding="utf-16")
        → UnicodeError: UTF-16 stream does not start with BOM

    推论：把 `"utf-16"` 放进自动回退链是**死代码**——回退链仅在无 BOM 时执行，
    而 BOM 场景已由 `_bom_encoding` 前置覆盖（带 BOM 的 UTF-16 文件在自动模式下
    本就能正确读取，见 `test_utf16_bom_file_reads_correctly`）。
    若 pandas 将来放宽 BOM 要求，本用例会失败并提醒同步修订 ADR 的论据。
    """
    import io

    import pandas as pd

    for text in ("批号,温度\nB123,235\n", "批次,温度\nAB1,235\n"):
        raw = text.encode("gbk")
        with pytest.raises(UnicodeError, match="BOM"):
            pd.read_csv(io.BytesIO(raw), encoding="utf-16")


def test_bomless_utf16_short_header_silently_misdecoded_known_gap():
    """**已知缺口（报警钉子）**：无 BOM 的 UTF-16LE 可能被 GBK 静默误解码。

    2026-09-21 审查 R1-5 实测（6 个样本）：5 个走「安全失败」抛 CsvEncodingError，
    1 个（`料号,数量\nAB1,235\nAC2,240\n`）**静默成功**且列名为乱码
    `['檈鱏', 'Unnamed: 1']`——即无 BOM 的 UTF-16 存在样本相关的静默乱码通路。

    性质与责任边界：
    - **非本次变更引入**：无 BOM 路径的逻辑（`_CSV_ENCODINGS` 链）在 v1.4.0 与
      HEAD 逐字相同（实测比对），BOM 嗅探与显式声明只是**新增**分支；
    - 是否可修：需要编码探测（该方案已由 ADR-0004 决策 4 否证：GBK/Big5 短样本
      不可分，误判率最高 51.5%）。当前口径 = 用户显式声明 + 文档引导；
    - 本用例是**报警钉子而非规格**：若将来引入编码探测并修好，此处会失败，
      提醒同步更新本用例与 ADR-0004。
    """
    import io

    p = "料号,数量\nAB1,235\nAC2,240\n"
    df = read_csv_with_encoding(io.BytesIO(p.encode("utf-16-le")))
    # 当前（错误）行为：不报错，列名乱码
    assert list(df.columns) == ["檈鱏", "Unnamed: 1"], (
        "此处不再乱码 → 无 BOM UTF-16 的静默误解码已修复，请同步更新 ADR-0004 与手册"
    )
