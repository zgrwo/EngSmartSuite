"""`vif_analysis` 对 `±Inf` 的清洗与披露（审查 2026-10-09 R2BD-03，P1）。

## 缺陷形态（生产口径，特征列 `x1` 前 3 行注入 `+Inf`）

| 输入 | status | messages | metadata |
| :--- | :--- | :--- | :--- |
| 干净 | ok | — | `{'high_vif_count': 0, 'invalid_vif_count': 0}` |
| **`x1` 含 3 个 `+Inf`** | **error** | `VIF 计算失败，请检查数据是否存在共线性或数值异常` | `{}` |
| `x1` 含 3 个 `NaN` | ok | — | 同上 |
| 直接删掉那 3 行 | ok | — | 同上 |

即：**`Inf` 的结果 ≠ `NaN` 的结果 ≠ 删行的结果**，且 `Inf` 路径下**全部数值表丢失**，
文案还把"含 `±Inf`"错误归因为"共线性/计算失败"（用户按"共线性"排查永远查不到原因）。

## 根因（与 R2BD-02 同一机制）

`dropna()` **不剔除 `±Inf`**（`Inf` 不是 `NaN`）；`modeling.py` 因同文件
`decision_tree_analysis` 已接 `_guard` 而被**文件级**源码守卫
（`test_boundary_contract.py::TestBoundaryContractSourceGuard`）整文件放行 ——
`vif_analysis` 自己没清洗，`variance_inflation_factor` 拿到含 `Inf` 的设计矩阵后
发散/抛错，落进外层 `except Exception`：结果表全丢 + 归因错 + 不披露。

## 判据（三条，缺一不可）

1. **真清洗** —— 结果必须与"直接删掉那 3 行"逐值一致（不是拒绝、不是 NaN 传播）；
2. **披露 + 不归因错** —— `messages` 必须点名 `±Inf` 数量，且不得出现"计算失败/共线性"
   这类**真实原因不是它**的提示（契约硬性要求 2：禁止错误归因）；
3. **机器可读** —— `metadata["boundary_codes"]` 必须带上 `E_DATA_NON_FINITE_DROPPED`。

## 披露口径说明（与同族 R2BD-02 的回归族修复一致）

多列按行清洗走 `_guard.clean_frame`，其文案是**按行**语义
（`⚠ 数据含 N 行 ±Inf（非有限值），已剔除后分析`）—— 该函数 docstring 明示它与
`clean_series` 的**单列**文案（点名列名）刻意不同，故本用例只断言
「数量 + `±Inf` 语义」，与 `tests/engine/test_regression_nonfinite_guard.py` 同口径。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause.modeling import vif_analysis

_N_INF = 3


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(干净帧, `x1` 含 3 个 `+Inf`, 直接删掉那 3 行) —— 后两者应给出同一结果。"""
    rng = np.random.default_rng(2026)
    n = 60
    x1 = rng.normal(0.0, 1.0, n)
    x2 = 0.6 * x1 + rng.normal(0.0, 0.8, n)
    x3 = rng.normal(0.0, 1.0, n)
    clean = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3})
    injected = clean.copy()
    injected.loc[: _N_INF - 1, "x1"] = np.inf
    return clean, injected, clean.iloc[_N_INF:].reset_index(drop=True)


