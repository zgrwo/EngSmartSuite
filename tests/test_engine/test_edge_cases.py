"""边界条件和边缘情况测试 — 确保引擎函数优雅降级。"""
import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.doe_opt import (
    doe_analysis,
    regression_analysis,
)
from smartsuite.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    power_analysis,
    vif_analysis,
)
from smartsuite.engine.spc_monitor import (
    anomaly_detect,
    cusum_chart,
    ewma_chart,
    process_capability_analysis,
)


def _make_df(data_dict):
    """Helper: 用最小样本构建 DataFrame。"""
    return pd.DataFrame(data_dict)


# ── 空/极小数据 ──

def test_single_row_data_does_not_crash():
    """所有函数在只有1行数据时应返回 error 而非崩溃。"""
    df = _make_df({"x": [1.0], "y": [2.0]})
    req = AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
    result = regression_analysis(req)
    assert result.status == "error"


def test_all_nan_column():
    """全 NaN 特征列：按任务断言具体状态 + 中文消息（Round-2 批次D #2b）。

    此前状态断言恒真（status 三种取值皆通过，任何结果都不失败）。现按 per-task
    期望表验证：多数任务应 error（带中文消息），无需数据的任务（power_analysis）
    和只用目标列的任务（process_capability）可 ok。
    """
    df = _make_df({"x": [np.nan, np.nan, np.nan], "y": [1.0, 2.0, 3.0]})
    req = AnalysisRequest(task="correlation", data=df, target_col="y", feature_cols=["x"])
    result = correlation_analysis(req)
    assert result.status == "error", f"全 NaN 特征列相关性应 error: {result.messages}"
    assert any("常量" in m or "变异" in m for m in result.messages), (
        f"应给出中文常量列提示: {result.messages}"
    )

    # 回归/DOE/ANOVA：有效样本不足 → error + 中文消息
    r2 = regression_analysis(AnalysisRequest(task="regression", data=df,
                                             target_col="y", feature_cols=["x"]))
    assert r2.status == "error"
    assert any("有效样本" in m or "不足" in m for m in r2.messages), f"{r2.messages}"
    r3 = doe_analysis(AnalysisRequest(task="doe_analysis", data=df,
                                      target_col="y", feature_cols=["x"]))
    assert r3.status == "error"
    assert any("有效样本" in m or "不足" in m for m in r3.messages), f"{r3.messages}"
    r4 = anova_analysis(AnalysisRequest(task="anova", data=df,
                                        target_col="y", feature_cols=["x"]))
    assert r4.status == "error"
    assert len(r4.messages) > 0, "ANOVA error 应有中文消息"

    # power_analysis 不依赖数据 → ok（个别任务豁免）
    r5 = power_analysis(AnalysisRequest(task="power_analysis", data=df, target_col="y",
                                        feature_cols=["x"], params={"effect_size": 0.5}))
    assert r5.status == "ok", f"power_analysis 应可 ok: {r5.messages}"
    # process_capability 只用目标列 → ok
    r6 = process_capability_analysis(AnalysisRequest(task="process_capability", data=df,
                                                     target_col="y", feature_cols=["x"],
                                                     params={"usl": 10, "lsl": 1}))
    assert r6.status == "ok", f"process_capability 应可 ok: {r6.messages}"


def test_zero_variance_column():
    """零方差特征列：按任务断言具体状态 + 中文消息（Round-2 批次D #2b）。

    此前状态断言恒真（status 三种取值皆通过）。per-task 期望：依赖方差的任务
    （correlation/regression/vif）应 error 且消息含「常量列」；doe/anova 对
    零方差因子可降级 ok（因子无变异但可报告）。
    """
    df = _make_df({"x": [5.0, 5.0, 5.0, 5.0, 5.0], "y": [1.0, 2.0, 3.0, 4.0, 5.0]})
    r_corr = correlation_analysis(AnalysisRequest(task="correlation", data=df,
                                                  target_col="y", feature_cols=["x"]))
    assert r_corr.status == "error", f"零方差列相关性应 error: {r_corr.messages}"
    assert any("常量" in m for m in r_corr.messages), f"应提示常量列: {r_corr.messages}"
    r_reg = regression_analysis(AnalysisRequest(task="regression", data=df,
                                                target_col="y", feature_cols=["x"]))
    assert r_reg.status == "error"
    assert any("常量" in m for m in r_reg.messages), f"应提示常量列: {r_reg.messages}"
    r_vif = vif_analysis(AnalysisRequest(task="vif", data=df, target_col="",
                                         feature_cols=["x", "y"]))
    assert r_vif.status == "error"
    assert any("常量" in m for m in r_vif.messages), f"VIF 应提示常量列: {r_vif.messages}"

    # doe_analysis 对零方差因子降级 ok（可报告，不崩溃）——回归保护
    req = AnalysisRequest(task="doe_analysis", data=df, target_col="y", feature_cols=["x"])
    result = doe_analysis(req)
    assert result.status == "ok", f"doe_analysis 应可降级 ok: {result.messages}"
    assert len(result.summary) > 0, "doe ok 结果应有 summary"


def test_anova_with_one_factor():
    """单因子 ANOVA 应正常工作并返回有效统计量。"""
    np.random.seed(42)
    df = _make_df({
        "group": ["A"] * 10 + ["B"] * 10 + ["C"] * 10,
        "val": np.random.normal(10, 2, 30),
    })
    req = AnalysisRequest(task="anova", data=df, target_col="val", feature_cols=["group"])
    result = anova_analysis(req)
    assert result.status == "ok"
    assert 0 <= result.metadata["r_squared"] <= 1, f"R² out of range: {result.metadata['r_squared']}"
    assert "anova_enhanced" in result.tables


# ── 确定性 ──

def test_correlation_deterministic():
    """相同输入应产生相同输出（确定性）。"""
    np.random.seed(123)
    df = _make_df({
        "a": np.arange(1, 11, dtype=float),
        "b": np.arange(11, 21, dtype=float),
    })
    req = AnalysisRequest(task="correlation", data=df, target_col="b", feature_cols=["a"])
    r1 = correlation_analysis(req)
    r2 = correlation_analysis(req)
    assert r1.summary == r2.summary
    assert r1.tables["correlation_matrix"].equals(r2.tables["correlation_matrix"])


