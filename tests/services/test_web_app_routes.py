"""Web app.py 路由直测（Flask test client，覆盖评估报告 P2-5：app.py 57% 洼地）。

覆盖面：index / csrf-token / tasks 路由、CSRF 403 分支、上传全部分支
（无文件/无扩展名/坏扩展名/GBK 编码/垃圾字节/坏 zip/zip 炸弹/非 Excel zip/
列数超限/大文件内存警告/parquet 保存失败/旧文件替换/定期清理）、analyze
全部 400 校验分支、NO_DATA 任务正路径、数据过期 400、ValidationError 400、
意外异常 500、main() debug 安全绑定。

不覆盖（导入期/环境分支，单测不可达）：app.py:21-28 flask ImportError
退出分支、129-154 SECRET_KEY 文件/env 分支（模块导入时执行）、402-409
`__main__` argparse 守卫、275-278（xlsx >100k 行需巨型 fixture，CSV 路径
已在 test_upload_limits.py 覆盖同判据）。

注：审查 2026-09-19 E5 后 CSV 读取下沉至 `services.data_io.read_csv_with_encoding`，
原先「latin-1 恒可解码→df is None 不可达」已不成立：回退链不再含 latin-1，
「全部编码失败」分支由 `test_upload_csv_all_encodings_fail` 直接覆盖。
"""

import io
import logging
import os
import pathlib
import re
import sys
import time
import zipfile

import pandas as pd
import pytest

from smartsuite.services import config as config_module
from smartsuite.services.orchestrator import TASK_REGISTRY
from smartsuite.web import app as app_module
from smartsuite.web.app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


def _csrf(client):
    resp = client.get("/api/csrf-token")
    assert resp.status_code == 200
    return resp.get_json()["token"]


def _post_csv(client, content: bytes, filename: str = "data.csv", encoding: str | None = None):
    data: dict = {"file": (io.BytesIO(content), filename)}
    if encoding is not None:
        data["encoding"] = encoding
    return client.post(
        "/api/upload",
        data=data,
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": _csrf(client)},
    )


# ── 基础路由 ──


