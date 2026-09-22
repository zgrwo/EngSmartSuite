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

# 入口 → (语句, 期望)
#   "required"  = 必须加载 matplotlib 且后端为 Agg（后端配置的归属路径）
#   "forbidden" = 不得加载（B2 惰性化目标：不需要绘图就不付绘图栈成本）
#   "optional"  = 允许加载；**若**加载则后端必须已是 Agg
_ENTRY_POINTS = [
    ("CLI", "import smartsuite.cli", "forbidden"),
    ("services.reporter", "import smartsuite.services.reporter", "forbidden"),
    ("services.orchestrator", "import smartsuite.services.orchestrator", "forbidden"),
    ("Web app", "import smartsuite.web.app", "optional"),
    ("Web api", "import smartsuite.web.api", "optional"),
    ("engine", "import smartsuite.engine", "required"),
    ("engine 分析子模块", "import smartsuite.engine.root_cause.correlation", "required"),
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
    code = (
        f"{statement}\n"
        "import sys\n"
        "loaded = 'matplotlib' in sys.modules\n"
        "if loaded:\n"
        "    import matplotlib\n"
        "    backend = matplotlib.get_backend()\n"
        "else:\n"
        "    backend = '-';\n"
        'print(f"{loaded}|{backend}")\n'
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_ROOT,
        env=_ENV,
    )


def _backend_in_fresh_interpreter(statement: str) -> tuple[bool, str]:
    """在独立解释器中执行 statement，返回 (是否加载了 matplotlib, 后端名)。

    必须先探测 sys.modules 再导入 matplotlib——否则"后端为 agg"只是因为探测
    代码自己把 matplotlib 拉进来了（本文件早期版本的真实缺陷）。

    内存不足时重试一次：这类失败是环境（父进程已持有全套依赖）而非被测契约的问题，
    但**不得静默跳过**——两次都失败仍报错，并在消息中区分“环境无法探测”与“后端错误”。
    """
    proc = _run_probe(statement)
    if proc.returncode != 0 and any(h in (proc.stderr or "") for h in _MEMORY_HINTS):
        proc = _run_probe(statement)
    assert proc.returncode == 0, (
        f"子进程无法完成后端探测（环境内存不足或导入失败）：\n{proc.stderr[-600:]}"
    )
    loaded, _, backend = (proc.stdout or "").strip().splitlines()[-1].partition("|")
    return loaded == "True", backend.lower()


@pytest.mark.parametrize(("name", "statement", "expectation"), _ENTRY_POINTS)
def test_matplotlib_load_and_backend_by_entry_point(name, statement, expectation):
    """按入口分层断言：配置归属路径必须加载且为 agg；免绘图路径不得加载。"""
    loaded, backend = _backend_in_fresh_interpreter(statement)
    if expectation == "required":
        assert loaded, f"{name}: 应加载 matplotlib（后端配置的归属路径）"
    if expectation == "forbidden":
        assert not loaded, f"{name}: 不需要绘图却加载了 matplotlib（B2 惰性化回退）"
    assert (not loaded) or backend == "agg", (
        f"{name}: matplotlib 在导入期被加载却锁定了非 Agg 后端（{backend}）"
    )


def test_close_figures_does_not_disturb_resolved_backend():
    """进程内：engine 配置已生效时，close_figures 内部的惰性 pyplot 导入不得改变后端。

    B2 后 reporter 不再模块级导入 pyplot（否则会早于 engine 配置锁定 tkagg），
    因此这里锁的是「惰性导入发生在配置之后」这一实际使用路径。
    """
    import matplotlib
    import matplotlib.pyplot as plt

    import smartsuite.engine  # noqa: F401 — 确保后端配置已执行
    from smartsuite.services.reporter import close_figures

    before = matplotlib.get_backend()
    fig = plt.figure()
    close_figures([fig])
    assert matplotlib.get_backend() == before
    assert matplotlib.get_backend().lower() == "agg"
    assert plt.get_fignums() == []


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
    """全仓不得在任何模块级导入 pyplot：它早于 engine 的 Agg 配置，会锁定错误后端。

    `matplotlib.figure` / `matplotlib` 允许模块级导入（不锁后端，engine 子模块用它
    构造 Figure），**pyplot 只能函数内按需导入**。
    """
    offenders = {}
    for path in _iter_source_files(_SRC):
        imported = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")))
        if "matplotlib.pyplot" in imported:
            offenders[str(path.relative_to(_SRC))] = "模块级 import matplotlib.pyplot"
    assert not offenders, (
        f"以下位置在模块级导入 pyplot（会锁定非 Agg 后端，改为函数内导入）：{offenders}"
    )


def test_engine_package_does_not_import_pyplot_at_module_level():
    """引擎层只用 matplotlib.figure 对象，不依赖 pyplot（避免锁定后端）。"""
    offenders = {}
    for path in _iter_source_files(_SRC / "engine"):
        imported = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")))
        if "matplotlib.pyplot" in imported:
            offenders[str(path.relative_to(_SRC))] = "模块级 import matplotlib.pyplot"
    assert not offenders, f"engine/ 不应导入 pyplot：{offenders}"
