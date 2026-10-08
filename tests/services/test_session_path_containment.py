"""会话数据路径的目录归属校验（P3-2）。

对应第三轮复核 P3-2（logs/reports/verify-round3/R3-复核清单.md）：

`/api/upload` 把落盘路径存入 session（`session["_data_path"] = tmp.name`），
`/api/analyze` 读 `session["_data_path"]` 并 `pd.read_parquet(path)`，
下一次上传还会 `os.unlink(old_path)` —— **全程不校验该路径是否位于上传目录内**。

代码事实属实（app.py:356-360 / :402 逐行读毕）。风险定级说明：
唯一屏障是 Flask 的**签名 cookie**，伪造需先拿到 `SECRET_KEY`，
故这**不是可直接利用的漏洞**，而是**纵深防御缺口**——
一旦密钥泄露（或运维设了弱 `SMARTSUITE_SECRET`），
session 即可指向上传目录之外，导致读任意 parquet + **删除任意文件**。

本文件钉住三件事：
  1. 归属校验函数本身的行为（含 `..`、绝对路径、同前缀兄弟目录等边界）；
  2. 越界的 session 路径被**拒绝**而非放行；
  3. 越界的 session 路径**绝不会被 unlink**（这是最危险的那一步）。
"""

import contextlib
import os
import pathlib

import pandas as pd
import pytest

from smartsuite.web.app import (
    _is_within_upload_dir,
    _upload_dir,
    app,
)

_CSRF_KEY = "_csrf_token"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _get_csrf(client) -> str:
    with client.session_transaction() as sess:
        sess[_CSRF_KEY] = "t" * 64
    return "t" * 64


def _upload(client, tmp_path, name="d.xlsx"):
    """上传一份最小 Excel，返回响应 dict。"""
    xlsx = tmp_path / name
    pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]}).to_excel(xlsx, index=False)
    token = _get_csrf(client)
    with open(xlsx, "rb") as fh:
        resp = client.post(
            "/api/upload",
            data={"file": (fh, name)},
            headers={"X-CSRF-Token": token},
            content_type="multipart/form-data",
        )
    return resp


