import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import qmc  # noqa: F401  (仅注释性引用，实际使用在引擎内)

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine._constants import INVERSE_LAM_TIME
from smartsuite.engine.inverse import (
    _build_model_equations,
    _raw_linear_coefficients,
    _fit_forward,
    _fit_rate_forward,
    inverse_parameter_solve,
    _optimal_time,
    _pair_incoming_output,
    _reachable_range,
    _resolve_bounds,
    _resolve_roles,
    _solve_one,
    _split_rows,
)


def test_resolve_roles_auto_prefix():
    df = pd.DataFrame(
        {
            "IncomingA": [1.0],
            "IncomingB": [2.0],
            "VariableU1": [3.0],
            "FixedT": [4.0],
            "OutputY1": [5.0],
        }
    )
    roles = _resolve_roles(df, {})
    assert roles.incoming == ["IncomingA", "IncomingB"]
    assert roles.variable == ["VariableU1"]
    assert roles.fixed == ["FixedT"]
    assert roles.output == ["OutputY1"]


def test_resolve_roles_param_override_and_chinese_prefix():
    df = pd.DataFrame({"来料A": [1.0], "可调U": [2.0], "输出Y": [3.0]})
    roles = _resolve_roles(df, {"incoming_cols": "来料A"})
    assert roles.incoming == ["来料A"]
    assert roles.variable == ["可调U"]
    assert roles.output == ["输出Y"]


def test_resolve_roles_missing_output_raises_chinese():
    df = pd.DataFrame({"IncomingA": [1.0]})
    try:
        _resolve_roles(df, {})
    except ValueError as exc:
        assert "输出" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应抛出中文错误")


def test_split_rows_history_and_request():
    df = pd.DataFrame(
        {
            "IncomingA": [1.1, 1.2, 1.3],
            "VariableU1": [5.0, 6.0, None],
            "OutputY1": [0.9, 0.8, 0.7],
        }
    )
    roles = _resolve_roles(df, {})
    history, requests, skipped = _split_rows(df, roles)
    assert len(history) == 2
    assert len(requests) == 1
    assert skipped == []
    assert requests.iloc[0]["OutputY1"] == 0.7


def test_split_rows_target_only_row_is_request():
    """C-1：目标写在 target 角色列、输出列留空的行也必须判为请求行。"""
    df = pd.DataFrame(
        {
            "IncomingA": [1.1, 1.2, 1.3],
            "VariableU1": [5.0, 6.0, None],
            "OutputY1": [0.9, 0.8, None],
            "TargetY1": [None, None, 0.7],
        }
    )
    roles = _resolve_roles(df, {})
    assert roles.target == ["TargetY1"]
    history, requests, skipped = _split_rows(df, roles)
    assert len(history) == 2
    assert len(requests) == 1
    assert skipped == []
    assert requests.iloc[0]["TargetY1"] == 0.7

    no_target = df.drop(columns=["TargetY1"])
    history2, requests2, skipped2 = _split_rows(no_target, _resolve_roles(no_target, {}))
    assert len(requests2) == 0
    assert any("缺少输出值或目标值" in reason for _, reason in skipped2)


def _linear_history(n=40, seed=0):
    rng = np.random.default_rng(seed)
    inc = rng.normal(1.1, 0.05, n)
    u1 = rng.uniform(4, 8, n)
    u2 = rng.uniform(2, 4, n)
    y1 = 1.3 - 0.06 * u1 + 0.05 * inc
    y2 = 0.9 - 0.04 * u2
    return pd.DataFrame(
        {
            "IncomingA": inc,
            "VariableU1": u1,
            "VariableU2": u2,
            "OutputY1": y1,
            "OutputY2": y2,
        }
    )


def test_fit_forward_auto_selects_and_predicts():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, quality = _fit_forward(df, roles, model="auto", random_state=42)
    assert len(forward.feature_cols) == 3
    assert quality["Output"].unique().tolist() == ["OutputY1", "OutputY2"]
    assert len(quality) == 8  # 2 输出 × 4 候选（spec §4.5 全候选对比表）
    sel = quality[quality["选用"]]
    assert sel["Output"].tolist() == ["OutputY1", "OutputY2"]
    assert sel["CV_R2"].min() > 0.8
    pred = forward.predict(df[forward.feature_cols].head(3))
    assert pred.shape == (3, 2)


def test_fit_forward_fixed_model():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, quality = _fit_forward(df, roles, model="linear", random_state=42)
    assert forward.choice == ["linear", "linear"]
    assert not forward.has_tree
    assert len(quality) == 2


def _rate_history(n=40, seed=1):
    rng = np.random.default_rng(seed)
    inc = rng.normal(1.1, 0.05, n)
    u = rng.uniform(4, 8, n)
    t = rng.uniform(45, 90, n)
    rate = 0.002 + 0.0004 * u
    y = inc - rate * t
    return pd.DataFrame({"IncomingZ1": inc, "VariableU1": u, "FixedTime": t, "OutputZ1": y})


def test_pair_incoming_output_by_suffix():
    assert _pair_incoming_output(["IncomingZ1", "IncomingZ2"], ["OutputZ1", "OutputZ2"]) == [
        ("IncomingZ1", "OutputZ1"),
        ("IncomingZ2", "OutputZ2"),
    ]


def test_fit_rate_forward_recovers_output():
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    fwd, quality = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.pairing_note is None
    assert quality.loc[quality["选用"], "CV_R2"].min() > 0.8
    row = df.iloc[0]
    pred = fwd.predict_output(row.to_dict(), {"VariableU1": 5.0}, time=60.0)
    assert pred.shape == (1,)


def test_rate_requires_time_col():
    df = _rate_history().drop(columns=["FixedTime"])
    roles = _resolve_roles(df, {})
    try:
        _fit_rate_forward(df, roles, None, random_state=42)
    except ValueError as exc:
        assert "time" in str(exc).lower() or "时间" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺时间列应报错")


def test_rate_forward_predict_rate_matches_physics():
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    fwd, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.uses_time and not fwd.has_tree
    rate = fwd.predict_rate(df.iloc[0].to_dict(), {"VariableU1": 5.0})
    assert rate.shape == (1,)
    assert abs(rate[0] - (0.002 + 0.0004 * 5.0)) < 1e-6


