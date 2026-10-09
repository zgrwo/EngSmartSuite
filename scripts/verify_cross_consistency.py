"""
全量方法交叉验证: Web UI 路径 ↔ Python 直接路径 ↔ 用户手册记录值

任务清单随 TASK_REGISTRY 派生（数量唯一源），不再硬编码方法总数。

验证维度:
1. status 一致性 (ok/error)
2. summary 一致性
3. tables 键名一致性
4. figures 数量一致性
5. 用户手册记录的关键数值是否与实际输出一致
"""

import json
import os
import re
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
np.random.seed(42)

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import preprocess_data
from smartsuite.services.orchestrator import RAW_CAT_TASKS, TASK_REGISTRY, orchestrate

# ── 加载测试数据 ──
df_raw = pd.read_excel("tests/data/injection_process.xlsx")
print(f"数据: {df_raw.shape[0]}行 × {df_raw.shape[1]}列")

# ── 用户手册记录值 (基于 tests/data/injection_process.xlsx, seed=42) ──
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

#: 手册数值检查的**登记总数**（分母守恒，审查 2026-10-09 P1-12）。
#:
#: 审查实测（I10b）：把引擎 `correlation` 强制 `status="error"`（CLI/Web 两路径同错）
#: 后，`manual_checks_total` 只在 `status_a == "ok"` 时自增 —— 分母由 11 静默缩为 10，
#: 输出仍是 `*** ALL PASSED ***`、exit 0（`11/11` → `10/10`），"总数缩水不可见"。
#: 现分母取自**登记条目数常量**，不随实际跑通的任务数变化；未产出可核对结果的
#: 登记任务直接计为失败（见下方 `status_a != "ok"` 分支）。
MANUAL_CHECKS_TOTAL = len(MANUAL_EXPECTATIONS)

# ── 手册覆盖度报告（审查 2026-10-09 G-7）──────────────────────────────────────
#
# 问题：本门禁在 `quality.yml` 里的 job 名是「手册数值一致性」，但它只校验
# `MANUAL_EXPECTATIONS` 登记的 **11/42** 个任务；`process_capability` 不在其中
# —— 实测把手册 §7.5 的 `Cp 1.279` 改成 `1.100` 后本脚本仍 `*** ALL PASSED ***`
# / exit 0（真实漂移由 `verify_manual_claims` 兜住，故定级 P2 而非 P1）。
# 分母本身守恒（不是"失败让通过率变好看"），问题是**覆盖面被 job 名高估**。
#
# 处置：① 输出与 job 名一律写实（"登记 N 项 / 手册含数值结果的任务 M 项"）；
#      ② 登记表**只增不减**（`MANUAL_REGISTRY_FLOOR`，防有人删条目把门禁调松）；
#      ③ 登记项必须真的出现在手册"含数值结果"的任务节里（防登记到不存在的节）。
MANUAL_EXPECTATIONS_COUNT = len(MANUAL_EXPECTATIONS)

#: 登记表条数下限（**只准增加**）。删掉一条登记即 FAIL —— 否则"门禁变松"无声无息。
MANUAL_REGISTRY_FLOOR = 11

#: 手册中"含数值结果"的任务节数下限（实测 28/42，2026-10-09）。
#: 低于此值说明手册被大幅删减（或检测口径失效），两种情况都该人工复核。
MANUAL_SECTION_FLOOR = 28

#: 判定"含数值结果"的口径（与 CLAIM/锚点门禁同一思路：只认**具体数值**）：
#:   · 表格行：≥2 列且某个非首列单元格含 `数字.两位以上小数`；
#:   · 列表/散文行：含 `数字.三位以上小数`（两位的常出现在章节编号/参数说明里）。
_MANUAL_TASK_HEADING_RE = re.compile(r"^###\s+\d+(?:\.\d+)*\s*(.*)$", re.MULTILINE)
_MANUAL_ANY_HEADING_RE = re.compile(r"^#{2,3}\s", re.MULTILINE)
_MANUAL_TASK_NAME_RE = re.compile(r"`([a-z0-9_]+)`")
_MANUAL_DEC2_RE = re.compile(r"\d+\.\d{2,}")
_MANUAL_DEC3_RE = re.compile(r"\d+\.\d{3,}")
#: 这些小节标题下的数字不算"数值结果"（解读/备注/参数说明里的数字是示例或散文）
_MANUAL_NON_RESULT_HINTS = ("解读", "备注", "注意", "提示", "参数选择", "示例图片")

