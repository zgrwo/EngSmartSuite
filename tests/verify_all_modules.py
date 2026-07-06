"""逐一复核全部38个模块: Web UI路径 vs 直接Python路径"""
import io
import json
import sys
import urllib.request
import uuid

import pandas as pd

# 解决终端编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

df_raw = pd.read_excel("tests/test_data.xlsx")
BASE = "http://127.0.0.1:5050"

# 上传数据到Web服务器
print("=" * 70)
print("Step 0: Upload data to Web server")
with open("tests/test_data.xlsx", "rb") as f:
    data = f.read()
B = uuid.uuid4().hex
body = (b'--' + B.encode() + b'\r\n'
        b'Content-Disposition: form-data; name="file"; filename="t.xlsx"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n'
        + data + b'\r\n--' + B.encode() + b'--\r\n')
req = urllib.request.Request(f"{BASE}/api/upload", body,
    {"Content-Type": f"multipart/form-data; boundary={B}"})
r = urllib.request.urlopen(req)
d = json.loads(r.read())
print(f"  Upload: {d['shape'][0]}rows x {d['shape'][1]}cols OK\n")

# ========== 定义所有测试用例 ==========
# (name, task_key, targets, features, categoricals, params, verify_fn)
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data

TESTS = []
results_web = {}
results_py = {}

def add_test(name, task_key, targets, features, cats, params, verifier=None):
    TESTS.append((name, task_key, targets, features, cats, params, verifier))

# ---- 要因筛选 ----
add_test("correlation", "correlation",
    ["不良率"], ["熔体温度","模具温度","注射压力","冷却时间"], [], {})

add_test("anova", "anova",
    ["不良率"], ["原料类型"], ["原料类型"], {})

add_test("hypothesis_test", "hypothesis_test",
    ["不良率"], ["保养日"], ["保养日"], {"test": "ttest_ind", "group_col": "保养日"})

add_test("decision_tree", "decision_tree",
    ["不良率"], ["熔体温度","模具温度","注射压力","冷却时间"], [], {"max_depth": 3})

add_test("vif", "vif",
    [""], ["熔体温度","模具温度","注射压力","冷却时间"], [], {})

add_test("contingency", "contingency",
    ["原料类型"], ["保养日"], ["原料类型","保养日"], {})

add_test("proportion_ci", "proportion_ci",
    ["首件合格"], [], [], {})

add_test("variance_test", "variance_test",
    ["不良率"], ["原料类型"], ["原料类型"], {"group_col": "原料类型"})

add_test("cohens_kappa", "cohens_kappa",
    [""], ["首件合格","外观检查"], [], {})

add_test("cronbach_alpha", "cronbach_alpha",
    [""], ["熔体温度","模具温度","注射压力"], [], {})

add_test("distribution_summary", "distribution_summary",
    ["不良率"], [], [], {})

add_test("normality_check", "normality_check",
    ["不良率"], ["熔体温度"], [], {})

add_test("power_analysis", "power_analysis",
    [""], [], [], {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5})

# ---- DOE/优化 ----
add_test("regression", "regression",
    ["不良率"], ["熔体温度","注射压力","冷却时间"], [], {})

add_test("response_surface", "response_surface",
    ["不良率"], ["熔体温度","模具温度"], [], {})

add_test("doe_analysis", "doe_analysis",
    ["不良率"], ["熔体温度","模具温度","注射压力"], [], {})

add_test("roc_analysis", "roc_analysis",
    ["首件合格"], ["熔体温度"], [], {})

add_test("logistic_regression", "logistic_regression",
    ["保养日"], ["熔体温度"], ["保养日"], {})

add_test("lasso_regression", "lasso_regression",
    ["不良率"], ["熔体温度","模具温度","注射压力"], [], {})

add_test("robust_regression", "robust_regression",
    ["不良率"], ["熔体温度"], [], {})

add_test("quantile_regression", "quantile_regression",
    ["不良率"], ["熔体温度"], [], {"quantile": 0.5})

