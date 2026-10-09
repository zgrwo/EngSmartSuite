"""Cross-check key numerical values from docs/user-manual/（按章拆页） against actual source code output.

Robust version: uses positional column access and detection to avoid encoding issues.
"""

import io
import os
import re
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 手册新鲜度模块（F-D1）

from claims_gate import VIF_CLAIM_TOLERANCE, VIF_MANUAL_CLAIMS, classify_missing  # noqa: E402

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services import config
from smartsuite.services.data_io import preprocess_data, preprocess_for_task
from smartsuite.services.orchestrator import RAW_CAT_TASKS, orchestrate

OUTPUT = os.path.join(PROJECT_ROOT, "scripts", "verify_manual_claims_output.txt")
buf = io.StringIO()

# 审查 2026-09-01 G-1：失败计数 → 脚本退出码（此前 DIFF 仅记录文本，永远 exit 0）
fail_count = 0
# 审查 2026-09-06 F-D1：rpt() 数值 CLAIM 登记簿 → 结尾对手册新鲜度校验
# （快照值必须仍存在于 user-manual/（按章拆页）对应章节，防手册内容漂移无门禁）
CLAIM_LOG: list[tuple] = []


def p(*args, **kwargs):
    print(*args, **kwargs, file=buf)


# ────────────────────────────────────────────────────────
# Load data & define column indices
# ────────────────────────────────────────────────────────
df_raw = pd.read_excel(os.path.join(PROJECT_ROOT, "tests", "data", "injection_process.xlsx"))
COLS = df_raw.columns  # by-index access
# Verified via data patterns:
IDX_MELT_TEMP = 24  # values ~200
IDX_MOLD_TEMP = 25  # values ~60, has NaN
IDX_INJ_PRESS = 26  # values ~80
IDX_COOL_TIME = 29  # values ~20
IDX_DEFECT = 40  # values ~4
IDX_MATERIAL = 8  # categorical: ABS/PP/PA66/PC/PA6
IDX_MAINT = 13  # categorical: 2 groups (保养日, counts: 否=897/是=103)
IDX_FIRST_OK = 18  # categorical: 2 groups
IDX_APPEAR = 19  # categorical: 2 groups

C_MELT = COLS[IDX_MELT_TEMP]
C_MOLD = COLS[IDX_MOLD_TEMP]
C_INJ = COLS[IDX_INJ_PRESS]
C_COOL = COLS[IDX_COOL_TIME]
C_DEF = COLS[IDX_DEFECT]
C_MAT = COLS[IDX_MATERIAL]
C_MAINT = COLS[IDX_MAINT]
C_OK = COLS[IDX_FIRST_OK]
C_APPEAR = COLS[IDX_APPEAR]  # §5.1 cohens_kappa 的第二评定者列

LABEL = {C_MELT: "熔体温度", C_MOLD: "模具温度", C_INJ: "注射压力", C_COOL: "冷却时间"}
FEATURES = [C_MELT, C_MOLD, C_INJ, C_COOL]

p("=== Columns ===")
for i in [
    IDX_MELT_TEMP,
    IDX_MOLD_TEMP,
    IDX_INJ_PRESS,
    IDX_COOL_TIME,
    IDX_DEFECT,
    IDX_MATERIAL,
    IDX_MAINT,
    IDX_FIRST_OK,
]:
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
req = AnalysisRequest(
    task="correlation",
    data=df_c,
    target_col=C_DEF,
    feature_cols=feat_c,
    params={"method": "pearson"},
)
res = orchestrate(req)
assert res.status != "error", str(res.messages)

tc = res.metadata.get("target_correlations", {})
tpa = res.metadata.get("target_p_adjusted", {})
for c in sorted(tc, key=lambda x: abs(tc[x]), reverse=True):
    p(f"  {LABEL.get(c, c)}: r={tc[c]:+.4f}  |r|={abs(tc[c]):.4f}  p_adj={tpa.get(c, '?')}")

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
req = AnalysisRequest(
    task="anova", data=df_a, target_col=C_DEF, feature_cols=[C_MAT], params={"alpha": 0.05}
)
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
abs_mean = float(df_raw[df_raw[C_MAT] == "ABS"][C_DEF].mean())
p(f"  ABS mean = {abs_mean:.4f}")

# ────────────────────────────────────────────────────────
# 3. HYPOTHESIS_TEST (4.3)
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("3. HYPOTHESIS_TEST (4.3)")
p("=" * 70)

df_h = df_raw.copy()
req = AnalysisRequest(
    task="hypothesis_test",
    data=df_h,
    target_col=C_DEF,
    feature_cols=[C_MAINT],
    params={"test": "ttest_ind", "group_col": C_MAINT},
)
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
req = AnalysisRequest(
    task="decision_tree",
    data=df_d,
    target_col=C_DEF,
    feature_cols=feat_d,
    params={"max_depth": 5, "random_state": 42},
)
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
req = AnalysisRequest(
    task="vif", data=df_v, target_col="", feature_cols=feat_v, params={"threshold": 5}
)
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
req = AnalysisRequest(
    task="contingency", data=df_ct, target_col=C_MAT, feature_cols=[C_MAINT], params={}
)
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
        val_map[v] = 0 if "不" in sv else 1
    else:
        val_map[v] = 0
p(f"Value map: {val_map}")

df_p[C_OK] = df_p[C_OK].map(val_map)
p(f"Mapped counts: {df_p[C_OK].value_counts().to_dict()}")

req = AnalysisRequest(
    task="proportion_ci",
    data=df_p,
    target_col=C_OK,
    feature_cols=[],
    params={"method": "wilson", "alpha": 0.05},
)
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

req = AnalysisRequest(
    task="process_capability",
    data=df_raw.copy(),
    target_col=C_DEF,
    feature_cols=[],
    params={"usl": 10, "lsl": 1},
)
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
                label = str(v.index[idx]) if hasattr(v, "index") else str(idx)
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
# 9. TREND_FORECAST (7.6) — 手册 §7.6 RMSE 硬校验（2026-08-29 审查 R2）
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("9. TREND_FORECAST (7.6)")
p("=" * 70)