#: 登记的检查项中**其判据不是手册里写出的数值**的那些（键 → 理由）。
#:
#: 这类登记项对不上"手册含数值结果的任务节"是**预期**的：它们校验的是判定/口径，
#: 不是手册数值。分开登记是为了让"登记项 ⊆ 手册含数值节"这条断言保持严格
#: —— 其余登记项若能对不上，说明登记到了一个不会产出可核对结果的位置（静默空转）。
MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC: dict[str, str] = {
    "outlier_consensus": (
        "判据是**高置信比例落在 1–10% 区间**（统计口径校验），不是手册某处写死的"
        "数值；§7.9 手册节为图表+方法说明，无 `≥0.01` 精度的结果值可核对"
    ),
}


def _manual_task_sections(manual_dir) -> dict[str, str]:
    """`### N.M 名称 (\\`task\\`)` 小节 → {任务名: 小节正文}（只收注册任务）。"""
    from pathlib import Path as _Path

    sections: dict[str, str] = {}
    for path in sorted(_Path(manual_dir).glob("[0-9]*.md")):
        text = path.read_text(encoding="utf-8")
        marks = list(_MANUAL_TASK_HEADING_RE.finditer(text))
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            nxt = _MANUAL_ANY_HEADING_RE.search(text, mark.end())
            if nxt:
                end = min(end, nxt.start())
            for task in _MANUAL_TASK_NAME_RE.findall(mark.group(1)):
                if task in TASK_REGISTRY:
                    sections[task] = text[mark.start() : end]
    return sections


def _manual_sections_with_numbers(manual_dir) -> tuple[set[str], int]:
    """返回 (含数值结果的任务名集合, 手册任务节总数)。"""
    sections = _manual_task_sections(manual_dir)
    with_numbers = {t for t, body in sections.items() if _manual_has_numeric_result(body)}
    return with_numbers, len(sections)


def _registered_manual_tasks() -> list[str]:
    """`MANUAL_EXPECTATIONS` 登记的任务名（供包装测试核对覆盖面对不对得上手册）。"""
    return sorted(MANUAL_EXPECTATIONS)


def _manual_sections_total(manual_dir) -> int:
    """手册里映射到注册任务的小节总数（供包装测试断言手册结构未变）。"""
    return len(_manual_task_sections(manual_dir))


def _manual_has_numeric_result(body: str) -> bool:
    """该手册节是否含数值结果行（口径见 `_MANUAL_DEC2_RE` 注释）。"""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("!["):  # 图片行
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and any(_MANUAL_DEC2_RE.search(c) for c in cells[1:]):
                return True
        elif _MANUAL_DEC3_RE.search(line) and not any(
            hint in line for hint in _MANUAL_NON_RESULT_HINTS
        ):
            return True
    return False


#: 允许 `status != "ok"` 的任务（键 → 理由）。**默认空**：42 个任务在本数据集
#: （`tests/data/injection_process.xlsx`，seed=42）上必须全部 `status=ok` —— 与
#: ci.yml「全量一致性校验（42 任务 status=ok 冒烟门禁）」同一口径。
#:
#: 审查 2026-10-09 P1-12：此前任一任务整体 error 时 A/B 同错 → status/tables/figures
#: 三项均无 mismatch → `*** ALL PASSED ***` + exit 0，任务失败完全不可见。
#: 需长期允许某任务失败时，请在此具名登记**理由**（而不是把门禁调松）。
ALLOWED_NON_OK_TASKS: dict[str, str] = {}

