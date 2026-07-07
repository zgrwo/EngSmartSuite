"""Flask application — SmartSuite Web UI 入口。"""
import atexit
import functools
import logging
import os
import pathlib
import secrets
import sys
import tempfile
import threading

import pandas as pd

# ── matplotlib 配置由引擎层统一管理（含中文字体 + 配色方案）──
# orchestrator 导入会级联触发 engine/__init__.py 中的全局 matplotlib 配置

try:
    from flask import Flask, jsonify, render_template, request, session
except ImportError:
    print("=" * 60)
    print("  ❌ SmartSuite Web UI 需要 Flask，但未安装。")
    print()
    print("  请运行：pip install smartsuite[web]")
    print("  或单独安装：pip install flask pyarrow")
    print("=" * 60)
    sys.exit(1)

from smartsuite.services.orchestrator import GROUP_COLORS, TASK_GROUPS, TASK_LABELS, TASK_REGISTRY
from smartsuite.web.api import column_info, run_analysis

logger = logging.getLogger(__name__)

# 上传文件的临时追踪，确保进程退出时清理
_UPLOAD_FILES: list[str] = []
_upload_lock = threading.Lock()


def _cleanup_uploads() -> None:
    with _upload_lock:
        paths = list(_UPLOAD_FILES)
    for path in paths:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_uploads)

# ── 定期清理过期临时文件（每 N 次请求触发一次）──
_request_counter = 0
_CLEANUP_INTERVAL = 50  # 每 50 次上传/分析请求尝试清理


def _periodic_cleanup() -> None:
    """清理不存在对应 session 的过期临时文件。"""
    global _request_counter
    with _upload_lock:
        _request_counter += 1
        if _request_counter % _CLEANUP_INTERVAL != 0:
            return
        for path in list(_UPLOAD_FILES):
            try:
                # 检查文件最后修改时间，超过 24h 的清理
                if os.path.exists(path):
                    mtime = os.path.getmtime(path)
                    import time as _time
                    if _time.time() - mtime > 86400:  # 24 hours
                        os.unlink(path)
                        _UPLOAD_FILES.remove(path)
                else:
                    _UPLOAD_FILES.remove(path)
            except OSError:
                pass

# ── CSRF 防护 ──
_CSRF_TOKEN_KEY = "_csrf_token"


def _generate_csrf_token() -> str:
    token = secrets.token_hex(32)
    session[_CSRF_TOKEN_KEY] = token
    return token


def require_csrf(f):
    """CSRF 校验装饰器：POST 端点需携带 X-CSRF-Token 头匹配 session token。"""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            client_token = request.headers.get("X-CSRF-Token", "")
            server_token = session.get(_CSRF_TOKEN_KEY, "")
            if not client_token or not secrets.compare_digest(client_token, server_token):
                return jsonify({"error": "CSRF 校验失败，请刷新页面后重试"}), 403
        return f(*args, **kwargs)

    return wrapper


app = Flask(__name__)
_secret_from_env = os.environ.get("SMARTSUITE_SECRET")
if _secret_from_env:
    app.config["SECRET_KEY"] = _secret_from_env
else:
    _secret_file = pathlib.Path.home() / ".smartsuite" / "secret_key"
    try:
        _secret_file.parent.mkdir(parents=True, exist_ok=True)
        if _secret_file.exists():
            _key = _secret_file.read_text().strip()
            if not _key:
                _key = secrets.token_hex(32)
                _secret_file.write_text(_key)
            app.config["SECRET_KEY"] = _key
        else:
            _fallback_key = secrets.token_hex(32)
            _secret_file.write_text(_fallback_key)
            app.config["SECRET_KEY"] = _fallback_key
        # 限制密钥文件权限（仅 owner 可读写）
        try:
            os.chmod(_secret_file, 0o600)
        except OSError:
            pass
    except OSError:
        _fallback_key = secrets.token_hex(32)
        app.config["SECRET_KEY"] = _fallback_key
        logger.warning("无法持久化密钥到 %s，使用临时密钥", _secret_file)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
# Session 安全配置
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1 小时后过期，限制 CSRF token 重用窗口


@app.route("/")
def index():
    # 为每个页面访问生成 CSRF token
    if _CSRF_TOKEN_KEY not in session:
        _generate_csrf_token()
    return render_template("index.html",
        task_labels=TASK_LABELS,
        task_groups=TASK_GROUPS,
        group_colors=GROUP_COLORS)


@app.route("/api/csrf-token")
def csrf_token():
    """前端获取 CSRF token。"""
    token = session.get(_CSRF_TOKEN_KEY)
    if not token:
        token = _generate_csrf_token()
    return jsonify({"token": token})


