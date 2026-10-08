"""`PARAM_SPEC` 的**按任务**解析（修一个真实缺陷）。

## 缺陷（第二十轮发现）

`services/param_labels.py::_spec_for_task(func_path)` 按**模块路径**取
`PARAM_SPEC`。但一个模块常含多个任务：

| 模块 | 含任务 |
|:---|:---|
| `engine/exploratory.py` | `box_chart` / `scatter_plot` / `bootstrap_ci` / `median_ci` |
| `engine/root_cause/association.py` | `contingency` / `cohens_kappa` / `cronbach_alpha` |
| `engine/root_cause/distribution.py` | `distribution_summary` / `normality_check` |
| `engine/root_cause/inference.py` | `proportion_ci` / `variance_test` |

故模块级 `PARAM_SPEC` 只属于**其中一个**任务，但派生逻辑会让同模块的**其他**
任务也拿到它 —— 即 `cohens_kappa` 会继承 `contingency` 的 `alpha` 标签、
`proportion_ci` 会继承 `variance_test` 的 `group_col`。

这正是第十七轮遇到过的"选项跨任务泄漏"同族问题：**共用的东西被当成了自己的**。
标签错只是显示问题，但**选项错是功能问题**（用户被提供引擎不认的值）——
而 `param_options` 走同一条派生路径，故同样受影响。

## 修法

`PARAM_SPEC` 改为**按任务注册**：任务模块里用
`PARAM_SPECS = {"task_key": Spec(...)}` 声明，解析时先查该映射，
再回落到模块级 `PARAM_SPEC`（单任务模块的简写形式）。
"""

from __future__ import annotations

import pytest

from smartsuite.services.param_labels import spec_for_task


class TestSpecIsResolvedPerTask:
    """同模块的多个任务**不得**互相继承 `PARAM_SPEC`。"""

    def test_single_task_module_still_works(self):
        """单任务模块（`capability` / `design`）沿用模块级 `PARAM_SPEC`。"""
        assert spec_for_task("process_capability") is not None
        assert spec_for_task("power_analysis") is not None

    @pytest.mark.parametrize(
        "task",
        [
            # 以下任务与**别的任务同模块**，且自身尚未迁移 → 必须返回 None。
            # 注意：迁移某个任务后，请把它从本表移出 —— 本表是"尚未迁移"的**活清单**。
            # 已移出：`distribution_summary`（第二十一轮）、`proportion_ci`（第二十二轮）。
            "cohens_kappa",
            "cronbach_alpha",
        ],
    )
    def test_task_without_own_spec_gets_none(self, task):
        """**核心断言**：同模块里没有自己 Spec 的任务必须返回 `None`。

        返回别人的 Spec 会让它的参数拿到错误的标签/提示/**选项** ——
        后者是功能问题。修复前这些任务全部会返回同模块邻居的 Spec。
        """
        assert spec_for_task(task) is None, (
            f"{task} 不该有 Spec（同模块的 Spec 属于别的任务）；"
            "若确实为它新增了 Spec，请把它从本用例的参数表里移出"
        )

    def test_task_with_own_spec_gets_it(self):
        """有自己 Spec 的任务必须拿到**自己**的（而非同模块邻居的）。"""
        from smartsuite.core.param_specs_common import ALPHA
        from smartsuite.engine.root_cause.association import PARAM_SPECS

        assert spec_for_task("contingency") is PARAM_SPECS["contingency"]
        assert PARAM_SPECS["contingency"].field_names == ["alpha"]
        assert PARAM_SPECS["contingency"]._fields["alpha"] is ALPHA

    def test_inference_tasks_do_not_share(self):
        """`proportion_ci` 与 `variance_test` 同模块，但两者**各有自己的** Spec。

        实测两者的 `DEFAULT_PARAMS` 不同（`proportion_ci` 有 `success_value`、
        `variance_test` 有 `group_col`），故**不可能**共用一份 ——
        这正是"按任务登记"要保证的：同模块的条目互不干扰。
        """
        s_vt = spec_for_task("variance_test")
        s_pc = spec_for_task("proportion_ci")
        assert s_vt is not s_pc, "两个任务必须各有独立 Spec"
        assert set(s_vt.field_names) == {"group_col", "alpha"}
        assert set(s_pc.field_names) == {"ci_level", "success_value"}

    def test_unknown_task_returns_none(self):
        assert spec_for_task("no_such_task") is None


class TestRegistryShape:
    """`PARAM_SPECS` 的形状契约。"""

    def test_registry_maps_task_keys_to_specs(self):
        from smartsuite.engine.root_cause.association import PARAM_SPECS

        assert isinstance(PARAM_SPECS, dict)
        for key, spec in PARAM_SPECS.items():
            assert isinstance(key, str) and key
            assert hasattr(spec, "validate_or_raise"), key

    def test_registry_keys_are_real_tasks(self):
        from smartsuite.services.orchestrator import TASK_REGISTRY

        for module in (
            "smartsuite.engine.root_cause.association",
            "smartsuite.engine.root_cause.distribution",
            "smartsuite.engine.root_cause.inference",
            "smartsuite.engine.exploratory",
        ):
            mod = __import__(module, fromlist=["PARAM_SPECS"])
            for key in getattr(mod, "PARAM_SPECS", {}):
                assert key in TASK_REGISTRY, f"{module} 的 PARAM_SPECS 键 {key!r} 不是已注册任务"