req = AnalysisRequest(
    task="trend_forecast",
    data=df_raw.copy(),
    target_col=C_DEF,
    feature_cols=[],
    params={},
)
res = orchestrate(req)
assert res.status != "error", str(res.messages)
tf_rmse = float(res.metadata.get("rmse", float("nan")))
tf_r2 = float(res.metadata.get("r_squared", float("nan")))
tf_dw = float(res.metadata.get("durbin_watson", float("nan")))
p(f"  RMSE={tf_rmse:.4f}, R²={tf_r2:.4f}, DW={tf_dw:.4f}")

# ────────────────────────────────────────────────────────
# 10. BOOTSTRAP_CI (8.1) — 手册 §8.1 CI 硬校验（2026-08-29 审查 R7）
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("10. BOOTSTRAP_CI (8.1)")
p("=" * 70)

req = AnalysisRequest(
    task="bootstrap_ci",
    data=df_raw.copy(),
    target_col=C_DEF,
    feature_cols=[],
    params={"n_bootstrap": 2000},
)
res = orchestrate(req)
assert res.status != "error", str(res.messages)
bc_point = float(res.metadata.get("point_estimate", float("nan")))
bc_lower = float(res.metadata.get("ci_lower", float("nan")))
bc_upper = float(res.metadata.get("ci_upper", float("nan")))
p(f"  点估计={bc_point:.4f}, CI=[{bc_lower:.4f}, {bc_upper:.4f}]")

# ────────────────────────────────────────────────────────
# 11. INVERSE_SOLVE (6.12) — 方程系数独立 OLS 校验（审查 2026-09-11 F6）
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("11. INVERSE_SOLVE (6.12)")
p("=" * 70)

_iv = df_raw[[C_MELT, C_MOLD, C_DEF]].dropna()
_iv_model = LinearRegression().fit(_iv[[C_MELT, C_MOLD]], _iv[C_DEF])
iv_intercept = float(_iv_model.intercept_)
iv_coef_melt = float(_iv_model.coef_[0])
iv_coef_mold = float(_iv_model.coef_[1])
_iv_pred = cross_val_predict(
    LinearRegression(), _iv[[C_MELT, C_MOLD]], _iv[C_DEF], cv=LeaveOneOut()
)
iv_loo_r2 = float(r2_score(_iv[C_DEF], _iv_pred))
p(
    f"  独立 OLS（{len(_iv)} 行）: 截距={iv_intercept:.6f}, "
    f"{LABEL[C_MELT]}={iv_coef_melt:.8f}, {LABEL[C_MOLD]}={iv_coef_mold:.8f}, "
    f"LOO R²={iv_loo_r2:.6f}"
)

# ────────────────────────────────────────────────────────
# 12. 补充取数（第二轮全量审查 2026-10-10 维度 F：F02/F03/F05/F06/F07/F09）
#     背景：手册 33 个含数值的节里，20 个**完全没有 CLAIM** —— 改坏手册值
#     门禁照样 exit 0（审查注入 INJ-3/4/5/6 实测）。本节把这些节的数值
#     登记进来，每个值都由 orchestrate() 实跑取得。
#     口径：**Web** = preprocess_for_task(df, …, task, cats, RAW_CAT_TASKS)
#     （非 RAW_CAT 任务 → preprocess_data 中位数填充；RAW_CAT 任务 → 原帧）；
#     raw = 直接传原始 DataFrame（引擎内部 dropna）。
# ────────────────────────────────────────────────────────
p()
p("=" * 70)
p("12. 补充取数（F02/F03/F05/F06/F07/F09：此前零 CLAIM 覆盖的手册节）")
p("=" * 70)


def web_run(task, data, target, features, params=None, cats=None):
    """按 Web 口径预处理后调用引擎（RAW_CAT 任务跳过 One-Hot，与 web/api.py 一致）。"""
    _d, _f, _log, _w = preprocess_for_task(data, list(features), task, cats, RAW_CAT_TASKS)
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=_d,
            target_col=target,
            feature_cols=list(_f),
            params=dict(params or {}),
        )
    )


# --- §3.1 前 5 行预览（原始文件，不预处理）；手册表格逐格必须一致 ---
PREVIEW_COLS = [
    "生产日期",
    "班次",
    "车间",
    "原料类型",
    "熔体温度",
    "模具温度",
    "注射压力",
    "冷却时间",
    "不良率",
    "拉伸强度",
]
# 手册 §3.1 表的数值快照（行号从 1 起；模具温度第 1/4 行为 NaN → 非数值 CLAIM）
PREVIEW_MANUAL = {
    (1, "熔体温度"): 206.5,
    (1, "注射压力"): 85.1,
    (1, "冷却时间"): 22.0,
    (1, "不良率"): 6.106,
    (1, "拉伸强度"): 35.56,
    (2, "熔体温度"): 204.8,
    (2, "模具温度"): 54.7,
    (2, "注射压力"): 80.0,
    (2, "冷却时间"): 20.8,
    (2, "不良率"): 3.008,
    (2, "拉伸强度"): 38.17,
    (3, "熔体温度"): 205.4,
    (3, "模具温度"): 66.0,
    (3, "注射压力"): 53.4,
    (3, "冷却时间"): 22.7,
    (3, "不良率"): 4.808,
    (3, "拉伸强度"): 35.93,
    (4, "熔体温度"): 208.5,
    (4, "注射压力"): 84.8,
    (4, "冷却时间"): 24.9,
    (4, "不良率"): 4.392,
    (4, "拉伸强度"): 33.9,
    (5, "熔体温度"): 202.5,
    (5, "模具温度"): 68.4,
    (5, "注射压力"): 64.2,
    (5, "冷却时间"): 19.8,
    (5, "不良率"): 2.186,
    (5, "拉伸强度"): 36.46,
}
PREVIEW_ACTUAL: dict[tuple[int, str], float] = {}
PREVIEW_ACTUAL_NAN: dict[tuple[int, str], bool] = {}
_pv = df_raw[PREVIEW_COLS].head(5)
for _ri in range(5):
    for _ci, _col in enumerate(PREVIEW_COLS, start=1):
        if _ci < 5:
            continue
        _v = _pv.iloc[_ri][_col]
        PREVIEW_ACTUAL_NAN[(_ri + 1, _col)] = bool(pd.isna(_v))
        if not pd.isna(_v):
            PREVIEW_ACTUAL[(_ri + 1, _col)] = float(_v)
