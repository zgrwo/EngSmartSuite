"""架构分层守卫（审查 2026-09-19 B4）。

`AGENTS.md` 的四条分层红线（engine 不依赖 flask/xlwings、web 不直接导入 engine、
cli 只依赖 services、core 不反向依赖）此前**只有文档、没有检查**——本文件把它变成
可执行约束。落笔时四层方向均无违规，因此这些用例是「固化已有约束」而非「修 bug」；
真正的红灯来自第二组（借道导出）。

第二组锁住 B4 的成果：层间需要对方能力时，必须走**命名明确的出口**
（`core.constants` / `services.bridge`），而不是在无关模块里挂 `# noqa: F401`
再"顺手"导出——那种借道既看不出归属，也没有任何检查能阻止它悄悄增长。
"""

import ast
import tokenize
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "smartsuite"
_SERVICES = _SRC / "services"


def _iter_py(root: Path):
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def _imported_modules(path: Path) -> set[str]:
    """收集文件中**所有作用域**的绝对导入模块名（含函数内导入）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def _imports_of(path: Path, package: str) -> list[str]:
    prefix = f"smartsuite.{package}"
    return sorted(m for m in _imported_modules(path) if m == prefix or m.startswith(prefix + "."))


def _from_imports(path: Path) -> dict[str, set[str]]:
    """`{模块名: {导入的符号}}`，仅模块级 from-import（借道导出的实际写法）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return result


# ── ① 分层方向（固化已有约束：当前四层均无违规）──


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("core", ("engine", "services", "web")),  # 数据契约层不得反向依赖任何上层
        ("engine", ("services", "web")),  # 引擎层纯 Python，不依赖应用/Web 层
        ("services", ("web",)),  # 桥接层不得依赖 Web 层
    ],
)
def test_layer_does_not_import_upper_layers(layer, forbidden):
    offenders: list[str] = []
    for package in forbidden:
        for path in _iter_py(_SRC / layer):
            hits = _imports_of(path, package)
            offenders += [f"{path.relative_to(_SRC)} -> {m}" for m in hits]
    assert not offenders, f"{layer}/ 不得导入 {forbidden}：{offenders}"


def test_web_does_not_import_engine_directly():
    """web 必须经 services 间接调用引擎（红线：web 不直接依赖 engine）。"""
    offenders: list[str] = []
    for path in _iter_py(_SRC / "web"):
        offenders += [f"{path.relative_to(_SRC)} -> {m}" for m in _imports_of(path, "engine")]
    assert not offenders, f"web/ 不得直接导入 engine/，应经 services 桥接：{offenders}"


def test_cli_does_not_import_engine_directly():
    """cli.py 是第五入口，只依赖 services/（不得绕过桥接层直取引擎）。"""
    offenders = _imports_of(_SRC / "cli.py", "engine")
    assert not offenders, f"cli.py 不得直接导入 engine/，应经 services 桥接：{offenders}"


def test_engine_does_not_import_web_frameworks():
    """引擎层零业务框架依赖：不得导入 flask / xlwings。"""
    offenders: list[str] = []
    for path in _iter_py(_SRC / "engine"):
        for module in _imported_modules(path):
            if module.split(".")[0] in {"flask", "xlwings"}:
                offenders.append(f"{path.relative_to(_SRC)} -> {module}")
    assert not offenders, f"engine/ 不得依赖 flask/xlwings：{offenders}"


# ── ② 借道导出必须显式（B4）──


def _real_comments(path: Path) -> list[tuple[int, str]]:
    """收集**真实注释** token（行号, 文本）。

    不能用 `"noqa" in text` 直接查源码：文档字符串里引用 `# noqa: F401`（例如
    解释某条豁免的历史）只是字面量，不是豁免声明，直接匹配会产生自指假阳性。
    tokenize 能区分 COMMENT 与 STRING，所以这里只认前者。
    """
    with path.open(encoding="utf-8") as handle:
        return [
            (token.start[0], token.string)
            for token in tokenize.generate_tokens(handle.readline)
            if token.type == tokenize.COMMENT
        ]


