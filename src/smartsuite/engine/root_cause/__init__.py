"""要因分析/统计推断子包（原 root_cause.py，2026-09-19 拆分）。"""

from smartsuite.engine.root_cause.anova import anova_analysis
from smartsuite.engine.root_cause.association import (
    cohens_kappa,
    contingency_analysis,
    cronbach_alpha,
)
from smartsuite.engine.root_cause.correlation import correlation_analysis
from smartsuite.engine.root_cause.design import power_analysis
from smartsuite.engine.root_cause.distribution import distribution_summary, normality_check
from smartsuite.engine.root_cause.hypothesis import hypothesis_test
from smartsuite.engine.root_cause.inference import proportion_ci, variance_test
from smartsuite.engine.root_cause.modeling import decision_tree_analysis, vif_analysis

__all__ = [
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