def test_vif_deterministic():
    """VIF 计算应是确定性的。"""
    np.random.seed(42)
    df = _make_df({
        "x1": np.random.normal(0, 1, 50),
        "x2": np.random.normal(0, 1, 50),
        "x3": np.random.normal(0, 1, 50),
    })
    req = AnalysisRequest(task="vif", data=df, target_col="x1", feature_cols=["x1", "x2", "x3"])
    r1 = vif_analysis(req)
    r2 = vif_analysis(req)
    assert r1.tables["vif_table"].equals(r2.tables["vif_table"])


# ── 极值处理 ──

def test_large_values():
    """极大值不应导致溢出或 NaN。"""
    df = _make_df({
        "x": [1e9, 2e9, 3e9, 4e9, 5e9],
        "y": [2e9, 4e9, 6e9, 8e9, 10e9],
    })
    req = AnalysisRequest(task="regression", data=df, target_col="y", feature_cols=["x"])
    result = regression_analysis(req)
    assert result.status == "ok"
    assert not np.isnan(result.metadata["r_squared"])


def test_negative_target_for_process_capability():
    """负值目标变量在过程能力分析中不应崩溃。"""
    df = _make_df({"val": np.random.normal(-5, 1, 30)})
    req = AnalysisRequest(task="process_capability", data=df, target_col="val",
                          params={"usl": -2.0, "lsl": -8.0})
    result = process_capability_analysis(req)
    assert result.status == "ok"


# ── 新函数 ──

def test_power_analysis_required_n():
    """功效分析 — 计算所需样本量。"""
    req = AnalysisRequest(
        task="power_analysis", data=pd.DataFrame(),
        target_col="", feature_cols=[],
        params={"effect_size": 0.5, "alpha": 0.05, "target_power": 0.80,
                "mode": "required_n", "test_type": "ttest"},
    )
    result = power_analysis(req)
    assert result.status == "ok"
    assert "required_n" in result.metadata
    assert result.metadata["required_n"] > 0


def test_power_analysis_achieved():
    """功效分析 — 计算已达功效。"""
    req = AnalysisRequest(
        task="power_analysis", data=pd.DataFrame(),
        target_col="", feature_cols=[],
        params={"effect_size": 0.3, "alpha": 0.05, "mode": "achieved",
                "test_type": "ttest", "current_n": 30},
    )
    result = power_analysis(req)
    assert result.status == "ok"
    assert "achieved_power" in result.metadata
    assert 0 < result.metadata["achieved_power"] < 1


def test_cusum_detects_shift():
    """CUSUM 应能检测数据的均值偏移。"""
    np.random.seed(42)
    base = np.random.normal(10.0, 0.5, 100)
    base[60:] += 1.0  # 2σ 偏移
    df = _make_df({"val": base})
    req = AnalysisRequest(task="spc_cusum", data=df, target_col="val",
                          params={"k": 0.5, "h": 5.0})
    result = cusum_chart(req)
    assert result.status == "ok"
    assert result.metadata["total_alarms"] > 0  # 应检测到偏移


def test_ewma_basic():
    """EWMA 应返回有效结果，稳定过程违规点应在合理范围内。"""
    np.random.seed(42)
    df = _make_df({"val": np.random.normal(10, 1, 50)})
    req = AnalysisRequest(task="spc_ewma", data=df, target_col="val",
                          params={"lam": 0.2, "L": 2.7})
    result = ewma_chart(req)
    assert result.status == "ok"
    assert "violations" in result.metadata
    # 随机稳定数据不应产生大量违规（允许少量假阳性）
    v = result.metadata["violations"]
    n_alarms = len(v) if isinstance(v, dict) else (len(v) if isinstance(v, list) else 0)
    assert n_alarms <= 10, f"稳定过程产生过多违规: {n_alarms}"

# ── 比例 CI ──
def test_proportion_ci_binary():
    from smartsuite.engine.root_cause import proportion_ci
    df = pd.DataFrame({"x": ["合格"]*85 + ["不合格"]*15})
    req = AnalysisRequest(task="proportion_ci", data=df, target_col="x")
    r = proportion_ci(req)
    assert r.status == "ok"
    assert 0.75 < r.metadata["p_hat"] < 0.95

# ── 列联表 ──
def test_contingency_2x2():
    from smartsuite.engine.root_cause import contingency_analysis
    df = pd.DataFrame({
        "a": ["A"]*40 + ["A"]*10 + ["B"]*20 + ["B"]*30,
        "b": ["X"]*40 + ["Y"]*10 + ["X"]*20 + ["Y"]*30,
    })
    req = AnalysisRequest(task="contingency", data=df, target_col="a", feature_cols=["b"])
    r = contingency_analysis(req)
    assert r.status == "ok"
    assert "p_value" in r.metadata
    # 2x2 卡方检验应有 Cramér's V 效应量
    if "effect" in r.metadata:
        assert 0 <= r.metadata["effect"] <= 1, f"Cramér's V out of range: {r.metadata['effect']}"

# ── Kendall ──
def test_correlation_kendall():
    from smartsuite.engine.root_cause import correlation_analysis
    np.random.seed(42)
    df = pd.DataFrame({
        "x": np.random.normal(0, 1, 100),
        "y": np.random.normal(0, 1, 100),
    })
    df["y"] = 0.7 * df["x"] + np.random.normal(0, 0.7, 100)
    req = AnalysisRequest(task="correlation", data=df, target_col="y",
        feature_cols=["x"], params={"method": "kendall"})
    r = correlation_analysis(req)
    assert r.status == "ok"
    # 已知 y ≈ 0.7x + noise，Kendall τ 应为正且与 Pearson r 量级相当
    tau = r.tables["correlation_matrix"].loc["y", "x"]
    assert 0.3 < tau < 0.8, f"Expected Kendall τ in 0.3-0.8, got {tau:.3f}"
    assert r.metadata["method"] == "kendall"

# ── Bootstrap edge ──
def test_bootstrap_no_data():
    from smartsuite.engine.spc_monitor import bootstrap_ci
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    req = AnalysisRequest(task="bootstrap_ci", data=df, target_col="x",
        params={"n_bootstrap": 100})
    r = bootstrap_ci(req)
    assert r.status == "error"  # < 5 data points

# ── Grubbs ──
def test_anomaly_grubbs():
    np.random.seed(42)
    x = np.concatenate([np.random.normal(10, 1, 48), [25.0, 28.0]])  # 2 clear outliers
    df = pd.DataFrame({"x": x})
    req = AnalysisRequest(task="anomaly_detect", data=df, target_col="x",
        params={"method": "grubbs", "alpha": 0.05})
    r = anomaly_detect(req)
    assert r.status == "ok"
    assert r.metadata["anomaly_count"] >= 2

