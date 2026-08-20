"""CLI (orchestrate) vs Web (run_analysis) numerical parity — all 40 methods.

由原 tests/_diff_cli_web.py 模块级脚本改造（审查 2026-08-19 #3.3）：
- 原文件名不匹配 pytest python_files=["test_*.py"] 收集规则，且无 test_* 函数，
  40 方法 CLI/Web 差分从未执行，属死代码
- 现为参数化 pytest 测试：40 个任务逐一对比 status/summary/tables/metadata
- 顺带修复原脚本两处参数格式 bug：
  grid_search 的 ranges 传字符串（引擎需 dict）、multi_objective 的 objectives 传字符串
"""
import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import (
    infer_group_col,
    preprocess_for_task,
)
from smartsuite.services.orchestrator import (
    NO_TARGET_TASKS,
    RAW_CAT_TASKS,
    TASK_REGISTRY,
    orchestrate,
)
from smartsuite.web.api import run_analysis


@pytest.fixture(scope="module")
def parity_df():
    path = "tests/test_data.xlsx"
    if not pd.io.common.file_exists(path):
        pytest.skip("缺少 tests/test_data.xlsx，跳过 CLI/Web 差分测试")
    return pd.read_excel(path)


def _infer_index(values):
    """Convert string-serialised index/column values back to original types."""
    out = []
    for v in values:
        try:
            fv = float(v)
            if fv == int(fv):
                out.append(int(fv))
            else:
                out.append(fv)
        except (ValueError, TypeError):
            out.append(v)
    if not out:
        return pd.Index(values)
    if all(isinstance(x, int) for x in out):
        return pd.Index(out, dtype="int64")
    if all(isinstance(x, (int, float)) for x in out):
        return pd.Index(out, dtype="float64")
    return pd.Index(values)


def df_from_serialized(table_dict):
    """Reconstruct a DataFrame from run_analysis's serialised table format."""
    return pd.DataFrame(
        data=table_dict["data"],
        index=_infer_index(table_dict["index"]),
        columns=_infer_index(table_dict["columns"]),
    )