add_test("grid_search", "grid_search",
    ["不良率"], ["熔体温度"], [], {"ranges": {"熔体温度": [180, 220]}, "n_points": 5, "direction": "minimize"})

add_test("multi_objective", "multi_objective",
    ["不良率"], ["熔体温度","模具温度"], [],
    {"objectives": [{"col": "不良率", "direction": "minimize"}, {"col": "拉伸强度", "direction": "maximize"}]})

# ---- 过程监控 ----
add_test("spc_xbar", "spc_xbar",
    ["不良率"], ["车间"], ["车间"], {"subgroup_col": "车间"})

add_test("spc_attribute", "spc_attribute",
    ["不良率"], [], [], {"chart_type": "c"})

add_test("spc_cusum", "spc_cusum",
    ["不良率"], [], [], {})

add_test("spc_ewma", "spc_ewma",
    ["不良率"], [], [], {})

add_test("process_capability", "process_capability",
    ["不良率"], [], [], {"usl": 10, "lsl": 1})

add_test("trend_forecast", "trend_forecast",
    ["不良率"], [], [], {})

add_test("anomaly_detect", "anomaly_detect",
    ["不良率"], [], [], {"method": "iqr"})

add_test("change_point", "change_point",
    ["不良率"], [], [], {})

add_test("outlier_consensus", "outlier_consensus",
    ["不良率"], ["熔体温度"], [], {})

# ---- 高级分析 ----
add_test("bootstrap_ci", "bootstrap_ci",
    ["不良率"], [], [], {"statistic": "mean", "n_bootstrap": 200})

add_test("median_ci", "median_ci",
    ["不良率"], [], [], {})

add_test("gage_rr", "gage_rr",
    ["不良率"], ["模具编号","检验员"], [],
    {"part_col": "模具编号", "operator_col": "检验员"})

add_test("tolerance_interval", "tolerance_interval",
    ["不良率"], [], [], {})

add_test("survival_analysis", "survival_analysis",
    ["不良率"], ["保养日"], [], {})

# ---- 箱线图 ----
add_test("box_chart", "box_chart",
    ["不良率"], ["原料类型"], ["原料类型"], {})

add_test("box_chart_sub", "box_chart",
    ["不良率"], ["原料类型","车间"], ["原料类型","车间"], {})

# ========== 逐项测试 ==========
print("=" * 70)
print(f"{'Module':28s} {'Web UI':>8s} {'Python':>8s} {'Match':>6s}  Key Values")
print("-" * 70)

total, match, web_err, py_err = 0, 0, 0, 0

