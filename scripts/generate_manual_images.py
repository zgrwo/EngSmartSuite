"""为 user-manual.md 生成所有示例图片到 docs/images/"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd, numpy as np, os

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data

df = pd.read_excel("tests/test_data.xlsx")
OUT = "docs/images"
os.makedirs(OUT, exist_ok=True)

def save_figs(result, prefix, max_n=2):
    """Save figures from an AnalysisResult, return list of filenames."""
    saved = []
    for i, fig in enumerate(result.figures[:max_n]):
        fname = f"{prefix}_{i+1}.png"
        path = os.path.join(OUT, fname)
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        saved.append(fname)
        print(f"  Saved: {fname} ({os.path.getsize(path)//1024}KB)")
    return saved

images_map = {}  # section_key -> list of filenames

# ── 1. correlation ──
print("\n=== correlation ===")
from smartsuite.engine.root_cause import correlation_analysis
r = correlation_analysis(AnalysisRequest(task="correlation", data=df, target_col="不良率",
    feature_cols=["熔体温度","模具温度","注射压力","冷却时间"]))
images_map["correlation"] = save_figs(r, "correlation")

# ── 2. anova ──
print("\n=== anova ===")
from smartsuite.engine.root_cause import anova_analysis
r = anova_analysis(AnalysisRequest(task="anova", data=df, target_col="不良率",
    feature_cols=["原料类型"]))
images_map["anova"] = save_figs(r, "anova")

# ── 3. hypothesis_test ──
print("\n=== hypothesis_test ===")
from smartsuite.engine.root_cause import hypothesis_test
r = hypothesis_test(AnalysisRequest(task="hypothesis_test", data=df, target_col="不良率",
    feature_cols=["保养日"], params={"test": "ttest_ind", "group_col": "保养日"}))
images_map["hypothesis_test"] = save_figs(r, "hypothesis_test")

# ── 4. decision_tree ──
print("\n=== decision_tree ===")
from smartsuite.engine.root_cause import decision_tree_analysis
r = decision_tree_analysis(AnalysisRequest(task="decision_tree", data=df, target_col="不良率",
    feature_cols=["熔体温度","模具温度","注射压力","冷却时间"]))
images_map["decision_tree"] = save_figs(r, "decision_tree")

# ── 5. vif ──
print("\n=== vif ===")
from smartsuite.engine.root_cause import vif_analysis
r = vif_analysis(AnalysisRequest(task="vif", data=df, target_col="",
    feature_cols=["熔体温度","模具温度","注射压力","冷却时间"]))
images_map["vif"] = save_figs(r, "vif")

# ── 6. regression ──
print("\n=== regression ===")
from smartsuite.engine.doe_opt import regression_analysis
r = regression_analysis(AnalysisRequest(task="regression", data=df, target_col="不良率",
    feature_cols=["熔体温度","注射压力","冷却时间"]))
images_map["regression"] = save_figs(r, "regression")

# ── 7. response_surface ──
print("\n=== response_surface ===")
from smartsuite.engine.doe_opt import response_surface_analysis
r = response_surface_analysis(AnalysisRequest(task="response_surface", data=df,
    target_col="不良率", feature_cols=["熔体温度","模具温度"]))
images_map["response_surface"] = save_figs(r, "response_surface")

# ── 8. roc_analysis ──
print("\n=== roc_analysis ===")
from smartsuite.engine.doe_opt import roc_analysis
r = roc_analysis(AnalysisRequest(task="roc_analysis", data=df, target_col="首件合格",
    feature_cols=["熔体温度"]))
images_map["roc_analysis"] = save_figs(r, "roc_analysis")

# ── 9. logistic_regression ──
print("\n=== logistic_regression ===")
from smartsuite.engine.doe_opt import logistic_regression
r = logistic_regression(AnalysisRequest(task="logistic_regression", data=df,
    target_col="保养日", feature_cols=["熔体温度","模具温度"]))
images_map["logistic_regression"] = save_figs(r, "logistic_regression")

# ── 10. lasso_regression ──
print("\n=== lasso_regression ===")
from smartsuite.engine.doe_opt import lasso_regression
r = lasso_regression(AnalysisRequest(task="lasso_regression", data=df, target_col="不良率",
    feature_cols=["熔体温度","模具温度","注射压力"]))
images_map["lasso_regression"] = save_figs(r, "lasso_regression")

# ── 11. robust_regression ──
print("\n=== robust_regression ===")
from smartsuite.engine.doe_opt import robust_regression
r = robust_regression(AnalysisRequest(task="robust_regression", data=df, target_col="不良率",
    feature_cols=["熔体温度"]))
images_map["robust_regression"] = save_figs(r, "robust_regression")

# ── 12. process_capability ──
print("\n=== process_capability ===")
from smartsuite.engine.spc_monitor import process_capability_analysis
r = process_capability_analysis(AnalysisRequest(task="process_capability", data=df,
    target_col="不良率", params={"usl": 10, "lsl": 1}))
images_map["process_capability"] = save_figs(r, "process_capability")

# ── 13. trend_forecast ──
print("\n=== trend_forecast ===")
from smartsuite.engine.spc_monitor import trend_forecast
r = trend_forecast(AnalysisRequest(task="trend_forecast", data=df, target_col="不良率"))
images_map["trend_forecast"] = save_figs(r, "trend_forecast", max_n=1)

# ── 14. cusum ──
print("\n=== cusum ===")
from smartsuite.engine.spc_monitor import cusum_chart
r = cusum_chart(AnalysisRequest(task="spc_cusum", data=df, target_col="不良率"))
images_map["cusum"] = save_figs(r, "cusum")

# ── 15. ewma ──
print("\n=== ewma ===")
from smartsuite.engine.spc_monitor import ewma_chart
r = ewma_chart(AnalysisRequest(task="spc_ewma", data=df, target_col="不良率"))
images_map["ewma"] = save_figs(r, "ewma")

# ── 16. anomaly_detect ──
print("\n=== anomaly_detect ===")
from smartsuite.engine.spc_monitor import anomaly_detect
r = anomaly_detect(AnalysisRequest(task="anomaly_detect", data=df, target_col="不良率",
    params={"method": "iqr"}))
images_map["anomaly_detect"] = save_figs(r, "anomaly_detect")

# ── 17. change_point ──
print("\n=== change_point ===")
from smartsuite.engine.spc_monitor import change_point_detect
r = change_point_detect(AnalysisRequest(task="change_point", data=df, target_col="不良率"))
images_map["change_point"] = save_figs(r, "change_point")

# ── 18. outlier_consensus ──
print("\n=== outlier_consensus ===")
from smartsuite.engine.spc_monitor import outlier_consensus
r = outlier_consensus(AnalysisRequest(task="outlier_consensus", data=df, target_col="不良率",
    feature_cols=["熔体温度"]))
images_map["outlier_consensus"] = save_figs(r, "outlier_consensus")

# ── 19. bootstrap_ci ──
print("\n=== bootstrap_ci ===")
from smartsuite.engine.spc_monitor import bootstrap_ci
r = bootstrap_ci(AnalysisRequest(task="bootstrap_ci", data=df, target_col="不良率",
    params={"statistic": "mean", "n_bootstrap": 200}))
images_map["bootstrap_ci"] = save_figs(r, "bootstrap_ci")

# ── 20. median_ci ──
print("\n=== median_ci ===")
from smartsuite.engine.spc_monitor import median_ci
r = median_ci(AnalysisRequest(task="median_ci", data=df, target_col="不良率"))
images_map["median_ci"] = save_figs(r, "median_ci")

# ── 21. box_chart ──
print("\n=== box_chart (simple) ===")
from smartsuite.engine.spc_monitor import box_chart
r = box_chart(AnalysisRequest(task="box_chart", data=df, target_col="不良率",
    feature_cols=["原料类型"]))
images_map["box_chart"] = save_figs(r, "box_chart")

# ── 22. box_chart (sub) ──
print("\n=== box_chart (with sub-category) ===")
r = box_chart(AnalysisRequest(task="box_chart", data=df, target_col="不良率",
    feature_cols=["原料类型","车间"]))
images_map["box_chart_sub"] = save_figs(r, "box_chart_sub")

# ── 23. distribution_summary ──
print("\n=== distribution_summary ===")
from smartsuite.engine.root_cause import distribution_summary
r = distribution_summary(AnalysisRequest(task="distribution_summary", data=df,
    target_col="不良率"))
images_map["distribution_summary"] = save_figs(r, "distribution_summary")

# ── 24. normality_check ──
print("\n=== normality_check ===")
from smartsuite.engine.root_cause import normality_check
r = normality_check(AnalysisRequest(task="normality_check", data=df, target_col="不良率",
    feature_cols=["熔体温度"]))
images_map["normality_check"] = save_figs(r, "normality_check")

# ── 25. contingency ──
print("\n=== contingency ===")
from smartsuite.engine.root_cause import contingency_analysis
r = contingency_analysis(AnalysisRequest(task="contingency", data=df, target_col="原料类型",
    feature_cols=["保养日"]))
images_map["contingency"] = save_figs(r, "contingency")

# ── 26. doe_analysis ──
print("\n=== doe_analysis ===")
from smartsuite.engine.doe_opt import doe_analysis
r = doe_analysis(AnalysisRequest(task="doe_analysis", data=df, target_col="不良率",
    feature_cols=["熔体温度","模具温度","注射压力"]))
images_map["doe_analysis"] = save_figs(r, "doe_analysis")

# ── 27. grid_search ──
print("\n=== grid_search ===")
from smartsuite.engine.doe_opt import grid_search
r = grid_search(AnalysisRequest(task="grid_search", data=df, target_col="不良率",
    feature_cols=["熔体温度"], params={"ranges": {"熔体温度": [180, 220]}, "n_points": 10,
    "direction": "minimize"}))
images_map["grid_search"] = save_figs(r, "grid_search")

# ── 28. survival_analysis ──
print("\n=== survival_analysis ===")
from smartsuite.engine.spc_monitor import survival_analysis
r = survival_analysis(AnalysisRequest(task="survival_analysis", data=df, target_col="不良率",
    feature_cols=["保养日"]))
images_map["survival_analysis"] = save_figs(r, "survival_analysis")

# ── 29. power_analysis ──
print("\n=== power_analysis ===")
from smartsuite.engine.root_cause import power_analysis
r = power_analysis(AnalysisRequest(task="power_analysis", data=df, target_col="", feature_cols=[],
    params={"mode": "required_n", "test_type": "ttest", "effect_size": 0.5}))
images_map["power_analysis"] = save_figs(r, "power_analysis")

# ── 30. tolerance_interval ──
print("\n=== tolerance_interval ===")
from smartsuite.engine.spc_monitor import tolerance_interval
r = tolerance_interval(AnalysisRequest(task="tolerance_interval", data=df, target_col="不良率"))
images_map["tolerance_interval"] = save_figs(r, "tolerance_interval")

# ── Summary ──
print(f"\n{'='*50}")
print(f"Total: {sum(len(v) for v in images_map.values())} images in {OUT}/")
total_kb = sum(os.path.getsize(os.path.join(OUT, f))
               for v in images_map.values() for f in v)
print(f"Total size: {total_kb//1024}KB")