# ── 全量方法的测试用例定义（随 TASK_REGISTRY，不硬编码总数） ──
# (task, target_col, feature_cols, categoricals, params)
TEST_CASES = [
    # === 要因筛选 ===
    ("correlation", "不良率", ["熔体温度", "模具温度", "注射压力", "冷却时间"], [], {}),
    ("anova", "不良率", ["原料类型"], ["原料类型"], {"alpha": 0.05}),
    ("hypothesis_test", "不良率", ["保养日"], ["保养日"], {"test": "ttest_ind"}),
    (
        "decision_tree",
        "不良率",
        ["熔体温度", "模具温度", "注射压力", "冷却时间"],
        [],
        {"max_depth": 5},
    ),
    ("vif", "", ["熔体温度", "模具温度", "注射压力", "冷却时间"], [], {}),
    ("contingency", "保养日", ["原料类型"], ["保养日", "原料类型"], {}),
    ("proportion_ci", "首件合格", [], [], {}),
    ("variance_test", "不良率", ["原料类型"], ["原料类型"], {"group_col": "原料类型"}),
    # === 信度诊断 ===
    ("cohens_kappa", "", ["首件合格", "外观检查"], [], {}),
    ("cronbach_alpha", "", ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("distribution_summary", "不良率", [], [], {}),
    ("normality_check", "不良率", ["熔体温度"], [], {}),
    (
        "power_analysis",
        "",
        [],
        [],
        {"mode": "required_n", "test_type": "ttest", "effect_size": 0.5},
    ),
    # === 建模优化 ===
    ("regression", "不良率", ["熔体温度", "注射压力", "冷却时间"], [], {}),
    ("response_surface", "不良率", ["熔体温度", "模具温度"], [], {"direction": "minimize"}),
    (
        "grid_search",
        "不良率",
        ["熔体温度"],
        [],
        {"ranges": {"熔体温度": (180, 220)}, "n_points": 10},
    ),
    (
        "multi_objective",
        "不良率",
        ["熔体温度", "模具温度"],
        [],
        {
            "objectives": [
                {"col": "不良率", "direction": "minimize"},
                {"col": "拉伸强度", "direction": "maximize"},
            ]
        },
    ),
    (
        "inverse_solve",
        "",
        [],
        [],
        {
            "incoming_cols": "熔体温度",
            "variable_cols": "模具温度",
            "output_cols": "不良率",
            "model": "linear",
        },
    ),
    ("doe_analysis", "不良率", ["熔体温度", "模具温度", "注射压力"], [], {}),
    (
        "doe_design",
        "",
        [],
        [],
        {
            "method": "full_factorial",
            "factors": [{"name": "A", "levels": [1, 2]}, {"name": "B", "levels": [1, 2]}],
            "randomize": False,
        },
    ),
    ("roc_analysis", "首件合格", ["熔体温度"], [], {}),
    ("logistic_regression", "保养日", ["熔体温度", "模具温度"], ["保养日"], {}),
    ("lasso_regression", "不良率", ["熔体温度", "模具温度", "注射压力"], [], {}),
    ("robust_regression", "不良率", ["熔体温度"], [], {}),
    ("quantile_regression", "不良率", ["熔体温度"], [], {"quantile": 0.5}),
    # === 过程监控 ===
    ("spc_xbar", "不良率", [], [], {}),  # 无X列→顺序索引, 无group_col→单一序列
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
    (
        "gage_rr",
        "不良率",
        ["模具编号", "检验员"],
        ["模具编号", "检验员"],
        {"part_col": "模具编号", "operator_col": "检验员"},
    ),
    ("tolerance_interval", "不良率", [], [], {}),
    ("survival_analysis", "不良率", ["设备报警"], [], {}),  # 设备报警是0/1数值列，适合作事件指示
    ("scatter_plot", "不良率", ["熔体温度"], [], {"fit": "linear"}),
]

assert {c[0] for c in TEST_CASES} == set(TASK_REGISTRY), (
    f"TEST_CASES 任务名须与 TASK_REGISTRY 一一对应，缺失: {sorted(set(TASK_REGISTRY) - {c[0] for c in TEST_CASES})}，"
    f"多余: {sorted({c[0] for c in TEST_CASES} - set(TASK_REGISTRY))}"
)

# 分母守恒（审查 2026-10-09 P1-12）：登记了手册期望的任务必须都在 TEST_CASES 里被跑到，
# 否则它永远不会进入循环、永远不会被计为失败（分母虚高且失败不可见）。
_unregistered = sorted(set(MANUAL_EXPECTATIONS) - {c[0] for c in TEST_CASES})
assert not _unregistered, f"MANUAL_EXPECTATIONS 登记的任务不在 TEST_CASES 中: {_unregistered}"

# ── 运行验证 ──
results = []
issues = []
manual_checks_passed = 0
task_not_ok = 0

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
        params_a = dict(params)
        req_a = AnalysisRequest(
            task=task, data=df_a, target_col=target, feature_cols=features, params=params_a
        )
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
        raw_cat_tasks = RAW_CAT_TASKS
        if task in raw_cat_tasks:
            feat_b = list(features)
        else:
            cat_set = set(cats)
            df_b, feat_b, _, _, _ = preprocess_data(df_b, features, cat_set)

        params_b = dict(params)

        req_b = AnalysisRequest(
            task=task, data=df_b, target_col=target, feature_cols=feat_b, params=params_b
        )
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
    status_match = status_a == status_b
    tables_match = tables_a == tables_b
    figs_match = figs_a == figs_b

    if not status_match:
        issues.append(f"STATUS MISMATCH: {test_name}: A={status_a}, B={status_b}")
    if not tables_match:
        only_a = tables_a - tables_b
        only_b = tables_b - tables_a
        if only_a or only_b:
            issues.append(f"TABLES MISMATCH: {test_name}: only_A={only_a}, only_B={only_b}")
    if not figs_match:
        issues.append(f"FIGS MISMATCH: {test_name}: A={figs_a}, B={figs_b}")

    # ── 任务整体状态门禁（审查 2026-10-09 P1-12）──
    # A/B 同错时三项 mismatch 均为 0 → 旧口径静默全绿。任务 status 本身必须被断言。
    if status_a != "ok" and task not in ALLOWED_NON_OK_TASKS:
        task_not_ok += 1
        issues.append(
            f"NOT_OK: {test_name}: status={status_a}（未登记的非 ok 任务不得静默通过；"
            f"messages={summary_a[:80]!r}）"
        )

    # ── 用户手册值检查 ──
    manual_result = ""
    if task in MANUAL_EXPECTATIONS and status_a != "ok":
        # 分母守恒：登记了期望却没产出可核对结果 → 直接计失败（不再缩分母）
        issues.append(
            f"MANUAL: {task} 无法核对手册数值（status={status_a}）——"
            "该任务已登记手册期望，按登记分母计为失败"
        )
    if task in MANUAL_EXPECTATIONS and status_a == "ok":
        exp = MANUAL_EXPECTATIONS[task]

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
            r2 = meta_a.get("r_squared", 0)
            p = None
            anova_tbl = result_a.tables.get("anova_enhanced")
            if anova_tbl is not None and "p值" in anova_tbl.columns:
                pvals = anova_tbl["p值"].dropna()
                if len(pvals) > 0:
                    p = float(pvals.iloc[0])
            if p is not None and exp["p值范围"][0] <= p <= exp["p值范围"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS p={p:.6f} R²={r2:.4f}"
            else:
                issues.append(f"MANUAL: {task} p_value={p} not in {exp['p值范围']}")

        elif task == "hypothesis_test":
            p = meta_a.get("p_value", 1)
            es = meta_a.get("effect_label", "")
            if exp["保养日p值"][0] <= p <= exp["保养日p值"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS p={p:.6f}"
            else:
                issues.append(f"MANUAL: {task} p={p:.6f} not in range")

        elif task == "decision_tree":
            cv = meta_a.get("cv_r2")
            if cv is not None:
                manual_checks_passed += 1
                manual_result = f"PASS CV_R²={cv:.3f}"
            else:
                issues.append(f"MANUAL: {task} cv_r2 missing in metadata")

        elif task == "vif":
            vif_table = result_a.tables.get("vif_table")
            if vif_table is not None:
                max_vif = vif_table["VIF"].max()
                if exp["所有VIF"][0] <= max_vif <= exp["所有VIF"][1]:
                    manual_checks_passed += 1
                    manual_result = f"PASS max(VIF)={max_vif:.3f}"
                else:
                    issues.append(f"MANUAL: {task} max(VIF)={max_vif:.3f}")

        elif task == "contingency":
            p = meta_a.get("p_value")
            if p is not None and exp["p值"][0] <= p <= exp["p值"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS p={p:.6f}"
            else:
                issues.append(f"MANUAL: {task} p_value={p} missing or out of range")

        elif task == "proportion_ci":
            ph = meta_a.get("p_hat")
            if ph is not None and exp["点估计"][0] <= ph <= exp["点估计"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS p_hat={ph:.4f}"
            else:
                issues.append(f"MANUAL: {task} p_hat={ph} not in {exp['点估计']}")

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
            else:
                issues.append(f"MANUAL: {task} judge={judge!r} does not contain {exp['判定']!r}")

        elif task == "distribution_summary":
            bf = meta_a.get("best_fit", "")
            if exp["最佳拟合"] in bf:
                manual_checks_passed += 1
                manual_result = f"PASS best_fit={bf}"
            else:
                issues.append(
                    f"MANUAL: {task} best_fit={bf!r} does not contain {exp['最佳拟合']!r}"
                )

        elif task == "outlier_consensus":
            n = meta_a.get("n", 1000)
            hc = meta_a.get("high_confidence_count", 0)
            ratio = hc / n if n > 0 else 0
            if exp["高置信比例"][0] <= ratio <= exp["高置信比例"][1]:
                manual_checks_passed += 1
                manual_result = f"PASS high_conf={hc}/{n}={ratio:.1%}"
            else:
                issues.append(
                    f"MANUAL: {task} high_conf={hc}/{n}={ratio:.1%} not in {exp['高置信比例']}"
                )

    # ── 日志 (ASCII only for Windows GBK terminal) ──
    match_str = "OK" if (status_match and tables_match and figs_match) else "!!"
    fig_str = f"{figs_a}/{figs_b}" if figs_a == figs_b else f"{figs_a}!={figs_b}"
    print(f"  {match_str} {task:<30} status={status_a}  tables={len(tables_a)}  figs={fig_str}")

    results.append(
        {
            "task": task,
            "status_a": status_a,
            "status_b": status_b,
            "tables_match": tables_match,
            "figs_match": figs_match,
            "manual_check": manual_result,
        }
    )

# ── 汇总 ──
print()
print("=" * 70)
ok_count = sum(1 for r in results if r["status_a"] == "ok")
error_count = sum(1 for r in results if r["status_a"] == "error")
status_mismatch = sum(1 for r in results if r["status_a"] != r["status_b"])
tables_mismatch = sum(1 for r in results if not r["tables_match"])
figs_mismatch = sum(1 for r in results if not r["figs_match"])

manual_failed = MANUAL_CHECKS_TOTAL - manual_checks_passed
print(f"  总计: {len(results)} 方法")
print(f"  ok: {ok_count}  error: {error_count}")
print(f"  未登记的非 ok 任务: {task_not_ok}  ← 必须为 0（见 ALLOWED_NON_OK_TASKS）")
print(f"  status 不一致: {status_mismatch}")
print(f"  tables 不一致: {tables_mismatch}")
print(f"  figures 不一致: {figs_mismatch}")

# ── 手册覆盖度（审查 2026-10-09 G-7）──────────────────────────────────────────
# job 名曾写作"手册数值一致性"，实际只覆盖登记表里的 11 个任务 ⇒ 覆盖面被高估。
# 现如实报告：登记项 / 手册含数值结果的任务节 / 全部任务，并把"登记表只增不减"
# 与"手册不被大幅删减"两条变成退出码的一部分（不达标即 FAIL，而不是只打印）。
manual_with_numbers, manual_sections_total = _manual_sections_with_numbers(
    os.path.join(PROJECT_ROOT, "docs", "user-manual")
)
manual_cov_problems: list[str] = []
if MANUAL_EXPECTATIONS_COUNT < MANUAL_REGISTRY_FLOOR:
    manual_cov_problems.append(
        f"登记表缩水：{MANUAL_EXPECTATIONS_COUNT} < 下限 {MANUAL_REGISTRY_FLOOR}"
        f"（MANUAL_EXPECTATIONS 只准增加；删除登记项 = 把门禁调松）"
    )
if len(manual_with_numbers) < MANUAL_SECTION_FLOOR:
    manual_cov_problems.append(
        f"手册含数值结果的任务节 {len(manual_with_numbers)} < 下限 {MANUAL_SECTION_FLOOR}"
        f"（手册被删减，或数值结果检测口径失效）"
    )
not_in_manual = sorted(
    set(MANUAL_EXPECTATIONS) - manual_with_numbers - set(MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC)
)
if not_in_manual:
    manual_cov_problems.append(
        f"登记项在手册中找不到含数值结果的任务节：{not_in_manual}"
        f"（登记到了不存在的节，该检查会静默空转；确属「判据不是手册数值」的，"
        f"请登记进 MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC 并写明理由）"
    )

print(
    f"  用户手册验证: {manual_checks_passed}/{MANUAL_CHECKS_TOTAL} passed"
    f"（登记条目数常量，分母守恒）"
)
print(
    f"  手册覆盖度（G-7）: 登记 {MANUAL_EXPECTATIONS_COUNT} 项 / "
    f"手册含数值结果的任务节 {len(manual_with_numbers)} 个 / "
    f"手册任务节 {manual_sections_total} 个 / TASK_REGISTRY {len(TASK_REGISTRY)} 个"
)
print(
    "    ↳ 本门禁的名称是「手册数值一致性」，但**只校验登记表内的任务**；"
    "未登记任务的手册漂移由 verify_manual_claims.py（38 条 CLAIM）承担"
)
if manual_failed:
    print(f"    ↳ 登记项失败 {manual_failed} 项")
for prob in manual_cov_problems:
    print(f"    ↳ [FAIL] {prob}")
print()

if issues:
    print(f"  问题 ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
else:
    print("  *** ALL PASSED ***")
print("=" * 70)

# ── 机器可读报告（审查 2026-10-09 G-7）──────────────────────────────────────
# 包装测试需要一个**稳定**的口径来断言覆盖度（而不是 grep 中文输出）。
# `--json <path>` 写出判定所用的全部计数；路径默认落在 `logs/`（.gitignore 已忽略），
# 因此本选项不会污染仓库。
_json_path = None
if "--json" in sys.argv:
    _idx = sys.argv.index("--json")
    _json_path = (
        sys.argv[_idx + 1]
        if _idx + 1 < len(sys.argv) and not sys.argv[_idx + 1].startswith("-")
        else os.path.join(PROJECT_ROOT, "logs", "cross_consistency.json")
    )
    os.makedirs(os.path.dirname(_json_path), exist_ok=True)
    with open(_json_path, "w", encoding="utf-8") as _f:
        json.dump(
            {
                "tasks_total": len(results),
                "ok": ok_count,
                "error": error_count,
                "task_not_ok": task_not_ok,
                "status_mismatch": status_mismatch,
                "tables_mismatch": tables_mismatch,
                "figs_mismatch": figs_mismatch,
                "manual_checks_passed": manual_checks_passed,
                "manual_checks_total": MANUAL_CHECKS_TOTAL,
                "manual_registered": MANUAL_EXPECTATIONS_COUNT,
                "manual_registry_floor": MANUAL_REGISTRY_FLOOR,
                "manual_sections_with_numbers": len(manual_with_numbers),
                "manual_sections_total": manual_sections_total,
                "manual_section_floor": MANUAL_SECTION_FLOOR,
                "manual_checks_without_manual_numeric": MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC,
                "task_registry_size": len(TASK_REGISTRY),
                "manual_coverage_problems": manual_cov_problems,
                "issues": issues,
            },
            _f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"  JSON 报告: {_json_path}")

# 返回状态码（第二轮 #3：手册数值检查失败也计入退出码，不再被静默吞掉）
# 注（审查 2026-10-09 P3-13/G-13）：ci.yml 的 consistency job 现以
# `set -o pipefail && … > log 2>&1 || { tail -80 log; exit 1; }` 调用 ——
# `pipefail` 已在管道**之前**生效，退出码**不会**被掩码（旧注释称"会掩码退出码"
# 是 `set -o pipefail` 引入前的遗留）。截尾只影响成功时的日志长度，失败时打全明细。
# 审查 2026-09-01 G-5：收敛容差——表格/图表差异为 0 容差（此前 ≤5 表 / ≤3 图
# 与"严格"验收声明矛盾，且当前基线实测 0 差异）
# 审查 2026-10-09 P1-12：补 `task_not_ok`（任务整体 error 时 A/B 同错 → 三项 mismatch
# 均为 0，旧口径会 `*** ALL PASSED ***` + exit 0）。
# 审查 2026-10-09 G-7：补 `manual_cov_problems`（登记表缩水 / 手册被删减 /
# 登记项对不上手册节 → 一律 FAIL，不只打印）。
exit_code = (
    1
    if (
        status_mismatch > 0
        or tables_mismatch > 0
        or figs_mismatch > 0
        or manual_failed > 0
        or task_not_ok > 0
        or bool(manual_cov_problems)
    )
    else 0
)
sys.exit(exit_code)
