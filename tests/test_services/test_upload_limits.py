"""上传边界与 CLI 输出测试（审查 #R2：probe 复用 / --outdir 路径补测）。

- test_upload_csv_row_limits：CSV 探测复用优化（app.py:234-237）的行数边界
  （恰好 100_000 行通过复用 probe，100_001 行拒绝）
- test_cli_outdir_success / test_cli_outdir_creatable_error：CLI 图表保存路径
  （成功保存 PNG + 只读/文件路径优雅中文报错，不裸 traceback）
"""

import io
import sys

import pytest

from smartsuite.web.app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c


def _upload_csv(client, n_rows: int):
    """构造 n 行 CSV 上传，返回 (status_code, json)。"""
    buf = io.BytesIO()
    buf.write(b"v1,v2\n")
    for i in range(n_rows):
        buf.write(f"{i},{i * 2}\n".encode())
    buf.seek(0)
    # 先取 CSRF token（session cookie 自动保持）
    token_resp = client.get("/api/csrf-token")
    assert token_resp.status_code == 200
    token = token_resp.get_json()["token"]
    data = {"file": (buf, "rows.csv")}
    return client.post(
        "/api/upload",
        data=data,
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": token},
    )


def test_upload_csv_exact_100000_rows_ok(client):
    """恰好 100_000 行：probe 读完全部行，直接复用（不再全量重读）。"""
    resp = _upload_csv(client, 100_000)
    assert resp.status_code == 200, f"100000 行应上传成功: {resp.get_json()}"
    body = resp.get_json()
    assert body["shape"] == [100_000, 2]


def test_upload_csv_100001_rows_rejected(client):
    """100_001 行：probe 检测超限即拒绝（不触发全量解析内存峰值）。"""
    resp = _upload_csv(client, 100_001)
    assert resp.status_code == 400, "100001 行应被拒绝"
    assert "行数超过限制" in resp.get_json()["error"]


def test_upload_csv_header_only_empty_rejected(client):
    """仅表头（0 数据行）：probe 为空 DataFrame → 中文"文件为空"错误。"""
    resp = _upload_csv(client, 0)
    assert resp.status_code == 400
    assert "文件为空" in resp.get_json()["error"]


# ── CLI 图表保存路径 ──


def _silence_logging(monkeypatch):
    """CLI main() 内的 setup_logging 在 pytest 下会产生环境噪音：
    - 文件 handler 日志轮转失败（logs/smartsuite.log）
    - root logger 被前序测试配置的 StreamHandler 在 capsys 替换 stdout 后写入失败
    测试聚焦 CLI 逻辑本身，日志配置由其他测试覆盖。"""
    import logging

    import smartsuite as pkg

    logging.getLogger().handlers.clear()
    monkeypatch.setattr(pkg, "setup_logging", lambda: None)


def test_cli_outdir_success(tmp_path, monkeypatch, capsys):
    """--outdir 成功保存 PNG 且打印表格（第④层防线：CLI 数值表可见）。"""
    _silence_logging(monkeypatch)
    from smartsuite import cli

    outdir = tmp_path / "charts"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartsuite",
            "run",
            str(pytest._repo_root / "templates" / "example_correlation.yaml"),
            "-i",
            str(pytest._repo_root / "tests" / "test_data.xlsx"),
            "--outdir",
            str(outdir),
        ],
    )
    cli.main()
    out = capsys.readouterr().out
    assert "── correlation_matrix ──" in out, "CLI 应打印数值表"
    assert "图表已保存" in out, "CLI 应提示图表保存成功"
    saved = list(outdir.glob("*.png"))
    assert len(saved) == 2, f"correlation 应保存 2 张图（热力图+散点矩阵）: {saved}"


def test_cli_outdir_uncreatable_graceful(tmp_path, monkeypatch, capsys):
    """--outdir 指向已有文件（makedirs 失败）：中文报错、无裸 traceback、不崩溃。"""
    _silence_logging(monkeypatch)
    from smartsuite import cli

    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smartsuite",
            "run",
            str(pytest._repo_root / "templates" / "example_correlation.yaml"),
            "-i",
            str(pytest._repo_root / "tests" / "test_data.xlsx"),
            "--outdir",
            str(blocker),
        ],
    )
    cli.main()  # 不应抛异常（成功路径返回）
    err = capsys.readouterr().err
    assert "错误: 无法创建图表输出目录" in err, f"应有中文报错: {err!r}"
    assert "Traceback (most recent call last):" not in err, "不得暴露 Python traceback"
