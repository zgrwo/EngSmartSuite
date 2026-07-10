"""Cross-check key numerical values from docs/user-manual.md against actual source code output.

Robust version: uses positional column access and detection to avoid encoding issues.
"""
import sys
import os
import io
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import orchestrate

OUTPUT = os.path.join(PROJECT_ROOT, "scripts", "verify_manual_claims_output.txt")
buf = io.StringIO()
def p(*args, **kwargs):
    print(*args, **kwargs, file=buf)

# ────────────────────────────────────────────────────────
# Load data & define column indices
# ────────────────────────────────────────────────────────
df_raw = pd.read_excel(os.path.join(PROJECT_ROOT, "tests", "test_data.xlsx"))
COLS = df_raw.columns  # by-index access
# Verified via data patterns:
IDX_MELT_TEMP = 24   # values ~200
IDX_MOLD_TEMP = 25   # values ~60, has NaN
IDX_INJ_PRESS = 26   # values ~80
IDX_COOL_TIME = 29   # values ~20
IDX_DEFECT    = 40   # values ~4
IDX_MATERIAL  = 8    # categorical: ABS/PP/PA66/PC/PA6
IDX_MAINT     = 13   # categorical: 2 groups (保养日, counts: 否=897/是=103)
IDX_FIRST_OK  = 18   # categorical: 2 groups
IDX_APPEAR    = 19   # categorical: 2 groups

C_MELT = COLS[IDX_MELT_TEMP]
C_MOLD = COLS[IDX_MOLD_TEMP]
C_INJ  = COLS[IDX_INJ_PRESS]
C_COOL = COLS[IDX_COOL_TIME]
C_DEF  = COLS[IDX_DEFECT]
C_MAT  = COLS[IDX_MATERIAL]
C_MAINT = COLS[IDX_MAINT]
C_OK   = COLS[IDX_FIRST_OK]

LABEL = {C_MELT: "熔体温度", C_MOLD: "模具温度", C_INJ: "注射压力", C_COOL: "冷却时间"}
FEATURES = [C_MELT, C_MOLD, C_INJ, C_COOL]

p("=== Columns ===")
for i in [IDX_MELT_TEMP, IDX_MOLD_TEMP, IDX_INJ_PRESS, IDX_COOL_TIME, IDX_DEFECT, IDX_MATERIAL, IDX_MAINT, IDX_FIRST_OK]:
    p(f"  Col[{i}] = {repr(COLS[i])}")
p()

def preprocess_numeric(df, features, categoricals=None):
    """Web UI preprocessing for non-RAW_CAT_TASKS."""
    cat_set = set(categoricals) if categoricals else set()
    df_enc, feat_enc, _, imp_log, _ = preprocess_data(df, features, cat_set)
    return df_enc, feat_enc

# ────────────────────────────────────────────────────────
# 1. CORRELATION (4.1)
# ────────────────────────────────────────────────────────
p("=" * 70)
p("1. CORRELATION (4.1)")
p("=" * 70)

df_c, feat_c = preprocess_numeric(df_raw, FEATURES)
req = AnalysisRequest(task="correlation", data=df_c, target_col=C_DEF,
    feature_cols=feat_c, params={"method": "pearson"})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

tc = res.metadata.get("target_correlations", {})
tpa = res.metadata.get("target_p_adjusted", {})
for c in sorted(tc, key=lambda x: abs(tc[x]), reverse=True):
    p(f"  {LABEL.get(c,c)}: r={tc[c]:+.4f}  |r|={abs(tc[c]):.4f}  p_adj={tpa.get(c,'?')}")

corr_r = {c: round(tc.get(c, 0), 4) for c in FEATURES}
corr_padj = {c: round(tpa.get(c, 0), 4) for c in FEATURES}

# ────────────────────────────────────────────────────────
# 2. ANOVA (4.2)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("2. ANOVA (4.2)")
p("=" * 70)

df_a = df_raw.copy()
req = AnalysisRequest(task="anova", data=df_a, target_col=C_DEF,
    feature_cols=[C_MAT], params={"alpha": 0.05})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

at = res.tables.get("anova_enhanced")
ct = res.tables.get("coefficients")
if at is not None:
    p("anova_enhanced:")
    p(at.to_string())
if ct is not None:
    p("coefficients:")
    p(ct.to_string())

# Extract values from ANOVA table by position
# Row 0 = factor, Row 1 = Residual
# Columns: [来源, 自由度(df), 平方和(SS), 均方(MS), F值, p值, η², ω², 效应量解读]
anova_F = float(at.iloc[0, 4]) if at is not None else None
anova_p = float(at.iloc[0, 5]) if at is not None else None
anova_eta2 = float(at.iloc[0, 6]) if at is not None else None
anova_omega2 = float(at.iloc[0, 7]) if at is not None else None
p(f"  F={anova_F}, p={anova_p}, eta2={anova_eta2}, omega2={anova_omega2}")