def test_fit_rate_forward_records_pairing_fallback():
    df = _rate_history().rename(columns={"IncomingZ1": "IncomingA", "OutputZ1": "OutputY"})
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    fwd, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.pairing_note is not None
    assert "配对" in fwd.pairing_note
    assert "共用" in fwd.pairing_note
    assert "IncomingA→OutputY" in fwd.pairing_note


def test_fit_rate_forward_skips_row_with_nan_rate_feature(caplog):
    df = _rate_history()
    df["IncomingZ2"] = np.linspace(0.5, 0.9, len(df))
    df.loc[0, "IncomingZ2"] = np.nan
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fwd, quality = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert not quality.empty
    assert quality.loc[quality["选用"], "CV_R2"].min() > 0.8
    assert any("剔除" in r.message for r in caplog.records)
    complete = df.dropna().iloc[0]
    pred = fwd.predict_output(complete.to_dict(), {"VariableU1": 5.0}, time=60.0)
    assert pred.shape == (1,)


def test_fit_rate_forward_all_zero_time_raises_chinese():
    df = _rate_history()
    df["FixedTime"] = 0.0
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    try:
        _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    except ValueError as exc:
        assert "时间" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("时间全为 0 应报错")


def test_solve_one_recovers_known_parameters():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    bounds = _resolve_bounds(df, roles, {})
    incoming = {"IncomingA": 1.1}
    target = np.array([1.3 - 0.06 * 5.0 + 0.05 * 1.1, 0.9 - 0.04 * 3.0])
    scale = df[roles.output].std().to_numpy()
    u, pred, info = _solve_one(
        forward,
        incoming,
        target,
        scale,
        np.ones(2),
        bounds,
        df[roles.variable].median().to_dict(),
        {"random_state": 42},
    )
    assert abs(u["VariableU1"] - 5.0) < 0.1
    assert abs(u["VariableU2"] - 3.0) < 0.1
    assert all(info["at_bound"][k] in (True, False) for k in u)


def test_solve_one_deterministic():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    args = (
        forward,
        {"IncomingA": 1.1},
        np.array([0.98, 0.78]),
        df[roles.output].std().to_numpy(),
        np.ones(2),
        _resolve_bounds(df, roles, {}),
        df[roles.variable].median().to_dict(),
        {"random_state": 42},
    )
    u1, _, _ = _solve_one(*args)
    u2, _, _ = _solve_one(*args)
    assert u1 == u2


def test_optimal_time_analytic():
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    forward, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    t = _optimal_time(
        forward,
        {"IncomingZ1": 1.1, "FixedTime": 60.0},
        np.array([1.1 - 0.004 * 60]),
        np.array([0.02]),
        np.ones(1),
        {"VariableU1": 5.0},
        (30.0, 120.0),
    )
    assert 30.0 <= t <= 120.0


class _StubRateForward:
    """最小 duck-typing 速率模型：r = intercept + slope·VariableU1。"""

    uses_time = True
    has_tree = False
    time_col = "FixedTime"

    def __init__(self, intercept=0.002, slope=0.0004):
        self.intercept = intercept
        self.slope = slope

    def predict_rate(self, incoming, u):
        return np.array([self.intercept + self.slope * float(u["VariableU1"])])

    def predict_output(self, incoming, u, time):
        rate = self.predict_rate(incoming, u)[0]
        return np.array([float(incoming["IncomingZ1"]) - rate * float(time)])


def test_optimal_time_weight_scaling():
    forward = _StubRateForward()
    incoming = {"IncomingZ1": 1.1, "FixedTime": 60.0}
    target = np.array([0.94])
    scale = np.array([0.02])
    weights = np.array([4.0])
    u = {"VariableU1": 5.0}
    t = _optimal_time(forward, incoming, target, scale, weights, u, (40.0, 60.0))
    a_ = (1.1 - 0.94) / 0.02
    b_ = (0.002 + 0.0004 * 5.0) / 0.02
    c_ = INVERSE_LAM_TIME / (60.0 - 40.0) ** 2
    expected = (4.0 * b_ * a_ + c_ * 60.0) / (4.0 * b_ * b_ + c_)
    unweighted = (b_ * a_ + c_ * 60.0) / (b_ * b_ + c_)
    assert t == pytest.approx(expected, rel=1e-9)
    assert t != pytest.approx(unweighted, rel=1e-6)


def test_optimal_time_uses_incoming_time_anchor(caplog):
    forward = _StubRateForward()
    target = np.array([0.94])
    scale = np.array([0.02])
    weights = np.array([1.0])
    u = {"VariableU1": 5.0}
    anchored = _optimal_time(
        forward, {"IncomingZ1": 1.1, "FixedTime": 60.0}, target, scale, weights, u, (40.0, 60.0)
    )
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fallback = _optimal_time(
            forward, {"IncomingZ1": 1.1}, target, scale, weights, u, (40.0, 60.0)
        )
    assert any("回退时间区间中点" in r.message for r in caplog.records)
    a_ = (1.1 - 0.94) / 0.02
    b_ = (0.002 + 0.0004 * 5.0) / 0.02
    c_ = INVERSE_LAM_TIME / (60.0 - 40.0) ** 2
    expected_anchored = (b_ * a_ + c_ * 60.0) / (b_ * b_ + c_)
    expected_fallback = (b_ * a_ + c_ * 50.0) / (b_ * b_ + c_)
    assert anchored == pytest.approx(expected_anchored, rel=1e-9)
    assert fallback == pytest.approx(expected_fallback, rel=1e-9)
    assert anchored != pytest.approx(fallback)


def test_solve_one_gbm_uses_differential_evolution():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="gbm", random_state=42)
    incoming = {"IncomingA": 1.1}
    known = {"VariableU1": 5.0, "VariableU2": 3.0}
    target = np.ravel(forward.predict(pd.DataFrame([{**incoming, **known}])))
    scale = df[roles.output].std().to_numpy()
    baseline = df[roles.variable].median().to_dict()
    baseline_pred = np.ravel(forward.predict(pd.DataFrame([{**incoming, **baseline}])))
    u, pred, info = _solve_one(
        forward,
        incoming,
        target,
        scale,
        np.ones(2),
        _resolve_bounds(df, roles, {}),
        baseline,
        {"random_state": 42},
    )
    assert "differential" in info["method"].lower()
    assert np.isfinite(pred).all()
    assert all(np.isfinite(value) for value in u.values())
    assert abs(u["VariableU1"] - 5.0) < 0.5
    assert abs(u["VariableU2"] - 3.0) < 0.5
    baseline_sigma = np.abs((baseline_pred - target) / scale)
    solved_sigma = np.abs(info["residual_sigma"])
    assert solved_sigma.max() < baseline_sigma.max()


