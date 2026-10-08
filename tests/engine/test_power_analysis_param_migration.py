"""`power_analysis` 参数校验的迁移对拍（阶段 P4 步骤③）。

契约：docs/governance/improvement-plan.md §六

## 为什么选 `power_analysis` 作本轮迁移对象

它是**参数最集中**的任务之一（10 个参数），且现有校验有明显可收敛之处：

- `alpha` 的区间检查**写了两遍**（第 43 行与第 78 行，`_safe_float` 之后又 float 一次）；
- `_safe_float` / `float()` / `np.isfinite` 三段式对 `effect_size` / `alpha` /
  `target_power` 各来一遍；
- 参数在多个分支里**反复重新读取**（`p0`/`p1`/`n_groups` 各出现 3 次）。

迁移到 `PARAM_SPEC` 后这些统一为一次校验。

## 覆盖范围

- **纯参数校验**（10 个参数的类型/区间/枚举）→ 迁移到 `Spec`；
- **依赖数据的校验**（如比例检验要求 p1 ≠ p0 之外的结构性检查）→ 留在引擎。

## 本轮发现的参数校验缺陷（修）

`effect_size=0` 有专门检查（"不能为 0"），但该检查**在 `current_n` 之前**；
若 `mode="achieved"` 且用户只给 `current_n`，`effect_size` 仍会走零值检查 ——
这是对的。真正的问题是：**`effect_size=0` 与 `alpha` 越界的报错顺序**
在 `_safe_float` 失败时**不可达**（先返回"值无效"），行为上自洽但代码冗余。

## 兼容性

参数校验失败改为**抛 `ParamValidationError`**（第十三轮建立的通路），
由 `orchestrator` 转成 `status="error"` + 中文文案。故本文件分两层断言。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.engine.root_cause.design import PARAM_SPEC, power_analysis
from smartsuite.services.orchestrator import orchestrate


def _frame(n: int = 60, seed: int = 7) -> pd.DataFrame:
    """带两组的连续数据（供 effect_size 等路径有数据可用）。"""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": np.concatenate([rng.normal(10, 1, n), rng.normal(11, 1, n)]),
            "g": ["A"] * n + ["B"] * n,
        }
    )


def _req(**params):
    return AnalysisRequest(
        task="power_analysis", data=_frame(), target_col="y", feature_cols=["g"], params=params
    )


def _via_orchestrator(**params):
    """经编排层执行 —— 对应 Web/CLI 用户实际看到的路径。"""
    return orchestrate(_req(**params))


class TestSpecContract:
    """`PARAM_SPEC` 的结构契约。"""

    def test_spec_declares_all_ten_params(self):
        assert set(PARAM_SPEC.field_names) == {
            "mode",
            "test_type",
            "effect_size",
            "alpha",
            "target_power",
            "current_n",
            "n_groups",
            "p0",
            "p1",
        }, PARAM_SPEC.field_names

    def test_no_required_fields(self):
        """全部参数可选（缺省走引擎默认值）—— power_analysis 可零参数运行。"""
        assert PARAM_SPEC.required_fields() == []

    def test_defaults_match_frontend_dictionary(self):
        """默认值必须与前端 `TASK_PARAMS`（现由 `/api/tasks` 下发）一致。"""
        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        d = PARAM_SPEC.defaults()
        assert d == DEFAULT_PARAMS["power_analysis"], f"Spec 默认值 {d} 与 DEFAULT_PARAMS 不一致"

    def test_labels_are_chinese(self):
        for name, label in PARAM_SPEC.labels().items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), f"{name} → {label!r}"


class TestEnumsAndRange:
    """枚举与区间校验（迁移目标）。"""

    @pytest.mark.parametrize("mode", ["required_n", "achieved"])
    def test_valid_modes(self, mode):
        r = _via_orchestrator(mode=mode, test_type="ttest", current_n=30)
        assert r.status == "ok", r.messages

    def test_invalid_mode_rejected_with_options(self):
        r = _via_orchestrator(mode="nope")
        assert r.status == "error"
        msg = " ".join(r.messages)
        assert "模式" in msg, msg
        assert "required_n" in msg and "achieved" in msg, msg

    @pytest.mark.parametrize("test_type", ["ttest", "anova", "proportion"])
    def test_valid_test_types(self, test_type):
        r = _via_orchestrator(test_type=test_type)
        assert r.status == "ok", r.messages

    def test_invalid_test_type_rejected_with_options(self):
        r = _via_orchestrator(test_type="zzz")
        assert r.status == "error"
        msg = " ".join(r.messages)
        assert "检验类型" in msg, msg
        for opt in ("ttest", "anova", "proportion"):
            assert opt in msg, msg

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5])
    def test_alpha_out_of_range_rejected(self, bad):
        """α 必须在 (0,1) 开区间。"""
        r = _via_orchestrator(alpha=bad)
        assert r.status == "error", f"alpha={bad} 应被拒绝"

    @pytest.mark.parametrize("bad", [0, 1, -0.5, 2.0])
    def test_target_power_out_of_range_rejected(self, bad):
        """目标功效必须在 (0,1) 开区间。"""
        r = _via_orchestrator(target_power=bad)
        assert r.status == "error", f"target_power={bad} 应被拒绝"

    def test_effect_size_zero_rejected(self):
        """效应量 0 无意义（无法检测零效应），且 statsmodels 会抛异常。"""
        r = _via_orchestrator(effect_size=0)
        assert r.status == "error"
        assert any("effect_size" in m or "效应量" in m for m in r.messages), r.messages

    def test_negative_effect_size_allowed(self):
        """负效应量合法（方向由符号表示，绝对值参与计算）。"""
        r = _via_orchestrator(effect_size=-0.5)
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("field", ["effect_size", "alpha", "target_power"])
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan", "inf", "abc"])
    def test_non_finite_or_non_numeric_rejected(self, field, bad):
        """NaN/Inf/非数值必须显式拒绝（sentinel-contract L1）。"""
        r = _via_orchestrator(**{field: bad})
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"


class TestProportionParams:
    """比例检验的 p0 / p1。"""

    def test_valid_proportions(self):
        r = _via_orchestrator(test_type="proportion", p0=0.3, p1=0.5)
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2, 0, 1])
    def test_proportion_out_of_range_rejected(self, bad):
        """p0/p1 必须在 **(0,1) 开区间**内（与既有实现一致）。

        0 与 1 也被拒绝：功效公式在 p 为 0/1 时分母退化（`p(1-p)=0`）。
        迁移时我一度写成闭区间 `[0,1]`，正是这条用例把差异抓出来。
        """
        r = _via_orchestrator(test_type="proportion", p0=bad)
        assert r.status == "error", f"p0={bad} 应被拒绝"
        r2 = _via_orchestrator(test_type="proportion", p1=bad)
        assert r2.status == "error", f"p1={bad} 应被拒绝"

    def test_equal_proportions_rejected(self):
        """p0 == p1 必须拒绝：零比例差无法检测（**既有行为，不是缺陷**）。

        原实现有专门检查 `abs(p1 - p0) < 1e-9` 并给出明确原因。注意这与
        "参数合法但不显著"不同 —— 它是**输入无意义**，故拒绝而非返回低功效。
        """
        for p0, p1 in ((0.5, 0.5), (0.3, 0.3)):
            r = _via_orchestrator(test_type="proportion", p0=p0, p1=p1)
            assert r.status == "error", f"p0=p1={p0} 应被拒绝"
            assert any("相等" in m or "零比例差" in m for m in r.messages), r.messages

    def test_achieved_power_alias_accepted(self):
        """`achieved_power` 是 `achieved` 的兼容别名（Web UI 曾用此写法）。"""
        r = _via_orchestrator(mode="achieved_power", current_n=30)
        assert r.status == "ok", r.messages
        assert r.metadata.get("mode") == "achieved", "别名应归一化为 achieved（否则下游分支看不到）"


class TestIntegerParams:
    """current_n / n_groups。"""

    def test_current_n_must_be_positive_integer(self):
        assert _via_orchestrator(mode="achieved", current_n=30).status == "ok"
        for bad in (0, -5):
            assert _via_orchestrator(mode="achieved", current_n=bad).status == "error", bad

    def test_current_n_rejects_non_integer(self):
        for bad in (5.5, "abc", float("inf")):
            assert _via_orchestrator(mode="achieved", current_n=bad).status == "error", bad

    def test_n_groups_must_be_at_least_two(self):
        """ANOVA 的组数至少 2。"""
        assert _via_orchestrator(test_type="anova", n_groups=3).status == "ok"
        for bad in (1, 0, -2):
            assert _via_orchestrator(test_type="anova", n_groups=bad).status == "error", bad


class TestEngineRaisesParamValidationError:
    """引擎层直接调用时抛异常（第十三轮建立的通路）。"""

    def test_bad_alpha_raises_with_code(self):
        with pytest.raises(ParamValidationError) as ei:
            power_analysis(_req(alpha=2.0))
        assert ei.value.code.startswith("E_PARAM_")
        assert ei.value.field_name == "alpha"

    def test_bad_mode_raises(self):
        with pytest.raises(ParamValidationError) as ei:
            power_analysis(_req(mode="nope"))
        assert ei.value.field_name == "mode"

    def test_valid_params_do_not_raise(self):
        r = power_analysis(_req(effect_size=0.5, alpha=0.05, target_power=0.8))
        assert r.status == "ok", r.messages
