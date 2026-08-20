"""引擎共享工具函数单测（_utils.py / _palette.py）。

背景：test_quality_guard 缺测检测要求公共函数有测试引用——
safe_float / threshold_label / durbin_watson / get_palette_style
此前仅被引擎内部间接调用，本文件补直接单测。
"""

import numpy as np
import pytest

from smartsuite.engine._palette import get_palette_style
from smartsuite.engine._utils import durbin_watson, safe_float, threshold_label


# ── safe_float（falsy 陷阱防护核心）──


def test_safe_float_none_returns_default():
    assert safe_float(None, 0.05) == 0.05


def test_safe_float_numeric_string():
    assert safe_float("0.05", 0.1) == 0.05


def test_safe_float_zero_is_not_treated_as_failure():
    # falsy 陷阱：0 是合法值，必须返回 0.0 而非默认值
    assert safe_float(0, 1.0) == 0.0


def test_safe_float_invalid_returns_default():
    assert safe_float("abc", 0.5) == 0.5


def test_safe_float_nan_returns_default():
    # 审查 2026-08-19 #2.6：float("nan") 不抛异常，但 NaN 视为转换失败
    assert safe_float("nan", 0.5) == 0.5
    assert safe_float(float("nan"), 0.5) == 0.5


def test_safe_float_inf_returns_default():
    assert safe_float("inf", 0.5) == 0.5
    assert safe_float(float("inf"), 0.5) == 0.5


# ── threshold_label（效应量等级标签）──

THRESHOLDS = [0.01, 0.06, 0.14]


def test_threshold_label_below_first_threshold():
    assert threshold_label(0.005, THRESHOLDS) == "可忽略"


def test_threshold_label_middle_level():
    assert threshold_label(0.03, THRESHOLDS) == "小"


def test_threshold_label_above_all_returns_last():
    assert threshold_label(0.5, THRESHOLDS) == "大"


def test_threshold_label_nan_returns_na():
    assert threshold_label(float("nan"), THRESHOLDS) == "N/A"


# ── durbin_watson（残差自相关统计量）──


def test_durbin_watson_no_autocorrelation_approx_2():
    rng = np.random.default_rng(42)
    residuals = rng.normal(size=200)
    assert abs(durbin_watson(residuals) - 2.0) < 0.3


def test_durbin_watson_positive_autocorrelation_less_than_2():
    residuals = np.arange(1, 101, dtype=float)  # 强正自相关
    assert durbin_watson(residuals) < 0.5


def test_durbin_watson_too_few_residuals_raises():
    with pytest.raises(ValueError):
        durbin_watson([1.0])


# ── get_palette_style（matplotlib rcParams 样式）──


def test_get_palette_style_returns_expected_keys():
    style = get_palette_style()
    assert style["axes.grid"] is True
    assert "figure.facecolor" in style
    assert "xtick.labelsize" in style
