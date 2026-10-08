"""批量迁移第四批（阶段 P4 步骤③，第二十二轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 5 个任务

| 任务 | 参数 | 校验 | 共享字段 |
|:---|:---|:---|:---|
| `decision_tree` | `max_depth`, `random_state` | `Integer(min=1)` / `Integer(min=0)` | ✅ `RANDOM_STATE` |
| `proportion_ci` | `ci_level`, `success_value` | `Finite(gt=0,lt=1)` / 透传 | ✅ `CI_LEVEL` |
| `quantile_regression` | `quantile` | `Finite(gt=0,lt=1)` | 自声明（τ 语义独特） |
| `response_surface` | `direction` | `Choice(maximize/minimize)` | 自声明（枚举不入共享库） |
| `change_point` | `n_changepoints` | `Integer(min=1)` | 自声明 |

## 有意不迁的：`regression`

实测 `regression_analysis()` 的函数体**不读取任何 `params`**（AST 扫描结果为空），
而 `DEFAULT_PARAMS["regression"] = {"model_type": "linear"}` ——
即 `model_type` 是**未接线的参数**（前端能选、引擎不读）。

这是本轮发现的**真实不一致**（属"参数不可达"的镜像：参数可设但无效果）。
按"精准修改"原则本轮**不处理**（需要先是确认它是否真该被读，还是该从
`DEFAULT_PARAMS` 移除 —— 那是独立决策），已在台账记录。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 31) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 1.5, n),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "flag": rng.choice(["合格", "不合格"], n),
            "g": (["A", "B"] * (n // 2))[:n],
            "t": np.arange(n),
        }
    )


def _via(task: str, params: dict, target: str = "y", features=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=_frame(),
            target_col=target,
            feature_cols=features if features is not None else ["x1", "x2"],
            params=params,
        )
    )


BATCH = {
    "decision_tree": ({"max_depth": 5, "random_state": 42}, "y", ["x1", "x2"]),
    "proportion_ci": ({"ci_level": 0.95}, "flag", ["g"]),
    "quantile_regression": ({"quantile": 0.5}, "y", ["x1", "x2"]),
    "response_surface": ({"direction": "maximize"}, "y", ["x1", "x2"]),
    "change_point": ({"n_changepoints": 5}, "y", ["t"]),
}


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_match_default_params(self, task):
        """主防线：`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 一致。"""
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        assert spec.defaults() == DEFAULT_PARAMS[task], (
            f"{task}: {spec.defaults()} != {DEFAULT_PARAMS[task]}"
        )

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_no_required_fields(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task).required_fields() == [], task


class TestValidParams:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_explicit(self, task):
        params, target, feats = BATCH[task]
        r = _via(task, params, target=target, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_default(self, task):
        _, target, feats = BATCH[task]
        r = _via(task, {}, target=target, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"


class TestRejections:
    @pytest.mark.parametrize("bad", [0, -1, 2.5, "abc", float("inf")])
    def test_decision_tree_max_depth_rejected(self, bad):
        r = _via("decision_tree", {"max_depth": bad})
        assert r.status == "error", f"max_depth={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [-1, 1.5, "abc", float("nan")])
    def test_decision_tree_random_state_rejected(self, bad):
        """`random_state` 必须是非负整数（负种子在 sklearn 下含义不明）。"""
        r = _via("decision_tree", {"random_state": bad})
        assert r.status == "error", f"random_state={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [0, 1, 42, 999])
    def test_decision_tree_random_state_valid(self, ok):
        r = _via("decision_tree", {"random_state": ok})
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_proportion_ci_level_rejected(self, bad):
        r = _via("proportion_ci", {"ci_level": bad}, target="flag", features=["g"])
        assert r.status == "error", f"ci_level={bad!r} 应被拒绝"

    def test_proportion_success_value_passthrough(self):
        """`success_value` 是**标签匹配值**，可为任意类型（含 `None`）→ 原样透传。

        它故意**不做校验**：用户可能用 `1` / `"1"` / `"合格"` 等任意标签。
        但必须真的被引擎读到（本用例证明传 `"不合格"` 会改变结果）。
        """
        r_ok = _via("proportion_ci", {"success_value": "合格"}, target="flag", features=["g"])
        r_other = _via("proportion_ci", {"success_value": "不合格"}, target="flag", features=["g"])
        assert r_ok.status == "ok" and r_other.status == "ok"
        assert r_ok.metadata != r_other.metadata, "success_value 应真正影响结果（未被忽略）"

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_quantile_rejected(self, bad):
        r = _via("quantile_regression", {"quantile": bad})
        assert r.status == "error", f"quantile={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", ["max", "MIN", "up", 123])
    def test_response_surface_direction_rejected(self, bad):
        r = _via("response_surface", {"direction": bad})
        assert r.status == "error", f"direction={bad!r} 应被拒绝"
        assert any("direction" in m or "方向" in m for m in r.messages), r.messages

    def test_response_surface_empty_string_means_not_provided(self):
        """空串在编排层被归一为「未提供」→ 用默认值 `maximize`（**既有语义**）。

        依据 `orchestrator._normalize_empty_params`（审查 2026-09-19 E11）：
        这正是 Web 表单"清空下拉框"的语义。故 `""` **不该**被拒绝 ——
        本用例首版把它列进拒绝清单，是**我的断言错层**（与第十三轮同一类错误）。
        """
        r = _via("response_surface", {"direction": ""})
        assert r.status == "ok", r.messages
        assert r.metadata.get("direction") == "maximize", r.metadata.get("direction")

    @pytest.mark.parametrize("ok", ["maximize", "minimize"])
    def test_response_surface_direction_valid(self, ok):
        r = _via("response_surface", {"direction": ok})
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [0, -3, 2.5, "abc"])
    def test_change_point_n_changepoints_rejected(self, bad):
        r = _via("change_point", {"n_changepoints": bad}, features=["t"])
        assert r.status == "error", f"n_changepoints={bad!r} 应被拒绝"


class TestEngineRaises:
    @pytest.mark.parametrize(
        "task,field,bad",
        [
            ("decision_tree", "max_depth", 0),
            ("proportion_ci", "ci_level", 1.5),
            ("quantile_regression", "quantile", 0),
            ("response_surface", "direction", "up"),
            ("change_point", "n_changepoints", 0),
        ],
    )
    def test_raises_with_field(self, task, field, bad):
        import importlib

        from smartsuite.services.task_spec import TASK_SPECS

        _, target, feats = BATCH[task]
        func_path = next(s.func_path for s in TASK_SPECS if s.key == task)
        mod_name, fn_name = func_path.split(":", 1)
        fn = getattr(importlib.import_module(mod_name), fn_name)
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task=task,
                    data=_frame(),
                    target_col=target,
                    feature_cols=feats,
                    params={field: bad},
                )
            )
        assert ei.value.field_name == field


class TestRegressionIsNotMigrated:
    """记录 `regression` 的现状：`model_type` 是**未接线的参数**。"""

    def test_regression_function_ignores_all_params(self):
        """`regression_analysis()` 不读取任何 `params`（AST 扫描）。

        而 `DEFAULT_PARAMS["regression"] = {"model_type": "linear"}` —— 即
        前端能选 `model_type`，引擎完全不看。**这是真实不一致**，
        本轮按"精准修改"原则不处理（需先确认它该被读还是该从默认值移除）。
        """
        import ast
        import importlib
        from pathlib import Path

        src = Path(importlib.import_module("smartsuite.engine.doe_opt.regression").__file__)
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "regression_analysis":
                reads = {
                    sub.args[0].value
                    for sub in ast.walk(node)
                    if isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                }
                assert reads == set(), f"regression_analysis 现在读取了 {reads}；请更新本用例与计划"
                return
        pytest.fail("未找到 regression_analysis")

    def test_regression_now_has_a_passthrough_spec(self):
        """**本用例已随进度更新**：`regression` 于第二十七轮补了 Spec。

        当时（第二十四轮）它确实没有 Spec，本用例断言 `is None` 是"钉住现状"；
        现在三个任务全部声明完毕，断言改为"有 Spec 且 `model_type` 是透传字段"。
        这正是"钉住现状"类用例的预期生命周期 —— 改动时它会失败并提醒更新。
        """
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("regression")
        assert spec is not None
        assert "model_type" in spec.field_names
