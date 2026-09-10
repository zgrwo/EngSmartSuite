import logging

import numpy as np
import pandas as pd
import pytest

from smartsuite.engine._constants import INVERSE_LAM_TIME
from smartsuite.engine.inverse import (
    fit_forward,
    fit_rate_forward,
    optimal_time,
    pair_incoming_output,
    resolve_bounds,
    resolve_roles,
    solve_one,
    split_rows,
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
    roles = resolve_roles(df, {})
    assert roles.incoming == ["IncomingA", "IncomingB"]
    assert roles.variable == ["VariableU1"]
    assert roles.fixed == ["FixedT"]
    assert roles.output == ["OutputY1"]


def test_resolve_roles_param_override_and_chinese_prefix():
    df = pd.DataFrame({"来料A": [1.0], "可调U": [2.0], "输出Y": [3.0]})
    roles = resolve_roles(df, {"incoming_cols": "来料A"})
    assert roles.incoming == ["来料A"]
    assert roles.variable == ["可调U"]
    assert roles.output == ["输出Y"]


def test_resolve_roles_missing_output_raises_chinese():
    df = pd.DataFrame({"IncomingA": [1.0]})
    try:
        resolve_roles(df, {})
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
    roles = resolve_roles(df, {})
    history, requests, skipped = split_rows(df, roles)
    assert len(history) == 2
    assert len(requests) == 1
    assert skipped == []
    assert requests.iloc[0]["OutputY1"] == 0.7


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
    roles = resolve_roles(df, {})
    forward, quality = fit_forward(df, roles, model="auto", random_state=42)
    assert len(forward.feature_cols) == 3
    assert quality["Output"].unique().tolist() == ["OutputY1", "OutputY2"]
    assert len(quality) == 8  # 2 输出 × 4 候选（spec §4.5 全候选对比表）
    sel = quality[quality["选用"]]
    assert sel["Output"].tolist() == ["OutputY1", "OutputY2"]
    assert sel["LOO_R2"].min() > 0.8
    pred = forward.predict(df[forward.feature_cols].head(3))
    assert pred.shape == (3, 2)


def test_fit_forward_fixed_model():
    df = _linear_history()
    roles = resolve_roles(df, {})
    forward, quality = fit_forward(df, roles, model="linear", random_state=42)
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
    assert pair_incoming_output(["IncomingZ1", "IncomingZ2"], ["OutputZ1", "OutputZ2"]) == [
        ("IncomingZ1", "OutputZ1"),
        ("IncomingZ2", "OutputZ2"),
    ]


def test_fit_rate_forward_recovers_output():
    df = _rate_history()
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    fwd, quality = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.pairing_note is None
    assert quality.loc[quality["选用"], "LOO_R2"].min() > 0.8
    row = df.iloc[0]
    pred = fwd.predict_output(row.to_dict(), {"VariableU1": 5.0}, time=60.0)
    assert pred.shape == (1,)


def test_rate_requires_time_col():
    df = _rate_history().drop(columns=["FixedTime"])
    roles = resolve_roles(df, {})
    try:
        fit_rate_forward(df, roles, None, random_state=42)
    except ValueError as exc:
        assert "time" in str(exc).lower() or "时间" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺时间列应报错")


def test_rate_forward_predict_rate_matches_physics():
    df = _rate_history()
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    fwd, _ = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.uses_time and not fwd.has_tree
    rate = fwd.predict_rate(df.iloc[0].to_dict(), {"VariableU1": 5.0})
    assert rate.shape == (1,)
    assert abs(rate[0] - (0.002 + 0.0004 * 5.0)) < 1e-6


def test_fit_rate_forward_records_pairing_fallback():
    df = _rate_history().rename(columns={"IncomingZ1": "IncomingA", "OutputZ1": "OutputY"})
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    fwd, _ = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert fwd.pairing_note is not None
    assert "配对" in fwd.pairing_note
    assert "共用" in fwd.pairing_note
    assert "IncomingA→OutputY" in fwd.pairing_note


def test_fit_rate_forward_skips_row_with_nan_rate_feature(caplog):
    df = _rate_history()
    df["IncomingZ2"] = np.linspace(0.5, 0.9, len(df))
    df.loc[0, "IncomingZ2"] = np.nan
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fwd, quality = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert not quality.empty
    assert quality.loc[quality["选用"], "LOO_R2"].min() > 0.8
    assert any("剔除" in r.message for r in caplog.records)
    complete = df.dropna().iloc[0]
    pred = fwd.predict_output(complete.to_dict(), {"VariableU1": 5.0}, time=60.0)
    assert pred.shape == (1,)


def test_fit_rate_forward_all_zero_time_raises_chinese():
    df = _rate_history()
    df["FixedTime"] = 0.0
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    try:
        fit_rate_forward(df, roles, "FixedTime", random_state=42)
    except ValueError as exc:
        assert "时间" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("时间全为 0 应报错")


def test_solve_one_recovers_known_parameters():
    df = _linear_history()
    roles = resolve_roles(df, {})
    forward, _ = fit_forward(df, roles, model="linear", random_state=42)
    bounds = resolve_bounds(df, roles, {})
    incoming = {"IncomingA": 1.1}
    target = np.array([1.3 - 0.06 * 5.0 + 0.05 * 1.1, 0.9 - 0.04 * 3.0])
    scale = df[roles.output].std().to_numpy()
    u, pred, info = solve_one(
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
    roles = resolve_roles(df, {})
    forward, _ = fit_forward(df, roles, model="linear", random_state=42)
    args = (
        forward,
        {"IncomingA": 1.1},
        np.array([0.98, 0.78]),
        df[roles.output].std().to_numpy(),
        np.ones(2),
        resolve_bounds(df, roles, {}),
        df[roles.variable].median().to_dict(),
        {"random_state": 42},
    )
    u1, _, _ = solve_one(*args)
    u2, _, _ = solve_one(*args)
    assert u1 == u2


def test_optimal_time_analytic():
    df = _rate_history()
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    forward, _ = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    t = optimal_time(
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
    t = optimal_time(forward, incoming, target, scale, weights, u, (40.0, 60.0))
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
    anchored = optimal_time(
        forward, {"IncomingZ1": 1.1, "FixedTime": 60.0}, target, scale, weights, u, (40.0, 60.0)
    )
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fallback = optimal_time(
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
    roles = resolve_roles(df, {})
    forward, _ = fit_forward(df, roles, model="gbm", random_state=42)
    incoming = {"IncomingA": 1.1}
    known = {"VariableU1": 5.0, "VariableU2": 3.0}
    target = np.ravel(forward.predict(pd.DataFrame([{**incoming, **known}])))
    scale = df[roles.output].std().to_numpy()
    baseline = df[roles.variable].median().to_dict()
    baseline_pred = np.ravel(forward.predict(pd.DataFrame([{**incoming, **baseline}])))
    u, pred, info = solve_one(
        forward,
        incoming,
        target,
        scale,
        np.ones(2),
        resolve_bounds(df, roles, {}),
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
    roles = resolve_roles(df, {})
    explicit = resolve_bounds(
        df,
        roles,
        {"variable_bounds": '{"VariableU1": [4.5, 6.5], "VariableU2": [2.5, 3.5]}'},
    )
    assert explicit["VariableU1"] == (4.5, 6.5)
    assert explicit["VariableU2"] == (2.5, 3.5)
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        fallback = resolve_bounds(df, roles, {"variable_bounds": "{不是合法JSON"})
    assert any("JSON" in r.message for r in caplog.records)
    assert fallback["VariableU1"] == (
        float(df["VariableU1"].min()),
        float(df["VariableU1"].max()),
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.inverse"):
        constant = resolve_bounds(df, roles, {"variable_bounds": {"VariableU1": [5.0, 5.0]}})
    assert constant["VariableU1"] == (5.0, 5.0)
    assert any("宽度为 0" in r.message for r in caplog.records)
