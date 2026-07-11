"""End-to-end test of all 39 analysis tasks via Web API.

Requires a running server: `python smartsuite/web/app.py`
Run manually: pytest tests/test_web_e2e.py -v
"""
import http.cookiejar
import json
import time
import urllib.request
import uuid

import pytest

BASE = "http://127.0.0.1:5050"

# ── Check server availability ──
try:
    _check = urllib.request.urlopen(f"{BASE}/api/csrf-token", timeout=2)
    _check.close()
except Exception:
    pytest.skip("Server not running on port 5050 — skip E2E test", allow_module_level=True)

# ── Session with cookie jar (required for CSRF) ──
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

# ── Get CSRF token ──
print("=== CSRF Token ===")
csrf_req = urllib.request.Request(f"{BASE}/api/csrf-token")
csrf_resp = opener.open(csrf_req)
csrf_token = json.loads(csrf_resp.read())["token"]
print(f"  Got token: {csrf_token[:16]}...")

# ── Upload ──
print("=== Upload ===")
with open("tests/test_data.xlsx", "rb") as f:
    data = f.read()
B = uuid.uuid4().hex
body = (b'--' + B.encode() + b'\r\n'
        b'Content-Disposition: form-data; name="file"; filename="t.xlsx"\r\n'
        b'Content-Type: application/octet-stream\r\n\r\n'
        + data +
        b'\r\n--' + B.encode() + b'--\r\n')
req = urllib.request.Request(f"{BASE}/api/upload", body,
    {"Content-Type": f"multipart/form-data; boundary={B}",
     "X-CSRF-Token": csrf_token})
r = opener.open(req)
d = json.loads(r.read())
print(f"  OK: {len(d['columns'])} cols, {d['shape']}")

# ── Test all 39 tasks ──
ALL_TASKS = [
    ("correlation", ["不良率"], ["熔体温度","模具温度","注射压力"], []),
    ("anova", ["不良率"], ["原料类型"], ["原料类型"]),
    ("hypothesis_test", ["不良率"], ["原料类型"], ["原料类型"]),
    ("decision_tree", ["不良率"], ["熔体温度","模具温度"], []),
    ("vif", [""], ["熔体温度","模具温度","注射压力"], []),
    ("regression", ["不良率"], ["熔体温度","注射压力"], []),
    ("response_surface", ["不良率"], ["熔体温度","模具温度"], []),
    ("doe_analysis", ["不良率"], ["熔体温度","模具温度"], []),
    ("roc_analysis", ["首件合格"], ["熔体温度"], []),
    ("logistic_regression", ["保养日"], ["熔体温度"], []),
    ("lasso_regression", ["不良率"], ["熔体温度","模具温度","注射压力"], []),
    ("robust_regression", ["不良率"], ["熔体温度"], []),
    ("quantile_regression", ["不良率"], ["熔体温度"], []),
    ("spc_xbar", ["不良率"], [], []),
    ("spc_attribute", ["不良率"], [], []),
    ("spc_cusum", ["不良率"], [], []),
    ("spc_ewma", ["不良率"], [], []),
    ("process_capability", ["不良率"], [], []),
    ("trend_forecast", ["不良率"], [], []),
    ("anomaly_detect", ["不良率"], [], []),
    ("change_point", ["不良率"], [], []),
    ("outlier_consensus", ["不良率"], ["熔体温度"], []),
    ("bootstrap_ci", ["不良率"], [], []),
    ("median_ci", ["不良率"], [], []),
    ("contingency", ["原料类型"], ["保养日"], ["原料类型","保养日"]),
    ("proportion_ci", ["首件合格"], [], []),
    ("variance_test", ["不良率"], ["原料类型"], ["原料类型"]),
    ("cohens_kappa", [""], ["首件合格","外观检查"], []),
    ("cronbach_alpha", [""], ["熔体温度","模具温度","注射压力"], []),
    ("distribution_summary", ["不良率"], [], []),
    ("normality_check", ["不良率"], ["熔体温度"], []),
    ("power_analysis", [""], [], []),
    ("survival_analysis", ["不良率"], ["保养日"], []),
    ("gage_rr", ["不良率"], ["模具编号","检验员"], []),
    ("tolerance_interval", ["不良率"], [], []),
    ("grid_search", ["不良率"], ["熔体温度"], []),
    ("multi_objective", ["不良率"], ["熔体温度","模具温度"], []),
    ("spc_nonparametric", ["不良率"], [], []),
    ("box_chart", ["不良率"], ["原料类型"], ["原料类型"]),
]

ok, fail, total = 0, 0, 0
for task, targets, features, cats in ALL_TASKS:
    total += 1
    params = {}
    if task == "spc_xbar": features = ["车间"]
    if task == "spc_attribute": params = {"chart_type": "p"}
    if task == "power_analysis": params = {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5}
    if task == "grid_search": params = {"ranges": {"熔体温度": [180, 220]}, "n_points": 5}
    if task == "multi_objective":
        params = {"objectives": [{"col": "不良率", "direction": "minimize"}, {"col": "拉伸强度", "direction": "maximize"}]}
    if task == "process_capability": params = {"usl": 10, "lsl": 1}
    if task == "gage_rr": params = {"part_col": "模具编号", "operator_col": "检验员"}

    t0 = time.time()
    body2 = json.dumps({"task": task, "targets": targets, "features": features,
                        "categoricals": cats, "params": params},
                       ensure_ascii=False).encode("utf-8")
    req2 = urllib.request.Request(f"{BASE}/api/analyze", body2,
        {"Content-Type": "application/json; charset=utf-8",
         "X-CSRF-Token": csrf_token})
    try:
        r2 = opener.open(req2)
        d2 = json.loads(r2.read())
        res = d2["results"][0]
        elapsed = time.time() - t0
        status = res["status"]
        summary = res.get("summary", "")[:60]
        n_tables = len(res.get("tables", {}))
        n_charts = len(res.get("charts", []))
        msgs = res.get("messages", [])
        msg = msgs[0][:50] if msgs else ""
        print(f"  {'OK' if status=='ok' else '--':2s} {task:25s} {elapsed:5.1f}s  "
              f"tables={n_tables} charts={n_charts}  {status}")
        ok += 1
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        err = e.read().decode("utf-8", errors="replace")[:150]
        print(f"  XX {task:25s} {elapsed:5.1f}s  HTTP{e.code}: {err}")
        fail += 1
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  !! {task:25s} {elapsed:5.1f}s  EXCEPTION: {e}")
        fail += 1

print(f"\n{'='*50}")
print(f"Results: {ok}/{total} responded, {fail} failed")
print("All tasks reachable via Web API!" if fail == 0 else f"{fail} tasks have issues")
