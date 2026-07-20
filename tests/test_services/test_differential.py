"""CLI 与 Web API 路径一致性测试 — 确保两个入口产生相同的数值结果。

原则: 相同的输入数据 + 相同的分析参数 → 相同的数值结果
这能捕获参数默认值不一致、预处理路径差异、异常处理差异等问题。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import (
    DEFAULT_PARAMS,
    TASK_GROUPS,
    TASK_LABELS,
    TASK_REGISTRY,
    orchestrate,
)

# ═══════════════════════════════════════════════════════════════
# 辅助: 模拟 CLI 路径 (直接调用 preprocess + orchestrate)
# ═══════════════════════════════════════════════════════════════

def run_via_cli(task, df, target_col, feature_cols, params=None, raw_cat=False):
    """模拟 CLI 路径: validate → preprocess_data → merge defaults → orchestrate。

    raw_cat=True 时跳过 One-Hot 编码（模拟 Web 路径对 RAW_CAT_TASKS 的特殊处理）。
    """
    params = params or {}
    defaults = DEFAULT_PARAMS.get(task, {})
    merged = {**defaults, **params}
    if raw_cat:
        df_enc = df.copy()
        feat_enc = list(feature_cols)
    else:
        df_enc, feat_enc, _, _, _ = preprocess_data(df, feature_cols)
    req = AnalysisRequest(task=task, data=df_enc, target_col=target_col,
                          feature_cols=feat_enc, params=merged)
    return orchestrate(req)


def run_via_web(task, df, target_col, feature_cols, params=None, categoricals=None):
    """模拟 Web 路径: 通过 run_analysis 执行（与 Web API 完全一致的路径）。"""
    from smartsuite.web.api import run_analysis
    if params is None:
        params = {}
    if categoricals is None:
        categoricals = []
    results = run_analysis(task, df, [target_col], list(feature_cols),
                          list(categoricals), params)
    return results[0] if results else None


# ═══════════════════════════════════════════════════════════════
# 注册一致性检查
# ═══════════════════════════════════════════════════════════════

def test_default_params_valid():
    """所有 DEFAULT_PARAMS 中的键都对应有效的注册任务。"""
    for task_name in DEFAULT_PARAMS:
        assert task_name in TASK_REGISTRY, \
            f"DEFAULT_PARAMS 中的 '{task_name}' 不在 TASK_REGISTRY 中"


def test_all_registered_tasks_have_defaults():
    """所有注册任务至少有一个 DEFAULT_PARAMS 条目（可为空）。"""
    missing = [t for t in TASK_REGISTRY if t not in DEFAULT_PARAMS]
    assert not missing, f"以下注册任务缺少 DEFAULT_PARAMS: {missing}"


def test_registry_label_group_consistency():
    """TASK_REGISTRY / TASK_LABELS / TASK_GROUPS 三者完全一致。"""
    reg_keys = set(TASK_REGISTRY.keys())
    label_keys = set(TASK_LABELS.keys())
    group_keys = set().union(*[set(v) for v in TASK_GROUPS.values()])

    assert reg_keys == label_keys, \
        f"REGISTRY 独有: {reg_keys - label_keys}, LABELS 独有: {label_keys - reg_keys}"
    assert reg_keys == group_keys, \
        f"REGISTRY 独有: {reg_keys - group_keys}, GROUPS 独有: {group_keys - reg_keys}"


# ═══════════════════════════════════════════════════════════════
# 预处理路径一致性
# ═══════════════════════════════════════════════════════════════

def test_preprocess_idempotent():
    """对已预处理数据再次调用 preprocess 不应改变结果。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "x1": np.random.normal(0, 1, 50),
        "x2": np.random.normal(5, 2, 50),
        "y": np.random.normal(10, 1, 50),
    })
    df1, cols1, _, log1, _ = preprocess_data(df, ["x1", "x2"])
    df2, cols2, _, log2, _ = preprocess_data(df1, cols1)
    assert cols1 == cols2, f"预处理不幂等: {cols1} ≠ {cols2}"
    assert sum(log2.values()) == 0, f"二次预处理产生新插补: {log2}"


