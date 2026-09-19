"""拆分回归钉子：doe_opt 公开 API 与 engine 导出同一对象（巨石拆分安全网）。"""

DOE_OPT_PUBLIC = [
    "regression_analysis",
    "response_surface_analysis",
    "grid_search",
    "multi_objective_opt",
    "doe_analysis",
    "roc_analysis",
    "logistic_regression",
    "lasso_regression",
    "robust_regression",
    "quantile_regression",
    "doe_design",
]


def test_public_functions_importable_from_doe_opt():
    import smartsuite.engine.doe_opt as doe

    for name in DOE_OPT_PUBLIC:
        assert callable(getattr(doe, name)), f"{name} 不可从 doe_opt 导入"


def test_doe_opt_is_engine_single_source_of_truth():
    import smartsuite.engine as eng
    import smartsuite.engine.doe_opt as doe

    for name in DOE_OPT_PUBLIC:
        assert getattr(eng, name) is getattr(doe, name), f"{name} 非同一对象"
