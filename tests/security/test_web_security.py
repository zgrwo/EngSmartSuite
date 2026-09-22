"""Web 安全回归套件（审查 2026-09-19 C4）。

防护本身此前已实现（CSRF / CSP / 会话 cookie / zip 限制 / 扩展名白名单 / 临时文件
隔离），本套件**不新增防护**，只把「声称有防护」变成可执行断言，并且：

1. **断言状态码与中文文案，不断言内部实现** —— 允许后续重构防护代码；
2. **按攻击面组织，而非按代码分支** —— `tests/services/test_web_app_routes.py` 已
   逐分支覆盖功能，此处补的是*跨端点不变量*，例如「所有 POST 端点都受 CSRF 保护」。
   该用例从 `url_map` **自动发现** POST 端点，新增端点若忘记加 `@require_csrf`
   会在此处直接变红，无需维护人工清单。
"""

import io
import os
import pathlib

import pytest

from smartsuite.web.app import app as flask_app

# 可执行/脚本类扩展名：白名单策略下必须一律拒绝
_EXECUTABLE_EXTENSIONS = [".py", ".exe", ".js", ".sh", ".bat", ".dll", ".so", ".php", ".jsp"]


def _post_rules() -> list[str]:
    """当前应用注册的所有 POST 路由（自动发现，避免人工清单漂移）。"""
    return sorted(
        rule.rule for rule in flask_app.url_map.iter_rules() if "POST" in (rule.methods or ())
    )


# ── CSRF：跨端点不变量 ──


def test_post_route_inventory_is_covered():
    """自动发现的前提：POST 路由存在且不含路径参数（有参数则需扩展构造逻辑）。"""
    rules = _post_rules()
    assert rules, "应至少注册一个 POST 端点"
    assert not [r for r in rules if "<" in r], (
        f"带路径参数的 POST 端点需要在此补充构造逻辑，否则会被静默漏测：{rules}"
    )


@pytest.mark.parametrize("rule", _post_rules())
def test_every_post_endpoint_requires_csrf(client, rule):
    """无 CSRF 头的 POST 必须被拒（403 + 中文）：新增端点漏加装饰器时在此变红。"""
    resp = client.post(rule, json={})

    assert resp.status_code == 403, f"{rule} 未受 CSRF 保护：{resp.status_code}"
    assert "CSRF" in resp.get_json()["error"]


def test_csrf_wrong_token_rejected(client):
    """token 存在但错误 → 403（区别于「缺失」，两者都不得放行）。"""
    resp = client.post("/api/analyze", json={}, headers={"X-CSRF-Token": "0" * 32})

    assert resp.status_code == 403
    assert "CSRF" in resp.get_json()["error"]


def test_csrf_valid_token_passes_the_gate(client, csrf):
    """正向对照：带正确 token 时不应再是 403（防「全部 403」也是绿的假象）。"""
    resp = client.post("/api/analyze", json={}, headers={"X-CSRF-Token": csrf()})

    assert resp.status_code != 403, resp.get_json()
    assert resp.status_code == 400, "无数据时应为 400（校验问题），而非 CSRF 拒绝"
    assert "CSRF" not in resp.get_json().get("error", "")


# ── 响应头 ──


def test_security_headers_present(client):
    """CSP / nosniff / Referrer-Policy 三项纵深防御头必须存在。"""
    resp = client.get("/api/tasks")
    headers = {k.lower(): v for k, v in resp.headers.items()}

    assert headers.get("content-security-policy"), "缺少 CSP 头"
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "no-referrer"


def test_csp_restricts_script_sources(client):
    """CSP 不得放开通配符脚本源或 eval（内联脚本已由模板决定，见 app.py 注释）。"""
    csp = client.get("/api/tasks").headers["Content-Security-Policy"]
    directive = next((d.strip() for d in csp.split(";") if d.strip().startswith("script-src")), "")

    assert directive, f"CSP 未声明 script-src：{csp!r}"
    assert "'unsafe-eval'" not in directive
    assert "*" not in directive.replace("'self'", ""), f"script-src 不应含通配符：{directive!r}"


def test_session_cookie_is_httponly_and_samesite(client):
    """会话 cookie 必须 HttpOnly（防 XSS 窃取）且 SameSite=Lax（防 CSRF 前置）。"""
    cookie = client.get("/api/csrf-token").headers.get("Set-Cookie", "")

    assert "HttpOnly" in cookie, cookie
    assert "SameSite=Lax" in cookie, cookie


# ── 文件上传攻击面 ──


@pytest.mark.parametrize("ext", _EXECUTABLE_EXTENSIONS)
def test_executable_extensions_rejected(client, csrf, ext):
    """白名单策略：可执行/脚本扩展名一律 400，且不进入解析流程。"""
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"payload"), f"evil{ext}")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf()},
    )

    assert resp.status_code == 400, f"{ext} 不应被接受"
    assert "不支持的文件格式" in resp.get_json()["error"]


def test_path_traversal_filename_cannot_escape_temp_dir(client, csrf):
    """文件名中的路径分隔符不得影响服务端落盘位置（落盘名由服务端生成）。"""
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "../../../evil.csv")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf()},
    )
    assert resp.status_code == 200, resp.get_json()

    with client.session_transaction() as sess:
        stored = sess["_data_path"]
    # 审查 2026-09-21 D2：落盘位置由服务端决定（专用上传目录，位于系统临时目录之下），
    # 文件名中的 `../` 不得影响它。
    from smartsuite.web import app as app_module

    assert pathlib.Path(stored).parent == app_module._upload_dir(), (
        f"上传文件落到服务端指定目录之外：{stored}"
    )
    # 不变量：落盘路径必须位于**服务端选定的上传目录**内（realpath 解符号链接）。
    # 不能用 tempfile.gettempdir() 作基准：conftest 会把 SMARTSUITE_UPLOAD_DIR
    # 隔离到 tmp_path，而 full job 的 --basetemp 又在系统临时目录之外
    # （2026-09-22 main full 矩阵 13/13 因此误红）。
    assert os.path.realpath(stored).startswith(
        os.path.realpath(str(app_module._upload_dir())) + os.sep
    ), f"上传文件不在服务端指定上传目录内：{stored}"


# ── 错误响应不泄漏内部信息 ──


@pytest.mark.parametrize(
    ("payload", "filename"),
    [
        (b"not a zip at all", "x.xlsx"),
        ("强度\n".encode("utf-16"), "x.csv"),
        (b"", "x.csv"),
    ],
)
def test_error_responses_do_not_leak_internals(client, csrf, payload, filename):
    """解析失败响应不得回显 traceback、内部模块路径或盘符路径。"""
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(payload), filename)},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf()},
    )
    assert resp.status_code == 400, (resp.status_code, resp.get_json())

    body = resp.get_data(as_text=True)
    for leaked in ("Traceback", "site-packages", 'File "', "smartsuite/", "smartsuite\\\\"):
        assert leaked not in body, f"响应泄漏内部信息 {leaked!r}：{body[:200]}"