for name, task_key, targets, features, cats, params, verifier in TESTS:
    total += 1

    # --- Web UI 路径 ---
    w_status, w_summary, w_meta = "?", "", {}
    try:
        body_json = json.dumps({"task": task_key, "targets": targets,
            "features": features, "categoricals": cats, "params": params},
            ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(f"{BASE}/api/analyze", body_json,
            {"Content-Type": "application/json; charset=utf-8"})
        r = urllib.request.urlopen(req)
        d = json.loads(r.read())
        res = d["results"][0]
        w_status = res["status"]
        w_summary = res.get("summary", "")
        w_meta = res.get("metadata", {})
    except Exception as e:
        w_status = f"ERR:{str(e)[:30]}"
        web_err += 1

    # --- 直接 Python 路径 ---
    p_status, p_summary, p_meta = "?", "", {}
    try:
        from smartsuite.services.orchestrator import orchestrate
        # 模拟Web UI预处理: box_chart跳过one-hot编码
        if task_key == "box_chart":
            df_enc = df_raw.copy()
            feat_enc = list(features)
        else:
            cat_set = set(cats) if cats else set()
            df_enc, feat_enc, _, _, _ = preprocess_data(df_raw, features, cat_set)
        # 处理 target
        target = targets[0] if targets else ""
        req_py = AnalysisRequest(task=task_key, data=df_enc,
            target_col=target, feature_cols=feat_enc, params=params)
        r_py = orchestrate(req_py)
        p_status = r_py.status
        p_summary = r_py.summary
        p_meta = r_py.metadata
    except Exception as e:
        p_status = f"ERR:{str(e)[:30]}"
        py_err += 1

    # --- 比较 ---
    status_match = (w_status == p_status)
    if status_match:
        match += 1
    marker = "OK" if status_match else "DIFF"

    # 提取关键值
    key_info = ""
    if "correlation" in name and "box" not in name:
        key_info = w_summary[:60]
    elif name == "anova":
        key_info = f"R2={p_meta.get('r_squared','?'):.4f}"
    elif name == "hypothesis_test":
        key_info = f"p={p_meta.get('p_value','?'):.4f} d={p_meta.get('effect_size','?'):.3f}"
    elif name == "process_capability":
        key_info = f"Cpk={p_meta.get('cpk','?'):.3f}"
    elif name == "vif":
        key_info = f"high={p_meta.get('high_vif_count','?')}"
    elif name == "regression":
        key_info = f"R2={p_meta.get('r_squared','?'):.4f} DW={p_meta.get('durbin_watson','?'):.3f}"
    elif name == "proportion_ci":
        key_info = f"p_hat={p_meta.get('p_hat','?'):.1%}"
    elif name == "kappa":
        key_info = f"kappa={p_meta.get('kappa','?'):.3f}"
    elif name == "distribution_summary":
        key_info = f"best={p_meta.get('best_fit','?')}"
    elif name == "normality_check":
        key_info = f"normal={p_meta.get('normal_count',0)}/{p_meta.get('n_columns',0)}"
    elif name == "bootstrap_ci":
        key_info = f"mean={p_meta.get('point_estimate',0):.3f} CI=[{p_meta.get('ci_lower',0):.3f},{p_meta.get('ci_upper',0):.3f}]"
    elif name == "box_chart":
        key_info = f"groups={p_meta.get('n_groups','?')}"
    elif name == "box_chart_sub":
        key_info = f"groups={p_meta.get('n_groups','?')} has_sub={p_meta.get('has_sub','?')}"
    elif name == "trend_forecast":
        key_info = f"R2={p_meta.get('r_squared','?'):.4f}"
    elif name == "cusum":
        key_info = f"alarms={p_meta.get('total_alarms','?')}"
    elif name == "outlier_consensus":
        key_info = f"high={p_meta.get('high_confidence_count','?')}"
    elif name == "survival_analysis":
        key_info = f"median={p_meta.get('median_survival','?')}"
    elif name == "response_surface":
        key_info = f"R2={p_meta.get('r_squared','?'):.3f}"
    elif name == "gage_rr":
        key_info = f"ndc={p_meta.get('ndc','?')} grr_sv={p_meta.get('grr_sv','?'):.1f}%"
    elif name == "lasso_regression":
        key_info = f"selected={p_meta.get('n_selected','?')}/{p_meta.get('n_features','?')}"
    elif name == "decision_tree":
        key_info = f"top={p_meta.get('top_factor','?')}"
    elif name == "power_analysis":
        key_info = f"n={p_meta.get('required_n','?')}"
    elif name == "roc_analysis":
        key_info = f"AUC={p_meta.get('auc','?'):.3f}"
    elif name == "logistic_regression":
        key_info = f"acc={p_meta.get('accuracy','?'):.3f}"

    print(f"  {name:26s} {w_status:>8s} {p_status:>8s} {marker:>6s}  {key_info}")

print("-" * 70)
print(f"  TOTAL: {total}  Match: {match}  WebUI err: {web_err}  Python err: {py_err}")
print(f"  Status: {'ALL OK' if match == total else f'{total-match} MISMATCH'}")

# ========== 详细差异报告 ==========
if match < total:
    print(f"\n{'='*70}")
    print("DETAILED MISMATCH REPORT:")
    for name, task_key, targets, features, cats, params, verifier in TESTS:
        w_s = results_web.get(name, {}).get("status", "?")
        p_s = results_py.get(name, {}).get("status", "?")
        if w_s != p_s:
            print(f"  {name}: Web={w_s} Python={p_s}")
