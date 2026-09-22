"""惰性导入守卫（审查 2026-09-19 B2）。

背景：CLI 冷启动 ~3s 的根因是**三层急切导入**叠加：

| 层 | 位置 | 代价 |
| :--- | :--- | :--- |
| ① | `smartsuite/__init__.py::check_core_deps` 用 `__import__` **真实导入** 6 个核心依赖 | sklearn 0.89s 等 |
| ② | `services/__init__.py` 全量 re-export audit/orchestrator/reporter | 拉入整条服务链与引擎 |
| ③ | `engine/__init__.py` 急切导入 42 个分析函数（4 个 try/except 块） | doe_opt 0.71s 等 |

本文件用**独立解释器**断言「按需加载」这件事**本身**（`sys.modules` 内容），
而不断言墙钟耗时——耗时随机器负载波动，`sys.modules` 是确定性的契约信号。

同时锁死公开 API 不变：惰性化不得让 `from smartsuite.engine import X` /
`from smartsuite.services import Y` 失效。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# 新增这些包即代表「重依赖被拉起」（pandas/numpy/pydantic 是数据契约的固有依赖，不在列）
_HEAVY = ("matplotlib", "sklearn", "statsmodels", "scipy")

_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
_MEMORY_HINTS = ("Memory allocation", "OpenBLAS error", "unable to allocate")


def _probe(statement: str) -> dict:
    """在独立解释器中执行 statement，返回被加载的模块清单。"""
    code = f"{statement}\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_ROOT,
        env=_ENV,
    )
    if proc.returncode != 0 and any(h in (proc.stderr or "") for h in _MEMORY_HINTS):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=_ROOT,
            env=_ENV,
        )
    assert proc.returncode == 0, f"探测子进程失败：\n{proc.stderr[-600:]}"
    return {name: None for name in json.loads((proc.stdout or "").strip().splitlines()[-1])}


def _loaded(modules: dict, prefix: str) -> set[str]:
    return {m for m in modules if m == prefix or m.startswith(prefix + ".")}


# ── ① 包级依赖自检不得真实导入 ──


def test_core_contracts_does_not_pull_heavy_deps():
    """只导入数据契约时，重依赖（matplotlib/sklearn/statsmodels/scipy）不得被加载。"""
    modules = _probe("from smartsuite.core.contracts import AnalysisRequest")
    loaded = {m for m in _HEAVY if m in modules}
    assert not loaded, f"导入 core.contracts 不应拉起重依赖，实际加载: {sorted(loaded)}"


def test_importing_smartsuite_package_does_not_pull_heavy_deps():
    """`import smartsuite` 本身（依赖自检）也不得真实导入核心依赖。"""
    modules = _probe("import smartsuite")
    loaded = {m for m in _HEAVY if m in modules}
    assert not loaded, f"依赖自检应只探测不导入，实际加载: {sorted(loaded)}"


def test_check_core_deps_reports_missing_without_importing_present_ones():
    """依赖自检既不导入已装依赖，也不漏报缺失依赖（缺失 → 中文 ImportError）。"""
    modules = _probe(
        "import smartsuite as pkg\n"
        "pkg._CORE_DEPS = {'openpyxl': 'x', 'no_such_pkg_xyz_abc': 'y'}\n"
        "try:\n"
        "    pkg.check_core_deps()\n"
        "except ImportError as e:\n"
        "    assert '缺少必要的核心依赖包' in str(e) and 'no_such_pkg_xyz_abc' in str(e)\n"
        "else:\n"
        "    raise AssertionError('缺失依赖应抛 ImportError')\n"
    )
    assert "openpyxl" not in modules, "已安装的依赖不应被真实导入"


# ── ② services 包级 re-export 不得急切 ──


def test_importing_data_io_does_not_load_other_services():
    """导入任一 services 子模块不得连带加载 audit/orchestrator/reporter。"""
    modules = _probe("import smartsuite.services.data_io")
    leaked = _loaded(modules, "smartsuite.services")
    assert "smartsuite.services.audit" not in leaked, f"audit 被连带加载: {sorted(leaked)}"
    assert "smartsuite.services.orchestrator" not in leaked
    assert "smartsuite.services.reporter" not in leaked
    assert "matplotlib" not in modules, "data_io 路径不应拉起 matplotlib"


def test_services_package_reexports_still_work():
    """惰性化不得破坏公开再导出（PEP 562 __getattr__ 必须让 from-import 生效）。"""
    modules = _probe(
        "from smartsuite.services import (\n"
        "    orchestrate, TASK_REGISTRY, preprocess_data, validate_data,\n"
        "    missing_pattern_analysis, recommend_analysis, to_excel, to_pdf,\n"
        "    to_ppt, to_html, process_audit, batch_analyze, auto_report, export_workbook,\n"
        ")\n"
        "assert callable(orchestrate) and len(TASK_REGISTRY) == 42\n"
    )
    assert _loaded(modules, "smartsuite.services"), "按需访问后模块应已加载"


# ── ③ engine 42 个分析函数不得急切导入 ──


def test_engine_package_does_not_eagerly_import_analysis_functions():
    """`import smartsuite.engine` 只应加载配置/常量，不得加载 42 个分析函数所在子包。"""
    modules = _probe("import smartsuite.engine")
    for sub in ("smartsuite.engine.doe_opt", "smartsuite.engine.root_cause"):
        assert sub not in modules, f"{sub} 不应在导入 engine 时被加载"
    assert "smartsuite.engine.inverse" not in modules
    assert "sklearn" not in modules, "engine 配置路径不应拉起 sklearn"


def test_engine_attribute_access_is_lazy_and_correct():
    """惰性 `__getattr__` 必须解析出正确函数，且只加载所需子包。"""
    _probe(
        "import sys\n"
        "import smartsuite.engine as e\n"
        "assert 'smartsuite.engine.root_cause.correlation' not in sys.modules\n"
        "fn = e.correlation_analysis\n"
        "assert fn.__name__ == 'correlation_analysis', fn\n"
        "assert fn.__module__.endswith('root_cause.correlation'), fn.__module__\n"
        "assert 'smartsuite.engine.spc_monitor' not in sys.modules, '不应连带加载未使用的子包'\n"
    )


def test_engine_unknown_attribute_raises_attribute_error():
    """未知属性必须抛 AttributeError（不得静默返回 None 或误导入）。"""
    _probe(
        "import smartsuite.engine as e\n"
        "try:\n"
        "    e.no_such_function\n"
        "except AttributeError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('未知属性应抛 AttributeError')\n"
    )


def test_engine_public_api_still_works():
    """`from smartsuite.engine import X` 对分析函数与常量都必须照旧可用。"""
    _probe(
        "from smartsuite.engine import (\n"
        "    correlation_analysis,\n"
        "    xbar_r_chart,\n"
        "    PALETTE,\n"
        "    GROUP_COLORS,\n"
        "    CPK_GOOD,\n"
        ")\n"
        "assert callable(correlation_analysis) and callable(xbar_r_chart)\n"
        "assert '要因筛选' in GROUP_COLORS and CPK_GOOD > 0 and PALETTE\n"
    )


# ── CLI 端到端：冷启动不得拉起引擎重依赖 ──


def test_cli_list_does_not_load_engine_deps():
    """`smartsuite list` 只需要任务清单，不得拉起 sklearn/statsmodels/matplotlib。"""
    modules = _probe("import smartsuite.cli")
    loaded = sorted(m for m in _HEAVY if m in modules)
    assert not loaded, f"CLI 冷启动不应加载重依赖，实际: {loaded}"


@pytest.mark.parametrize("heavy", _HEAVY)
def test_heavy_dep_names_are_real(heavy):
    """防御：本文件断言的重依赖名必须真实存在于环境（防拼写导致守卫假绿）。"""
    import importlib.util

    assert importlib.util.find_spec(heavy) is not None, f"{heavy} 未安装，守卫名可能有误"
