"""Round-2 审查修复批次B — 回归测试（TDD：先红后绿）。

覆盖:
- cli.py: _parse_sheet / 缺 task / 空 YAML / 缺列模板 中文错误
- api.py: One-Hot 冲突 ValidationError、categoricals 校验、_serialize_meta、
          表格 inf→NaN 序列化
- app.py: get_json(silent) 400、categoricals 400、ValidationError→400
- audit.py: ±Inf 清洗、缺列不崩溃、失败 health_check 反映
- reporter.py: to_pdf 表格行 CJK 字体
- smartsuite.__init__.py: setup_logging 幂等 / 归一化 / 降级
"""

import json
import logging
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisResult
from smartsuite.core.exceptions import ValidationError


# ─────────────────────────── cli.py (任务 7) ───────────────────────────


def test_parse_sheet_pure_digit_string():
    """'0'/'01' 字符串按索引解析为 int；'Sheet1'/None 原样保留。"""
    from smartsuite.cli import _parse_sheet

    assert _parse_sheet("0") == 0
    assert _parse_sheet("01") == 1
    assert _parse_sheet(0) == 0
    assert _parse_sheet("Sheet1") == "Sheet1"
    assert _parse_sheet(None) is None


def _run_cli(monkeypatch, args, capsys):
    """以给定 argv 调用 cli.main()，返回 (exit_code_or_None, stdout, stderr)。"""
    import smartsuite.cli as cli_mod

    monkeypatch.setattr(sys, "argv", args)
    exit_code = None
    try:
        cli_mod.main()
    except SystemExit as e:
        exit_code = e.code
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_cli_missing_task_key(monkeypatch, tmp_path, capsys):
    """模板缺 task 键 → 中文错误 + exit 1（当前 :87 裸 KeyError）。"""
    tmpl = tmp_path / "no_task.yaml"
    tmpl.write_text("target_col: 不良率\nfeature_cols: [熔体温度]\n", encoding="utf-8")
    code, out, err = _run_cli(
        monkeypatch,
        ["smartsuite", "run", str(tmpl), "--input", "tests/test_data.xlsx"],
        capsys,
    )
    assert code == 1, f"应 exit 1，实际 {code}"
    assert "错误:" in (out + err), f"应输出中文错误: {out} {err}"


def test_cli_empty_yaml(monkeypatch, tmp_path, capsys):
    """空 YAML（config=None）→ 中文错误，不抛 TypeError。"""
    tmpl = tmp_path / "empty.yaml"
    tmpl.write_text("", encoding="utf-8")
    code, out, err = _run_cli(
        monkeypatch,
        ["smartsuite", "run", str(tmpl), "--input", "tests/test_data.xlsx"],
        capsys,
    )
    assert code == 1, f"应 exit 1，实际 {code}"
    assert "错误:" in (out + err), f"应输出中文错误: {out} {err}"


def test_cli_missing_column_template(monkeypatch, tmp_path, capsys):
    """模板引用不存在的列 → 中文错误（当前 preprocess KeyError 裸奔）。"""
    tmpl = tmp_path / "bad_col.yaml"
    tmpl.write_text(
        "task: correlation\ntarget_col: 不良率\nfeature_cols: [不存在的列]\n",
        encoding="utf-8",
    )
    code, out, err = _run_cli(
        monkeypatch,
        ["smartsuite", "run", str(tmpl), "--input", "tests/test_data.xlsx"],
        capsys,
    )
    assert code == 1, f"应 exit 1，实际 {code}"
    assert "错误:" in (out + err), f"应输出中文错误: {out} {err}"


def test_cli_sheet_zero_index(monkeypatch, tmp_path, capsys):
    """--sheet '0'（字符串）按索引解析，正常执行完成。"""
    tmpl = tmp_path / "corr.yaml"
    tmpl.write_text(
        "task: correlation\ntarget_col: 不良率\nfeature_cols: [熔体温度, 模具温度]\n",
        encoding="utf-8",
    )
    code, out, err = _run_cli(
        monkeypatch,
        ["smartsuite", "run", str(tmpl), "--input", "tests/test_data.xlsx", "--sheet", "0"],
        capsys,
    )
    assert code is None, f"正常执行不应 exit，实际 exit {code}: {out} {err}"
    assert out.strip(), "应输出分析结论"


# ─────────────────────────── api.py (任务 8/9/10) ───────────────────────────