def test_resolve_bounds_explicit_override_invalid_fallback_and_zero_width(caplog):
    df = _linear_history()
    roles = _resolve_roles(df, {})
    explicit = _resolve_bounds(
        df,
        roles,
        {"variable_bounds": '{"VariableU1": [4.5, 6.5], "VariableU2": [2.5, 3.5]}'},
    )
    assert explicit["VariableU1"] == (4.5, 6.5)
    assert explicit["VariableU2"] == (2.5, 3.5)
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fallback = _resolve_bounds(df, roles, {"variable_bounds": "{不是合法JSON"})
    assert any("JSON" in r.message for r in caplog.records)
    assert fallback["VariableU1"] == (
        float(df["VariableU1"].min()),
        float(df["VariableU1"].max()),
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        constant = _resolve_bounds(df, roles, {"variable_bounds": {"VariableU1": [5.0, 5.0]}})
    assert constant["VariableU1"] == (5.0, 5.0)
    assert any("宽度为 0" in r.message for r in caplog.records)


def test_reachable_range_contains_solution_and_widens_with_time():
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    forward, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    bounds = _resolve_bounds(df, roles, {})
    lo, hi = _reachable_range(
        forward, {"IncomingZ1": 1.1}, bounds, n=1024, seed=0, time_bounds=(30.0, 120.0)
    )
    assert (hi > lo).all()
    assert lo.shape == (1,)


def test_reachable_range_extracts_time_from_bounds():
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    forward, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    bounds = _resolve_bounds(
        df, roles, {"time_adjustable": "true", "time_min": 30, "time_max": 120}
    )
    assert "FixedTime" in bounds
    incoming = {"IncomingZ1": 1.1, "FixedTime": 60.0}
    lo_auto, hi_auto = _reachable_range(forward, incoming, bounds, n=1024, seed=0)
    lo_exp, hi_exp = _reachable_range(
        forward, incoming, bounds, n=1024, seed=0, time_bounds=(30.0, 120.0)
    )
    assert np.array_equal(lo_auto, lo_exp)
    assert np.array_equal(hi_auto, hi_exp)
    fixed_bounds = {k: v for k, v in bounds.items() if k != "FixedTime"}
    lo_fixed, hi_fixed = _reachable_range(
        forward, {"IncomingZ1": 1.1, "FixedTime": 60.0}, fixed_bounds, n=1024, seed=0
    )
    assert np.all(hi_auto - lo_auto > hi_fixed - lo_fixed)


def test_reachable_range_forward_contains_solved_solution_and_is_deterministic():
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    bounds = _resolve_bounds(df, roles, {})
    incoming = {"IncomingA": 1.1}
    target = np.array([1.3 - 0.06 * 5.0 + 0.05 * 1.1, 0.9 - 0.04 * 3.0])
    scale = df[roles.output].std().to_numpy()
    _, pred, _ = _solve_one(
        forward,
        incoming,
        target,
        scale,
        np.ones(2),
        bounds,
        df[roles.variable].median().to_dict(),
        {"random_state": 42},
    )
    lo, hi = _reachable_range(forward, incoming, bounds, n=1024, seed=7)
    lo2, hi2 = _reachable_range(forward, incoming, bounds, n=1024, seed=7)
    assert lo.shape == (2,)
    assert (lo <= pred).all()
    assert (pred <= hi).all()
    assert np.array_equal(lo, lo2)
    assert np.array_equal(hi, hi2)
    constant = _resolve_bounds(
        df, roles, {"variable_bounds": {"VariableU1": [5.0, 5.0], "VariableU2": [3.0, 3.0]}}
    )
    lo_c, hi_c = _reachable_range(forward, incoming, constant, n=256, seed=7)
    assert np.allclose(lo_c, hi_c)


def _e2e_frame(n=40, seed=2):
    hist = _linear_history(n=n, seed=seed)
    req = pd.DataFrame(
        {
            "IncomingA": [1.15],
            "VariableU1": [None],
            "VariableU2": [None],
            "OutputY1": [1.3 - 0.06 * 5.5 + 0.05 * 1.15],
            "OutputY2": [0.9 - 0.04 * 2.5],
        }
    )
    return pd.concat([hist, req], ignore_index=True)


def test_inverse_solve_end_to_end():
    df = _e2e_frame()
    req = AnalysisRequest(
        task="inverse_solve",
        data=df,
        target_col="",
        feature_cols=[],
        params={"model": "linear", "random_state": 42},
    )
    result = inverse_parameter_solve(req)
    assert result.status == "ok"
    assert set(result.tables) == {
        "recommendations",
        "predictions",
        "model_quality",
        "reachable_ranges",
        "model_equations",
    }
    assert len(result.tables["recommendations"]) == 1
    assert len(result.figures) >= 2
    assert "反解" in result.summary


def test_inverse_solve_fit_only_and_errors():
    hist = _linear_history()
    req = AnalysisRequest(
        task="inverse_solve", data=hist, target_col="", feature_cols=[], params={"model": "linear"}
    )
    assert inverse_parameter_solve(req).status == "ok"
    bad = AnalysisRequest(
        task="inverse_solve",
        data=pd.DataFrame({"A": [1.0]}),
        target_col="",
        feature_cols=[],
        params={},
    )
    result = inverse_parameter_solve(bad)
    assert result.status == "error" and result.messages


def _variable_time_history(n=40, seed=3):
    rng = np.random.default_rng(seed)
    inc = rng.normal(1.1, 0.05, n)
    t = rng.uniform(45, 90, n)
    u1 = rng.uniform(4, 8, n)
    y = 1.3 - 0.06 * u1 + 0.05 * inc - 0.001 * t
    return pd.DataFrame({"IncomingA": inc, "VariableTime": t, "VariableU1": u1, "OutputY1": y})


def _variable_time_frame():
    hist = _variable_time_history()
    req = pd.DataFrame(
        {"IncomingA": [1.1], "VariableTime": [None], "VariableU1": [None], "OutputY1": [1.0]}
    )
    return pd.concat([hist, req], ignore_index=True)


def test_time_adjustable_false_does_not_optimize_variable_time():
    hist = _variable_time_history()
    roles = _resolve_roles(hist, {"time_col": "VariableTime"})
    bounds = _resolve_bounds(hist, roles, {"time_col": "VariableTime", "time_adjustable": "false"})
    assert "VariableTime" not in bounds
    assert "VariableU1" in bounds
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=_variable_time_frame(),
            target_col="",
            feature_cols=[],
            params={"model": "linear", "time_col": "VariableTime", "time_adjustable": "false"},
        )
    )
    assert result.status == "ok"
    assert result.metadata["time_adjustable"] is False
    rec = result.tables["recommendations"]
    assert len(rec) == 1
    median = float(hist["VariableTime"].median())
    assert rec.iloc[0]["VariableTime"] == pytest.approx(median, abs=1e-9)
    assert any("不可调" in message for message in result.messages)


