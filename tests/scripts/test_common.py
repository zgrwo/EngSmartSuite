"""scripts/common.py 的子进程环境助手单测（审查 2026-09-19 门禁假红根因硬化）。

背景：门禁脚本会以子进程跑 pytest / CLI 探针。子进程 import numpy 时 OpenBLAS 按
CPU 核数建线程池；内存紧张时子进程会以
"OpenBLAS error: Memory allocation still failed after 10 retries, giving up."
直接退出（非零退出码 / stdout 为空），使门禁出现间歇性假红。
`child_env()` 统一限制线程并固定 UTF-8 输出。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from common import child_env  # noqa: E402

_THREAD_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def test_limits_blas_threads_and_sets_utf8():
    env = child_env()
    for var in _THREAD_VARS:
        assert env[var] == "1", f"{var} 应被限制为 1，实际 {env[var]!r}"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_respects_explicit_user_setting(monkeypatch):
    """用户显式设置的线程数不得被覆盖（setdefault 语义）。"""
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "8")
    assert child_env()["OPENBLAS_NUM_THREADS"] == "8"


def test_overrides_are_stringified():
    env = child_env(PYTHONPATH="/tmp/x", SMARTSuite_PROBE=3)
    assert env["PYTHONPATH"] == "/tmp/x"
    assert env["SMARTSuite_PROBE"] == "3"


def test_does_not_mutate_parent_environment():
    before = dict(os.environ)
    child_env()
    assert dict(os.environ) == before, "child_env 不得修改父进程环境"


def test_returns_plain_dict_of_str():
    """subprocess 的 env 必须是 {str: str}（含非 str 值会直接报错）。"""
    env = child_env()
    assert isinstance(env, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