def test_index_route_renders(client):
    """GET / 渲染首页并为会话生成 CSRF token（app.py:186-193）。"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"SmartSuite" in resp.data
    # index 生成的 token 与 /api/csrf-token 返回一致（已有 token 不再重新生成）
    token = client.get("/api/csrf-token").get_json()["token"]
    assert token, "访问首页后应已有 CSRF token"


def test_api_tasks_lists_all_registered(client):
    """GET /api/tasks 返回注册表全量任务+标签+分组（app.py:378-382）。"""
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["tasks"]) == set(TASK_REGISTRY.keys())
    assert set(body["labels"]) == set(TASK_REGISTRY.keys())
    assert body["groups"], "分组不应为空"


def test_post_without_csrf_rejected_403(client):
    """无 CSRF 头的 POST 一律 403（app.py:113-125 安全分支）。"""
    resp = client.post("/api/analyze", json={"task": "anova"})
    assert resp.status_code == 403
    assert "CSRF" in resp.get_json()["error"]


# ── 上传分支 ──


def test_upload_no_file_400(client):
    """无 file 字段 → 400「请选择文件」（app.py:210-211）。"""
    resp = client.post(
        "/api/upload",
        data={},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert resp.status_code == 400
    assert "请选择文件" in resp.get_json()["error"]


def test_upload_no_extension_400(client):
    resp = _post_csv(client, b"a\n1\n", filename="datafile")
    assert resp.status_code == 400
    assert "无法识别文件类型" in resp.get_json()["error"]


def test_upload_bad_extension_400(client):
    resp = _post_csv(client, b"a\n1\n", filename="data.txt")
    assert resp.status_code == 400
    assert "不支持的文件格式" in resp.get_json()["error"]


def test_upload_csv_gbk_decoded(client):
    """GBK 中文表头 CSV：utf-8 解码失败后回退 gbk 成功（read_csv_with_encoding）。"""
    content = "强度,温度\n45.1,180\n46.3,182\n".encode("gbk")
    resp = _post_csv(client, content)
    assert resp.status_code == 200, resp.get_json()
    names = [c["name"] for c in resp.get_json()["columns"]]
    assert "强度" in names and "温度" in names


def test_upload_csv_garbage_parse_error_400(client):
    """字段数不一致的垃圾 CSV：utf-8 可解码但解析异常 → 400（CsvParseError）。"""
    resp = _post_csv(client, b"a,b\n1,2\n1,2,3\n")
    assert resp.status_code == 400
    assert "无法解析 CSV" in resp.get_json()["error"]


def test_upload_csv_utf16_bom_decoded(client):
    """UTF-16 BOM 中文 CSV：ADR-0004 后由「400 拒绝」改为正确解码。

    本用例 2026-09-21 由 test_upload_csv_utf16_rejected_not_garbled 反转而来；
    仍守住原意图——列名不得是 'ÿþyb!k' 这类乱码。
    """
    content = "强度,温度\n45.1,180\n46.3,182\n".encode("utf-16")
    resp = _post_csv(client, content)
    assert resp.status_code == 200, resp.get_json()
    names = [c["name"] for c in resp.get_json()["columns"]]
    assert names[:2] == ["强度", "温度"], f"UTF-16 应正确解码: {names[:2]}"


def test_upload_csv_explicit_big5_encoding(client):
    """encoding=big5：繁体表头正确返回（ADR-0004 决策 2）。"""
    content = "批號,溫度\nB2301,235\n".encode("big5")
    resp = _post_csv(client, content, encoding="big5")
    assert resp.status_code == 200, resp.get_json()
    names = [c["name"] for c in resp.get_json()["columns"]]
    assert names[:2] == ["批號", "溫度"]


def test_upload_csv_unsupported_encoding_400(client):
    """白名单外编码：400 + 中文错误（不透传 pandas 英文异常）。"""
    content = "批号,温度\nB1,235\n".encode("gbk")
    resp = _post_csv(client, content, encoding="latin-1")
    assert resp.status_code == 400
    assert "不支持的编码" in resp.get_json()["error"]


def test_frontend_encoding_options_within_backend_allowlist():
    """前端编码下拉框选项 ⊆ 后端白名单（ADR-0004 约束：白名单只定义一处）。"""
    from smartsuite.services.data_io import SUPPORTED_CSV_ENCODINGS

    html = (pathlib.Path(app_module.__file__).parent / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    block = re.search(r'<select id="encoding".*?</select>', html, re.S)
    assert block, "index.html 应存在 id=encoding 的下拉框"
    values = set(re.findall(r'<option value="([^"]*)"', block.group(0)))
    values.discard("")  # 空值 = 自动识别
    assert values <= set(SUPPORTED_CSV_ENCODINGS), f"前端出现后端不支持的编码: {values}"


def test_upload_excel_bad_zip_400(client):
    resp = _post_csv(client, b"this is not a zip", filename="data.xlsx")
    assert resp.status_code == 400
    assert "不是有效的 Excel" in resp.get_json()["error"]


def test_upload_excel_zip_bomb_400(client):
    """条目数 >1000 的 zip → 400「过多条目」（app.py:258-259）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(1001):
            zf.writestr(f"e{i}.xml", "x")
    resp = _post_csv(client, buf.getvalue(), filename="bomb.xlsx")
    assert resp.status_code == 400
    assert "过多条目" in resp.get_json()["error"]