def test_time_adjustable_true_includes_variable_time():
    hist = _variable_time_history()
    roles = _resolve_roles(hist, {"time_col": "VariableTime"})
    bounds = _resolve_bounds(
        hist,
        roles,
        {"time_col": "VariableTime", "time_adjustable": "true", "time_min": 30, "time_max": 120},
    )
    assert bounds["VariableTime"] == (30.0, 120.0)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=_variable_time_frame(),
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "time_col": "VariableTime",
                "time_adjustable": "true",
                "time_min": 30,
                "time_max": 120,
            },
        )
    )
    assert result.status == "ok"
    assert result.metadata["time_adjustable"] is True
    rec = result.tables["recommendations"]
    assert len(rec) == 1
    assert 30.0 <= rec.iloc[0]["VariableTime"] <= 120.0
    assert abs(rec.iloc[0]["VariableU1"] - 5.0) < 0.5


def test_inverse_solve_all_requests_fail_summary():
    hist = _variable_time_history()
    req = pd.DataFrame(
        {"IncomingA": [1.1], "VariableTime": [None], "VariableU1": [None], "OutputY1": [1.0]}
    )
    df = pd.concat(
        [hist.drop(columns=["VariableU1"]), req.drop(columns=["VariableU1"])], ignore_index=True
    )
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "time_col": "VariableTime", "time_adjustable": "false"},
        )
    )
    assert result.status == "ok"
    assert len(result.tables["recommendations"]) == 0
    assert "均未能求解" in result.summary
    assert "未检测到请求行" not in result.summary
    assert any("反解失败" in message for message in result.messages)


def test_inverse_solve_accepts_request_rows_list():
    """Web UI 表格录入的请求行经 params.request_rows 传入，无需数据中留空行。"""
    hist = _linear_history()
    rows = [
        {
            "IncomingA": 1.15,
            "OutputY1": 1.3 - 0.06 * 5.5 + 0.05 * 1.15,
            "OutputY2": 0.9 - 0.04 * 2.5,
        }
    ]
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42, "request_rows": rows},
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_history"] == len(hist)
    assert result.metadata["n_request"] == 1
    rec = result.tables["recommendations"]
    assert len(rec) == 1
    assert abs(rec.iloc[0]["VariableU1"] - 5.5) < 0.5
    assert any("已追加" in message for message in result.messages)


def test_inverse_solve_request_rows_json_and_string_numbers():
    """request_rows 支持 JSON 字符串与字符串数值（前端序列化路径）。"""
    hist = _linear_history()
    rows = json.dumps(
        [
            {
                "IncomingA": "1.15",
                "OutputY1": str(1.3 - 0.06 * 5.5 + 0.05 * 1.15),
                "OutputY2": "0.8",
            }
        ]
    )
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42, "request_rows": rows},
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_request"] == 1
    assert len(result.tables["recommendations"]) == 1


def test_inverse_solve_role_cols_as_lists():
    """前端勾选组以列表下发列角色（_split_param_cols 列表分支 + 请求行录入）。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "incoming_cols": ["IncomingA"],
                "variable_cols": ["VariableU1", "VariableU2"],
                "output_cols": ["OutputY1", "OutputY2"],
                "request_rows": [
                    {
                        "IncomingA": 1.15,
                        "OutputY1": 1.3 - 0.06 * 5.5 + 0.05 * 1.15,
                        "OutputY2": 0.8,
                    }
                ],
            },
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_request"] == 1
    rec = result.tables["recommendations"]
    assert len(rec) == 1
    assert abs(rec.iloc[0]["VariableU2"] - 2.5) < 0.5


def test_inverse_solve_target_only_request_row():
    """C-1：目标列（target_cols）独立通道端到端可用（输出列留空）。"""
    hist = _linear_history()
    req = pd.DataFrame(
        {
            "IncomingA": [1.15],
            "VariableU1": [None],
            "VariableU2": [None],
            "OutputY1": [None],
            "OutputY2": [None],
            "TargetY1": [1.3 - 0.06 * 5.5 + 0.05 * 1.15],
            "TargetY2": [0.9 - 0.04 * 2.5],
        }
    )
    df = pd.concat([hist, req], ignore_index=True)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42},
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_request"] == 1
    rec = result.tables["recommendations"]
    assert len(rec) == 1
    assert abs(rec.iloc[0]["VariableU1"] - 5.5) < 0.5
    assert abs(rec.iloc[0]["VariableU2"] - 2.5) < 0.5


def test_inverse_solve_partial_target_missing_counts_failed_request():
    """N-6：请求行只提供部分目标 → 失败分支计数 + 中文消息，不静默出结果。"""
    hist = _linear_history()
    req = pd.DataFrame(
        {
            "IncomingA": [1.15],
            "VariableU1": [None],
            "VariableU2": [None],
            "OutputY1": [None],
            "OutputY2": [None],
            "TargetY1": [1.3 - 0.06 * 5.5 + 0.05 * 1.15],
            "TargetY2": [None],
        }
    )
    df = pd.concat([hist, req], ignore_index=True)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42},
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_request"] == 1
    assert result.metadata["n_failed_requests"] == 1
    assert (
        result.metadata["n_skipped"]
        == result.metadata["n_skipped_rows"] + result.metadata["n_failed_requests"]
    )
    assert any(
        "请求行" in message and "目标缺失或无效" in message and "OutputY2" in message
        for message in result.messages
    )
    assert result.tables["recommendations"].empty


def test_inverse_solve_request_rows_invalid_and_unknown_columns():
    """request_rows 非法结构 → 中文报错；未知列忽略并提示。"""
    hist = _linear_history()
    bad = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "request_rows": ["bad"]},
        )
    )
    assert bad.status == "error"
    assert any("request_rows" in message for message in bad.messages)
    for invalid in ("{不是JSON", {"列": 1}):
        result = inverse_parameter_solve(
            AnalysisRequest(
                task="inverse_solve",
                data=hist,
                target_col="",
                feature_cols=[],
                params={"model": "linear", "request_rows": invalid},
            )
        )
        assert result.status == "error"
        assert any("request_rows" in message for message in result.messages)
    unknown = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "request_rows": [
                    {
                        "IncomingA": 1.15,
                        "OutputY1": 1.0,
                        "OutputY2": 0.8,
                        "不存在列": 1,
                    }
                ],
            },
        )
    )
    assert unknown.status == "ok"
    assert any("已忽略" in message for message in unknown.messages)


def test_inverse_solve_request_rows_bool_rejected():
    """C-3：布尔取值显式失败（不得静默按 1/0 参与反解）。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "request_rows": [{"IncomingA": 1.15, "OutputY1": True}]},
        )
    )
    assert result.status == "error"
    assert any("布尔" in message for message in result.messages)


