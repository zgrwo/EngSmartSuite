import numpy as np
import pandas as pd

from smartsuite.engine.inverse import (
    fit_forward,
    fit_rate_forward,
    pair_incoming_output,
    resolve_roles,
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
    assert "IncomingA→OutputY" in fwd.pairing_note


def test_fit_rate_forward_skips_row_with_nan_rate_feature():
    df = _rate_history()
    df.loc[0, "IncomingZ1"] = np.nan
    roles = resolve_roles(df, {"time_col": "FixedTime"})
    fwd, quality = fit_rate_forward(df, roles, "FixedTime", random_state=42)
    assert quality.loc[quality["选用"], "LOO_R2"].min() > 0.8
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