def _normalize_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DataFrame for comparison: normalize NaN/empty, convert types, round."""
    df = df.copy()
    for col in df.columns:
        col_dtype = df[col].dtype
        is_stringy = (
            col_dtype == object
            or "str" in str(col_dtype).lower()
            or "string" in str(col_dtype).lower()
        )
        if is_stringy:
            empty_set = {"", "nan", "NaN", "None", "null", "NA"}
            df[col] = df[col].replace(empty_set, np.nan)
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_datetime64_any_dtype(
            df[col]
        ):
            df[col] = df[col].apply(
                lambda x: round(float(x), 4) if pd.notna(x) and np.isfinite(float(x)) else x
            )
    return df


def tables_equal(t_a, t_b):
    """Compare two table dicts {name: DataFrame}.  Returns (ok, detail)."""
    if set(t_a.keys()) != set(t_b.keys()):
        return False, f"key sets differ: A={set(t_a.keys())} B={set(t_b.keys())}"
    for k in t_a:
        ta_norm = _normalize_nan(t_a[k])
        tb_norm = _normalize_nan(t_b[k])
        try:
            pd.testing.assert_frame_equal(
                ta_norm,
                tb_norm,
                check_index_type=False,
                check_column_type=False,
                check_dtype=False,
                atol=1e-4,
                rtol=1e-3,
            )
        except AssertionError as exc:
            return False, f"table '{k}': {str(exc)[:150]}"
    return True, ""



def _meta_scalars_equal(meta_a, meta_b, rtol=1e-3, atol=1e-6):
    """比较两路径 metadata 中共有的标量数值键（Round-2 批次D #1）。

    复用 tests/test_services/test_differential.py 的浮点比较思路：
    仅键集合一致仍可能数值漂移（如 Web JSON 序列化精度），对 float 值做
    rtol/atol 双容差比较；nan 视为相等（两侧皆 nan 时跳过）。
    返回 (ok, detail)。
    """
    for key in meta_a:
        if key not in meta_b:
            continue
        av, bv = meta_a[key], meta_b[key]
        is_num = (
            lambda v: isinstance(v, (int, float, np.integer, np.floating))
            and not isinstance(v, bool)
        )
        if not (is_num(av) and is_num(bv)):
            continue
        af, bf = float(av), float(bv)
        if np.isnan(af) and np.isnan(bf):
            continue  # nan 视为相等
        if not (np.isfinite(af) and np.isfinite(bf)):
            continue
        if abs(af - bf) > atol + rtol * abs(bf):
            return False, f"metadata[{key}]: CLI={af!r}, Web={bf!r}"
    return True, ""

def _compare_one(df, task, target_col_str, features, categoricals, params):
    targets_for_b = [target_col_str] if target_col_str else []

    # ---- Path A: 复刻 run_analysis 预处理后直接 orchestrate ----
    try:
        feat_a = list(features)
        params_a = dict(params)
        df_enc, feat_enc, _, _ = preprocess_for_task(
            df, feat_a, task, categoricals, RAW_CAT_TASKS,
        )
        if task == "hypothesis_test" and "group_col" not in params_a:
            extra = infer_group_col(df, feat_a, categoricals)
            if extra:
                extra_col = extra["group_col"]
                if extra_col not in feat_enc:
                    feat_enc = list(feat_enc) + [extra_col]
                params_a = {**params_a, **extra}
        req_a = AnalysisRequest(
            task=task, data=df_enc, target_col=target_col_str,
            feature_cols=feat_enc, params=params_a,
        )
        r_a = orchestrate(req_a)
    except Exception as e:
        return False, f"PATH_A exception: {str(e)[:120]}"

    # ---- Path B: run_analysis ----
    b_targets = list(targets_for_b)
    if not b_targets and task not in NO_TARGET_TASKS:
        b_targets = [target_col_str] if target_col_str else [""]
    try:
        r_b_list = run_analysis(task, df, targets=b_targets,
                                features=list(features),
                                categoricals=list(categoricals) if categoricals else [],
                                params=dict(params))
        if not r_b_list:
            return False, "PATH_B returned empty list"
        r_b_dict = r_b_list[0]
    except Exception as e:
        return False, f"PATH_B exception: {str(e)[:120]}"

    # ---- 比较 ----
    status_ok = r_a.status == r_b_dict["status"]
    # Round-2 批次D #1：summary 全字符串对比（此前截断前 50 字符，
    # 尾部结论差异（如显著性判定）会被漏检）
    summary_ok = (r_a.summary or "") == (r_b_dict.get("summary") or "")
    meta_keys_ok = set(r_a.metadata.keys()) == set(r_b_dict.get("metadata", {}).keys())
    meta_vals_ok, meta_detail = _meta_scalars_equal(
        r_a.metadata, r_b_dict.get("metadata", {})
    )
    try:
        t_b = {
            k: df_from_serialized(v)
            for k, v in r_b_dict.get("tables", {}).items()
            if not k.startswith("_merged")
        }
    except Exception as exc:
        return False, f"TABLE_RECONSTRUCT: {str(exc)[:120]}"
    table_ok, table_detail = tables_equal(r_a.tables, t_b)

    if not (status_ok and summary_ok and table_ok and meta_keys_ok and meta_vals_ok):
        detail = (
            f"status_ok={status_ok} summary_ok={summary_ok} "
            f"table_ok={table_ok} meta_keys_ok={meta_keys_ok} meta_vals_ok={meta_vals_ok}"
        )
        if not table_ok:
            detail += f"\n    table_detail: {table_detail}"
        if not meta_vals_ok:
            detail += f"\n    meta_detail: {meta_detail}"
        return False, detail
    return True, ""


Y = "不良率"
X = ["熔体温度", "模具温度", "注射压力", "冷却时间"]
CAT = "原料类型"

PARITY_CASES = [
    # Category 1 — 数值特征回归族
    ("correlation", Y, X, [], {}),
    ("regression", Y, X, [], {}),
    ("decision_tree", Y, X, [], {}),
    ("lasso_regression", Y, X, [], {}),
    ("robust_regression", Y, X, [], {}),
    ("quantile_regression", Y, X, [], {}),
    # Category 2 — 类别特征
    ("anova", Y, [], [CAT], {}),
    ("hypothesis_test", Y, [], [CAT], {}),
    ("variance_test", Y, [], [CAT], {}),
    # Category 3 — Y-only
    ("process_capability", Y, [], [], {"usl": 10, "lsl": 1}),
    ("trend_forecast", Y, [], [], {}),
    ("anomaly_detect", Y, [], [], {}),
    ("distribution_summary", Y, [], [], {}),
    ("normality_check", Y, [], [], {}),
    ("proportion_ci", Y, [], [], {}),
    ("bootstrap_ci", Y, [], [], {}),
    ("median_ci", Y, [], [], {}),
    ("tolerance_interval", Y, [], [], {}),
    ("change_point", Y, [], [], {}),
    ("spc_nonparametric", Y, [], [], {}),
    # Category 4 — SPC
    ("spc_xbar", Y, [], [], {}),
    ("spc_cusum", Y, [], [], {}),
    ("spc_ewma", Y, [], [], {}),
    ("spc_attribute", Y, [], [], {}),
    # Category 5 — NO_TARGET_TASKS
    ("vif", "", X, [], {}),
    ("cohens_kappa", "", [], ["首件合格", "外观检查"], {}),
    ("cronbach_alpha", "", X[:3], [], {}),
    ("power_analysis", "", [], [], {"effect_size": 0.5}),
    # Category 6 — 特殊
    ("doe_analysis", Y, X, [], {}),
    ("response_surface", Y, ["熔体温度", "模具温度"], [], {}),
    # 审查修复：ranges 必须为 dict（原脚本传字符串致 Path A 恒错）
    ("grid_search", Y, ["熔体温度"], [], {"ranges": {"熔体温度": [180, 220]}}),
    # 审查修复：objectives 必须为 list[dict]
    ("multi_objective", Y, ["熔体温度", "模具温度"], [],
     {"objectives": [{"col": "不良率", "direction": "minimize"},
                     {"col": "拉伸强度", "direction": "maximize"}]}),
    ("roc_analysis", "首件合格", ["熔体温度"], [], {}),
    ("logistic_regression", "保养日", X, [], {}),
    ("box_chart", Y, [], [CAT], {}),
    ("outlier_consensus", Y, ["熔体温度"], [], {}),
    ("survival_analysis", Y, [], ["保养日"], {}),
    ("gage_rr", Y, [], ["模具编号", "检验员"],
     {"part_col": "模具编号", "operator_col": "检验员"}),
    ("contingency", "", [], ["原料类型", "保养日"], {}),
    ("scatter_plot", Y, X[:1], [], {"fit": "linear"}),
]


def test_parity_case_count():
    """40 个任务必须全部覆盖（含注册表核对）。"""
    assert len(PARITY_CASES) == 40
    registered = set(TASK_REGISTRY.keys())
    covered = {c[0] for c in PARITY_CASES}
    assert covered == registered, f"差分清单与注册表不一致: {covered ^ registered}"


@pytest.mark.parametrize(
    "task,target_col_str,features,categoricals,params",
    [c for c in PARITY_CASES],
    ids=[c[0] for c in PARITY_CASES],
)
def test_cli_web_numerical_parity(parity_df, task, target_col_str, features, categoricals, params):
    """CLI(orchestrate) 与 Web(run_analysis) 数值一致（审查 2026-08-19 #3.3 改造）。"""
    ok, detail = _compare_one(parity_df, task, target_col_str, features, categoricals, params)
    assert ok, f"{task}: {detail}"

