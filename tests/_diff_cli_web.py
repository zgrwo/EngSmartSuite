"""CLI (orchestrate) vs Web (run_analysis) numerical parity test — all 39 methods.

Path A: replicate run_analysis's internal preprocessing, then orchestrate().
Path B: run_analysis() → list[dict] → compare status/summary/tables/metadata.

Fixes over the original script:
1. run_analysis returns list[dict], not list[AnalysisResult] — access with ["key"]
2. Tables serialised as {columns, index, data, shape} — reconstruct via pd.DataFrame
3. Table comparison uses check_index_type=False, check_column_type=False
4. Path A replicates auto_generate_subgroup_col / infer_group_col
5. logistic_regression & contingency: pass correct targets for run_analysis iteration
"""
import pandas as pd
import numpy as np
from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import (
    TASK_REGISTRY, orchestrate, NO_TARGET_TASKS, RAW_CAT_TASKS,
)
from smartsuite.web.api import run_analysis
from smartsuite.services.data_io import (
    preprocess_for_task, auto_generate_subgroup_col, infer_group_col,
)

# ---------------------------------------------------------------------------
df = pd.read_excel("tests/test_data.xlsx")

y_num = "不良率"
x_num = ["熔体温度", "模具温度", "注射压力", "冷却时间"]
cat_col = "原料类型"

results: list[str] = []
mismatches: list[str] = []

# ---------------------------------------------------------------------------
def _infer_index(values):
    """Convert string-serialised index/column values back to original types."""
    out = []
    for v in values:
        # Keep strings that look like real text (not just a number in string form)
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
    # If all converted values are int-like, use int; else keep the mixed list
    if all(isinstance(x, int) for x in out):
        return pd.Index(out, dtype="int64")
    if all(isinstance(x, (int, float)) for x in out):
        return pd.Index(out, dtype="float64")
    return pd.Index(values)


def _infer_columns(values):
    """Like _infer_index but preserves column names that are genuinely strings."""
    return _infer_index(values)


def df_from_serialized(table_dict):
    """Reconstruct a DataFrame from run_analysis's serialised table format."""
    return pd.DataFrame(
        data=table_dict["data"],
        index=_infer_index(table_dict["index"]),
        columns=_infer_columns(table_dict["columns"]),
    )


