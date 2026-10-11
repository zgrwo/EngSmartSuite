"""微尺度防护回归测试 — 绝对阈值同族 + 展示层 + 哨兵补齐。

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
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine import (
    anomaly_detect,
    bootstrap_ci,
    box_chart,
    cronbach_alpha,
    cusum_chart,
    distribution_summary,
    ewma_chart,
    gage_rr,
    grid_search,
    hypothesis_test,
    median_ci,
    outlier_consensus,
    regression_analysis,
    spc_nonparametric,
    survival_analysis,
    tolerance_interval,
    trend_forecast,
    xbar_r_chart,
)
from smartsuite.engine._utils import durbin_watson, shapiro_p
from smartsuite.services.orchestrator import orchestrate
from smartsuite.web.api import _serialize_table

_APP_JS = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web" / "static" / "app.js"


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


def test_shapiro_p_constant_column_returns_one_without_warning():
    """shapiro_p 常量列短路：scipy 1.15/1.17 会发「range zero」UserWarning，必须提前拦截。

    非退化输入与 scipy 原生结果逐值一致（回归护栏）。
    """
    constant = pd.Series([5.0] * 20)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert shapiro_p(constant) == 1.0

    rng = np.random.default_rng(0)
    sample = pd.Series(rng.normal(size=30))
    assert shapiro_p(sample) == pytest.approx(float(sp_stats.shapiro(sample)[1]), rel=1e-12)


def test_shapiro_p_non_finite_result_is_not_faked_as_normal():
    """scipy 无法计算时不得把 NaN 伪造成 `1.0`（审查 2026-10-09 P0-3）。

    `1.0` 的语义是「无方差 → 不拒绝正态」；把「无法计算（Σy² 溢出）」也映射成 1.0，
    会让**强非正态**数据被判「满足正态性」—— 判决随量级翻转（1e152 非正态、
    1e153 正态），用户据此免做数据变换。正确语义：无法计算 → `NaN`（不可判定），
    由调用方显式处置（不得伪造 0.0/1.0，见 skills/smartsuite-dev.md 陷阱 9 规则 2）。
    """
    rng = np.random.default_rng(11)
    skewed = rng.exponential(scale=4.0, size=200) + 1.0  # 强右偏，绝非正态

    p_macro = shapiro_p(pd.Series(skewed))
    assert np.isfinite(p_macro) and p_macro < 0.01, f"前置：常规量级应判强非正态，实际 {p_macro}"

    p_huge = shapiro_p(pd.Series(skewed * 1e155))
    assert not np.isfinite(p_huge), (
        f"1e155 量级下 scipy 返回 NaN（Σy² 溢出），shapiro_p 不得返回 {p_huge!r}"
    )


@pytest.mark.parametrize("bad", [np.inf, -np.inf, np.nan])
def test_shapiro_p_non_finite_input_is_undetermined(bad):
    """含 ±Inf/NaN 的数据无法判定正态性，不得回落到「正态」。"""
    assert not np.isfinite(shapiro_p(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, bad])))


@pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:Precision loss occurred:RuntimeWarning")
def test_normality_check_does_not_fake_normal_at_overflow_scale():
    """端到端：同一强右偏数据放大到 1e155 后，不得改口说「满足正态性」。

    ⚠️ 必须显式放宽 RuntimeWarning（同本文件 `test_hedges_g_zero_variance_warns_not_silent`
    的处置）：`pyproject.toml` 的 `filterwarnings = ["error", ...]` 只作用于 pytest，
    生产（Web/CLI）不会把 numpy 的 `invalid value encountered` 升为异常。不加这两行时
    本用例会**空过** —— 实测同一输入在 pytest 下走的是「未归类的异常」分支
    （status=error、summary 为空），于是"不得声称正态"的断言恒真。这本身就是
    P0-6 同一条假绿通道，故此处显式声明为生产口径。

    ## 2026-10-09 更新（审查 P1-4）：期望从「出结果」改为「B0 拒绝」

    本用例原先断言 `huge.status == "ok"` 且只是"不得声称正态" —— 那是**量级上界
    尚无守卫**时的现状记录。P1-4 落地后，`normality_check` 入口调用了
    `_guard.check_magnitude`（`log10(max|y|) > 150` → `E_SCALE_EXTREME_MAGNITUDE`），
    1e155 属**必须拒绝**的量级（该量级下 `Σy²` 溢出为 Inf，判决随量级翻转：
    实测同一份偏度 1.4547 的数据 1e152 判非正态、1e153 判正态）。
    故期望改为：**要么 B0 拒绝并说明量级原因，要么出结果且不得声称正态** ——
    两者都满足"不得伪造正态"这一原始意图，且拒绝路径必须给出可执行建议。
    """
    rng = np.random.default_rng(11)
    skewed = rng.exponential(scale=4.0, size=200) + 1.0

    def run(scale):
        df = pd.DataFrame({"v": skewed * scale})
        return orchestrate(
            AnalysisRequest(
                task="normality_check", data=df, target_col="v", feature_cols=[], params={}
            )
        )

    small = run(1.0)
    huge = run(1e155)
    assert small.status == "ok" and "0/1 列满足正态性" in small.summary, small.summary
    blob = " ".join(huge.messages or [])
    if huge.status == "error":
        assert "量级" in blob, f"拒绝理由必须指向量级（否则用户排查不到真因）：{huge.messages}"
        assert "单位换算" in blob or "中心化" in blob, f"B0 拒绝须给可执行建议：{huge.messages}"
    else:
        assert "1/1 列满足正态性" not in huge.summary, f"溢出量级不得被判为正态：{huge.summary}"

    # ── B-4: 微尺度常量判据 ────────────────────────────────────────────────────def test_trend_forecast_pico_scale_not_constant():
    """pico 级波动不得被误判常量，且统计量随量纲同比缩放（审查 2026-09-22 发现 6）。"""

    def run(scale):
        rng = np.random.default_rng(2)
        df = pd.DataFrame({"y": (5.0 + 1.0 * rng.standard_normal(50)) * scale})
        return trend_forecast(
            AnalysisRequest(
                task="trend_forecast", data=df, target_col="y", feature_cols=[], params={}
            )
        )

    macro, micro = run(1.0), run(1e-13)
    assert micro.status == "ok", f"pico 级真实波动被误判常量: {micro.messages}"
    assert micro.metadata["slope"] == pytest.approx(macro.metadata["slope"] * 1e-13, rel=1e-6)
    assert micro.metadata["intercept"] == pytest.approx(
        macro.metadata["intercept"] * 1e-13, rel=1e-6
    )


def test_spc_xbar_pico_scale_not_constant():
    """控制限随量纲同比缩放（旧实现绝对阈值下 pico 级被整列跳过）。"""

    def run(scale):
        rng = np.random.default_rng(2)
        df = pd.DataFrame({"y": (5.0 + 1.0 * rng.standard_normal(50)) * scale})
        return xbar_r_chart(
            AnalysisRequest(task="spc_xbar", data=df, target_col="y", feature_cols=[], params={})
        )

    macro, micro = run(1.0), run(1e-13)
    assert micro.status == "ok", f"pico 级真实波动被误判常量: {micro.messages}"
    assert micro.metadata["ucl_x"] == pytest.approx(macro.metadata["ucl_x"] * 1e-13, rel=1e-6)
    assert micro.metadata["lcl_x"] == pytest.approx(macro.metadata["lcl_x"] * 1e-13, rel=1e-6)
    assert micro.metadata["xbar_mean"] == pytest.approx(
        macro.metadata["xbar_mean"] * 1e-13, rel=1e-6
    )


def test_spc_nonparametric_pico_scale_not_constant():
    """非参数控制限同样必须随量纲缩放，不得被常量判据吞掉。"""

    def run(scale):
        rng = np.random.default_rng(2)
        df = pd.DataFrame({"y": (5.0 + 1.0 * rng.standard_normal(50)) * scale})
        return spc_nonparametric(
            AnalysisRequest(
                task="spc_nonparametric", data=df, target_col="y", feature_cols=[], params={}
            )
        )

    macro, micro = run(1.0), run(1e-13)
    assert micro.status == "ok", f"pico 级真实波动被误判常量: {micro.messages}"
    assert micro.metadata["ucl"] == pytest.approx(macro.metadata["ucl"] * 1e-13, rel=1e-6)
    assert micro.metadata["lcl"] == pytest.approx(macro.metadata["lcl"] * 1e-13, rel=1e-6)
    assert micro.metadata["cl"] == pytest.approx(macro.metadata["cl"] * 1e-13, rel=1e-6)


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
    """E-3：不止 grep 字符串——用 node 实际执行 fmtCellNum 验证量级自适应分支。

    审查 2026-09-24（P3-3）：`fmtCellNum` 已迁至 `util.js` 并成为模块导出
    （`export function`）。本用例相应改为：在 static/ 下全部 JS 中定位该函数，
    并剥离 `export` 关键字后再交给 `node -e`（脚本模式下 `export` 是语法错误）。
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用（GitHub runner 自带；本地未安装时跳过）")
    static = _APP_JS.parent
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(static.glob("*.js")))
    marker = "function fmtCellNum"
    assert marker in js, f"未在 static/*.js 中找到 {marker}"
    start = js.index(marker)
    end = js.index("\n}", start) + 2
    func = js[start:end]
    script = (
        func + "\nconsole.log(JSON.stringify([fmtCellNum(9.827e-11), fmtCellNum(0.123456),"
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
    # P4 步骤③（第二十四轮）：参数校验改抛异常 → 经编排层取用户可见结果
    r = orchestrate(
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
    """微尺度不得被误判零方差：EWMA 控制限同比缩放、CUSUM 报警数不变。"""
    rng = np.random.default_rng(4)
    base = np.concatenate([rng.normal(0, 1, 25), rng.normal(3, 1, 25)])

    def run(scale):
        df = pd.DataFrame({"y": base * scale})
        c = cusum_chart(
            AnalysisRequest(task="spc_cusum", data=df, target_col="y", feature_cols=[], params={})
        )
        e = ewma_chart(
            AnalysisRequest(task="spc_ewma", data=df, target_col="y", feature_cols=[], params={})
        )
        return c, e

    c_macro, e_macro = run(1.0)
    c_micro, e_micro = run(1e-13)
    assert c_micro.status == "ok" and e_micro.status == "ok", (
        f"微尺度分组被误判零方差: cusum={c_micro.messages}, ewma={e_micro.messages}"
    )
    assert c_micro.metadata["total_alarms"] == c_macro.metadata["total_alarms"]
    assert e_micro.metadata["ucl_asym"] == pytest.approx(
        e_macro.metadata["ucl_asym"] * 1e-13, rel=1e-6
    )
    assert e_micro.metadata["lcl_asym"] == pytest.approx(
        e_macro.metadata["lcl_asym"] * 1e-13, rel=1e-6
    )


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


# ── R1-3（2026-09-21 审查）：box_chart / grid_search 构建期固定位舍入 ──────────
# 固定位 round(x, 3/4) 在**数据构建期**执行（非展示期），把微尺度有效值直接截为
# 0.0。修复前实测：box_chart 分组统计整表 0.0；grid_search optimal_params 由真实
# 500/70 变为 {温度: 0.0, 压力: 0.0}（推荐工艺参数被销毁）。
def test_box_chart_micro_scale_group_stats_scale_with_magnitude():
    rng = np.random.default_rng(3)
    n = 60
    macro = rng.normal(5.0, 1.0, n)
    groups = ["A", "B"] * (n // 2)

    def run(values):
        df = pd.DataFrame({"y": values, "g": groups})
        return box_chart(
            AnalysisRequest(
                task="box_chart", data=df, target_col="y", feature_cols=["g"], params={}
            )
        )

    r_macro = run(macro)
    r_micro = run(macro * 1e-9)
    assert r_macro.status == "ok" and r_micro.status == "ok", (r_macro.messages, r_micro.messages)
    t_macro = r_macro.tables["group_statistics"]
    t_micro = r_micro.tables["group_statistics"]
    for col in ("均值", "中位数", "标准差", "IQR", "最小值", "最大值"):
        macro_v = float(t_macro[col].iloc[0])
        micro_v = float(t_micro[col].iloc[0])
        assert micro_v != 0.0, f"{col} 在 ×1e-9 下被舍入为 0.0（整表归零）"
        assert micro_v == pytest.approx(macro_v * 1e-9, rel=0.02), f"{col} 未随量纲同比缩放"


def test_box_chart_stats_table_match_group_statistics_at_micro_scale():
    """box_chart 统计表必须与 group_statistics 表逐位一致（微尺度不归零）。

    对应陷阱 9「展示层二次舍入」：表格若用固定 `:g`，对 1e6 量级只留 6 位有效数字，
    微尺度靠科学计数；实现走与结果表同口径的展示格式化。
    """
    rng = np.random.default_rng(11)
    n = 40
    df = pd.DataFrame({"y": rng.normal(5.0, 1.0, n) * 1e-9, "g": ["A", "B"] * (n // 2)})
    r = box_chart(
        AnalysisRequest(task="box_chart", data=df, target_col="y", feature_cols=["g"], params={})
    )
    assert r.status == "ok", r.messages
    ax = r.figures[0].axes[0]
    assert len(ax.tables) == 1, "统计值应汇总为一张表"
    table = ax.tables[0]
    stats = r.tables["group_statistics"]
    row_keys = ["样本量", "均值", "标准差", "最大值", "最小值"]
    for i, (_, row) in enumerate(stats.iterrows()):
        for r_idx, col in enumerate(row_keys):
            shown = float(table[(r_idx, i + 1)].get_text().get_text())
            expected = float(row[col])
            if col == "样本量":
                assert shown == expected, f"第 {i + 1} 列 n 与统计表不一致: {shown} != {expected}"
                continue
            assert shown != 0.0, f"第 {i + 1} 列「{col}」在微尺度下归零"
            assert shown == pytest.approx(expected, rel=1e-6), (
                f"第 {i + 1} 列「{col}」表格值 {shown} 与统计表 {expected} 不一致"
            )


def test_grid_search_micro_scale_optimal_params_scale_with_magnitude():
    rng = np.random.default_rng(3)
    n = 80
    factors = ["温度", "压力"]

    def run(scale):
        x1 = rng.uniform(400, 500, n) * scale
        x2 = rng.uniform(50, 70, n) * scale
        y = (200 + 0.05 * (x1 / scale) + 0.3 * (x2 / scale) + rng.normal(0, 0.1, n)) * scale
        df = pd.DataFrame({"温度": x1, "压力": x2, "强度": y})
        params = {
            "ranges": {"温度": [400 * scale, 500 * scale], "压力": [50 * scale, 70 * scale]},
            "direction": "maximize",
            "n_points": 10,
        }
        return grid_search(
            AnalysisRequest(
                task="grid_search", data=df, target_col="强度", feature_cols=factors, params=params
            )
        )

    r_macro = run(1.0)
    r_micro = run(1e-9)
    assert r_macro.status == "ok" and r_micro.status == "ok", (r_macro.messages, r_micro.messages)
    for key in factors:
        macro_v = float(r_macro.metadata["optimal_params"][key])
        micro_v = float(r_micro.metadata["optimal_params"][key])
        assert micro_v != 0.0, f"推荐参数 {key} 在 ×1e-9 下被舍入为 0.0（可执行结论被销毁）"
        assert micro_v == pytest.approx(macro_v * 1e-9, rel=0.05), f"推荐参数 {key} 未随量纲缩放"


# ── D-4（2026-09-21 审查）：IsolationForest 量纲敏感 → 微尺度静默零检出 ────────
def test_anomaly_detect_isolation_forest_scale_invariant():
    """多变量异常检出数必须与量纲无关（×1e-9 不得静默归零）。

    修复前实测：同一数据 scale 1e0…1e-7 恒检出 6 个，1e-9/1e-12 骤降为 0，
    且 status=ok 无任何提示。根因是 IsolationForest 直接吃原始特征值，
    未做标准化。修复=入模型前 StandardScaler。
    """
    rng = np.random.default_rng(1)
    base = np.concatenate([rng.normal(0, 1, 100), [8.0, -8.0]])
    noise = rng.normal(0, 0.1, 102)

    def run(scale):
        df = pd.DataFrame({"x": base * scale, "y": (base * 2 + noise) * scale})
        return anomaly_detect(
            AnalysisRequest(
                task="anomaly_detect",
                data=df,
                target_col="",
                feature_cols=["x", "y"],
                params={"method": "isolation_forest"},
            )
        )

    counts = {}
    for scale in (1.0, 1e-7, 1e-9, 1e-12, 1e12):
        r = run(scale)
        assert r.status == "ok", (scale, r.messages)
        counts[scale] = r.metadata["anomaly_count"]
    assert counts[1.0] > 0, "宏观量级应检出强异常点（±8σ）"
    assert len(set(counts.values())) == 1, f"检出数随量纲变化（微尺度静默归零）: {counts}"


def test_outlier_consensus_isolation_vote_scale_invariant():
    """outlier_consensus 的 IsolationForest 投票同样必须量纲无关。"""
    rng = np.random.default_rng(1)
    base = np.concatenate([rng.normal(0, 1, 100), [8.0, -8.0]])

    def run(scale):
        df = pd.DataFrame({"y": base * scale})
        return outlier_consensus(
            AnalysisRequest(
                task="outlier_consensus",
                data=df,
                target_col="y",
                feature_cols=[],
                params={},
            )
        )

    r_macro, r_micro = run(1.0), run(1e-9)
    assert r_macro.status == "ok" and r_micro.status == "ok", (r_macro.messages, r_micro.messages)
    t_macro = r_macro.tables.get("consensus") or next(iter(r_macro.tables.values()))
    t_micro = r_micro.tables.get("consensus") or next(iter(r_micro.tables.values()))
    assert len(t_macro) == len(t_micro), "异常共识条数随量纲变化"


# ── C-1 / R2BD-06（2026-10-09 二轮全量审查）：微尺度**展示通道**不得塌缩 ──────
# 报告：logs/reports/2026-10-09-review-r2-ac.md 的 C-1（P1）、
#      logs/reports/2026-10-09-review-r2-bd.md 的 R2BD-06（P2）。
#
# 缺陷形态：×1e-9 时 `summary`、图例/标题、以及"先格式化再放进表"的字符串单元格
# 走 `f"{x:.4f}"` 手写定点格式 → 整段吞成 `0.0000`；而**同一次分析**的数值列
# （`round_for_display`）已是科学计数 → 用户看到两套互相矛盾的数值口径。
#
# 断言口径：任一用户可见文本通道都不得出现 `0.0000` / `0.000`。选用数据（n=60、
# μ≈5e-9）上没有任何统计量真值为 0，故"零值"不是竞争解释；同时逐任务把 summary
# 里抽出的数值与 `metadata` 的**真值**对拍（跨通道一致性，不依赖具体量级）。
#
# 回归防线对应实现：`engine/_utils.disp`（与 `round_for_display` 共用
# `_is_micro_scale` 阈值，见该函数 docstring）。
_MICRO_SCALE = 1e-9


def _micro_frame(seed: int = 2, n: int = 60) -> pd.DataFrame:
    """微尺度（ppb 级）工艺数据：μ≈5e-9、σ≈1e-9，形态与常规量级完全同构。"""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"y": (5.0 + rng.standard_normal(n)) * _MICRO_SCALE})


def _req(task: str, df: pd.DataFrame, params: dict | None = None) -> AnalysisRequest:
    return AnalysisRequest(task=task, data=df, target_col="y", feature_cols=[], params=params or {})


def _capability_micro(df: pd.DataFrame):
    """过程能力：规格限/目标值必须与数据同比缩放，否则指标本身无意义。"""
    return orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=df,
            target_col="y",
            feature_cols=[],
            params={
                "usl": 8.0 * _MICRO_SCALE,
                "lsl": 2.0 * _MICRO_SCALE,
                "target": 5.0 * _MICRO_SCALE,
            },
        )
    )


_MICRO_RUNNERS = {
    "distribution_summary": lambda df: distribution_summary(_req("distribution_summary", df)),
    "spc_xbar": lambda df: xbar_r_chart(_req("spc_xbar", df)),
    "spc_nonparametric": lambda df: spc_nonparametric(_req("spc_nonparametric", df)),
    "trend_forecast": lambda df: trend_forecast(_req("trend_forecast", df)),
    "tolerance_interval": lambda df: tolerance_interval(
        _req("tolerance_interval", df, {"coverage": 0.99, "confidence": 0.95})
    ),
    "process_capability": _capability_micro,
    "median_ci": lambda df: median_ci(_req("median_ci", df)),
    "bootstrap_ci": lambda df: bootstrap_ci(_req("bootstrap_ci", df, {"n_bootstrap": 200})),
}


def _visible_texts(res) -> list[str]:
    """收集一个 `AnalysisResult` 的**全部用户可见文本通道**（summary / 表 / 图）。

    ⚠️ 表单元格**必须带行标签**（`表名[行].列=值`）——2026-10-10 修：
    原写法只出 `表名.列=值`，把**行**丢了，于是调用方无法区分
    「均值被固定小数位吞成 0」和「偏度本来就恰好是 0」。3.10 腿就因此在
    `process_capability` 上假红（见 `_ZERO_IS_LEGITIMATE_ROWS`）。
    """
    out = [f"summary: {res.summary}"]
    for name, frame in (res.tables or {}).items():
        for idx, row in frame.iterrows():
            for col in frame.columns:
                out.append(f"{name}[{idx}].{col}={row[col]}")
    for fig in res.figures or []:
        for ax in fig.axes:
            out.extend([ax.get_title(), ax.get_xlabel(), ax.get_ylabel()])
            legend = ax.get_legend()
            if legend is not None:
                out.extend(t.get_text() for t in legend.get_texts())
            out.extend(t.get_text() for t in ax.texts)
    return out


#: **「0 是合法值」的统计量**：无量纲形状量。
#:
#: 为什么必须豁免（2026-10-10，三条 3.10 腿假红后定位）：
#: `process_capability` 的 `descriptive_stats` 表里，偏度/峰度按项目既定口径
#: 用固定小数位（`capability.py:717-718` 注释：「偏度/峰度是无量纲形状量」）。
#: 而 pandas 2.x 分叉上，×1e-9 数据的**三/四阶矩会下溢**（`(x-μ)³ ~ 1e-27`，
#: 相减后有效位丢失）⇒ `skew()` / `kurtosis()` 返回恰好 0 ⇒ 渲染 `0.0000`。
#: 这**不是显示层塌缩**（显示忠实反映了算出来的 0），而是统计量本身的数值精度问题。
#: 把"0.0000"一律当塌缩，等于要求无量纲量永远不等于 0 —— 那是错的断言。
_ZERO_IS_LEGITIMATE_ROWS = ("偏度", "峰度")


@pytest.mark.parametrize("task", sorted(_MICRO_RUNNERS))
def test_micro_scale_display_has_no_collapsed_zero(task):
    """×1e-9 下 summary / 表字符串单元格 / 图内文本均不得被吞成 `0.0000`。

    修复前实测（`disp` 接入之前）：
      distribution_summary: `y: μ=0.000, M=0.000, σ=0.000, CV=19.8%。`
      spc_xbar:            `X-bar CL=0.0000, UCL=0.0000, LCL=0.0000`
                           `control_limits` 整行 5 格全 `0.0000`
      spc_nonparametric:   `CL(P50)=0.0000, UCL=0.0000, LCL=0.0000`（图标题/图例同）
      trend_forecast:      `RMSE=0.0000`；表内 `RMSE/MAE/斜率/截距` 全 `0.0000`
      tolerance_interval:  `99% 总体以 95% 置信度落在 [0.0000, 0.0000]`（表 + 图例同）
    """
    res = _MICRO_RUNNERS[task](_micro_frame())
    assert res.status == "ok", res.messages
    bad = [
        t
        for t in _visible_texts(res)
        if ("0.0000" in t or "0.000" in t)
        # 无量纲形状量恰好为 0 是**合法值**，不是塌缩（理由见 _ZERO_IS_LEGITIMATE_ROWS）
        and not any(row in t for row in _ZERO_IS_LEGITIMATE_ROWS)
    ]
    assert not bad, f"{task} 在 ×{_MICRO_SCALE:g} 下展示塌缩为 0（固定小数位吞没微尺度值）: {bad}"


#: task → (summary 中抽取数值的正则, metadata 真值路径)
_MICRO_SUMMARY_PROBES: dict[str, tuple[str, str]] = {
    "distribution_summary": (r"μ", "descriptive.均值"),
    "spc_xbar": (r"CL", "xbar_mean"),
    "spc_nonparametric": (re.escape("CL(P50)"), "cl"),
    "trend_forecast": (r"RMSE", "rmse"),
    "median_ci": (r"中位数", "median"),
    "bootstrap_ci": (r"mean", "point_estimate"),
}


def _metadata_value(res, path: str) -> float:
    cur = res.metadata
    for part in path.split("."):
        cur = cur[part]
    return float(cur)


def _summary_number(summary: str, pattern: str) -> float:
    """按正则从 summary 抽取数值（`pattern` 须含一个捕获组；分隔符写法各任务不同）。"""
    match = re.search(pattern + r"\s*[:=]?\s*([-+]?[0-9.]+(?:[eE][-+]?\d+)?)", summary)
    assert match is not None, f"summary 中未找到模式「{pattern}」：{summary}"
    return float(match.group(1))


@pytest.mark.parametrize("task", sorted(_MICRO_SUMMARY_PROBES))
def test_micro_scale_summary_matches_metadata_value(task):
    """summary 里抽出的数值必须与 `metadata` 真值一致（跨通道一致性，量级无关）。

    这条把"两套口径"直接钉死：无论实现怎么改，摘要显示的数值与机器可读出口
    必须是同一个数。修复前 `spc_xbar` 的摘要 CL 为 0.0，而 `metadata["xbar_mean"]`
    是 5.08e-9 —— 两者相差 5×10⁹ 倍却同时呈现给用户。
    """
    pattern, path = _MICRO_SUMMARY_PROBES[task]
    res = _MICRO_RUNNERS[task](_micro_frame())
    assert res.status == "ok", res.messages
    shown = _summary_number(res.summary, pattern)
    assert shown == pytest.approx(_metadata_value(res, path), rel=1e-3), (
        f"{task} 摘要 {pattern}={shown} 与 metadata[{path}]={_metadata_value(res, path)} 不一致"
    )


def test_tolerance_interval_summary_bounds_match_metadata():
    """容许区间的摘要区间端点必须随量纲缩放且与 `metadata` 一致（C-1 同族）。"""
    res = _MICRO_RUNNERS["tolerance_interval"](_micro_frame())
    assert res.status == "ok", res.messages
    match = re.search(r"\[([-+0-9.eE]+), ([-+0-9.eE]+)\]", res.summary)
    assert match is not None, f"summary 中未找到区间：{res.summary}"
    lower, upper = float(match.group(1)), float(match.group(2))
    assert lower == pytest.approx(float(res.metadata["lower"]), rel=1e-3)
    assert upper == pytest.approx(float(res.metadata["upper"]), rel=1e-3)
    assert lower > 0.0 and upper > lower, f"微尺度区间被压平：{res.summary}"


def test_disp_formats_micro_scale_as_scientific_and_keeps_macro_unchanged():
    """共享展示格式化器 `disp` 的契约（`round_for_display` 的文本侧同源实现）。"""
    from smartsuite.engine._utils import disp

    # 微尺度 → 有效数字（科学计数），不再被固定小数位吞成 0
    assert disp(5.079471251645309e-09) == "5.079e-09"
    assert disp(-1.2345e-13) == "-1.234e-13"
    # 常规量级 → 与此前 `f"{x:.4f}"` 逐字一致（既有显示不受影响）
    assert disp(10.347291) == "10.3473"
    assert disp(0.123456) == "0.1235"
    # 真值 0 与不可判定值有明确显示语义，不得与"被吞掉"混淆
    assert disp(0.0) == "0.0000"
    assert disp(float("nan")) == "N/A"
    assert disp(float("inf")) == "+∞" and disp(float("-inf")) == "-∞"
    # decimals 同时是微尺度分支的有效数字位数（趋势表用 6 位）
    assert disp(5.013012e-10, 6) == "5.01301e-10"
    assert disp(0.501301, 6) == "0.501301"


# ══════════════════════════════════════════════════════════════
# 微尺度**量纲对抗**：展示层三通道（R2BD-06 / C-1 同族残留）
# ══════════════════════════════════════════════════════════════


def _survival_df(scale: float = 1.0) -> pd.DataFrame:
    """右删失寿命数据的微/宏观同构构造（**同一数组仅乘 `scale`**）。"""
    rng = np.random.default_rng(21)
    times = rng.weibull(2.0, 60) * 100.0 * scale
    events = (rng.random(60) < 0.7).astype(int)
    events[0] = 1
    return pd.DataFrame({"t": times, "e": events})


def _run_gage_rr(scale: float) -> AnalysisResult:
    return gage_rr(
        AnalysisRequest(
            task="gage_rr",
            data=_gage_df(scale),
            target_col="m",
            feature_cols=["part", "op"],
            params={"part_col": "part", "operator_col": "op"},
        )
    )


def _run_survival_analysis(scale: float) -> AnalysisResult:
    return survival_analysis(
        AnalysisRequest(
            task="survival_analysis",
            data=_survival_df(scale),
            target_col="t",
            feature_cols=["e"],
            params={},
        )
    )


#: task → 跑一次（入参 = 量纲缩放因子）。两个任务的 `summary` / 表内**字符串**单元格 /
#: 图内文本都曾用固定小数位手写格式化（`:.4f` / `:.6f` / `:.0f`），
#: 在 ×1e-9 下整段吞成 `0.0000` / `0`（审查 2026-10-09 R2BD-06 同族残留）。
_MICRO_CONTRAST_RUNNERS = {
    "gage_rr": _run_gage_rr,
    "survival_analysis": _run_survival_analysis,
}

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

#: 展示字符串判据的相对容差：渲染出来的文本只有 4~6 位有效数字，
#: **宏量级那一侧解析回来本身就带舍入**（`0.0260` ← 0.0259714、`0.000105` ← 1.048e-4），
#: 微尺度分支又按 `decimals` 位**有效数字**渲染（`disp(x, 3)` → `1.21e-07` ← 1.20715e-07，
#: 相对误差 ~2.4e-3）。故按 5% 判"同一个量"；而"被固定小数位吞成 0"是 **100%** 偏离，
#: 判别力不受影响。
_REL_TOL = 0.05

#: 宏量级就渲染成 0 的格子（合法零 / 被钳位的方差分量 / KM 曲线起点）在微尺度也必须为 0
#: （允许 < 1e-12 的浮点尘埃）。
_ABS_TOL = 1e-12


def _scale_law_holds(macro_val: float, micro_val: float) -> bool:
    """微/宏两个**展示值**是否符合量纲定律（不变量 / ×s / ×s²）。

    ⚠️ 判据做成**比值**而非"与期望值比"：`×s²` 分支的期望值本身在 ~1e-18 量级，
    若用绝对容差（如 1e-12）兜底，"塌缩成 0"会被误判为通过（本轮实测踩到过）。
    """
    if macro_val == 0.0:
        return abs(micro_val) <= _ABS_TOL
    ratio = micro_val / macro_val
    return any(
        abs(ratio - _MICRO_SCALE**power) <= _REL_TOL * _MICRO_SCALE**power for power in (0, 1, 2)
    )


def _numbers(text: str) -> list[float]:
    """抽出一段展示文本里的全部数字（含科学计数法）。"""
    return [float(m) for m in _NUM_RE.findall(str(text))]


def _channel_texts(res: AnalysisResult) -> dict[str, str]:
    """`AnalysisResult` 的**三个用户可见通道** → 逐条文本（键稳定，可逐条对齐）。

    summary / 表内单元格（含预格式化字符串）/ 图内文本（标题、轴标签、图例、图内标注）。
    与 `_visible_texts` 覆盖同一批通道，但**带键**，以便 macro↔micro 逐条比对
    （见 `test_micro_scale_channels_are_scale_covariant` 为何不用通用扫描）。
    """
    out: dict[str, str] = {"summary": str(res.summary)}
    for name, frame in (res.tables or {}).items():
        for col in frame.columns:
            for i, value in enumerate(frame[col].tolist()):
                out[f"{name}[{i}].{col}"] = str(value)
    for fi, fig in enumerate(res.figures or []):
        for ai, ax in enumerate(fig.axes):
            out[f"fig{fi}.ax{ai}.title"] = ax.get_title()
            out[f"fig{fi}.ax{ai}.xlabel"] = ax.get_xlabel()
            out[f"fig{fi}.ax{ai}.ylabel"] = ax.get_ylabel()
            legend = ax.get_legend()
            if legend is not None:
                for li, t in enumerate(legend.get_texts()):
                    out[f"fig{fi}.ax{ai}.legend{li}"] = t.get_text()
            for ti, t in enumerate(ax.texts):
                out[f"fig{fi}.ax{ai}.text{ti}"] = t.get_text()
    return out


@pytest.mark.parametrize("task", sorted(_MICRO_CONTRAST_RUNNERS))
def test_micro_scale_channels_are_scale_covariant(task):
    """×1e-9 下**每个**用户可见数字必须按量纲定律缩放（或本就是无量纲不变量）。

    判据（陷阱 9 的"量纲对抗"用在展示层）：同一数组乘 `s = 1e-9` 后，展示文本里的
    每个数字必须满足三者之一 ——

    - **无量纲不变量**：逐字相同（`%GRR`/`ndc`/`F`/`p`/贡献率/`%SV`/生存概率/
      Weibull β/自由度/样本量）；
    - **线性协变量**（`×s`）：带一次量纲的量 —— 标准差、`kσ` 研究变异、TV、
    - **平方协变量**（`×s²`）：**方差量** —— 均方（`SS/df`）、方差分量及其 95%CI
      （单位是量纲的平方，数据乘 1e-9 后它们乘 1e-18）。

    固定小数位手写格式化会让这些量塌缩成**恰好 0**（`0.0000` / `0.000000` / `0`），
    三个分支都不成立 → 逐条点名。**合法零不受影响**：宏量级就渲染成 0 的格子
    （`gage_rr` 的交互分量被合并钳位为 0、KM 曲线起点 `时间=0.0`）在微尺度仍为 0，
    走"不变量"分支通过 —— 这正是本判据不能用"含 `0.000` 子串"那种通用扫描的原因：

    - `gage_rr` 在**正确输出**下就有 `贡献率(%)=0.0`、`方差分量=0.000000`（合法 0）；
    - `survival_analysis` 在**正确输出**下就有 `km_survival[0].时间=0.0`（曲线起点）
      与 `生存概率=1.0000`（含子串 `0.000`）。

    两者若接进 `_MICRO_RUNNERS` 的通用扫描都会在**修复后**依旧变红（误报）。

    判据的已知边界（如实登记）：它把"整体不缩放"也视为合法（与"无量纲不变量"
    无法从文本区分），故它拦的是**展示塌缩**这一类缺陷，不拦"该缩放却没缩放"的整体性错误。

    修复前实测（×1e-9）：`gage_rr` 的 `标准差/5.2σ变异/均方/方差分量/95%CI/图内标注`
    与 `summary` 的 EV/AV/PV 全为 `0.0000`/`0.000000`/`0.000`；
    `survival_analysis` 的 `summary` 与图例 `Weibull (β=1.99, η=121)` 中 `η` 显示为 `0`。
    """
    macro = _MICRO_CONTRAST_RUNNERS[task](1.0)
    micro = _MICRO_CONTRAST_RUNNERS[task](_MICRO_SCALE)
    assert macro.status == "ok", macro.messages
    assert micro.status == "ok", micro.messages

    macro_channels, micro_channels = _channel_texts(macro), _channel_texts(micro)
    assert set(macro_channels) == set(micro_channels), (
        f"{task} 两次运行的通道结构不一致，判据无法逐条对齐："
        f"{sorted(set(macro_channels) ^ set(micro_channels))}"
    )
    collapsed: list[str] = []
    for key in sorted(macro_channels):
        macro_nums, micro_nums = _numbers(macro_channels[key]), _numbers(micro_channels[key])
        assert len(macro_nums) == len(micro_nums), (
            f"{task}.{key}: 数字个数变化 —— {macro_channels[key]!r} → {micro_channels[key]!r}"
        )
        for macro_val, micro_val in zip(macro_nums, micro_nums, strict=True):
            if not _scale_law_holds(macro_val, micro_val):
                collapsed.append(
                    f"{key}: {macro_val!r} → {micro_val!r}"
                    "（既非无量纲不变量、也未按 ×s 或 ×s² 缩放 —— 固定小数位把它吞成了 0）"
                )
    assert not collapsed, f"{task} 在 ×{_MICRO_SCALE:g} 下展示塌缩：\n  " + "\n  ".join(collapsed)