# ── Audit ──
def test_process_audit():
    from smartsuite.services.audit import process_audit
    np.random.seed(42)
    df = pd.DataFrame({
        "x1": np.random.normal(10, 1, 100),
        "x2": np.random.normal(20, 3, 100),
        "y": np.random.normal(50, 5, 100),
    })
    result = process_audit(df, target_col="y", feature_cols=["x1", "x2"],
                          usl=60, lsl=40, target=50)
    assert "health_checks" in result
    assert "overall_rating" in result
    assert len(result["health_checks"]) >= 4

# ── 新函数边界测试 ──
def test_gage_rr_basic():
    from smartsuite.engine.spc_monitor import gage_rr
    np.random.seed(42)
    parts = np.repeat(range(1, 11), 6)
    operators = np.tile(np.repeat(["A", "B", "C"], 2), 10)
    df = pd.DataFrame({
        "part": parts, "op": operators,
        "measure": np.random.normal(10, 0.1, 60) + (parts - 5) * 0.5,
    })
    req = AnalysisRequest(task="gage_rr", data=df, target_col="measure",
        feature_cols=["part", "op"], params={"part_col": "part", "operator_col": "op"})
    r = gage_rr(req)
    assert r.status == "ok"
    assert "ndc" in r.metadata

def test_tolerance_interval_basic():
    from smartsuite.engine.spc_monitor import tolerance_interval
    df = pd.DataFrame({"x": np.random.normal(10, 1, 100)})
    req = AnalysisRequest(task="tolerance_interval", data=df, target_col="x",
        params={"coverage": 0.99, "confidence": 0.95})
    r = tolerance_interval(req)
    assert r.status == "ok"
    assert r.metadata["lower"] < r.metadata["upper"]

def test_distribution_summary_positive():
    from smartsuite.engine.root_cause import distribution_summary
    df = pd.DataFrame({"x": np.random.lognormal(0, 0.5, 200)})
    req = AnalysisRequest(task="distribution_summary", data=df, target_col="x")
    r = distribution_summary(req)
    assert r.status == "ok"
    assert "best_fit" in r.metadata
    # 对数正态数据的最佳拟合应为 lognorm 或 gamma 之类的正偏态分布
    best = r.metadata["best_fit"]
    assert best != "None", "未找到最佳拟合分布"
    assert isinstance(best, str) and len(best) > 0

def test_cohens_kappa_agreement():
    from smartsuite.engine.root_cause import cohens_kappa
    df = pd.DataFrame({"r1": ["A"]*40+["B"]*10+["A"]*5+["B"]*45,
                       "r2": ["A"]*42+["B"]*8+["A"]*8+["B"]*42})
    req = AnalysisRequest(task="cohens_kappa", data=df, target_col="",
        feature_cols=["r1", "r2"])
    r = cohens_kappa(req)
    assert r.status == "ok"
    assert r.metadata["kappa"] > 0.5

def test_contingency_large():
    from smartsuite.engine.root_cause import contingency_analysis
    df = pd.DataFrame({
        "a": np.random.choice(["X","Y","Z"], 200),
        "b": np.random.choice(["P","Q","R","S"], 200),
    })
    req = AnalysisRequest(task="contingency", data=df, target_col="a", feature_cols=["b"])
    r = contingency_analysis(req)
    assert r.status == "ok"

def test_roc_perfect_separation():
    from smartsuite.engine.doe_opt import roc_analysis
    np.random.seed(42)
    scores = np.concatenate([np.random.normal(5,1,100), np.random.normal(8,1,100)])
    labels = ["合格"]*100 + ["不合格"]*100
    df = pd.DataFrame({"score": scores, "label": labels})
    req = AnalysisRequest(task="roc_analysis", data=df, target_col="label",
        feature_cols=["score"])
    r = roc_analysis(req)
    assert r.status == "ok"
    assert r.metadata["auc"] > 0.8


# ── 最新函数边界测试 ──
def test_logistic_regression_binary():
    from smartsuite.engine.doe_opt import logistic_regression
    np.random.seed(42)
    n = 200
    x1 = np.random.normal(0, 1, n)
    x2 = np.random.normal(0, 1, n)
    logit = -1 + 2*x1 + 0.5*x2
    prob = 1 / (1 + np.exp(-logit))
    y = np.random.binomial(1, prob)
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": np.where(y, "不合格", "合格")})
    req = AnalysisRequest(task="logistic_regression", data=df, target_col="y",
        feature_cols=["x1", "x2"])
    r = logistic_regression(req)
    assert r.status == "ok"
    assert r.metadata["accuracy"] > 0.6

def test_cronbach_alpha_good():
    from smartsuite.engine.root_cause import cronbach_alpha
    np.random.seed(42)
    true_score = np.random.normal(0, 1, 100)
    items = {f"item{i}": true_score + np.random.normal(0, 0.3, 100) for i in range(1, 6)}
    df = pd.DataFrame(items)
    req = AnalysisRequest(task="cronbach_alpha", data=df, target_col="",
        feature_cols=list(items.keys()))
    r = cronbach_alpha(req)
    assert r.status == "ok"
    assert r.metadata["alpha"] > 0.8

def test_median_ci_positive():
    from smartsuite.engine.spc_monitor import median_ci
    df = pd.DataFrame({"x": np.random.lognormal(0, 1, 200)})
    req = AnalysisRequest(task="median_ci", data=df, target_col="x")
    r = median_ci(req)
    assert r.status == "ok"
    assert r.metadata["ci_lower"] < r.metadata["median"] < r.metadata["ci_upper"]

def test_survival_minimal():
    from smartsuite.engine.spc_monitor import survival_analysis
    np.random.seed(42)
    times = np.concatenate([np.random.exponential(1000, 60), np.full(40, 2000)])
    events = np.concatenate([np.ones(60), np.zeros(40)])
    df = pd.DataFrame({"time": times, "event": events})
    req = AnalysisRequest(task="survival_analysis", data=df, target_col="time",
        feature_cols=["event"])
    r = survival_analysis(req)
    assert r.status == "ok"
    assert r.metadata["n_censored"] > 0

