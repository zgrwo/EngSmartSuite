"""能力 / SPC / DOE 防护回归测试 — 规格限哨兵、相对判据、分组与参数校验。

对应 logs/reports/review-2026-09-05-release-prep.md 问题项：
C1(规格限 isfinite), B1(常量列相对阈值), B2(d2* 取 ∞ 列), C2(无效 group_col),
M-4(n_runs falsy), B3(微尺度阈值), E1(verify_docs tag 校验)。
另含修复轮新观察 O-1(表格显示舍入尺度感知)。
每项先以对抗脚本复现（修复前基线），再随修复转绿。
"""

import numpy as np
import pytest
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

    from smartsuite.engine.doe_opt.regression import _breusch_pagan

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


# ── 新观察 O-1: 表格显示舍入尺度感知（微尺度数据不再显示 0.0000）──────


def test_round_for_display_scale_aware():
    from smartsuite.engine._utils import round_for_display

    # 常规量级：与 round(x, 4) 逐位一致（既有表格显示口径不变）
    normal = np.array([123.45678, 0.123456, -5.5])
    assert np.array_equal(round_for_display(normal), np.round(normal, 4))
    assert round_for_display(123.45678) == 123.4568
    # 微尺度：按 4 位有效数字保留，而非整组归零
    micro = round_for_display(np.array([1.2346e-10, 2.0e-13]))
    assert abs(micro[0] - 1.235e-10) < 1e-12, f"微尺度值被归零或失真: {micro[0]}"
    assert micro[1] > 0
    # 标量输入同样保留量级
    assert round_for_display(1.2346e-10) > 1e-11
    # 全零 / 非有限值行为不变
    assert np.array_equal(round_for_display(np.zeros(3)), np.zeros(3))
    assert np.isnan(round_for_display(np.array([np.nan, 0.5]))[0])
    assert round_for_display(np.array([np.inf, 1.0]))[0] == np.inf


def test_trend_forecast_micro_scale_table_not_zero():
    from smartsuite.engine.detection import trend_forecast

    np.random.seed(1)
    micro = pd.DataFrame({"v": 1e-10 + np.random.normal(0, 1e-13, 60)})
    r = trend_forecast(_mk("trend_forecast", micro, "v"))
    assert r.status == "ok", r.messages
    tbl = r.tables["forecast"]
    assert (tbl["预测值"].to_numpy() != 0).all(), "微尺度预测值不应整列显示 0.0000"
    assert (tbl["预测值"].abs() < 1e-8).all(), "预测值应保持微尺度量级"


# ── 逐公式审计处置（2026-09-05）：效应量标签 + McNemar 小样本提示 ────


def test_ttest_ind_effect_labeled_hedges_g():
    """审计瑕疵#8：_cohens_d 返回含小样本校正的 Hedges g，两样本分支标签同步。"""
    from smartsuite.engine.root_cause import hypothesis_test

    np.random.seed(301)
    g1 = np.random.normal(10, 2, 30)
    g2 = np.random.normal(12, 2, 30)
    df = pd.DataFrame({"v": np.concatenate([g1, g2]), "g": ["A"] * 30 + ["B"] * 30})
    r = hypothesis_test(_mk("hypothesis_test", df, "v", ["g"], {"test": "ttest_ind"}))
    assert r.status == "ok", r.messages
    assert r.metadata["effect_name"] == "Hedges g", f"实际: {r.metadata['effect_name']}"
    # 数值仍为 Hedges g（含校正因子）
    sp_pool = np.sqrt((29 * g1.var(ddof=1) + 29 * g2.var(ddof=1)) / 58)
    g_ref = (g1.mean() - g2.mean()) / sp_pool * (1 - 3 / (4 * 60 - 9))
    assert abs(r.metadata["effect_size"] - g_ref) < 1e-9


