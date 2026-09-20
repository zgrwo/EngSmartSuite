"""惰性导入机制的**进程内**单测（审查 2026-09-19 B2）。

`tests/guards/test_lazy_imports.py` 用独立解释器断言「按需加载」这一契约本身
（子进程不参与覆盖率统计），本文件在进程内直接调用各层 `__getattr__` /
`_module_available`，覆盖实现分支并锁死回退行为。
"""

import importlib
import sys

import pytest

import smartsuite
from smartsuite.services import task_spec  # noqa: F401 — 触发 services 包初始化


# ── ① 包级依赖自检：只探测不导入 ──


def test_module_available_true_for_imported_module():
    """已导入模块短路返回 True（不查 find_spec）。"""
    assert smartsuite._module_available("pandas") is True


def test_module_available_true_for_installed_but_unimported(monkeypatch):
    """已安装但未导入 → find_spec 命中，且**不得**真的导入它。"""
    target = "openpyxl"
    monkeypatch.delitem(sys.modules, target, raising=False)
    assert smartsuite._module_available(target) is True
    assert target not in sys.modules, "依赖自检不得真实导入"


def test_module_available_false_for_missing_package():
    assert smartsuite._module_available("no_such_pkg_xyz_abc") is False


def test_module_available_handles_value_error(monkeypatch):
    """find_spec 对 __spec__ 为 None 的模块抛 ValueError → 按「不可用」处理而非崩溃。"""
    import importlib.util

    def _boom(name):
        raise ValueError(f"{name}.__spec__ is None")

    monkeypatch.setattr(importlib.util, "find_spec", _boom)
    assert smartsuite._module_available("未导入且探测异常") is False


# ── ② services 包级惰性再导出 ──


def test_services_lazy_export_resolves_to_real_object():
    services = importlib.import_module("smartsuite.services")
    from smartsuite.services.orchestrator import orchestrate as real

    assert services.orchestrate is real, "惰性解析必须返回真实对象（不得包装/副本）"


def test_services_lazy_export_does_not_load_unrelated_submodules(monkeypatch):
    """取 data_io 的导出不得连带加载 audit/reporter。"""
    for mod in list(sys.modules):
        if mod.startswith("smartsuite.services."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    services = importlib.import_module("smartsuite.services")
    _ = services.validate_data
    assert "smartsuite.services.data_io" in sys.modules
    assert "smartsuite.services.audit" not in sys.modules
    assert "smartsuite.services.reporter" not in sys.modules


def test_services_unknown_attribute_raises():
    services = importlib.import_module("smartsuite.services")
    with pytest.raises(AttributeError):
        _ = services.压根不存在
    assert "smartsuite.services" in repr(services)


def test_services_dir_lists_public_api():
    services = importlib.import_module("smartsuite.services")
    assert set(services.__all__).issubset(set(dir(services)))


def test_services_all_names_are_resolvable():
    """`__all__` 与 `_EXPORT_SOURCES` 必须一一对应（防新增再导出时漏登记）。"""
    services = importlib.import_module("smartsuite.services")
    assert set(services.__all__) == set(services._EXPORT_SOURCES)
    for name in services.__all__:
        assert getattr(services, name) is not None


# ── ③ engine 包级惰性分析函数导出 ──


def test_engine_lazy_export_resolves_and_caches(monkeypatch):
    engine = importlib.import_module("smartsuite.engine")
    monkeypatch.delitem(engine.__dict__, "correlation_analysis", raising=False)
    fn = engine.correlation_analysis
    assert fn.__name__ == "correlation_analysis"
    assert engine.__dict__["correlation_analysis"] is fn, "解析结果应写回 globals 缓存"


def test_engine_unknown_attribute_raises():
    engine = importlib.import_module("smartsuite.engine")
    with pytest.raises(AttributeError):
        _ = engine.no_such_function


def test_engine_lazy_lookup_exhausted_raises(monkeypatch):
    """名字在 __all__ 中但所有子包都没有 → AttributeError（不得静默返回 None）。"""
    engine = importlib.import_module("smartsuite.engine")
    monkeypatch.setattr(engine, "_LAZY_SUBPACKAGES", ())
    monkeypatch.delitem(engine.__dict__, "correlation_analysis", raising=False)
    with pytest.raises(AttributeError, match="correlation_analysis"):
        _ = engine.correlation_analysis


def test_engine_all_names_resolve_or_are_constants():
    """`__all__` 中每个名字都必须可解析（分析函数走惰性，常量走急切导入）。"""
    engine = importlib.import_module("smartsuite.engine")
    for name in engine.__all__:
        assert getattr(engine, name) is not None, f"{name} 不可解析"


# ── 桥接出口（B4：借道改为显式模块）──


def test_bridge_exports_engine_display_rounding():
    """web 经 `services.bridge` 取引擎的展示口径；必须是同一函数对象。"""
    from smartsuite.engine._utils import round_for_display as real
    from smartsuite.services.bridge import round_for_display as bridged

    assert bridged is real


def test_orchestrator_no_longer_carries_borrowed_names():
    """B4：orchestrator 不再为 web 转手导出（借道退出它，改为命名出口）。"""
    orch = importlib.import_module("smartsuite.services.orchestrator")

    assert not hasattr(orch, "round_for_display")
    assert not hasattr(orch, "GROUP_COLORS")
    with pytest.raises(AttributeError):
        _ = orch.round_for_display


def test_orchestrator_has_no_lazy_bridge_left():
    """orchestrator 的 __getattr__ 惰性桥接已移除（避免两条并行取用路径）。"""
    orch = importlib.import_module("smartsuite.services.orchestrator")

    assert "__getattr__" not in vars(orch)