def test_raw_linear_coefficients_match_raw_ols():
    """原始单位系数换算与直接 OLS 拟合一致（方程与模型预测同源）。"""
    from sklearn.linear_model import LinearRegression

    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    raw_model = LinearRegression().fit(df[forward.feature_cols], df["OutputY1"])
    intercept, coefs = _raw_linear_coefficients(forward.models[0])
    assert intercept == pytest.approx(float(raw_model.intercept_), rel=1e-9, abs=1e-9)
    assert np.allclose(coefs, raw_model.coef_, rtol=1e-9, atol=1e-9)


def test_build_model_equations_linear_forward_and_inverse():
    """线性模型：前向方程含各可调参数项，反解公式逐参数逐输出给出。"""
    df = _linear_history()
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    bounds = _resolve_bounds(df, roles, {})
    table = _build_model_equations(forward, roles, bounds, {"reg_lambda": 0.02}, "std")
    assert list(table.columns) == ["类型", "对象", "表达式", "说明"]
    forward_rows = table[table["类型"] == "前向方程"]
    assert forward_rows["对象"].tolist() == ["OutputY1", "OutputY2"]
    first = forward_rows.iloc[0]["表达式"]
    assert first.startswith("OutputY1 = ") and "IncomingA" in first and "VariableU1" in first
    inverse_rows = table[table["类型"] == "反解公式"]
    assert set(inverse_rows["对象"]) == {
        "OutputY1 → VariableU1",
        "OutputY1 → VariableU2",
        "OutputY2 → VariableU1",
        "OutputY2 → VariableU2",
    }
    example = inverse_rows[inverse_rows["对象"] == "OutputY1 → VariableU1"].iloc[0]["表达式"]
    assert example.startswith("VariableU1 = (目标OutputY1 − ")
    zero_row = inverse_rows[inverse_rows["对象"] == "OutputY1 → VariableU2"].iloc[0]
    assert zero_row["表达式"] == "—" and "量级可忽略" in zero_row["说明"]
    objective = table[table["类型"] == "优化目标"]
    assert len(objective) == 1 and "λ" in objective.iloc[0]["表达式"]


def test_build_model_equations_poly_and_gbm_notes():
    """poly 展开原始单位二次项；GBM 明确标注无解析表达式。"""
    df = _linear_history()
    roles = _resolve_roles(df, {})
    bounds = _resolve_bounds(df, roles, {})
    poly_forward, _ = _fit_forward(df, roles, model="poly", random_state=42)
    poly_table = _build_model_equations(poly_forward, roles, bounds, {"reg_lambda": 0.02}, "std")
    poly_expr = poly_table[poly_table["类型"] == "前向方程"].iloc[0]["表达式"]
    assert "^2" in poly_expr and "VariableU1^2" in poly_expr
    assert (poly_table[poly_table["类型"] == "反解公式"]["表达式"] == "—").all()
    gbm_forward, _ = _fit_forward(df, roles, model="gbm", random_state=42)
    gbm_table = _build_model_equations(gbm_forward, roles, bounds, {"reg_lambda": 0.02}, "std")
    gbm_forward_rows = gbm_table[gbm_table["类型"] == "前向方程"]
    assert (gbm_forward_rows["表达式"] == "—").all()
    assert gbm_forward_rows["说明"].str.contains("无解析").all()


def test_build_model_equations_rate_time_formula():
    """速率模型：前向方程 = 来料 − 速率·t，时间给出解析反解。"""
    df = _rate_history()
    roles = _resolve_roles(df, {"time_col": "FixedTime"})
    forward, _ = _fit_rate_forward(df, roles, "FixedTime", random_state=42)
    bounds = _resolve_bounds(df, roles, {"time_col": "FixedTime", "time_adjustable": "true"})
    table = _build_model_equations(forward, roles, bounds, {"reg_lambda": 0.02}, "std")
    forward_expr = table[table["类型"] == "前向方程"].iloc[0]["表达式"]
    assert "IncomingZ1" in forward_expr and "·t" in forward_expr
    time_row = table[table["对象"] == "OutputZ1 → FixedTime"].iloc[0]
    assert time_row["表达式"].startswith("FixedTime = (IncomingZ1 − 目标OutputZ1) / (")
    assert "未含时间正则" in time_row["说明"]
    objective = table[table["类型"] == "优化目标"].iloc[0]["表达式"]
    assert "τ" in objective