p(f"  §3.1 预览：数值格 {len(PREVIEW_MANUAL)}，NaN 格 {sum(PREVIEW_ACTUAL_NAN.values())}")

# --- §4.4 decision_tree（Web 口径；手册表 = Web，训练 R²/CV R² 同口径）---
_df44, _feat44 = preprocess_numeric(df_raw, FEATURES)
_res44 = orchestrate(
    AnalysisRequest(
        task="decision_tree",
        data=_df44,
        target_col=C_DEF,
        feature_cols=_feat44,
        params={"max_depth": 5, "random_state": 42},
    )
)
dt_train_r2 = round(float(_res44.metadata.get("train_r2", float("nan"))), 3)
dt_cv_r2 = round(float(_res44.metadata.get("cv_r2", float("nan"))), 3)
_fi44 = _res44.tables.get("feature_importance")
dt_gini: dict[str, float] = {}
dt_perm_std: dict[str, float] = {}
for _i in range(len(_fi44)):
    _f = str(_fi44.iloc[_i, 0])
    dt_gini[_f] = round(float(_fi44.iloc[_i, 1]), 3)
    dt_perm_std[_f] = round(float(_fi44.iloc[_i, 3]), 3)
p(f"  §4.4 Web: 训练R²={dt_train_r2} CV_R²={dt_cv_r2} Gini={dt_gini} std={dt_perm_std}")

# --- §5.2 cronbach_alpha（Web 口径）---
_res52 = web_run("cronbach_alpha", df_raw, "", [C_MELT, C_MOLD, C_INJ], {})
cron_alpha = round(float(_res52.metadata.get("alpha", float("nan"))), 3)
cron_n = int(_res52.metadata.get("n", 0))
p(f"  §5.2 Web: α={cron_alpha} n={cron_n}")

# --- §6.1 regression（Web 口径）---
_res61 = web_run("regression", df_raw, C_DEF, [C_MELT, C_INJ, C_COOL], {})
_ct61 = _res61.tables.get("coefficients")
reg_rows: dict[str, dict[str, float]] = {}
for _i in range(len(_ct61)):
    _name = str(_ct61.iloc[_i, 0])
    reg_rows[_name] = {
        "系数": round(float(_ct61.iloc[_i, 1]), 3),
        "标准误": round(float(_ct61.iloc[_i, 2]), 3),
        "t值": round(float(_ct61.iloc[_i, 3]), 2),
        "p值": round(float(_ct61.iloc[_i, 4]), 3),
    }
_m61 = _res61.metadata
reg_r2 = round(float(_m61.get("r_squared", float("nan"))), 4)
reg_r2adj = round(float(_m61.get("r_squared_adj", float("nan"))), 4)
reg_f = round(float(_m61.get("f_statistic", float("nan"))), 2)
reg_fp = round(float(_m61.get("f_pvalue", float("nan"))), 3)
reg_dw = round(float(_m61.get("durbin_watson", float("nan"))), 3)
reg_bp = round(float(_m61.get("breusch_pagan_p", float("nan"))), 3)
p(
    f"  §6.1 Web: {reg_rows} R²={reg_r2} adj={reg_r2adj} F={reg_f} Fp={reg_fp} "
    f"DW={reg_dw} BPp={reg_bp}"
)

# --- §6.2 response_surface（Web 口径）---
_res62 = web_run("response_surface", df_raw, C_DEF, [C_MELT, C_MOLD], {"direction": "minimize"})
_ft62 = _res62.tables.get("model_fit")
rs_r2 = round(float(_res62.metadata.get("r_squared", float("nan"))), 3)
rs_r2adj = round(float(_res62.metadata.get("r_squared_adj", float("nan"))), 3)
rs_pred = round(float(_res62.metadata.get("optimal_z", float("nan"))), 2)
p(f"  §6.2 Web: R²={rs_r2} adj={rs_r2adj} 预测={rs_pred}")

# --- §6.7 roc_analysis（手册自述编码：合格=1）---
_df67 = df_raw.copy()
_df67[C_OK] = _df67[C_OK].map(lambda v: 0 if "不" in str(v) else 1)
_res67 = web_run("roc_analysis", _df67, C_OK, [C_MELT], {})
_pts67 = _res67.tables.get("roc_points")
roc_auc = round(float(_res67.metadata.get("auc", float("nan"))), 3)
roc_thr = round(float(_res67.metadata.get("best_threshold", float("nan"))), 1)
roc_j = round(float(_pts67["Youden_J"].max()), 3)
p(f"  §6.7 Web 合格=1: AUC={roc_auc} 阈值={roc_thr} J={roc_j}")

# --- §6.8 logistic_regression（Web 口径）---
_res68 = web_run("logistic_regression", df_raw, C_MAINT, [C_MELT, C_MOLD], {}, cats=[C_MAINT])
logit_acc = round(float(_res68.metadata.get("accuracy", float("nan"))) * 100, 1)
logit_mcf = round(float(_res68.metadata.get("mcfadden_r2", float("nan"))), 3)
p(f"  §6.8 Web: 准确率={logit_acc}% McFadden={logit_mcf}")

# --- §6.9 lasso_regression（Web 口径）---
_res69 = web_run("lasso_regression", df_raw, C_DEF, [C_MELT, C_MOLD, C_INJ], {})
lasso_alpha = round(float(_res69.metadata.get("best_alpha", float("nan"))), 4)
lasso_r2 = round(float(_res69.metadata.get("r_squared", float("nan"))), 4)
p(f"  §6.9 Web: α={lasso_alpha} R²={lasso_r2}")