# ABS mean
abs_mean = float(df_raw[df_raw[C_MAT] == 'ABS'][C_DEF].mean())
p(f"  ABS mean = {abs_mean:.4f}")

# ────────────────────────────────────────────────────────
# 3. HYPOTHESIS_TEST (4.3)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("3. HYPOTHESIS_TEST (4.3)")
p("=" * 70)

df_h = df_raw.copy()
req = AnalysisRequest(task="hypothesis_test", data=df_h, target_col=C_DEF,
    feature_cols=[C_MAINT], params={"test": "ttest_ind", "group_col": C_MAINT})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

tr = res.tables.get("test_results")
ds = res.tables.get("descriptive_stats")
if tr is not None:
    p("test_results:")
    p(tr.to_string())
    p(f"  Columns: {list(tr.columns)}")
    # Columns at positions: 0=method, 1=statistic, 2=p, 3=effect, 4=effect_label, 5=power, 6=conclusion
    ht_stat = float(tr.iloc[0, 1])
    ht_p = float(tr.iloc[0, 2])
    ht_effect = str(tr.iloc[0, 3])
    p(f"  t={ht_stat:.4f}, p={ht_p:.6f}, effect={ht_effect}")
if ds is not None:
    p("descriptive_stats:")
    p(ds.to_string())
    for i in range(len(ds)):
        grp = str(ds.iloc[i, 0])
        nv = int(ds.iloc[i, 1])
        mv = float(ds.iloc[i, 2])
        sdv = float(ds.iloc[i, 3])
        p(f"  Group '{grp}': n={nv}, mean={mv:.4f}, std={sdv:.4f}")

# ────────────────────────────────────────────────────────
# 4. DECISION_TREE (4.4)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("4. DECISION_TREE (4.4)")
p("=" * 70)

df_d, feat_d = preprocess_numeric(df_raw, FEATURES)
req = AnalysisRequest(task="decision_tree", data=df_d, target_col=C_DEF,
    feature_cols=feat_d, params={"max_depth": 5, "random_state": 42})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

fi = res.tables.get("feature_importance")
if fi is not None:
    p("feature_importance:")
    p(fi.to_string())
    p(f"  Columns: {list(fi.columns)}")
    # Columns: [因子, 内置重要性(Gini), 排列重要性, 排列重要性 std, 综合重要性]
    dt_perm = {}
    dt_gini = {}
    for i in range(len(fi)):
        factor = str(fi.iloc[i, 0])
        gini_v = float(fi.iloc[i, 1])
        perm_v = float(fi.iloc[i, 2])
        perm_std = float(fi.iloc[i, 3]) if len(fi.columns) > 3 else 0
        p(f"  {factor}: Gini={gini_v:.4f}, Perm={perm_v:.4f}, Perm_std={perm_std:.4f}")
        dt_perm[factor] = round(perm_v, 4)
        dt_gini[factor] = round(gini_v, 4)

# ────────────────────────────────────────────────────────
# 5. VIF (4.5)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("5. VIF (4.5)")
p("=" * 70)

df_v, feat_v = preprocess_numeric(df_raw, FEATURES)
req = AnalysisRequest(task="vif", data=df_v, target_col="",
    feature_cols=feat_v, params={"threshold": 5})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

vt = res.tables.get("vif_table")
if vt is not None:
    p("vif_table:")
    p(vt.to_string())
    vif_vals = {}
    for i in range(len(vt)):
        var_name = str(vt.iloc[i, 0])
        vif_val = float(vt.iloc[i, 1])
        verdict = str(vt.iloc[i, 2]) if len(vt.columns) > 2 else ""
        p(f"  {var_name}: VIF={vif_val:.4f}  {verdict}")
        vif_vals[var_name] = round(vif_val, 4)

# ────────────────────────────────────────────────────────
# 6. CONTINGENCY (4.6)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("6. CONTINGENCY (4.6)")
p("=" * 70)

df_ct = df_raw.copy()
# contingency_analysis uses: col1=target_col, col2=feature_cols[0]
req = AnalysisRequest(task="contingency", data=df_ct, target_col=C_MAT,
    feature_cols=[C_MAINT], params={})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

co_tbl = res.tables.get("contingency_table")
ex_tbl = res.tables.get("expected_frequencies")

if co_tbl is not None:
    p("contingency_table:")
    p(co_tbl.to_string())
    p()

