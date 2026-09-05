"""review-2026-09-05 发版前审查修复回归测试。

对应 logs/reports/review-2026-09-05-release-prep.md 问题项：
C1(规格限 isfinite), B1(常量列相对阈值), B2(d2* 取 ∞ 列), C2(无效 group_col),
M-4(n_runs falsy), B3(微尺度阈值), E1(verify_docs tag 校验)。
每项先以对抗脚本复现（修复前基线），再随修复转绿。
"""

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest


def _mk(task, df, y, feats=None, params=None):
    return AnalysisRequest(
        task=task, data=df, target_col=y, feature_cols=feats or [], params=params or {}
    )


# ── C1: process_capability 规格限非有限值显式拒绝 ──────────────────


def test_capability_spec_limits_reject_inf():
    from smartsuite.engine.capability import process_capability_analysis

    np.random.seed(0)
    df = pd.DataFrame({"v": np.random.normal(50, 2, 100)})
    r = process_capability_analysis(
        _mk("process_capability", df, "v", params={"usl": "inf", "lsl": "-inf"})
    )
    assert r.status == "error", (
        f"inf 规格限应报错，实际 status={r.status}, cp={r.metadata.get('cp')}"
    )
    assert any("有限" in m for m in r.messages)


def test_capability_spec_limits_reject_nan():
    from smartsuite.engine.capability import process_capability_analysis

    np.random.seed(0)
    df = pd.DataFrame({"v": np.random.normal(50, 2, 100)})
    r = process_capability_analysis(
        _mk("process_capability", df, "v", params={"usl": 100, "lsl": "nan"})
    )
    assert r.status == "error", "lsl=nan 应报错，不应产出 cp=nan/cpk 荒谬值"
    assert any("LSL" in m for m in r.messages)


def test_capability_target_invalid_is_error_not_silent():
    from smartsuite.engine.capability import process_capability_analysis

    np.random.seed(0)
    df = pd.DataFrame({"v": np.random.normal(50, 2, 100)})
    for bad in ("nan", "inf", "abc"):
        r = process_capability_analysis(_mk("process_capability", df, "v", params={"target": bad}))
        assert r.status == "error", f"target={bad!r} 应报错（不再静默置 None）"
    # 合法规格限 + 目标值仍正常
    r = process_capability_analysis(
        _mk("process_capability", df, "v", params={"usl": 56, "lsl": 44, "target": 50})
    )
    assert r.status == "ok", r.messages


# ── B1: 常量列判定改相对阈值，微尺度数据不再误报 ────────────────────


def test_trend_forecast_micro_scale_not_constant():
    from smartsuite.engine.detection import trend_forecast

    np.random.seed(1)
    micro = pd.DataFrame({"v": 1e-10 + np.random.normal(0, 1e-13, 60)})
    r = trend_forecast(_mk("trend_forecast", micro, "v"))
    assert r.status == "ok", f"微尺度数据误判为常量列: {r.messages}"
    # 全精度指标应为微尺度有效值：白噪声无趋势（R²≈0），RMSE 保持 1e-13 量级
    assert abs(float(r.metadata["r_squared"])) < 0.2
    assert 0 < float(r.metadata["rmse"]) < 1e-11


def test_trend_forecast_true_constant_still_error():
    from smartsuite.engine.detection import trend_forecast

    const = pd.DataFrame({"v": [5.0] * 20})
    r = trend_forecast(_mk("trend_forecast", const, "v"))
    assert r.status == "error" and any("常量列" in m for m in r.messages)


def test_spc_nonparametric_micro_scale_not_constant():
    from smartsuite.engine.spc_charts import spc_nonparametric

    np.random.seed(2)
    micro = pd.DataFrame({"v": 1e-10 + np.random.normal(0, 1e-13, 60)})
    r = spc_nonparametric(_mk("spc_nonparametric", micro, "v"))
    assert r.status == "ok", f"微尺度数据误判为常量列: {r.messages}"
    # 控制限应为微尺度上的有效数值（而非 NaN/0），且 CL 落在数据均值附近
    cl = float(r.metadata["cl"])
    assert np.isfinite(cl) and abs(cl - 1e-10) < 1e-12
    assert float(r.metadata["ucl"]) > cl > float(r.metadata["lcl"])