# --- §7.5 process_capability 的 95%CI（Cp/Cpk/Pp/Ppk）---
_res75 = orchestrate(
    AnalysisRequest(
        task="process_capability",
        data=df_raw.copy(),
        target_col=C_DEF,
        feature_cols=[],
        params={"usl": 10, "lsl": 1},
    )
)
_pc_m = _res75.metadata
cp_ci = [round(float(_pc_m["cp_ci"][0]), 3), round(float(_pc_m["cp_ci"][1]), 3)]
cpk_ci = [round(float(_pc_m["cpk_ci"][0]), 3), round(float(_pc_m["cpk_ci"][1]), 3)]
pp_ci = [round(float(_pc_m["pp_ci"][0]), 3), round(float(_pc_m["pp_ci"][1]), 3)]
ppk_ci = [round(float(_pc_m["ppk_ci"][0]), 3), round(float(_pc_m["ppk_ci"][1]), 3)]
# §7.5 尾注：Pp 的 CI 半宽 ÷ Cp 的 CI 半宽。手册原写「n=100 时 0.80 倍」——那是
# 未给数据集的定值，实测不可复现（第二轮复核表判 ✗）。现改为「本页数据实测值 +
# 说明它随数据波动」，故此处登记的是本页同一份 metadata 现算出来的比值。
pc_hw_ratio = round(
    ((_pc_m["pp_ci"][1] - _pc_m["pp_ci"][0]) / 2) / ((_pc_m["cp_ci"][1] - _pc_m["cp_ci"][0]) / 2),
    2,
)
p(f"  §7.5 CI: Cp={cp_ci} Cpk={cpk_ci} Pp={pp_ci} Ppk={ppk_ci} 半宽比={pc_hw_ratio}")

# --- §7.6 trend_forecast（y_only，两口径相同）---
_res76 = orchestrate(
    AnalysisRequest(
        task="trend_forecast",
        data=df_raw.copy(),
        target_col=C_DEF,
        feature_cols=[],
        params={"forecast_steps": 5},
    )
)
tf_r2_new = round(float(_res76.metadata.get("r_squared", float("nan"))), 4)
tf_dw_new = round(float(_res76.metadata.get("durbin_watson", float("nan"))), 3)
tf_mape = round(float(_res76.metadata.get("mape", float("nan"))), 2)
p(f"  §7.6: R²={tf_r2_new} DW={tf_dw_new} MAPE={tf_mape}%")

# --- §7.9 outlier_consensus（Web 口径）---
_res79 = web_run("outlier_consensus", df_raw, C_DEF, [C_MELT], {})
oc_high = int(_res79.metadata.get("high_confidence_count", 0))
oc_total = int(_res79.metadata.get("total_flagged", 0))
oc_iso = int(_res79.metadata.get("isoforest_count", 0))
p(f"  §7.9 Web: 高置信={oc_high} 总标记={oc_total} IsoForest={oc_iso}")

# --- §4.8 variance_test（RAW_CAT 任务 → Web 口径 = 原帧）---
_res48 = web_run("variance_test", df_raw, C_DEF, [C_MAT], {})
_vt48 = _res48.tables.get("variance_tests")
lev_stat = round(float(_vt48.iloc[0, 1]), 3)
lev_p = round(float(_vt48.iloc[0, 2]), 3)
bar_stat = round(float(_vt48.iloc[1, 1]), 3)
bar_p = round(float(_vt48.iloc[1, 2]), 3)
p(f"  §4.8: Levene={lev_stat}/{lev_p} Bartlett={bar_stat}/{bar_p}")

# --- §5.1 cohens_kappa（RAW_CAT 任务）---
_df51 = df_raw.copy()
_df51[C_OK] = _df51[C_OK].map(lambda v: 0 if "不" in str(v) else 1)
_df51[C_APPEAR] = _df51[C_APPEAR].map(lambda v: 0 if "不" in str(v) else 1)
_res51 = web_run("cohens_kappa", _df51, "", [C_OK, C_APPEAR], {})
kappa_v = round(float(_res51.metadata.get("kappa", float("nan"))), 3)
p(f"  §5.1: Kappa={kappa_v}")

# --- §5.5 power_analysis（纯参数计算）---
power_req: dict[float, int] = {}
for _d in (0.5, 0.2, 0.8):
    _pr = orchestrate(
        AnalysisRequest(
            task="power_analysis",
            data=df_raw.copy(),
            target_col="",
            feature_cols=[],
            params={
                "effect_size": _d,
                "test_type": "ttest",
                "mode": "required_n",
                "alpha": 0.05,
                "power": 0.8,
            },
        )
    )
    _tbl = _pr.tables.get("power_result")
    power_req[_d] = int(float(_tbl.iloc[-1, 1]))
p(f"  §5.5: required_n = {power_req}")

# --- §7.3 spc_cusum（y_only）---
_res73 = web_run("spc_cusum", df_raw, C_DEF, [], {"k": 0.5, "h": 5.0})
cusum_alarms = int(_res73.metadata.get("total_alarms", 0))
p(f"  §7.3: 总报警={cusum_alarms}")

# --- §7.8 change_point（y_only）---
_res78 = web_run("change_point", df_raw, C_DEF, [], {})
_seg78 = _res78.tables.get("segment_statistics")
seg_n = int(_seg78.iloc[0, 3])
seg_mean = round(float(_seg78.iloc[0, 4]), 4)
seg_sd = round(float(_seg78.iloc[0, 5]), 4)
p(f"  §7.8: 段1 n={seg_n} 均值={seg_mean} σ={seg_sd}")

# --- §7.10 box_chart（RAW_CAT 任务）---
_res710 = web_run("box_chart", df_raw, C_DEF, [C_MAT], {"show_stats": True}, cats=[C_MAT])
_gs710 = _res710.tables.get("group_statistics")
box_stats: dict[str, tuple[int, float, float]] = {}
for _i in range(len(_gs710)):
    box_stats[str(_gs710.iloc[_i, 0])] = (
        int(_gs710.iloc[_i, 1]),
        round(float(_gs710.iloc[_i, 2]), 3),
        round(float(_gs710.iloc[_i, 4]), 3),
    )
p(f"  §7.10: {box_stats}")

# --- §7.11 spc_nonparametric（y_only）---
_res711 = web_run("spc_nonparametric", df_raw, C_DEF, [], {"side": "two-sided"})
spc_np = {
    "CL": round(float(_res711.metadata.get("cl", float("nan"))), 3),
    "UCL": round(float(_res711.metadata.get("ucl", float("nan"))), 3),
    "LCL": round(float(_res711.metadata.get("lcl", float("nan"))), 3),
}
p(f"  §7.11: {spc_np}")

# --- §8.2 median_ci（y_only）---
_res82 = web_run("median_ci", df_raw, C_DEF, [], {})
med_median = round(float(_res82.metadata.get("median", float("nan"))), 4)
med_lo = round(float(_res82.metadata.get("ci_lower", float("nan"))), 4)
med_hi = round(float(_res82.metadata.get("ci_upper", float("nan"))), 4)
p(f"  §8.2: 中位数={med_median} CI=[{med_lo}, {med_hi}]")

