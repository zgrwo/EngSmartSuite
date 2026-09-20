"""matplotlib 后端与导入时序守卫（审查 2026-09-19 E8 / B3）。

背景：后端设置 `matplotlib.use("Agg")` 原本出现在**两处**（`engine/__init__.py` 与
`web/api.py`），且 `web/api.py` 在**模块级** `import matplotlib.pyplot`。pyplot 一旦
被导入后端即被锁定，之后再调 `use()` 只能切换（或报错），"谁先导入"因此成了隐性契约；
Windows 上若 pyplot 先于配置导入，默认后端可能是 TkAgg（需要显示器）。

B3 后的契约：
1. **唯一配置点** = `engine/__init__.py`（后端 + 中文字体 + 配色）；
2. `web/` 不得在模块级导入 pyplot——web 按分层红线不能直接 import engine，
   只能依赖「经 services → engine 已完成配置」这一事实，而模块级导入会早于它；
3. `services/reporter.py` 可在模块级导入 pyplot，因其 import 链必然先经
   `services/__init__` → `audit` → `engine`；

第 1、3 条由**独立解释器**断言（本进程内 pyplot 可能早已被其他测试导入，
后端已被锁定，断言会失去鉴别力）。
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import smartsuite

_SRC = Path(smartsuite.__file__).parent
_ROOT = _SRC.parents[1]

# 每个入口都必须在**新解释器**中解析出 agg 后端
_ENTRY_POINTS = [
    ("CLI", "import smartsuite.cli"),
    ("Web app", "import smartsuite.web.app"),
    ("Web api", "import smartsuite.web.api"),
    ("services.reporter", "import smartsuite.services.reporter"),
    ("engine", "import smartsuite.engine"),
]


# 子进程只读后端名，无 BLAS 并行需求；不限制线程时 OpenBLAS 可能在内存紧张时
# 以 "Memory allocation still failed after 10 retries" 退出（同 conftest 的内存硬化）
_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
# 子进程因内存不足未能启动时的 stderr 特征（区别于真实导入错误）
_MEMORY_HINTS = ("Memory allocation", "OpenBLAS error", "unable to allocate")


def _run_probe(statement: str) -> subprocess.CompletedProcess:
    code = f"{statement}\nimport matplotlib\nprint(matplotlib.get_backend().lower())"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_ROOT,
        env=_ENV,
    )


def _backend_in_fresh_interpreter(statement: str) -> str:
    """在独立解释器中执行 statement 后读取后端名（小写）。

    内存不足时重试一次：这类失败是环境（父进程已持有全套依赖）而非被测契约的问题，
    但**不得静默跳过**——两次都失败仍报错，并在消息中区分“环境无法探测”与“后端错误”。
    """
    proc = _run_probe(statement)
    if proc.returncode != 0 and any(h in (proc.stderr or "") for h in _MEMORY_HINTS):
        proc = _run_probe(statement)
    assert proc.returncode == 0, (
        f"子进程无法完成后端探测（环境内存不足或导入失败）：\n{proc.stderr[-600:]}"
    )
    return (proc.stdout or "").strip().splitlines()[-1]


@pytest.mark.parametrize(("name", "statement"), _ENTRY_POINTS)
def test_entry_point_resolves_to_agg_backend(name, statement):
    """五个入口在全新解释器中都必须得到 agg（防 TkAgg 等交互后端）。"""
    backend = _backend_in_fresh_interpreter(statement)
    assert backend == "agg", f"{name}: 期望 agg 后端，实际 {backend!r}"


def test_reporter_import_keeps_agg_in_this_process():
    """本进程内导入 reporter 后后端仍为 agg（与上条互补：锁当前解释器状态）。"""
    import matplotlib
    import smartsuite.services.reporter  # noqa: F401

    assert matplotlib.get_backend().lower() == "agg"


# ── 静态守卫 ──


def _iter_source_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _calls_use_agg(tree: ast.AST) -> list[int]:
    """找出 `xxx.use("Agg")` 形式调用的行号（按字面 AGG 前缀识别）。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "use" or not node.args:
            continue
        arg = node.args[0]
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and arg.value.lower().startswith("agg")
        ):
            hits.append(node.lineno)
    return hits


def test_only_engine_init_configures_matplotlib_backend():
    """全仓只有 engine/__init__.py 允许设置 Agg 后端（单一配置点）。"""
    offenders = {}
    for path in _iter_source_files(_SRC):
        lines = _calls_use_agg(ast.parse(path.read_text(encoding="utf-8")))
        if lines and path != _SRC / "engine" / "__init__.py":
            offenders[str(path.relative_to(_SRC))] = lines
    assert not offenders, (
        f"matplotlib 后端只能由 engine/__init__.py 配置，以下位置重复设置：{offenders}"
    )


def _module_level_imports(tree: ast.Module) -> set[str]:
    """模块级 import 的模块名（含顶层 if/try 内，排除函数/类体内）。"""

    def collect(nodes) -> set[str]:
        names: set[str] = set()
        for node in nodes:
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, (ast.If, ast.Try)):
                names |= collect(node.body)
                names |= collect(getattr(node, "orelse", []))
                for handler in getattr(node, "handlers", []):
                    names |= collect(handler.body)
        return names

    return collect(tree.body)


def test_web_does_not_import_pyplot_at_module_level():
    """web/ 不得在模块级导入 pyplot：它早于 engine 配置，会锁定错误后端。

    需要 pyplot 时改为函数内导入（届时 engine 配置必然已执行）。
    """
    offenders = {}
    for path in _iter_source_files(_SRC / "web"):
        imported = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")))
        if "matplotlib.pyplot" in imported:
            offenders[str(path.relative_to(_SRC))] = "模块级 import matplotlib.pyplot"
    assert not offenders, f"web/ 模块级导入 pyplot（时序脆弱）：{offenders}"


def test_engine_package_never_imports_pyplot():
    """引擎层只用 matplotlib.figure 对象，不依赖 pyplot（避免锁定后端）。"""
    offenders = {}
    for path in _iter_source_files(_SRC / "engine"):
        imported = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")))
        if "matplotlib.pyplot" in imported:
            offenders[str(path.relative_to(_SRC))] = "模块级 import matplotlib.pyplot"
    assert not offenders, f"engine/ 不应导入 pyplot：{offenders}"