def test_cohens_d_dispatch_labeled_hedges_g():
    from smartsuite.engine.root_cause import hypothesis_test

    np.random.seed(302)
    df = pd.DataFrame(
        {
            "v": np.concatenate([np.random.normal(0, 1, 20), np.random.normal(1, 1, 20)]),
            "g": ["A"] * 20 + ["B"] * 20,
        }
    )
    r = hypothesis_test(_mk("hypothesis_test", df, "v", ["g"], {"test": "cohens_d"}))
    assert r.status == "ok", r.messages
    assert r.metadata["effect_name"] == "Hedges g"
    assert r.metadata["test"].startswith("效应量 Hedges g")


def test_mcnemar_small_discordant_warms_exact_binomial():
    """审计约定#1：b+c<25 时 Yates 校正 + 精确二项复核提示。"""
    from smartsuite.engine.root_cause import hypothesis_test

    # b=2, c=7（不一致对 9 < 25）
    col1 = [0] * 10 + [0] * 2 + [1] * 7 + [1] * 11
    col2 = [0] * 10 + [1] * 2 + [0] * 7 + [1] * 11
    df = pd.DataFrame({"pre": col1, "post": col2})
    r = hypothesis_test(_mk("hypothesis_test", df, "post", ["pre", "post"], {"test": "mcnemar"}))
    assert r.status == "ok", r.messages
    assert any("精确二项" in m for m in r.messages), f"应提示精确二项复核: {r.messages}"
    assert "(Yates校正)" in r.metadata["test"]
    # 大样本分支无提示
    col1b = [0] * 40 + [0] * 15 + [1] * 25 + [1] * 40
    col2b = [0] * 40 + [1] * 15 + [0] * 25 + [1] * 40
    df2 = pd.DataFrame({"pre": col1b, "post": col2b})
    r2 = hypothesis_test(_mk("hypothesis_test", df2, "post", ["pre", "post"], {"test": "mcnemar"}))
    assert r2.status == "ok" and not r2.messages


# ── B-5（2026-09-21 审查）：McNemar OR 的未定义/伪有限值 ──────────────────────
def _mcnemar_df(b: int, c: int, a: int = 30, d: int = 30):
    """2×2 配对表：a=一致(1,1)、b=(1→0)、c=(0→1)、d=一致(0,0)。"""
    pre = [1] * a + [1] * b + [0] * c + [0] * d
    post = [1] * a + [0] * b + [1] * c + [0] * d
    return pd.DataFrame({"pre": pre, "post": post})


def test_mcnemar_odds_ratio_c_zero_is_not_fake_finite():
    """c=0（OR→∞）不得输出伪有限值 3e11 并写进 summary（审查 B-5 P2）。

    修复前实测 b=30,c=0 → `odds_ratio=300000000000.0`，
    summary 显示「OR=b/c=300000000000.00」；且 metadata 的
    `float(or_val) if not np.isinf(or_val) else None` 因伪有限值而成为死代码。
    """
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _mk("hypothesis_test", _mcnemar_df(30, 0), "pre", ["pre", "post"], {"test": "mcnemar"})
    )
    assert r.status == "ok", r.messages
    assert r.metadata["odds_ratio"] is None, (
        f"c=0 时 OR 无有限值，应为 None，实际 {r.metadata['odds_ratio']}"
    )
    assert "300000000000" not in r.summary, f"summary 不得显示伪有限 OR: {r.summary}"
    assert "∞" in r.summary or "无法计算" in r.summary, f"应显式说明 OR 不可用: {r.summary}"


def test_mcnemar_odds_ratio_zero_zero_is_undefined():
    """b=c=0（0/0 未定义）不得伪装成「OR=0.00 / 无关联」（审查 B-5）。"""
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _mk("hypothesis_test", _mcnemar_df(0, 0), "pre", ["pre", "post"], {"test": "mcnemar"})
    )
    assert r.status == "ok", r.messages
    assert r.metadata["odds_ratio"] is None, (
        f"0/0 未定义，应为 None，实际 {r.metadata['odds_ratio']}"
    )
    assert "无法计算" in r.summary or "未定义" in r.summary, f"应显式说明: {r.summary}"