# --- §8.3 gage_rr（非 RAW_CAT → Web 口径中位数填充）---
_res83 = web_run(
    "gage_rr",
    df_raw,
    C_DEF,
    ["模具编号", "检验员"],
    {"part_col": "模具编号", "operator_col": "检验员"},
)
gage_grr_sv = round(float(_res83.metadata.get("grr_sv", float("nan"))), 1)
gage_ndc = int(_res83.metadata.get("ndc", -1))
p(f"  §8.3: %GRR={gage_grr_sv} ndc={gage_ndc}")

# --- §8.5 survival_analysis（RAW_CAT 任务）---
_res85 = web_run("survival_analysis", df_raw, C_DEF, [C_MAINT], {}, cats=[C_MAINT])
surv_median = float(_res85.metadata.get("median_survival", float("nan")))
p(f"  §8.5: 中位寿命={surv_median}")

# --- §7.5 口径表（20 批 × 5 件；配方 + seed=0 由手册 07-spc.md 明写）---
_s75_rng = np.random.default_rng(0)
_s75_rows: list[dict] = []
for _b in range(20):
    _mu = _s75_rng.normal(50, 2.0)  # 批间 sd=2.0
    _s75_rows += [{"批": f"B{_b:02d}", "值": _mu + _s75_rng.normal(0, 0.4)} for _ in range(5)]
_s75_df = pd.DataFrame(_s75_rows)
s75_table: dict[str, dict[str, float]] = {}
for _tag, _params in (
    ("移动极差", {"usl": 56, "lsl": 44}),
    ("按列池化", {"usl": 56, "lsl": 44, "subgroup_col": "批"}),
):
    _r75 = orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=_s75_df,
            target_col="值",
            feature_cols=[],
            params=_params,
        )
    )
    _m75 = _r75.metadata
    s75_table[_tag] = {
        "σ_within": round(float(_m75["sigma_within"]), 4),
        "Cp": round(float(_m75["cp"]), 3),
        "Cpk": round(float(_m75["cpk"]), 3),
        "Pp": round(float(_m75["pp"]), 3),
        "Ppk": round(float(_m75["ppk"]), 3),
    }
p(f"  §7.5 口径表: {s75_table}")

# --- §10 排错 FAQ 的两个阈值 ---
_s10_rng = np.random.default_rng(11)
_s10_rows: list[dict] = []
for _g in range(60):  # 60 组 > 50 上限；组均值递增 → 显著 → 走事后检验分支
    _s10_rows += [{"y": 5 + 0.5 * _g + _v, "g": f"G{_g:02d}"} for _v in _s10_rng.normal(0, 1, 10)]
_res10 = orchestrate(
    AnalysisRequest(
        task="anova",
        data=pd.DataFrame(_s10_rows),
        target_col="y",
        feature_cols=["g"],
        params={"alpha": 0.05},
    )
)
_tukey_cap = None
for _m10 in _res10.messages:
    _mt10 = re.search(r"超过事后检验上限\((\d+)\)", str(_m10))
    if _mt10:
        _tukey_cap = int(_mt10.group(1))
faq_upload_mb = int(config.UPLOAD_MAX_BYTES / 1024 / 1024)
p(f"  §10: Tukey 上限={_tukey_cap}（解析自引擎消息）上传上限={faq_upload_mb} MB")

# ────────────────────────────────────────────────────────
# FINAL COMPARISON REPORT
# ────────────────────────────────────────────────────────
p()
p()
p("=" * 100)
p("FINAL COMPARISON REPORT")
p("=" * 100)
p()


def rpt(analysis, value_name, manual, actual=None, tolerance=0.001, ok=None):
    """Report a single comparison.

    ok 由调用方判定（True/False）时优先采用——VIF 的手册记录是区间声明
    （"~1.002-1.004"），字符串全等比较恒 DIFF（第二轮 #1 修复）；
    未传 ok 时回退旧逻辑（字符串全等 / 数值容差）。
    """
    global fail_count
    if ok is not None:
        match = "OK" if ok else "DIFF"
        disp = f"{float(actual):.4f}" if isinstance(actual, (int, float)) else str(actual)
    elif actual is None:
        # 审查 2026-09-21 G-2：原为固定 ("N/A", "N/A")——而失败判定是
        # `match not in ("OK", "N/A")`，于是「手册侧有 CLAIM 值、但引擎不再
        # 产出该值」被静默放过（门禁照常 exit 0）。改由 claims_gate 区分两种缺失。
        disp, match = classify_missing(manual)
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
    # 审查 2026-09-06 F-D1：数值 CLAIM 登记（含 N/A 场景——手册侧有值才对）
    if isinstance(manual, (int, float)) and not isinstance(manual, bool):
        CLAIM_LOG.append((analysis, value_name, manual))
    # 审查 2026-09-01 G-1：非 OK/N/A 计为失败（DIFF/ERR）
    if match not in ("OK", "N/A"):
        fail_count += 1


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
# 审查 2026-09-24（第三轮复核 P2-4）：独立双样本 t 检验默认改为 Welch
# （新增 Levene 方差齐性检验 + Welch–Satterthwaite 自由度），手册 §4.3 的统计量
# 随之由 Student 口径 12.60 变为 Welch 口径 10.92。参考值同步，容差不变。
rpt("hypothesis_test", "t statistic", 10.92, ht_stat, 0.05)
rpt("hypothesis_test", "p value", 0.0000, ht_p, 0.001)
# Extract group means from ds table
for i in range(len(ds)):
    grp = str(ds.iloc[i, 0])
    mv = float(ds.iloc[i, 2])
    if "否" in grp:
        rpt("hypothesis_test", "No group mean", 4.405, round(mv, 4), 0.005)
    elif "是" in grp:
        rpt("hypothesis_test", "Yes group mean", 2.891, round(mv, 4), 0.005)