def test_spc_nonparametric_true_constant_still_error():
    from smartsuite.engine.spc_charts import spc_nonparametric

    const = pd.DataFrame({"v": [2.5] * 30})
    r = spc_nonparametric(_mk("spc_nonparametric", const, "v"))
    assert r.status == "error" and any("常量列" in m for m in r.messages)


# ── B2: gage_rr AV 的 d2* 取 AIAG K2 口径（g 行 m→∞ 列） ────────────


def test_d2_star_infty_matches_aiag_k2():
    from smartsuite.engine.reliability import _d2_star_infty

    # AIAG MSA 4 版 K2 = 5.15/d2*∞：2→3.65、3→2.70、4→2.30
    assert abs(_d2_star_infty(2) - 1.41) < 1e-9
    assert abs(_d2_star_infty(3) - 1.91) < 1e-9
    assert abs(_d2_star_infty(4) - 2.24) < 1e-9
    assert abs(_d2_star_infty(5) - 2.48) < 1e-9
    assert abs(5.15 / _d2_star_infty(2) - 3.65) < 0.01


def test_gage_rr_2operator_small_sample_av_matches_anova():
    """10 零件 × 2 操作员 × 2 重复（AIAG 默认配置）：修复前 AV 高估 ~8.8%。"""
    from smartsuite.engine.reliability import gage_rr

    np.random.seed(6)
    rows = []
    true_vals = np.random.normal(50, 2, 10)
    for p_idx, p in enumerate(range(1, 11)):
        for op in ("O1", "O2"):
            op_bias = 0.4 if op == "O2" else 0.0
            for _ in range(2):
                rows.append(
                    {
                        "part": p,
                        "operator": op,
                        "measurement": true_vals[p_idx] + op_bias + np.random.normal(0, 0.3),
                    }
                )
    df = pd.DataFrame(rows)
    r = gage_rr(
        _mk(
            "gage_rr",
            df,
            "measurement",
            ["part", "operator"],
            {"part_col": "part", "operator_col": "operator"},
        )
    )
    assert r.status == "ok", r.messages
    av = r.metadata.get("av")
    assert av is not None and av > 0

    from statsmodels.formula.api import ols

    model = ols("measurement ~ C(part) + C(operator)", data=df).fit()
    import statsmodels.api as sm

    aov = sm.stats.anova_lm(model, typ=2)
    ms_op = float(aov.loc["C(operator)", "sum_sq"] / aov.loc["C(operator)", "df"])
    ms_e = float(aov.loc["Residual", "sum_sq"] / aov.loc["Residual", "df"])
    sigma_op = float(np.sqrt(max(0, (ms_op - ms_e) / (10 * 2))))
    ratio = av / sigma_op
    assert abs(ratio - 1.0) < 0.12, (
        f"2 操作员小样本 AV/anova={ratio:.4f}（修复前 ~1.088，AIAG K2 口径应≈1.0）"
    )


# ── C2: spc_xbar 无效 group_col 显式报错 ───────────────────────────


def test_spc_xbar_invalid_group_col_rejected():
    from smartsuite.engine.spc_charts import xbar_r_chart

    np.random.seed(3)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 40)})
    r = xbar_r_chart(_mk("spc_xbar", df, "v", params={"group_col": "does_not_exist"}))
    assert r.status == "error", "无效分组列不应静默退化为单系列"
    assert any("does_not_exist" in m for m in r.messages)


