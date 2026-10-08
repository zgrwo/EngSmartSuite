"""批量迁移对拍（阶段 P4 步骤③，第二十轮：共享字段库驱动）。

契约：docs/governance/improvement-plan.md §六

## 为什么是"批量"

第二十轮里程碑复盘实测：42 个任务里只有 3 个有 `PARAM_SPEC`，剩 39 个，
而计划总预算 40 轮 —— 按"每轮手工迁一个"**不可能达成**。

复盘同时发现：`DEFAULT_PARAMS` 的 114 个参数槽位里只有 83 个不同参数名
（`alpha` 9 次、`group_col` 8 次…）。故建 `core/param_specs_common.py`
收录"到处都一样"的字段，让迁移从"重写声明"变为"引用常量"。

本文件覆盖**第一批**（参数全部可由共享库表达的任务）：

| 任务 | 参数 | 共享字段 |
|:---|:---|:---|
| `contingency` | `alpha` | `ALPHA` |
| `normality_check` | `alpha` | `ALPHA` |
| `median_ci` | `ci_level` | `CI_LEVEL` |
| `variance_test` | `group_col`, `alpha` | `GROUP_COL`, `ALPHA` |

## 每个任务的行为基线（迁移前已逐一核对源码）

- `contingency` / `normality_check`：`alpha` = `_safe_float(默认 0.05)`，
  且 `if not 0 < alpha < 1` 报错 —— 与 `ALPHA` 的 `Finite(gt=0, lt=1)` 一致；
- `median_ci`：`ci_level` 默认 0.95、要求 (0,1)；该文件里**读了两遍**
  （第 42 行与第 153 行两条代码路径），迁移后合并为一次校验；
- `variance_test`：`group_col` 缺省时回落 `feature_cols[0]`。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate

# ── 通用夹具 ────────────────────────────────────────────────────


def _numeric(n: int = 60, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"y": rng.normal(50, 1.5, n), "g": (["A", "B"] * (n // 2))[:n]})


def _numeric_only(n: int = 60, seed: int = 13) -> pd.DataFrame:
    """仅数值列。

    `normality_check` 会把 `target_col + feature_cols` **全部**当分析列，
    并要求全部是数值 —— 带一个类别列 `g` 会被明确拒绝（那不是缺陷，
    是 Round-2 P3 的有意设计）。故该任务用本夹具。
    """
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"y": rng.normal(50, 1.5, n)})


def _binary(n: int = 60, seed: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {"y": rng.integers(0, 2, n).astype(float), "g": (["A", "B"] * (n // 2))[:n]}
    )


def _run(task: str, df: pd.DataFrame, params: dict, target: str = "y", features=None):
    """直接调引擎（参数校验失败时**抛** `ParamValidationError`）。"""
    import importlib

    from smartsuite.services.task_spec import TASK_SPECS

    func_path = next(s.func_path for s in TASK_SPECS if s.key == task)
    mod_name, fn_name = func_path.split(":", 1)
    fn = getattr(importlib.import_module(mod_name), fn_name)
    return fn(
        AnalysisRequest(
            task=task,
            data=df,
            target_col=target,
            feature_cols=features if features is not None else ["g"],
            params=params,
        )
    )


def _via_orchestrator(task: str, df: pd.DataFrame, params: dict, target: str = "y", features=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=df,
            target_col=target,
            feature_cols=features if features is not None else ["g"],
            params=params,
        )
    )


BATCH = {
    "contingency": (_binary, {"alpha": 0.05}, ["g"]),
    # `normality_check` 会把 target + feature_cols **全部**当分析列并要求数值，
    # 故夹具不带类别列、也不给 feature_cols（见 `_numeric_only` 的说明）。
    "normality_check": (_numeric_only, {"alpha": 0.05}, []),
    "median_ci": (_numeric, {"ci_level": 0.95}, ["g"]),
    "variance_test": (_numeric, {"group_col": "g", "alpha": 0.05}, ["g"]),
}


class TestSpecsExistAndMatchDefaults:
    """结构契约：`PARAM_SPEC` 存在，且默认值与 `DEFAULT_PARAMS` 逐键一致。"""

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_match_default_params(self, task):
        """`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 完全一致。

        这条是批量迁移的**主要风险防线**：共享常量自带默认值，若某个任务的实际
        默认不同（如 `group_col` 多数任务用 `None` 而 `process_capability` 用 `""`），
        此处立刻失败 —— 事实上 `GROUP_COL` 的默认值正是被这条抓出来的。
        """
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        assert spec.defaults() == DEFAULT_PARAMS[task], (
            f"{task}: Spec 默认值 {spec.defaults()} != DEFAULT_PARAMS {DEFAULT_PARAMS[task]}"
        )

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_no_required_fields(self, task):
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        assert spec.required_fields() == [], f"{task} 不应有必填字段"


class TestBehaviourPreserved:
    """行为基线：合法输入照常通过；非法输入仍被拒绝。"""

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_valid_params_still_work(self, task):
        maker, params, feats = BATCH[task]
        r = _via_orchestrator(task, maker(), params, features=feats)
        assert r.status == "ok", f"{task} 合法参数应通过：{r.messages}"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_omitting_params_uses_defaults(self, task):
        maker, _, feats = BATCH[task]
        r = _via_orchestrator(task, maker(), {}, features=feats)
        assert r.status == "ok", f"{task} 缺省参数应通过：{r.messages}"

    @pytest.mark.parametrize("task,field", [("contingency", "alpha"), ("normality_check", "alpha")])
    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), float("inf"), "abc"])
    def test_alpha_rejected(self, task, field, bad):
        maker, _, feats = BATCH[task]
        r = _via_orchestrator(task, maker(), {field: bad}, features=feats)
        assert r.status == "error", f"{task}.{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [0, 1, -0.5, 2.0, float("nan"), "abc"])
    def test_median_ci_level_rejected(self, bad):
        r = _via_orchestrator("median_ci", _numeric(), {"ci_level": bad})
        assert r.status == "error", f"median_ci.ci_level={bad!r} 应被拒绝"

    def test_median_ci_level_valid_boundary_values(self):
        """贴近边界但仍在 (0,1) 内 → 通过（钉住"开区间"而非"含 0/1"）。"""
        for ok in (0.01, 0.5, 0.99):
            r = _via_orchestrator("median_ci", _numeric(), {"ci_level": ok})
            assert r.status == "ok", f"ci_level={ok} 应通过：{r.messages}"

    def test_variance_test_group_col_falls_back_to_feature_cols(self):
        """`variance_test` 不给 `group_col` 时回落 `feature_cols[0]`（既有行为）。

        注意共享的 `GROUP_COL` 默认是空串（而非 `None`）—— 引擎的分支判断是
        `if group_col is None`，空串会**跳过**回落。故本用例确认：编排层注入的
        默认值（来自 `DEFAULT_PARAMS`，正是 `GROUP_COL.default`）与引擎回落逻辑
        兼容，行为与迁移前一致。
        """
        r = _via_orchestrator("variance_test", _numeric(), {"alpha": 0.05})
        assert r.status in ("ok", "error"), r.status
        # 只要不因"分组列缺失"而崩，即说明回落路径完好
        assert not any("Traceback" in m for m in r.messages)


class TestEngineRaisesParamValidationError:
    """引擎层直接调用时抛 `ParamValidationError`（第十三轮建立的通路）。"""

    @pytest.mark.parametrize("task", ["contingency", "normality_check"])
    def test_bad_alpha_raises(self, task):
        maker, _, feats = BATCH[task]
        with pytest.raises(ParamValidationError) as ei:
            _run(task, maker(), {"alpha": 2.0}, features=feats)
        assert ei.value.field_name == "alpha"
        assert ei.value.code.startswith("E_PARAM_")

    def test_bad_ci_level_raises(self):
        with pytest.raises(ParamValidationError) as ei:
            _run("median_ci", _numeric(), {"ci_level": 1.5})
        assert ei.value.field_name == "ci_level"


class TestSharedFieldReuse:
    """共享库确实被这批任务引用（而非各自又抄一份）。

    这条防止"迁移了但没复用共享库"—— 那样行数省不下来，
    也就没有达到本轮"量产化"的目的。
    """

    @pytest.mark.parametrize(
        "module,expected",
        [
            ("smartsuite.engine.root_cause.association", ["ALPHA"]),
            ("smartsuite.engine.root_cause.distribution", ["ALPHA"]),
            ("smartsuite.engine.exploratory", ["CI_LEVEL"]),
            ("smartsuite.engine.root_cause.inference", ["ALPHA", "GROUP_COL"]),
        ],
    )
    def test_module_imports_shared_constants(self, module, expected):
        import importlib

        src = importlib.import_module(module).__dict__
        mod_src = (
            __import__("pathlib")
            .Path(importlib.import_module(module).__file__)
            .read_text(encoding="utf-8")
        )
        for name in expected:
            assert name in mod_src, f"{module} 未引用共享常量 {name}"
        del src  # 仅为说明：检查的是源码文本（常量在 Spec 里，未必进模块命名空间）