p()
p("--- 4.4 DECISION_TREE ---")
for factor, short, claim in [
    (C_COOL, "冷却时间", 0.194),
    (C_MELT, "熔体温度", 0.106),
    (C_MOLD, "模具温度", 0.049),
    (C_INJ, "注射压力", 0.004),
]:
    actual = dt_perm.get(factor)
    rpt("decision_tree", f"{short} perm", claim, actual, 0.01 if claim > 0.05 else 0.005)

p()
p("--- 4.5 VIF ---")
for factor, short in [
    (C_MELT, "VIF 熔体温度"),
    (C_MOLD, "VIF 模具温度"),
    (C_INJ, "VIF 注射压力"),
    (C_COOL, "VIF 冷却时间"),
]:
    actual = vif_vals.get(factor)
    # 审查 2026-09-21 E1-1：原为单条泛化字符串 CLAIM "~1.002-1.004" + 硬编码窗口
    # [1.0, 1.005]（宽 0.005，比手册 3 位小数精度宽 5 倍），且字符串**不进 CLAIM_LOG**
    # （rpt 仅登记 int/float）→ 手册新鲜度门禁对这 4 条完全失明。
    # 现改为逐因子数值 CLAIM（与手册 §4.5 表逐行一致）+ 容差 0.001。
    manual_vif = VIF_MANUAL_CLAIMS.get(factor)
    if actual is not None and manual_vif is not None:
        rpt("vif", short, manual_vif, actual, VIF_CLAIM_TOLERANCE)

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
    if "cpk" in key_lower and "ppk" not in key_lower and "ci" not in key_lower:
        rpt("process_capability", f"Cpk ({key})", 0.923, round(val, 4), 0.01)
    elif (
        "cp" in key_lower
        and "cpk" not in key_lower
        and "pp" not in key_lower
        and "ci" not in key_lower
    ):
        rpt("process_capability", f"Cp ({key})", 1.279, round(val, 4), 0.01)

p()
p("--- 7.6 TREND_FORECAST ---")
rpt("trend_forecast", "RMSE", 1.2415, round(tf_rmse, 4), 0.001)

p()
p("--- 8.1 BOOTSTRAP_CI ---")
rpt("bootstrap_ci", "点估计", 4.2491, round(bc_point, 4), 0.001)
rpt("bootstrap_ci", "CI 下限", 4.1740, round(bc_lower, 4), 0.001)
rpt("bootstrap_ci", "CI 上限", 4.3244, round(bc_upper, 4), 0.001)

p()
p("--- 6.12 INVERSE_SOLVE ---")
# 手册 §6.12 model_equations 前向方程（独立 OLS 复核；引擎 linear 与 raw OLS 等价）
rpt("inverse_solve", "方程截距", 6.334, round(iv_intercept, 4), 0.001)
rpt("inverse_solve", "熔体温度系数", -0.008057, round(iv_coef_melt, 6), 5e-6)
rpt("inverse_solve", "模具温度系数", -0.007928, round(iv_coef_mold, 6), 5e-6)
rpt("inverse_solve", "LOO R²", -0.002, round(iv_loo_r2, 4), 0.001)

p()
p("--- 5.3 / 5.4 分布特征与正态性（审查 2026-10-09 P0-10 新增）---")
# 背景：手册 §5.3 的偏度/峰度曾长期写 0.61/0.48（实测 0.898/1.881），§5.4 曾写
# 「2/2 列满足正态性」（实测 raw 1/2、web 0/2）—— 两处都不在上述任何 CLAIM 的覆盖内，
# 故 35 条 CLAIM 全绿也拦不住。此处补登记，把它们纳入手册新鲜度门禁。
_df53, _ = preprocess_numeric(df_raw, [])
_res53 = orchestrate(
    AnalysisRequest(
        task="distribution_summary", data=_df53, target_col=C_DEF, feature_cols=[], params={}
    )
)
_d53 = (_res53.metadata or {}).get("descriptive") or {}
rpt("distribution_summary", "偏度", 0.898, round(float(_d53.get("偏度", float("nan"))), 4), 0.001)
rpt("distribution_summary", "峰度", 1.881, round(float(_d53.get("峰度", float("nan"))), 4), 0.001)

_df54, _feat54 = preprocess_numeric(df_raw, [C_MELT])
_res54 = orchestrate(
    AnalysisRequest(
        task="normality_check",
        data=_df54,
        target_col=C_DEF,
        feature_cols=_feat54,
        params={},
    )
)
# 手册 §5.4 明确取 **Web 口径**（缺失值中位数填充后 n=1000）：实测「0/2 列满足正态性」
_nt = _res54.tables.get("normality_results")
_n_normal = 0
if _nt is not None and "正态性" in _nt.columns:
    _n_normal = sum(1 for v in _nt["正态性"].tolist() if str(v).startswith("正态"))
rpt("normality_check", "满足正态列数(web 口径)", 0, _n_normal, 0.5)

# ════════════════════════════════════════════════════════════
# 第二轮全量审查（维度 F）补充 CLAIM：此前**零覆盖**的手册节
# 每个 value_name 都必须在 manual_claims_freshness.py 同时登记
# ANCHOR_PATTERNS（行锚点）+ VALUE_CAPTURE_PATTERNS（逐值捕获）——
# 否则新鲜度门禁直接判 FAIL（P1-5 收紧策略）。
# ════════════════════════════════════════════════════════════
p()
p("--- 3.1 示例数据前 5 行预览（逐格；手册表 = df.head(5)）---")
for _key in sorted(PREVIEW_MANUAL):
    _ri, _col = _key
    rpt("manual_preview", f"{_ri}行·{_col}", PREVIEW_MANUAL[_key], PREVIEW_ACTUAL.get(_key), 5e-7)
for _key in sorted(PREVIEW_ACTUAL_NAN):
    if not PREVIEW_ACTUAL_NAN[_key]:
        continue
    _ri, _col = _key
    rpt("manual_preview", f"{_ri}行·{_col}", "NaN", "NaN")

