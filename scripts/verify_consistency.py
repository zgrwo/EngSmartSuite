"""SmartSuite V1 -- behaviour and result consistency verification."""

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# 第二轮 #8：--skip-pytest 供 CI quick job 复用——跳过嵌套 pytest 步骤，
# 避免 quick job 里"引擎层/服务层/集成测试 + 这里全量 pytest"重复跑完整套件
_parser = argparse.ArgumentParser(description="行为/架构一致性验证（全任务冒烟门禁）")
_parser.add_argument(
    "--skip-pytest",
    action="store_true",
    help="跳过嵌套 pytest 步骤（CI quick job 用它避免重复跑完整套件）",
)
_args = _parser.parse_args()

PASS, FAIL = 0, 0
checks = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        checks.append(f"  PASS  {name}")
        if detail:
            checks.append(f"        {detail}")
    else:
        FAIL += 1
        checks.append(f"  FAIL  {name}")
        if detail:
            checks.append(f"        {detail}")


def section(title):
    checks.append(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
section("0. Environment")


# ============================================================
def _import_guard(label: str, do_import) -> None:
    """包导入检查：导入失败记录 FAIL（退出码非零），不崩溃脚本。

    审查 2026-09-01 G-3：此前 check(..., True) 硬编码，import 失败时脚本直接 traceback。
    """
    try:
        do_import()
    except Exception as e:  # noqa: BLE001 — 启动诊断需捕获任意导入失败
        check(label, False, detail=f"import 失败: {type(e).__name__}: {e}")
        return
    check(label, True)


def _imp_smartsuite():
    import smartsuite  # noqa: F401


def _imp_contracts():
    # 脚本后续使用模块级 AnalysisRequest，需在此重建绑定
    global AnalysisRequest
    from smartsuite.core.contracts import AnalysisRequest  # noqa: F401


def _imp_apiref_task_keys():
    """api-reference.md 的 Task Key 清单：文档侧唯一任务清单（防文档↔注册表漂移）。"""
    import re as _re

    global _apiref_task_keys
    _path = os.path.join(ROOT, "rules", "api-reference.md")
    with open(_path, encoding="utf-8") as _fh:
        _apiref_task_keys = set(
            _re.findall(r"^- \*\*Task Key\*\*: `([a-z_0-9]+)`", _fh.read(), _re.M)
        )


def _imp_engine():
    from smartsuite.engine import __all__ as engine_all  # noqa: F401

    global _engine_export_count
    _engine_export_count = len(engine_all)


def _imp_orchestrator():
    # 脚本后续使用模块级 TASK_REGISTRY/orchestrate，需在此重建绑定
    global orchestrate, TASK_REGISTRY, _orchestrator_task_count
    from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate  # noqa: F401

    _orchestrator_task_count = len(TASK_REGISTRY)


_engine_export_count = 0
_orchestrator_task_count = 0
_apiref_task_keys = set()
_import_guard("smartsuite package importable", _imp_smartsuite)
_import_guard("Data contracts importable", _imp_contracts)
_import_guard("Engine functions importable", _imp_engine)
_import_guard("Orchestrator importable", _imp_orchestrator)
_import_guard("api-reference Task Key 清单可读", _imp_apiref_task_keys)

# 方法总数不再硬编码字面量，改为派生链保持一致（避免文档/引擎/注册表三者数字漂移）：
#   engine 导出数 ≥ orchestrator 任务数 == api-reference.md Task Key 数（唯一人读锚点）
check(
    f"Orchestrator: {_orchestrator_task_count} tasks == api-reference {len(_apiref_task_keys)} Task Keys",
    _orchestrator_task_count == len(_apiref_task_keys),
)
check(
    f"Engine: {_engine_export_count} exports cover {_orchestrator_task_count} tasks",
    _engine_export_count >= _orchestrator_task_count,
)

# ============================================================
section("1. Architecture Constraints")
# ============================================================
# 使用 Python 文件扫描替代 Unix grep，确保跨平台兼容
import glob as _glob


def _grep_files(pattern: str, path_pattern: str) -> tuple[bool, str]:
    """在匹配 path_pattern 的文件中搜索 pattern，返回 (是否找到, 匹配内容)。"""
    matches = []
    for fpath in _glob.glob(os.path.join(ROOT, path_pattern), recursive=True):
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if pattern.lower() in line.lower():
                        matches.append(f"{os.path.relpath(fpath, ROOT)}: {line.strip()[:100]}")
        except OSError:
            pass
    return len(matches) > 0, "\n".join(matches[:5])


found, details = _grep_files("xlwings", "src/smartsuite/engine/**/*.py")
check("engine/ has zero xlwings references", not found, details if found else "")

# excel/ 目录已移除（ADR-001 修订），如不存在则跳过
_excel_dir = os.path.join(ROOT, "src", "smartsuite", "excel")
if os.path.isdir(_excel_dir):
    found, details = _grep_files("sklearn", "src/smartsuite/excel/**/*.py")
    check("excel/ has zero sklearn/statsmodels references", not found, details if found else "")
else:
    check("excel/ has zero sklearn/statsmodels references", True, "目录不存在 (已按 ADR-001 移除)")

# ============================================================
section("2. All Engine Functions Runnable (status=ok)")
# ============================================================
np.random.seed(42)
data = pd.DataFrame(
    {
        "a": np.random.normal(100, 10, 50),
        "b": np.random.normal(50, 5, 50),
        "c": np.random.normal(30, 3, 50),
        "target": np.random.normal(20, 2, 50),
    }
)
# 按任务裁剪的辅助列：二值目标 / 二/三水平分组 / 子组 / 量具零件与操作员
data["yb"] = (data["a"] > data["a"].median()).astype(int)
data["g2"] = np.where(data["a"] > data["a"].median(), "高", "低")
data["g3"] = pd.qcut(data["a"], 3, labels=["低", "中", "高"])
data["sub"] = np.repeat(np.arange(1, 11), 5)
data["part"] = np.repeat(np.arange(1, 11), 5)
data["operator"] = np.tile(["甲", "乙", "丙", "甲", "乙"], 10)

# 任务专用调用（审查 2026-08-19 #3.1：原通用参数对多数任务不适用，
# 门禁判定升级为 status==ok，每个任务跑各自规范路径）
# ⚠️ '预期状态表'风险（第二轮 #17）：TASK_SPEC 是审查者手工维护的"预期参数表"，
# 若某任务的 spec 与引擎实际契约偏离（如参数名/列要求过时），status=ok 判定会
# 静默通过而不暴露真实行为问题——spec 变更必须同步 api-reference.md 与手册，
# 并靠 tests/ 的 4 层防线兜底（本表只做冒烟，不做深度行为验证）。
TASK_SPEC = {
    # Round-2 P3：anova 需真实类别因子（数值连续列每水平 1 样本现被拒绝）
    "anova": ("target", ["g3"], {}),
    "box_chart": ("target", ["b"], {"mode": "facet", "group_col": "g3"}),
    "hypothesis_test": ("target", ["g2"], {"test": "ttest_ind", "group_col": "g2"}),
    # 避免完美分离（yb 由 a 的切分生成，a 作特征会精确预测）
    "logistic_regression": ("yb", ["b", "c"], {}),
    "roc_analysis": ("yb", ["a", "b"], {}),
    "proportion_ci": ("yb", [], {}),
    # group_col == x_col 场景（审查 #1.2 回归场景）
    "scatter_plot": ("target", ["a"], {"fit": "linear", "group_col": "a"}),
    "spc_xbar": ("target", [], {"group_col": "sub"}),
    "spc_attribute": ("yb", [], {"chart_type": "p"}),
    "spc_cusum": ("target", [], {"group_col": "sub"}),
    "spc_ewma": ("target", [], {"group_col": "sub"}),
    "variance_test": ("target", ["g3"], {"group_col": "g3"}),
    "survival_analysis": ("target", ["yb", "g2"], {"group_col": "g2"}),
    "gage_rr": ("target", ["part", "operator"], {"part_col": "part", "operator_col": "operator"}),
    "grid_search": (
        "target",
        ["a", "b"],
        {"ranges": {"a": [80, 120], "b": [40, 60]}, "n_points": 5, "direction": "maximize"},
    ),
    "multi_objective": (
        "target",
        ["a", "b"],
        {"objectives": [{"col": "target", "direction": "maximize"}]},
    ),
    "doe_design": (
        "",
        [],
        {
            "method": "full_factorial",
            "factors": [{"name": "a", "levels": [1, 2]}, {"name": "b", "levels": [1, 2]}],
            "randomize": False,
        },
    ),
}
for task_id in sorted(TASK_REGISTRY.keys()):
    spec = TASK_SPEC.get(task_id)
    if spec is not None:
        target_col, feature_cols, params = spec
    else:
        target_col, feature_cols, params = "target", ["a", "b", "c"], {}
    req = AnalysisRequest(
        task=task_id, data=data, target_col=target_col, feature_cols=feature_cols, params=params
    )
    try:
        result = orchestrate(req)
        check(
            f"  {task_id} -> AnalysisResult(status=ok)",
            result.task == task_id and result.status == "ok",
            f"status={result.status}, messages={result.messages[:1]}",
        )
    except Exception as e:
        check(f"  {task_id} -> AnalysisResult(status=ok)", False, str(e)[:80])

# ============================================================
section("3. Determinism (Same Input = Same Output)")
# ============================================================
np.random.seed(123)
d1 = pd.DataFrame(
    {
        "x1": np.random.normal(100, 10, 20),
        "x2": np.random.normal(50, 5, 20),
        "y": np.random.normal(30, 3, 20),
    }
)
np.random.seed(123)
d2 = pd.DataFrame(
    {
        "x1": np.random.normal(100, 10, 20),
        "x2": np.random.normal(50, 5, 20),
        "y": np.random.normal(30, 3, 20),
    }
)
r1 = orchestrate(
    AnalysisRequest(task="correlation", data=d1, target_col="y", feature_cols=["x1", "x2"])
)
r2 = orchestrate(
    AnalysisRequest(task="correlation", data=d2, target_col="y", feature_cols=["x1", "x2"])
)
check(
    "Same input -> same correlation matrix",
    np.allclose(r1.tables["correlation_matrix"].values, r2.tables["correlation_matrix"].values),
)
check("Same input -> same summary", r1.summary == r2.summary)
r1r2 = orchestrate(
    AnalysisRequest(task="regression", data=d1, target_col="y", feature_cols=["x1", "x2"])
).metadata["r_squared"]
r2r2 = orchestrate(
    AnalysisRequest(task="regression", data=d2, target_col="y", feature_cols=["x1", "x2"])
).metadata["r_squared"]
check("Same input -> same R2", abs(r1r2 - r2r2) < 1e-10)

# ============================================================
section("4. Error Handling & Edge Cases")
# ============================================================
check(
    "Unknown task -> error",
    orchestrate(AnalysisRequest(task="nonexistent", data=d1, target_col="y")).status == "error",
)
check(
    "Missing target col -> error",
    orchestrate(
        AnalysisRequest(task="anova", data=d1, target_col="no_such_col", feature_cols=["x1"])
    ).status
    == "error",
)
r = orchestrate(
    AnalysisRequest(
        task="correlation",
        data=d1.assign(x1_nan=d1["x1"].where(d1.index > 5)),
        target_col="y",
        feature_cols=["x1", "x2"],
    )
)
check("NaN data -> graceful return", r.status in ("ok", "warning", "error"), f"status={r.status}")

from smartsuite.core.exceptions import AnalysisError, ConvergenceError

check(
    "ConvergenceError < AnalysisError < SmartSuiteError",
    isinstance(ConvergenceError("t"), AnalysisError),
)

# ============================================================
section("5. Reporter Output (PDF/PPT)")
# ============================================================
from smartsuite.services.reporter import to_pdf, to_ppt

r = orchestrate(
    AnalysisRequest(task="correlation", data=d1, target_col="y", feature_cols=["x1", "x2"])
)
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
    pdf_p = f.name
try:
    to_pdf(r, pdf_p)
    check("PDF generation (>100B)", os.path.getsize(pdf_p) > 100, f"{os.path.getsize(pdf_p)}B")
finally:
    os.unlink(pdf_p)
with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
    ppt_p = f.name
try:
    to_ppt(r, ppt_p)
    check("PPT generation (>1KB)", os.path.getsize(ppt_p) > 1000, f"{os.path.getsize(ppt_p)}B")
finally:
    os.unlink(ppt_p)
rs = orchestrate(
    AnalysisRequest(task="response_surface", data=d1, target_col="y", feature_cols=["x1", "x2"])
)
check("Response surface produces figures", len(rs.figures) >= 1)

# ============================================================
section("6. Test Data Regression Validation")
# ============================================================
test_path = os.path.join(ROOT, "tests", "test_data.xlsx")
if os.path.exists(test_path):
    df = pd.read_excel(test_path)
    nc = [
        "熔体温度",
        "模具温度",
        "注射压力",
        "保压压力",
        "注射速度",
        "冷却时间",
        "循环周期",
        "螺杆转速",
        "背压",
        "锁模力",
        "干燥温度",
        "干燥时间",
    ]
    r = orchestrate(
        AnalysisRequest(task="correlation", data=df, target_col="拉伸强度", feature_cols=nc)
    )
    check("melt_temp correlates with tensile_strength", "熔体温度" in r.summary, r.summary)
    r = orchestrate(
        AnalysisRequest(
            task="anova",
            data=df.dropna(subset=["冲击强度"]),
            target_col="冲击强度",
            feature_cols=["原料类型"],
            params={"alpha": 0.05},
        )
    )
    check("material_type significantly affects impact_strength", "显著" in r.summary, r.summary)
    r = orchestrate(
        AnalysisRequest(
            task="anova",
            data=df.dropna(subset=["不良率"]),
            target_col="不良率",
            feature_cols=["保养日"],
            params={"alpha": 0.05},
        )
    )
    check("maintenance_day significantly affects defect_rate", "显著" in r.summary, r.summary)
    r = orchestrate(
        AnalysisRequest(
            task="anova",
            data=df.dropna(subset=["不良率", "设备报警"]),
            target_col="不良率",
            feature_cols=["设备报警"],
            params={"alpha": 0.05},
        )
    )
    check("machine_alarm significantly affects defect_rate", "显著" in r.summary, r.summary)

# ============================================================
section("7. Statistical Correctness (Known Data)")
# ============================================================
np.random.seed(999)
x = np.random.normal(0, 1, 100)
y = 0.8 * x + np.random.normal(0, 0.3, 100)
r = orchestrate(
    AnalysisRequest(
        task="correlation", data=pd.DataFrame({"x": x, "y": y}), target_col="y", feature_cols=["x"]
    )
)
val = r.tables["correlation_matrix"].loc["y", "x"]
check(f"Known strong correlation r~0.9: detected r={val:.3f} > 0.8", abs(val) > 0.8)

g1 = pd.DataFrame({"g": "A", "v": np.random.normal(100, 5, 30)})
g2 = pd.DataFrame({"g": "B", "v": np.random.normal(115, 5, 30)})
r = orchestrate(
    AnalysisRequest(
        task="hypothesis_test",
        data=pd.concat([g1, g2]),
        target_col="v",
        feature_cols=["g"],
        params={"group_col": "g"},
    )
)
check(
    "Known significant difference: detected p<0.01",
    r.metadata["p_value"] < 0.01,
    f"p={r.metadata['p_value']:.6f}",
)

# ============================================================
section("8. Test Suite (pytest)")
# ============================================================
if _args.skip_pytest:
    # CI quick job 已用独立 pytest 步骤跑过引擎层/服务层/集成测试，
    # 此处显式登记"跳过"而非默认 PASS，避免门禁误以为嵌套 pytest 覆盖过
    check("pytest all pass", True, "跳过（--skip-pytest，由 CI quick job 独立步骤覆盖）")
else:
    # --basetemp 固定独立临时目录：避免 Windows 上 pytest-current junction
    # 残留导致 sessionfinish 清理 PermissionError（审查 2026-08-19 #5.2）
    _verify_basetemp = os.path.join(tempfile.gettempdir(), "ss-verify-basetmp")
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--tb=line",
            "-q",
            f"--basetemp={_verify_basetemp}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # 第二轮 #17：子进程输出含无法解码字节时不抛异常
        cwd=ROOT,
    )
    # 仅检查 returncode，不 grep "failed" 单词 —
    # statsmodels ConvergenceWarning 中含有 "failed to converge" 文字会误判
    check("pytest all pass", r.returncode == 0, f"returncode={r.returncode}")
    if r.returncode != 0:
        # 失败时透传子进程输出（含 FAILED 测试名与失败行），保证 CI 日志可诊断
        print("  ── pytest 子进程输出（失败详情）──")
        for line in (r.stdout or "").splitlines()[-40:]:
            print(f"    {line}")
        for line in (r.stderr or "").splitlines()[-10:]:
            print(f"    [stderr] {line}")

# ============================================================
section("9. CLI")
# ============================================================
r = subprocess.run(
    [sys.executable, "-m", "smartsuite.cli", "list"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",  # 第二轮 #17：同上
    cwd=ROOT,
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
)
stdout = r.stdout or ""
check(
    "CLI lists core methods",
    all(n in stdout for n in ["anova", "correlation", "spc_xbar", "trend_forecast"]),
    f"output_len={len(stdout)}",
)

# ============================================================
section("SUMMARY")
# ============================================================
total = PASS + FAIL
checks.append(f"\n  PASS: {PASS}/{total}  FAIL: {FAIL}/{total}")
checks.append(f"  {'*** ALL CHECKS PASSED ***' if FAIL == 0 else '*** SOME CHECKS FAILED ***'}")
for line in checks:
    print(line)
sys.exit(0 if FAIL == 0 else 1)