def test_bootstrap_ci_ci_level_out_of_range():
    """审查 2026-08-19 #1.3：ci_level 越界应返回中文错误而非崩溃/荒谬输出。"""
    from smartsuite.engine.exploratory import bootstrap_ci

    np.random.seed(1)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 50)})
    req = AnalysisRequest(task="bootstrap_ci", data=df, target_col="v",
                          params={"ci_level": 1.5, "n_bootstrap": 200})
    result = bootstrap_ci(req)
    assert result.status == "error"
    assert any("ci_level" in m for m in result.messages)


def test_median_ci_ci_level_out_of_range():
    """审查 2026-08-19 #1.3：median_ci 的 ci_level=2 不得输出 "200% CI"。"""
    from smartsuite.engine.exploratory import median_ci

    np.random.seed(1)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 50)})
    req = AnalysisRequest(task="median_ci", data=df, target_col="v",
                          params={"ci_level": 2})
    result = median_ci(req)
    assert result.status == "error"
    assert any("ci_level" in m for m in result.messages)


def test_median_ci_valid_level_still_works():
    """回归：合法 ci_level 正常工作。"""
    from smartsuite.engine.exploratory import median_ci

    np.random.seed(1)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 50)})
    req = AnalysisRequest(task="median_ci", data=df, target_col="v",
                          params={"ci_level": 0.90})
    result = median_ci(req)
    assert result.status == "ok"
    assert result.metadata["ci_level"] == 0.90


def test_power_analysis_effect_size_zero_rejected():
    """审查 2026-08-19 #1.4：effect_size=0 应返回中文错误而非 statsmodels ValueError。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    req = AnalysisRequest(task="power_analysis", data=df, target_col="v",
                          params={"effect_size": 0, "test_type": "ttest"})
    result = power_analysis(req)
    assert result.status == "error"
    assert any("effect_size" in m for m in result.messages)


def test_power_analysis_string_p0_p1_rejected():
    """审查 2026-08-19 #1.4：字符串 p0/p1 应返回中文错误而非 TypeError。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    req = AnalysisRequest(task="power_analysis", data=df, target_col="v",
                          params={"test_type": "proportion", "p0": "0.3", "p1": "oops"})
    result = power_analysis(req)
    assert result.status == "error"
    assert any("p0/p1" in m for m in result.messages)


def test_power_analysis_string_n_groups_convertible():
    """审查 2026-08-19 #1.4：n_groups='3' 应被安全转换而非 statsmodels TypeError。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    req = AnalysisRequest(task="power_analysis", data=df, target_col="v",
                          params={"test_type": "anova", "n_groups": "3", "effect_size": 0.5})
    result = power_analysis(req)
    assert result.status == "ok", f"n_groups='3' 应可转换: {result.messages}"
    assert result.metadata["required_n"] > 0


def test_power_analysis_proportion_mode_works():
    """回归：proportion 模式计算与曲线（审查 #2.10 不再误用 ANOVA 曲线）。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    req = AnalysisRequest(task="power_analysis", data=df, target_col="v",
                          params={"test_type": "proportion", "p0": 0.3, "p1": 0.5,
                                  "effect_size": 0.2, "target_power": 0.8})
    result = power_analysis(req)
    assert result.status == "ok", f"proportion 模式失败: {result.messages}"
    assert result.metadata["required_n"] > 0
    assert len(result.figures) == 1


def test_anomaly_grubbs_string_params_rejected():
    """审查 2026-08-19 #1.4：grubbs 分支字符串参数应返回中文错误而非 TypeError。"""
    from smartsuite.engine.detection import anomaly_detect

    np.random.seed(3)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 30)})
    req = AnalysisRequest(task="anomaly_detect", data=df, target_col="v",
                          params={"method": "grubbs", "alpha": "oops", "max_outliers": "5"})
    result = anomaly_detect(req)
    assert result.status == "error"
    assert any("alpha" in m for m in result.messages)

    req2 = AnalysisRequest(task="anomaly_detect", data=df, target_col="v",
                           params={"method": "grubbs", "alpha": "0.05", "max_outliers": "2"})
    result2 = anomaly_detect(req2)
    assert result2.status == "ok", f"合法字符串参数应可用: {result2.messages}"


# ── 审查 2026-08-19 #3.7 边界矩阵补齐 ──
import matplotlib.pyplot as _plt


def _close_result_figs(res):
    """释放分析结果中的 Figure，避免长循环下 matplotlib 内存累积（审查 #3.7）。"""
    for fig in getattr(res, "figures", []) or []:
        try:
            fig.clear()
            _plt.close(fig)
        except Exception:
            pass
    _plt.close("all")



def test_empty_dataframe_all_tasks_return_result():
    """空数据（0 行）：全部 40 任务不得抛异常（返回 ok 或带中文消息的 error）。"""
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate

    df = pd.DataFrame({"x": pd.Series(dtype=float), "y": pd.Series(dtype=float),
                       "g": pd.Series(dtype=object)})
    for task in sorted(TASK_REGISTRY.keys()):
        try:
            res = orchestrate(AnalysisRequest(
                task=task, data=df, target_col="y", feature_cols=["x", "g"]))
            assert res.task == task
            if res.status != "ok":
                assert len(res.messages) > 0, f"{task}: error 无消息"
            _close_result_figs(res)
        except Exception as exc:
            raise AssertionError(f"{task}: 空数据抛异常 {type(exc).__name__}: {exc}")


def test_all_nan_column_all_tasks_graceful():
    """全 NaN 列：全部 40 任务不得抛异常。"""
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate

    df = pd.DataFrame({"x": [np.nan] * 10, "y": [np.nan] * 10, "g": ["A"] * 10})
    for task in sorted(TASK_REGISTRY.keys()):
        try:
            res = orchestrate(AnalysisRequest(
                task=task, data=df, target_col="y", feature_cols=["x", "g"]))
            assert res.task == task
            _close_result_figs(res)
        except Exception as exc:
            raise AssertionError(f"{task}: 全 NaN 抛异常 {type(exc).__name__}: {exc}")


def test_single_row_all_tasks_graceful():
    """单行数据：全部 40 任务不得抛异常。"""
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate

    df = pd.DataFrame({"x": [1.0], "y": [2.0], "g": ["A"]})
    for task in sorted(TASK_REGISTRY.keys()):
        try:
            res = orchestrate(AnalysisRequest(
                task=task, data=df, target_col="y", feature_cols=["x", "g"]))
            assert res.task == task
            _close_result_figs(res)
        except Exception as exc:
            raise AssertionError(f"{task}: 单行抛异常 {type(exc).__name__}: {exc}")


