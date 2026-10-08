"""Flask application — SmartSuite Web UI 入口。"""

import atexit
import contextlib
import functools
import logging
import os
import pathlib
import re
import secrets
import shutil
import sys
import tempfile
import time as _time
import uuid

import pandas as pd

# ── matplotlib 配置由引擎层统一管理（后端 Agg + 中文字体 + 配色方案）──
# 下方 services 导入会级联触发 engine/__init__.py 中的全局配置；因此 web/ 下任何
# 模块都**不得**再自设后端或在模块级导入 pyplot（见 B3 守卫
# tests/guards/test_matplotlib_backend_order.py）

try:
    from flask import Flask, jsonify, make_response, render_template, request, session
except ImportError:
    print("=" * 60)
    print("  ❌ SmartSuite Web UI 需要 Flask，但未安装。")
    print()
    print("  请运行：pip install smartsuite[web]")
    print("  或单独安装：pip install flask pyarrow")
    print("=" * 60)
    sys.exit(1)

from werkzeug.exceptions import HTTPException

from smartsuite.core.constants import GROUP_COLORS
from smartsuite.core.exceptions import CsvEncodingError, OutputError, ValidationError
from smartsuite.services import config
from smartsuite.services.data_io import read_csv_with_encoding
from smartsuite.services.orchestrator import (
    DEFAULT_PARAMS,
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    TASK_GROUPS,
    TASK_LABELS,
    TASK_REGISTRY,
    orchestrate,
)
from smartsuite.services.param_labels import (
    derive_param_hints,
    derive_param_labels,
    derive_param_options,
)
from smartsuite.services.reporter import EXPORT_FORMATS, export_report
from smartsuite.web.api import column_info, prepare_web_request, run_analysis

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


def _is_within_upload_dir(path) -> bool:
    """`path` 是否位于上传目录之内（含目录本身）。用于 session 数据路径的归属校验。

    契约：docs/governance/boundary-contract.md（B0 拒绝）

    审查 2026-09-24（第三轮复核 P3-2）：`/api/upload` 把落盘路径存入 session，
    `/api/analyze` 据此 `pd.read_parquet`，下一次上传还会 `os.unlink` 该路径——
    **全程不校验归属**。唯一屏障是 Flask 签名 cookie。这**不是可直接利用的漏洞**
    （伪造 session 需先拿到 `SECRET_KEY`），而是**纵深防御缺口**：一旦密钥泄露
    或运维配了弱 `SMARTSUITE_SECRET`，即可读任意 parquet 并**删除任意文件**。

    实现要点：
      - 两侧都做 `resolve()` 归一化，故 `..`、相对路径、符号链接都被展开后再比较；
      - 用 `os.path.commonpath` 做**路径段级**比较，而非字符串前缀——
        `uploads-evil/` 与 `uploads/` 有公共前缀但不同目录，前缀匹配会误放行；
      - `path` 为 None/空 → False（不可判定即拒绝）。

    有意不做的事：不校验文件是否真实存在（TOCTOU），那是调用方的事；
    不限制文件名（`_is_own_upload` 负责命名契约）。
    """
    if not path or not isinstance(path, (str, os.PathLike)):
        return False
    try:
        upload_root = _upload_dir().resolve()
        target = pathlib.Path(path).resolve()
    except (OSError, ValueError):
        return False
    try:
        return os.path.commonpath([str(upload_root), str(target)]) == str(upload_root)
    except ValueError:
        # 不同驱动器（Windows）→ commonpath 抛 ValueError → 必然不在同一目录树
        return False


def _is_own_upload(path: pathlib.Path) -> bool:
    """是否为本应用创建的上传临时文件（命名单一来源，审查 R1-2）。

    上传文件一律由 `NamedTemporaryFile(prefix="ss-", suffix=".parquet")` 创建
    （见 `/api/upload`），故 `ss-*.parquet` 即本应用所有物。按前缀收窄清理范围后，
    即使运维把 `SMARTSUITE_UPLOAD_DIR` 指向共享目录，也不会误删他人在同目录内的
    parquet（原先按 `*.parquet` 全量匹配，实测会删除无关文件）。
    """
    return path.name.startswith("ss-") and path.suffix == ".parquet"