def test_run_analysis_onehot_conflict_raises_validation():
    """One-Hot 编码列名冲突 → ValidationError（当前 500）。"""
    from smartsuite.web.api import run_analysis

    df = pd.DataFrame(
        {
            "不良率": [1.0, 2.0, 3.0, 4.0],
            "原料类型": ["A", "B", "A", "B"],
            "原料类型_B": [5.0, 6.0, 7.0, 8.0],  # 与 One-Hot 生成的列重名
        }
    )
    with pytest.raises(ValidationError):
        run_analysis("regression", df, ["不良率"], ["原料类型"], ["原料类型"], {})


def test_run_analysis_categoricals_not_list():
    """categoricals 非 list → ValidationError。"""
    from smartsuite.web.api import run_analysis

    df = pd.DataFrame({"不良率": [1.0, 2.0], "熔体温度": [3.0, 4.0]})
    with pytest.raises(ValidationError):
        run_analysis(
            "correlation", df, ["不良率"], ["熔体温度"], categoricals="熔体温度", params={}
        )


def test_serialize_meta_df_series_ndarray():
    """DataFrame/Series/ndarray 显式转列表，而非巨型 str()。"""
    from smartsuite.web.api import _serialize_meta

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert _serialize_meta(df) == [[1, 3], [2, 4]]
    assert _serialize_meta(pd.Series([1, 2])) == [1, 2]
    assert _serialize_meta(np.array([[1.5, 2.5]])) == [[1.5, 2.5]]


def test_serialize_table_inf_replaced():
    """表格序列化 round 前 inf/-inf → NaN → fillna('')，JSON 无 Infinity。"""
    from smartsuite.web.api import _serialize_table

    tbl = pd.DataFrame({"a": [1.0, np.inf, 2.0], "b": [-np.inf, 3.0, 4.0]})
    out = _serialize_table(tbl)
    flat = [v for row in out["data"] for v in row]
    assert not any(isinstance(v, float) and not np.isfinite(v) for v in flat)
    assert "Infinity" not in json.dumps(out)


def test_run_analysis_vif_inf_not_in_json():
    """VIF 共线场景产生 inf 表 → 序列化后 JSON 无 Infinity（防 JSON.parse 崩）。"""
    from smartsuite.web.api import run_analysis

    dfv = pd.DataFrame(
        {
            "a": [1.0, 2, 3, 4, 5, 6],
            "b": [1.0, 2, 3, 4, 5, 6],
            "c": [2.0, 4, 6, 8, 10, 12],
        }
    )
    results = run_analysis("vif", dfv, [], ["a", "b", "c"], [])
    assert results[0]["status"] == "ok"
    text = json.dumps(results)
    assert "Infinity" not in text, "VIF inf 表不应产生 JSON Infinity"


# ─────────────────────────── app.py (任务 11) ───────────────────────────


@pytest.fixture()
def api_client(tmp_path):
    """带 CSRF + _data_path 会话的 Flask test client。"""
    from smartsuite.web.app import app

    df = pd.DataFrame(
        {
            "不良率": [1.0, 2.0, 3.0, 4.0, 5.0],
            "熔体温度": [10.0, 20.0, 30.0, 40.0, 50.0],
            "原料类型": ["A", "B", "A", "B", "A"],
            "原料类型_B": [5.0, 6.0, 7.0, 8.0, 9.0],
        }
    )
    pq = tmp_path / "data.parquet"
    df.to_parquet(pq)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "test-token"
        sess["_data_path"] = str(pq)
    return client


def _post_analyze(client, payload=None, raw=None, content_type="application/json"):
    headers = {"X-CSRF-Token": "test-token"}
    if raw is not None:
        return client.post("/api/analyze", data=raw, content_type=content_type, headers=headers)
    return client.post("/api/analyze", json=payload, headers=headers)


def test_analyze_invalid_json_400(api_client):
    """非法 JSON body → 400 中文（get_json(silent=True) 后 body=None）。"""
    resp = _post_analyze(api_client, raw="{not-json{{{", content_type="application/json")
    assert resp.status_code == 400
    assert "JSON" in resp.get_json()["error"]


def test_analyze_categoricals_not_list_400(api_client):
    """categoricals 非 list → 400 中文。"""
    resp = _post_analyze(
        api_client,
        payload={
            "task": "regression",
            "targets": ["不良率"],
            "features": ["熔体温度"],
            "categoricals": "熔体温度",
            "params": {},
        },
    )
    assert resp.status_code == 400
    assert "categoricals" in resp.get_json()["error"]


