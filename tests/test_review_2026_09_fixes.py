"""review-2026-09-01 修复回归测试 — 覆盖跨层修复项（真伪复核后确认项）。

对应修复项: N-1, N-2, N-3(+auto), C-1, C-2, C-4, C-5, S-1, S-4
每项先红后绿（写于修复前，随修复转绿）。
"""

import json
import os

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.exceptions import OutputError
from smartsuite.services.data_io import (
    auto_generate_subgroup_col,
    missing_pattern_analysis,
    preprocess_data,
)
from smartsuite.services.orchestrator import orchestrate
from smartsuite.web.api import _serialize_table


# ── N-1: _serialize_table 必须能序列化 datetime64 列 ──
def test_serialize_table_datetime_column_json_safe():
    df = pd.DataFrame(
        {"dt": pd.to_datetime(["2024-01-01", None, "2024-03-01"]), "y": [1.0, 2.5, 3.0]}
    )
    out = _serialize_table(df)
    # 不得抛 TypeError（datetime 对象不可 json 序列化）
    payload = json.dumps(out)
    assert "2024-01-01" in payload
    assert "y" in out["columns"]


# ── C-1: missing_pattern_analysis 0 列 DataFrame 不得抛 KeyError ──
def test_missing_pattern_analysis_zero_columns():
    result = missing_pattern_analysis(pd.DataFrame())
    assert isinstance(result, dict)
    assert "column_missing_stats" in result


# ── C-4: 显式空 categorical set = 不做 One-Hot（falsy-trap 修复）──
def test_preprocess_empty_categorical_set_no_onehot():
    df = pd.DataFrame({"城市": ["北京", "上海", "北京"], "值": [1.0, 2.0, 3.0]})
    df_enc, encoded_cols, _, _, _ = preprocess_data(df, ["城市", "值"], categorical_cols=set())
    # 显式空集合应跳过自动类别检测：不生成 城市_xxx dummy 列
    assert "城市" in encoded_cols
    assert not any(c.startswith("城市_") for c in df_enc.columns)


# ── C-5: auto_generate_subgroup_col 空 DataFrame 不得抛 ValueError ──
def test_auto_subgroup_empty_df_guarded():
    df_out, params = auto_generate_subgroup_col(pd.DataFrame(), {})
    assert isinstance(df_out, pd.DataFrame)


# ── C-2: _validate_output_path 异常应转 OutputError（reporter try 内）──
def test_to_html_makedirs_failure_raises_outputerror(monkeypatch):
    from smartsuite.services import reporter

    def _boom(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "makedirs", _boom)
    result = AnalysisResult(task="regression", status="ok", summary="s")
    with pytest.raises(OutputError):
        reporter.to_html(result, "C:/NotWritable/report.html")


# ── N-2: gage_rr sigma_multiplier 非有限值 → error（不静默传播 NaN）──
def _make_gage_df():
    rng = np.random.default_rng(0)
    rows = []
    for p in range(1, 4):
        for op in ("A", "B"):
            base = 50.0 + p
            for _ in range(2):
                rows.append({"part": p, "operator": op, "m": base + rng.normal(0, 0.3)})
    return pd.DataFrame(rows)


def test_gage_rr_sigma_multiplier_nan_rejected():
    df = _make_gage_df()
    r = orchestrate(
        AnalysisRequest(
            task="gage_rr",
            data=df,
            target_col="m",
            feature_cols=["part", "operator"],
            params={"sigma_multiplier": "nan"},
        )
    )
    assert r.status == "error"
    assert any("sigma_multiplier" in m for m in r.messages)


# ── N-3: contamination 字符串应转换（numeric string）或保留 'auto' ──
def _iso_req(contamination):
    rng = np.random.default_rng(1)
    df = pd.DataFrame(
        {"y": rng.normal(size=100), "x1": rng.normal(size=100), "x2": rng.normal(size=100)}
    )
    return AnalysisRequest(
        task="anomaly_detect",
        data=df,
        target_col="y",
        feature_cols=["x1", "x2"],
        params={"method": "isolation_forest", "contamination": contamination},
    )


def test_anomaly_contamination_numeric_string_accepted():
    r = orchestrate(_iso_req("0.05"))
    assert r.status == "ok", f"numeric string 应被接受: {r.messages}"
    assert r.metadata["contamination"] == 0.05


def test_anomaly_contamination_auto_accepted():
    r = orchestrate(_iso_req("auto"))
    assert r.status == "ok", f"'auto' 应被接受: {r.messages}"
    assert r.metadata["contamination"] == "auto"


def test_anomaly_contamination_invalid_string_rejected():
    r = orchestrate(_iso_req("abc"))
    assert r.status == "error"


# ── S-1: Web /api/analyze 畸形 task（数组）应 400 而非 500 ──
def _csrf_client(app):
    client = app.test_client()
    r0 = client.get("/api/csrf-token")
    return client, r0.get_json()["token"]


def test_analyze_unhashable_task_returns_400():
    from smartsuite.web.app import app

    client, token = _csrf_client(app)
    resp = client.post(
        "/api/analyze",
        json={
            "task": ["correlation"],
            "targets": ["y"],
            "features": [],
            "categoricals": [],
            "params": {},
        },
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 400


# ── S-4: targets/features 数量上限 → 400 ──
def test_analyze_too_many_targets_returns_400():
    from smartsuite.web.app import app

    client, token = _csrf_client(app)
    resp = client.post(
        "/api/analyze",
        json={
            "task": "correlation",
            "targets": [f"c{i}" for i in range(51)],
            "features": ["f1"],
            "categoricals": [],
            "params": {},
        },
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 400
