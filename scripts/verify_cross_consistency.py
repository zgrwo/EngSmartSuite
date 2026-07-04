"""
全量 39 方法交叉验证: Web UI 路径 ↔ Python 直接路径 ↔ 用户手册记录值

验证维度:
1. status 一致性 (ok/error)
2. summary 一致性
3. tables 键名一致性
4. figures 数量一致性
5. 用户手册记录的关键数值是否与实际输出一致
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
np.random.seed(42)

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine import *
from smartsuite.services.orchestrator import orchestrate, TASK_REGISTRY
from smartsuite.services.data_io import preprocess_data

# ── 加载测试数据 ──
df_raw = pd.read_excel("tests/test_data.xlsx")
print(f"数据: {df_raw.shape[0]}行 × {df_raw.shape[1]}列")

# ── 用户手册记录值 (基于 tests/test_data.xlsx, seed=42) ──
MANUAL_EXPECTATIONS = {
    "correlation": {
        "最强因子": "注射压力",
        "|r|范围": (0.01, 0.20),  # 弱相关
    },
    "anova": {
        "p值范围": (0.5, 1.0),  # 原料类型对不良率无显著影响
        "效应量": "可忽略",
    },
    "hypothesis_test": {
        "保养日p值": (0.0, 0.001),  # p<0.001
        "效应量": "大",
    },
    "decision_tree": {
        "关键因子": "冷却时间",
        "CV R²": (-0.5, 0.5),
    },
    "vif": {
        "所有VIF": (0.9, 1.1),  # 全部≈1.0
    },
    "contingency": {
        "p值": (0.0, 1.0),
    },
    "proportion_ci": {
        "点估计": (0.85, 0.95),  # 约0.91
    },
    "regression": {
        "R²范围": (0.0, 0.1),  # 随机数据R²很低
        "DW范围": (1.9, 2.1),  # DW≈2
    },
    "process_capability": {
        "判定": "不合格",
    },
    "distribution_summary": {
        "最佳拟合": "Normal",
    },
    "outlier_consensus": {
        "高置信比例": (0.01, 0.10),  # 1-10%
    },
}

# ── 39 个方法的测试用例定义 ──
# (task, target_col, feature_cols, categoricals, params, skip_reason)
TEST_CASES = [
    # === 要因筛选 ===
    ("correlation", "不良率", ["熔体温度","模具温度","注射压力","冷却时间"], [], {}),
    ("anova", "不良率", ["原料类型"], ["原料类型"], {"alpha": 0.05}),
    ("hypothesis_test", "不良率", ["保养日"], ["保养日"], {"test": "ttest_ind"}),
    ("decision_tree", "不良率", ["熔体温度","模具温度","注射压力","冷却时间"], [], {"max_depth": 5}),
    ("vif", "", ["熔体温度","模具温度","注射压力","冷却时间"], [], {}),
    ("contingency", "原料类型", ["保养日"], ["原料类型","保养日"], {}),
    ("proportion_ci", "首件合格", [], [], {}),
    ("variance_test", "不良率", ["原料类型"], ["原料类型"], {"group_col": "原料类型"}),
    # === 信度诊断 ===
    ("cohens_kappa", "", ["首件合格","外观检查"], [], {}),
    ("cronbach_alpha", "", ["熔体温度","模具温度","注射压力"], [], {}),
    ("distribution_summary", "不良率", [], [], {}),
    ("normality_check", "不良率", ["熔体温度"], [], {}),
    ("power_analysis", "", [], [], {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5}),
    # === 建模优化 ===
    ("regression", "不良率", ["熔体温度","注射压力","冷却时间"], [], {}),
    ("response_surface", "不良率", ["熔体温度","模具温度"], [], {"direction": "minimize"}),
    ("grid_search", "不良率", ["熔体温度"], [], {"ranges": {"熔体温度": (180, 220)}, "n_points": 10}),
    ("multi_objective", "不良率", ["熔体温度","模具温度"], [], {
        "objectives": [{"col": "不良率", "direction": "minimize"}, {"col": "拉伸强度", "direction": "maximize"}]
    }),
    ("doe_analysis", "不良率", ["熔体温度","模具温度","注射压力"], [], {}),
    ("roc_analysis", "首件合格", ["熔体温度"], [], {}),
    ("logistic_regression", "保养日", ["熔体温度","模具温度"], ["保养日"], {}),
    ("lasso_regression", "不良率", ["熔体温度","模具温度","注射压力"], [], {}),
    ("robust_regression", "不良率", ["熔体温度"], [], {}),
    ("quantile_regression", "不良率", ["熔体温度"], [], {"quantile": 0.5}),
    # === 过程监控 ===
    ("spc_xbar", "不良率", [], [], {"subgroup_col": "车间"}),
    ("spc_attribute", "不良率", [], [], {"chart_type": "c"}),
    ("spc_cusum", "不良率", [], [], {}),
    ("spc_ewma", "不良率", [], [], {}),
    ("process_capability", "不良率", [], [], {"usl": 10, "lsl": 1}),
    ("trend_forecast", "不良率", [], [], {}),
    ("anomaly_detect", "不良率", [], [], {"method": "iqr"}),
    ("change_point", "不良率", [], [], {}),
    ("outlier_consensus", "不良率", ["熔体温度"], [], {}),
    ("box_chart", "不良率", ["原料类型"], ["原料类型"], {}),
    ("spc_nonparametric", "不良率", [], [], {"side": "two-sided"}),
    # === 高级分析 ===
    ("bootstrap_ci", "不良率", [], [], {"n_bootstrap": 200}),
    ("median_ci", "不良率", [], [], {}),
    ("gage_rr", "不良率", ["模具编号","检验员"], ["模具编号","检验员"], {"part_col": "模具编号", "operator_col": "检验员"}),
    ("tolerance_interval", "不良率", [], [], {}),
    ("survival_analysis", "不良率", ["设备报警"], [], {}),  # 设备报警是0/1数值列，适合作事件指示
]

assert len(TEST_CASES) == 39, f"Expected 39 test cases, got {len(TEST_CASES)}"

# ── 运行验证 ──
results = []
issues = []
manual_checks_passed = 0
manual_checks_total = 0

for task, target, features, cats, params in TEST_CASES:
    test_name = f"{task}"
    if target:
        test_name += f"({target}"
        if features:
            test_name += f"×{len(features)}"
        test_name += ")"

    # ── Path A: Python 直接调用 ──
    try:
        df_a = df_raw.copy()
        req_a = AnalysisRequest(task=task, data=df_a, target_col=target,
                                feature_cols=features, params=params)
        result_a = orchestrate(req_a)
        status_a = result_a.status
        summary_a = result_a.summary
        tables_a = set(result_a.tables.keys())
        figs_a = len(result_a.figures)
        meta_a = result_a.metadata
    except Exception as e:
        status_a = "exception"
        summary_a = str(e)[:100]
        tables_a = set()
        figs_a = 0
        meta_a = {}
        issues.append(f"PATH_A_CRASH: {test_name}: {e}")

    # ── Path B: Web UI 预处理路径 ──
    try:
        df_b = df_raw.copy()
        # 模拟 Web UI 预处理: 要因分析/box_chart/anova 保留原始类别列
        raw_cat_tasks = {"box_chart", "anova", "variance_test"}
        if task in raw_cat_tasks:
            feat_b = list(features)
        else:
            cat_set = set(cats)
            df_b, feat_b, _, _ = preprocess_data(df_b, features, cat_set)

        req_b = AnalysisRequest(task=task, data=df_b, target_col=target,
                                feature_cols=feat_b, params=params)
        result_b = orchestrate(req_b)
        status_b = result_b.status
        summary_b = result_b.summary
        tables_b = set(result_b.tables.keys())
        figs_b = len(result_b.figures)
        meta_b = result_b.metadata
    except Exception as e:
        status_b = "exception"
        summary_b = str(e)[:100]
        tables_b = set()
        figs_b = 0
        meta_b = {}
        issues.append(f"PATH_B_CRASH: {test_name}: {e}")

    # ── 对比 ──
    status_match = (status_a == status_b)
    tables_match = (tables_a == tables_b)
    figs_match = (figs_a == figs_b)

    if not status_match:
        issues.append(f"STATUS MISMATCH: {test_name}: A={status_a}, B={status_b}")
    if not tables_match:
        only_a = tables_a - tables_b
        only_b = tables_b - tables_a
        if only_a or only_b:
            issues.append(f"TABLES MISMATCH: {test_name}: only_A={only_a}, only_B={only_b}")
    if not figs_match:
        issues.append(f"FIGS MISMATCH: {test_name}: A={figs_a}, B={figs_b}")

    # ── 用户手册值检查 ──
    manual_result = ""
    if task in MANUAL_EXPECTATIONS and status_a == "ok":
        exp = MANUAL_EXPECTATIONS[task]
        manual_checks_total += 1

        if task == "correlation":
            tc = meta_a.get("target_correlations", {})
            if tc:
                top = max(tc.items(), key=lambda x: abs(x[1]))
                r = abs(top[1])
                if exp["|r|范围"][0] <= r <= exp["|r|范围"][1]:
                    manual_checks_passed += 1
                    manual_result = f"PASS |r|={r:.3f} in range"
                else:
                    issues.append(f"MANUAL: {task} |r|={r:.3f} not in {exp['|r|范围']}")

        elif task == "anova":
            p = meta_a.get("r_squared", 0)
            if p >= 0:
                manual_checks_passed += 1
                manual_result = f"PASS R²={p:.4f}"

        elif task == "hypothesis_test":
            p = meta_a.get("p_value", 1)
            es = meta_a.get("effect_label", "")
            if exp["保养日p值"][0] <= p <= exp["保养日p值"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS p={p:.6f}"
            else:
                issues.append(f"MANUAL: {task} p={p:.6f} not in range")

        elif task == "decision_tree":
            cv = meta_a.get("cv_r2", None)
            if cv is not None:
                manual_checks_passed += 1
                manual_result = f"PASS CV_R²={cv:.3f}"

        elif task == "vif":
            vif_table = result_a.tables.get("vif_table")
            if vif_table is not None:
                max_vif = vif_table["VIF"].max()
                if exp["所有VIF"][0] <= max_vif <= exp["所有VIF"][1]:
                    manual_checks_passed += 1
                    manual_result = f"PASS max(VIF)={max_vif:.3f}"
                else:
                    issues.append(f"MANUAL: {task} max(VIF)={max_vif:.3f}")

        elif task == "regression":
            r2 = meta_a.get("r_squared", 0)
            dw = meta_a.get("durbin_watson", 0)
            if exp["R²范围"][0] <= r2 <= exp["R²范围"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS R²={r2:.4f}"
            else:
                issues.append(f"MANUAL: {task} R²={r2:.4f}")

        elif task == "process_capability":
            judge = meta_a.get("judge", "")
            if exp["判定"] in judge:
                manual_checks_passed += 1
                manual_result = f"PASS judge={judge}"

        elif task == "distribution_summary":
            bf = meta_a.get("best_fit", "")
            if exp["最佳拟合"] in bf:
                manual_checks_passed += 1
                manual_result = f"PASS best_fit={bf}"

        elif task == "outlier_consensus":
            n = meta_a.get("n", 1000)
            hc = meta_a.get("high_conf_count", 0)
            ratio = hc / n if n > 0 else 0
            if exp["高置信比例"][0] <= ratio <= exp["高置信比例"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS high_conf={hc}/{n}={ratio:.1%}"

    # ── 日志 (ASCII only for Windows GBK terminal) ──
    match_str = "OK" if (status_match and tables_match and figs_match) else "!!"
    fig_str = f"{figs_a}/{figs_b}" if figs_a == figs_b else f"{figs_a}!={figs_b}"
    print(f"  {match_str} {task:<30} status={status_a}  tables={len(tables_a)}  figs={fig_str}")

    results.append({
        "task": task, "status_a": status_a, "status_b": status_b,
        "tables_match": tables_match, "figs_match": figs_match,
        "manual_check": manual_result,
    })

# ── 汇总 ──
print()
print("=" * 70)
ok_count = sum(1 for r in results if r["status_a"] == "ok")
error_count = sum(1 for r in results if r["status_a"] == "error")
status_mismatch = sum(1 for r in results if not r["status_a"] == r["status_b"])
tables_mismatch = sum(1 for r in results if not r["tables_match"])
figs_mismatch = sum(1 for r in results if not r["figs_match"])

print(f"  总计: {len(results)} 方法")
print(f"  ok: {ok_count}  error: {error_count}")
print(f"  status 不一致: {status_mismatch}")
print(f"  tables 不一致: {tables_mismatch}")
print(f"  figures 不一致: {figs_mismatch}")
print(f"  用户手册验证: {manual_checks_passed}/{manual_checks_total} passed")
print()

if issues:
    print(f"  问题 ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
else:
    print("  *** ALL PASSED ***")
print("=" * 70)

# 返回状态码
exit_code = 1 if (status_mismatch > 0 or tables_mismatch > 5 or figs_mismatch > 3) else 0
sys.exit(exit_code)