class TestIsWithinUploadDir:
    """归属校验函数本身（纯函数，边界密集）。"""

    def test_path_inside_upload_dir_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        target = _upload_dir() / "ss-abc.parquet"
        assert _is_within_upload_dir(target) is True

    def test_path_outside_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        outside = tmp_path / "elsewhere" / "ss-abc.parquet"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"x")
        assert _is_within_upload_dir(outside) is False

    def test_dotdot_traversal_is_rejected(self, tmp_path, monkeypatch):
        """`<upload>/../ss-x.parquet` 归一化后在上传目录之外 → 必须拒绝。"""
        up = tmp_path / "up"
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(up))
        traversal = up / ".." / "ss-abc.parquet"
        assert _is_within_upload_dir(traversal) is False

    def test_sibling_with_common_prefix_is_rejected(self, tmp_path, monkeypatch):
        """`uploads-evil/` 与 `uploads/` 有公共前缀但不是子目录 —— 不得被前缀匹配放行。"""
        up = tmp_path / "uploads"
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(up))
        sibling = tmp_path / "uploads-evil" / "ss-abc.parquet"
        sibling.parent.mkdir(parents=True, exist_ok=True)
        assert _is_within_upload_dir(sibling) is False

    def test_upload_dir_itself_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        assert _is_within_upload_dir(_upload_dir()) is True

    def test_none_and_empty_are_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        assert _is_within_upload_dir(None) is False
        assert _is_within_upload_dir("") is False

    def test_string_path_is_accepted(self, tmp_path, monkeypatch):
        """session 里存的是 str（JSON 序列化），函数必须能吃 str。"""
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        target = str(_upload_dir() / "ss-abc.parquet")
        assert _is_within_upload_dir(target) is True

    def test_relative_path_is_resolved_before_check(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        (_upload_dir()).mkdir(parents=True, exist_ok=True)
        assert _is_within_upload_dir("up/ss-abc.parquet") is True


class TestAnalyzeRejectsForeignDataPath:
    """analyze 不得读取上传目录之外的文件。"""

    def test_foreign_path_rejected_and_not_read(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        _upload_dir()  # 确保目录存在
        # 在上传目录之外放一个合法 parquet，并把 session 指向它
        foreign = tmp_path / "secret.parquet"
        pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0]}).to_parquet(foreign)
        token = _get_csrf(client)
        with client.session_transaction() as sess:
            sess["_data_path"] = str(foreign)

        resp = client.post(
            "/api/analyze",
            json={"task": "normality_check", "targets": ["y"], "features": [], "params": {}},
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 400, (
            f"越界路径应被拒绝（400），实际 {resp.status_code}: {resp.get_data(as_text=True)[:200]}"
        )
        body = resp.get_json()
        assert "上传" in body["error"], f"错误应提示需重新上传: {body}"

    def test_valid_path_still_works(self, client, tmp_path, monkeypatch):
        """回归防线：正常路径不得被误伤。"""
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        up = _upload(client, tmp_path)
        assert up.status_code == 200, up.get_data(as_text=True)[:200]
        token = _get_csrf(client)
        resp = client.post(
            "/api/analyze",
            json={"task": "normality_check", "targets": ["a"], "features": [], "params": {}},
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


class TestUploadNeverUnlinksForeignFile:
    """最危险的一步：旧路径清理不得删除上传目录之外的文件。"""

    def test_foreign_old_path_is_not_deleted(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        _upload_dir()
        victim = tmp_path / "victim.txt"
        victim.write_text("do not delete", encoding="utf-8")

        token = _get_csrf(client)
        with client.session_transaction() as sess:
            sess["_data_path"] = str(victim)

        resp = _upload(client, tmp_path)
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert victim.exists(), "上传时的旧路径清理删除了上传目录之外的文件——这是 P3-2 最危险的后果"
        assert victim.read_text(encoding="utf-8") == "do not delete"

    def test_own_old_file_is_still_cleaned(self, client, tmp_path, monkeypatch):
        """回归防线：本 session 自己上一份上传文件仍应被清理（否则泄漏）。"""
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        assert _upload(client, tmp_path, name="a.xlsx").status_code == 200
        with client.session_transaction() as sess:
            first = sess["_data_path"]
        assert os.path.exists(first)
        assert _upload(client, tmp_path, name="b.xlsx").status_code == 200
        assert not os.path.exists(first), "自己上一份上传文件应被清理"


class TestUploadDirCleanupUnaffected:
    """TTL 扫描仍只清本应用文件（既有契约不得回退）。"""

    def test_sweep_only_removes_own_files(self, tmp_path, monkeypatch):
        from smartsuite.web import app as web_app
        from smartsuite.web.app import _sweep_expired

        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        # 重置节流（CLEANUP_MIN_INTERVAL_SECONDS=600，否则同进程内第二次扫描被跳过）
        monkeypatch.setattr(web_app, "_last_sweep_at", 0.0)
        d = _upload_dir()
        own = d / "ss-old.parquet"
        own.write_bytes(b"x")
        foreign = d / "someone-else.parquet"
        foreign.write_bytes(b"x")
        # 把 mtime 推到 TTL 之外
        old = 0
        with contextlib.suppress(OSError):
            os.utime(own, (old, old))
            os.utime(foreign, (old, old))
        _sweep_expired()
        assert not own.exists(), "本应用过期文件应被清理"
        assert foreign.exists(), "他人在同目录的文件不得被删除"

    def test_upload_dir_is_pathlib(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTSUITE_UPLOAD_DIR", str(tmp_path / "up"))
        assert isinstance(_upload_dir(), pathlib.Path)