def test_analyze_onehot_conflict_400(api_client):
    """One-Hot 列名冲突 → 400（ValidationError 映射），不再 500。"""
    resp = _post_analyze(
        api_client,
        payload={
            "task": "regression",
            "targets": ["不良率"],
            "features": ["原料类型"],
            "categoricals": ["原料类型"],
            "params": {},
        },
    )
    assert resp.status_code == 400, (
        f"应 400，实际 {resp.status_code}: {resp.get_data(as_text=True)}"
    )
    assert "One-Hot" in resp.get_json()["error"]


def test_analyze_missing_body_400(api_client):
    """空 body → 400 中文。"""
    resp = _post_analyze(api_client, raw="", content_type="application/json")
    assert resp.status_code == 400


def test_analyze_no_data_task_without_upload():
    """无需数据的任务（doe_design）在未上传数据文件时应能正常运行，不再报「请先上传」。"""
    from smartsuite.web.app import app

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "test-token"
        # 不设置 _data_path，模拟未上传文件
    resp = _post_analyze(
        client,
        payload={
            "task": "doe_design",
            "targets": [],
            "features": [],
            "categoricals": [],
            "params": {
                "method": "full_factorial",
                "factors": [{"name": "A", "levels": [1, 2]}],
                "randomize": False,
            },
        },
    )
    assert resp.status_code == 200, (
        f"应 200，实际 {resp.status_code}: {resp.get_data(as_text=True)}"
    )
    results = resp.get_json()["results"]
    assert results[0]["status"] == "ok"
    assert results[0]["metadata"]["n_runs"] == 2


# ─────────────────────────── audit.py (任务 12) ───────────────────────────


def test_process_audit_missing_feature_col_no_crash():
    """feature_cols 含不存在列 → 不抛 KeyError（当前 :40 在 try 外）。"""
    from smartsuite.services.audit import process_audit

    df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0], "a": [2.0, 3.0, 4.0, 5.0, 6.0]})
    out = process_audit(df, target_col="y", feature_cols=["不存在列", "a"])
    assert "health_checks" in out