p()
p("--- 4.4 DECISION_TREE 训练/CV R² 与 Gini/排列 std（Web 口径）---")
rpt("decision_tree", "训练 R²", 0.116, dt_train_r2, 0.001)
rpt("decision_tree", "CV R²", -0.107, dt_cv_r2, 0.001)
# 手册 §4.4 表的 Gini / 排列重要性 std 两列快照（逐行；列内 0.011/0.012 等近值
# 靠 manual_claims_freshness 的行锚点 + 逐列捕获区分）
for _f, _short, _gini, _std in (
    (C_COOL, "冷却时间", 0.463, 0.011),
    (C_MELT, "熔体温度", 0.330, 0.012),
    (C_MOLD, "模具温度", 0.184, 0.010),
    (C_INJ, "注射压力", 0.023, 0.003),
):
    rpt("decision_tree", f"{_short} Gini", _gini, dt_gini.get(_f), 0.001)
    rpt("decision_tree", f"{_short} perm std", _std, dt_perm_std.get(_f), 0.001)

p()
p("--- 4.8 VARIANCE_TEST ---")
rpt("variance_test", "Levene 统计量", 0.204, lev_stat, 0.001)
rpt("variance_test", "Levene p", 0.936, lev_p, 0.001)
rpt("variance_test", "Bartlett 统计量", 1.747, bar_stat, 0.001)
rpt("variance_test", "Bartlett p", 0.782, bar_p, 0.001)

p()
p("--- 5.1 COHENS_KAPPA ---")
rpt("cohens_kappa", "Kappa", -0.009, kappa_v, 0.001)

p()
p("--- 5.2 CRONBACH_ALPHA（Web 口径）---")
rpt("cronbach_alpha", "α", 0.031, cron_alpha, 0.001)
rpt("cronbach_alpha", "n", 1000, cron_n, 0.5)

p()
p("--- 5.5 POWER_ANALYSIS（required_n）---")
for _d, _short, _n_manual in (
    (0.5, "d=0.5 每组样本量", 64),
    (0.2, "d=0.2 每组样本量", 394),
    (0.8, "d=0.8 每组样本量", 26),
):
    rpt("power_analysis", _short, _n_manual, power_req.get(_d), 0.5)

p()
p("--- 6.1 REGRESSION（Web 口径）---")
for _name, _short, _spec in (
    ("const", "const", (6.105, 1.115, 5.48, 0.000)),
    ("熔体温度", "熔体温度", (-0.007, 0.005, -1.43, 0.153)),
    ("注射压力", "注射压力", (-0.007, 0.005, -1.47, 0.142)),
    ("冷却时间", "冷却时间", (0.011, 0.010, 1.09, 0.277)),
):
    _row = reg_rows.get(_name, {})
    for _k, _lit, _tol in zip(
        ("系数", "标准误", "t值", "p值"),
        _spec,
        (0.001, 0.001, 0.005, 0.001),
        strict=True,
    ):
        rpt("regression", f"{_short} {_k}", _lit, _row.get(_k), _tol)
rpt("regression", "R²", 0.0058, reg_r2, 0.0001)
rpt("regression", "调整R²", 0.0028, reg_r2adj, 0.0001)
rpt("regression", "F", 1.94, reg_f, 0.005)
rpt("regression", "F p", 0.122, reg_fp, 0.001)
rpt("regression", "DW", 1.976, reg_dw, 0.001)
rpt("regression", "BP p", 0.804, reg_bp, 0.001)

p()
p("--- 6.2 RESPONSE_SURFACE（Web 口径）---")
rpt("response_surface", "R²", 0.016, rs_r2, 0.001)
rpt("response_surface", "调整R²", 0.011, rs_r2adj, 0.001)
rpt("response_surface", "最优预测值", 3.52, rs_pred, 0.005)

p()
p("--- 6.7 ROC_ANALYSIS（手册约定编码：合格=1）---")
rpt("roc_analysis", "AUC", 0.511, roc_auc, 0.001)
rpt("roc_analysis", "最佳阈值", 202.6, roc_thr, 0.05)
rpt("roc_analysis", "Youden J", 0.112, roc_j, 0.001)

p()
p("--- 6.8 LOGISTIC_REGRESSION（Web 口径）---")
rpt("logistic_regression", "准确率(%)", 89.7, logit_acc, 0.05)
rpt("logistic_regression", "McFadden R²", 0.004, logit_mcf, 0.0005)

p()
p("--- 6.9 LASSO_REGRESSION（Web 口径）---")
rpt("lasso_regression", "α", 0.0022, lasso_alpha, 0.00005)
rpt("lasso_regression", "R²", 0.0071, lasso_r2, 0.00005)

p()
p("--- 7.3 SPC_CUSUM ---")
rpt("spc_cusum", "总报警", 9, cusum_alarms, 0.5)

p()
p("--- 7.5 PROCESS_CAPABILITY 95%CI（F02：手册曾偏窄 22%）---")
rpt("process_capability", "Cp CI 下限", 1.207, cp_ci[0], 0.0005)
rpt("process_capability", "Cp CI 上限", 1.351, cp_ci[1], 0.0005)
rpt("process_capability", "Cpk CI 下限", 0.867, cpk_ci[0], 0.0005)
rpt("process_capability", "Cpk CI 上限", 0.979, cpk_ci[1], 0.0005)
rpt("process_capability", "Pp CI 下限", 1.155, pp_ci[0], 0.0005)
rpt("process_capability", "Pp CI 上限", 1.260, pp_ci[1], 0.0005)
rpt("process_capability", "Ppk CI 下限", 0.828, ppk_ci[0], 0.0005)
rpt("process_capability", "Ppk CI 上限", 0.915, ppk_ci[1], 0.0005)
rpt("process_capability", "尾注 Pp/Cp 半宽比", 0.74, pc_hw_ratio, 0.005)

p()
p("--- 7.6 TREND_FORECAST（R²/DW/MAPE）---")
rpt("trend_forecast", "R²", 0.0002, tf_r2_new, 0.00005)
rpt("trend_forecast", "DW", 1.979, tf_dw_new, 0.001)
rpt("trend_forecast", "MAPE", 24.82, tf_mape, 0.005)

p()
p("--- 7.8 CHANGE_POINT ---")
rpt("change_point", "段1 样本数", 1000, seg_n, 0.5)
rpt("change_point", "段1 均值", 4.2491, seg_mean, 0.0005)
rpt("change_point", "段1 标准差", 1.2422, seg_sd, 0.0005)

p()
p("--- 7.9 OUTLIER_CONSENSUS（Web 口径）---")
rpt("outlier_consensus", "高置信异常", 23, oc_high, 0.5)
rpt("outlier_consensus", "总标记", 59, oc_total, 0.5)
rpt("outlier_consensus", "IsoForest 计数", 50, oc_iso, 0.5)

