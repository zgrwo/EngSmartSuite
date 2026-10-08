"""日志目录解析契约（`setup_logging` 的默认落点）。

对应第三轮复核 P1-7（logs/reports/verify-round3/R3-复核清单.md）：

    if log_dir is None:
        # 项目根目录相对于 __init__.py 是 ../../（src/ 布局）
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")

源码检出（src 布局）下该路径正确解析到仓库根 `logs/`。
但 **wheel/site-packages 安装**后，`dirname(__file__)` 是
`.../site-packages/smartsuite`，`../../logs` 变成
`.../site-packages/logs` —— 两类后果：

  1. 可写时：日志污染 Python 的 site-packages（卸载包不会清理，属"装到别人家里"）；
  2. 不可写时（系统级安装/只读容器）：**静默降级到临时目录**，
     用户找不到日志却不知道该去哪找。

修复取向：
  - `SMARTSUITE_LOG_DIR` 环境变量优先（运维/测试显式指定）；
  - 否则用**当前工作目录**下的 `logs/`（与 `run_server.py` 从仓库根启动的既有行为一致）；
  - 源码检出场景下 cwd 与包根通常相同，行为不变；
  - 仍在 `~/.smartsuite/logs` 与系统临时目录之间保留降级链，但**必须记日志说明落点**。
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import pytest

import smartsuite


@pytest.fixture
def root_handlers_backup():
    """保存并恢复 root logger 的 handlers（同 test_service_guards.py 的模式）。"""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


def _file_handler(root):
    return next(
        (h for h in root.handlers if isinstance(h, RotatingFileHandler)),
        None,
    )


class TestLogDirResolution:
    def test_explicit_log_dir_is_used(self, root_handlers_backup, tmp_path):
        target = tmp_path / "mylogs"
        smartsuite.setup_logging(log_dir=str(target))
        fh = _file_handler(root_handlers_backup)
        assert fh is not None
        assert os.path.dirname(fh.baseFilename) == str(target)

    def test_env_var_takes_priority(self, root_handlers_backup, tmp_path, monkeypatch):
        """`SMARTSUITE_LOG_DIR` 必须优先于默认落点（运维/容器场景的唯一控制手段）。"""
        env_dir = tmp_path / "envlogs"
        monkeypatch.setenv("SMARTSUITE_LOG_DIR", str(env_dir))
        smartsuite.setup_logging()
        fh = _file_handler(root_handlers_backup)
        assert fh is not None
        assert os.path.dirname(fh.baseFilename) == str(env_dir), (
            f"未采纳 SMARTSUITE_LOG_DIR，实际落到 {fh.baseFilename}"
        )

    def test_default_is_cwd_logs_not_package_relative(
        self, root_handlers_backup, tmp_path, monkeypatch
    ):
        """默认落点必须是 cwd/logs，**不得**是包安装目录下的 logs。

        这是 P1-7 的核心断言：模拟"包被安装在别处"（如 site-packages）时，
        日志不得写进包目录。
        """
        monkeypatch.delenv("SMARTSUITE_LOG_DIR", raising=False)
        work = tmp_path / "workdir"
        work.mkdir()
        monkeypatch.chdir(work)
        smartsuite.setup_logging()
        fh = _file_handler(root_handlers_backup)
        assert fh is not None
        actual = os.path.dirname(fh.baseFilename)
        assert actual == str(work / "logs"), f"默认落点应为 cwd/logs，实际 {actual}"

        pkg_dir = os.path.dirname(os.path.abspath(smartsuite.__file__))
        assert not actual.startswith(pkg_dir), (
            f"日志写进了包安装目录 {pkg_dir}（site-packages 污染）"
        )

    def test_env_var_with_relative_path_resolves_to_cwd(
        self, root_handlers_backup, tmp_path, monkeypatch
    ):
        work = tmp_path / "wd"
        work.mkdir()
        monkeypatch.chdir(work)
        monkeypatch.setenv("SMARTSUITE_LOG_DIR", "customlogs")
        smartsuite.setup_logging()
        fh = _file_handler(root_handlers_backup)
        assert fh is not None
        assert os.path.dirname(fh.baseFilename) == str(work / "customlogs")


class TestDegradationIsReported:
    """降级必须可追溯——原实现在静默降级到临时目录后用户无从得知。"""

    def test_unwritable_env_dir_falls_back_to_temp_and_warns(
        self, root_handlers_backup, monkeypatch, tmp_path, caplog
    ):
        import tempfile

        blocker = tmp_path / "notadir"
        blocker.write_text("x", encoding="utf-8")  # 路径是文件 → makedirs 必然失败
        monkeypatch.setenv("SMARTSUITE_LOG_DIR", str(blocker / "logs"))

        with caplog.at_level(logging.WARNING):
            smartsuite.setup_logging()

        fh = _file_handler(root_handlers_backup)
        assert fh is not None, "降级后仍应有文件 handler（临时目录）"
        assert os.path.dirname(fh.baseFilename) == tempfile.gettempdir()
        assert any("临时" in r.message or "降级" in r.message for r in caplog.records), (
            f"降级到临时目录必须记日志，实际 records={[r.message for r in caplog.records]}"
        )

    def test_successful_setup_logs_the_actual_location(
        self, root_handlers_backup, tmp_path, monkeypatch, caplog
    ):
        """成功时也要说明落点——用户需要知道日志在哪。"""
        monkeypatch.setenv("SMARTSUITE_LOG_DIR", str(tmp_path / "l"))
        with caplog.at_level(logging.INFO):
            smartsuite.setup_logging()
        assert any("日志" in r.message for r in caplog.records)


class TestIdempotenceUnchanged:
    """幂等与降级契约不得因本次改动回退。"""

    def test_second_call_is_noop(self, root_handlers_backup, tmp_path):
        smartsuite.setup_logging(log_dir=str(tmp_path / "a"))
        n_first = len(root_handlers_backup.handlers)
        smartsuite.setup_logging(log_dir=str(tmp_path / "b"))
        assert len(root_handlers_backup.handlers) == n_first

    def test_rotation_settings_unchanged(self, root_handlers_backup, tmp_path):
        smartsuite.setup_logging(log_dir=str(tmp_path / "r"))
        fh = _file_handler(root_handlers_backup)
        assert fh is not None
        assert fh.maxBytes == 1 * 1024 * 1024
        assert fh.backupCount == 5
        assert fh.level == logging.DEBUG
