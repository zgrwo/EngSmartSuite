"""TaskSpec 单一事实源与派生结构测试（审查 2026-09-19 B1）。

背景：`services/orchestrator.py` 原以 7 组并列集合登记任务
（TASK_REGISTRY / DEFAULT_PARAMS / TASK_LABELS / TASK_GROUPS / RAW_CAT_TASKS /
NO_TARGET_TASKS / NO_DATA_TASKS），其中三处还用 `append`/`add` 打补丁
（inverse_solve）。新增一个方法要改 7 处，漏改即产生「引擎有、前端不可达」。

现由 `services/task_spec.py` 的 `TASK_SPECS` 单点派生。本文件锁死三件事：

1. **派生结果与重构前逐结构一致**（冻结快照，防重构漂移）；
2. **新增一条 spec 即 7 个结构同步**（单一事实源的兑现证明）；
3. **LazyTaskRegistry 的全部调用约定**（多处门禁脚本 / Web / monkeypatch 依赖）。

> 重构时的逐项严格比对（含 42 个函数解析目标与组内顺序）已作为一次性证据执行：
> 用 `derive` 结果与重构前转储的 JSON 快照比对，0 处差异。
"""

from importlib import import_module

import pytest

from smartsuite.services.orchestrator import (
    DEFAULT_PARAMS,
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    RAW_CAT_TASKS,
    TASK_GROUPS,
    TASK_LABELS,
    TASK_REGISTRY,
)
from smartsuite.services.task_spec import TASK_SPECS, TaskSpec, derive

# ── 冻结快照（重构前结构，用于锁死「派生无漂移」）──
# 键集/分组顺序/标记集合是语义契约：改动它们等于改变 Web 分组与预处理行为，
# 必须是有意为之（新增方法时同步更新本快照）。
_EXPECTED_GROUP_ORDER = ["要因筛选", "信度诊断", "建模优化", "过程监控", "高级分析"]

_EXPECTED_RAW_CAT = frozenset(
    {
        "anova",
        "box_chart",
        "cohens_kappa",
        "contingency",
        "hypothesis_test",
        "inverse_solve",
        "scatter_plot",
        "spc_attribute",
        "spc_xbar",
        "survival_analysis",
        "variance_test",
    }
)

_EXPECTED_NO_TARGET = frozenset(
    {
        "cohens_kappa",
        "cronbach_alpha",
        "doe_design",
        "inverse_solve",
        "multi_objective",
        "power_analysis",
        "vif",
    }
)

_EXPECTED_NO_DATA = frozenset({"doe_design", "power_analysis"})


# ── 1. 派生结果与重构前一致 ──


def test_group_order_matches_frozen_snapshot():
    """分组顺序即 Web 展示顺序，重构后必须逐字保持。"""
    assert list(TASK_GROUPS) == _EXPECTED_GROUP_ORDER


def test_flag_sets_match_frozen_snapshot():
    """三个预处理标记集合是 Web 行为契约（跳过 One-Hot / 免 Y / 免数据）。"""
    assert RAW_CAT_TASKS == _EXPECTED_RAW_CAT
    assert NO_TARGET_TASKS == _EXPECTED_NO_TARGET
    assert NO_DATA_TASKS == _EXPECTED_NO_DATA


def test_derived_structures_are_key_aligned():
    """6 个派生结构的键集必须完全一致（防「引擎有、前端不可达」）。"""
    keys = set(TASK_REGISTRY)
    assert set(TASK_LABELS) == keys
    assert set(DEFAULT_PARAMS) == keys
    assert TASK_GROUPS, "TASK_GROUPS 不得为空"
    assert {k for ks in TASK_GROUPS.values() for k in ks} == keys
    assert RAW_CAT_TASKS.issubset(keys)
    assert NO_TARGET_TASKS.issubset(keys)
    assert NO_DATA_TASKS.issubset(keys)
    # 无需数据的任务必然也无需目标列（否则 Web 会要求用户选 Y 却根本不读）
    assert NO_DATA_TASKS.issubset(NO_TARGET_TASKS)


def test_group_membership_order_follows_spec_order():
    """组内顺序 == TASK_SPECS 中的出现顺序（前端不再另行排序）。"""
    flattened = [key for keys in TASK_GROUPS.values() for key in keys]
    assert flattened == [spec.key for spec in TASK_SPECS]


def test_no_patch_style_registration_remains():
    """重构点：inverse_solve 必须由 spec 字段承载，而非 append/add 补丁。

    这条同时防「有人把补丁式注册加回来」（补丁会让 7 组结构再次分叉）。
    """
    inverse = next(s for s in TASK_SPECS if s.key == "inverse_solve")
    assert inverse.raw_cat is True
    assert inverse.no_target is True
    assert inverse.no_data is False  # 反解需要输入数据
    assert "inverse_solve" in TASK_GROUPS["建模优化"]