p()
p("--- 7.10 BOX_CHART group_statistics ---")
for _g, _n_manual, _mean_manual, _sd_manual in (
    ("ABS", 315, 4.217, 1.220),
    ("PA6", 206, 4.350, 1.241),
    ("PA66", 85, 4.190, 1.295),
    ("PC", 159, 4.165, 1.191),
    ("PP", 235, 4.282, 1.290),
):
    _n, _mean, _sd = box_stats.get(_g, (0, 0.0, 0.0))
    rpt("box_chart", f"{_g} 样本量", _n_manual, _n, 0.5)
    rpt("box_chart", f"{_g} 均值", _mean_manual, _mean, 0.001)
    rpt("box_chart", f"{_g} 标准差", _sd_manual, _sd, 0.001)

p()
p("--- 7.11 SPC_NONPARAMETRIC ---")
rpt("spc_nonparametric", "CL", 4.073, spc_np["CL"], 0.001)
rpt("spc_nonparametric", "UCL", 9.879, spc_np["UCL"], 0.001)
rpt("spc_nonparametric", "LCL", 1.679, spc_np["LCL"], 0.001)

p()
p("--- 8.2 MEDIAN_CI ---")
rpt("median_ci", "中位数", 4.0130, med_median, 0.00005)
rpt("median_ci", "CI 下限", 3.9220, med_lo, 0.00005)
rpt("median_ci", "CI 上限", 4.1210, med_hi, 0.00005)

p()
p("--- 8.3 GAGE_RR ---")
rpt("gage_rr", "%GRR", 99.5, gage_grr_sv, 0.05)
rpt("gage_rr", "ndc", 0, gage_ndc, 0.5)

p()
p("--- 8.5 SURVIVAL_ANALYSIS ---")
rpt("survival_analysis", "中位寿命", 9.6, round(surv_median, 1), 0.05)

p()
p("--- 7.5 口径表（20 批 × 5 件，seed=0；原「无法逐位复现」，现纳入门禁）---")
for _tag, _spec75 in (
    ("移动极差", {"σ_within": 0.8069, "Cp": 2.479, "Cpk": 2.475, "Pp": 0.832, "Ppk": 0.831}),
    ("按列池化", {"σ_within": 0.3678, "Cp": 5.438, "Cpk": 5.430, "Pp": 0.832, "Ppk": 0.831}),
):
    _actual75 = s75_table.get(_tag, {})
    for _k, _lit in _spec75.items():
        rpt(
            "process_capability",
            f"口径表 {_tag} {_k}",
            _lit,
            _actual75.get(_k),
            0.0005 if _k == "σ_within" else 0.001,
        )

p()
p("--- 10 排错 FAQ 的两个阈值 ---")
rpt("manual_faq", "Tukey 水平上限", 50, _tukey_cap, 0.5)
rpt("manual_faq", "上传大小上限(MB)", 50, faq_upload_mb, 0.5)

p()
p("=" * 100)
p("VERIFICATION COMPLETE")
p("=" * 100)

# ── 手册新鲜度校验（审查 2026-09-06 F-D1）：CLAIM 快照 ↔ user-manual/（按章拆页） ──
from manual_claims_freshness import check_manual_freshness  # noqa: E402

p()
p("--- 手册新鲜度校验（CLAIM 快照 ↔ user-manual/（按章拆页））---")
# 手册自 2026-09-18 起按章拆页：合并目录下全部编号章节（NN-*.md），
# 保持与 §4.1/§7.5 等章节锚定的解析口径不变（index.md 不含 ### 章节号，不参与）
import glob as _glob  # noqa: E402


def _read_manual_text() -> str:
    _manual_dir = os.path.join(PROJECT_ROOT, "docs", "user-manual")
    _parts: list[str] = []
    for _p in sorted(_glob.glob(os.path.join(_manual_dir, "[0-9]*.md"))):
        with open(_p, encoding="utf-8") as _f:
            _parts.append(_f.read())
    return "\n".join(_parts)


_manual_text = _read_manual_text()
if not _manual_text:
    print("[FAIL] 未找到 docs/user-manual/[0-9]*.md 章节文件")
    sys.exit(1)
_problems = check_manual_freshness(_manual_text, CLAIM_LOG)
for _prob in _problems:
    p(f"  [DIFF] {_prob}")
p(f"  校验数值 CLAIM {len(CLAIM_LOG)} 条，问题 {len(_problems)} 条")
fail_count += len(_problems)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(f"Output: {OUTPUT}")
# 审查 2026-09-01 G-1：发布前门禁——任一项 DIFF/ERR 即以非零退出码告警
# 审查 2026-09-05 E2：GBK 控制台打印 ❌ 会触发 UnicodeEncodeError，门禁标记用 ASCII
# 审查 2026-10-09 R2 的 G-3：本脚本**没有 `if __name__ == "__main__"` guard**
# （主体是模块级代码）。任何以 `runpy`/`spec_from_file_location` 加载它的调用方
# 都会被这个 `sys.exit` **抢走退出码** —— 实测 `manual_claims_freshness.py` 的
# 独立入口曾因此 **exit 0 且零结论输出**（惰性门禁，比没有门禁更危险）。
# 调用方侧已用"自建命名空间 + 捕获 SystemExit"围住；此处再加一层：
# 分支结果改为**抛出 SystemExit**（由调用方决定处置），只有直接运行时才真正退出。
# 完整修法（把主体收进 `main()`）属较大重构，单独立项。
if fail_count:
    print(f"\n[FAIL] {fail_count} 项与手册不一致（详见 {OUTPUT}），门禁失败")
    raise SystemExit(1)
print("Done.")
# ⚠️ 必须用 `globals().get("__name__")` 而不是裸 `__name__`：调用方
# （`manual_claims_freshness.py::_load_claims_local`）用 `compile()+exec()` 到
# **自建命名空间**加载本文件，该命名空间里没有 `__name__` —— 裸用它会在成功路径上
# 抛 `NameError`，把"校验通过"变成"未能加载 CLAIM"（我第一版就是这么写的，实测踩到）。
if globals().get("__name__") == "__main__":
    raise SystemExit(0)
