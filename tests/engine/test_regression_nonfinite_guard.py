"""回归族（OLS / Lasso / 稳健）对 `±Inf` 的清洗与披露（审查 2026-10-09 R2BD-02，P1）。

缺陷形态（生产口径，目标列前 3 行注入 `+Inf`，其余 57 行正常）：

| 任务 | status | messages |
| :--- | :--- | :--- |
| `quantile_regression` | ok | `⚠ 数据含 3 行 ±Inf（非有限值），已剔除后分析` ✅ |
| **`lasso_regression`** | **RAISED(ValueError)** | — |
| **`robust_regression`** | error | `稳健回归拟合失败`（**无 ±Inf 披露**）|
| **`regression`** | error | `R² 计算为非有限值（数据可能为常量或退化），回归结果不可用`（**错误归因 + 无披露**）|

根因：`dropna()` **不剔除 ±Inf**（Inf 不是 NaN）—— `_guard.py` 模块 docstring 与
`skills/smartsuite-dev.md` 快速修复清单第 13 行已明文记录，但修复只落到了
同文件的 `quantile_regression`。文件级源码守卫（`test_input_cleanup_is_reported`）
因"同文件已有一个函数接了 `clean_frame`"而整文件放行，另 3 个函数结构上看不见。

判据（两条，缺一不可）：

1. **真清洗** —— 结果必须与"直接删掉那 3 行"逐值一致（不是拒绝、不是 NaN 传播）；
2. **披露 + 不归因错** —— `messages` 必须点名 ±Inf 数量，且**不得**出现"常量/退化"
   （真实原因是非有限值，不是常量列 —— 契约硬性要求 2：禁止错误归因）。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt.regression import (
    lasso_regression,
    regression_analysis,
    robust_regression,
)

#: 三个函数的调用入口与各自的 `task` 名
_FUNCS = {
    "regression": regression_analysis,
    "lasso_regression": lasso_regression,
    "robust_regression": robust_regression,
}


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(干净帧, 目标列含 3 个 +Inf, 直接删掉那 3 行) —— 三者应给出同一结果。"""
    rng = np.random.default_rng(3)
    x1 = rng.uniform(1, 10, 60)
    x2 = rng.uniform(0, 1, 60)
    y = 1 + 0.5 * x1 + 2.0 * x2 + 0.05 * rng.standard_normal(60)
    clean = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
    injected = clean.copy()
    injected.loc[:2, "y"] = np.inf
    return clean, injected, clean.iloc[3:].reset_index(drop=True)


def _run(task: str, frame: pd.DataFrame):
    """直接调引擎（不经 orchestrator 的兜底捕获）—— 让"异常逃出引擎"可断言。"""
    with warnings.catch_warnings():
        # 生产口径：`pyproject.toml` 的 filterwarnings=["error"] **只作用于 pytest**，
        # 而本用例要断言的是"生产下引擎不得给出错误结论"。pytest 口径会把
        # statsmodels 的 `invalid value encountered` 升为异常，执行在产生结论之前
        # 就中断 → 断言恒真（空过/假绿，见该轮报告 §三 的口径分歧实测）。
        warnings.simplefilter("default")
        return _FUNCS[task](
            AnalysisRequest(
                task=task,
                data=frame,
                target_col="y",
                feature_cols=["x1", "x2"],
                params={},
            )
        )


@pytest.mark.parametrize("task", sorted(_FUNCS))
def test_target_inf_is_cleaned_and_disclosed(task):
    """目标列的 3 个 +Inf 必须被清洗（而非拒绝/传播）并**点名披露**。"""
    _clean, injected, dropped = _frames()
    result = _run(task, injected)
    assert result.status == "ok", f"{task} 未清洗 ±Inf（拒绝或崩溃）：messages={result.messages}"
    blob = " ".join(result.messages)
    assert "3" in blob and ("±Inf" in blob or "非有限值" in blob), (
        f"{task} 未披露被剔除的 ±Inf 数量与列名：{result.messages}"
    )
    assert "E_DATA_NON_FINITE_DROPPED" in result.metadata.get("boundary_codes", []), (
        f"{task} 缺少机器可读错误码：{result.metadata.get('boundary_codes')}"
    )
    # 真清洗判据：与"直接删掉那 3 行"同解（不是凑出一个能跑的结果）
    reference = _run(task, dropped)
    assert reference.status == "ok", reference.messages
    assert result.metadata["n_samples"] == reference.metadata["n_samples"] == 57, (
        f"{task} 清洗后样本量应回到 57：{result.metadata.get('n_samples')} vs "
        f"{reference.metadata.get('n_samples')}"
    )


@pytest.mark.parametrize("task", sorted(_FUNCS))
def test_no_misattribution_to_constant_column(task):
    """不得把 ±Inf 归因成「常量/退化」（契约硬性要求 2：禁止错误归因）。"""
    _clean, injected, _dropped = _frames()
    result = _run(task, injected)
    blob = " ".join(result.messages) + str(result.summary)
    assert "常量" not in blob, f"{task} 把 ±Inf 归因为常量列：{blob}"
    assert "退化" not in blob or "非有限" in blob, f"{task} 归因文案指向「退化」：{blob}"


@pytest.mark.parametrize("task", sorted(_FUNCS))
def test_feature_inf_is_cleaned_and_disclosed(task):
    """特征列的 ±Inf 同样必须清洗 —— 原实现把它喂给 sklearn/statsmodels 后抛错。"""
    clean, _injected, dropped = _frames()
    injected = clean.copy()
    injected.loc[:2, "x1"] = np.inf
    result = _run(task, injected)
    assert result.status == "ok", f"{task} 未清洗特征列 ±Inf：messages={result.messages}"
    blob = " ".join(result.messages)
    assert "±Inf" in blob or "非有限值" in blob, f"{task} 未披露特征列 ±Inf：{result.messages}"
    assert result.metadata["n_samples"] == _run(task, dropped).metadata["n_samples"] == 57


def test_nan_is_still_silent_for_regression_family():
    """NaN 属缺失语义（契约 L4，免披露）—— 清洗不得把 NaN 也变成噪音。"""
    clean, _injected, _dropped = _frames()
    nan_frame = clean.copy()
    nan_frame.loc[:2, "y"] = np.nan
    for task in sorted(_FUNCS):
        result = _run(task, nan_frame)
        assert result.status == "ok", (task, result.messages)
        blob = " ".join(result.messages)
        assert "±Inf" not in blob and "非有限值" not in blob, (
            f"{task} 对 NaN 产生非有限值披露（契约 L4 免披露）：{result.messages}"
        )
        assert result.metadata.get("boundary_codes", []) == [], (
            f"{task} 对 NaN 记了边界错误码：{result.metadata.get('boundary_codes')}"
        )


def test_lasso_does_not_raise_on_inf():
    """Lasso 的 `ValueError: Input y contains infinity` 必须被入口清洗挡掉（红线）。"""
    _clean, injected, _dropped = _frames()
    result = _run("lasso_regression", injected)  # 不抛异常即为通过（其余断言见上）
    assert result.status == "ok", result.messages
    assert np.isfinite(float(result.metadata["r_squared"]))