def test_process_audit_correlation_failure_healthcheck():
    """correlation 分析失败（常量目标）→ health_check 显示 ✗ 失败而非误导。"""
    from smartsuite.services.audit import process_audit

    df = pd.DataFrame(
        {
            "y": [5.0] * 5,
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    out = process_audit(df, target_col="y", feature_cols=["a", "b"])
    checks = out["health_checks"]
    corr_check = checks[checks["检查项"] == "关键因子识别"]
    assert len(corr_check) == 1
    assert str(corr_check.iloc[0]["状态"]).startswith("✗"), (
        f"相关失败应显示失败状态: {corr_check.iloc[0]['状态']}"
    )
    assert "无强相关因子" not in str(corr_check.iloc[0]["详情"])


@pytest.mark.parametrize(
    "entry", ["batch_analyze", "process_audit", "export_workbook", "auto_report"]
)
def test_audit_entries_clean_inf(monkeypatch, tmp_path, entry):
    """四个入口在分析前统一 ±Inf→NaN 清洗。"""
    from smartsuite.services import audit as audit_mod

    captured = {}

    def fake_orchestrate(req):
        captured["df"] = req.data.copy()
        return AnalysisResult(task=req.task, status="ok", summary="ok", tables={}, figures=[])

    monkeypatch.setattr(audit_mod, "orchestrate", fake_orchestrate)
    df = pd.DataFrame(
        {
            "y": [1.0, 2.0, 3.0, 4.0, 5.0],
            "a": [1.0, np.inf, 3.0, 4.0, 5.0],
            "b": [2.0, 3.0, -np.inf, 5.0, 6.0],
        }
    )
    if entry == "batch_analyze":
        audit_mod.batch_analyze(df, "y", ["a", "b"], tasks=["correlation"])
    elif entry == "process_audit":
        audit_mod.process_audit(df, "y", ["a", "b"])
    elif entry == "export_workbook":
        out = os.path.join(str(tmp_path), "wb.xlsx")
        audit_mod.export_workbook(df, "y", ["a", "b"], output_path=out, tasks=["correlation"])
    else:
        out = os.path.join(str(tmp_path), "report.html")
        audit_mod.auto_report(df, "y", ["a", "b"], output_path=out)
    assert "df" in captured, f"{entry} 应调用 orchestrate"
    sub = captured["df"][["a", "b"]]
    assert not (sub == np.inf).any().any() and not (sub == -np.inf).any().any(), (
        f"{entry} 传入引擎的数据仍含 ±Inf"
    )


# ─────────────────────────── reporter.py (任务 13) ───────────────────────────


def test_to_pdf_table_rows_use_body_font(monkeypatch, tmp_path):
    """to_pdf 表格行不再用 Courier（CJK 内容静默丢失）。"""
    import reportlab.pdfgen.canvas as rl_canvas_mod

    created = []

    class RecordingCanvas(rl_canvas_mod.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.font_calls = []
            created.append(self)

        def setFont(self, name, size, leading=None):  # noqa: N802 — 覆盖 reportlab Canvas.setFont
            self.font_calls.append((name, size))
            return super().setFont(name, size, leading)

    monkeypatch.setattr(rl_canvas_mod, "Canvas", RecordingCanvas)

    from smartsuite.services.reporter import to_pdf

    result = AnalysisResult(
        task="correlation",
        status="ok",
        summary="中文结论测试",
        tables={"相关性": pd.DataFrame({"因子": ["熔体温度"], "r": [0.85]})},
        figures=[],
    )
    out = os.path.join(str(tmp_path), "report.pdf")
    to_pdf(result, out)
    assert created, "应创建 canvas"
    canvas = created[-1]
    table_fonts = [name for name, size in canvas.font_calls if size == 7]
    assert table_fonts, "应存在表格行 setFont(_, 7) 调用"
    assert all(name != "Courier" for name in table_fonts), f"表格行仍使用 Courier: {table_fonts}"


# ─────────────────────────── __init__.py (任务 14) ───────────────────────────


@pytest.fixture()
def root_handlers_backup():
    """保存并恢复 root logger 的 handlers（setup_logging 测试用）。"""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    root.handlers.clear()
    yield root
    root.handlers.clear()
    root.handlers.extend(saved_handlers)
    root.setLevel(saved_level)


def _managed_handlers(root):
    return [h for h in root.handlers if getattr(h, "_smartsuite_managed", False)]


def test_setup_logging_idempotent(root_handlers_backup):
    """重复调用 setup_logging 不重复添加 handler（幂等守卫基于本包 handler）。"""
    from smartsuite import setup_logging

    setup_logging()
    first = len(_managed_handlers(root_handlers_backup))
    setup_logging()
    second = len(_managed_handlers(root_handlers_backup))
    assert first == 2, f"首次应添加文件+控制台 2 个 handler，实际 {first}"
    assert second == 2, f"重复调用不应新增 handler: {first} -> {second}"


def test_setup_logging_other_handlers_do_not_block(root_handlers_backup):
    """root 上存在其他 handler 时，setup_logging 仍添加本包 handler。"""
    from smartsuite import setup_logging

    root = root_handlers_backup
    root.addHandler(logging.NullHandler())
    setup_logging()
    assert len(_managed_handlers(root)) == 2


def test_setup_logging_normpath(root_handlers_backup, monkeypatch):
    """log_dir 归一化：带 .. 的路径被 normpath 处理。"""
    from smartsuite import setup_logging

    base = tempfile.mkdtemp()
    weird = os.path.join(base, "sub", "..", "logs")
    setup_logging(log_dir=weird)
    fh = _managed_handlers(root_handlers_backup)[0]
    assert fh.baseFilename == os.path.normpath(os.path.join(weird, "smartsuite.log"))


def test_setup_logging_makedirs_fallback(root_handlers_backup, monkeypatch):
    """makedirs 失败 → 降级 tempfile + warning，不崩溃。"""
    from smartsuite import setup_logging

    root = root_handlers_backup
    real_makedirs = os.makedirs

    def failing_makedirs(path, *a, **kw):
        if "logs" in str(path) or "smartsuite" in str(path).lower():
            raise OSError("denied")
        return real_makedirs(path, *a, **kw)

    monkeypatch.setattr(os, "makedirs", failing_makedirs)
    setup_logging(log_dir=os.path.join(tempfile.gettempdir(), "logs"))
    handlers = _managed_handlers(root)
    assert len(handlers) >= 1, "即使文件 handler 降级，控制台 handler 仍应存在"


def test_run_analysis_spc_auto_subgroup():
    """Round-2 P3：Web 路径 cusum/ewma 无 group_col 时自动生成子组列。"""
    import numpy as np
    import pandas as pd

    from smartsuite.web.api import run_analysis

    np.random.seed(3)
    df = pd.DataFrame({"y": np.random.normal(50, 2, 100)})
    res = run_analysis("spc_cusum", df, targets=["y"], features=[], categoricals=[], params={})
    assert res and res[0]["status"] == "ok", f"spc_cusum 失败: {res[0].get('messages')}"
    assert res[0]["metadata"].get("n_groups", 0) > 1, (
        f"应自动生成多子组系列，实际 n_groups: {res[0]['metadata'].get('n_groups')}"
    )
