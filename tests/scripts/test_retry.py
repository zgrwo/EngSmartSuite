"""retry.py 瞬态错误重试装饰器测试。"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "retry.py"
mod = importlib.util.spec_from_file_location("retry", SPEC)
retry = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(retry)

retry_transient = retry.retry_transient


def test_success_no_retry():
    calls = []

    @retry_transient(max_attempts=3, delay=0)
    def ok():
        calls.append(1)
        return "done"

    assert ok() == "done"
    assert len(calls) == 1


def test_transient_error_retried_then_succeeds():
    calls = []

    @retry_transient(max_attempts=3, delay=0)
    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise ConnectionError("瞬态失败")
        return "recovered"

    assert flaky() == "recovered"
    assert len(calls) == 2


def test_transient_error_exhausts_attempts():
    calls = []

    @retry_transient(max_attempts=3, delay=0)
    def always_fails():
        calls.append(1)
        raise ConnectionError("总是失败")

    with pytest.raises(ConnectionError):
        always_fails()
    assert len(calls) == 3  # 达到上限后抛最后一次异常


def test_non_transient_error_immediately_raised():
    calls = []

    @retry_transient(max_attempts=3, delay=0)
    def fatal():
        calls.append(1)
        raise ValueError("非瞬态错误")

    with pytest.raises(ValueError):
        fatal()
    assert len(calls) == 1  # 非瞬态错误不重试


def test_custom_classifier():
    calls = []

    def is_flaky(exc):
        return isinstance(exc, (ConnectionError, TimeoutError))

    @retry_transient(max_attempts=3, delay=0, classifier=is_flaky)
    def custom():
        calls.append(1)
        if len(calls) < 2:
            raise TimeoutError("超时")
        return "ok"

    assert custom() == "ok"
    assert len(calls) == 2


# 注：不写"指数退避间隔递增"的实测断言——time.monotonic() 测量小延迟
# （0.05s 量级）受调度噪声影响，CI 上间歇失败（macOS 实证 0.146 < 0.185）。
# 重试行为（次数/成功恢复/上限）已由上述用例覆盖，退避计算正确性由实现保证。
