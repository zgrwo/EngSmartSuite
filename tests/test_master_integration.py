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
    ("spc_xbar", "y", ["group"], {}),
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


@pytest.mark.parametrize("task,target,features,params", [
    (t[0], t[1], t[2], t[3] if len(t) > 3 else {}) for t in TASKS_TO_TEST
])
def test_all_registered_tasks(df, task, target, features, params):
    """参数化测试: 每个注册任务 + 参数变体至少运行一次。"""
    req = AnalysisRequest(task=task, data=df, target_col=target,
                          feature_cols=features, params=params)
    result = orchestrate(req)
    assert result.status in ("ok", "error"), f"{task}: unexpected status {result.status}"
    assert result.task == task, f"{task}: task mismatch {result.task}"

    if result.status == "ok":
        # 成功结果必须包含有意义的输出
        assert isinstance(result.summary, str) and len(result.summary) > 0, (
            f"{task}: summary 为空")
        assert isinstance(result.tables, dict), f"{task}: tables 不是 dict"
        assert isinstance(result.figures, list), f"{task}: figures 不是 list"
        assert isinstance(result.metadata, dict), f"{task}: metadata 不是 dict"
    else:
        # 错误结果必须包含错误消息
        assert len(result.messages) > 0, f"{task}: error 但没有 messages"
        assert any(len(m) > 0 for m in result.messages), f"{task}: messages 全为空字符串"


def test_all_tasks_registered_count():
    """验证任务注册表完整性。"""
    assert len(TASK_REGISTRY) == 39, f"Expected 39 tasks, got {len(TASK_REGISTRY)}"
    required = ["correlation", "anova", "regression", "hypothesis_test",
               "decision_tree", "vif", "normality_check", "distribution_summary"]
    for t in required:
        assert t in TASK_REGISTRY, f"Missing: {t}"


def test_registry_label_group_consistency():
    """验证 TASK_REGISTRY ↔ TASK_LABELS ↔ TASK_GROUPS 三者一致。

    新增任务时如果忘记同步更新 web/app.py 的标签或分组，此测试会立即发现。
    """
    from smartsuite.services.orchestrator import TASK_GROUPS, TASK_LABELS

    registry_keys = set(TASK_REGISTRY.keys())
    label_keys = set(TASK_LABELS.keys())
    # 展开 TASK_GROUPS 的所有任务
    group_keys: set[str] = set()
    for group_tasks in TASK_GROUPS.values():
        group_keys.update(group_tasks)

    # 1. TASK_REGISTRY ↔ TASK_LABELS 一致
    missing_labels = registry_keys - label_keys
    extra_labels = label_keys - registry_keys
    assert not missing_labels, (
        f"TASK_REGISTRY 中有 {len(missing_labels)} 个任务缺少 TASK_LABELS: {sorted(missing_labels)}"
    )
    assert not extra_labels, (
        f"TASK_LABELS 中有 {len(extra_labels)} 个任务未在 TASK_REGISTRY 注册: {sorted(extra_labels)}"
    )

    # 2. TASK_REGISTRY ↔ TASK_GROUPS 一致
    missing_groups = registry_keys - group_keys
    extra_groups = group_keys - registry_keys
    assert not missing_groups, (
        f"TASK_REGISTRY 中有 {len(missing_groups)} 个任务未分配到任何 TASK_GROUPS: {sorted(missing_groups)}"
    )
    assert not extra_groups, (
        f"TASK_GROUPS 中有 {len(extra_groups)} 个任务未在 TASK_REGISTRY 注册: {sorted(extra_groups)}"
    )

    # 3. 无任务同时属于多个分组
    all_grouped = []
    for group_tasks in TASK_GROUPS.values():
        all_grouped.extend(group_tasks)
    duplicates = [t for t in set(all_grouped) if all_grouped.count(t) > 1]
    assert not duplicates, f"以下任务同时属于多个 TASK_GROUPS: {duplicates}"