if ex_tbl is not None:
    p("expected_frequencies:")
    p(ex_tbl.to_string())
    p()

p(f"All tables: {list(res.tables.keys())}")
p(f"Metadata: {res.metadata}")

# Print all non-standard tables
for k, v in res.tables.items():
    if k not in ("contingency_table", "expected_frequencies"):
        p(f"\nTable '{k}':")
        p(v.to_string())

# Extract chi2 p and Cramer's V from metadata
cont_chi2_p = None
cont_cv = None

# Directly from res.metadata (contingency_analysis puts p_value and effect_size there)
meta_pval = res.metadata.get("p_value")
if meta_pval is not None:
    cont_chi2_p = float(meta_pval)
    p(f"  From metadata: p_value={cont_chi2_p:.4f}")

meta_effect = res.metadata.get("effect_size")
meta_effect_name = res.metadata.get("effect_name", "")
if meta_effect is not None:
    cont_cv = float(meta_effect)
    p(f"  From metadata: effect_size={cont_cv:.4f} ({meta_effect_name})")

p(f"  Final: chi2_p = {cont_chi2_p}, Cramer's V = {cont_cv}")

# ────────────────────────────────────────────────────────
# 7. PROPORTION_CI (4.7)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("7. PROPORTION_CI (4.7)")
p("=" * 70)

# Convert 首件合格 to binary: 合格=1, 不合格=0
df_p = df_raw.copy()
p(f"First OK unique: {list(df_p[C_OK].unique())}")
p(f"Value counts: {df_p[C_OK].value_counts().to_dict()}")

# Map by position (first value is typically 合格)
uv = list(df_p[C_OK].unique())
val_map = {}
for v in uv:
    sv = str(v)
    if len(sv) > 0:
        b = ord(sv[0])
        # In GBK: 合 = 0xBACF, 不 = 0xB2BB
        # Binary approach: '不合格' starts with the '不' character
        val_map[v] = 0 if '不' in sv else 1
    else:
        val_map[v] = 0
p(f"Value map: {val_map}")

df_p[C_OK] = df_p[C_OK].map(val_map)
p(f"Mapped counts: {df_p[C_OK].value_counts().to_dict()}")

req = AnalysisRequest(task="proportion_ci", data=df_p, target_col=C_OK,
    feature_cols=[], params={"method": "wilson", "alpha": 0.05})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

pci = res.tables.get("proportion_ci")
if pci is not None:
    p("proportion_ci:")
    p(pci.to_string())
    pci_data = {}
    for i in range(len(pci)):
        method = str(pci.iloc[i, 0])
        lower = float(pci.iloc[i, 1])
        upper = float(pci.iloc[i, 2])
        p(f"  {method}: [{lower:.4f}, {upper:.4f}]")
        pci_data[method] = {"lower": round(lower, 4), "upper": round(upper, 4)}

# ────────────────────────────────────────────────────────
# 8. PROCESS_CAPABILITY (7.5)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("8. PROCESS_CAPABILITY (7.5)")
p("=" * 70)

req = AnalysisRequest(task="process_capability", data=df_raw.copy(), target_col=C_DEF,
    feature_cols=[], params={"usl": 10, "lsl": 1})
res = orchestrate(req)
assert res.status != "error", str(res.messages)

p(f"All tables: {list(res.tables.keys())}")
p(f"Metadata keys: {list(res.metadata.keys())}")

pc_vals = {}
for k, v in res.tables.items():
    p(f"\nTable '{k}':")
    p(v.to_string())
    p(f"  Columns: {list(v.columns)}")
    p(f"  Index: {list(v.index)}")
    # Try to extract numeric values
    for idx in range(len(v)):
        for col in range(len(v.columns)):
            val = v.iloc[idx, col]
            try:
                fv = float(val)
                label = str(v.index[idx]) if hasattr(v, 'index') else str(idx)
                col_label = str(v.columns[col])
                pc_vals[f"{k}.{label}.{col_label}"] = fv
            except (ValueError, TypeError):
                pass

# Also check metadata for Cp/Cpk
for key, val in res.metadata.items():
    if isinstance(val, (int, float)):
        pc_vals[f"meta.{key}"] = float(val)

p(f"\nAll PC numeric values: {pc_vals}")

# ────────────────────────────────────────────────────────
# FINAL COMPARISON REPORT
# ────────────────────────────────────────────────────────
p()
p()
p("=" * 100)
p("FINAL COMPARISON REPORT")
p("=" * 100)
p()