def test_mcnemar_odds_ratio_exact_without_epsilon_residue():
    """c>0 时 OR 应为精确 b/c（EPSILON 引入 1e-10 级假精度，审查 B-5）。"""
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _mk("hypothesis_test", _mcnemar_df(10, 2), "pre", ["pre", "post"], {"test": "mcnemar"})
    )
    assert r.status == "ok", r.messages
    assert r.metadata["odds_ratio"] == 5.0, (
        f"b/c=10/2 应精确为 5.0，实际 {r.metadata['odds_ratio']}"
    )
    assert "4.9999" not in r.summary, f"summary 不得带 EPSILON 残差: {r.summary}"


# ── B-3（2026-09-21 审查）：Wilcoxon 效应量不得由 p 反推 ──────────────────────
def test_wilcoxon_effect_size_is_not_p_backderived():
    """Wilcoxon 秩相关 r 须由实际 Z 得出，不得由 p 反推（审查 B-3 P2）。

    原实现 `z = norm.ppf(1 - max(p, EPSILON)/2)`：`EPSILON=1e-10` 把 Z 钳在
    6.467，于是**强效应被系统性压小且随 n 增大而衰减**——实测「全部差值为正」
    （最大效应）时：n=100 → r=0.647、n=400 → 0.323、n=1000 → 0.205、
    n=4000 → 0.102，而该情形的渐近真值是 **r = √3/2 ≈ 0.866**（与 n 无关）。

    判据用可推导的渐近真值 + 单调性不变量，不复制实现本身。
    """
    import math

    from smartsuite.engine.root_cause import hypothesis_test

    # 全部为正差且**互不相同**（无并列、无零差）——此时 scipy 渐近 Z 与教科书
    # 正态近似公式逐位一致（本审查实测 8.6818/17.3313/27.3930），
    # 故渐近真值 r → √3/2 ≈ 0.866 无歧义。
    rs = []
    for n in (100, 400, 1000):
        df = pd.DataFrame({"y": np.arange(1.0, n + 1)})
        r = hypothesis_test(
            _mk("hypothesis_test", df, "y", [], {"test": "wilcoxon_1samp", "popmedian": 0.0})
        )
        assert r.status == "ok", r.messages
        rs.append(float(r.metadata["effect_size"]))

    expected = math.sqrt(3) / 2  # ≈ 0.866：最大效应的渐近 r
    for n, r in zip((100, 400, 1000), rs, strict=True):
        assert abs(r - expected) < 0.05, f"n={n}: 最大效应下 r 应≈{expected:.4f}，实测 {r:.4f}"
    assert max(rs) - min(rs) < 0.05, f"r 不应随样本量变化（p 反推封顶的典型症状）: {rs}"


# ── B-2（2026-09-21 审查）：kappa z 口径的假阳性防护 ──────────────────────────
def test_cohens_kappa_z_matches_fleiss_ase0():
    """Kappa 的 z 必须等于手算 Fleiss ASE0（H0 下标准误），勿按"更精确 SE"改坏。

    2026-09-21 审查 B-2 报「kappa 用简化 H0 标准误，与 statsmodels/Fleiss ASE0
    不同，z 为 9.802 vs 4.000」。父会话对账：18 张 2×2/3×3/4×4 随机表的引擎 z 与
    手算 ASE0 = κ/√[p_o(1-p_o)/(n(1-p_e)²)] 最大偏差 **1.76e-08**（浮点噪声），
    且经典 [[35,15],[15,35]] 表为 4.3644（与手算 4.3644 一致）。
    → **该 finding 是假阳性**：实现本就是 Fleiss ASE0，无需修改。
    本用例把正确口径钉住，防止后续按误报「修正」引入真实缺陷。
    """
    from smartsuite.engine.root_cause.association import cohens_kappa
    from smartsuite.engine.root_cause.hypothesis import hypothesis_test  # noqa: F401

    tables = [
        pd.DataFrame([[35, 15], [15, 35]]),  # 经典 2×2（审查反例）
        pd.DataFrame([[50, 5], [8, 37]]),
        pd.DataFrame([[20, 4, 1], [3, 25, 2], [1, 2, 30]]),
        pd.DataFrame([[10, 6, 2, 1], [4, 18, 3, 2], [2, 3, 22, 4], [1, 2, 5, 15]]),
    ]
    for ct in tables:
        rows = []
        for i, rlab in enumerate(ct.index):
            for j, clab in enumerate(ct.columns):
                rows += [(rlab, clab)] * int(ct.iloc[i, j])
        df = pd.DataFrame(rows, columns=["a", "b"])
        r = cohens_kappa(_mk("cohens_kappa", df, "", ["a", "b"], {}))
        assert r.status == "ok", (ct.values.tolist(), r.messages)

        n = int(ct.values.sum())
        p_o = np.trace(ct.values) / n
        row = ct.sum(axis=1).values.astype(float)
        col = ct.sum(axis=0).values.astype(float)
        p_e = float((row * col).sum() / n**2)
        kappa = (p_o - p_e) / (1 - p_e)
        se0 = np.sqrt(p_o * (1 - p_o) / (n * (1 - p_e) ** 2))
        z_expected = kappa / se0

        z_engine = float(r.metadata["z"])
        assert z_engine == pytest.approx(z_expected, rel=1e-6), (
            f"kappa z 偏离 Fleiss ASE0：引擎 {z_engine:.6f} vs 手算 {z_expected:.6f}"
        )


