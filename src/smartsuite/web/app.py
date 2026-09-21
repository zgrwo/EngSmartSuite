"""Flask application — SmartSuite Web UI 入口。"""

import atexit
import contextlib
import functools
import logging
import os
import pathlib
import secrets
import sys
import tempfile
import time as _time

import pandas as pd

# ── matplotlib 配置由引擎层统一管理（后端 Agg + 中文字体 + 配色方案）──
# 下方 services 导入会级联触发 engine/__init__.py 中的全局配置；因此 web/ 下任何
# 模块都**不得**再自设后端或在模块级导入 pyplot（见 B3 守卫
# tests/guards/test_matplotlib_backend_order.py）

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

from smartsuite.core.constants import GROUP_COLORS
from smartsuite.core.exceptions import CsvEncodingError, ValidationError
from smartsuite.services import config
from smartsuite.services.data_io import read_csv_with_encoding
from smartsuite.services.orchestrator import (
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    TASK_GROUPS,
    TASK_LABELS,
    TASK_REGISTRY,
)
from smartsuite.web.api import column_info, run_analysis

logger = logging.getLogger(__name__)

# ── 上传临时文件：专用目录 + mtime TTL 扫描（审查 2026-09-21 D2）──
# 原实现用进程级注册表（_UPLOAD_FILES / _upload_lock / _request_counter）追踪临时文件：
# 多 worker 下各进程只看得见自己创建的文件，别人的过期文件无人清理（泄漏），且
# 「清理间隔」是按本进程请求数计数的。改为状态落在文件系统上：任何 worker 都能扫全量。
_last_sweep_at = 0.0

# 单次分析的目标列/特征列数量上限见 services/config.py（审查 2026-09-19 B7 集中）


def _upload_dir() -> pathlib.Path:
    """上传数据专用目录（按需创建）；`SMARTSUITE_UPLOAD_DIR` 可覆盖（测试/运维）。"""
    override = os.environ.get(config.UPLOAD_DIR_ENV)
    directory = (
        pathlib.Path(override)
        if override
        else pathlib.Path(tempfile.gettempdir()) / config.UPLOAD_DIR_NAME
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _is_own_upload(path: pathlib.Path) -> bool:
    """是否为本应用创建的上传临时文件（命名单一来源，审查 R1-2）。

    上传文件一律由 `NamedTemporaryFile(prefix="ss-", suffix=".parquet")` 创建
    （见 `/api/upload`），故 `ss-*.parquet` 即本应用所有物。按前缀收窄清理范围后，
    即使运维把 `SMARTSUITE_UPLOAD_DIR` 指向共享目录，也不会误删他人在同目录内的
    parquet（原先按 `*.parquet` 全量匹配，实测会删除无关文件）。
    """
    return path.name.startswith("ss-") and path.suffix == ".parquet"


def _sweep_expired(*, force: bool = False) -> int:
    """删除本目录内 mtime 超过 TTL 的**本应用** parquet，返回删除数。

    默认按 `CLEANUP_MIN_INTERVAL_SECONDS` 节流（避免每个请求都做目录 I/O）；
    `force=True` 跳过节流（测试与显式清理入口用）。
    """
    global _last_sweep_at
    now = _time.time()
    if not force and now - _last_sweep_at < config.CLEANUP_MIN_INTERVAL_SECONDS:
        return 0
    _last_sweep_at = now
    removed = 0
    for path in _upload_dir().glob("*.parquet"):
        if not _is_own_upload(path):
            continue
        try:
            if now - path.stat().st_mtime > config.UPLOAD_TTL_SECONDS:
                path.unlink()
                removed += 1
        except OSError:
            logger.debug("过期上传文件清理失败: %s", path, exc_info=True)
    return removed


def _cleanup_uploads() -> None:
    """进程退出兜底：删除本目录内**本应用**的全部临时 parquet。

    会话数据本身是无状态的 parquet，进程退出后不再有任何引用，故无需区分
    「哪个会话的」；但仍需区分「哪个应用的」——`SMARTSUITE_UPLOAD_DIR`
    可被运维指向共享位置，此时不得删掉他人文件（审查 R1-2）。
    """
    for path in _upload_dir().glob("*.parquet"):
        if not _is_own_upload(path):
            continue
        try:
            path.unlink()
        except OSError:
            logger.debug("退出清理临时文件失败: %s", path, exc_info=True)


atexit.register(_cleanup_uploads)


def _periodic_cleanup() -> None:
    """请求路径上的过期清理（节流由 `_sweep_expired` 承担）。"""
    _sweep_expired()


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
        # 限制密钥文件权限（仅 owner 可读写）；chmod 失败（如 Windows/只读卷）不阻断启动
        with contextlib.suppress(OSError):
            os.chmod(_secret_file, 0o600)
    except OSError:
        _fallback_key = secrets.token_hex(32)
        app.config["SECRET_KEY"] = _fallback_key
        logger.warning("无法持久化密钥到 %s，使用临时密钥", _secret_file)
app.config["MAX_CONTENT_LENGTH"] = config.UPLOAD_MAX_BYTES
# Session 安全配置
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# 审查 2026-09-01 S-3：本地 HTTP 默认 False；公网 HTTPS 部署可设环境变量开启
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SMARTSUITE_COOKIE_SECURE") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = (
    config.SESSION_LIFETIME_SECONDS
)  # 1 小时；限制 CSRF token 重用窗口