def _parquet_safe(df: pd.DataFrame) -> pd.DataFrame:
    """把 pyarrow 无法序列化的混合类型 object 列转为 string（其余原样返回）。

    2026-09-23 现场：Excel 同列数值 + 文本（STEPSEQ 含 '02200.1.000100'）时，
    `to_parquet` 按 int64 推断后抛 ArrowInvalid → 上传 500。该列本无数值语义，
    转 pandas string（NA 保留为缺失）后落盘，下游按文本列处理。
    仅处理会致 pyarrow 失败的 mixed 家族：`mixed-integer-float` 是合法数值列
    （int+float），保持原样以免丢失数值语义。
    """
    mixed_cols = [
        c
        for c in df.columns
        if pd.api.types.is_object_dtype(df[c])
        and pd.api.types.infer_dtype(df[c], skipna=True) in ("mixed", "mixed-integer")
    ]
    if not mixed_cols:
        return df
    safe = df.copy()
    for c in mixed_cols:
        safe[c] = safe[c].astype("string")
    return safe


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


def _csrf_tokens_match(client_token, server_token) -> bool:
    """CSRF token 恒定时间比较 — 对任意字节序列返回 bool，**永不抛异常**。

    契约：docs/governance/boundary-contract.md（B0 拒绝）

    审查 2026-09-24（第三轮复核 P0-4）：
    `secrets.compare_digest` 对含非 ASCII 字符的 **str** 抛
    `TypeError: comparing strings with non-ASCII characters is not supported`
    （实测 'é' / '中' 均抛）。原实现直接把它放在请求处理路径上、且全项目没有
    errorhandler → 任意人发一个 `X-CSRF-Token: é` 就能让 /api/analyze 与
    /api/upload 返回 500 HTML 并刷日志（无需任何凭据）。

    修复要点（两层，缺一不可）：
      1. 先 `encode("utf-8")` 转 bytes —— compare_digest 对 bytes 不做 ASCII 检查，
         语义是「任意字节序列的恒定时间比较」，正是我们要的；
      2. `encode` 本身对含 **孤立代理对**（surrogate）的 str 会抛 UnicodeEncodeError，
         故整体包在 try 中兜底返回 False。

    注意：不在此处 `strip()`。token 是 hex 串，前后空白应视为不匹配而非容错，
    否则等于放宽 token 语法，与「恒定时间比较」的初衷相悖。
    """
    try:
        if not isinstance(client_token, str) or not isinstance(server_token, str):
            return False
        if not client_token or not server_token:
            return False
        return secrets.compare_digest(client_token.encode("utf-8"), server_token.encode("utf-8"))
    except (UnicodeEncodeError, TypeError, AttributeError):
        # 孤立代理对 / 非字符串输入 → 视为不匹配（拒绝），不向调用方抛异常
        return False


def require_csrf(f):
    """CSRF 校验装饰器：POST 端点需携带 X-CSRF-Token 头匹配 session token。"""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            client_token = request.headers.get("X-CSRF-Token", "")
            server_token = session.get(_CSRF_TOKEN_KEY, "")
            if not _csrf_tokens_match(client_token, server_token):
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
    """安全响应头（CSP 纵深防御）。

    审查 2026-09-24（P3-3）：`script-src` 原被迫含 `'unsafe-inline'`，因为模板与
    JS 模板字面量里有 11 处内联事件处理器（`onclick`）。这些已全部改为
    `data-action` + 根级事件委托（见 `static/app.js` 的 ACTIONS 表），
    故**脚本侧的 `unsafe-inline` 已移除**。

    审查 2026-09-24（第二十九轮）：`style-src` 的 `'unsafe-inline'` **也已移除**。
    原因是 CSP3 起 `style-src` 的 `'unsafe-inline'` 同样覆盖**行内 `style="…"` 属性**
    —— 要收紧它就必须把行内样式全部改成 class，本轮做了这件事（7 处）：

      - `display:none` × 3 → `.is-hidden`（`!important`，见 style.css 的说明）；
      - 错误提示色 × 3 → `.empty-hint.is-error`；
      - 相关系数矩阵按值着色 × 1 → `.cell-strong` / `.cell-normal` 两档；
      - 工作流分组背景色 × 1 → 5 个静态 `[data-group="…"]` 规则。

    最后一项需要说明：分组色原经 `style="--group-bg: {{ 色值 }}"` 注入 CSS 变量。
    `data-*` 属性**无法**驱动 `background`（CSS3 的 `attr()` 只能用于 `content`），
    而 `GROUP_COLORS` 是**固定 5 项**，故安全地固化为静态类 ——
    一致性由 `tests/guards/test_web_ui_guards.py::test_wf_group_colors_match_engine` 守护。

    两条收紧分别由 `test_csp_allows_no_inline_script` 与
    `test_csp_allows_no_inline_style` 锁定。
    """
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    # 点击劫持纵深：frame-ancestors 已被现代浏览器支持，X-Frame-Options 覆盖旧浏览器
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


