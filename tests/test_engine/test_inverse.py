import numpy as np
import pandas as pd

from smartsuite.engine.inverse import fit_forward, resolve_roles, split_rows


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
    assert quality["Output"].tolist() == ["OutputY1", "OutputY2"]
    assert quality.loc[quality["选用"], "LOO_R2"].min() > 0.8
    pred = forward.predict(df[forward.feature_cols].head(3))
    assert pred.shape == (3, 2)


def test_fit_forward_fixed_model():
    df = _linear_history()
    roles = resolve_roles(df, {})
    forward, quality = fit_forward(df, roles, model="linear", random_state=42)
    assert forward.choice == ["linear", "linear"]
    assert not forward.has_tree