def test_upload_excel_valid_zip_but_not_excel_400(client):
    """通过 zip 校验但 openpyxl 无法解析 → 400（app.py:263-267）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", "不是 Excel 内容")
    resp = _post_csv(client, buf.getvalue(), filename="fake.xlsx")
    assert resp.status_code == 400
    assert "无法解析 Excel" in resp.get_json()["error"]


def test_upload_excel_too_many_cols_400(client):
    """501 列 xlsx → 400 列数超限（app.py:279-282）。"""
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append([f"c{i}" for i in range(501)])
    ws.append(list(range(501)))
    buf = io.BytesIO()
    wb.save(buf)
    resp = _post_csv(client, buf.getvalue(), filename="wide.xlsx")
    assert resp.status_code == 400
    assert "超过限制" in resp.get_json()["error"]
    assert "列数" in resp.get_json()["error"]


def test_upload_large_file_logs_memory_warning(client, caplog):
    """>20MB 上传触发内存警告日志（app.py:285-287），数据本身合法。"""
    row = "1." + "2" * 208  # ≈210 字节/行 × 100k 行 ≈ 21MB > 20MiB
    buf = io.BytesIO()
    buf.write(b"v\n")
    for _ in range(100_000):
        buf.write(f"{row}\n".encode())
    with caplog.at_level(logging.WARNING, logger="smartsuite.web.app"):
        resp = _post_csv(client, buf.getvalue())
    assert resp.status_code == 200
    assert any("内存占用" in r.message for r in caplog.records)


def test_upload_parquet_save_failure_500(client, monkeypatch):
    """parquet 保存失败 → 500 中文兜底，不泄漏 traceback（app.py:295-301）。"""

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _boom)
    resp = _post_csv(client, b"a,b\n1,2\n")
    assert resp.status_code == 500
    assert "数据保存失败" in resp.get_json()["error"]


def test_upload_replaces_old_session_file(client):
    """二次上传：旧临时文件被删除，新文件落在专用目录内。"""
    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    with client.session_transaction() as sess:
        old_path = sess["_data_path"]
    assert os.path.exists(old_path)
    assert _post_csv(client, b"a,b\n3,4\n").status_code == 200
    with client.session_transaction() as sess:
        new_path = sess["_data_path"]
    assert new_path != old_path
    assert not os.path.exists(old_path), "旧上传文件应被删除"
    assert pathlib.Path(new_path).parent == app_module._upload_dir()


# ── D2：上传目录 + mtime TTL 扫描（无进程级注册表）──


def test_upload_lands_in_dedicated_dir(client):
    """D2：上传文件写入专用目录；进程级注册表已移除。"""
    assert not hasattr(app_module, "_UPLOAD_FILES"), "进程级注册表应已移除"
    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    with client.session_transaction() as sess:
        path = pathlib.Path(sess["_data_path"])
    assert path.parent == app_module._upload_dir(), "上传文件必须落在专用目录内"
    assert path.exists()


def test_sweep_expired_removes_stale_keeps_fresh():
    """D2：按 mtime 扫描——过期文件删除、未过期文件保留（不依赖任何注册表）。"""
    upload_dir = app_module._upload_dir()
    stale = upload_dir / "ss-stale.parquet"
    fresh = upload_dir / "ss-fresh.parquet"
    stale.write_bytes(b"x")
    fresh.write_bytes(b"x")
    old_t = time.time() - config_module.UPLOAD_TTL_SECONDS - 60
    os.utime(stale, (old_t, old_t))

    assert app_module._sweep_expired(force=True) == 1
    assert not stale.exists(), "过期文件应被删除"
    assert fresh.exists(), "未过期文件必须保留"


def test_cleanup_uploads_clears_upload_dir(client):
    """atexit 兜底：进程退出清空本目录全部临时文件（不再依赖注册表）。"""
    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    with client.session_transaction() as sess:
        path = sess["_data_path"]
    (app_module._upload_dir() / "ss-exit.parquet").write_bytes(b"x")

    app_module._cleanup_uploads()

    assert not os.path.exists(path)
    assert list(app_module._upload_dir().glob("*.parquet")) == []


def test_periodic_cleanup_sweeps_stale_via_request(client, monkeypatch):
    """D2：请求路径触发清理（节流由 CLEANUP_MIN_INTERVAL_SECONDS 控制）。"""
    monkeypatch.setattr(config_module, "CLEANUP_MIN_INTERVAL_SECONDS", 0)
    stale = app_module._upload_dir() / "ss-stale.parquet"
    stale.write_bytes(b"x")
    old_t = time.time() - config_module.UPLOAD_TTL_SECONDS - 60
    os.utime(stale, (old_t, old_t))

    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    assert not stale.exists(), "过期文件应由请求路径上的清理删除"


def test_sweep_expired_is_throttled(monkeypatch):
    """节流：距上次扫描不足下限时直接返回 0（避免每请求都做目录 I/O）。"""
    monkeypatch.setattr(config_module, "CLEANUP_MIN_INTERVAL_SECONDS", 3600)
    upload_dir = app_module._upload_dir()
    stale = upload_dir / "ss-throttled.parquet"
    old_t = time.time() - config_module.UPLOAD_TTL_SECONDS - 60
    stale.write_bytes(b"x")
    os.utime(stale, (old_t, old_t))

    app_module._sweep_expired(force=True)  # 建立时间戳（并清掉当前过期文件）
    stale.write_bytes(b"x")
    os.utime(stale, (old_t, old_t))

    assert app_module._sweep_expired() == 0, "节流窗口内不应扫描"
    assert stale.exists()


# ── analyze 校验分支 ──


def _analyze(client, **overrides):
    body = {"task": "anova", "targets": ["强度"], "features": ["温度"]}
    body.update(overrides)
    return client.post("/api/analyze", json=body, headers={"X-CSRF-Token": _csrf(client)})


def test_analyze_task_not_string_400(client):
    resp = _analyze(client, task=["anova"])
    assert resp.status_code == 400
    assert "task 必须是字符串" in resp.get_json()["error"]


def test_analyze_missing_task_400(client):
    resp = _analyze(client, task="")
    assert resp.status_code == 400
    assert "缺少分析任务" in resp.get_json()["error"]


def test_analyze_targets_not_list_400(client):
    resp = _analyze(client, targets="强度")
    assert resp.status_code == 400
    assert "targets 必须是字符串列表" in resp.get_json()["error"]


def test_analyze_features_not_list_400(client):
    resp = _analyze(client, features="温度")
    assert resp.status_code == 400
    assert "features 必须是字符串列表" in resp.get_json()["error"]


def test_analyze_categoricals_not_list_400(client):
    resp = _analyze(client, categoricals="工艺")
    assert resp.status_code == 400
    assert "categoricals 必须是字符串列表" in resp.get_json()["error"]


def test_analyze_params_not_dict_400(client):
    resp = _analyze(client, params=["x"])
    assert resp.status_code == 400
    assert "params 必须是字典" in resp.get_json()["error"]


def test_analyze_too_many_features_400(client):
    resp = _analyze(client, features=[f"f{i}" for i in range(101)])
    assert resp.status_code == 400
    assert "特征列数量" in resp.get_json()["error"]


def test_analyze_unknown_task_400(client):
    resp = _analyze(client, task="no_such_method")
    assert resp.status_code == 400
    assert "未知的分析任务" in resp.get_json()["error"]


def test_analyze_without_upload_400(client):
    resp = _analyze(client)
    assert resp.status_code == 400
    assert "请先上传数据文件" in resp.get_json()["error"]


def test_analyze_stale_data_file_400(client, monkeypatch):
    """读取时文件已消失（TOCTOU 窗口）→ 400 过期提示，非裸 500（app.py:362-366）。

    exists() 检查与 read_parquet 之间的竞态窗口无法确定性构造，
    以 read_parquet 抛 FileNotFoundError 模拟「检查后文件被清理」。"""

    def _vanished(path, *args, **kwargs):
        raise FileNotFoundError(path)

    monkeypatch.setattr(pd, "read_parquet", _vanished)
    assert _post_csv(client, "强度,温度\n45,180\n46,182\n".encode()).status_code == 200
    resp = _analyze(client)
    assert resp.status_code == 400
    assert "已过期" in resp.get_json()["error"]


def test_analyze_preprocess_error_returns_400(client):
    """特征列不存在（correlation 非 RAW_CAT 任务）→ api 层 ValidationError → 400（app.py:369-372）。"""
    assert _post_csv(client, "强度,温度\n45,180\n46,182\n".encode()).status_code == 200
    resp = _analyze(client, task="correlation", features=["不存在列"])
    assert resp.status_code == 400
    assert "数据预处理失败" in resp.get_json()["error"]


def test_analyze_unexpected_error_returns_500(client, monkeypatch):
    """非 ValidationError 的意外异常 → 500 通用中文兜底（app.py:373-375）。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("模拟意外崩溃")

    monkeypatch.setattr(app_module, "run_analysis", _boom)
    assert _post_csv(client, "强度,温度\n45,180\n46,182\n".encode()).status_code == 200
    resp = _analyze(client)
    assert resp.status_code == 500
    assert "分析处理失败" in resp.get_json()["error"]


