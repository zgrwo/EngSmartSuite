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
    """全 NaN 列应被优雅处理。"""
    df = _make_df({"x": [np.nan, np.nan, np.nan], "y": [1.0, 2.0, 3.0]})
    req = AnalysisRequest(task="correlation", data=df, target_col="y", feature_cols=["x"])
    result = correlation_analysis(req)
    assert result.status in ("ok", "error")  # 不应崩溃


def test_zero_variance_column():
    """零方差列应被检测并处理。"""
    df = _make_df({"x": [5.0, 5.0, 5.0, 5.0, 5.0], "y": [1.0, 2.0, 3.0, 4.0, 5.0]})
    req = AnalysisRequest(task="doe_analysis", data=df, target_col="y", feature_cols=["x"])
    result = doe_analysis(req)
    assert result.status in ("ok", "error")


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
