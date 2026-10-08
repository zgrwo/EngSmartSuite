"""批量迁移第五批（阶段 P4 步骤③，第二十三轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 5 个任务

| 任务 | 参数 | 校验 |
|:---|:---|:---|
| `correlation` | `method`, `control_vars` | `Choice(pearson/spearman/kendall)`；控制变量透传 |
| `logistic_regression` | `threshold` | `Finite(gt=0, lt=1)`，默认 0.5 |
| `spc_nonparametric` | `side` | `Choice(two-sided/upper/lower)` |
| `spc_cusum` | `k`, `h`, `mu`, `sigma` | `k`/`h` = `Finite(gt=0)`；`mu`/`sigma` 可选 |
| `spc_ewma` | `lam`, `L`, `mu`, `sigma` | `lam` = `Finite(gt=0,lt=1)`；`L` = `Finite(gt=0)` |

## 枚举一律逐任务声明（本批 3 个 `Choice`）

`correlation.method`、`spc_nonparametric.side`、`tolerance_interval.side`
都是枚举，但**值集不同**（后者是容差区间方向）—— 这正是共享库
"不含任何枚举字段"的理由（见 `core/param_specs_common.py` 的判据表）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 41) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 1.5, n),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "flag": rng.integers(0, 2, n),
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
    "correlation": ({"method": "pearson"}, "y", ["x1", "x2"]),
    "logistic_regression": ({"threshold": 0.5}, "flag", ["x1", "x2"]),
    "spc_nonparametric": ({"side": "two-sided"}, "y", ["g"]),
    "spc_cusum": ({"k": 0.5, "h": 5.0, "group_col": "g"}, "y", ["g"]),
    "spc_ewma": ({"lam": 0.2, "L": 2.7, "group_col": "g"}, "y", ["g"]),
}


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_are_subset_of_default_params(self, task):
        """`Spec.defaults()` 的**每个键值**都必须与 `DEFAULT_PARAMS[task]` 相容。

        这里用"子集"而非"相等"：本批多个任务的 Spec **有意声明比
        `DEFAULT_PARAMS` 更多的字段** —— 例如 `spc_cusum` 的 `mu`/`sigma`
        是引擎支持的**可选显式覆盖**（用户不给则由数据估计），
        它们不在 `DEFAULT_PARAMS` 里（因为默认是"不指定"），但必须被 `Spec` 认识
        才能校验用户显式传入的值。

        这是对"默认值必须一致"主防线的**精确化**：缺省的键必须在两边一致；
        Spec 多出来的键必须是"可选覆盖"型（默认 `None`）。
        """
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        defaults = spec.defaults()
        dp = DEFAULT_PARAMS[task]
        for key, val in dp.items():
            if key in defaults:
                assert defaults[key] == val, (
                    f"{task}.{key}: Spec={defaults[key]!r} != DEFAULT={val!r}"
                )
        # Spec 多出的键必须是"可选覆盖"（默认 None），不得是必填或有默认值的普通参数
        extra = set(defaults) - set(dp)
        for key in extra:
            assert defaults[key] is None, (
                f"{task}.{key} 不在 DEFAULT_PARAMS 里，故必须是可选覆盖（默认 None），"
                f"实际 {defaults[key]!r}"
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


class TestEnumParams:
    @pytest.mark.parametrize("ok", ["pearson", "spearman", "kendall"])
    def test_correlation_method_valid(self, ok):
        r = _via("correlation", {"method": ok})
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["p", "kendal", "spearman_", "pearsons"])
    def test_correlation_method_rejected_with_options(self, bad):
        """非法方法名必须被拒，且提示列出**全部**可选值。

        注意本用例**不含** `"SPEARMAN"`（大小写变体，应被接受）与 `""`
        （编排层归一为「未提供」→ 用默认值）—— 两者由下面的用例覆盖。
        这里刻意把它们分开：混在一个"拒绝"清单里会掩盖归一层语义。
        """
        r = _via("correlation", {"method": bad})
        assert r.status == "error", f"method={bad!r} 应被拒绝"
        joined = " ".join(r.messages)
        for opt in ("pearson", "spearman", "kendall"):
            assert opt in joined, f"提示应列出可选值 {opt}: {joined}"

    @pytest.mark.parametrize("ok", ["Pearson", "SPEARMAN", "Kendall"])
    def test_correlation_method_is_case_insensitive(self, ok):
        """`Choice` 自带大小写归一 —— 合法值的大小写变体应被接受。"""
        r = _via("correlation", {"method": ok})
        assert r.status == "ok", f"method={ok!r} 应被接受: {r.messages}"

    def test_correlation_method_empty_string_uses_default(self):
        """空串在编排层被归一为「未提供」→ 默认 `pearson`（既有语义）。"""
        r = _via("correlation", {"method": ""})
        assert r.status == "ok", r.messages
        assert r.metadata.get("method") == "pearson", r.metadata.get("method")

    @pytest.mark.parametrize("ok", ["two-sided", "upper", "lower"])
    def test_spc_nonparametric_side_valid(self, ok):
        r = _via("spc_nonparametric", {"side": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["one-sided", "both", "two_sided", 123])
    def test_spc_nonparametric_side_rejected(self, bad):
        """注意 `"one-sided"` 应被拒 —— 引擎的实际值集是 `two-sided/upper/lower`。

        我最初把共享库的 `SIDE` 常量按 "two-sided/one-sided" 写，核对源码才发现
        真实值集不同。这条用例把这个事实钉住。
        """
        r = _via("spc_nonparametric", {"side": bad}, features=["g"])
        assert r.status == "error", f"side={bad!r} 应被拒绝（引擎只接受 two-sided/upper/lower）"


class TestNumericParams:
    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_logistic_threshold_rejected(self, bad):
        r = _via("logistic_regression", {"threshold": bad}, target="flag")
        assert r.status == "error", f"threshold={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [0.1, 0.5, 0.9])
    def test_logistic_threshold_valid(self, ok):
        r = _via("logistic_regression", {"threshold": ok}, target="flag")
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize(
        "field,bad", [("k", 0), ("k", -1), ("h", 0), ("h", float("inf")), ("k", "abc")]
    )
    def test_cusum_kh_rejected(self, field, bad):
        r = _via("spc_cusum", {field: bad}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize(
        "field,bad", [("lam", 0), ("lam", -0.1), ("lam", 1.5), ("L", 0), ("L", -2)]
    )
    def test_ewma_lambda_and_width_rejected(self, field, bad):
        r = _via("spc_ewma", {field: bad}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    def test_ewma_lam_upper_bound_is_inclusive(self):
        """⚠️ `lam` 的取值范围是 **(0, 1]（含 1）**，不是 (0,1)。

        引擎源码为 `if not 0 < lam <= 1`（λ=1 表示"只看最新点"，是合法的极端平滑）。
        本用例首版把 `lam=1` 列进拒绝清单 —— **我的假设错了**，核对源码后修正。
        这类"边界到底是开还是闭"的差异，只靠推断必然出错，必须读源码并用例钉住。
        """
        assert _via("spc_ewma", {"lam": 1}, features=["g"]).status == "ok"
        assert _via("spc_ewma", {"lam": 1.0001}, features=["g"]).status == "error"

    @pytest.mark.parametrize("field", ["mu", "sigma"])
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc"])
    def test_cusum_optional_mu_sigma_rejected_when_invalid(self, field, bad):
        """`mu`/`sigma` 是**可选显式覆盖**；显式给出非法值时须拒绝。

        它们不在 `DEFAULT_PARAMS` 里（默认"不指定"，由数据估计），
        故必须由 `Spec` 显式声明才能校验用户传入的值。
        """
        r = _via("spc_cusum", {field: bad}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    def test_cusum_explicit_mu_sigma_accepted(self):
        r = _via("spc_cusum", {"mu": 50.0, "sigma": 1.5}, features=["g"])
        assert r.status == "ok", r.messages


class TestEngineRaises:
    @pytest.mark.parametrize(
        "task,field,bad,feats,target",
        [
            ("correlation", "method", "p", ["x1", "x2"], "y"),
            ("logistic_regression", "threshold", 1.5, ["x1", "x2"], "flag"),
            ("spc_nonparametric", "side", "both", ["g"], "y"),
            ("spc_cusum", "k", 0, ["g"], "y"),
            ("spc_ewma", "L", 0, ["g"], "y"),
        ],
    )
    def test_raises_with_field(self, task, field, bad, feats, target):
        import importlib

        from smartsuite.services.task_spec import TASK_SPECS

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
