"""DOE/优化子包（原 doe_opt.py，2026-09-19 拆分）。"""

from smartsuite.engine.doe_opt.classification import logistic_regression, roc_analysis
from smartsuite.engine.doe_opt.doe import doe_analysis, doe_design
from smartsuite.engine.doe_opt.optimization import grid_search, multi_objective_opt
from smartsuite.engine.doe_opt.regression import (
    lasso_regression,
    quantile_regression,
    regression_analysis,
    robust_regression,
)
from smartsuite.engine.doe_opt.response_surface import response_surface_analysis

__all__ = [
    "doe_analysis",
    "doe_design",
    "grid_search",
    "lasso_regression",
    "logistic_regression",
    "multi_objective_opt",
    "quantile_regression",
    "regression_analysis",
    "response_surface_analysis",
    "robust_regression",
    "roc_analysis",
]