def test_analyze_power_analysis_no_data_ok(client):
    """NO_DATA 任务（power_analysis）免上传直接分析 → 200（app.py:353-356, 367-368）。"""
    resp = client.post(
        "/api/analyze",
        json={"task": "power_analysis", "targets": [], "features": [], "params": {}},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert resp.status_code == 200, resp.get_json()
    results = resp.get_json()["results"]
    assert results and results[0]["status"] == "ok"
    assert results[0]["summary"], "power_analysis 应产出中文摘要"


# ── main() 启动入口 ──


def _silence_logging(monkeypatch):
    import smartsuite as pkg

    monkeypatch.setattr(pkg, "setup_logging", lambda: None)


def test_main_debug_forces_localhost_binding(monkeypatch, capsys):
    """debug+非本机 → 强制绑定 127.0.0.1 + 双重警告（app.py:385-395）。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw), raising=False)
    app_module.main(host="0.0.0.0", port=9999, debug=True)
    out = capsys.readouterr().out
    assert calls["host"] == "127.0.0.1", "debug 模式必须强制本机绑定"
    assert calls["port"] == 9999 and calls["debug"] is True
    assert "已强制绑定 127.0.0.1" in out
    assert "请勿在公网环境使用" in out


def test_main_default_runs_localhost(monkeypatch, capsys):
    """默认参数：host/port/debug 原样传递（app.py:394-398）。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw))
    app_module.main()
    assert calls == {"host": "127.0.0.1", "port": 5050, "debug": False}