# ── B-1（2026-09-21 审查）：Cliff's δ 的 CI 越界 ──────────────────────────────
def test_mannwhitney_effect_size_ci_stays_within_bounds():
    """有界效应量（Cliff's δ ∈ [-1,1]）的置信区间不得越出定义域（审查 B-1 P2）。

    原实现无条件套用 Cohen's d 的标准误公式 `_cohens_d_ci`，实测：
      n=8  → δ=-0.9062 CI=(-1.9353, +0.1228)
      n=10 → δ=-0.8600 CI=(-1.7761, +0.0561)
      n=20 → δ=-0.7500 CI=(-1.3912, -0.1088)
    全部越出 [-1,1]。δ 的 CI 需要其自身（支配矩阵）的方差分量，本仓无可核验的
    闭式公式，故口径定为：**不猜测**——δ 不输出 CI（None）并给出说明；
    本用例断言「要么 None，要么落在 [-1,1] 内」，两种合规实现都能通过。
    """
    from smartsuite.engine.root_cause import hypothesis_test

    rng = np.random.default_rng(7)
    for n in (8, 10, 20, 50):
        g1 = rng.normal(0, 1, n)
        g2 = rng.normal(1.5, 1, n)
        df = pd.DataFrame({"y": np.r_[g1, g2], "g": ["A"] * n + ["B"] * n})
        r = hypothesis_test(_mk("hypothesis_test", df, "y", ["g"], {"test": "mannwhitney"}))
        assert r.status == "ok", r.messages
        ci = r.metadata.get("effect_size_ci")
        if ci is None:
            assert "effect_ci_note" in r.metadata, "不输出 CI 时必须给出原因说明"
            continue
        lo, hi = ci
        assert -1 <= lo <= 1 and -1 <= hi <= 1, f"n={n}: Cliff's δ 的 CI 越界: ({lo}, {hi})"
        assert lo <= hi, f"n={n}: CI 下界应不大于上界: ({lo}, {hi})"


def test_ttest_effect_size_ci_unchanged():
    """对照：Hedges g（d 族，定义域无界）必须仍有 CI（防把守卫改成一律 None）。"""
    from smartsuite.engine.root_cause import hypothesis_test

    rng = np.random.default_rng(3)
    g1 = rng.normal(0, 1, 30)
    g2 = rng.normal(0.6, 1, 30)
    df = pd.DataFrame({"y": np.r_[g1, g2], "g": ["A"] * 30 + ["B"] * 30})
    r = hypothesis_test(_mk("hypothesis_test", df, "y", ["g"], {"test": "ttest_ind"}))
    assert r.status == "ok", r.messages
    ci = r.metadata.get("effect_size_ci")
    assert ci is not None, "Hedges g 的 CI 不应被移除"
    lo, hi = ci
    assert np.isfinite(lo) and np.isfinite(hi) and lo < hi