def rpt(analysis, value_name, manual, actual, tolerance=0.001):
    """Report a single comparison."""
    if actual is None:
        disp, match = "N/A", "N/A"
    elif isinstance(manual, str):
        match = "OK" if str(actual) == str(manual) else "DIFF"
        disp = str(actual)
    else:
        try:
            diff = abs(float(actual) - float(manual))
            match = "OK" if diff < tolerance else f"DIFF({diff:.4f})"
            disp = f"{float(actual):.4f}"
        except (ValueError, TypeError):
            match = "ERR"
            disp = str(actual)
    p(f"  {analysis:<24} | {value_name:<25} | {str(manual):<18} | {disp:<18} | {match}")

p("--- 4.1 CORRELATION ---")
rpt("correlation", "注射压力 r", -0.050, corr_r.get(C_INJ), 0.001)
rpt("correlation", "模具温度 r", -0.049, corr_r.get(C_MOLD), 0.001)
rpt("correlation", "熔体温度 r", -0.049, corr_r.get(C_MELT), 0.001)
rpt("correlation", "冷却时间 r", 0.038, corr_r.get(C_COOL), 0.001)
all_1 = all(abs(corr_padj.get(c, 0) - 1.0) < 0.001 for c in FEATURES)
rpt("correlation", "Bonferroni p_adj=1.0", "True", "True" if all_1 else "False")

p()
p("--- 4.2 ANOVA ---")
rpt("anova", "F", 0.67, anova_F, 0.01)
rpt("anova", "p", 0.615, anova_p, 0.01)
rpt("anova", "eta2", 0.0027, anova_eta2, 0.0005)
rpt("anova", "ABS mean", 4.217, round(abs_mean, 4), 0.005)

p()
p("--- 4.3 HYPOTHESIS_TEST ---")
rpt("hypothesis_test", "t statistic", 12.60, ht_stat, 0.05)
rpt("hypothesis_test", "p value", 0.0000, ht_p, 0.001)
# Extract group means from ds table
for i in range(len(ds)):
    grp = str(ds.iloc[i, 0])
    mv = float(ds.iloc[i, 2])
    if '否' in grp:
        rpt("hypothesis_test", f"No group mean", 4.405, round(mv, 4), 0.005)
    elif '是' in grp:
        rpt("hypothesis_test", f"Yes group mean", 2.891, round(mv, 4), 0.005)

p()
p("--- 4.4 DECISION_TREE ---")
for factor, short, claim in [(C_COOL, "冷却时间", 0.194), (C_MELT, "熔体温度", 0.106),
                              (C_MOLD, "模具温度", 0.049), (C_INJ, "注射压力", 0.004)]:
    actual = dt_perm.get(factor)
    rpt("decision_tree", f"{short} perm", claim, actual, 0.01 if claim > 0.05 else 0.005)

p()
p("--- 4.5 VIF ---")
for factor, short in [(C_MELT, "VIF 熔体温度"), (C_MOLD, "VIF 模具温度"),
                       (C_INJ, "VIF 注射压力"), (C_COOL, "VIF 冷却时间")]:
    actual = vif_vals.get(factor)
    if actual is not None:
        ok = 1.0 <= actual <= 1.005
        rpt("vif", short, "~1.002-1.004", actual, 0.01)

p()
p("--- 4.6 CONTINGENCY ---")
rpt("contingency", "chi2 p", 0.064, cont_chi2_p, 0.01)
rpt("contingency", "Cramer's V", 0.094, cont_cv, 0.01)

p()
p("--- 4.7 PROPORTION_CI ---")
for method, bounds in pci_data.items():
    if "Wilson" in method:
        rpt("proportion_ci", "Wilson lower", 0.8917, bounds["lower"], 0.0005)
        rpt("proportion_ci", "Wilson upper", 0.9271, bounds["upper"], 0.0005)
    elif "点估计" in method or "point" in method.lower() or "估计" in method:
        rpt("proportion_ci", "point estimate", 0.9110, bounds["lower"], 0.0005)

p()
p("--- 7.5 PROCESS_CAPABILITY ---")
# Search for Cp and Cpk in pc_vals
for key, val in pc_vals.items():
    key_lower = key.lower()
    if 'cpk' in key_lower and 'ppk' not in key_lower and 'ci' not in key_lower:
        rpt("process_capability", f"Cpk ({key})", 0.923, round(val, 4), 0.01)
    elif 'cp' in key_lower and 'cpk' not in key_lower and 'pp' not in key_lower and 'ci' not in key_lower:
        rpt("process_capability", f"Cp ({key})", 1.279, round(val, 4), 0.01)

p()
p("=" * 100)
p("VERIFICATION COMPLETE")
p("=" * 100)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(f"Output: {OUTPUT}")
print("Done.")
