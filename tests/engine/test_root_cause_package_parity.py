"""拆分回归钉子：root_cause 公开 API 与 engine 导出同一对象（I3 拆分安全网）。"""

ROOT_CAUSE_PUBLIC = [
    "correlation_analysis",
    "anova_analysis",
    "hypothesis_test",
    "decision_tree_analysis",
    "vif_analysis",
    "power_analysis",
    "contingency_analysis",
    "proportion_ci",
    "variance_test",
    "cohens_kappa",
    "cronbach_alpha",
    "distribution_summary",
    "normality_check",
]


def test_public_functions_importable_from_root_cause():
    import smartsuite.engine.root_cause as rc

    for name in ROOT_CAUSE_PUBLIC:
        assert callable(getattr(rc, name)), f"{name} 不可从 root_cause 导入"


def test_root_cause_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.root_cause as rc

    for name in ROOT_CAUSE_PUBLIC:
        assert getattr(eng, name) is getattr(rc, name), f"{name} 非同一对象"