# ── A-1（2026-09-21 审查）：两处 IQR 掩码实现的一致性 ────────────────────────
def test_iqr_outlier_mask_consistent_between_tasks():
    """`anomaly_detect(method='iqr')` 与 `outlier_consensus` 的 IQR 判据必须一致。

    审查 2026-09-21 A-1：两处各自复制了一份 IQR 掩码（含 IQR==0 拒绝逻辑）。
    本用例是**抽取共享助手的安全网**（也长期作为「两处判据不得漂移」的守卫）：
    同一数据下 outlier_consensus 的 IQR 投票数须等于解析解
    `count(y < Q1-1.5IQR | y > Q3+1.5IQR)`，且 anomaly_detect 的检出数与之相同。
    """
    from smartsuite.engine.detection.anomaly import anomaly_detect
    from smartsuite.engine.detection.outlier import outlier_consensus

    rng = np.random.default_rng(5)
    cases = [
        np.r_[rng.normal(0, 1, 80), [7.0, -7.0]],  # 正常 + 强异常
        rng.normal(0, 1, 60),  # 无强异常
        np.r_[rng.normal(0, 1, 50), [4.0]],  # 边界型异常
    ]
    for idx, values in enumerate(cases):
        df = pd.DataFrame({"y": values})
        r_a = anomaly_detect(_mk("anomaly_detect", df, "y", [], {"method": "iqr"}))
        r_o = outlier_consensus(_mk("outlier_consensus", df, "y", [], {}))
        assert r_a.status == "ok" and r_o.status == "ok", (idx, r_a.messages, r_o.messages)

        q1, q3 = df["y"].quantile(0.25), df["y"].quantile(0.75)
        iqr = q3 - q1
        expected = int(((df["y"] < q1 - 1.5 * iqr) | (df["y"] > q3 + 1.5 * iqr)).sum())

        assert r_o.metadata["iqr_count"] == expected, f"case {idx}: IQR 投票数应等于解析解"
        assert r_a.metadata["anomaly_count"] == r_o.metadata["iqr_count"], (
            f"case {idx}: 两任务的 IQR 判据不一致（"
            f"{r_a.metadata['anomaly_count']} vs {r_o.metadata['iqr_count']}）"
        )


def test_iqr_zero_constant_column_both_reject():
    """常量列（IQR=0）两任务都必须显式报错（不得一路静默、一路报错）。"""
    from smartsuite.engine.detection.anomaly import anomaly_detect
    from smartsuite.engine.detection.outlier import outlier_consensus

    df = pd.DataFrame({"y": np.full(30, 5.0)})
    r_a = anomaly_detect(_mk("anomaly_detect", df, "y", [], {"method": "iqr"}))
    r_o = outlier_consensus(_mk("outlier_consensus", df, "y", [], {}))
    assert r_a.status == "error" and "IQR=0" in " ".join(r_a.messages)
    assert r_o.status == "error" and "IQR=0" in " ".join(r_o.messages)


def test_iqr_outlier_mask_direct_unit():
    """`detection._shared.iqr_outlier_mask` 直接单测（质量守卫要求公共函数有直测）。

    三态：正常数据 → 返回 (掩码, 下界, 上界) 且边界与掩码同源；常量列（IQR=0）
    → 返回 None（由调用方生成任务级中文错误）。
    """
    from smartsuite.engine._constants import IQR_OUTLIER_MULTIPLIER
    from smartsuite.engine.detection._shared import iqr_outlier_mask

    data = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 100.0])
    result = iqr_outlier_mask(data, IQR_OUTLIER_MULTIPLIER)
    assert result is not None
    mask, lower, upper = result
    q1, q3 = data.quantile(0.25), data.quantile(0.75)
    iqr = q3 - q1
    assert lower == pytest.approx(q1 - IQR_OUTLIER_MULTIPLIER * iqr)
    assert upper == pytest.approx(q3 + IQR_OUTLIER_MULTIPLIER * iqr)
    assert int(mask.sum()) == 1, "仅 100 应被判为异常"
    assert bool(mask.iloc[-1]) is True

    assert iqr_outlier_mask(pd.Series([5.0] * 10), IQR_OUTLIER_MULTIPLIER) is None, (
        "常量列（IQR=0）应返回 None 交由调用方报错"
    )