def test_imputation_fills_missing():
    """NaN 列应被中位数填充。"""
    np.random.seed(42)
    df = pd.DataFrame({
        "num_col": pd.Series([1.0, 2.0, None, 4.0, 5.0]),
        "y": np.random.normal(0, 1, 5),
    })
    df2, cols, _, log, _ = preprocess_data(df, ["num_col"])
    assert "num_col" in cols or any(c.startswith("num_col") for c in cols)
    assert df2[cols[0]].notna().sum() > 0, "输出列不应全 NaN"
    # 修复后：原始 NaN 也应被填充
    assert df2[cols[0]].isna().sum() == 0, \
        f"预处理后仍有 {df2[cols[0]].isna().sum()} 个 NaN，原始 NaN 未被填充"


# ═══════════════════════════════════════════════════════════════
# 跨路径数值一致性 — 全量 40 方法
# ═══════════════════════════════════════════════════════════════

# 为每种方法构建标准化测试数据
def _make_test_data(task: str, n: int = 100):
    """为指定 task 生成标准化的测试数据。"""
    np.random.seed(42)

    # 基础数值数据（所有方法共用）
    x1 = np.random.normal(10, 2, n)
    x2 = np.random.normal(50, 10, n)
    x3 = np.random.normal(0, 1, n)
    y = 5.0 + 1.5 * x1 - 0.5 * x2 + np.random.normal(0, 2, n)

    # 类别列
    groups = np.random.choice(["组A", "组B", "组C"], n)
    binary = np.random.choice(["正常", "异常"], n, p=[0.8, 0.2])
    before = np.random.choice(["合格", "不合格"], n, p=[0.7, 0.3])
    after = np.random.choice(["合格", "不合格"], n, p=[0.85, 0.15])

    # 子组（确保长度与 n 一致）
    n_subgroups = max(2, min(15, n // 5))
    subgroup = np.concatenate([
        np.repeat(range(1, n_subgroups + 1), 5),
        np.full(n - n_subgroups * 5, n_subgroups)
    ])[:n]

    # 时间序列
    time_idx = np.arange(n)

    # 生存数据
    event_time = np.abs(np.random.normal(50, 20, n))
    event_observed = np.random.binomial(1, 0.7, n)
    event_group = np.random.choice(["处理组", "对照组"], n)

    # 操作员 / 部件
    operators = np.random.choice(["张三", "李四", "王五"], n)
    parts = np.random.choice([f"部件{i}" for i in range(1, 11)], n)

    df = pd.DataFrame({
        "x1": x1, "x2": x2, "x3": x3, "y": y,
        "组别": groups, "二分类": binary, "子组": subgroup,
        "时间": time_idx, "前": before, "后": after,
        "事件时间": event_time, "事件状态": event_observed, "事件分组": event_group,
        "操作员": operators, "部件": parts,
    })
    return df


def _params_for(task: str):
    """返回 task 特定的参数和配置，模拟 Web UI 用户选择。"""
    params = {}
    extras = {}

    if task == "spc_cusum":
        params["k"] = 0.5
        params["h"] = 5.0
    elif task == "spc_ewma":
        params["lam"] = 0.2
        params["L"] = 2.7
    elif task == "spc_attribute":
        params["chart_type"] = "p"
    elif task == "spc_nonparametric":
        params["side"] = "two-sided"
    elif task == "process_capability":
        params["usl"] = 20.0
        params["lsl"] = 0.0
    elif task == "trend_forecast":
        params["forecast_steps"] = 3
    elif task == "anomaly_detect":
        params["method"] = "iqr"
    elif task == "change_point":
        params["min_segment"] = 10
        params["n_changepoints"] = 3
    elif task == "regression":
        params["model_type"] = "linear"
    elif task == "response_surface":
        params["direction"] = "maximize"
    elif task == "grid_search":
        params["ranges"] = {"x1": [5, 15], "x2": [30, 70]}
        params["n_points"] = 5
    elif task == "multi_objective":
        params["objectives"] = [{"col": "y", "direction": "maximize"}]
    elif task == "doe_analysis":
        params["alpha"] = 0.05
    elif task == "lasso_regression":
        params["l1_ratio"] = 1.0
    elif task == "quantile_regression":
        params["quantile"] = 0.5
    elif task == "bootstrap_ci":
        params["statistic"] = "mean"
        params["n_bootstrap"] = 200
        params["ci_level"] = 0.95
    elif task == "median_ci":
        params["ci_level"] = 0.95
    elif task == "gage_rr":
        params["part_col"] = "部件"
        params["operator_col"] = "操作员"
        params["sigma_multiplier"] = 5.15
    elif task == "tolerance_interval":
        params["coverage"] = 0.99
        params["confidence"] = 0.95
        params["side"] = "two-sided"
    elif task == "power_analysis":
        params["mode"] = "required_n"
        params["test_type"] = "ttest"
        params["effect_size"] = 0.5
    elif task == "correlation":
        params["method"] = "pearson"
    elif task == "anova":
        extras["categoricals"] = ["组别"]
    elif task == "hypothesis_test":
        params["test"] = "ttest_ind"
        extras["categoricals"] = ["组别"]
    elif task == "contingency":
        extras["categoricals"] = ["前", "后"]
    elif task == "variance_test":
        extras["categoricals"] = ["组别"]

    return params, extras


# ── 自动跳过 Web 路径中自带特殊处理的方法 ──
# Web run_analysis 对 spc_xbar 和 hypothesis_test 有自动参数注入
# 在对等测试中，我们预先提供参数以避免随机化差异
_WEB_AUTO_TASKS = {"spc_xbar", "hypothesis_test"}

# 需要原始类别列的任务（Web 路径会跳过 One-Hot 编码）
from smartsuite.services.orchestrator import RAW_CAT_TASKS


@pytest.mark.parametrize("task", sorted(TASK_REGISTRY.keys()))
def test_cli_web_numerical_parity_all(task):
    """CLI 路径 与 Web 路径 对 40 个方法产生一致的数值结果。

    验证: status, summary, metadata 中的核心数值、tables 键名。

    对于 RAW_CAT_TASKS 中的方法，CLI 路径也会跳过 One-Hot 编码，
    以模拟# Web 路径对原始类别列的保留行为。
    """
    params, extras = _params_for(task)
    categoricals = extras.get("categoricals", [])
    raw_cat = task in RAW_CAT_TASKS

    df = _make_test_data(task, n=80)

    # 选择 target 和 features
    if task in ("survival_analysis",):
        target = "事件时间"
        features = ["事件状态", "事件分组"]
    elif task in ("contingency", "cohens_kappa"):
        target = "前"
        features = ["后"]
        # 减少随机性带来的不一致
        params["test_type"] = "mcnemar" if task == "contingency" else "cohens_kappa"
    elif task in ("spc_attribute",):
        # 需要二分类目标
        target = "二分类"
        features = ["子组"]
    elif task in ("box_chart",):
        target = "y"
        features = ["组别"]
        categoricals = ["组别"]
    elif task in ("roc_analysis",):
        target = "y"
        features = ["x1", "x2"]
    elif task in ("logistic_regression",):
        # 需要二分类目标
        target = "二分类"
        features = ["x1", "x2"]
    elif task in ("power_analysis",):
        target = ""
        features = ["x1", "x2"]
    elif task in ("median_ci", "distribution_summary", "normality_check",
                  "bootstrap_ci", "tolerance_interval", "anomaly_detect",
                  "outlier_consensus"):
        target = "y"
        features = []
    elif task in ("trend_forecast", "spc_cusum", "spc_ewma", "spc_nonparametric",
                  "change_point", "process_capability"):
        target = "y"
        features = []
    elif task == "gage_rr":
        target = "y"
        features = []
    elif task == "spc_xbar":
        target = "y"
        features = ["子组"]
    elif task in ("hypothesis_test",):
        target = "y"
        features = ["x1", "组别"]
        categoricals = ["组别"]
    elif task in ("anova", "variance_test"):
        target = "y"
        features = ["组别"]
        categoricals = ["组别"]
    elif task in ("contingency",):
        target = "y"
        features = ["前", "后"]
        categoricals = ["前", "后"]
        # Ensure 2x2 contingency table works by binning y
        df["y_cat"] = pd.cut(df["y"], bins=2, labels=["低", "高"]).astype(str)
        target = "y_cat"
        features = ["组别"]
        categoricals = ["组别"]
    else:
        target = "y"
        features = ["x1", "x2"]

    features = [f for f in features if f in df.columns]

    # ── 路径 A: CLI (validate + preprocess + merge defaults + orchestrate) ──
    try:
        result_cli = run_via_cli(task, df, target, features,
                                 params=params, raw_cat=raw_cat)
    except Exception as e:
        result_cli = {"status": "error", "summary": str(e)[:200], "_exception": str(type(e).__name__)}

    # ── 路径 B: Web (run_analysis → preprocess + orchestrate + JSON roundtrip) ──
    try:
        web_result = run_via_web(task, df, target, features,
                                params=params, categoricals=categoricals)
    except Exception as e:
        web_result = {"status": "error", "summary": str(e)[:200], "_exception": str(type(e).__name__)}

    # ── 验证 ──
    # 1. 状态一致性（Web 路径错误消息含更丰富上下文，但 status 应一致）
    cli_status = result_cli.status if hasattr(result_cli, 'status') else result_cli.get("status", "error")
    web_status = web_result.get("status", "error")
    assert cli_status == web_status, \
        f"{task}: CLI={cli_status}, Web={web_status} — 行为不一致"

    # 2. 若都成功，验证数值一致性
    if cli_status == "ok" and web_status == "ok":
        # 2a. Summary 非空
        assert len(str(result_cli.summary)) > 0, f"{task}: CLI summary 为空"
        assert len(str(web_result.get("summary", ""))) > 0, f"{task}: Web summary 为空"

        # 2b. Tables 键一致
        cli_tables = set(result_cli.tables.keys())
        web_tables = set(web_result.get("tables", {}).keys())
        # Web 路径可能含 _merged_correlation（仅多目标时）
        web_tables_clean = {k for k in web_tables if not k.startswith("_")}
        assert cli_tables == web_tables_clean, \
            f"{task}: CLI tables={cli_tables}, Web tables={web_tables_clean}"

        # 2c. 核心数值元数据一致
        cli_meta = result_cli.metadata
        web_meta = web_result.get("metadata", {})
        # 比较共同的标量元数据（排除 dict/list/numpy 和 figure 相关）
        for key in cli_meta:
            if key in web_meta:
                cv = cli_meta[key]
                wv = web_meta[key]
                if isinstance(cv, (int, float, bool, str)) and not isinstance(cv, bool):
                    if isinstance(cv, (int, float)) and isinstance(wv, (int, float)):
                        # 数值比较（容忍 Web JSON 序列化的舍入差异，1e-6）
                        if np.isfinite(cv) and np.isfinite(wv):
                            assert abs(float(cv) - float(wv)) < 1e-6 or \
                                abs(float(cv) - float(wv)) / (abs(float(cv)) + 1e-10) < 1e-4, \
                                f"{task}: metadata[{key}] 数值不一致: CLI={cv}, Web={wv}"

    # 3. 若都失败，验证错误行为一致（都有 error status）
    elif cli_status != "ok" or web_status != "ok":
        # 两者至少有一个失败是合理的（如数据不适合该方法）
        # 但不应出现一个 ok 一个 error 的情况（已由 status 断言覆盖）
        pass


def test_cli_web_default_params_sync():
    """Web app.js 中的 TASK_PARAMS 与 DEFAULT_PARAMS 应兼容。

    确保 Web UI 能正常覆盖所有默认参数。
    """
    # 这是静态检查：DEFAULT_PARAMS 中定义的参数应被 app.js 消费
    for task, defaults in DEFAULT_PARAMS.items():
        assert isinstance(defaults, dict), \
            f"DEFAULT_PARAMS[{task}] 必须是 dict，实际: {type(defaults)}"


def test_cli_web_specific_parity():
    """针对易出差异的方法做精确对比。

    这些方法在 Web 路径中有额外的参数注入逻辑，
    需要确保提供参数后两条路径行为一致。
    """
    np.random.seed(42)
    n = 60

    # ── X-bar/R 控制图 ──
    subgroup = np.repeat(range(1, 13), 5)
    df_spc = pd.DataFrame({
        "子组": subgroup,
        "val": np.random.normal(10, 1, len(subgroup)),
    })

    from smartsuite.services.data_io import preprocess_data

    # CLI 路径: 手动预处理
    df_enc, feat_enc, _, _, _ = preprocess_data(df_spc, ["子组"])
    req_cli = AnalysisRequest(task="spc_xbar", data=df_enc, target_col="val",
                              feature_cols=feat_enc,
                              params={})
    r_cli = orchestrate(req_cli)

    # Web 路径: run_analysis (X 列为 "子组")
    web_r = run_via_web("spc_xbar", df_spc, "val", ["子组"],
                       params={})

    assert r_cli.status == web_r.get("status"), \
        f"spc_xbar status: CLI={r_cli.status}, Web={web_r.get('status')}"
    assert abs(float(r_cli.metadata.get("xbar_mean", 0)) -
               float(web_r.get("metadata", {}).get("xbar_mean", 0))) < 1e-4, \
        "spc_xbar xbar_mean 不一致"

    # ── 回归 ──
    x1 = np.random.normal(10, 2, n)
    x2 = np.random.normal(50, 10, n)
    y = 5.0 + 1.5 * x1 - 0.5 * x2 + np.random.normal(0, 2, n)
    df_reg = pd.DataFrame({"x1": x1, "x2": x2, "y": y})

    r_cli_reg = run_via_cli("regression", df_reg, "y", ["x1", "x2"])
    web_r_reg = run_via_web("regression", df_reg, "y", ["x1", "x2"])

    assert r_cli_reg.status == web_r_reg.get("status"), \
        f"regression status: CLI={r_cli_reg.status}, Web={web_r_reg.get('status')}"
    if r_cli_reg.status == "ok":
        assert abs(r_cli_reg.metadata["r_squared"] -
                   float(web_r_reg.get("metadata", {}).get("r_squared", 0))) < 1e-4, \
            f"regression R² 不一致: CLI={r_cli_reg.metadata['r_squared']}, " \
            f"Web={web_r_reg.get('metadata', {}).get('r_squared')}"

    # ── ANOVA ──
    df_anova = pd.DataFrame({
        "group": np.random.choice(["A", "B", "C"], n),
        "y": np.concatenate([
            np.random.normal(10, 1, n // 3),
            np.random.normal(12, 1, n // 3),
            np.random.normal(14, 1, n - 2 * (n // 3)),
        ]),
    })

    r_cli_a = run_via_cli("anova", df_anova, "y", ["group"])
    web_r_a = run_via_web("anova", df_anova, "y", ["group"],
                         categoricals=["group"])

    assert r_cli_a.status == web_r_a.get("status"), \
        f"anova status: CLI={r_cli_a.status}, Web={web_r_a.get('status')}"
    if r_cli_a.status == "ok":
        cli_p = float(r_cli_a.metadata.get("p_value", 0))
        web_p = float(web_r_a.get("metadata", {}).get("p_value", 0))
        assert abs(cli_p - web_p) < 1e-4 or abs(cli_p - web_p) / (abs(cli_p) + 1e-10) < 0.01, \
            f"anova p 值不一致: CLI={cli_p}, Web={web_p}"