def test_compare_one_catches_metadata_numeric_drift(parity_df, monkeypatch):
    """变异验证（Round-2 批次D #1）：metadata 数值漂移必须被 _compare_one 捕获。

    不修改引擎代码：monkeypatch 包一层 run_analysis，仅对 regression 任务把
    metadata['r_squared'] 加 0.5，模拟两路径数值不一致，断言 _compare_one 返回
    False 且详情包含 r_squared —— 证明数值对比不是形同虚设（仅键集合一致也会被拒）。
    """
    import sys

    real_run = run_analysis

    def mutated_run(*args, **kwargs):
        results = real_run(*args, **kwargs)
        for res in results:
            meta = res.get("metadata") or {}
            if "r_squared" in meta and isinstance(meta["r_squared"], (int, float)):
                meta["r_squared"] = float(meta["r_squared"]) + 0.5
        return results

    monkeypatch.setattr(sys.modules[__name__], "run_analysis", mutated_run)
    ok, detail = _compare_one(parity_df, "regression", Y, X, [], {})
    assert not ok, "metadata 数值漂移（r_squared+0.5）应被捕获"
    assert "r_squared" in detail, f"详情应指出漂移键: {detail}"


def test_compare_one_catches_summary_tail_diff(parity_df, monkeypatch):
    """变异验证（Round-2 批次D #1）：summary 尾部差异必须被 _compare_one 捕获。

    此前 summary 仅比较前 50 字符，尾部结论（如显著性判定）漂移会漏检。
    此处把 Web summary 尾部替换，断言 full-string 比较能捕获。
    """
    import sys

    real_run = run_analysis

    def mutated_run(*args, **kwargs):
        results = real_run(*args, **kwargs)
        for res in results:
            s = res.get("summary") or ""
            if len(s) > 60:
                res["summary"] = s[:-10] + "（已变异）"
        return results

    monkeypatch.setattr(sys.modules[__name__], "run_analysis", mutated_run)
    ok, detail = _compare_one(parity_df, "process_capability", Y, [], [],
                              {"usl": 10, "lsl": 1})
    assert not ok, "summary 尾部差异应被捕获"
    assert "summary_ok=False" in detail, f"详情应指出 summary 不一致: {detail}"
