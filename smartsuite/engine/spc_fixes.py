import numpy as np
from scipy import stats as sp_stats

# Import the original module to patch
import smartsuite.engine.spc_monitor as spc

# --- Robust utilities and replacements for spc_monitor ---

def _safe_autocorr(residuals, lag):
    """Compute autocorrelation at lag robustly.

    Returns 0.0 if either segment is (near-)constant or correlation is NaN.
    """
    a = residuals[lag:]
    b = residuals[:-lag]
    # Use nanstd to be robust to NaNs; treat extremely small std as constant
    if np.nanstd(a) < 1e-12 or np.nanstd(b) < 1e-12:
        return 0.0
    try:
        r = np.corrcoef(a, b)[0, 1]
    except Exception:
        return 0.0
    return 0.0 if np.isnan(r) else float(r)


def _ljung_box(residuals, lags=None):
    """Robust wrapper for Ljung-Box to tolerate degenerate residual series.

    This replaces smartsuite.engine.spc_monitor._ljung_box at import time.
    """
    n = len(residuals)
    if lags is None:
        lags = min(10, n // 5)
    lags = max(1, min(lags, n // 2))
    acf_sum = 0.0
    for k in range(1, lags + 1):
        r_k = _safe_autocorr(residuals, k)
        acf_sum += r_k ** 2 / (n - k)
    q_stat = n * (n + 2) * acf_sum
    try:
        p_val = float(1 - sp_stats.chi2.cdf(q_stat, lags))
    except Exception:
        p_val = float("nan")
    return float(q_stat), p_val, lags


def _cp_confidence_interval(cp, n, alpha=0.05):
    """Cp/Cpk confidence interval with defensive guards.

    Returns (None, None) when CI cannot be reliably estimated (small dof,
    invalid ppf results, or exceptions).
    """
    dof = n - 1
    if dof <= 0 or cp is None:
        return (None, None)
    try:
        chi2_lower = sp_stats.chi2.ppf(alpha / 2, dof)
        chi2_upper = sp_stats.chi2.ppf(1 - alpha / 2, dof)
        if np.isnan(chi2_lower) or np.isnan(chi2_upper) or chi2_lower <= 0:
            return (None, None)
        ci_lower = cp * np.sqrt(chi2_lower / dof)
        ci_upper = cp * np.sqrt(chi2_upper / dof)
        return (float(ci_lower), float(ci_upper))
    except Exception:
        return (None, None)


def _cpk_confidence_interval(cpk, n, alpha=0.05):
    """Cpk confidence interval (Bissell approx) with defensive guards."""
    if cpk is None or n < 2:
        return (None, None)
    try:
        se = np.sqrt(1 / (9 * n) + cpk ** 2 / (2 * (n - 1)))
        z = sp_stats.norm.ppf(1 - alpha / 2)
        ci_lower = cpk - z * se
        ci_upper = cpk + z * se
        return (float(ci_lower), float(ci_upper))
    except Exception:
        return (None, None)


# Apply monkeypatches to the spc_monitor module so importing this file
# makes the safer implementations active without editing the large source file.
spc._ljung_box = _ljung_box
spc._cp_confidence_interval = _cp_confidence_interval
spc._cpk_confidence_interval = _cpk_confidence_interval

# Expose the safe_autocorr for tests / diagnostics
spc._safe_autocorr = _safe_autocorr