# ── smartsuite-web 控制台入口（审查 2026-09-19 E14a）──


def test_console_script_entry_is_registered_and_callable():
    """pyproject 的 smartsuite-web 入口必须指向可导入的可调用对象（防注册漂移）。"""
    import importlib
    import re
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    # 用正则而非 tomllib：tomllib 仅 3.11+，而 requires-python >= 3.10
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^smartsuite-web\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml 缺少 smartsuite-web 控制台入口"
    module_path, _, attr = match.group(1).partition(":")
    assert attr, f"入口目标须为 module:callable 形式: {match.group(1)}"
    assert callable(getattr(importlib.import_module(module_path), attr))


def test_cli_help_is_chinese_and_exits_zero(capsys):
    """`smartsuite-web --help` 输出中文帮助并 exit 0。"""
    with pytest.raises(SystemExit) as ei:
        app_module.cli(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "监听地址" in out and "监听端口" in out, f"帮助应含中文参数说明: {out[:200]}"


def test_cli_passes_host_and_port(monkeypatch):
    """--host/--port 透传到 app.run。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw))
    assert app_module.cli(["--host", "0.0.0.0", "--port", "9999"]) == 0
    assert calls == {"host": "0.0.0.0", "port": 9999, "debug": False}


def test_cli_port_zero_is_not_swallowed(monkeypatch):
    """--port 0 是 Flask 合法值（随机端口），不得被 `or` 当成假值吞掉。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw))
    app_module.cli(["--port", "0"])
    assert calls["port"] == 0, f"--port 0 应原样传递: {calls}"