# ── 2. 单一事实源：新增一条 spec 即 7 个结构同步 ──


def _probe_spec() -> TaskSpec:
    return TaskSpec(
        key="_probe_task",
        func_path="smartsuite.engine._utils:round_for_display",
        label="探针任务",
        group="要因筛选",
        default_params={"probe": 1},
        raw_cat=True,
        no_target=True,
        no_data=True,
    )


def test_single_spec_addition_updates_all_structures():
    """追加一条 TaskSpec → 7 个结构全部自动包含它（「改一处」的兑现证明）。"""
    derived = derive((*TASK_SPECS, _probe_spec()))

    assert len(derived.registry) == len(TASK_SPECS) + 1
    assert "_probe_task" in derived.registry
    assert derived.labels["_probe_task"] == "探针任务"
    assert derived.default_params["_probe_task"] == {"probe": 1}
    assert derived.groups["要因筛选"][-1] == "_probe_task"
    assert "_probe_task" in derived.raw_cat
    assert "_probe_task" in derived.no_target
    assert "_probe_task" in derived.no_data
    assert callable(derived.registry["_probe_task"])


def test_duplicate_key_raises_instead_of_silently_overwriting():
    """重复键必须显式报错，不得「后写覆盖先写」静默丢失。"""
    with pytest.raises(ValueError, match="TaskSpec 键重复"):
        derive(
            (*TASK_SPECS, TaskSpec(key="anova", func_path="x:y", label="重复", group="要因筛选"))
        )


def test_default_params_are_copied_not_aliased():
    """派生结构不得与 spec 共享同一 dict（防调用方改写冻结 spec）。"""
    derived = derive(TASK_SPECS)
    derived.default_params["correlation"]["method"] = "改写"
    spec = next(s for s in TASK_SPECS if s.key == "correlation")
    assert spec.default_params["method"] == "pearson", "spec 被调用方改写"


# ── 3. LazyTaskRegistry 调用约定 ──


def test_every_spec_path_resolves_to_its_declared_function():
    """每个 func_path 必须可解析、可调用，且与函数的定义模块严格一致。"""
    for spec in TASK_SPECS:
        module_name, _, attr = spec.func_path.partition(":")
        assert attr, f"{spec.key}: func_path 必须为 '模块:函数名' 形式"
        func = getattr(import_module(module_name), attr)
        assert callable(func), f"{spec.key}: 解析结果不可调用"
        assert func.__name__ == attr
        assert spec.func_path == f"{func.__module__}:{func.__name__}", (
            f"{spec.key}: func_path 应指向**定义模块**（{func.__module__}），实际 {spec.func_path}"
        )


def test_registry_resolution_is_cached():
    """重复取值返回同一对象（缓存生效，不重复 import/查找）。"""
    assert TASK_REGISTRY["correlation"] is TASK_REGISTRY["correlation"]


def test_registry_supports_mapping_protocols():
    """门禁脚本与 Web 依赖的读取面：keys/values/items/len/iter/set/sorted/未知键。"""
    assert len(TASK_REGISTRY) == len(TASK_SPECS) == 42
    assert set(TASK_REGISTRY) == {s.key for s in TASK_SPECS}
    assert list(TASK_REGISTRY.keys()) == [s.key for s in TASK_SPECS]
    assert all(callable(f) for f in TASK_REGISTRY.values())
    assert dict(TASK_REGISTRY.items()).keys() == TASK_REGISTRY.keys()
    assert sorted(TASK_REGISTRY)[0] == sorted(s.key for s in TASK_SPECS)[0]
    with pytest.raises(KeyError):
        TASK_REGISTRY["不存在的任务"]


def test_registry_item_assignment_overrides_and_is_reversible(monkeypatch):
    """`monkeypatch.setitem` 依赖：覆盖单个任务后可恢复（约 20 处测试依赖）。"""

    def _fake(_req):
        raise AssertionError("不应被调用")

    original = TASK_REGISTRY["correlation"]
    with monkeypatch.context() as ctx:
        ctx.setitem(TASK_REGISTRY, "correlation", _fake)
        assert TASK_REGISTRY["correlation"] is _fake
    assert TASK_REGISTRY["correlation"] is original, "覆盖必须可逆"
    assert len(TASK_REGISTRY) == 42, "覆盖不得改变键数"


def test_registry_contains_is_lazy_and_does_not_resolve():
    """`in` 判定不得触发函数解析（否则 CLI 冷启动仍会加载引擎）。

    用不可导入的路径构造：若 `in` 触发解析会抛 ModuleNotFoundError。
    """
    derived = derive(
        (TaskSpec(key="ghost", func_path="definitely.not.a.module:fn", label="幽灵", group="g"),)
    )
    assert "ghost" in derived.registry, "`in` 不应触发解析"
    assert "missing" not in derived.registry
    with pytest.raises(ModuleNotFoundError):
        derived.registry["ghost"]  # 真正取值时才解析并暴露坏路径
