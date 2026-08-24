"""End-to-end test of all 40 analysis tasks via Web API.

Requires a running server: `python src/smartsuite/web/app.py`
When the server is not running, the module is skipped at collection time.
Run manually: pytest tests/test_web_e2e.py -v
"""

import http.cookiejar
import json
import urllib.error
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

# ── All 40 tasks: (task, targets, features, categoricals, params) ──
ALL_TASKS = [
    ("correlation", ["不良率"], ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("anova", ["不良率"], ["原料类型"], ["原料类型"], {}),
    ("hypothesis_test", ["不良率"], ["保养日"], ["保养日"], {}),
    ("decision_tree", ["不良率"], ["熔体温度", "模具温度"], [], {}),
    ("vif", [""], ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("regression", ["不良率"], ["熔体温度", "注射压力"], [], {}),
    ("response_surface", ["不良率"], ["熔体温度", "模具温度"], [], {}),
    ("doe_analysis", ["不良率"], ["熔体温度", "模具温度"], [], {}),
    ("roc_analysis", ["首件合格"], ["熔体温度"], [], {}),
    ("logistic_regression", ["保养日"], ["熔体温度"], [], {}),
    ("lasso_regression", ["不良率"], ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("robust_regression", ["不良率"], ["熔体温度"], [], {}),
    ("quantile_regression", ["不良率"], ["熔体温度"], [], {}),
    ("spc_xbar", ["不良率"], ["车间"], [], {}),
    # 审查 2026-08-19 #2.8：p 图要求 0/1 比例数据，改用二值列「首件合格」
    # （不良率为百分比 0-100 列，引擎已明确拒绝并提示）
    ("spc_attribute", ["首件合格"], [], [], {"chart_type": "p"}),
    ("spc_cusum", ["不良率"], [], [], {}),
    ("spc_ewma", ["不良率"], [], [], {}),
    ("process_capability", ["不良率"], [], [], {"usl": 10, "lsl": 1}),
    ("trend_forecast", ["不良率"], [], [], {}),
    ("anomaly_detect", ["不良率"], [], [], {}),
    ("change_point", ["不良率"], [], [], {}),
    ("outlier_consensus", ["不良率"], ["熔体温度"], [], {}),
    ("bootstrap_ci", ["不良率"], [], [], {}),
    ("median_ci", ["不良率"], [], [], {}),
    ("contingency", ["原料类型"], ["保养日"], ["原料类型", "保养日"], {}),
    ("proportion_ci", ["首件合格"], [], [], {}),
    ("variance_test", ["不良率"], ["原料类型"], ["原料类型"], {}),
    ("cohens_kappa", [""], ["首件合格", "外观检查"], [], {}),
    ("cronbach_alpha", [""], ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("distribution_summary", ["不良率"], [], [], {}),
    ("normality_check", ["不良率"], ["熔体温度"], [], {}),
    (
        "power_analysis",
        [""],
        [],
        [],
        {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5},
    ),
    ("survival_analysis", ["不良率"], ["保养日"], [], {}),
    (
        "gage_rr",
        ["不良率"],
        ["模具编号", "检验员"],
        [],
        {"part_col": "模具编号", "operator_col": "检验员"},
    ),
    ("tolerance_interval", ["不良率"], [], [], {}),
    (
        "grid_search",
        ["不良率"],
        ["熔体温度"],
        [],
        {"ranges": {"熔体温度": [180, 220]}, "n_points": 5},
    ),
    (
        "multi_objective",
        ["不良率"],
        ["熔体温度", "模具温度"],
        [],
        {
            "objectives": [
                {"col": "不良率", "direction": "minimize"},
                {"col": "拉伸强度", "direction": "maximize"},
            ]
        },
    ),
    ("spc_nonparametric", ["不良率"], [], [], {}),
    ("box_chart", ["不良率"], ["原料类型"], ["原料类型"], {}),
    ("scatter_plot", ["不良率"], ["熔体温度"], [], {"fit": "linear"}),
]

assert len({t for t, *_ in ALL_TASKS}) == 40, "E2E must cover all 40 tasks"


@pytest.fixture(scope="module")
def web_session():
    """带 cookie 的会话：获取 CSRF token 并上传测试数据。"""
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    csrf_resp = opener.open(urllib.request.Request(f"{BASE}/api/csrf-token"))
    csrf_token = json.loads(csrf_resp.read())["token"]

    with open("tests/test_data.xlsx", "rb") as f:
        data = f.read()
    boundary = uuid.uuid4().hex
    body = (
        b"--" + boundary.encode() + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="t.xlsx"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        + data
        + b"\r\n--"
        + boundary.encode()
        + b"--\r\n"
    )
    req = urllib.request.Request(
        f"{BASE}/api/upload",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}", "X-CSRF-Token": csrf_token},
    )
    resp = json.loads(opener.open(req).read())
    assert resp.get("columns"), f"上传失败: {resp}"

    return opener, csrf_token


@pytest.mark.parametrize(
    "task,targets,features,cats,params", ALL_TASKS, ids=[t for t, *_ in ALL_TASKS]
)
def test_task_via_web_api(web_session, task, targets, features, cats, params):
    opener, csrf_token = web_session
    body = json.dumps(
        {
            "task": task,
            "targets": targets,
            "features": features,
            "categoricals": cats,
            "params": params,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/analyze",
        body,
        {"Content-Type": "application/json; charset=utf-8", "X-CSRF-Token": csrf_token},
    )
    resp = opener.open(req, timeout=120)
    d = json.loads(resp.read())
    res = d["results"][0]
    assert res["status"] == "ok", f"{task} status={res['status']}: {res.get('messages')}"
    assert res.get("summary"), f"{task} summary 为空"