@app.after_request
def _security_headers(resp):
    """Round-2 P3：CSP 纵深防御（模板含内联 style/onclick → 需 unsafe-inline）。"""
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.before_request
def _make_session_permanent():
    """配合 PERMANENT_SESSION_LIFETIME：使会话 cookie 具有固定过期时间。

    审查 2026-08-19 Round-2：未设置 permanent 时 PERMANENT_SESSION_LIFETIME 不生效。
    """
    session.permanent = True


@app.route("/")
def index():
    # 为每个页面访问生成 CSRF token
    if _CSRF_TOKEN_KEY not in session:
        _generate_csrf_token()
    return render_template(
        "index.html", task_labels=TASK_LABELS, task_groups=TASK_GROUPS, group_colors=GROUP_COLORS
    )


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

    # 服务端文件类型校验 (.xls 是 OLE2 二进制格式, openpyxl 不支持, 已移除)
    filename = f.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        return jsonify(
            {"error": "无法识别文件类型（无扩展名），请上传 .xlsx / .xlsm / .csv 文件"}
        ), 400
    if ext not in (".xlsx", ".xlsm", ".csv"):
        return jsonify(
            {"error": f"不支持的文件格式「{ext}」，请上传 .xlsx / .xlsm / .csv 文件"}
        ), 400

    import io
    import zipfile

    f_bytes = f.read()

    if ext == ".csv":
        # CSV 文件：多编码尝试（UTF-8 BOM → UTF-8 → GBK）。审查 2026-09-19 E5：
        # 移除 latin-1 兜底——latin-1 对任意字节序列恒可解码，会把 UTF-16/Big5
        # 中文表头静默读成乱码（'ÿþyb!k'），用户据此得到错误的 Cp/Cpk 结论。
        # ADR-0004：BOM（UTF-8/16/32）确定性判定；表单可选 encoding 字段供用户
        # 显式声明编码（繁体 Big5 等），空串/缺省 = 自动。
        try:
            # Round-2 P3：先探测行数（只读 max_rows+1 行），超限直接拒绝，
            # 避免 49MB CSV 全量解析产生数百 MB 内存峰值后被拒。
            # 审查 #P2：探测 nrows=100_001 未超限 ⟺ 文件行数 ≤ 100_000，
            # probe 已是完整数据——直接复用，避免同一文件全量重读两次。
            df = read_csv_with_encoding(
                io.BytesIO(f_bytes),
                nrows=config.CSV_PROBE_ROWS,
                encoding=(request.form.get("encoding") or "").strip() or None,
            )
        except CsvEncodingError as e:
            return jsonify({"error": str(e)}), 400
        except Exception:
            # CsvParseError（结构非法/空文件）与其余意外解析异常统一为中文 400，
            # 与改造前行为一致；traceback 只进日志，不曝给用户
            logger.exception("CSV 文件解析失败")
            return jsonify({"error": "无法解析 CSV 文件，请确认文件格式正确"}), 400
        if len(df) > config.MAX_DATA_ROWS:
            return jsonify({"error": "数据行数超过限制 (100000行)，请减少数据量"}), 400
    else:
        # Excel 文件：Zip bomb 防护
        try:
            with zipfile.ZipFile(io.BytesIO(f_bytes)) as zf:
                total_size = sum(info.file_size for info in zf.infolist())
                if total_size > config.MAX_ZIP_UNCOMPRESSED_BYTES:
                    return jsonify({"error": "文件解压后过大（限制200MB），请减少数据量"}), 400
                if len(zf.infolist()) > config.MAX_ZIP_ENTRIES:
                    return jsonify({"error": "文件包含过多条目，可能不是有效的 Excel 文件"}), 400
        except zipfile.BadZipFile:
            return jsonify({"error": "不是有效的 Excel 文件，请确认文件格式正确"}), 400

        try:
            df = pd.read_excel(io.BytesIO(f_bytes), engine="openpyxl")
        except Exception:
            logger.exception("Excel 文件解析失败")
            return jsonify({"error": "无法解析 Excel 文件，请确认文件格式正确"}), 400

    if df.empty:
        return jsonify({"error": "文件为空或无法读取数据"}), 400

    # ── 大数据防护：限制行数和列数，防止 OOM ──
    max_rows = config.MAX_DATA_ROWS
    max_cols = config.MAX_DATA_COLS
    if df.shape[0] > max_rows:
        return jsonify(
            {"error": f"数据行数 ({df.shape[0]}) 超过限制 ({max_rows}行)，请减少数据量"}
        ), 400
    if df.shape[1] > max_cols:
        return jsonify(
            {"error": f"数据列数 ({df.shape[1]}) 超过限制 ({max_cols}列)，请减少列数"}
        ), 400

    # 大文件内存警告（当前实现将整个文件读入内存）
    _mem_mb = len(f_bytes) / (1024 * 1024)
    if len(f_bytes) > config.LARGE_FILE_WARN_BYTES:
        logger.warning("上传文件较大 (%.0f MB)，内存占用可能较高", _mem_mb)

    # 先写新文件再清理旧文件（避免写失败时丢失已有数据）
    tmp = tempfile.NamedTemporaryFile(
        dir=_upload_dir(), prefix="ss-", suffix=".parquet", delete=False
    )
    tmp.close()
    try:
        df.to_parquet(tmp.name)
    except Exception as exc:
        logger.error("上传数据 parquet 保存失败: %s (%s)", tmp.name, exc, exc_info=True)
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
        return jsonify({"error": "数据保存失败，请重试"}), 500
    # 新文件写入成功，更新 session 并清理上一份（本 session 自己的旧文件）
    old_path = session.get("_data_path")
    session["_data_path"] = tmp.name
    if old_path and old_path != tmp.name and os.path.exists(old_path):
        with contextlib.suppress(OSError):
            os.unlink(old_path)
    return jsonify({"columns": column_info(df), "shape": list(df.shape)})