def test_spc_xbar_valid_and_empty_group_col_still_work():
    from smartsuite.engine.spc_charts import xbar_r_chart

    np.random.seed(4)
    df = pd.DataFrame(
        {
            "v": np.random.normal(0, 1, 40),
            "line": ["A"] * 20 + ["B"] * 20,
        }
    )
    r = xbar_r_chart(_mk("spc_xbar", df, "v", params={"group_col": "line"}))
    assert r.status == "ok", r.messages
    # 有效分组列必须真正按分组渲染（2 系列），而非静默单系列
    assert r.metadata.get("n_series") == 2, f"应识别 2 个分组，实际 {r.metadata.get('n_series')}"
    r = xbar_r_chart(_mk("spc_xbar", df, "v", params={"group_col": ""}))
    assert r.status == "ok", "空分组列 = 单系列，行为不变"
    assert r.metadata.get("n_series") == 1


# ── M-4: doe_design n_runs falsy 陷阱 ──────────────────────────────


def _doe_req(method, n_runs):
    df = pd.DataFrame({"a": [1.0, 2.0]})
    params = {
        "method": method,
        "factors": [{"name": "A", "levels": [-1, 1]}, {"name": "B", "levels": [-1, 1]}],
    }
    if n_runs is not ...:
        params["n_runs"] = n_runs
    return _mk("doe_design", df, "a", params=params)


def test_doe_design_n_runs_zero_rejected():
    from smartsuite.engine.doe_opt import doe_design

    for method in ("fractional_factorial", "plackett_burman"):
        r = doe_design(_doe_req(method, 0))
        assert r.status == "error", f"{method} n_runs=0 不应静默使用默认值"
        assert any("n_runs" in m for m in r.messages)


def test_doe_design_n_runs_none_uses_default():
    from smartsuite.engine.doe_opt import doe_design

    r = doe_design(_doe_req("fractional_factorial", ...))
    assert r.status == "ok", r.messages
    assert len(r.tables["design_matrix"]) == 4  # 2 因子默认全组合 2^2
    r = doe_design(_doe_req("plackett_burman", ...))
    assert r.status == "ok", r.messages


# ── B3: 微尺度数据下 BP 检验与置信带不退化 ──────────────────────────


def test_breusch_pagan_micro_scale_heteroscedastic_not_na():
    import statsmodels.api as sm

    from smartsuite.engine.doe_opt import _breusch_pagan

    rng = np.random.default_rng(3)
    n = 60
    x = np.arange(n, dtype=float)
    # 微尺度 y（~1e-13 噪声）且噪声随 x 增大 → 异方差
    y = 1e-10 + 1e-13 * (x / n) * 5 + rng.normal(0, 1, n) * 1e-13 * (1 + 3 * x / n)
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit()
    lm, p = _breusch_pagan(model, X)
    assert lm is not None and p is not None, "微尺度异方差数据的 BP 检验不应退化为 N/A"
    # 同尺度同方差（残差为真实数据而非舍入噪声）的 BP 同样可计算，LM 为量纲无关比值
    y_h = 1e-10 + rng.normal(0, 1, n) * 1e-13
    model_h = sm.OLS(y_h, X).fit()
    lm_h, _ = _breusch_pagan(model_h, X)
    assert lm_h is not None, "微尺度同方差真实数据的 BP 不应退化为 N/A"
    # 完美拟合（残差仅浮点舍入水平）仍应判 N/A——保留原 #审查 2026-08-19 行为
    y_perfect = 1.0 + 2.0 * (x / n)
    model_p = sm.OLS(y_perfect, X).fit()
    lm_p, _ = _breusch_pagan(model_p, X)
    assert lm_p is None, "完美拟合（舍入水平残差）的 BP 应判 N/A"


def test_scatter_ci_band_micro_scale_x():
    from smartsuite.engine.exploratory import scatter_plot

    rng = np.random.default_rng(7)
    n = 40
    x = 1e-10 + rng.normal(0, 1e-13, n)
    y = 2.0 + 0.5 * (x - 1e-10) * 1e13 + rng.normal(0, 0.1, n)
    df = pd.DataFrame({"x": x, "y": y})
    r = scatter_plot(_mk("scatter_plot", df, "y", ["x"], {"fit": "linear"}))
    assert r.status == "ok", r.messages
    # 置信带（fill_between → PolyCollection）应绘制而非静默缺失
    assert len(r.figures[0].axes[0].collections) >= 1, "微尺度 X 的置信带不应缺失"