def test_large_n_6000_all_tasks_graceful():
    """n>5000：全部 40 任务不得抛异常（性能哨兵）。"""
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate

    np.random.seed(7)
    n = 6000
    df = pd.DataFrame({
        "a": np.random.normal(0, 1, n),
        "b": np.random.normal(0, 1, n),
        "c": np.random.normal(0, 1, n),
        "y": np.random.normal(0, 1, n),
        "yb": np.random.choice([0, 1], n),
        "g": np.random.choice(["A", "B"], n),
    })
    for task in sorted(TASK_REGISTRY.keys()):
        try:
            target = "yb" if task in ("logistic_regression", "roc_analysis",
                                      "proportion_ci", "spc_attribute") else "y"
            features = ["g"] if task == "hypothesis_test" else ["a", "b", "c"]
            params = {"group_col": "g"} if task in ("hypothesis_test", "variance_test",
                                                    "box_chart") else {}
            res = orchestrate(AnalysisRequest(
                task=task, data=df, target_col=target, feature_cols=features, params=params))
            assert res.task == task
            _close_result_figs(res)
        except Exception as exc:
            raise AssertionError(f"{task}: n=6000 抛异常 {type(exc).__name__}: {exc}")


def test_anova_high_cardinality_factor_guarded():
    """审查 2026-08-19 #1.4：连续特征（数千水平）此前致 matplotlib 原生崩溃，
    现应返回明确中文错误。"""
    from smartsuite.engine.root_cause import anova_analysis

    np.random.seed(7)
    n = 6000
    df = pd.DataFrame({
        "a": np.random.normal(0, 1, n),
        "y": np.random.normal(0, 1, n),
    })
    req = AnalysisRequest(task="anova", data=df, target_col="y", feature_cols=["a"])
    result = anova_analysis(req)
    assert result.status == "error"
    assert any("水平数过多" in m or "分箱" in m for m in result.messages)


# ── Round-2 审查修复 批次A1 回归测试 ──


def test_multi_objective_duplicate_index_picks_valid_row():
    """Round-2 #A1：重复索引且首现行被 NaN 排除时，最优行必须是有效行（此前静默返回被排除行）。"""
    from smartsuite.engine.doe_opt import multi_objective_opt

    df = pd.DataFrame({"强度": [np.nan, 100.0, 50.0], "批次": ["P1", "P2", "P3"]}, index=[0, 0, 1])
    r = multi_objective_opt(AnalysisRequest(
        task="multi_objective", data=df, target_col="",
        feature_cols=["批次"],
        params={"objectives": [{"col": "强度", "direction": "maximize"}]}))
    assert r.status == "ok", f"multi_objective 失败: {r.messages}"
    best = r.metadata.get("optimal_params", {})
    assert best.get("批次") == "P2", f"应选有效行 P2(强度=100)，实际: {best}"


def test_anova_constant_target_rejected():
    """Round-2 #A2：常量目标列不得输出 R²=-inf + 虚假显著结论。"""
    from smartsuite.engine.root_cause import anova_analysis

    df = pd.DataFrame({"g": ["A"] * 10 + ["B"] * 10, "y": [5.0] * 20})
    r = anova_analysis(AnalysisRequest(task="anova", data=df, target_col="y", feature_cols=["g"]))
    assert r.status == "error", f"常量目标列应报错: {r.status}"
    assert any("常量" in m for m in r.messages)


def test_box_chart_group_col_equals_target_or_subcol():
    """Round-2 #A3：box_chart group_col 与目标列/次分类列同列时不得崩溃。"""
    from smartsuite.engine.exploratory import box_chart

    # group_col == target_col（数值列同时作 Y 与分组）
    df = pd.DataFrame({"v": np.repeat([1.0, 2.0], 20),
                       "w": np.random.normal(0, 1, 40)})
    r1 = box_chart(AnalysisRequest(task="box_chart", data=df, target_col="v",
                                   feature_cols=["w"], params={"group_col": "v"}))
    assert r1.status == "ok", f"group==target 崩溃: {r1.messages}"
    # group_col == feature_cols[1]（次分类列同列）
    df2 = pd.DataFrame({"v": np.random.normal(0, 1, 40), "g": ["A"] * 20 + ["B"] * 20,
                        "s": np.random.normal(0, 1, 40)})
    r2 = box_chart(AnalysisRequest(task="box_chart", data=df2, target_col="s",
                                   feature_cols=["v", "g"], params={"group_col": "g"}))
    assert r2.status == "ok", f"group==feat[1] 崩溃: {r2.messages}"


def test_grid_search_ranges_key_equals_target():
    """Round-2 #A4：grid_search 的 ranges 键与目标列相同（重复列）时不得 ValueError。"""
    from smartsuite.engine.doe_opt import grid_search

    np.random.seed(1)
    df = pd.DataFrame({"料温": np.random.uniform(170, 190, 30)})
    r = grid_search(AnalysisRequest(task="grid_search", data=df, target_col="料温",
                                    feature_cols=["料温"],
                                    params={"ranges": {"料温": [170, 190]}}))
    assert r.status == "ok", f"ranges==target 失败: {r.status} {r.messages[:1]}"


def test_spc_xbar_int64_x_axis_ordered():
    """Round-2 #A5：np.int64 X 列（Excel/CSV 默认类型）必须按数值序而非字典序。"""
    from smartsuite.engine.spc_charts import _natural_sort_key
    from smartsuite.engine.spc_monitor import xbar_r_chart

    np.random.seed(3)
    x = pd.Series(np.arange(1, 13), dtype="int64")
    y = np.random.normal(50, 2, 12)
    y[11] = 60.0
    df = pd.DataFrame({"x": x, "y": y})
    r = xbar_r_chart(AnalysisRequest(task="spc_xbar", data=df, target_col="y",
                                     feature_cols=[], params={"group_col": "x"}))
    assert r.status == "ok", f"spc_xbar 失败: {r.messages}"
    # 真实排序键验证：np.int64 序列必须数值序（旧 key 得 [1,10,11,12,2,...]）
    order = sorted(x.unique(), key=_natural_sort_key)
    assert [int(v) for v in order] == list(range(1, 13)), f"int64 排序错误: {order}"
    # float64 / Python int / 字符串混合类型不崩溃
    mixed = sorted([1, 10, 2, "a", 11.5], key=_natural_sort_key)
    assert mixed == [1, 2, 10, 11.5, "a"], f"混合类型排序错误: {mixed}"