def test_cli_debug_flag_and_env(monkeypatch, capsys):
    """--debug 与 SMARTSUITE_DEBUG=1 都能开启 debug；两者共存不报错。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw))

    app_module.cli(["--host", "127.0.0.1", "--debug"])
    assert calls["debug"] is True

    monkeypatch.setenv("SMARTSUITE_DEBUG", "1")
    app_module.cli([])
    assert calls["debug"] is True, "环境变量 SMARTSUITE_DEBUG=1 应开启 debug"

    monkeypatch.setenv("SMARTSUITE_DEBUG", "0")
    app_module.cli([])
    assert calls["debug"] is False


def test_cli_debug_forces_localhost(monkeypatch, capsys):
    """经 cli 入口传 --debug + 非本机地址 → 仍强制绑定 127.0.0.1。"""
    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr(flask_app, "run", lambda **kw: calls.update(kw))
    app_module.cli(["--host", "0.0.0.0", "--debug"])
    assert calls["host"] == "127.0.0.1", "debug 模式必须强制本机绑定"


def test_run_server_delegates_to_cli():
    """run_server.py 不得再自行调用 main()（消除第三份启动代码）。"""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "run_server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "smartsuite.web.app"
        for alias in node.names
    }
    assert "cli" in imported, f"run_server.py 应从 smartsuite.web.app 导入 cli: {imported}"
    assert "main" not in imported, "run_server.py 不应再直接导入 main"


# ── 清理链 OSError 防御分支 ──


def test_cleanup_uploads_survives_unlink_oserror(client, monkeypatch):
    """unlink 失败（文件被占用等）→ 跳过该文件，不中断清理。"""
    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    with client.session_transaction() as sess:
        path = sess["_data_path"]

    def _busy(self, *args, **kwargs):
        raise OSError("文件被占用")

    monkeypatch.setattr(pathlib.Path, "unlink", _busy)
    app_module._cleanup_uploads()  # 不应抛异常
    assert os.path.exists(path)


def test_sweep_expired_survives_stat_oserror(monkeypatch):
    """mtime 读取失败 → 跳过该文件继续清理（防御分支不抛异常）。"""
    broken = app_module._upload_dir() / "ss-broken.parquet"
    broken.write_bytes(b"x")
    real_stat = pathlib.Path.stat

    def _boom(self, **kwargs):
        if self.suffix == ".parquet":
            raise OSError("stat 失败")
        return real_stat(self, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", _boom)
    assert app_module._sweep_expired(force=True) == 0
    assert broken in list(app_module._upload_dir().glob("*.parquet"))


# ── 上传解析防御分支 ──


def test_upload_csv_all_encodings_fail(client, monkeypatch):
    """全部编码均解码失败 → 「无法识别 CSV 文件编码」（CsvEncodingError → 400）。"""

    def _undecodable(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")

    monkeypatch.setattr(pd, "read_csv", _undecodable)
    resp = _post_csv(client, b"a,b\n1,2\n")
    assert resp.status_code == 400
    assert "无法识别 CSV 文件编码" in resp.get_json()["error"]


def test_upload_excel_zip_oversize_rejected(client):
    """zip 解压后总量 >200MB → 400（app.py:254-257 防炸弹；高压缩比数据即可触发）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(110):
            zf.writestr(f"e{i}.bin", b"0" * (2 * 1024 * 1024))  # 声明大小 220MB
    resp = _post_csv(client, buf.getvalue(), filename="big.xlsx")
    assert resp.status_code == 400
    assert "解压后过大" in resp.get_json()["error"]


def test_upload_excel_over_max_rows_rejected(client):
    """xlsx 100_001 行 → 400 行数超限（app.py:275-278；CSV 路径由 test_upload_limits 覆盖）。"""
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet()
    # +2：pandas read_excel 默认首行作表头（100_002 行 → 100_001 数据行）
    for i in range(100_002):
        ws.append([float(i)])
    buf = io.BytesIO()
    wb.save(buf)
    resp = _post_csv(client, buf.getvalue(), filename="long.xlsx")
    assert resp.status_code == 400
    assert "超过限制" in resp.get_json()["error"]


def test_upload_parquet_failure_cleans_tmp_without_crash(client, monkeypatch):
    """parquet 保存失败且临时文件删除也失败 → 双重兜底后 500（app.py:295-301）。"""

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    def _busy(path, *args, **kwargs):
        raise OSError("占用")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _boom)
    monkeypatch.setattr(os, "unlink", _busy)
    resp = _post_csv(client, b"a,b\n1,2\n")
    assert resp.status_code == 500


