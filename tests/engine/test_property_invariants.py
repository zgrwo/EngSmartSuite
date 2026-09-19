"""属性测试（hypothesis）— 随机搜索核心统计不变量与历史 bug 模式。

覆盖 skill 陷阱 9（量纲缩放结论翻转）与 falsy 0（doe_design n_runs=0）：
- 量纲对抗：同一数据乘 1e-12~1e9 后 r/p/Cp/Cpk 与结论不变，控制限同比缩放；
- 数学不变量：p∈[0,1]、R²∈[0,1]、Cpk≤Cp、LCL≤CL≤UCL；
- 退化与 falsy：空/单行/常量/全 NaN 返回 error 不抛异常；n_runs=0 不得回退默认值。

常规确定性防线见 test_invariants.py / test_edge_cases.py；本文件仅补充随机搜索。

已知边界（2026-09-19 审查 E-2）：生成器保证非退化幅值下限，纯绝对兜底模式
（`scale = X if X > 1e-12 else 1.0`）不在本文件触发；该模式由
test_micro_scale_guards.py 的 pico 用例（xbar/nonparametric/trend）钉住。
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine import (
    correlation_analysis,
    process_capability_analysis,
    regression_analysis,
    xbar_r_chart,
)
from smartsuite.engine.doe_opt import doe_design

SETTINGS = settings(
    max_examples=25,
    deadline=None,
    derandomize=True,  # 固定种子：失败样本可跨机/跨 run 稳定复现（探索广度换确定性）
    suppress_health_check=[HealthCheck.too_slow],
)

_SCALES = st.sampled_from([1e-12, 1e-9, 1e-6, 1.0, 1e3, 1e9])
_FLOATS = st.floats(-1e4, 1e4, allow_nan=False, allow_infinity=False)
_UNIT_FLOATS = st.floats(-1.0, 1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _pair_frames(draw):
    """双变量数据：x 有离散度、y = 斜率·x + 噪声 + 斜坡 + 交替微扰，保证残差恒非退化。

    交替微扰项不可被 hypothesis 收缩掉（即使噪声/抖动全收缩为常数），
    避免落入完美拟合区——该区间 statsmodels 的 p 值处于机器精度噪声，
    不属于量纲不变量的有效检验范围（历史见 _breusch_pagan 完美拟合守卫）。
    """
    n = draw(st.integers(min_value=8, max_value=30))
    slope = draw(st.floats(-10.0, 10.0, allow_nan=False, allow_infinity=False))
    jitter = np.asarray(draw(st.lists(_UNIT_FLOATS, min_size=n, max_size=n)))
    noise = np.asarray(draw(st.lists(_UNIT_FLOATS, min_size=n, max_size=n)))
    ramp = np.linspace(-1.0, 1.0, n)
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    xs = ramp + 0.05 * jitter
    ys = slope * xs + 0.5 * noise + 0.25 * ramp + 0.05 * sign
    return pd.DataFrame({"x": xs, "y": ys})


@st.composite
def _value_series(draw):
    """单变量数据：叠加斜坡保证样本标准差 > 0。"""
    n = draw(st.integers(min_value=10, max_value=40))
    vals = np.asarray(draw(st.lists(_FLOATS, min_size=n, max_size=n))) + np.linspace(-1.0, 1.0, n)
    return pd.DataFrame({"v": vals})


@st.composite
def _grouped_frames(draw):
    """分组数据：组内斜坡保证极差 > 0，组间偏移保证子组均值互异（避免退化常量列）。"""
    k = draw(st.integers(min_value=5, max_value=10))
    base = np.asarray(draw(st.lists(_FLOATS, min_size=k * 3, max_size=k * 3))).reshape(k, 3)
    arr = base + np.linspace(-1.0, 1.0, 3)[None, :] + np.arange(k, dtype=float)[:, None]
    return pd.DataFrame({"x": np.repeat([f"g{i}" for i in range(k)], 3), "y": arr.ravel()})


@SETTINGS
@given(frame=_pair_frames(), scale=_SCALES)
def test_correlation_invariants_and_scale_invariance(frame, scale):
    base = correlation_analysis(
        AnalysisRequest(task="correlation", data=frame, target_col="y", feature_cols=["x"])
    )
    assert base.status == "ok", base.messages
    r0 = float(base.tables["correlation_matrix"].loc["y", "x"])
    p0 = float(base.tables["p_values_raw"].loc["y", "x"])
    assert -1.0 <= r0 <= 1.0, f"r 越界: {r0}"
    assert 0.0 <= p0 <= 1.0, f"p 越界: {p0}"

    scaled = correlation_analysis(
        AnalysisRequest(task="correlation", data=frame * scale, target_col="y", feature_cols=["x"])
    )
    assert scaled.status == "ok", scaled.messages
    assert float(scaled.tables["correlation_matrix"].loc["y", "x"]) == pytest.approx(r0, abs=1e-8)
    assert float(scaled.tables["p_values_raw"].loc["y", "x"]) == pytest.approx(p0, abs=1e-8)


@SETTINGS
@given(frame=_pair_frames(), scale=_SCALES)
def test_regression_invariants_and_scale_stability(frame, scale):
    base = regression_analysis(
        AnalysisRequest(task="regression", data=frame, target_col="y", feature_cols=["x"])
    )
    assert base.status == "ok", base.messages
    r2 = float(base.metadata["r_squared"])
    assert 0.0 <= r2 <= 1.0 + 1e-9, f"R² 越界: {r2}"
    p0 = np.asarray(base.tables["coefficients"]["p值"], dtype=float)
    assert np.all((p0 >= 0.0) & (p0 <= 1.0)), f"p 值越界: {p0}"

    scaled = regression_analysis(
        AnalysisRequest(task="regression", data=frame * scale, target_col="y", feature_cols=["x"])
    )
    assert scaled.status == "ok", scaled.messages
    assert float(scaled.metadata["r_squared"]) == pytest.approx(r2, abs=1e-8)
    p1 = np.asarray(scaled.tables["coefficients"]["p值"], dtype=float)
    assert p1 == pytest.approx(p0, abs=1e-5)


@SETTINGS
@given(frame=_value_series(), half_width=st.floats(0.5, 3.0), scale=_SCALES)
def test_process_capability_cpk_leq_cp_and_scale_invariance(frame, half_width, scale):
    mu = float(frame["v"].mean())
    sd = float(frame["v"].std(ddof=1))
    usl, lsl = mu + half_width * sd, mu - half_width * sd
    base = process_capability_analysis(
        AnalysisRequest(
            task="process_capability",
            data=frame,
            target_col="v",
            params={"usl": usl, "lsl": lsl},
        )
    )
    assert base.status == "ok", base.messages
    cp, cpk = float(base.metadata["cp"]), float(base.metadata["cpk"])
    assert cpk <= cp + 1e-9, f"Cpk>{cpk} 超过 Cp={cp}"

    scaled = process_capability_analysis(
        AnalysisRequest(
            task="process_capability",
            data=frame.assign(v=frame["v"] * scale),
            target_col="v",
            params={"usl": usl * scale, "lsl": lsl * scale},
        )
    )
    assert scaled.status == "ok", scaled.messages
    assert float(scaled.metadata["cp"]) == pytest.approx(cp, rel=1e-7, abs=1e-12)
    assert float(scaled.metadata["cpk"]) == pytest.approx(cpk, rel=1e-7, abs=1e-12)


@SETTINGS
@given(frame=_grouped_frames(), scale=_SCALES)
def test_xbar_limits_bracket_centerline_and_scale_equivariant(frame, scale):
    req = AnalysisRequest(task="spc_xbar", data=frame, target_col="y", feature_cols=["x"])
    base = xbar_r_chart(req)
    assert base.status == "ok", base.messages
    cl = float(base.metadata["xbar_mean"])
    ucl = float(base.metadata["ucl_x"])
    lcl = float(base.metadata["lcl_x"])
    assert lcl <= cl <= ucl, f"控制限未夹住中心线: LCL={lcl}, CL={cl}, UCL={ucl}"

    scaled = xbar_r_chart(
        AnalysisRequest(
            task="spc_xbar",
            data=frame.assign(y=frame["y"] * scale),
            target_col="y",
            feature_cols=["x"],
        )
    )
    assert scaled.status == "ok", scaled.messages
    assert float(scaled.metadata["ucl_x"]) == pytest.approx(ucl * scale, rel=1e-7, abs=1e-12)
    assert float(scaled.metadata["lcl_x"]) == pytest.approx(lcl * scale, rel=1e-7, abs=1e-12)


def test_degenerate_inputs_return_error_without_raising():
    """空/单行/常量/全 NaN 输入：优雅降级为中文 error，不抛异常。"""
    empty = pd.DataFrame({"x": pd.Series(dtype=float), "y": pd.Series(dtype=float)})
    single = pd.DataFrame({"x": [1.0], "y": [2.0]})
    constant = pd.DataFrame({"x": ["g1", "g1", "g1"], "y": [2.0, 2.0, 2.0]})
    nan_only = pd.DataFrame({"v": [np.nan, np.nan]})

    r = correlation_analysis(
        AnalysisRequest(task="correlation", data=empty, target_col="y", feature_cols=["x"])
    )
    assert r.status == "error" and r.messages, f"空数据未优雅降级: {r.status}"

    r = regression_analysis(
        AnalysisRequest(task="regression", data=single, target_col="y", feature_cols=["x"])
    )
    assert r.status == "error" and r.messages, f"单行数据未优雅降级: {r.status}"

    r = xbar_r_chart(
        AnalysisRequest(task="spc_xbar", data=constant, target_col="y", feature_cols=["x"])
    )
    assert r.status == "error" and "常量" in r.messages[0], f"常量列未识别: {r.messages}"

    r = process_capability_analysis(
        AnalysisRequest(
            task="process_capability",
            data=nan_only,
            target_col="v",
            params={"usl": 1.0, "lsl": -1.0},
        )
    )
    assert r.status == "error" and r.messages, f"全 NaN 未优雅降级: {r.status}"


def test_doe_design_zero_n_runs_not_silently_defaulted():
    """falsy 0 陷阱（历史 M-4）：n_runs=0 必须显式报错，不得回退 2**k 默认。"""
    factors = [{"name": f"F{i}", "levels": ["低", "高"]} for i in range(3)]
    zero = doe_design(
        AnalysisRequest(
            task="doe_design",
            data=pd.DataFrame(),
            params={"method": "fractional_factorial", "factors": factors, "n_runs": 0},
        )
    )
    assert zero.status == "error", f"n_runs=0 应报错: {zero.status}"
    assert "n_runs" in zero.messages[0] and "0" in zero.messages[0], zero.messages

    default = doe_design(
        AnalysisRequest(
            task="doe_design",
            data=pd.DataFrame(),
            params={"method": "fractional_factorial", "factors": factors},
        )
    )
    assert default.status == "ok", default.messages
    assert len(default.tables["design_matrix"]) == 8, "省略 n_runs 时应回退 2^3=8 行设计"