# ── Round-2 审查修复 批次A2 回归测试 ──


def test_regression_constant_feature_rejected():
    """Round-2 #A2a：常量特征列 → 系数 t=inf/NaN（此前进入 Web JSON 链）。"""
    from smartsuite.engine.doe_opt import regression_analysis

    np.random.seed(1)
    df = pd.DataFrame({"x1": [5.0] * 30, "x2": np.random.normal(0, 1, 30),
                       "y": np.random.normal(0, 1, 30)})
    r = regression_analysis(AnalysisRequest(task="regression", data=df, target_col="y",
                                            feature_cols=["x1", "x2"]))
    assert r.status == "error", f"常量特征列应报错: {r.status}"
    assert any("常量" in m for m in r.messages)


def test_vif_constant_feature_detected():
    """Round-2 #A2b：常量特征列 VIF 不得误判为'无明显共线性'。"""
    from smartsuite.engine.root_cause import vif_analysis

    np.random.seed(1)
    df = pd.DataFrame({"x1": [1.0] * 10, "x2": np.random.normal(0, 1, 10)})
    r = vif_analysis(AnalysisRequest(task="vif", data=df, target_col="",
                                     feature_cols=["x1", "x2"]))
    assert r.status == "error", f"常量特征列 VIF 应报错: {r.status}"
    assert any("常量" in m for m in r.messages)


def test_orchestrate_empty_target_col_rejected():
    """Round-2 #A2c：空 target_col（''）应被 orchestrator 拦截为中文错误而非引擎 KeyError。"""
    from smartsuite.services.orchestrator import orchestrate

    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    r = orchestrate(AnalysisRequest(task="regression", data=df, target_col="",
                                    feature_cols=["x"]))
    assert r.status == "error"
    assert any("target" in m or "目标" in m for m in r.messages)


def test_hypothesis_test_unknown_test_type_rejected():
    """Round-2 #A2d：非法 test_type 不得静默跑 t 检验。"""
    from smartsuite.services.orchestrator import orchestrate

    df = pd.DataFrame({"g": ["A"] * 10 + ["B"] * 10, "v": np.random.normal(0, 1, 20)})
    r = orchestrate(AnalysisRequest(task="hypothesis_test", data=df, target_col="v",
                                    feature_cols=["g"],
                                    params={"test": "bogus_test", "group_col": "g"}))
    assert r.status == "error"
    assert any("test" in m or "检验" in m for m in r.messages)


def test_kruskal_continuous_fallback_rejected():
    """Round-2 #A2e：kruskal 无分组列时回退到连续特征列 → 不得输出 η²_H=1.000 误导结果。"""
    from smartsuite.services.orchestrator import orchestrate

    np.random.seed(5)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 60), "f": np.random.normal(0, 1, 60)})
    r = orchestrate(AnalysisRequest(task="hypothesis_test", data=df, target_col="v",
                                    feature_cols=["f"], params={"test": "kruskal"}))
    assert r.status == "error", f"连续列回退应报错: {r.status}"
    assert any("分组" in m for m in r.messages)


# ── Round-2 审查修复 批次A3 回归测试 ──


def test_trend_forecast_string_steps_rejected():
    """Round-2 #A3b：forecast_steps 字符串/非法值不得 TypeError。"""
    from smartsuite.engine.detection import trend_forecast

    np.random.seed(7)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 30)})
    r = trend_forecast(AnalysisRequest(task="trend_forecast", data=df, target_col="y",
                                       params={"forecast_steps": "abc"}))
    assert r.status == "error"
    assert any("forecast" in m or "预测" in m for m in r.messages)


def test_doe_analysis_string_factor_3levels():
    """Round-2 #A3c：>=3 水平字符串因子不得 TypeError 崩溃。"""
    from smartsuite.engine.doe_opt import doe_analysis

    np.random.seed(1)
    df = pd.DataFrame({
        "f": ["低"] * 10 + ["中"] * 10 + ["高"] * 10,
        "y": np.random.normal(0, 1, 30),
    })
    r = doe_analysis(AnalysisRequest(task="doe_analysis", data=df, target_col="y",
                                     feature_cols=["f"]))
    assert r.status in ("ok", "error"), f"doe_analysis 崩溃: {r.status}"
    if r.status == "error":
        assert any("无法" in m or "非数值" in m or "水平" in m for m in r.messages)


def test_anomaly_contamination_invalid_rejected():
    """Round-2 #A3d：contamination 非法值不得泄漏英文异常。"""
    from smartsuite.engine.detection import anomaly_detect

    np.random.seed(2)
    df = pd.DataFrame({"a": np.random.normal(0, 1, 30), "b": np.random.normal(0, 1, 30)})
    r = anomaly_detect(AnalysisRequest(task="anomaly_detect", data=df, target_col="a",
                                       feature_cols=["b"],
                                       params={"method": "isolation_forest",
                                               "contamination": "oops"}))
    assert r.status == "error"
    assert all("contamination" in m or "污染" in m for m in r.messages)
    assert "InvalidParameterError" not in " ".join(r.messages)


def test_survival_event_column_validation():
    """Round-2 #A3e：事件列编码 1/2（非 {0,1}）不得静默输出恒 1.0 的 KM 曲线。"""
    from smartsuite.engine.reliability import survival_analysis

    np.random.seed(3)
    df = pd.DataFrame({"t": np.random.exponential(100, 40),
                       "e": np.random.choice([1, 2], 40)})
    r = survival_analysis(AnalysisRequest(task="survival_analysis", data=df, target_col="t",
                                          feature_cols=["e"]))
    if r.status == "ok":
        tbl = r.tables.get("km_table")
        if tbl is not None and "生存概率" in tbl.columns:
            surv = tbl["生存概率"].astype(float)
            assert surv.iloc[-1] < 1.0, "KM 曲线不应恒为 1.0（存在失效事件但被静默忽略）"
    else:
        assert any("事件" in m for m in r.messages)


def test_ljung_box_q_matches_statsmodels():
    """Round-2 #A3a：Ljung-Box Q 与 statsmodels 参考一致（旧 np.corrcoef 偏大）。"""
    import statsmodels.stats.diagnostic as sm_diag

    from smartsuite.engine.detection import _ljung_box

    np.random.seed(7)
    x = np.random.normal(0, 1, 200)
    resid = x - x.mean()  # 非零均值残差更易暴露 corrcoef 偏差
    q, p, lags = _ljung_box(resid, lags=10)
    ref = sm_diag.acorr_ljungbox(resid, lags=[10], return_df=True)
    ref_q = float(ref["lb_stat"].iloc[0])
    assert abs(q - ref_q) < 0.5, f"Ljung-Box Q 偏差: 引擎={q:.2f} statsmodels={ref_q:.2f}"


