import numpy as np
from smartsuite.engine import spc_monitor

# Ensure fixes module is imported so monkeypatches apply
try:
    import smartsuite.engine.spc_fixes  # noqa: F401
except Exception:
    # If import fails, tests should still try original functions and will expose issues
    pass


def test_ljung_box_constant_residuals():
    residuals = np.ones(20)
    q_stat, p_val, lags = spc_monitor._ljung_box(residuals, lags=5)
    # q_stat should be numeric and p_val should be a float (not raise)
    assert isinstance(q_stat, float)
    assert isinstance(p_val, float)


def test_cp_confidence_interval_small_dof():
    # with n=1 (dof=0) returning (None, None) is expected
    ci = spc_monitor._cp_confidence_interval(1.0, 1)
    assert ci == (None, None)