def _run(frame: pd.DataFrame):
    """直接调引擎（不经 orchestrator 的兜底捕获）—— 让"异常逃出引擎"可断言。

    ⚠️ 显式放宽为 `simplefilter("default")`（**生产口径**）：`pyproject.toml` 的
    `filterwarnings = ["error"]` **只作用于 pytest**，而本用例要断言的是"生产下
    引擎不得给出错误归因/丢结果"。pytest 口径会把 `statsmodels`/`numpy` 内部告警
    升为异常，使执行在**产生文案之前**就中断 → 断言可能空过（假绿）。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        return vif_analysis(
            AnalysisRequest(
                task="vif",
                data=frame,
                target_col="",
                feature_cols=["x1", "x2", "x3"],
                params={},
            )
        )


def _vif_map(result) -> dict[str, float]:
    frame = result.tables["vif_table"]
    return {str(row["变量"]): float(row["VIF"]) for _, row in frame.iterrows()}


def test_feature_inf_is_cleaned_and_disclosed():
    """特征列的 3 个 `+Inf` 必须被清洗（而非拒绝）并**点名披露**。"""
    _clean, injected, _dropped = _frames()
    result = _run(injected)
    assert result.status == "ok", f"vif 未清洗 ±Inf（拒绝或崩溃）：messages={result.messages}"
    assert "vif_table" in result.tables, f"±Inf 路径下结果表全丢：{list(result.tables)}"
    blob = " ".join(result.messages)
    assert str(_N_INF) in blob and ("±Inf" in blob or "非有限值" in blob), (
        f"vif 未披露被剔除的 ±Inf 数量：{result.messages}"
    )
    assert "E_DATA_NON_FINITE_DROPPED" in result.metadata.get("boundary_codes", []), (
        f"vif 缺少机器可读错误码：{result.metadata.get('boundary_codes')}"
    )


def test_no_misattribution_to_collinearity_or_failure():
    """不得把 `±Inf` 归因成「VIF 计算失败/共线性」（禁止错误归因，契约硬性要求 2）。"""
    _clean, injected, _dropped = _frames()
    result = _run(injected)
    blob = " ".join(result.messages) + " " + str(result.summary)
    assert "计算失败" not in blob, f"vif 把 ±Inf 归因为计算失败：{blob}"
    assert "共线性" not in blob or "非有限" in blob, f"vif 把 ±Inf 归因为共线性：{blob}"
    assert "常量" not in blob, f"vif 把 ±Inf 归因为常量列：{blob}"


def test_cleaned_result_matches_dropped_rows():
    """真清洗判据：与"直接删掉那 3 行"**逐值一致**（不是凑出一个能跑的结果）。"""
    _clean, injected, dropped = _frames()
    result = _run(injected)
    reference = _run(dropped)
    assert reference.status == "ok", reference.messages
    got, want = _vif_map(result), _vif_map(reference)
    assert set(got) == set(want) == {"x1", "x2", "x3"}, (got, want)
    for col in want:
        assert got[col] == pytest.approx(want[col], rel=1e-12), (
            f"{col}: 清洗后 VIF={got[col]} 与删行基准={want[col]} 不一致"
        )


def test_nan_is_still_silent():
    """`NaN` 属缺失语义（契约 L4，免披露）—— 清洗不得把 `NaN` 也变成噪音。"""
    clean, _injected, _dropped = _frames()
    nan_frame = clean.copy()
    nan_frame.loc[: _N_INF - 1, "x1"] = np.nan
    result = _run(nan_frame)
    assert result.status == "ok", result.messages
    blob = " ".join(result.messages)
    assert "±Inf" not in blob and "非有限值" not in blob, (
        f"vif 对 NaN 产生非有限值披露（契约 L4 免披露）：{result.messages}"
    )
    assert result.metadata.get("boundary_codes", []) == [], (
        f"vif 对 NaN 记了边界错误码：{result.metadata.get('boundary_codes')}"
    )


def test_inf_leaving_too_few_rows_names_the_real_reason():
    """清洗后样本不足时，错误文案必须点名**真实原因**（`±Inf`），而不是只报"样本不足"。"""
    clean, _injected, _dropped = _frames()
    mostly_inf = clean.copy()
    mostly_inf.loc[: len(clean) - 3, "x1"] = np.inf  # 只剩 2 行有效（< len(cols)+2）
    result = _run(mostly_inf)
    assert result.status == "error", f"清洗后仅剩 2 行，应拒绝：{result.status}"
    blob = " ".join(result.messages)
    assert "±Inf" in blob or "非有限值" in blob, (
        f"样本不足的**真实原因是 ±Inf 被剔除**，文案却未点名：{result.messages}"
    )