def test_services_layer_has_no_f401_exemptions():
    """services 层不得用 `# noqa: F401` 挂借道导出。

    需要给别的层用的名字，要么是**本模块的公开 API**（本层自有职责），要么应在
    命名明确的归属模块里（`core/constants.py` 的配色常量、`services/bridge.py` 的
    引擎能力出口）。挂在无关模块上纯粹为「转手」，会让调用方以为那是该模块的职责。
    """
    offenders: dict[str, list[str]] = {}
    for path in _iter_py(_SERVICES):
        hits = [
            f"{line}: {text.strip()}"
            for line, text in _real_comments(path)
            if "noqa" in text and "F401" in text
        ]
        if hits:
            offenders[str(path.relative_to(_SRC))] = hits
    assert not offenders, f"services/ 不应保留借道导出豁免（改为命名出口）：{offenders}"


def test_orchestrator_does_not_carry_borrowed_names():
    """编排模块的导入必须服务于编排职责本身，不得转手导出配色常量/展示函数。"""
    borrowed = {"GROUP_COLORS", "round_for_display"}
    imports = _from_imports(_SERVICES / "orchestrator.py")
    leaked = {
        f"{module} -> {sorted(names & borrowed)}"
        for module, names in imports.items()
        if names & borrowed
    }
    assert not leaked, f"orchestrator 不应为其他层转手导出 {sorted(borrowed)}：{leaked}"


def test_web_reads_group_colors_from_core_constants():
    """配色常量属核心数据，web 应直取 `core/constants.py`（core 无需经 services）。"""
    imports = _from_imports(_SRC / "web" / "app.py")
    assert "GROUP_COLORS" in imports.get("smartsuite.core.constants", set()), (
        "web/app.py 应从 smartsuite.core.constants 导入 GROUP_COLORS"
    )


def test_web_reads_display_rounding_from_bridge():
    """展示口径属引擎能力，web 只能经显式桥接模块取用。"""
    imports = _from_imports(_SRC / "web" / "api.py")
    assert "round_for_display" in imports.get("smartsuite.services.bridge", set()), (
        "web/api.py 应从 smartsuite.services.bridge 导入 round_for_display"
    )


def test_bridge_module_is_the_sole_engine_capability_outlet():
    """`services/bridge.py` 必须真实导出引擎对象（同一对象，非副本/包装）。"""
    from smartsuite.engine import round_for_display as engine_impl
    from smartsuite.services.bridge import round_for_display as bridged

    assert bridged is engine_impl, "桥接必须是同一函数对象，否则展示口径会漂移"


def test_bridge_module_does_not_become_a_dumping_ground():
    """桥接模块只登记**确实被上层需要**的引擎能力，防止变成 re-export 垃圾场。"""
    exported = {
        name
        for name, value in vars(__import__("smartsuite.services.bridge", fromlist=["_"])).items()
        if not name.startswith("_")
    }
    assert exported == {"round_for_display"}, (
        f"bridge 只应导出 round_for_display，实际：{sorted(exported)}"
    )


def test_upper_layers_do_not_import_engine_private_modules():
    """services/ web/ cli 不得从 engine 的**私有子模块**取用能力（审查 R1-10）。

    engine 的 `_utils` / `_palette` / `_constants` 等是内部实现；上层直连会让
    「公开 API」形同虚设——符号改名或搬移会静默破坏分层契约，且调用方看不出
    该名字归属谁。需要的能力应由 `engine/__init__.py` 公开导出
    （`PALETTE` / `GROUP_COLORS` / `round_for_display` 均已如此），再经
    `services/bridge.py` 桥接给 web。
    """
    offenders: list[str] = []
    targets = [_iter_py(_SRC / pkg) for pkg in ("services", "web")]
    targets.append(iter([_SRC / "cli.py"]))
    for files in targets:
        for f in files:
            for mod in sorted(_imported_modules(f)):
                if mod.startswith("smartsuite.engine._"):
                    offenders.append(f"{f.relative_to(_SRC).as_posix()} → {mod}")
    assert not offenders, (
        f"上层不得直连 engine 私有模块（应经 engine 公开导出 + services/bridge）: {offenders}"
    )
