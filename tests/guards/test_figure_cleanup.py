"""图窗关闭逻辑单一实现守卫（审查 2026-09-19 E19 / 补充发现 5.5）。

背景：`cli.py` 与 `services/audit.py` 各自内联了同一段「惰性 import pyplot →
逐个 plt.close(fig)」逻辑，属重复实现，任一处漏改都会造成图窗泄漏（内存增长）
或行为漂移。

架构约束：AGENTS.md 规定 `cli.py` 只依赖 `services/`、**不得直接依赖 `engine/`**，
因此共享实现落在 `services/reporter.py`（pyplot 的归属模块），而非
`engine/_utils.py`。

计划原始设想「函数内惰性 import pyplot」经核实不成立：`services/__init__.py`
在导入期即全量 re-export `reporter`（其模块级已 `import matplotlib.pyplot`），
因此 `import smartsuite.cli` 时 pyplot 早已在 `sys.modules` 中——惰性导入在此
已是无效防御，真正的根因是 services 包的急切导入（Phase B2 处理）。
"""

import ast
from pathlib import Path

import pytest
from matplotlib import pyplot as plt

import smartsuite
from smartsuite.services.reporter import close_figures

_SRC = Path(smartsuite.__file__).parent

# 必须共用单一实现的文件（自身不得再出现 pyplot 导入 / 直接关闭）
_DELEGATING_FILES = ("cli.py", "services/audit.py")


@pytest.fixture(autouse=True)
def _clean_figures():
    """每个用例前后清空图窗，避免相互污染。"""
    close_figures()
    yield
    close_figures()


# ── 功能：close_figures 行为 ──


def test_close_figures_closes_given_list():
    """传入图窗列表 → 逐个关闭。"""
    figs = [plt.figure(), plt.figure()]
    assert len(plt.get_fignums()) == 2
    close_figures(figs)
    assert plt.get_fignums() == [], "指定列表应被全部关闭"


def test_close_figures_none_closes_all():
    """无参数 → 关闭全部（plt.close('all') 语义）。"""
    plt.figure()
    plt.figure()
    close_figures()
    assert plt.get_fignums() == [], f"应关闭全部图窗，剩余 {plt.get_fignums()}"


def test_close_figures_empty_list_is_noop():
    """空列表 → 不抛异常且不误关其它图窗（区别于 None 的关闭全部语义）。"""
    plt.figure()
    close_figures([])
    assert len(plt.get_fignums()) == 1, "空列表不得关闭全部图窗"


def test_close_figures_is_idempotent():
    """重复关闭同一图窗不得告警（本仓 filterwarnings=error，告警即失败）。"""
    fig = plt.figure()
    close_figures([fig])
    close_figures([fig])
    assert plt.get_fignums() == []


# ── 分层可达性：共享实现必须能被两侧导入 ──


def test_cli_reuses_same_function_object():
    """cli.py 应复用 reporter.close_figures（同一函数对象，非副本）。"""
    from smartsuite.cli import close_figures as cli_close_figures

    assert cli_close_figures is close_figures


def test_audit_keeps_adapter_to_shared_implementation():
    """audit 层保留 _close_figures 适配器（容忍 result 无 figures 字段）。"""
    from smartsuite.services import audit as audit_module

    assert hasattr(audit_module, "_close_figures")

    class _ResultWithoutFigures:
        pass

    # 无 figures 字段不得抛异常
    audit_module._close_figures(_ResultWithoutFigures())


def test_cli_does_not_import_engine_directly():
    """分层红线：cli.py 只依赖 services/，不得直接 import smartsuite.engine。"""
    imported = _imported_module_names(_SRC / "cli.py")
    assert not any(name.startswith("smartsuite.engine") for name in imported), (
        f"cli.py 不得直接依赖 engine：{sorted(n for n in imported if 'engine' in n)}"
    )


# ── 静态守卫：不得再次分叉关闭逻辑 ──


def _imported_module_names(path: Path) -> set[str]:
    """AST 收集 import 的模块名（含函数体内导入）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("relpath", _DELEGATING_FILES)
def test_delegating_file_does_not_import_pyplot(relpath):
    """cli.py / audit.py 不得再自行 import pyplot（防关闭逻辑再次分叉）。"""
    imported = _imported_module_names(_SRC / relpath)
    assert "matplotlib.pyplot" not in imported, (
        f"{relpath} 不应再导入 matplotlib.pyplot——请共用 services.reporter.close_figures"
    )


@pytest.mark.parametrize("relpath", _DELEGATING_FILES)
def test_delegating_file_has_no_direct_figure_close(relpath):
    """cli.py / audit.py 不得直接 plt.close(...) 自行收尾。"""
    tree = ast.parse((_SRC / relpath).read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"plt", "_plt"}
    ]
    assert not offenders, f"{relpath} 第 {offenders} 行仍在直接关闭图窗"
