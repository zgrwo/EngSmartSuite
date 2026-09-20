import pytest
import pathlib

pytest._repo_root = pathlib.Path(__file__).resolve().parent.parent

# 子进程内存硬化（2026-09-19 B3 根因诊断）：本项目多处守卫/门禁以 subprocess 起**新解释器**
# （tests/guards/*、scripts/verify_consistency.py 的嵌套 pytest 与 CLI 探针）。子进程
# import numpy 时 OpenBLAS 按 CPU 核数建线程池，而父进程已持有全套引擎依赖，内存紧张时
# 子进程会直接以 “OpenBLAS error: Memory allocation still failed after 10 retries” 退出，
# 表现为无关门禁间歇性假红（曾误判为“未解释现象”）。子进程只需读后端名/跑断言，无 BLAS
# 并行需求，故在会话级统一限制线程数；用 setdefault 尊重用户显式设置。
import os as _os

for _var in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    _os.environ.setdefault(_var, "1")

import numpy as np
import pandas as pd
import pytest

import werkzeug.test as _werkzeug_test

# error 门禁（2026-09-19）：werkzeug TestClient 对 >500KB 的 multipart 上传会创建
# NamedTemporaryFile 且请求结束后不主动关闭（上游行为），ResourceWarning 会在任意
# 后续测试的 GC 时刻爆出并误伤无关测试。测试数据本就在内存中，强制走内存编码。
_stream_encode_multipart = _werkzeug_test.stream_encode_multipart


def _stream_encode_multipart_in_memory(values, *args, **kwargs):
    kwargs.setdefault("use_tempfile", False)
    return _stream_encode_multipart(values, *args, **kwargs)


_werkzeug_test.stream_encode_multipart = _stream_encode_multipart_in_memory


@pytest.fixture
def sample_doe_data() -> pd.DataFrame:
    """注塑 DOE 实验数据：料温、模温、注射压力、保压时间 → 强度、不良率"""
    np.random.seed(42)
    n = 30
    return pd.DataFrame(
        {
            "料温": np.random.uniform(180, 220, n),
            "模温": np.random.uniform(40, 80, n),
            "注射压力": np.random.uniform(60, 100, n),
            "保压时间": np.random.uniform(5, 15, n),
            "强度": np.random.normal(45, 3, n),
            "不良率": np.random.beta(2, 98, n) * 100,
        }
    )


@pytest.fixture
def sample_spc_data() -> pd.DataFrame:
    """过程监控数据：30 个子组，每组 5 个样本"""
    np.random.seed(42)
    rows = []
    for subgroup in range(1, 31):
        for sample in range(1, 6):
            rows.append({"子组": subgroup, "样本": sample, "测量值": np.random.normal(10.0, 0.5)})
    return pd.DataFrame(rows)


@pytest.fixture
def sample_two_group_data() -> pd.DataFrame:
    """两组对比数据：新旧工艺"""
    np.random.seed(42)
    old = pd.DataFrame({"工艺": "旧工艺", "强度": np.random.normal(44, 3, 20)})
    new = pd.DataFrame({"工艺": "新工艺", "强度": np.random.normal(47, 3, 20)})
    return pd.concat([old, new], ignore_index=True)
