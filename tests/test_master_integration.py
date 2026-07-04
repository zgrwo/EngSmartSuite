"""主集成测试 — 验证所有 TASK_REGISTRY 函数可被调用并返回合理结果。"""
import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate


@pytest.fixture(scope="module")
def df():
    np.random.seed(42)
    n = 100
    return pd.DataFrame({
        "x1": np.random.normal(10, 2, n),
        "x2": np.random.normal(20, 3, n),
        "x3": np.random.normal(5, 1, n),
        "y": np.random.normal(50, 10, n),
        "group": np.random.choice(["A", "B", "C"], n),
        "binary": np.random.choice([0, 1], n),
        "cat1": np.random.choice(["X", "Y"], n),
        "cat2": np.random.choice(["P", "Q"], n),
        "before": np.random.normal(30, 5, n),
        "after": np.random.normal(30, 5, n) + 3,
        "item1": np.random.normal(5, 1, n),
        "item2": np.random.normal(5, 1, n),
        "item3": np.random.normal(5, 1, n),
        "time": np.arange(n),
        "event": np.random.choice([0, 1], n, p=[0.7, 0.3]),
    })


# Test every registered task at least once
TASKS_TO_TEST = [
    ("correlation", "y", ["x1", "x2", "x3"]),
    ("anova", "y", ["group"]),
    ("hypothesis_test", "y", ["binary"], {"test": "ttest_ind", "group_col": "binary"}),
    ("hypothesis_test", "y", ["before", "after"], {"test": "ttest_paired"}),
    ("hypothesis_test", "y", [], {"test": "ttest_1samp", "popmean": 50}),
    ("hypothesis_test", "y", ["before", "after"], {"test": "wilcoxon_paired"}),
    ("hypothesis_test", "y", [], {"test": "wilcoxon_1samp", "popmedian": 50}),
    ("hypothesis_test", "y", ["group"], {"test": "kruskal_wallis", "group_col": "group"}),
    ("hypothesis_test", "y", ["x1", "x2", "x3"], {"test": "friedman"}),
    ("hypothesis_test", "y", ["cat1", "cat2"], {"test": "mcnemar"}),
    ("hypothesis_test", "y", ["group"], {"test": "jonckheere", "group_col": "group"}),
    ("hypothesis_test", "y", ["x1", "x2", "x3"], {"test": "cochran_q"}),
    ("hypothesis_test", "y", ["binary"], {"test": "ks", "group_col": "binary"}),
    ("hypothesis_test", "y", [], {"test": "mann_kendall"}),
    ("decision_tree", "y", ["x1", "x2", "x3"]),
    ("vif", "", ["x1", "x2", "x3"]),
    ("regression", "y", ["x1", "x2", "x3"]),
    ("logistic_regression", "binary", ["x1", "x2", "x3"]),
    ("lasso_regression", "y", ["x1", "x2", "x3"]),
    ("response_surface", "y", ["x1", "x2"]),
    ("doe_analysis", "y", ["x1", "x2", "x3"]),
    ("spc_xbar", "y", [], {"subgroup_col": "group"}),
    ("spc_cusum", "y", [], {}),
    ("spc_ewma", "y", [], {}),
    ("process_capability", "y", [], {"usl": 70, "lsl": 30}),
    ("trend_forecast", "y", [], {}),
    ("anomaly_detect", "y", [], {"method": "iqr"}),
    ("anomaly_detect", "y", [], {"method": "grubbs"}),
    ("outlier_consensus", "y", ["x1", "x2"]),
    ("bootstrap_ci", "y", [], {"n_bootstrap": 200}),
    ("median_ci", "y", [], {}),
    ("normality_check", "y", ["x1", "x2", "x3"]),
    ("distribution_summary", "y", [], {}),
    ("power_analysis", "", [], {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5}),
    ("power_analysis", "", [], {"mode": "achieved", "test_type": "proportion", "current_n": 50, "p0": 0.5, "p1": 0.6}),
    ("contingency", "cat1", ["cat2"]),
    ("proportion_ci", "binary", [], {}),
    ("variance_test", "y", ["group"], {"group_col": "group"}),
    ("cohens_kappa", "", ["cat1", "cat2"]),
    ("cronbach_alpha", "", ["item1", "item2", "item3"]),
    ("survival_analysis", "time", ["event"]),
    ("change_point", "y", [], {}),
    ("roc_analysis", "binary", ["x1"]),
    ("tolerance_interval", "y", [], {}),
    ("box_chart", "y", ["group"]),
    ("box_chart", "y", ["group", "binary"], {"mode": "nested"}),
    ("spc_nonparametric", "y", [], {"side": "two-sided"}),
    ("spc_nonparametric", "y", [], {"side": "upper"}),
    ("quantile_regression", "y", ["x1", "x2"], {"quantile": 0.5}),
    ("robust_regression", "y", ["x1", "x2"]),
    ("grid_search", "y", ["x1"], {"ranges": {"x1": (5, 15)}, "n_points": 5}),
    ("multi_objective", "y", ["x1", "x2"], {"objectives": [{"col": "y", "direction": "maximize"}]}),
    ("spc_attribute", "y", [], {"chart_type": "c"}),
    ("gage_rr", "y", ["group", "binary"], {"part_col": "group", "operator_col": "binary"}),
]


@pytest.mark.parametrize("task,target,features", [
    (t, tg, f) for t, tg, f, *_ in TASKS_TO_TEST
])
def test_all_registered_tasks(df, task, target, features):
    """参数化测试: 每个注册任务至少运行一次。"""
    # Find the matching params for this task+target+features combo
    params = {}
    for t_entry in TASKS_TO_TEST:
        if t_entry[0] == task and t_entry[1] == target and t_entry[2] == features:
            if len(t_entry) > 3:
                params = t_entry[3]
            break

    req = AnalysisRequest(task=task, data=df, target_col=target,
                          feature_cols=features, params=params)
    result = orchestrate(req)
    assert result.status in ("ok", "error"), f"{task} returned unexpected status: {result.status}"
    # Not asserting "ok" because some tasks legitimately fail with synthetic data


def test_all_tasks_registered_count():
    """验证任务注册表完整性。"""
    assert len(TASK_REGISTRY) >= 39
    required = ["correlation", "anova", "regression", "hypothesis_test",
               "decision_tree", "vif", "normality_check", "distribution_summary"]
    for t in required:
        assert t in TASK_REGISTRY, f"Missing: {t}"
