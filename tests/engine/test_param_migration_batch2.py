"""批量迁移第二批（阶段 P4 步骤③，第二十一轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 4 个任务（都是"单参数"，迁移成本最低）

| 任务 | 参数 | 计划 | 共享字段 |
|:---|:---|:---|:---|
| `doe_analysis` | `alpha` | `Finite(gt=0,lt=1)`，默认 0.05 | ✅ `ALPHA` |
| `trend_forecast` | `forecast_steps` | `Integer(min=1,max=1000)`，默认 5 | 自声明 |
| `vif` | `threshold` | `Finite(gt=0)`，默认 5 | 自声明 |
| `distribution_summary` | `bins` | `Integer(min=1)`，默认 `None` | 自声明 |

## 迁移顺带修掉的两处「静默降级」（boundary-contract 明令禁止）

实测发现（迁移前基线）：

1. **`vif.threshold` 完全没有校验**：
   - `threshold='abc'` → `_safe_float` 静默回落到默认 5（用户以为用了自己的阈值）；
   - `threshold=inf` → `vif_data["VIF"] > inf` 恒假 → 判定表全空；
     且 `if threshold <= xmax` 恒假 → **阈值参考线不显示**。
   - `threshold=-1` → 所有变量都被判为"高 VIF"。
   迁移后：非数值/非有限值明确拒绝（B0），`gt=0` 拒绝无意义的非正阈值。

2. **`distribution_summary.bins` 对非整数静默回落自动分箱**：
   `bins='abc'` 走 `except (ValueError, TypeError)` → 静默用自动值。
   迁移后：明确拒绝，提示应为正整数。**`None`（未提供）仍走自动分箱 —— 那是文档化行为，保持不变。**

两处都是"有意改变行为"，故在此文件显式记录，并各配一条对拍用例。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _numeric(n: int = 60, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 1.5, n),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "g": (["A", "B"] * (n // 2))[:n],
        }
    )


def _via_orchestrator(task: str, params: dict, target: str = "y", features=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=_numeric(),
            target_col=target,
            feature_cols=features if features is not None else ["g"],
            params=params,
        )
    )


def _run_engine(task: str, params: dict, target: str = "y", features=None):
    import importlib

    from smartsuite.services.task_spec import TASK_SPECS

    func_path = next(s.func_path for s in TASK_SPECS if s.key == task)
    mod_name, fn_name = func_path.split(":", 1)
    fn = getattr(importlib.import_module(mod_name), fn_name)
    return fn(
        AnalysisRequest(
            task=task,
            data=_numeric(),
            target_col=target,
            feature_cols=features if features is not None else ["g"],
            params=params,
        )
    )


#: (maker 无需数据生成器，本批都用 `_numeric`)
BATCH = {
    "doe_analysis": ({"alpha": 0.05}, ["g"]),
    "trend_forecast": ({"forecast_steps": 5}, []),
    "vif": ({"threshold": 5}, ["x1", "x2"]),
    "distribution_summary": ({"bins": 15}, []),
}


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_match_default_params(self, task):
        """`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 一致（批量迁移的主防线）。"""
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        assert spec.defaults() == DEFAULT_PARAMS[task], (
            f"{task}: {spec.defaults()} != {DEFAULT_PARAMS[task]}"
        )

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_no_required_fields(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task).required_fields() == [], task


class TestValidParamsStillWork:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_explicit_params(self, task):
        params, feats = BATCH[task]
        r = _via_orchestrator(task, params, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_default_params(self, task):
        _, feats = BATCH[task]
        r = _via_orchestrator(task, {}, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"

    @pytest.mark.parametrize("ok", [0.001, 0.05, 0.5, 0.999])
    def test_doe_analysis_alpha_valid(self, ok):
        r = _via_orchestrator("doe_analysis", {"alpha": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("ok", [1, 5, 1000])
    def test_trend_forecast_steps_valid(self, ok):
        r = _via_orchestrator("trend_forecast", {"forecast_steps": ok}, features=[])
        assert r.status == "ok", r.messages

    def test_distribution_summary_bins_none_keeps_auto(self):
        """`bins` 不给（`None`）→ 走**自动分箱**（文档化行为，迁移后必须保持）。"""
        r_absent = _via_orchestrator("distribution_summary", {}, features=[])
        r_none = _via_orchestrator("distribution_summary", {"bins": None}, features=[])
        assert r_absent.status == "ok" and r_none.status == "ok"


class TestRejections:
    """拒绝路径（含两处**有意**的行为改进）。"""

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_doe_analysis_alpha_rejected(self, bad):
        r = _via_orchestrator("doe_analysis", {"alpha": bad}, features=["g"])
        assert r.status == "error", f"alpha={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [0, -1, 1001, 5.5, "abc", float("inf")])
    def test_trend_forecast_steps_rejected(self, bad):
        r = _via_orchestrator("trend_forecast", {"forecast_steps": bad}, features=[])
        assert r.status == "error", f"forecast_steps={bad!r} 应被拒绝"

    def test_trend_forecast_steps_upper_bound_is_inclusive(self):
        """边界值 1000 通过、1001 拒绝 —— 钉住"含上界"。"""
        assert _via_orchestrator("trend_forecast", {"forecast_steps": 1000}).status == "ok"
        assert _via_orchestrator("trend_forecast", {"forecast_steps": 1001}).status == "error"

    @pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), "abc"])
    def test_vif_threshold_rejected_after_migration(self, bad):
        """**行为改进 ①**：`vif.threshold` 此前**完全没有校验**。

        迁移前实测：`'abc'` 静默回落默认 5；`inf` 使判定表全空且阈值参考线不显示；
        `-1` 把全部变量判为高 VIF。三者都是"静默降级"（boundary-contract 明令禁止）。
        """
        r = _via_orchestrator("vif", {"threshold": bad}, target="", features=["x1", "x2"])
        assert r.status == "error", f"threshold={bad!r} 应被拒绝（迁移前被静默接受）"

    @pytest.mark.parametrize("ok", [0.5, 1, 5, 100])
    def test_vif_threshold_valid(self, ok):
        r = _via_orchestrator("vif", {"threshold": ok}, target="", features=["x1", "x2"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [0, -3, 2.5, "abc", float("inf")])
    def test_distribution_summary_bins_rejected_after_migration(self, bad):
        """**行为改进 ②**：`bins` 非整数此前静默回落自动分箱。

        迁移前实测：`bins='abc'` 走 `except (ValueError, TypeError)` → 静默用自动值，
        用户以为自己设了 15 个箱。迁移后明确拒绝（`None` 仍走自动）。
        """
        r = _via_orchestrator("distribution_summary", {"bins": bad}, features=[])
        assert r.status == "error", f"bins={bad!r} 应被拒绝（迁移前被静默回落）"


class TestEngineRaises:
    """引擎层直接调用时抛 `ParamValidationError`。"""

    @pytest.mark.parametrize(
        "task,field,feats",
        [
            ("doe_analysis", "alpha", ["g"]),
            ("trend_forecast", "forecast_steps", []),
            ("distribution_summary", "bins", []),
        ],
    )
    def test_bad_value_raises_with_code(self, task, field, feats):
        bad = {"alpha": 2.0, "forecast_steps": 0, "bins": 0}[field]
        with pytest.raises(ParamValidationError) as ei:
            _run_engine(task, {field: bad}, features=feats)
        assert ei.value.field_name == field
        assert ei.value.code.startswith("E_PARAM_")

    def test_vif_bad_threshold_raises(self):
        with pytest.raises(ParamValidationError) as ei:
            _run_engine("vif", {"threshold": "abc"}, target="", features=["x1", "x2"])
        assert ei.value.field_name == "threshold"


class TestSharedFieldReuse:
    @pytest.mark.parametrize(
        "module,expected",
        [
            ("smartsuite.engine.doe_opt.doe", "ALPHA"),
        ],
    )
    def test_module_references_shared_constant(self, module, expected):
        import importlib
        from pathlib import Path

        src = Path(importlib.import_module(module).__file__).read_text(encoding="utf-8")
        assert f"import {expected}" in src or f", {expected}" in src, (
            f"{module} 未引用共享常量 {expected}"
        )
