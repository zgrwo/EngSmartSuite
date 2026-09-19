"""EngSmartSuite 性能基准 — 3 代表任务 × 3 规模。

运行：uv run pytest benchmarks/ --benchmark-only -q --benchmark-json=benchmark.json
设计：经 services.orchestrate 走端到端路径（含校验与绘图），与用户实际耗时一致。
非门禁：本文件不在 tests/ 下、不被默认 pytest 收集；结果作为构件对比，不设阈值。
"""

import gc

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

SIZES = [1_000, 10_000, 100_000]
RNG = np.random.default_rng(42)


def _anova_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "val": RNG.normal(10, 1, n),
            "group": RNG.choice(["A", "B", "C", "D", "E"], n),
        }
    )


def _spc_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "val": RNG.normal(10, 1, n),
            "subgroup": np.repeat(np.arange(1, n // 5 + 1), 5)[:n],
        }
    )


def _survival_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": RNG.exponential(10, n).round(3),
            "event": RNG.integers(0, 2, n),
        }
    )


def _release(result) -> None:
    for fig in result.figures:
        fig.clear()
    del result
    gc.collect()


@pytest.mark.benchmark(group="anova")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_anova(benchmark, n):
    req = AnalysisRequest(task="anova", data=_anova_df(n), target_col="val", feature_cols=["group"])
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)


@pytest.mark.benchmark(group="spc_xbar")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_spc_xbar(benchmark, n):
    req = AnalysisRequest(
        task="spc_xbar", data=_spc_df(n), target_col="val", feature_cols=["subgroup"]
    )
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)


@pytest.mark.benchmark(group="survival")
@pytest.mark.parametrize("n", SIZES)
def test_benchmark_survival(benchmark, n):
    req = AnalysisRequest(
        task="survival_analysis", data=_survival_df(n), target_col="time", feature_cols=["event"]
    )
    result = benchmark(orchestrate, req)
    assert result.status == "ok"
    _release(result)