def test_build_model_equations_keeps_small_coefficient_with_large_scale():
    """F1 回归：小系数（1e-13）× 大量纲（1e12）不得被量级判据静默丢弃。"""
    n = 60
    rng = np.random.default_rng(0)
    x = np.linspace(-1e12, 1e12, n)
    u = rng.uniform(4.0, 8.0, n)  # 非共线：u 不可由 x 仿射表出
    df = pd.DataFrame({"IncomingX": x, "VariableU1": u, "OutputY1": 0.5 + 1e-13 * x + 1.0 * u})
    roles = _resolve_roles(df, {})
    forward, _ = _fit_forward(df, roles, model="linear", random_state=42)
    bounds = _resolve_bounds(df, roles, {})
    table = _build_model_equations(forward, roles, bounds, {"reg_lambda": 0.02}, "std", history=df)
    forward_expr = table[table["类型"] == "前向方程"].iloc[0]["表达式"]
    assert "1e-13·IncomingX" in forward_expr
    inverse_expr = table[table["类型"] == "反解公式"].iloc[0]["表达式"]
    assert "IncomingX" in inverse_expr, "大量纲小系数项必须在反解公式中保留"


def test_parse_request_rows_truncates_and_returns_count():
    """F3：解析阶段按上限截断并返回截断条数（追加物化前完成）。"""
    from smartsuite.engine.inverse import _parse_request_rows

    rows, truncated = _parse_request_rows([{"a": i} for i in range(5)], 2)
    assert len(rows) == 2 and truncated == 3
    assert [row["a"] for row in rows] == [0.0, 1.0]
    rows, truncated = _parse_request_rows(None)
    assert rows == [] and truncated == 0


def test_inverse_solve_request_rows_variable_values_ignored():
    """F2：request_rows 携带可调参数值时显式忽略并提示，不静默并入历史。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "request_rows": [
                    {
                        "IncomingA": 1.15,
                        "VariableU1": 5.0,
                        "OutputY1": 1.3 - 0.06 * 5.5 + 0.05 * 1.15,
                        "OutputY2": 0.8,
                    }
                ],
            },
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_history"] == len(hist)
    assert result.metadata["n_request"] == 1
    assert any("可调参数取值已忽略" in message for message in result.messages)


def test_inverse_solve_request_rows_truncated_before_materialize(monkeypatch):
    """F3：request_rows 超过上限时先截断，再进入行分类与求解。"""
    from smartsuite.engine import inverse as inverse_module

    monkeypatch.setattr(inverse_module, "INVERSE_MAX_REQUESTS", 2)
    hist = _linear_history()
    rows = [{"IncomingA": 1.15, "OutputY1": 1.0, "OutputY2": 0.8} for _ in range(5)]
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42, "request_rows": rows},
        )
    )
    assert result.status == "ok"
    assert result.metadata["n_request"] == 2
    assert any("超过上限 2 条" in message for message in result.messages)


def test_fit_forward_auto_caps_candidates_for_large_n(monkeypatch):
    """R-1：auto 超行数上限时跳过 GPR/GBM 并给出中文说明（保持 LOO）。"""
    from smartsuite.engine import inverse as inverse_module

    assert inverse_module.INVERSE_AUTO_CANDIDATE_MAX_ROWS == 500  # 默认预算锚点
    monkeypatch.setattr(inverse_module, "INVERSE_AUTO_CANDIDATE_MAX_ROWS", 50)
    df = _linear_history(n=60)
    roles = _resolve_roles(df, {})
    forward, quality = _fit_forward(df, roles, model="auto", random_state=42)
    assert set(forward.choice) <= {"linear", "poly"}
    assert set(quality["候选"]) == {"linear", "poly"}
    assert set(quality["CV方案"]) == {"LOO"}
    assert forward.note and "跳过" in forward.note and "gpr" in forward.note
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "auto", "random_state": 42},
        )
    )
    assert result.status == "ok"
    assert any("auto 已跳过候选" in message for message in result.messages)


def test_fit_forward_large_n_uses_kfold(monkeypatch):
    """R-1：超行数上限时候选筛选由 LOO 切换为 5 折（O(n)→O(5)）。"""
    from smartsuite.engine import inverse as inverse_module

    assert inverse_module.INVERSE_CV_LOO_MAX_ROWS == 2000  # 默认预算锚点
    monkeypatch.setattr(inverse_module, "INVERSE_CV_LOO_MAX_ROWS", 100)
    df = _linear_history(n=150)
    roles = _resolve_roles(df, {})
    _, quality = _fit_forward(df, roles, model="linear", random_state=42)
    assert set(quality["CV方案"]) == {"5折"}


def test_fit_forward_gbm_always_uses_kfold():
    """N-1：gbm 恒用 5 折（LOO×n 次拟合随 n 增长，n 接近预算时达分钟级悬崖）。"""
    df = _linear_history(n=60)
    roles = _resolve_roles(df, {})
    _, quality = _fit_forward(df, roles, model="gbm", random_state=42)
    assert set(quality["CV方案"]) == {"5折"}


def test_cv_split_gbm_boundary_rows_keep_kfold():
    """N-1：GBM 在预算边界行数（500）不回落 LOO。"""
    from smartsuite.engine import inverse as inverse_module

    for n_rows in (10, 499, 500):
        _, label = inverse_module._cv_split(n_rows, 42, "gbm")
        assert label == "5折", f"n={n_rows} 应恒用 5 折"


def test_auto_candidates_boundary_at_budget_rows():
    """N-1：auto 候选判据含边界（n=500 即削候选，n=499 保留全候选）。"""
    from smartsuite.engine import inverse as inverse_module

    cands_at, notes_at = inverse_module._auto_candidates(500, 2)
    assert cands_at == ("linear", "poly")
    assert notes_at and "500" in notes_at[0]
    cands_below, notes_below = inverse_module._auto_candidates(499, 2)
    assert cands_below == ("linear", "poly", "gpr", "gbm")
    assert notes_below == []


def test_inverse_solve_max_starts_clamped_with_message():
    """C-2：max_starts 超上限按上限处理并写中文消息。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "max_starts": 100000,
                "request_rows": [
                    {
                        "IncomingA": 1.15,
                        "OutputY1": 1.3 - 0.06 * 5.5 + 0.05 * 1.15,
                        "OutputY2": 0.9 - 0.04 * 2.5,
                    }
                ],
            },
        )
    )
    assert result.status == "ok"
    assert any("max_starts" in message and "上限" in message for message in result.messages)


