"""web/api.py 内部机制单测（应用层 100% 覆盖专项）。

覆盖面：_serialize_meta 序列化矩阵（ndarray/np 数值/深度保护）、
多目标相关性合并矩阵、unknown-cat 警告通路、单目标异常兜底。
"""

import numpy as np
import pandas as pd

from smartsuite.web import api as api_module
from smartsuite.web.api import _serialize_meta, run_analysis


# ── _serialize_meta 序列化矩阵 ──


def test_serialize_meta_numpy_scalar_and_array():
    assert _serialize_meta(np.int64(7)) == 7
    assert _serialize_meta(np.float64(1.5)) == 1.5
    assert _serialize_meta(np.array([1, 2])) == [1, 2]
    assert _serialize_meta(pd.Series([1.0, 2.0])) == [1.0, 2.0]
    assert _serialize_meta(pd.DataFrame({"a": [1]})) == [[1]]


def test_serialize_meta_nonfinite_becomes_null():
    """±Inf/NaN → None（JSON 合法性）（api.py:67, 71）。"""
    assert _serialize_meta(float("inf")) is None
    assert _serialize_meta(float("nan")) is None
    assert _serialize_meta(np.float64(float("-inf"))) is None


def test_serialize_meta_depth_guard():
    """循环引用 → 超过 10 层后 str 兜底，不无限递归（api.py:53-54）。"""
    d: dict = {"k": "v"}
    d["self"] = d
    out = _serialize_meta(d)
    assert isinstance(out, dict)


# ── run_analysis 通路 ──


def test_run_analysis_multi_target_correlation_merged_matrix():
    """correlation 多目标 → 第一个结果附带 _merged_correlation（api.py:174-195, 216-217）。"""
    df = pd.DataFrame(
        {
            "强度": [45.0, 46.0, 47.0, 48.0, 49.0, 50.0] * 3,
            "硬度": [10.0, 10.5, 11.0, 11.5, 12.0, 12.5] * 3,
            "温度": [180.0, 182.0, 184.0, 186.0, 188.0, 190.0] * 3,
        }
    )
    results = run_analysis("correlation", df, ["强度", "硬度"], ["温度"], [], {})
    assert len(results) == 2
    merged = results[0]["tables"].get("_merged_correlation")
    assert merged is not None, "第一个结果应附带合并矩阵"
    assert merged["index"] == ["强度", "硬度"]
    second = results[1]["tables"]
    assert "_merged_correlation" not in second, "仅第一个结果附带合并矩阵"


def test_run_analysis_unknown_category_warning_path(monkeypatch):
    """preprocess 产出未知类别警告 → 提升为用户可见消息（api.py:165-172）。

    运行时 preprocess_data 不传 known_cat_map，此通路以 canned 预处理器直测。
    """

    def fake_preprocess(df, features, task, categoricals, raw_cat_tasks):
        return df, list(features), {}, [("产线", {"L9"}, 2)]

    monkeypatch.setattr(api_module, "preprocess_for_task", fake_preprocess)
    df = pd.DataFrame({"强度": [1.0, 2.0, 3.0], "产线": ["A", "B", "A"]})
    results = run_analysis("correlation", df, ["强度"], ["产线"], [], {})
    joined = "\n".join(results[0]["messages"])
    assert "未知类别" in joined and "影响 2 行" in joined


def test_run_analysis_per_target_exception_returns_error_row(monkeypatch):
    """单目标分析异常 → 该目标降级 error 行，不拖垮整体（api.py:240-251）。

    同时覆盖合并矩阵循环内的单目标异常隔离（api.py:191-192）：
    orchestrate 全程抛错 → 合并循环捕获告警（merged_corr 不产出），
    逐目标循环亦各自降级 error。
    """

    def boom(req):
        raise RuntimeError("引擎崩溃")

    monkeypatch.setattr(api_module, "orchestrate", boom)
    df = pd.DataFrame(
        {
            "强度": [1.0, 2.0, 3.0],
            "硬度": [2.0, 4.0, 6.0],
            "温度": [180.0, 182.0, 184.0],
        }
    )
    results = run_analysis("correlation", df, ["强度", "硬度"], ["温度"], [], {})
    assert len(results) == 2
    for r in results:
        assert r["status"] == "error"
        assert "分析异常" in r["messages"][0]
        assert r["tables"] == {} and r["charts"] == []
    assert all("_merged_correlation" not in r["tables"] for r in results)
