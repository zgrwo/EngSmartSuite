"""Web 安全套件共享夹具（审查 2026-09-19 C4）。

上传临时目录的隔离由 `tests/conftest.py` 的 autouse 夹具统一负责（审查 2026-09-21
D2：进程级注册表已移除，隔离手段改为每个测试一个上传目录）。
"""

import pytest

from smartsuite.web.app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def csrf(client):
    """返回可重复调用的取 token 函数（同一会话内 token 稳定）。"""

    def _token() -> str:
        resp = client.get("/api/csrf-token")
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["token"]

    return _token
