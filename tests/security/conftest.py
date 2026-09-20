"""Web 安全套件共享夹具（审查 2026-09-19 C4）。

与 `tests/services/conftest.py` 相同的隔离思路：模块级临时文件追踪表必须在每个
用例前后清空，否则上一个用例留下的路径会干扰清理逻辑的断言。
"""

import pytest

from smartsuite.web import app as app_module
from smartsuite.web.app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_upload_tracking():
    """隔离模块级临时文件追踪列表（先清理遗留文件，再清空追踪表）。"""
    app_module._cleanup_uploads()
    with app_module._upload_lock:
        app_module._UPLOAD_FILES.clear()
    yield
    app_module._cleanup_uploads()
    with app_module._upload_lock:
        app_module._UPLOAD_FILES.clear()


@pytest.fixture()
def csrf(client):
    """返回可重复调用的取 token 函数（同一会话内 token 稳定）。"""

    def _token() -> str:
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["token"]

    return _token