def test_inverse_solve_max_starts_non_positive_warns_and_clamps():
    """N-7：max_starts≤0 显式中文提示并按 1 处理（不再静默钳位）。"""
    hist = _linear_history()
    for value in (0, -3):
        result = inverse_parameter_solve(
            AnalysisRequest(
                task="inverse_solve",
                data=hist,
                target_col="",
                feature_cols=[],
                params={
                    "model": "linear",
                    "random_state": 42,
                    "max_starts": value,
                    "request_rows": [
                        {
                            "IncomingA": 1.15,
                            "OutputY1": 1.3 - 0.06 * 5.0 + 0.05 * 1.15,
                            "OutputY2": 0.9 - 0.04 * 3.0,
                        }
                    ],
                },
            )
        )
        assert result.status == "ok"
        assert any(
            "max_starts" in message and "按 1 处理" in message for message in result.messages
        ), value


def test_inverse_solve_model_zero_raises_chinese():
    """N-7：model=数值 0 不再被空值回退吞掉，显式中文报错。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": 0, "random_state": 42},
        )
    )
    assert result.status == "error"
    assert any("model" in message for message in result.messages)


def test_inverse_solve_weight_mode_zero_warns_and_falls_back():
    """N-7：weight_mode=数值 0 不再静默回退，中文提示后回退 std。"""
    hist = _linear_history()
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "weight_mode": 0,
                "random_state": 42,
                "request_rows": [
                    {
                        "IncomingA": 1.15,
                        "OutputY1": 1.3 - 0.06 * 5.0 + 0.05 * 1.15,
                        "OutputY2": 0.9 - 0.04 * 3.0,
                    }
                ],
            },
        )
    )
    assert result.status == "ok"
    assert any("weight_mode" in message and "回退" in message for message in result.messages)


def test_resolve_roles_time_col_zero_not_treated_as_empty():
    """N-7：time_col=数值 0 不再被当作空值回退自动识别，显式报列不存在。"""
    df = pd.DataFrame({0: [1.0, 2.0], "IncomingA": [1.1, 1.2], "OutputY": [0.9, 0.8]})
    try:
        _resolve_roles(df, {"time_col": 0})
    except ValueError as exc:
        assert "time_col" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("time_col=0 应显式报列不存在，而非静默回退")


def test_fit_forward_gpr_large_n_raises_chinese(monkeypatch):
    """R-1：显式 GPR 超过硬上限中文报错，防 O(n³) 假死。"""
    from smartsuite.engine import inverse as inverse_module

    assert inverse_module.INVERSE_GPR_MAX_ROWS == 2000  # 默认预算锚点
    monkeypatch.setattr(inverse_module, "INVERSE_GPR_MAX_ROWS", 100)
    df = _linear_history(n=150)
    roles = _resolve_roles(df, {})
    try:
        _fit_forward(df, roles, model="gpr", random_state=42)
    except ValueError as exc:
        assert "GPR" in str(exc) and "100" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("显式 GPR 超限应中文报错")


def test_fit_forward_auto_skips_poly_for_wide_features(monkeypatch):
    """R-1：poly 展开列数超上限时 auto 跳过 poly 并说明。"""
    from smartsuite.engine import inverse as inverse_module

    assert inverse_module.INVERSE_POLY_MAX_TERMS == 100  # 默认预算锚点
    monkeypatch.setattr(inverse_module, "INVERSE_POLY_MAX_TERMS", 20)
    rng = np.random.default_rng(0)
    n = 50
    data = {f"VariableU{i}": rng.uniform(4, 8, n) for i in range(1, 7)}  # 6 列 → 27 项
    data["IncomingA"] = rng.normal(1.1, 0.05, n)
    data["OutputY1"] = 1.0 + sum(0.05 * data[f"VariableU{i}"] for i in range(1, 7))
    df = pd.DataFrame(data)
    roles = _resolve_roles(df, {})
    forward, quality = _fit_forward(df, roles, model="auto", random_state=42)
    assert "poly" not in set(quality["候选"])
    assert forward.note and "poly" in forward.note


def test_fast_predictor_matches_pipeline_predictions():
    """求解器快速路径与 sklearn pipeline 预测数值一致（linear/poly/rate）。"""
    df = _linear_history()
    roles = _resolve_roles(df, {})
    for model in ("linear", "poly"):
        forward, _ = _fit_forward(df, roles, model=model, random_state=42)
        assert forward.fast and all(item is not None for item in forward.fast)
        sample = df[forward.feature_cols].head(5)
        expected = forward.predict(sample)
        for col_index, predictor in enumerate(forward.fast):
            got = np.asarray(
                [
                    float(np.ravel(predictor(sample.iloc[r].to_numpy(dtype=float)[None, :]))[0])
                    for r in range(len(sample))
                ]
            )
            assert np.allclose(got, expected[:, col_index], rtol=1e-9, atol=1e-9)

    rate_df = _rate_history()
    rate_roles = _resolve_roles(rate_df, {"time_col": "FixedTime"})
    rate_forward, _ = _fit_rate_forward(rate_df, rate_roles, "FixedTime", random_state=42)
    assert rate_forward.fast_rate and all(item is not None for item in rate_forward.fast_rate)
    row = rate_df.iloc[0].to_dict()
    u_values = {"VariableU1": 5.0}
    rates = rate_forward.predict_rate(row, u_values)
    for index, (cols, predictor) in enumerate(
        zip(rate_forward.rate_feature_cols, rate_forward.fast_rate, strict=True)
    ):
        # 与 _rate_feature_value 同口径：可调参数取值优先于历史行取值
        values = np.asarray([[u_values.get(c, row[c]) for c in cols]], dtype=float)
        assert float(np.ravel(predictor(values))[0]) == pytest.approx(float(rates[index]), rel=1e-9)


def test_reachable_range_inside_flag_scales_with_output_magnitude():
    """R-2：微尺度输出的「是否在内」不得被绝对 epsilon 吞没。"""
    rng = np.random.default_rng(0)
    n = 40
    inc = rng.normal(1.1, 0.05, n)
    u = rng.uniform(4, 8, n)
    micro = pd.DataFrame(
        {"IncomingA": inc, "VariableU1": u, "OutputY1": (1.3 - 0.06 * u + 0.05 * inc) * 1e-12}
    )
    y_far = float(micro["OutputY1"].max()) * 1.5
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=micro,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "request_rows": [{"IncomingA": 1.1, "OutputY1": y_far}],
            },
        )
    )
    assert result.status == "ok"
    assert result.tables["reachable_ranges"].iloc[0]["是否在内"] == "否"

    normal = pd.DataFrame(
        {"IncomingA": inc, "VariableU1": u, "OutputY1": 1.3 - 0.06 * u + 0.05 * inc}
    )
    y_in = float(1.3 - 0.06 * 5.0 + 0.05 * 1.1)
    result2 = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=normal,
            target_col="",
            feature_cols=[],
            params={
                "model": "linear",
                "random_state": 42,
                "request_rows": [{"IncomingA": 1.1, "OutputY1": y_in}],
            },
        )
    )
    assert result2.tables["reachable_ranges"].iloc[0]["是否在内"] == "是"


def test_inverse_solve_does_not_mutate_input_dataframe():
    """R-5：角色列强制数值化只作用于副本，不违反引擎输入不变式。"""
    hist = _linear_history()
    hist["IncomingA"] = hist["IncomingA"].map(lambda v: f"{v:.6f}")  # 文本 dtype
    original_dtype = hist["IncomingA"].dtype
    original = hist["IncomingA"].copy()
    assert not pd.api.types.is_numeric_dtype(original_dtype)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=hist,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42},
        )
    )
    assert result.status == "ok"
    assert hist["IncomingA"].dtype == original_dtype
    assert hist["IncomingA"].equals(original)


def _synthetic_batch_frames(n_history: int = 33, n_request: int = 11, seed: int = 7):
    """脱敏同构批次：列名/规模与真实批次一致（15 列、常数列、离散可调参数）。

    N-4：真实批次数据不入库导致 CI 无验收载体；本函数合成同构样本供 CI 回归，
    真实数据验收仍由 test_inverse_solve_real_batch_acceptance 在本机执行。
    """
    rng = np.random.default_rng(seed)
    g = rng.uniform(1.05, 1.20, n_history)
    history = pd.DataFrame(
        {
            "IncomingZ1": g,
            "IncomingZ2": g - rng.uniform(0.0, 0.05, n_history),
            "IncomingZ3": g - rng.uniform(0.0, 0.05, n_history),
            "IncomingZ4": g - rng.uniform(0.0, 0.08, n_history),
            "IncomingBow": rng.integers(131, 332, n_history).astype(float),
            "VariableU1": rng.integers(5, 9, n_history).astype(float),
            "VariableU2": rng.integers(2, 5, n_history).astype(float),
            "VariableU3": rng.integers(2, 5, n_history).astype(float),
            "FixedU4": 3.0,
            "VariableU5": rng.integers(2, 5, n_history).astype(float),
            "FixedTime": 60.0,
        }
    )
    coefs = [
        (0.80, 0.10, -0.010, -0.020),
        (0.70, 0.12, -0.008, -0.015),
        (0.60, 0.15, -0.006, -0.012),
        (0.50, 0.18, -0.004, -0.010),
    ]
    for suffix, (a1, a2, b1, b2) in zip(("Z1", "Z2", "Z3", "Z4"), coefs, strict=True):
        history[f"Output{suffix}"] = (
            0.05
            + a1 * history["IncomingZ1"]
            + a2 * history["IncomingZ2"]
            + b1 * history["VariableU1"]
            + b2 * history["VariableU2"]
            + rng.normal(0.0, 0.002, n_history)
        )
    requests = pd.DataFrame(
        {
            "IncomingZ1": rng.uniform(1.06, 1.18, n_request),
            "IncomingZ2": rng.uniform(1.06, 1.16, n_request),
            "IncomingZ3": rng.uniform(1.06, 1.16, n_request),
            "IncomingZ4": rng.uniform(1.02, 1.12, n_request),
            "IncomingBow": rng.integers(131, 332, n_request).astype(float),
            "VariableU1": np.nan,
            "VariableU2": np.nan,
            "VariableU3": np.nan,
            "FixedU4": np.nan,
            "VariableU5": np.nan,
            "FixedTime": np.nan,
        }
    )
    for suffix, (a1, a2, b1, b2) in zip(("Z1", "Z2", "Z3", "Z4"), coefs, strict=True):
        requests[f"Output{suffix}"] = (
            0.05 + a1 * requests["IncomingZ1"] + a2 * requests["IncomingZ2"] + b1 * 6.0 + b2 * 3.0
        )
    return history, requests


def test_inverse_solve_synthetic_batch_acceptance():
    """N-4：脱敏同构批次（33 历史 + 11 请求、真实列名形态）端到端，补 CI 验收。"""
    history, requests = _synthetic_batch_frames()
    df = pd.concat([history, requests], ignore_index=True)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42},
        )
    )
    assert result.status == "ok", result.messages
    assert result.metadata["n_history"] == len(history)
    assert result.metadata["n_request"] == len(requests)
    assert len(result.tables["recommendations"]) == len(requests)


def test_inverse_solve_real_batch_acceptance():
    """R-4：真实批次验收数据（logs/Data.xlsx 33 行 + logs/examples.xlsx 11 请求）端到端。

    用户真实批次数据不入库（logs/ 已 gitignore）；CI 或他人环境缺文件时跳过，
    CI 的同构回归见 test_inverse_solve_synthetic_batch_acceptance（N-4）。
    """
    data_dir = Path(__file__).resolve().parents[2] / "logs"
    history_path = data_dir / "Data.xlsx"
    requests_path = data_dir / "examples.xlsx"
    if not history_path.exists() or not requests_path.exists():
        pytest.skip("真实批次验收数据未提供（logs/Data.xlsx + logs/examples.xlsx）")
    history = pd.read_excel(history_path)
    requests = pd.read_excel(requests_path)
    df = pd.concat([history, requests], ignore_index=True)
    result = inverse_parameter_solve(
        AnalysisRequest(
            task="inverse_solve",
            data=df,
            target_col="",
            feature_cols=[],
            params={"model": "linear", "random_state": 42},
        )
    )
    assert result.status == "ok", result.messages
    assert result.metadata["n_history"] == len(history)
    assert result.metadata["n_request"] == len(requests)
    assert len(result.tables["recommendations"]) == len(requests)