def _normalize_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DataFrame for comparison: normalize NaN/empty, convert types, round.

    Matches the serialization pipeline in run_analysis:
      - str() on index/columns
      - round(4) on numeric columns
      - fillna("") on all data
    """
    df = df.copy()
    for col in df.columns:
        col_dtype = df[col].dtype
        # Check if this is a string-like column (object or StringDtype)
        is_stringy = (
            col_dtype == object
            or "str" in str(col_dtype).lower()
            or "string" in str(col_dtype).lower()
        )
        if is_stringy:
            # Replace empty strings and literal NaN markers with true NaN
            empty_set = {"", "nan", "NaN", "None", "null", "NA"}
            # Use .replace() which works for both object and StringDtype
            df[col] = df[col].replace(empty_set, np.nan)
            # Try to convert to numeric (mixed-type columns)
            try:
                numeric = pd.to_numeric(df[col])
                df[col] = numeric
            except (ValueError, TypeError):
                pass
        # Round numeric columns to match serialization precision (round(4))
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_datetime64_any_dtype(df[col]):
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
                ta_norm, tb_norm,
                check_index_type=False,
                check_column_type=False,
                check_dtype=False,
                atol=1e-4, rtol=1e-3,
            )
        except AssertionError as exc:
            return False, f"table '{k}': {str(exc)[:150]}"
    return True, ""


def compare_one(label, task, target_col_str, features, categoricals, params):
    """Run both paths (A = CLI-style, B = Web-style), compare results."""
    # ---- build target/features lists for run_analysis ----
    targets_for_b = [target_col_str] if target_col_str else []

    # ---- Path A: replicate run_analysis preprocessing, then orchestrate ----
    try:
        df_a = df.copy()
        feat_a = list(features)
        params_a = dict(params)

        # (1) auto_generate_subgroup_col for spc_xbar
        if task == "spc_xbar" and "subgroup_col" not in params_a:
            df_a, params_a = auto_generate_subgroup_col(df_a, params_a)

        # (2) preprocess
        df_enc, feat_enc, _, _ = preprocess_for_task(
            df_a, feat_a, task, categoricals, RAW_CAT_TASKS,
        )

        # (3) hypothesis_test group_col inference
        if task == "hypothesis_test" and "group_col" not in params_a:
            extra = infer_group_col(df_a, feat_a, categoricals)
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
        results.append(f"{label:28s} PATH_A ERROR: {str(e)[:80]}")
        mismatches.append(f"{label}: PATH_A exception: {str(e)[:120]}")
        return

    # ---- Path B: run_analysis ----
    # Special handling for tasks that need targets but engine ignores them
    b_targets = list(targets_for_b)
    if not b_targets and task not in NO_TARGET_TASKS:
        # contingency, logistic_regression when target is passed as categorical
        b_targets = [target_col_str] if target_col_str else [""]

    try:
        b_categoricals = list(categoricals) if categoricals else []
        r_b_list = run_analysis(task, df, targets=b_targets,
                                features=list(features),
                                categoricals=b_categoricals,
                                params=dict(params))
        if not r_b_list:
            results.append(f"{label:28s} PATH_B: empty result list")
            mismatches.append(f"{label}: PATH_B returned empty list")
            return
        r_b_dict = r_b_list[0]
    except Exception as e:
        results.append(f"{label:28s} PATH_B ERROR: {str(e)[:80]}")
        mismatches.append(f"{label}: PATH_B exception: {str(e)[:120]}")
        return

    # ---- comparisons ----
    status_ok = (r_a.status == r_b_dict["status"])
    summary_ok = True
    if r_a.summary or r_b_dict.get("summary"):
        summary_ok = (r_a.summary[:50] == r_b_dict.get("summary", "")[:50])

    meta_keys_ok = set(r_a.metadata.keys()) == set(r_b_dict.get("metadata", {}).keys())

    # reconstruct B tables
    try:
        t_b = {
            k: df_from_serialized(v)
            for k, v in r_b_dict.get("tables", {}).items()
            if not k.startswith("_merged")
        }
    except Exception as exc:
        t_b = {}
        results.append(f"{label:28s} TABLE_RECONSTRUCT ERROR: {str(exc)[:80]}")
        mismatches.append(f"{label}: TABLE_RECONSTRUCT: {str(exc)[:120]}")
        return

    table_ok, table_detail = tables_equal(r_a.tables, t_b)

    parts = [
        f"status={status_ok}",
        f"summary≈{summary_ok}",
        f"tables={table_ok}",
        f"meta_keys={meta_keys_ok}",
    ]
    results.append(f"{label:28s} {' | '.join(parts)}")

    if not (status_ok and summary_ok and table_ok and meta_keys_ok):
        detail = (
            f"  status_ok={status_ok} summary_ok={summary_ok} "
            f"table_ok={table_ok} meta_keys_ok={meta_keys_ok}"
        )
        if not table_ok:
            detail += f"\n    table_detail: {table_detail}"
        mismatches.append(f"{label}: {detail}")


# =====================================================================
# Category 1 — both target + features (numerical)
# =====================================================================
for task in ["correlation", "regression", "decision_tree", "lasso_regression",
             "robust_regression", "quantile_regression"]:
    compare_one(task, task, y_num, x_num, [], {})

# =====================================================================
# Category 2 — ANOVA-like (categorical features)
# =====================================================================
for task in ["anova", "hypothesis_test", "variance_test"]:
    compare_one(task, task, y_num, [], [cat_col], {})

# =====================================================================
# Category 3 — Y-only
# =====================================================================
y_only_tasks = [
    "process_capability", "trend_forecast", "anomaly_detect",
    "distribution_summary", "normality_check", "proportion_ci",
    "bootstrap_ci", "median_ci", "tolerance_interval", "change_point",
    "spc_nonparametric",
]
for task in y_only_tasks:
    params = {"usl": 10, "lsl": 1} if task == "process_capability" else {}
    compare_one(task, task, y_num, [], [], params)

# =====================================================================
# Category 4 — SPC
# =====================================================================
for task in ["spc_xbar", "spc_cusum", "spc_ewma", "spc_attribute"]:
    compare_one(task, task, y_num, [], [], {})

# =====================================================================
# Category 5 — NO_TARGET_TASKS
# =====================================================================
compare_one("vif", "vif", "", x_num, [], {})
compare_one("cohens_kappa", "cohens_kappa", "", [], ["首件合格", "外观检查"], {})
compare_one("cronbach_alpha", "cronbach_alpha", "", x_num[:3], [], {})
compare_one("power_analysis", "power_analysis", "", [], [], {"effect_size": 0.5})

# =====================================================================
# Category 6 — remaining / special
# =====================================================================
compare_one("doe_analysis",       "doe_analysis",       y_num,   x_num,                       [],  {})
compare_one("response_surface",   "response_surface",   y_num,   ["熔体温度", "模具温度"],     [],  {})
compare_one("grid_search",        "grid_search",        y_num,   ["熔体温度"],                 [],  {"ranges": "熔体温度:180,220"})
compare_one("multi_objective",    "multi_objective",    "不良率", ["熔体温度", "模具温度"],     [],  {"objectives": "不良率:minimize;拉伸强度:maximize"})
compare_one("roc_analysis",       "roc_analysis",       "首件合格", ["熔体温度"],               [],  {})
# logistic_regression: target_col is the binary outcome
compare_one("logistic_regression","logistic_regression", "保养日", x_num,                       [],  {})
compare_one("box_chart",          "box_chart",          y_num,   [],                           [cat_col], {})
compare_one("outlier_consensus",  "outlier_consensus",  y_num,   ["熔体温度"],                 [],  {})
compare_one("survival_analysis",  "survival_analysis",  y_num,   [],                           ["保养日"], {})
compare_one("gage_rr",            "gage_rr",            y_num,   [],                           ["模具编号", "检验员"],
            {"part_col": "模具编号", "operator_col": "检验员"})
compare_one("contingency",        "contingency",        "",      [],                           ["原料类型", "保养日"], {})

# =====================================================================
# report
# =====================================================================
print("=" * 72)
print("CLI vs Web numerical parity — results")
print("=" * 72)
for r in results:
    print(r)

total = len(results)
bad = len(mismatches)
print(f"\nTotal: {total} tasks tested, {bad} mismatches")

assert total == 39, f"Expected 39 tasks, got {total}"

if mismatches:
    print(f"\n--- MISMATCHES ({bad}) ---")
    for m in mismatches:
        print(m)
    print("\n*** SOME MISMATCHES FOUND ***")
else:
    print("\nALL CLEAN — zero CLI/Web mismatches across all 39 methods")
