"""numpy 标量的数值类型识别回归测试（审查 2026-09-19 E12 + 全仓同类排查）。

根因：`isinstance(x, (int, float))` 漏判 numpy 标量 —— numpy 2.x 起
`np.int64` / `np.float32` 等**不再是** int/float 子类（唯一例外 `np.float64`，
它是 float 子类，故原始报告"np.float64 走 str(x) 失真"的例证不成立）。
正确判据是 `numbers.Real`（覆盖 int/float/numpy 全系/Fraction，排除 str/None）。

**可达性核查（逐处验证，避免假阳性修复）**

| 位置 | 是否可达 | 依据 |
| :--- | :--- | :--- |
| `services/reporter.py::_fmt_html_cell` | ✅ **是** | `df.to_html(float_format=...)` 实测把 `np.float32` 传入（float64 亦然）→ HTML 报告把 float32 渲染成 `0.12345679`，与 Web/CLI 的 `0.1235` 不一致 |
| `engine/doe_opt/doe.py::_is_num` | ✅ **是** | Python API 传入 numpy 数值参数时被误判为非数值 |
| `engine/doe_opt/optimization.py` ranges 校验 | ✅ **是** | numpy 数值上下限被误拒为「上下限必须为数值」 |
| `services/audit.py` 导出数值分支 | ❌ 否 | `enumerate(Series)` 迭代产出 **Python** 标量（非 numpy），`isinstance` 本就通过 |
| `engine/inverse.py::_coerce_request_value` | ❌ 否 | 兜底 `return value` 与目标分支等价（行为无差异） |
| `engine/root_cause/distribution.py` CV 展示 | ❌ 否 | `desc["CV(%)"]` 已由 `round(float(...), 2)` 包装，恒为 Python float |
| `services/audit.py` 相关系数判定 | ❌ 否 | `metadata["target_correlations"]` 值已是 Python float |
| `engine/spc_charts/_shared.py` | ❌ 否 | 已用 `numbers.Number`（正确先例） |
"""

import numbers

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine.doe_opt import grid_search
from smartsuite.engine.doe_opt.doe import _is_num
from smartsuite.services.reporter import _fmt_html_cell, to_html

# ── 1. HTML 单元格格式化（可达：float_format 确实收到 np.float32）──


def test_fmt_html_cell_float32_is_scale_aware():
    """np.float32 必须与等值 Python float 同口径（修复前输出 8 位小数原文）。"""
    value = np.float32(0.12345679)
    assert _fmt_html_cell(value) == "0.1235", (
        f"float32 应走尺度感知格式化，实际 {_fmt_html_cell(value)!r}"
    )
    assert _fmt_html_cell(value) == _fmt_html_cell(0.12345679)


@pytest.mark.parametrize(
    "value",
    [
        np.float64(0.12345679),
        np.float32(0.12345679),
        np.float16(0.12345679),
        np.float64(7.0),
        # int 系经 to_html(float_format=) 不可达，此处仅作为类型一致性加固
        np.int64(7),
        np.int32(7),
        np.uint16(7),
    ],
)
def test_fmt_html_cell_matches_python_equivalent(value):
    """numpy 标量与其等值 Python 标量渲染必须一致。"""
    python_equivalent = value.item()
    assert _fmt_html_cell(value) == _fmt_html_cell(python_equivalent), (
        f"{type(value).__name__} 与 {type(python_equivalent).__name__} 渲染不一致: "
        f"{_fmt_html_cell(value)!r} != {_fmt_html_cell(python_equivalent)!r}"
    )


def test_fmt_html_cell_bool_stays_text():
    """bool ⊂ numbers.Real —— 扩类型时不得把布尔值变成 1.0000。"""
    assert _fmt_html_cell(True) == "True"
    assert _fmt_html_cell(False) == "False"
    assert _fmt_html_cell(np.bool_(True)) == "True"


@pytest.mark.parametrize("value", [np.float32("nan"), np.float32("inf"), np.float32("-inf")])
def test_fmt_html_cell_nonfinite_numpy_no_crash(value):
    """numpy 非有限值仍走原样输出，不得抛异常。"""
    assert _fmt_html_cell(value) in ("nan", "inf", "-inf")


def test_to_html_float32_column_uses_scale_aware_format(tmp_path):
    """端到端可达性证明：float32 列的 HTML 报告不得出现 8 位小数原文。"""
    result = AnalysisResult(
        task="distribution_summary",
        status="ok",
        summary="测试",
        tables={
            "t": pd.DataFrame({"微尺度": np.array([0.12345679, 0.98765432], dtype=np.float32)})
        },
    )
    out = to_html(result, str(tmp_path / "r.html"))
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert out and "0.1235" in html, "float32 列应渲染为 0.1235"
    assert "0.12345679" not in html, "不得泄漏 float32 原始精度"


# ── 2. 参数数值判定（可达：Python API 可传 numpy 数值）──


@pytest.mark.parametrize("value", [np.int64(1), np.int32(1), np.float32(1.5), np.float64(1.5)])
def test_is_num_accepts_numpy_scalars(value):
    """_is_num 用于 DOE 的 alpha / 因子水平校验：numpy 数值不得被误判为非数值。"""
    assert _is_num(value) is True


@pytest.mark.parametrize("value", [True, False, "1", None, "x"])
def test_is_num_rejects_non_numbers(value):
    """bool/str/None 仍须被拒（bool 必须排除，否则 True 会被当成数值 1）。"""
    assert _is_num(value) is False


# ── 3. grid_search ranges 校验（可达：numpy 数值上下限被误拒）──


def test_grid_search_accepts_numpy_range_bounds():
    """ranges 传入 numpy 整数上下限时不得误报「上下限必须为数值」。"""
    rng = np.random.default_rng(42)
    x1 = rng.uniform(-5, 5, 100)
    df = pd.DataFrame({"x1": x1, "y": 3.0 * x1 + rng.normal(0, 0.5, 100)})
    req = AnalysisRequest(
        task="grid_search",
        data=df,
        target_col="y",
        feature_cols=["x1"],
        params={
            "ranges": {"x1": (np.int64(-5), np.int64(5))},
            "n_points": 20,
            "direction": "maximize",
        },
    )
    result = grid_search(req)
    assert result.status == "ok", f"numpy 上下限应被接受: {result.messages}"
    assert result.metadata["optimal_params"]["x1"] > 2.0


def test_numbers_real_is_the_intended_predicate():
    """锁定判据本身：numbers.Real 覆盖 numpy 全系数值、排除 str/None。"""
    assert all(
        isinstance(v, numbers.Real)
        for v in (1, 1.5, np.int64(1), np.int32(1), np.float32(1.5), np.float64(1.5))
    )
    assert not any(isinstance(v, numbers.Real) for v in ("1", None, np.bool_(True)))