def test_upload_old_file_unlink_failure_keeps_new_upload(client, monkeypatch):
    """旧文件删除失败 → 跳过但新上传仍成功（app.py:306-312）。"""
    assert _post_csv(client, b"a,b\n1,2\n").status_code == 200
    with client.session_transaction() as sess:
        old_path = sess["_data_path"]

    real_unlink = os.unlink

    def _busy_first(path, *args, **kwargs):
        if path == old_path:
            raise OSError("旧文件被占用")
        return real_unlink(path)

    monkeypatch.setattr(os, "unlink", _busy_first)
    resp = _post_csv(client, b"a,b\n3,4\n")
    assert resp.status_code == 200, "旧文件删除失败不得影响新上传"
    assert os.path.exists(old_path), "被占用的旧文件保留（防御分支）"


# ── 模块入口与导入期分支（reload 舞蹈，置于文件末尾防状态扩散）──


def test_module_main_entrypoint(monkeypatch):
    """`python app.py` 入口：argparse 解析 → main() 传参（app.py:401-415）。"""
    import pathlib
    import runpy

    _silence_logging(monkeypatch)
    calls = {}
    monkeypatch.setattr("flask.Flask.run", lambda self, **kw: calls.update(kw))
    monkeypatch.setattr(sys, "argv", ["app.py", "--port", "5059"])
    runpy.run_path(str(pathlib.Path(app_module.__file__)), run_name="__main__")
    assert calls["port"] == 5059
    assert calls["host"] == "127.0.0.1"
    assert calls["debug"] is False


def test_secret_key_bootstrap_branches(monkeypatch, tmp_path, caplog):
    """SECRET_KEY 引导四分支：env 直用 / 文件读取 / 空文件重建 / 新建 + chmod 失败兜底。

    app.py:129-154 为导入期代码，通过带环境补丁的 importlib.reload 逐分支执行。
    reload 原地重执行模块对象（其他测试模块持有的引用不受影响），测试末尾
    无补丁 reload 恢复正常状态。
    """
    import importlib

    secret_file = tmp_path / ".smartsuite" / "secret_key"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # 分支1：env 变量直用（130-131）
    monkeypatch.setenv("SMARTSUITE_SECRET", "env-secret-abc")
    importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"] == "env-secret-abc"
    monkeypatch.delenv("SMARTSUITE_SECRET")

    # 分支2：文件存在且有内容 → 读用（136-138, 141）
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text("file-key-123", encoding="utf-8")
    importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"] == "file-key-123"

    # 分支3：文件存在但为空 → 重建写入（138-140）
    secret_file.write_text("", encoding="utf-8")
    importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"], "空文件应重建密钥"
    assert secret_file.read_text(encoding="utf-8") == app_module.app.config["SECRET_KEY"]

    # 分支4：文件不存在 → 新建（142-145）
    secret_file.unlink()
    importlib.reload(app_module)
    assert secret_file.exists(), "应持久化新密钥"
    assert app_module.app.config["SECRET_KEY"] == secret_file.read_text(encoding="utf-8")

    # 分支5：chmod 失败 → 忽略权限设置，密钥仍生效（147-150）
    monkeypatch.setattr(os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("no chown")))
    importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"]
    monkeypatch.undo()

    # 恢复：无补丁状态重载，回读真实密钥文件
    importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"]


def test_secret_key_home_unwritable_falls_back(monkeypatch, tmp_path, caplog):
    """home 不可写（mkdir 失败）→ 临时密钥 + 警告日志（app.py:151-154）。"""
    import importlib

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file")
    monkeypatch.setattr("pathlib.Path.home", lambda: blocker)
    with caplog.at_level(logging.WARNING, logger="smartsuite.web.app"):
        importlib.reload(app_module)
    assert app_module.app.config["SECRET_KEY"], "mkdir 失败应回退临时密钥"
    assert any("无法持久化密钥" in r.message for r in caplog.records)
    monkeypatch.undo()
    importlib.reload(app_module)  # 恢复


def test_flask_import_error_prints_guidance_and_exits(monkeypatch, capsys):
    """无 Flask 环境 → 中文安装引导 + exit(1)（app.py:19-28）。"""
    import importlib

    monkeypatch.setitem(sys.modules, "flask", None)  # import 即触发 ImportError
    with pytest.raises(SystemExit) as ei:
        importlib.reload(app_module)
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "需要 Flask" in out and "pip install smartsuite[web]" in out
    monkeypatch.undo()
    importlib.reload(app_module)  # 恢复正常模块状态