@app.route("/api/upload", methods=["POST"])
@require_csrf
def upload():
    _periodic_cleanup()
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "请选择文件"}), 400

    # 服务端文件类型校验
    filename = f.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".xlsx", ".xls", ".xlsm"):
        return jsonify({"error": f"不支持的文件格式「{ext}」，请上传 .xlsx / .xls 文件"}), 400

    # Zip bomb 防护：仅对 ZIP 格式的 Excel (.xlsx/.xlsm) 检查解压后大小
    # .xls 是 OLE2 二进制格式，不是 ZIP，跳过此项检查
    import io
    import zipfile
    f_bytes = f.read()
    if ext in (".xlsx", ".xlsm"):
        try:
            with zipfile.ZipFile(io.BytesIO(f_bytes)) as zf:
                total_size = sum(info.file_size for info in zf.infolist())
                if total_size > 200 * 1024 * 1024:
                    return jsonify({"error": "文件解压后过大（限制200MB），请减少数据量"}), 400
                if len(zf.infolist()) > 1000:
                    return jsonify({"error": "文件包含过多条目，可能不是有效的 Excel 文件"}), 400
        except zipfile.BadZipFile:
            return jsonify({"error": "不是有效的 Excel 文件，请确认文件格式正确"}), 400

    try:
        df = pd.read_excel(io.BytesIO(f_bytes))
    except Exception:
        logger.exception("Excel 文件解析失败")
        return jsonify({"error": "无法解析 Excel 文件，请确认文件格式正确"}), 400

    if df.empty:
        return jsonify({"error": "文件为空或无法读取数据"}), 400

    # ── 大数据防护：限制行数和列数，防止 OOM ──
    max_rows = 100_000
    max_cols = 500
    if df.shape[0] > max_rows:
        return jsonify({"error": f"数据行数 ({df.shape[0]}) 超过限制 ({max_rows}行)，请减少数据量"}), 400
    if df.shape[1] > max_cols:
        return jsonify({"error": f"数据列数 ({df.shape[1]}) 超过限制 ({max_cols}列)，请减少列数"}), 400

    # 大文件内存警告（当前实现将整个文件读入内存）
    _mem_mb = len(f_bytes) / (1024 * 1024)
    if _mem_mb > 20:
        logger.warning("上传文件较大 (%.0f MB)，内存占用可能较高", _mem_mb)

    # 先写新文件再清理旧文件（避免写失败时丢失已有数据）
    with _upload_lock:
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()
        try:
            df.to_parquet(tmp.name)
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return jsonify({"error": "数据保存失败，请重试"}), 500
        # 新文件写入成功，更新 session 并清理旧文件
        old_path = session.get("_data_path")
        session["_data_path"] = tmp.name
        _UPLOAD_FILES.append(tmp.name)
        if old_path and os.path.exists(old_path):
            try:
                os.unlink(old_path)
                if old_path in _UPLOAD_FILES:
                    _UPLOAD_FILES.remove(old_path)
            except OSError:
                pass
    return jsonify({"columns": column_info(df), "shape": list(df.shape)})


@app.route("/api/analyze", methods=["POST"])
@require_csrf
def analyze():
    _periodic_cleanup()
    try:
        body = request.get_json()
        task = body.get("task")
        targets = body.get("targets", [])
        features = body.get("features", [])
        categoricals = body.get("categoricals", [])
        params = body.get("params", {})
        if not task or not targets:
            return jsonify({"error": "缺少分析任务或目标列"}), 400
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            return jsonify({"error": "targets 必须是字符串列表"}), 400
        if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
            return jsonify({"error": "features 必须是字符串列表"}), 400
        if not isinstance(params, dict):
            return jsonify({"error": "params 必须是字典"}), 400
        if task not in TASK_REGISTRY:
            return jsonify({"error": f"未知的分析任务「{task}」，支持: {list(TASK_REGISTRY.keys())}"}), 400
        path = session.get("_data_path")
        if not path or not os.path.exists(path):
            return jsonify({"error": "请先上传数据文件"}), 400
        df = pd.read_parquet(path)
        results = run_analysis(task, df, targets, features, categoricals, params)
        return jsonify({"results": results})
    except Exception as e:
        logger.exception("分析请求处理失败: %s", str(e)[:200])
        return jsonify({"error": "分析处理失败，请检查数据格式后重试"}), 500


@app.route("/api/tasks")
def list_tasks():
    return jsonify({"tasks": list(TASK_REGISTRY.keys()),
                    "labels": TASK_LABELS, "groups": TASK_GROUPS})


def main(host="127.0.0.1", port=5050, debug=False):
    if debug and host != "127.0.0.1":
        print("⚠️  警告: debug 模式仅在 localhost 下安全，已强制绑定 127.0.0.1")
        host = "127.0.0.1"
    if debug:
        print("⚠️  警告: debug 模式启用了 Werkzeug 交互调试器，请勿在公网环境使用！")
    logger.info("SmartSuite Web UI 启动: http://%s:%s", host, port)
    print(f"\n  SmartSuite Web UI\n  地址: http://{host}:{port}\n  按 Ctrl+C 停止\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    debug = os.environ.get("SMARTSUITE_DEBUG", "0") == "1"
    main(debug=debug)