@app.route("/api/analyze", methods=["POST"])
@require_csrf
def analyze():
    _periodic_cleanup()
    try:
        # 审查 2026-08-19 Round-2：silent=True 使非法/缺失 JSON 返回 None → 400 中文
        body = request.get_json(silent=True)
        if body is None:
            return jsonify({"error": "请求体必须是合法 JSON 对象"}), 400
        task = body.get("task")
        targets = body.get("targets", [])
        features = body.get("features", [])
        categoricals = body.get("categoricals", [])
        params = body.get("params", {})
        # 审查 2026-09-01 S-1：task 缺少类型检查 → unhashable 输入（如数组）
        # 在 `task not in TASK_REGISTRY` 处抛 TypeError → 500，应返回 400
        if not isinstance(task, str):
            return jsonify({"error": "task 必须是字符串"}), 400
        if not task or (not targets and task not in NO_TARGET_TASKS):
            return jsonify({"error": "缺少分析任务或目标列"}), 400
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            return jsonify({"error": "targets 必须是字符串列表"}), 400
        if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
            return jsonify({"error": "features 必须是字符串列表"}), 400
        if not isinstance(categoricals, list) or not all(isinstance(c, str) for c in categoricals):
            return jsonify({"error": "categoricals 必须是字符串列表"}), 400
        if not isinstance(params, dict):
            return jsonify({"error": "params 必须是字典"}), 400
        # 审查 2026-09-01 S-4：目标列/特征列数量上限 → 400
        if len(targets) > config.MAX_TARGETS:
            return jsonify({"error": f"目标列数量不能超过 {config.MAX_TARGETS}"}), 400
        if len(features) > config.MAX_FEATURES:
            return jsonify({"error": f"特征列数量不能超过 {config.MAX_FEATURES}"}), 400
        if task not in TASK_REGISTRY:
            return jsonify(
                {"error": f"未知的分析任务「{task}」，支持: {list(TASK_REGISTRY.keys())}"}
            ), 400
        # 完全无需数据的任务（纯参数计算）跳过数据文件检查，传入空 DataFrame
        path = session.get("_data_path")
        if task in NO_DATA_TASKS:
            df = pd.DataFrame()
        elif not path or not os.path.exists(path):
            return jsonify({"error": "请先上传数据文件"}), 400
        else:
            # 审查 2026-09-01 S-2：清理线程与读取存在 TOCTOU 窗口，
            # 文件可能在 exists() 后被删除 → FileNotFoundError 专项 400（非裸 500）
            try:
                df = pd.read_parquet(path)
            except FileNotFoundError:
                logger.warning("上传数据文件已被清理，请重新上传: %s", path)
                return jsonify({"error": "上传的数据文件已过期，请重新上传"}), 400
        results = run_analysis(task, df, targets, features, categoricals, params)
        return jsonify({"results": results})
    except ValidationError as e:
        # 审查 2026-08-19 Round-2：数据预处理失败（One-Hot 冲突/缺列）→ 400 中文
        logger.warning("分析请求校验失败: %s", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("分析请求处理失败: %s", str(e)[:200])
        return jsonify({"error": "分析处理失败，请检查数据格式后重试"}), 500


@app.route("/api/tasks")
def list_tasks():
    return jsonify(
        {"tasks": list(TASK_REGISTRY.keys()), "labels": TASK_LABELS, "groups": TASK_GROUPS}
    )


def main(host="127.0.0.1", port=5050, debug=False):
    # 日志配置：文件 DEBUG 全量，控制台 INFO
    from smartsuite import setup_logging

    setup_logging()

    if debug and host != "127.0.0.1":
        print("⚠️  警告: debug 模式仅在 localhost 下安全，已强制绑定 127.0.0.1")
        host = "127.0.0.1"
    if debug:
        print("⚠️  警告: debug 模式启用了 Werkzeug 交互调试器，请勿在公网环境使用！")
    logger.info("SmartSuite Web UI 启动: http://%s:%s", host, port)
    print(f"\n  SmartSuite Web UI\n  地址: http://{host}:{port}\n  按 Ctrl+C 停止\n")
    app.run(host=host, port=port, debug=debug)


def cli(argv: list[str] | None = None) -> int:
    """控制台入口（`smartsuite-web` / `python -m smartsuite.web.app`）。

    审查 2026-09-19 E14a：此前仅在 `__main__` 守卫内解析参数，导致 console
    script 若指向 `main()` 则无法传参（总是默认 host/port）。现抽为可复用
    入口，供 console script、模块执行与 run_server.py 三方共用。

    参数:
        argv: 参数列表；`None` 表示读 `sys.argv`（便于测试注入）。
    """
    import argparse

    parser = argparse.ArgumentParser(description="SmartSuite Web UI")
    parser.add_argument("--host", default=None, help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="监听端口 (默认: 5050)")
    parser.add_argument("--debug", action="store_true", help="启用 Flask debug 模式")
    args = parser.parse_args(argv)
    main(
        host=args.host or "127.0.0.1",
        port=args.port
        if args.port is not None
        else 5050,  # --port 0 是 Flask 合法值（随机端口），勿用 or 吞掉
        debug=bool(args.debug or os.environ.get("SMARTSUITE_DEBUG", "0") == "1"),
    )
    return 0


if __name__ == "__main__":
    # 不 sys.exit：runpy 入口（python app.py）须正常返回，退出码由 cli() 返回值
    # 经 console script 包装层承担（smartsuite-web = smartsuite.web.app:cli）
    cli()
