"""review-2026-09-16 修复回归测试 — 微尺度绝对阈值同族 + 展示层 + 哨兵补齐。

对应审查报告 logs/reports/review-2026-09-16-full-modules.md 的问题清单：
  B-1 (P0) doe_analysis 绝对 EPSILON 误判标准误 → t 置 0 / p 置 1
  B-2      Grubbs 微尺度静默零异常；常量列静默返回 ok
  B-3      Hedges g 合并标准差绝对判据 → 微尺度静默 0.0
  B-4      trend/spc_xbar/spc_nonparametric 微尺度误报「常量列」
  B-5      Web/HTML/前端固定 4 位展示吞没微尺度（抵消 round_for_display）
  C-1      max_outliers=inf 触发 OverflowError 穿透
  C-2      sw_p falsy 三元把合法 0.0 显示为 N/A
  C-3      _std_beta / _lenth_pse / _desirability 绝对 EPSILON
  D-1/D-2  zscore/consensus/gage_rr/tolerance/cusum/ewma/correlation/d/CV%/cronbach/
           MAPE/Durbin-Watson/WE 规则 同族绝对阈值

所有用例在修复前为红（先写测试→修复→转绿）。
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine import (
    anomaly_detect,
    cronbach_alpha,
    cusum_chart,
    distribution_summary,
    ewma_chart,
    gage_rr,
    hypothesis_test,
    outlier_consensus,
    regression_analysis,
    spc_nonparametric,
    tolerance_interval,
    trend_forecast,
    xbar_r_chart,
)
from smartsuite.engine._utils import durbin_watson
from smartsuite.services.orchestrator import orchestrate
from smartsuite.web.api import _serialize_table

_APP_JS = (
    Path(__file__).resolve().parent.parent / "src" / "smartsuite" / "web" / "static" / "app.js"
)


def _doe_df(scale: float, seed: int = 23, n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.uniform(1, 10, n)
    g = np.repeat(["A", "B"], n // 2)
    y = scale * (1 + 0.5 * x + 0.2 * (g == "B") + 0.05 * rng.standard_normal(n))
    return pd.DataFrame({"x": x, "g": g, "y": y})


def _spike_df(scale: float = 1.0) -> pd.DataFrame:
    """微/宏观同构：100 点基座 + 20σ 离群点（宏观 scale=1e10 时即常规量级）。"""
    rng = np.random.default_rng(11)
    y = 5e-13 + 1e-14 * rng.standard_normal(100)
    y[50] = 2e-12
    return pd.DataFrame({"y": y * scale})


def _two_group(scale: float):
    rng = np.random.default_rng(7)
    a = rng.normal(0, 1, 40)
    b = rng.normal(3, 1, 40)
    return pd.DataFrame({"g": ["A"] * 40 + ["B"] * 40, "y": np.r_[a, b] * scale})


def _gage_df(scale: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    parts = np.repeat(range(1, 11), 6)
    ops = np.tile(np.repeat(["A", "B", "C"], 2), 10)
    measure = (10 + (parts - 5) * 0.5 + rng.normal(0, 0.1, 60)) * scale
    return pd.DataFrame({"part": parts, "op": ops, "m": measure})


# ── B-1 (P0): doe_analysis 量纲对抗 ──────────────────────────────────────────
def test_doe_analysis_ppb_scale_matches_normal_scale():
    def run(scale):
        return orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=_doe_df(scale),
                target_col="y",
                feature_cols=["x"],
                params={},
            )
        )

    macro, micro = run(1.0), run(1e-9)
    row_m = macro.tables["effect_estimates"].iloc[0]
    row_u = micro.tables["effect_estimates"].iloc[0]
    assert row_u["显著"] == "是", f"ppb 数据应显著（t=0/p=1 为旧缺陷）: {row_u.to_dict()}"
    assert row_u["p值"] == pytest.approx(row_m["p值"], abs=1e-6)
    assert row_u["t值"] == pytest.approx(row_m["t值"], rel=1e-3)
    # 主效应展示按量纲同比，不再被 4 位小数整列归零
    assert row_u["主效应"] == pytest.approx(row_m["主效应"] * 1e-9, rel=1e-3)
    assert "显著因子: 1/1" in micro.summary


def test_doe_analysis_micro_factor_coding_and_effect_ratio():
    """B-1 同族：因子列本身微尺度（DOE z-score 编码 std+EPSILON 稀释 + 效应占比分母）。

    旧缺陷两处：编码用 `std + EPSILON`（因子 ~1e-11 时编码被压缩 ~5 倍）；
    `abs(grand_mean) > EPSILON` 把微尺度占比整体置 0。
    """

    def run(scale):
        df = _doe_df(scale)
        df["x"] = df["x"] * scale  # 因子与响应同比缩放，关系不变
        return orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=df,
                target_col="y",
                feature_cols=["x"],
                params={},
            )
        )

    macro, micro = run(1.0), run(1e-11)
    row_m = macro.tables["effect_estimates"].iloc[0]
    row_u = micro.tables["effect_estimates"].iloc[0]
    assert row_u["显著"] == "是", f"微尺度因子应显著: {row_u.to_dict()}"
    assert row_u["t值"] == pytest.approx(row_m["t值"], rel=1e-3)
    assert row_u["主效应"] == pytest.approx(row_m["主效应"] * 1e-11, rel=1e-3)
    assert float(row_u["效应占比"]) == pytest.approx(float(row_m["效应占比"]), rel=1e-3)
    assert float(row_u["效应占比"]) > 0.0, "微尺度占比不得被绝对 EPSILON 归零"


def test_doe_analysis_lenth_pse_micro_scale_not_floored():
    """C-3 同族：`_lenth_pse` 绝对下限 `max(pse, EPSILON)`（3 因子无重复 DOE）。

    微尺度效应 ~1e-12 时旧代码把 PSE/SME 抬到 1e-10（约 50 倍失真）。
    """
    rng = np.random.default_rng(41)
    n = 40
    x1, x2, x3 = (rng.uniform(0, 1, n) for _ in range(3))

    def run(y_scale):
        y = y_scale * (2 + 0.6 * x1 - 0.4 * x2 + 0.15 * x3 + 0.02 * rng.standard_normal(n))
        df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3, "y": y})
        return orchestrate(
            AnalysisRequest(
                task="doe_analysis",
                data=df,
                target_col="y",
                feature_cols=["x1", "x2", "x3"],
                params={},
            )
        )

    macro, micro = run(1e-2), run(1e-11)
    assert micro.status == "ok", micro.messages
    pse_m = float(macro.metadata["lenth_pse"])
    pse_u = float(micro.metadata["lenth_pse"])
    me_m = float(macro.metadata["lenth_me"])
    me_u = float(micro.metadata["lenth_me"])
    assert pse_m > 0 and pse_u > 0
    assert pse_u == pytest.approx(pse_m * 1e-9, rel=1e-6), "PSE 被绝对下限抬高"
    assert me_u == pytest.approx(me_m * 1e-9, rel=1e-6), "SME 被绝对下限抬高"


def test_doe_analysis_perfect_fit_not_fabricated_zero_t():
    """完全共线（残差≈0）→ 不得伪造 t=0/p=1/不显著（旧缺陷）。

    数值路径：残差非精确 0 时 t 应极大（≈1e16）、p≈0；精确 0（浮点可达）时
    t 无定义 → NaN + 「无法判定」。两种路径都不得回到 t=0.0/p=1.0/否。
    """
    g = np.repeat(["A", "B"], 30)
    y = np.where(g == "B", 7.0, 3.0)  # 二水平编码下完美线性
    df = pd.DataFrame({"g": g, "y": y})
    r = orchestrate(
        AnalysisRequest(task="doe_analysis", data=df, target_col="y", feature_cols=["g"], params={})
    )
    row = r.tables["effect_estimates"].iloc[0]
    assert row["显著"] in ("是", "无法判定"), f"完美拟合不得判「否」: {row.to_dict()}"
    t = float(row["t值"])
    if row["显著"] == "无法判定":
        assert math.isnan(t)
    else:
        assert abs(t) > 1e6, "完美拟合下 t 不得被伪造为 0"
        assert float(row["p值"]) == 0.0


# ── B-2: Grubbs ────────────────────────────────────────────────────────────
def test_grubbs_micro_scale_detects_outlier():
    micro = anomaly_detect(
        AnalysisRequest(
            task="anomaly_detect",
            data=_spike_df(1.0),
            target_col="y",
            feature_cols=[],
            params={"method": "grubbs", "alpha": 0.05, "max_outliers": 5},
        )
    )
    macro = anomaly_detect(
        AnalysisRequest(
            task="anomaly_detect",
            data=_spike_df(1e10),
            target_col="y",
            feature_cols=[],
            params={"method": "grubbs", "alpha": 0.05, "max_outliers": 5},
        )
    )
    assert micro.status == "ok"
    assert micro.metadata["anomaly_count"] == macro.metadata["anomaly_count"] >= 1


def test_grubbs_constant_column_explicit_error():
    df = pd.DataFrame({"y": np.full(50, 1e-12)})
    r = anomaly_detect(
        AnalysisRequest(
            task="anomaly_detect",
            data=df,
            target_col="y",
            feature_cols=[],
            params={"method": "grubbs"},
        )
    )
    assert r.status == "error"
    assert any("常量" in m for m in r.messages)


# ── B-3: Hedges g ──────────────────────────────────────────────────────────
def test_hedges_g_micro_scale_matches_macro():
    def run(scale):
        return orchestrate(
            AnalysisRequest(
                task="hypothesis_test",
                data=_two_group(scale),
                target_col="y",
                feature_cols=["g"],
                params={"test": "ttest_ind"},
            )
        )

    macro, micro = run(1.0), run(1e-12)
    assert micro.status == "ok"
    g_macro = float(macro.metadata["effect_size"])
    g_micro = float(micro.metadata["effect_size"])
    assert abs(g_macro) > 1.0, "前置：真实效应应为大效应"
    assert g_micro == pytest.approx(g_macro, rel=1e-6)


@pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:Precision loss occurred:RuntimeWarning")
def test_hedges_g_zero_variance_warns_not_silent():
    df = pd.DataFrame({"g": ["A"] * 10 + ["B"] * 10, "y": [1.0] * 10 + [2.0] * 10})
    r = orchestrate(
        AnalysisRequest(
            task="hypothesis_test",
            data=df,
            target_col="y",
            feature_cols=["g"],
            params={"test": "ttest_ind"},
        )
    )
    assert float(r.metadata["effect_size"]) == 0.0
    assert any("变异" in m for m in r.messages), "零方差返回 0 必须伴随警告，不得静默"


# ── B-4: 微尺度常量判据 ────────────────────────────────────────────────────
def test_trend_forecast_pico_scale_not_constant():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"y": 5e-13 + 1e-13 * rng.standard_normal(50)})
    r = trend_forecast(
        AnalysisRequest(task="trend_forecast", data=df, target_col="y", feature_cols=[], params={})
    )
    assert r.status == "ok", f"pico 级真实波动被误判常量: {r.messages}"


def test_spc_xbar_pico_scale_not_constant():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"y": 5e-13 + 1e-13 * rng.standard_normal(50)})
    r = xbar_r_chart(
        AnalysisRequest(task="spc_xbar", data=df, target_col="y", feature_cols=[], params={})
    )
    assert r.status == "ok", f"pico 级真实波动被误判常量: {r.messages}"


def test_spc_nonparametric_pico_scale_not_constant():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"y": 5e-13 + 1e-13 * rng.standard_normal(50)})
    r = spc_nonparametric(
        AnalysisRequest(
            task="spc_nonparametric", data=df, target_col="y", feature_cols=[], params={}
        )
    )
    assert r.status == "ok", f"pico 级真实波动被误判常量: {r.messages}"


# ── B-5: 展示层 ────────────────────────────────────────────────────────────
def test_serialize_table_micro_column_not_zeroed():
    out = _serialize_table(pd.DataFrame({"v": [9.827e-11, 4.1e-11]}))
    assert out["data"][0][0] == pytest.approx(9.827e-11, rel=1e-3)
    assert out["data"][1][0] == pytest.approx(4.1e-11, rel=1e-3)


def test_serialize_table_normal_column_still_rounds():
    out = _serialize_table(pd.DataFrame({"v": [0.12345678]}))
    assert out["data"][0][0] == 0.1235


def test_serialize_table_inf_and_nan_still_safe():
    out = _serialize_table(pd.DataFrame({"v": [np.inf, -np.inf, np.nan, 1.0]}))
    assert out["data"][0][0] == ""
    assert out["data"][1][0] == ""
    assert out["data"][2][0] == ""
    assert out["data"][3][0] == 1.0


def test_to_html_micro_values_not_zeroed(tmp_path):
    from smartsuite.services.reporter import to_html

    res = AnalysisResult(
        task="trend_forecast",
        status="ok",
        summary="s",
        tables={"预测": pd.DataFrame({"预测值": [9.827e-11, 4.1e-11]})},
    )
    path = to_html(res, str(tmp_path / "report.html"))
    text = Path(path).read_text(encoding="utf-8")
    assert "9.827e-11" in text, "HTML 报告不得把微尺度值吞成 0.0000"


def test_app_js_fmt_cell_num_execution():
    """E-3：不止 grep 字符串——用 node 实际执行 fmtCellNum 验证量级自适应分支。"""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用（GitHub runner 自带；本地未安装时跳过）")
    js = _APP_JS.read_text(encoding="utf-8")
    start = js.index("function fmtCellNum")
    end = js.index("\n}", start) + 2
    script = (
        js[start:end] + "\nconsole.log(JSON.stringify([fmtCellNum(9.827e-11), fmtCellNum(0.123456),"
        " fmtCellNum(0), fmtCellNum('N/A')]));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    vals = json.loads(out.stdout)
    assert vals[0] == "9.827e-11", f"微尺度应走指数分支: {vals[0]}"
    assert vals[1] == "0.1235", f"常规数值应 4 位小数: {vals[1]}"
    assert vals[2] == "0.0000", f"零值显示: {vals[2]}"
    assert vals[3] == "N/A", f"非数值应原样返回: {vals[3]}"


# ── C-1: max_outliers=inf ──────────────────────────────────────────────────
def test_grubbs_max_outliers_inf_chinese_error():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"y": rng.normal(0, 1, 30)})
    r = anomaly_detect(
        AnalysisRequest(
            task="anomaly_detect",
            data=df,
            target_col="y",
            feature_cols=[],
            params={"method": "grubbs", "max_outliers": float("inf")},
        )
    )
    assert r.status == "error"
    assert any("max_outliers" in m for m in r.messages)


# ── C-2: sw_p 精确 0.0 ─────────────────────────────────────────────────────
def test_sw_p_exact_zero_not_shown_as_na(monkeypatch):
    import smartsuite.engine.root_cause as rc
    from smartsuite.engine.root_cause import distribution as rc_distribution

    # 2026-09-19 拆分：sp_stats 绑定在 distribution 子模块（patch scipy.stats.shapiro 本身）
    monkeypatch.setattr(rc_distribution.sp_stats, "shapiro", lambda data: (0.9, 0.0))
    df = pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0]})
    r = rc.distribution_summary(
        AnalysisRequest(task="distribution_summary", data=df, target_col="y", feature_cols=[])
    )
    val = r.tables["descriptive_stats"].loc["Shapiro-Wilk p", "值"]
    assert val == 0.0, f"精确 p=0.0 不应显示为 N/A: {val!r}"


# ── C-3: _std_beta / _desirability ─────────────────────────────────────────
def test_regression_std_beta_micro_scale():
    rng = np.random.default_rng(5)
    x = rng.uniform(1, 10, 50)
    y = 1e-10 * (1 + 0.5 * x + 0.05 * rng.standard_normal(50))

    def run(x_scale, y_scale):
        df = pd.DataFrame({"x": x * x_scale, "y": y * y_scale})
        return regression_analysis(
            AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
        )

    macro = run(1.0, 1e10)
    micro_y = run(1.0, 1.0)
    micro_y_lo = run(1.0, 0.1)  # y_std≈1.4e-11 < 旧阈值 1e-10 → 直接命中 y_std 分支
    micro_x = run(1e-11, 1e10)
    base = float(macro.tables["coefficients"].set_index("变量").loc["x", "标准化系数(β)"])
    assert abs(base) > 0.1, "前置：宏观标准化系数应有非零值"
    for label, r in (
        ("y 微尺度", micro_y),
        ("y 微尺度(跨阈值)", micro_y_lo),
        ("x 微尺度", micro_x),
    ):
        beta = float(r.tables["coefficients"].set_index("变量").loc["x", "标准化系数(β)"])
        assert beta == pytest.approx(base, rel=1e-6), f"{label} β 偏离"


def test_desirability_micro_range_scale_invariant():
    from smartsuite.engine.doe_opt.optimization import _desirability

    base = np.array([1.0, 2.0, 3.0])
    macro = _desirability(base, "maximize")
    micro = _desirability(base * 1e-12, "maximize")
    assert np.allclose(micro, macro, atol=1e-9)


# ── D-1: 显式拒绝/静默弱化的同族点 ────────────────────────────────────────
def test_anomaly_detect_zscore_micro_scale_detects():
    r = anomaly_detect(
        AnalysisRequest(
            task="anomaly_detect",
            data=_spike_df(1.0),
            target_col="y",
            feature_cols=[],
            params={"method": "zscore"},
        )
    )
    assert r.status == "ok", f"微尺度 zscore 不得显式拒绝: {r.messages}"
    assert r.metadata["anomaly_count"] >= 1


def test_outlier_consensus_micro_scale_zscore_counts():
    r = outlier_consensus(
        AnalysisRequest(
            task="outlier_consensus", data=_spike_df(1.0), target_col="y", feature_cols=[]
        )
    )
    assert r.status == "ok"
    assert r.metadata["zscore_count"] >= 1, "微尺度 z 分数被 +EPSILON 压低 → 静默漏检"


def test_gage_rr_micro_scale_matches_macro():
    def run(scale):
        return gage_rr(
            AnalysisRequest(
                task="gage_rr",
                data=_gage_df(scale),
                target_col="m",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        )

    macro, micro = run(1.0), run(1e-12)
    assert micro.status == "ok", f"微尺度测量数据被误判零变异: {micro.messages}"
    assert micro.metadata["grr_sv"] == pytest.approx(macro.metadata["grr_sv"], rel=1e-6)


def test_tolerance_interval_micro_scale_bounds_scale():
    def run(scale):
        rng = np.random.default_rng(9)
        df = pd.DataFrame({"y": (10 + rng.standard_normal(100)) * scale})
        return tolerance_interval(
            AnalysisRequest(
                task="tolerance_interval",
                data=df,
                target_col="y",
                feature_cols=[],
                params={"coverage": 0.99, "confidence": 0.95},
            )
        )

    macro, micro = run(1.0), run(1e-12)
    assert micro.status == "ok", f"微尺度数据被误判零标准差: {micro.messages}"
    assert micro.metadata["lower"] == pytest.approx(macro.metadata["lower"] * 1e-12, rel=1e-6)
    assert micro.metadata["upper"] == pytest.approx(macro.metadata["upper"] * 1e-12, rel=1e-6)


def test_cusum_ewma_micro_scale_not_skipped():
    rng = np.random.default_rng(4)
    df = pd.DataFrame({"y": 10 + 1e-13 * rng.standard_normal(50)})
    for task, func in (("spc_cusum", cusum_chart), ("spc_ewma", ewma_chart)):
        r = func(AnalysisRequest(task=task, data=df, target_col="y", feature_cols=[], params={}))
        assert r.status == "ok", f"{task} 微尺度分组被误判零方差: {r.messages}"


# ── D-2: 除法防护的同族点 ─────────────────────────────────────────────────
def test_durbin_watson_scale_invariant():
    rng = np.random.default_rng(0)
    resid = 0.5 * rng.standard_normal(50)
    assert durbin_watson(resid * 1e-9) == pytest.approx(durbin_watson(resid), rel=1e-9)


def test_hypothesis_correlation_micro_scale_matches_macro():
    rng = np.random.default_rng(6)
    x = rng.uniform(1, 10, 60)
    y = 0.8 * x + rng.standard_normal(60)

    def run(scale):
        df = pd.DataFrame({"x": x * scale, "y": y * scale})
        return hypothesis_test(
            AnalysisRequest(
                task="hypothesis_test",
                data=df,
                target_col="y",
                feature_cols=["x"],
                params={"test": "correlation"},
            )
        )

    macro, micro = run(1.0), run(1e-11)
    assert micro.status == "ok", f"微尺度相关不应报常量列: {micro.messages}"
    assert float(micro.metadata["effect_size"]) == pytest.approx(
        float(macro.metadata["effect_size"]), rel=1e-9
    )


def test_ttest_1samp_micro_scale_effect_matches_macro():
    rng = np.random.default_rng(8)
    base = 10 + rng.normal(0, 1, 40)

    def run(scale):
        r = hypothesis_test(
            AnalysisRequest(
                task="hypothesis_test",
                data=pd.DataFrame({"y": base * scale}),
                target_col="y",
                feature_cols=[],
                params={"test": "ttest_1samp", "popmean": 0.0},
            )
        )
        return float(r.metadata["effect_size"])

    d_macro, d_micro = run(1.0), run(1e-11)
    assert abs(d_macro) > 1.0
    assert d_micro == pytest.approx(d_macro, rel=1e-6), "微尺度 d 被 +EPSILON 稀释"


def test_ttest_paired_micro_scale_effect_matches_macro():
    rng = np.random.default_rng(12)
    a = 10 + rng.normal(0, 1, 40)
    b = a + 0.8 + rng.normal(0, 0.2, 40)

    def run(scale):
        r = hypothesis_test(
            AnalysisRequest(
                task="hypothesis_test",
                data=pd.DataFrame({"before": a * scale, "after": b * scale}),
                target_col="after",
                feature_cols=["before", "after"],
                params={"test": "ttest_paired"},
            )
        )
        return float(r.metadata["effect_size"])

    d_macro, d_micro = run(1.0), run(1e-11)
    assert abs(d_macro) > 1.0
    assert d_micro == pytest.approx(d_macro, rel=1e-6), "微尺度配对 d 被 +EPSILON 稀释"


def test_distribution_summary_cv_zero_mean_not_absurd():
    df = pd.DataFrame({"y": [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]})
    r = distribution_summary(
        AnalysisRequest(task="distribution_summary", data=df, target_col="y", feature_cols=[])
    )
    cv = float(r.tables["descriptive_stats"].loc["CV(%)", "值"])
    assert math.isnan(cv) or abs(cv) < 1e4, f"均值精确为 0 时 CV 不应爆表: {cv}"


def test_cronbach_alpha_micro_scale_matches_macro():
    rng = np.random.default_rng(13)
    latent = rng.normal(0, 1, 100)
    items = pd.DataFrame(
        {
            "q1": latent + rng.normal(0, 0.5, 100),
            "q2": latent + rng.normal(0, 0.5, 100),
            "q3": latent + rng.normal(0, 0.5, 100),
        }
    )

    def run(scale):
        r = cronbach_alpha(
            AnalysisRequest(
                task="cronbach_alpha",
                data=items * scale,
                target_col="q1",
                feature_cols=["q1", "q2", "q3"],
            )
        )
        return r

    macro, micro = run(1.0), run(1e-12)
    assert micro.status == "ok", f"微尺度量表数据被误判零方差: {micro.messages}"
    assert float(micro.metadata["alpha"]) == pytest.approx(float(macro.metadata["alpha"]), rel=1e-9)


def test_trend_forecast_mape_micro_scale_computed():
    rng = np.random.default_rng(14)
    y = 1 + 0.5 * np.arange(50) + 0.1 * rng.standard_normal(50)

    def mape(scale):
        r = trend_forecast(
            AnalysisRequest(
                task="trend_forecast",
                data=pd.DataFrame({"y": y * scale}),
                target_col="y",
                feature_cols=[],
                params={},
            )
        )
        rows = r.tables["accuracy_metrics"]
        return rows.set_index("指标").loc["MAPE (%)", "值"]

    macro_txt, micro_txt = mape(1.0), mape(1e-11)
    assert micro_txt != "N/A", "微尺度 MAPE 被 |y|>EPSILON 掩码整体排除"
    assert float(str(micro_txt).rstrip("%")) == pytest.approx(
        float(str(macro_txt).rstrip("%")), rel=1e-3
    )


def test_we_rules_micro_sigma_detects_violation():
    from smartsuite.engine.spc_charts.we_rules import _we_rules_xbar

    cl, sigma = 5e-13, 1e-13
    vals = np.full(20, cl)
    vals[10] = cl + 5 * sigma
    violations = _we_rules_xbar(vals, cl, sigma)
    assert violations.get("规则1: 超出±3σ"), "sigma 被绝对下限抬高 → 超过 3σ 的微尺度点未检出"


def test_we_rules_zero_sigma_no_false_violations():
    """退化 σ=0（组内子组均值全同）→ 不得让 `abs(x-cl) >= 1σ` 的全量误报（Rule 8）。"""
    from smartsuite.engine.spc_charts.we_rules import _we_rules_xbar

    assert _we_rules_xbar(np.full(20, 5.0), 5.0, 0.0) == {}
    assert _we_rules_xbar(np.full(20, 5.0), 5.0, float("nan")) == {}
