"""`scatter_plot` 对 `±Inf` 的清洗与披露（审查 2026-10-09 R2BD-11，P2；实测含红线违约）。

缺陷形态（生产口径，目标列 `y` 前 3 行 `+Inf`，四路对照）：

| 输入 | status | `metadata.n_points` | messages |
| :--- | :--- | :--- | :--- |
| 干净 | ok | **60** | `[]` |
| **y 含 3 个 +Inf** | ok | **60** | **`[]`** ← 与干净情形**完全一致** |
| y 含 3 个 NaN | ok | 57 | `[]` |
| 删掉那 3 行 | ok | 57 | `[]` |

即 ±Inf 行被当成有效点画进图（`n_points=60`），既不清洗也不披露 —— 与 NaN 的处理
（静默丢弃，符合 L4 契约）不一致。**根因**：`scatter_plot` 未接 `_guard`；
`exploratory.py` 因同文件其他函数（`distribution_summary`/`box_chart`）用了
`clean_series` 而被**文件级**源码守卫放行（R2BD-02/03/11 同一机制）。

⚠️ 本轮新发现（比报告记载更严重）：当 `fit="linear"`（前端可选、
`tests/guards/test_boundary_disclosure.py` 已登记该参数组合）时，
`LinearRegression().fit` 直接抛 `ValueError: Input y contains infinity`
**未捕获逃出引擎** —— 红线违约（引擎必须返回 `AnalysisResult(status="error")`）。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.exploratory import scatter_plot


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    return pd.DataFrame({"x1": rng.uniform(0, 1, 60), "y": rng.normal(5.0, 1.0, 60)})


def _run(frame: pd.DataFrame, fit: str):
    return scatter_plot(
        AnalysisRequest(
            task="scatter_plot",
            data=frame,
            target_col="y",
            feature_cols=["x1"],
            params={"fit": fit},
        )
    )


@pytest.mark.parametrize("fit", ["none", "linear"])
def test_inf_rows_are_removed_from_the_plot_and_disclosed(fit):
    """±Inf 行不得进入图（`n_points` 必须回到 57）且必须披露数量与列名。"""
    frame = _frame()
    injected = frame.copy()
    injected.loc[:2, "y"] = np.inf
    result = _run(injected, fit)
    assert result.status == "ok", result.messages
    assert result.metadata["n_points"] == 57, (
        f"fit={fit}: ±Inf 行仍被当成有效点画进图（n_points={result.metadata['n_points']}，"
        "NaN 情形为 57）"
    )
    blob = " ".join(result.messages)
    assert "3" in blob and ("±Inf" in blob or "非有限值" in blob), (
        f"fit={fit}: ±Inf 既未清洗也未披露：messages={result.messages}"
    )
    assert "E_DATA_NON_FINITE_DROPPED" in result.metadata.get("boundary_codes", []), (
        f"fit={fit}: 缺少机器可读错误码：{result.metadata.get('boundary_codes')}"
    )


@pytest.mark.parametrize("fit", ["none", "linear"])
def test_linear_fit_does_not_raise_on_inf(fit):
    """`fit="linear"` 不得把非有限值喂给 sklearn（原为未捕获 `ValueError`）。"""
    frame = _frame()
    injected = frame.copy()
    injected.loc[:2, "y"] = np.inf
    result = _run(injected, fit)  # 不抛异常即为通过；数值断言见下
    assert result.status == "ok", result.messages
    if fit == "linear":
        assert np.isfinite(float(result.metadata["r_squared"])), (
            f"清洗后 R² 应有限：{result.metadata['r_squared']}"
        )


def test_result_matches_dropping_the_inf_rows():
    """真清洗判据：结果（n_points 与 R²）必须与"直接删掉那 3 行"逐值一致。"""
    frame = _frame()
    injected = frame.copy()
    injected.loc[:2, "y"] = np.inf
    dropped = frame.iloc[3:].reset_index(drop=True)
    a, b = _run(injected, "linear"), _run(dropped, "linear")
    assert a.metadata["n_points"] == b.metadata["n_points"] == 57
    assert float(a.metadata["r_squared"]) == pytest.approx(
        float(b.metadata["r_squared"]), rel=1e-12
    )


def test_feature_column_inf_is_also_cleaned():
    """X 列的 ±Inf 同样必须清洗（拟合与坐标都吃它）。"""
    frame = _frame()
    injected = frame.copy()
    injected.loc[:2, "x1"] = -np.inf
    result = _run(injected, "linear")
    assert result.status == "ok", result.messages
    assert result.metadata["n_points"] == 57
    assert "±Inf" in " ".join(result.messages) or "非有限值" in " ".join(result.messages)


def test_nan_stays_silent_and_is_dropped():
    """NaN 属缺失语义（契约 L4，免披露）—— 清洗不得把 NaN 变成噪音。"""
    frame = _frame()
    injected = frame.copy()
    injected.loc[:2, "y"] = np.nan
    result = _run(injected, "linear")
    assert result.status == "ok", result.messages
    assert result.metadata["n_points"] == 57
    assert result.messages == [], f"NaN 被当成 ±Inf 披露：{result.messages}"
    assert result.metadata.get("boundary_codes", []) == []


def test_grouped_scatter_also_cleans_inf():
    """带分组列时同样必须清洗（分组列是字符串，不能被数值清洗路径静默跳过）。"""
    rng = np.random.default_rng(6)
    frame = pd.DataFrame(
        {
            "x1": rng.uniform(0, 1, 60),
            "y": rng.normal(5.0, 1.0, 60),
            "g": (["A", "B", "C"] * 20),
        }
    )
    injected = frame.copy()
    injected.loc[:2, "y"] = np.inf
    result = scatter_plot(
        AnalysisRequest(
            task="scatter_plot",
            data=injected,
            target_col="y",
            feature_cols=["x1"],
            params={"fit": "linear", "group_col": "g"},
        )
    )
    assert result.status == "ok", result.messages
    assert result.metadata["n_points"] == 57, (
        f"分组路径未清洗 ±Inf（n_points={result.metadata['n_points']}）"
    )
    assert "±Inf" in " ".join(result.messages) or "非有限值" in " ".join(result.messages)