# ── API 统一错误契约（审查 2026-09-24 R3-P3-1）──
# 原状态：全项目零 errorhandler → /api/* 的 404/405/413/500 全部返回 Flask 默认
# **HTML** 错误页，而业务 4xx 返回 {"error": 中文}。API 消费者需同时处理两种格式，
# 且 413（超过 MAX_CONTENT_LENGTH）由 WSGI 层抛出，业务代码无法拦截。
# 现约定：**/api/ 前缀的请求，任何错误都返回 JSON**；页面路由保持 HTML 行为。
_API_ERROR_PAGES: dict[int, str] = {
    400: "请求格式不正确",
    403: "无权访问该资源",
    404: "请求的接口不存在",
    405: "请求方法不被支持",
    413: "请求数据过大（超过服务器限制），请减少数据量或列数",
    500: "服务器内部错误，请稍后重试",
}


def _wants_json_error() -> bool:
    """该请求的错误响应是否应为 JSON：仅 /api/ 前缀。"""
    return request.path.startswith("/api/")


def _json_error_response(status: int):
    """构造 API 错误 JSON 响应；页面路由返回 None 交回 Flask 默认 HTML。"""
    if not _wants_json_error():
        return None
    return jsonify({"error": _API_ERROR_PAGES.get(status, "请求处理失败")}), status


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
def _handle_client_error(exc):  # pragma: no cover — 装饰器链共用实现
    """4xx → /api/ 路径返回 JSON，页面路径保留 Flask HTML 行为。"""
    status = getattr(exc, "code", 400) or 400
    return _json_error_response(status) or exc


@app.errorhandler(413)
def _handle_request_entity_too_large(exc):
    """上传体超过 MAX_CONTENT_LENGTH → 413 JSON（而非 WSGI 层 HTML 500/413）。

    实测（复核 A6）：Flask 对超限请求抛 RequestEntityTooLarge，但测试套件
    从未覆盖该路径（全仓 grep 413 零命中），前端 app.js:82-84 只能靠
    "r.json() 失败 → 猜状态码" 兜底。
    """
    return _json_error_response(413) or exc


@app.errorhandler(Exception)
def _handle_unexpected_error(exc):
    """未预期异常兜底：API 路径返回 500 JSON（不回显内部细节），页面路径交回 Flask。

    审查 2026-09-24 R3：此前 /api/* 的任何逃逸异常（如非 ASCII CSRF token 的
    TypeError、上传目录不可用时的 OSError）都渲染成 HTML 500，客户端 JSON 解析
    失败后只能显示"网络错误"，真实原因与 error_id 全部丢失。
    """
    if isinstance(exc, HTTPException):
        return _json_error_response(exc.code or 500) or exc
    if not _wants_json_error():
        raise exc
    error_id = uuid.uuid4().hex[:8]
    logger.exception(
        "API 未预期异常 [error_id=%s]: %s %s, error_type=%s",
        error_id,
        request.method,
        request.path,
        type(exc).__name__,
    )
    return (
        jsonify(
            {
                "error": "服务器内部错误，请稍后重试",
                "error_id": error_id,
            }
        ),
        500,
    )


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

    # 混合类型列先转 string：pyarrow 对 object mixed 列抛 ArrowInvalid（2026-09-23 现场）
    df = _parquet_safe(df)

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
    # 审查 2026-09-24（第三轮复核 P3-2）：删除前**必须**校验归属。
    # 这是本流程最危险的一步——session 可被伪造时会变成"删任意文件"。
    # 越界时不删除，仅记日志（不打断当前上传，用户已拿到新数据）。
    if old_path and old_path != tmp.name and os.path.exists(old_path):
        if _is_within_upload_dir(old_path):
            with contextlib.suppress(OSError):
                os.unlink(old_path)
        else:
            logger.warning("跳过删除上传目录之外的旧数据路径（会话路径越界）: %s", old_path)
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
        elif not _is_within_upload_dir(path):
            # 审查 2026-09-24（第三轮复核 P3-2）：会话路径必须落在上传目录内。
            # 记 warning 供运维发现异常会话；对用户按"未上传"处理（不泄漏路径细节）。
            logger.warning("会话数据路径越界，已拒绝读取: %s", path)
            return jsonify({"error": "数据文件无效，请重新上传数据文件"}), 400
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