# ── Round-2 审查修复 批次A4 回归测试 ──


def test_gage_rr_av_matches_anova():
    """Round-2 #A3f：AV（操作员分量）用 AIAG d2* 后应与 ANOVA 估计接近（此前高估）。"""
    from smartsuite.engine.reliability import gage_rr

    np.random.seed(6)
    parts = np.arange(1, 11)
    ops = ["O1", "O2", "O3"]
    rows = []
    true_vals = np.random.normal(50, 2, 10)
    for p_idx, p in enumerate(parts):
        for op in ops:
            op_bias = {"O1": 0.0, "O2": 0.4, "O3": -0.3}[op]
            for _ in range(3):
                rows.append({"part": p, "operator": op,
                             "measurement": true_vals[p_idx] + op_bias
                             + np.random.normal(0, 0.3)})
    df = pd.DataFrame(rows)
    r = gage_rr(AnalysisRequest(task="gage_rr", data=df, target_col="measurement",
                                feature_cols=["part", "operator"],
                                params={"part_col": "part", "operator_col": "operator"}))
    assert r.status == "ok", f"gage_rr 失败: {r.messages}"
    av = r.metadata.get("av")
    assert av is not None and av > 0, "AV 应可计算"
    import statsmodels.api as sm
    from statsmodels.formula.api import ols

    model = ols("measurement ~ C(part) + C(operator)", data=df).fit()
    aov = sm.stats.anova_lm(model, typ=2)
    # statsmodels 0.14+ 不输出 mean_sq 列 → 用 sum_sq/df 计算
    ms_op = float(aov.loc["C(operator)", "sum_sq"] / aov.loc["C(operator)", "df"])
    ms_e = float(aov.loc["Residual", "sum_sq"] / aov.loc["Residual", "df"])
    sigma_op = np.sqrt(max(0, (ms_op - ms_e) / (10 * 3)))
    assert abs(av - sigma_op) / sigma_op < 0.25, \
        f"AV={av:.4f} 与 ANOVA sigma_op={sigma_op:.4f} 偏差过大（d2* 修正应缩小差距）"


def test_power_analysis_achieved_n_groups_string():
    """Round-2 #A2f：achieved 分支 n_groups='3' 不得 TypeError。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    r = power_analysis(AnalysisRequest(
        task="power_analysis", data=df, target_col="v",
        params={"mode": "achieved", "test_type": "anova", "n_groups": "3",
                "current_n": 20, "effect_size": 0.5}))
    assert r.status == "ok", f"achieved n_groups 应可转换: {r.messages}"
    assert "功效" in r.summary


def test_power_analysis_effect_size_nan_rejected():
    """Round-2 #A2f：effect_size='nan' 不得穿透顶层校验。"""
    from smartsuite.engine.root_cause import power_analysis

    df = pd.DataFrame({"v": [1.0]})
    r = power_analysis(AnalysisRequest(
        task="power_analysis", data=df, target_col="v",
        params={"effect_size": "nan", "test_type": "ttest"}))
    assert r.status == "error"
    assert any("有限" in m or "effect" in m.lower() for m in r.messages)


def test_decision_tree_max_depth_zero_rejected():
    """Round-2 #A2g：max_depth=0 应返回中文错误而非 sklearn ValueError。"""
    from smartsuite.engine.root_cause import decision_tree_analysis

    np.random.seed(1)
    df = pd.DataFrame({"x1": np.random.normal(0, 1, 30), "y": np.random.normal(0, 1, 30)})
    r = decision_tree_analysis(AnalysisRequest(
        task="decision_tree", data=df, target_col="y", feature_cols=["x1"],
        params={"max_depth": 0}))
    assert r.status == "error"
    assert any("max_depth" in m for m in r.messages)


def test_cohens_kappa_full_consensus_undefined():
    """Round-2 #A2h：全一致表不得判'低于随机一致'（kappa 无定义）。"""
    from smartsuite.engine.root_cause import cohens_kappa

    df = pd.DataFrame({"r1": ["A"] * 10 + ["B"] * 10, "r2": ["A"] * 10 + ["B"] * 10})
    r = cohens_kappa(AnalysisRequest(task="cohens_kappa", data=df, target_col="r1",
                                     feature_cols=["r2"]))
    assert r.status == "error" or "几乎完美" in r.summary or "无定义" in " ".join(r.messages), \
        f"全一致表误判: {r.status} {r.summary[:60]}"


def test_cusum_partial_mu_sigma_rejected():
    """Round-2 #A2j：CUSUM 只传 mu 或 sigma 应报错（与 EWMA 一致）。"""
    from smartsuite.engine.spc_monitor import cusum_chart

    df = pd.DataFrame({"y": np.random.normal(0, 1, 30)})
    r = cusum_chart(AnalysisRequest(task="spc_cusum", data=df, target_col="y",
                                    feature_cols=[], params={"mu": 0.0}))
    assert r.status == "error"
    assert any("mu/sigma" in m for m in r.messages)


def test_process_capability_constant_data_rejected():
    """Round-2 #A2n：常量数据不得返回全 None 的 ok 结果。"""
    from smartsuite.engine.capability import process_capability_analysis

    df = pd.DataFrame({"v": [10.0] * 50})
    r = process_capability_analysis(AnalysisRequest(
        task="process_capability", data=df, target_col="v",
        params={"usl": 12, "lsl": 8}))
    assert r.status == "error"
    assert any("常量" in m for m in r.messages)


# ── Round-2 审查修复 批次A4b 回归测试（白名单）──


def test_anomaly_method_whitelist():
    """Round-2 #A2p：未知 method 不得静默按 Z-score 执行。"""
    from smartsuite.engine.detection import anomaly_detect

    np.random.seed(2)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 30)})
    r = anomaly_detect(AnalysisRequest(task="anomaly_detect", data=df, target_col="v",
                                       params={"method": "bogus"}))
    assert r.status == "error"
    assert any("method" in m or "方法" in m for m in r.messages)


