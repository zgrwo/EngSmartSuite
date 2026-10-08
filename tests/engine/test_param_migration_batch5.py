"""批量迁移第六批（阶段 P4 步骤③，第二十四轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 5 个任务

| 任务 | 参数 | 校验 |
|:---|:---|:---|
| `lasso_regression` | `alpha_lasso`, `l1_ratio` | `l1_ratio` = `Finite(ge=0, le=1)`（**闭**区间）；`alpha_lasso` 透传 |
| `multi_objective` | `objectives`, `weights`, `direction` | 前两者透传；`direction` = `Choice` |
| `anomaly_detect` | `method`, `alpha`, `max_outliers` | `Choice(4 种)`；`ALPHA`；`Integer(min=1)` |
| `anova` | `alpha`, `interactions`, `ss_type` | `ALPHA`；`Choice(0/1)`；`Choice(2/3)` 带中文文案 |
| `grid_search` | `ranges`, `direction`, `n_points` | `ranges` 透传；`direction` = `Choice`；`n_points` = `Integer(min=2)` |

## 只声明 `DEFAULT_PARAMS` 里的参数（少即是多）

引擎还读一些**不在**默认值表里的可选参数：

- `anomaly_detect.contamination`：可为 `(0, 0.5]` 数值**或字符串 `"auto"`**
  （双形态，`Spec` 表达需要自定义校验器）；
- `lasso_regression.alpha_lasso`：同样有 `None` 与 `"auto"` 双哨兵语义；
- `grid_search` / `multi_objective` 的 `ranges`/`objectives`/`weights`：
  用户手写的结构化字符串（格式校验属业务规则，引擎内已有专门实现）。

本轮**不声明**它们 → 原样透传、行为不变。这是"精准修改"：迁移的目标是把
**默认值表里那几个参数**的校验收口，不是顺手扩大 `Spec` 的表面。

## 两处**闭区间**（不是开区间）

`lasso_regression.l1_ratio` 是 `[0, 1]`（源码 `if not 0 <= l1_ratio <= 1`）——
`0` = 纯 Ridge、`1` = 纯 Lasso，两端都合法。
这与 `alpha`/`ci_level` 的 `(0,1)` 开区间不同，**不能照抄**。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 51) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "y": 3.0 * x1 - 1.5 * x2 + rng.normal(0, 0.3, n),
            "x1": x1,
            "x2": x2,
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


#: `grid_search` 的搜索范围：`{列名: (下限, 上限)}`（**dict**，不是字符串）
_RANGES = {"x1": (-2, 2), "x2": (-2, 2)}

BATCH = {
    "lasso_regression": ({"l1_ratio": 1.0}, "y", ["x1", "x2"]),
    # `multi_objective` 必须有 `objectives`（引擎要求）
    "multi_objective": (
        {"objectives": [{"col": "y", "direction": "maximize"}]},
        "y",
        ["x1", "x2"],
    ),
    "anomaly_detect": ({"method": "iqr", "alpha": 0.05, "max_outliers": 5}, "y", ["g"]),
    "anova": ({"alpha": 0.05, "interactions": 0, "ss_type": 2}, "y", ["g"]),
    # `grid_search` 必须有 `ranges`（引擎要求），否则报「需要提供参数搜索范围」
    # `grid_search` 必须有 `ranges`（引擎要求）
    "grid_search": (
        {"ranges": _RANGES, "direction": "maximize", "n_points": 5},
        "y",
        ["x1", "x2"],
    ),
}


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_match_default_params(self, task):
        """主防线：`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 逐键一致。"""
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
        """只给**必需输入**（不带任何可选项）→ 应走各参数的默认值并成功。

        `grid_search` / `multi_objective` 的必需输入是 `ranges` / `objectives`
        （引擎要求非空），它们不在 `Spec` 的校验范围内（透传字段），故此处补上。
        """
        _, target, feats = BATCH[task]
        required = {
            "grid_search": {"ranges": _RANGES},
            "multi_objective": {"objectives": [{"col": "y", "direction": "maximize"}]},
        }.get(task, {})
        r = _via(task, required, target=target, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"


class TestClosedIntervalParams:
    """两处**闭**区间 —— 与 `alpha` 的 (0,1) 开区间不同，不能照抄。"""

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    def test_lasso_l1_ratio_boundaries_inclusive(self, ok):
        """`l1_ratio ∈ [0,1]`：`0`=纯 Ridge、`1`=纯 Lasso，**两端都合法**。

        `0` 需同时给出 `alpha_lasso` —— 见下面的 `CrossRule` 用例。
        """
        params = {"l1_ratio": ok}
        if ok == 0.0:
            params["alpha_lasso"] = 0.01
        r = _via("lasso_regression", params)
        assert r.status == "ok", f"l1_ratio={ok} 应被接受: {r.messages}"

    def test_lasso_ridge_without_alpha_gets_actionable_message(self):
        """**本轮修掉的一处「错误归因」**。

        `l1_ratio=0`（纯 Ridge）时 sklearn 无法自动生成 α 网格，抛
        `ValueError: Automatic alpha grid generation is not supported for l1_ratio=0`。
        该异常此前被 orchestrator 泛化翻译成误导性的
        「**数据格式或数值范围不符合分析要求**」—— 真实原因是**参数组合**问题，
        用户会去查数据，而数据没问题（boundary-contract 禁止错误归因）。

        现由 `CrossRule` 在参数层拦下，给出可操作的中文提示。
        """
        r = _via("lasso_regression", {"l1_ratio": 0})
        assert r.status == "error"
        joined = " ".join(r.messages)
        assert "l1_ratio" in joined or "Ridge" in joined, joined
        assert "数据格式" not in joined, f"不得归因为数据问题: {joined}"

    def test_lasso_ridge_with_alpha_still_works(self):
        """给出 α 后纯 Ridge 是合法的 —— 证明规则是「组合约束」而非「一刀切拒绝」。"""
        r = _via("lasso_regression", {"l1_ratio": 0, "alpha_lasso": 0.01})
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2, float("nan"), "abc"])
    def test_lasso_l1_ratio_out_of_range_rejected(self, bad):
        r = _via("lasso_regression", {"l1_ratio": bad})
        assert r.status == "error", f"l1_ratio={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [0, 1, -0.5, 2.0, float("nan")])
    def test_anova_alpha_is_open_interval(self, bad):
        """对照：`alpha` 仍是 **(0,1) 开区间**（与 `l1_ratio` 的闭区间形成对照）。"""
        r = _via("anova", {"alpha": bad}, features=["g"])
        assert r.status == "error", f"alpha={bad!r} 应被拒绝"


class TestEnumParams:
    @pytest.mark.parametrize("ok", ["iqr", "zscore", "grubbs", "isolation_forest"])
    def test_anomaly_method_valid(self, ok):
        # 孤立森林需要**数值**特征列（传分类列会报"模型拟合失败"）—— 用 x1/x2
        feats = ["x1", "x2"] if ok == "isolation_forest" else ["g"]
        r = _via("anomaly_detect", {"method": ok}, features=feats)
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["IQR_", "z_score", "lof", "iforest"])
    def test_anomaly_method_rejected_with_options(self, bad):
        r = _via("anomaly_detect", {"method": bad}, features=["g"])
        assert r.status == "error", f"method={bad!r} 应被拒绝"
        joined = " ".join(r.messages)
        for opt in ("iqr", "zscore", "grubbs", "isolation_forest"):
            assert opt in joined, f"提示应列出可选值 {opt}: {joined}"

    @pytest.mark.parametrize("ok", [0, 1])
    def test_anova_interactions_valid(self, ok):
        r = _via("anova", {"interactions": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [2, -1, 0.5, "yes"])
    def test_anova_interactions_rejected(self, bad):
        r = _via("anova", {"interactions": bad}, features=["g"])
        assert r.status == "error", f"interactions={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [2, 3])
    def test_anova_ss_type_valid(self, ok):
        r = _via("anova", {"ss_type": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [1, 4, "II", 2.5])
    def test_anova_ss_type_rejected(self, bad):
        r = _via("anova", {"ss_type": bad}, features=["g"])
        assert r.status == "error", f"ss_type={bad!r} 应被拒绝"

    def test_anova_ss_type_options_have_chinese_labels(self):
        """`ss_type` 的选项必须带中文文案（前端下拉框显示用）。

        这个参数**改变结论**（实测同数据 Type II 给显著、Type III 给不显著），
        故下拉里必须让用户看清自己在选什么口径。
        """
        from smartsuite.services.param_labels import spec_for_task

        validator = spec_for_task("anova")._fields["ss_type"].validator
        opts = dict(validator.options())
        assert set(opts) == {2, 3}
        for value, label in opts.items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), (value, label)

    @pytest.mark.parametrize("ok", ["maximize", "minimize"])
    def test_grid_search_direction_valid(self, ok):
        assert _via("grid_search", {"ranges": _RANGES, "direction": ok}).status == "ok"

    @pytest.mark.parametrize("bad", ["max", "MIN", "up"])
    def test_grid_search_direction_rejected(self, bad):
        """`multi_objective` **没有**顶层 `direction` —— 它藏在每个 objective 里。

        我一度给 `multi_objective` 也声明了顶层 `direction`，并往 `DEFAULT_PARAMS`
        加了一项；核对源码（`obj.get("direction", "maximize")`）后撤回 ——
        那样会造出"前端能设、引擎不看"的假参数，正是本轮在 `regression`
        上发现的那类缺陷。**教训：「引擎读了 params」≠「读的是顶层同名键」。**
        """
        assert _via("grid_search", {"ranges": _RANGES, "direction": bad}).status == "error"


class TestIntegerParams:
    @pytest.mark.parametrize("ok", [1, 5, 100])
    def test_anomaly_max_outliers_valid(self, ok):
        r = _via("anomaly_detect", {"max_outliers": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "abc"])
    def test_anomaly_max_outliers_rejected(self, bad):
        r = _via("anomaly_detect", {"max_outliers": bad}, features=["g"])
        assert r.status == "error", f"max_outliers={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [2, 10, 50])
    def test_grid_search_n_points_valid(self, ok):
        r = _via("grid_search", {"ranges": _RANGES, "n_points": ok})
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", [1, 0, -5, 2.5, "abc"])
    def test_grid_search_n_points_rejected(self, bad):
        """`n_points` 至少 2，且必须是整数（**行为改进**）。

        迁移前实测：`1` / `0` / `-5` / `2.5` / `"abc"` / `inf` **全部返回 `ok`** ——
        `int()` 失败时静默回落默认值 10，且无区间检查。这是「静默降级」
        （boundary-contract 明令禁止）。迁移后明确拒绝。
        """
        r = _via("grid_search", {"ranges": _RANGES, "n_points": bad})
        assert r.status == "error", f"n_points={bad!r} 应被拒绝"


class TestOptionalParamsPassThrough:
    """未在 `Spec` 里声明的可选参数应**原样透传**（本轮有意不扩大表面）。"""

    def test_anomaly_contamination_auto_still_works(self):
        """`contamination="auto"` 是字符串哨兵，`Spec` 未声明它 → 必须仍可传入。"""
        r = _via("anomaly_detect", {"contamination": "auto"}, features=["g"])
        assert r.status == "ok", f"contamination='auto' 应仍可用: {r.messages}"

    def test_anomaly_contamination_numeric_still_works(self):
        r = _via("anomaly_detect", {"contamination": 0.1}, features=["g"])
        assert r.status == "ok", r.messages

    def test_lasso_alpha_lasso_auto_still_works(self):
        r = _via("lasso_regression", {"alpha_lasso": "auto"})
        assert r.status == "ok", f"alpha_lasso='auto' 应仍可用: {r.messages}"

    def test_grid_search_ranges_dict_still_works(self):
        """`ranges` 是用户手写的结构化字符串（如 'x1:0,10;x2:-1,1'）。"""
        r = _via("grid_search", {"ranges": _RANGES})
        assert r.status == "ok", r.messages


class TestEngineRaises:
    @pytest.mark.parametrize(
        "task,field,bad,feats,target",
        [
            ("lasso_regression", "l1_ratio", 2.0, ["x1", "x2"], "y"),
            ("anova", "ss_type", 5, ["g"], "y"),
            ("grid_search", "n_points", 1, ["x1", "x2"], "y"),
            ("anomaly_detect", "method", "lof", ["g"], "y"),
        ],
    )
    def test_raises_with_field(self, task, field, bad, feats, target):
        import importlib

        from smartsuite.services.task_spec import TASK_SPECS

        func_path = next(s.func_path for s in TASK_SPECS if s.key == task)
        mod_name, fn_name = func_path.split(":", 1)
        fn = getattr(importlib.import_module(mod_name), fn_name)
        # `grid_search` 需先满足"ranges 非空"才能走到参数校验，
        # 否则先报「需要提供参数搜索范围」（数据前置守卫早于参数校验）。
        extra = {"ranges": _RANGES} if task == "grid_search" else {}
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task=task,
                    data=_frame(),
                    target_col=target,
                    feature_cols=feats,
                    params={**extra, field: bad},
                )
            )
        assert ei.value.field_name == field
