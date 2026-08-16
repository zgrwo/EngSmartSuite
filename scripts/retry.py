#!/usr/bin/env python3
"""
retry.py — 瞬态错误重试装饰器

背景（来源：ExcelVBA retry_decorator.py 的 com_retry / retry_com_call）：
  进程间通信（COM/gRPC/容器化服务/浏览器自动化）常有瞬态错误
  （RPC_E_CALL_REJECTED、连接重置、超时）——不是缺陷，重试即可恢复。
  本模块提供通用的 `@retry_transient` 装饰器，错误分类器可注入。

用法：
  from retry import retry_transient

  @retry_transient(max_attempts=3, delay=0.5)
  def call_service() -> bytes:
      return client.request()          # 瞬态错误会自动重试

  自定义错误分类（决定哪些异常可重试）：
  def is_transient(exc):
      return isinstance(exc, (ConnectionError, TimeoutError))

  @retry_transient(max_attempts=5, classifier=is_transient)
  def flaky() -> int: ...

设计：
  - 指数退避：delay * backoff^attempt（默认 backoff=2）
  - 非瞬态错误立即重抛（不浪费重试）
  - 达到上限后抛最后一次异常（保留原因链）
"""

import functools
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _default_classifier(exc: BaseException) -> bool:
    """默认瞬态错误分类：网络/超时类。

    ConnectionError / TimeoutError 是 OSError 子类，若再叠加 OSError，
    会把 FileNotFoundError / PermissionError 也误判为「瞬时可重试」。
    """
    return isinstance(exc, (ConnectionError, TimeoutError))


def retry_transient(
    max_attempts: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    classifier: Callable[[BaseException], bool] | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """瞬态错误重试装饰器。

    Args:
        max_attempts: 最大尝试次数（含首次）。
        delay: 首次重试延迟秒数。
        backoff: 退避倍数（每次重试 delay *= backoff）。
        classifier: 判断异常是否可重试的 callable；默认网络/超时类。

    Returns:
        若最终仍失败，抛最后一次异常（非瞬态立即重抛）。
    """
    is_transient = classifier or _default_classifier

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay
            while True:
                try:
                    return func(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 —— 分类器决定是否重试
                    if not is_transient(exc) or attempt >= max_attempts:
                        raise
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1

        return wrapper

    return decorator


if __name__ == "__main__":
    # 演示：模拟瞬态失败后成功
    calls = {"n": 0}

    @retry_transient(max_attempts=4, delay=0.01)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("瞬时断连")
        return "ok"

    print(flaky(), f"（第 {calls['n']} 次成功）")