def _load_session_frame(task: str):
    """读取本会话的数据帧；返回 `(df, error_response)`。

    `/api/analyze` 与 `/api/export` 共用，确保**路径安全校验不漂移**
    （会话路径必须落在上传目录内 —— 审查 2026-09-24 第三轮复核 P3-2）。
    无需数据的任务返回空 DataFrame。

    error_response 非 None 时，调用方应直接 `return error_response`。
    """
    path = session.get("_data_path")
    if task in NO_DATA_TASKS:
        return pd.DataFrame(), None
    if not path or not os.path.exists(path):
        return None, (jsonify({"error": "请先上传数据文件"}), 400)
    if not _is_within_upload_dir(path):
        logger.warning("会话数据路径越界，已拒绝读取: %s", path)
        return None, (jsonify({"error": "数据文件无效，请重新上传数据文件"}), 400)
    try:
        return pd.read_parquet(path), None
    except FileNotFoundError:
        logger.warning("上传数据文件已被清理，请重新上传: %s", path)
        return None, (jsonify({"error": "上传的数据文件已过期，请重新上传"}), 400)


@app.route("/api/export", methods=["POST"])
@require_csrf
def export_report_endpoint():
    """把分析结果导出为报告文件并作为附件下载（阶段 P5，2026-09-24）。

    ## 补的是什么缺口

    `services/reporter.py` 的 `to_html`/`to_pdf`/`to_ppt` 与
    `audit.export_workbook` 此前**只有 Python API 能用** —— CLI 无导出命令、
    Web 无导出端点。用户跑完分析**拿不到报告文件**，这是产品级缺口。

    ## 为什么要重跑分析

    报告需要 `AnalysisResult.figures`（matplotlib 对象，无法经 JSON 往返），
    故不能复用前端已有的 `/api/analyze` 结果。本端点按同一份请求体重新执行分析。

    ## 与 `/api/analyze` 的一致性

    数据读取与路径安全校验**复用 `_load_session_frame()`**（同一实现），
    避免两处各写一份导致安全校验漂移。
    """
    try:
        # `force=True`：即使客户端没带 `Content-Type: application/json` 也解析。
        # 不用 `silent=True` —— 那会让"没带 JSON"与"JSON 是空对象"无法区分，
        # 于是无 CSRF token 的探测请求会先撞上 400（参数缺失）而不是 403（鉴权），
        # 掩盖真实原因（本端点首版即如此，被 test_export_requires_csrf 抓出）。
        body = request.get_json(force=True, silent=True)
        if body is None:
            return jsonify({"error": "请求体必须是 JSON 对象"}), 400
        task = body.get("task", "")
        fmt = body.get("format", "")
        if not isinstance(task, str) or not task:
            return jsonify({"error": "缺少分析任务"}), 400
        if task not in TASK_REGISTRY:
            return jsonify({"error": f"未知的分析任务「{task}」"}), 400
        targets = body.get("targets", [])
        features = body.get("features", [])
        categoricals = body.get("categoricals", [])
        params = body.get("params", {})
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            return jsonify({"error": "targets 必须是字符串列表"}), 400
        if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
            return jsonify({"error": "features 必须是字符串列表"}), 400
        if not isinstance(params, dict):
            return jsonify({"error": "params 必须是字典"}), 400

        # 格式白名单（与 exporter 的 EXPORT_FORMATS 同源，不在此另列一份）
        key = fmt.strip().lower() if isinstance(fmt, str) else ""
        if key not in EXPORT_FORMATS:
            return jsonify(
                {"error": f"不支持的报告格式「{fmt}」，支持: " + " / ".join(sorted(EXPORT_FORMATS))}
            ), 400

        df, err = _load_session_frame(task)
        if err is not None:
            return err

        target = targets[0] if targets else ""
        if not target and task not in NO_TARGET_TASKS:
            return jsonify({"error": "缺少目标列"}), 400
        # 与 `/api/analyze` 走**同一套预处理**（`prepare_web_request`）：
        # 跳过预处理会漏掉 one-hot 冲突等前置校验，让导出报告里的数值与屏幕上
        # 不一致 —— 那比报错更糟（用户不会怀疑报告）。
        req = prepare_web_request(task, df, targets, features, categoricals, params)
        result = orchestrate(req)
        if result.status != "ok":
            # 分析本身失败（参数非法等）→ 400 + 中文原因，不得 500
            return jsonify({"error": "；".join(result.messages) or "分析失败，无法导出"}), 400

        ext, mime = EXPORT_FORMATS[key]
        # reporter 的三种导出都写**文件路径**（它们同时是 CLI 的导出入口，
        # 那个契约不该为了 Web 改）。故此处写临时目录、读回内存、随即删目录 ——
        # 不用 `send_file`：它持有的文件句柄在测试里会以
        # `PytestUnraisableExceptionWarning: Exception ignored in FileIO` 暴露，
        # 且临时文件本就不该留下来。
        tmpdir = tempfile.mkdtemp(prefix="smartsuite_export_")
        try:
            out_path = os.path.join(tmpdir, f"{task}{ext}")
            export_report(
                result,
                key,
                out_path,
                df=df,
                target_col=target,
                feature_cols=features,
            )
            with open(out_path, "rb") as fh:
                payload = fh.read()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # 文件名用任务名（用户下载后一眼能认出），并做 ASCII 安全化：
        # 响应头只能放 latin-1，中文任务名会让 werkzeug 抛 UnicodeEncodeError。
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", task) or "report"
        resp = make_response(payload)
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Disposition"] = f'attachment; filename="{safe_name}{ext}"'
        resp.headers["Content-Length"] = str(len(payload))
        return resp
    except OutputError as e:
        # 导出层明确的中文拒绝（如 xlsx 缺列信息）→ 400
        logger.warning("报告导出被拒绝: %s", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("报告导出失败: %s", str(e)[:200])
        return jsonify({"error": "报告导出失败，请检查数据后重试"}), 500


@app.route("/api/tasks")
def list_tasks():
    """任务清单 + 标签 + 分组 + **参数默认值**。

    审查 2026-09-24（P4 步骤④）：新增 `params` 键，下发
    `services/task_spec.py::TASK_SPECS` 派生的 `DEFAULT_PARAMS`。

    目的：消灭前端 `params.js` 里那份**逐字重复**的 `TASK_PARAMS` 字面量。
    两份默认值必须一致，原先靠 `scripts/verify_frontend_params.py` 每次门禁
    比对来维持（手工一致性）；改由本端点下发后，后端是唯一事实源，
    **结构上不可能不一致**。

    无参数的任务下发 `{}`（而非缺失）—— 前端据此决定是否显示参数面板，
    "缺失"会被误当成"未知任务"。
    """
    return jsonify(
        {
            "tasks": list(TASK_REGISTRY.keys()),
            "labels": TASK_LABELS,
            "groups": TASK_GROUPS,
            "params": {task: DEFAULT_PARAMS.get(task, {}) for task in TASK_REGISTRY},
            # 审查 2026-09-24（P4 步骤④续）：参数标签/提示派生自各任务的
            # `PARAM_SPEC`（`Opt(..., label=..., hint=...)`），取代前端
            # `params.js` 里的 `PARAM_LABELS` / `PARAM_HINTS` 两份重复字典。
            #
            # 键名用 `param_labels` 而非 `labels` —— 后者已被**任务**标签占用
            # （见上方 TASK_LABELS），复用会破坏任务按钮渲染。
            #
            # 尚未声明 `Spec` 的任务没有对应条目，前端回落到参数名本身
            # （`|| k`），故本项可先于逐任务迁移完成，中间态不会出现空白标签。
            "param_labels": derive_param_labels(),
            "param_hints": derive_param_hints(),
            # 下拉选项的值 + 显示文案（`Choice` 的 `(值, 文案)` 声明）；
            # 这是删除前端 PARAM_META（169 行）的前置。
            "param_options": derive_param_options(),
        }
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
