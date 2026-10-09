"""批量迁移第九批（阶段 P4 步骤③收尾，第二十七轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 3 个任务 —— 迁完即支撑**步骤④**（删前端平行字典）

实测：派生的标签/提示覆盖 **90/114 个参数槽位**，未覆盖的 25 个**全部**来自
这三个任务（`doe_design` 7 个、`inverse_solve` 17 个、`regression` 1 个）。
故步骤④ 的前提就是迁完它们。

| 任务 | 参数 | 校验策略 |
|:---|:---|:---|
| `doe_design` | 8 个 | **完整迁移**（抛 `ParamValidationError`） |
| `inverse_solve` | 18 个 | **声明但不校验**（透传）—— 见下 |
| `regression` | `model_type` | 透传（未接线的参数） |

## `inverse_solve` 为什么**不**做批量拒绝

实测它的参数处理（`engine/inverse/_params.py`）**已经是契约要求的"可见降级"**：

```
model='bogus'       → 「参数「model」取值无效（bogus），可选：auto/linear/poly/gpr/gbm/rate」
weight_mode='bogus' → 「参数「weight_mode」取值无效（'bogus'），已回退默认 std」
max_starts=0        → 「参数「max_starts」=0 应为正整数，已按 1 处理」
```

即：**每条降级都写进了用户可见的 `messages`**（B2/B3 契约），而不是静默改写。
这比"批量拒绝"更贴合反演求解的交互场景（用户在试参数，一次说清所有可调项
比逐个报错更好）。故本轮**只声明标签/提示以支撑步骤④ 的标签派生，
不改变它的校验语义** —— 无校验器即透传。

## `doe_design` 迁移顺带修掉的「静默降级 / 错误归因」

| 参数 | 迁移前**实测**行为 |
|:---|:---|
| `center_points` | `-1`/`2.5`/`"abc"` **都 `ok`** —— 非 BB/CCD 分支完全不读它；BB/CCD 分支 `int(2.5)` 静默截断 |
| `n_runs` | `0`/`1`/`"abc"` **都 `ok`**（非 fractional/PB 分支不读它） |
| `replicates` | `2.5` → `ok`（`int(2.5)` 静默截断为 2） |
| `seed` | `-1` → 被报成「**数据格式或数值范围不符合分析要求**」——真实原因是 `np.random.RandomState(-1)` 抛 `Seed must be between 0 and 2**32-1`（**错误归因**） |
| `alpha` | `inf` → `ok`（`_is_num(inf) and inf > 0` 为真） |
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 81) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "y": 3.0 * x1 - 1.5 * x2 + rng.normal(0, 0.3, n),
            "x1": x1,
            "x2": x2,
            "t": np.arange(n, dtype=float),
            "g": (["A", "B"] * (n // 2))[:n],
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


#: `doe_design` 的 2 水平因子（全因子/部分因子/PB/taguchi）
_F2 = [{"name": "A", "levels": [1, 2]}, {"name": "B", "levels": [1, 2]}]
#: 3 水平**数值**因子（ccd 需 2-10 个）
_F3 = [{"name": "A", "levels": [1.0, 2.0, 3.0]}, {"name": "B", "levels": [1.0, 2.0, 3.0]}]
#: 3 水平**数值**因子 ×3（box_behnken 需 3-12 个 —— 我首版用 _F3 的 2 个，被引擎拒绝）
_F3B = [
    {"name": "A", "levels": [1.0, 2.0, 3.0]},
    {"name": "B", "levels": [1.0, 2.0, 3.0]},
    {"name": "C", "levels": [1.0, 2.0, 3.0]},
]


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", ["doe_design", "inverse_solve", "regression"])
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", ["doe_design", "inverse_solve", "regression"])
    def test_defaults_match_default_params(self, task):
        """主防线：`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 精确相等。"""
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        assert spec.defaults() == DEFAULT_PARAMS[task], (
            f"{task}: {spec.defaults()} != {DEFAULT_PARAMS[task]}"
        )

    @pytest.mark.parametrize("task", ["doe_design", "inverse_solve", "regression"])
    def test_no_required_fields(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task).required_fields() == [], task


class TestDerivationCoversEverySlot:
    """**步骤④ 的前置断言** —— 这是"能否删前端手写字典"的判据。"""

    def test_every_default_param_slot_has_a_derived_label(self):
        """派生的标签必须覆盖全部 114 个默认参数槽位。

        只要有一个槽位没被覆盖，删掉前端字典就会让那个参数在界面上没有标签。
        """
        from smartsuite.services.param_labels import derive_param_labels
        from smartsuite.services.task_spec import TASK_SPECS

        labels = derive_param_labels()
        missing: list[str] = []
        for spec in TASK_SPECS:
            for name in DEFAULT_PARAMS.get(spec.key, {}):
                # 任务级键优先，其次全局键（与前端取值顺序一致）
                if f"{name}@{spec.key}" in labels or name in labels:
                    continue
                missing.append(f"{name}@{spec.key}")
        assert missing == [], f"以下槽位未被派生标签覆盖，删前端字典会丢标签: {missing}"

    def test_every_derived_label_is_non_empty(self):
        from smartsuite.services.param_labels import derive_param_labels

        bad = {k: v for k, v in derive_param_labels().items() if not str(v).strip()}
        assert bad == {}, f"派生标签不得为空: {bad}"


class TestDoeDesign:
    @pytest.mark.parametrize(
        "method,factors",
        [
            ("full_factorial", _F2),
            ("fractional_factorial", _F2),
            ("plackett_burman", _F2),
            ("taguchi", _F2),
            ("box_behnken", _F3B),
            ("ccd", _F3),
        ],
    )
    def test_methods_still_work(self, method, factors):
        r = _via("doe_design", {"method": method, "factors": factors})
        assert r.status == "ok", f"{method}: {r.messages}"

    @pytest.mark.parametrize("bad", ["bogus", "FULL_FACTORIAL_", "ccd_"])
    def test_method_rejected_with_options(self, bad):
        r = _via("doe_design", {"method": bad, "factors": _F2})
        assert r.status == "error", f"method={bad!r} 应被拒绝"
        assert any("method" in m or "方法" in m for m in r.messages), r.messages

    @pytest.mark.parametrize("ok", ["rotatable", "orthogonal", "face", 1.0, 2.5])
    def test_alpha_valid(self, ok):
        r = _via("doe_design", {"method": "ccd", "factors": _F3, "alpha": ok})
        assert r.status == "ok", f"alpha={ok!r}: {r.messages}"

    @pytest.mark.parametrize("bad", [0, -1, "bogus", "abc", float("nan"), float("inf")])
    def test_alpha_rejected(self, bad):
        """`inf` 此前被接受（`_is_num(inf) and inf > 0` 为真）—— 已修。"""
        r = _via("doe_design", {"method": "ccd", "factors": _F3, "alpha": bad})
        assert r.status == "error", f"alpha={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [0, 1, 3, 10])
    def test_center_points_valid(self, ok):
        r = _via("doe_design", {"method": "ccd", "factors": _F3, "center_points": ok})
        assert r.status == "ok", f"center_points={ok}: {r.messages}"

    @pytest.mark.parametrize("bad", [-1, 2.5, "abc", float("nan")])
    def test_center_points_rejected_after_migration(self, bad):
        """**行为改进**：迁移前 `-1`/`2.5`/`"abc"` 在非 BB/CCD 分支**完全不读**，
        在 BB/CCD 分支 `int(2.5)` 静默截断为 2。"""
        r = _via("doe_design", {"method": "ccd", "factors": _F3, "center_points": bad})
        assert r.status == "error", f"center_points={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [1, 2, 5])
    def test_replicates_valid(self, ok):
        r = _via("doe_design", {"factors": _F2, "replicates": ok})
        assert r.status == "ok", f"replicates={ok}: {r.messages}"

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "abc"])
    def test_replicates_rejected(self, bad):
        """`2.5` 此前被 `int()` 静默截断为 2。"""
        r = _via("doe_design", {"factors": _F2, "replicates": bad})
        assert r.status == "error", f"replicates={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [0, 42, 1000])
    def test_seed_valid(self, ok):
        r = _via("doe_design", {"factors": _F2, "seed": ok})
        assert r.status == "ok", f"seed={ok}: {r.messages}"

    @pytest.mark.parametrize("bad", [-1, 1.5, "abc", float("nan")])
    def test_seed_rejected_with_parameter_message(self, bad):
        """**修掉一处错误归因**：`seed=-1` 迁移前报
        「数据格式或数值范围不符合分析要求」，真实原因是
        `np.random.RandomState(-1)` 抛 `Seed must be between 0 and 2**32-1`。
        """
        r = _via("doe_design", {"factors": _F2, "seed": bad})
        assert r.status == "error", f"seed={bad!r} 应被拒绝"
        joined = " ".join(r.messages)
        assert "seed" in joined or "随机种子" in joined, joined
        assert "数据格式" not in joined, f"不得归因为数据问题: {joined}"

    @pytest.mark.parametrize("ok", [4, 8])
    def test_n_runs_valid(self, ok):
        """`n_runs` 必须足够装下所有因子（正交表要求 2^n-1 >= 因子数）。

        `n_runs=1` 装不下 2 个因子 → 报「因子数(2)超过 2^n-1(0)」。
        那是**数据前置约束**，不是参数非法，故本用例从 4 起（我首版含 1，属断言错层）。
        """
        r = _via("doe_design", {"method": "fractional_factorial", "factors": _F2, "n_runs": ok})
        assert r.status == "ok", f"n_runs={ok}: {r.messages}"

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "abc"])
    def test_n_runs_rejected_after_migration(self, bad):
        """**行为改进**：迁移前完全不校验（非 fractional/PB 分支甚至不读）。"""
        r = _via("doe_design", {"method": "fractional_factorial", "factors": _F2, "n_runs": bad})
        assert r.status == "error", f"n_runs={bad!r} 应被拒绝"

    def test_randomize_accepts_bool_and_string(self):
        """`randomize` 是**混合类型**参数（默认 `True` 是布尔）→ 透传。"""
        for value in (True, False, "true", "false"):
            r = _via("doe_design", {"factors": _F2, "randomize": value})
            assert r.status == "ok", f"randomize={value!r}: {r.messages}"

    def test_factors_is_passthrough(self):
        """`factors` 是结构化列表（`[{name, levels}]`）→ 透传，由引擎内专门解析。"""
        r = _via("doe_design", {"factors": _F2})
        assert r.status == "ok", r.messages
        r2 = _via("doe_design", {"factors": None})
        assert r2.status == "error", r2.messages


class TestInverseSolveDeclaredButNotValidated:
    """`inverse_solve` 只声明标签/提示，**不接管校验** —— 它的降级本就是可见的。"""

    def test_all_18_params_have_labels(self):
        """18 个参数都必须有中文标签（步骤④ 删前端字典的前提）。"""
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("inverse_solve")
        labels = spec.labels()
        expected = set(DEFAULT_PARAMS["inverse_solve"])
        assert set(labels) == expected, f"缺标签: {expected - set(labels)}"
        for name, label in labels.items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), (name, label)

    def test_model_is_a_choice_with_chinese_labels(self):
        from smartsuite.services.param_labels import spec_for_task

        validator = spec_for_task("inverse_solve")._fields["model"].validator
        opts = dict(validator.options())
        assert set(opts) == {"auto", "linear", "poly", "gpr", "gbm", "rate"}, sorted(opts)
        for value, label in opts.items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), (value, label)

    def test_weight_mode_is_a_choice_with_chinese_labels(self):
        from smartsuite.services.param_labels import spec_for_task

        validator = spec_for_task("inverse_solve")._fields["weight_mode"].validator
        opts = dict(validator.options())
        assert set(opts) == {"std", "range", "none"}, sorted(opts)

    def test_engine_degradations_are_user_visible(self):
        """**本轮确认**：`inverse_solve` 的每条降级都写进了用户可见的 `messages`。

        这正是 boundary-contract 要求的 B2/B3 可见性，故**不需要**改成批量拒绝。
        本用例把这条性质钉住（若将来改成静默改写，它会失败）。
        """
        cases = [
            ({"model": "bogus"}, "model"),
            ({"weight_mode": "bogus"}, "weight_mode"),
            ({"max_starts": 0}, "max_starts"),
        ]
        for params, key in cases:
            r = _via("inverse_solve", params)
            joined = " ".join(r.messages)
            assert key in joined, f"{key} 的降级必须在 messages 里可见: {r.messages}"

    def test_invalid_params_do_not_raise(self):
        """透传字段 → 引擎不抛 `ParamValidationError`（校验留在 `_params.py`）。

        真实值断言（原为恒真断言 `status in ("ok","error")`）：逐参数钉住**方向**——
        `model` 非法取值属硬错误（拒绝并列出可选值），`weight_mode` 与负 `reg_lambda`
        属**可见降级**（回退/透传后继续）。

        ⚠️ 本用例**不能**复用 `_via()` 的 `_frame()`：那张表没有
        `Incoming*/Variable*/Output*` 角色列，`inverse_solve` 会因"未识别到输出列"
        直接 error —— 原断言 `status in ("ok","error")` 正是靠这个**无关错误**通过的
        （假绿）。故这里单独造一份角色列齐备的历史。
        """
        rng = np.random.default_rng(7)
        inc = rng.normal(1.1, 0.05, 40)
        u1 = rng.uniform(4.0, 8.0, 40)
        u2 = rng.uniform(2.0, 4.0, 40)
        history = pd.DataFrame(
            {
                "IncomingA": inc,
                "VariableU1": u1,
                "VariableU2": u2,
                "OutputY1": 1.3 - 0.06 * u2 + 0.05 * inc,
            }
        )

        def run(params: dict):
            return orchestrate(
                AnalysisRequest(
                    task="inverse_solve",
                    data=history,
                    target_col="",
                    feature_cols=[],
                    params=params,
                )
            )

        # ① model 非法 → 拒绝，且必须列出全部可选模型（用户据此改）
        r_model = run({"model": "bogus"})
        assert r_model.status == "error", r_model.messages
        msg = " ".join(r_model.messages)
        assert "参数「model」取值无效（bogus）" in msg, r_model.messages
        assert "auto/linear/poly/gpr/gbm/rate" in msg, r_model.messages

        # ② weight_mode 非法 → 继续，但必须披露已回退默认 std
        r_mode = run({"weight_mode": "bogus"})
        assert r_mode.status == "ok", r_mode.messages
        assert any("已回退默认 std" in m for m in r_mode.messages), r_mode.messages
        assert r_mode.metadata["model_choice"] == {"OutputY1": "linear"}, r_mode.metadata

        # ③ 负 reg_lambda → 透传（透传字段不做区间校验），结果仍可产出
        r_lam = run({"reg_lambda": -1})
        assert r_lam.status == "ok", r_lam.messages
        assert not any("取值无效" in m for m in r_lam.messages), r_lam.messages


class TestRegressionModelType:
    def test_model_type_is_an_unwired_param(self):
        """**本轮决策**：`regression.model_type` 是未接线的参数，声明为**透传**。

        AST 扫描证实 `regression_analysis()` **不读任何 params**（见第二十四轮台账）。
        修它有两个方向（补实现 / 删假参数），都需要产品判断，故本轮不改语义；
        但**必须**声明它 —— 否则步骤④ 删前端字典时 `model_type` 会丢标签。

        本用例把现状钉住：一旦它被接线，测试会失败并提醒更新计划。
        """
        base = _via("regression", {"model_type": "linear"})
        other = _via("regression", {"model_type": "quadratic"})
        assert base.status == "ok" and other.status == "ok", base.messages
        assert base.metadata == other.metadata, (
            "model_type 若开始影响结果，说明它已被接线 —— 请更新本用例与计划台账"
        )


class TestEngineRaises:
    @pytest.mark.parametrize(
        "field,bad",
        [
            ("method", "bogus"),
            ("replicates", 0),
            ("seed", -1),
            ("center_points", -1),
            ("n_runs", 0),
        ],
    )
    def test_doe_design_raises(self, field, bad):
        import importlib

        fn = importlib.import_module("smartsuite.engine.doe_opt.doe").doe_design
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task="doe_design",
                    data=_frame(),
                    target_col="y",
                    feature_cols=[],
                    params={"factors": _F3, field: bad},
                )
            )
        assert ei.value.field_name == field