def test_spc_nonparametric_side_whitelist():
    """Round-2 #A2p：未知 side 不得静默按双侧执行。"""
    from smartsuite.engine.spc_monitor import spc_nonparametric

    np.random.seed(2)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 30)})
    r = spc_nonparametric(AnalysisRequest(task="spc_nonparametric", data=df, target_col="y",
                                          feature_cols=[], params={"side": "both"}))
    assert r.status == "error"
    assert any("side" in m for m in r.messages)


def test_bootstrap_statistic_whitelist():
    """Round-2 #A2p：未知 statistic 不得静默按 mean 执行。"""
    from smartsuite.engine.exploratory import bootstrap_ci

    np.random.seed(2)
    df = pd.DataFrame({"v": np.random.normal(0, 1, 30)})
    r = bootstrap_ci(AnalysisRequest(task="bootstrap_ci", data=df, target_col="v",
                                     params={"statistic": "variance"}))
    assert r.status == "error"
    assert any("statistic" in m for m in r.messages)


def test_anova_quote_column_rejected():
    """Round-2 #A2o：含单引号列名应返回明确中文错误而非 patsy 解析失败。"""
    from smartsuite.engine.root_cause import anova_analysis

    df = pd.DataFrame({"a'b": ["A"] * 10 + ["B"] * 10, "y": np.random.normal(0, 1, 20)})
    r = anova_analysis(AnalysisRequest(task="anova", data=df, target_col="y",
                                       feature_cols=["a'b"]))
    assert r.status == "error"
    assert any("单引号" in m or "重命名" in m for m in r.messages)

# ── Round-2 批次D：常量列边界定向 + EWMA 回归 ──


def test_normality_check_constant_column():
    """边界定向（Round-2 批次D #6）：normality_check 常量列必须有明确结果。

    当前引擎行为：常量列 SW p=1.0 → 判定「正态 ✓」（无警告、不崩溃）。
    固定此确定性行为，防止未来回归成 NaN/崩溃。
    """
    from smartsuite.engine.root_cause import normality_check

    df = _make_df({"x": [5.0] * 20})
    result = normality_check(AnalysisRequest(task="normality_check", data=df, target_col="x"))
    assert result.status == "ok", f"常量列应可评估: {result.messages}"
    tbl = result.tables["normality_results"]
    row = tbl.iloc[0]
    assert str(row["Shapiro-Wilk p"]) == "1.0000", f"常量列 SW p 应为 1.0: {row['Shapiro-Wilk p']}"
    assert "正态" in str(row["正态性"]), f"常量列被判定为: {row['正态性']}"
    assert result.metadata["normal_count"] == 1


def test_outlier_consensus_constant_column():
    """边界定向（Round-2 批次D #6）：outlier_consensus 常量列 → 明确中文错误（IQR=0）。"""
    from smartsuite.engine.detection import outlier_consensus

    df = _make_df({"y": [5.0] * 30})
    result = outlier_consensus(AnalysisRequest(task="outlier_consensus", data=df, target_col="y"))
    assert result.status == "error", f"常量列应报错: {result.messages}"
    assert any("IQR" in m or "变化" in m or "异常" in m for m in result.messages), (
        f"应给出明确中文消息: {result.messages}"
    )


def test_trend_forecast_constant_y():
    """边界定向（Round-2 批次D #6）：trend_forecast 常量 y → error（防 R²=1.0 假完美）。"""
    from smartsuite.engine.detection import trend_forecast

    df = _make_df({"t": list(range(30)), "y": [5.0] * 30})
    result = trend_forecast(AnalysisRequest(task="trend_forecast", data=df, target_col="y"))
    assert result.status == "error", f"常量 y 应报错而非 R²=1.0: {result.messages}"
    assert any("常量" in m for m in result.messages), f"应提示常量列: {result.messages}"


def test_ewma_partial_mu_sigma_rejected():
    """Round-2 批次D #4a：EWMA 只传 mu 或 sigma 应 error（此前静默忽略两个参数）。"""
    from smartsuite.engine.spc_charts import ewma_chart

    np.random.seed(3)
    df = _make_df({"y": np.random.normal(0, 1, 30)})
    r_mu = ewma_chart(AnalysisRequest(task="spc_ewma", data=df, target_col="y",
                                      params={"lam": 0.2, "L": 2.7, "mu": 0.0}))
    assert r_mu.status == "error", f"只传 mu 应报错: {r_mu.messages}"
    assert any("mu/sigma" in m for m in r_mu.messages), f"应提示 mu/sigma 同传: {r_mu.messages}"
    r_sigma = ewma_chart(AnalysisRequest(task="spc_ewma", data=df, target_col="y",
                                         params={"lam": 0.2, "L": 2.7, "sigma": 1.0}))
    assert r_sigma.status == "error", f"只传 sigma 应报错: {r_sigma.messages}"
    assert any("mu/sigma" in m for m in r_sigma.messages)
    # 回归：两者都传仍可用
    r_both = ewma_chart(AnalysisRequest(task="spc_ewma", data=df, target_col="y",
                                        params={"lam": 0.2, "L": 2.7, "mu": 0.0, "sigma": 1.0}))
    assert r_both.status == "ok", f"mu/sigma 同传应 ok: {r_both.messages}"
def test_weco_rules_7_and_8_detected():
    """Round-2 #A2r：交替升降（规则7）与连续8点在±1σ外（规则8）应被检出。"""
    from smartsuite.engine.spc_charts import _we_rules_xbar

    # 规则7：交替升降
    alt = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    v7 = _we_rules_xbar(np.array(alt, dtype=float), cl=0.5, sigma=0.6)
    assert any("交替" in k for k in v7), f"规则7未检出: {list(v7.keys())}"
    # 规则8：连续8点在±1σ外
    outside = [2.0] * 8 + [0.0] * 4
    v8 = _we_rules_xbar(np.array(outside, dtype=float), cl=0.0, sigma=0.5)
    assert any("±1σ外" in k or "1σ外" in k for k in v8), f"规则8未检出: {list(v8.keys())}"


def test_change_point_min_segment_half_n_rejected():
    """Round-2 #A2q：min_segment*2 > n（含偶数 n//2 边界）应报错而非静默无变点。"""
    from smartsuite.engine.detection import change_point_detect

    np.random.seed(42)
    df = pd.DataFrame({"x": np.random.normal(10, 0.5, 40)})
    r = change_point_detect(AnalysisRequest(task="change_point", data=df, target_col="x",
                                            params={"min_segment": 20, "n_changepoints": 3}))
    assert r.status == "error"
    assert any("min_segment" in m for m in r.messages)

