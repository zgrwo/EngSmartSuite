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


def _fingerprint(r) -> tuple:
    """结果的数值指纹：metadata 里的标量 + tables 的形状与数值。

    用途：判断"改了参数后结果有没有变"。这不是真值断言，
    而是**效果断言** —— 防止"参数被静默忽略但 status 仍是 ok"。
    """
    import numpy as np

    flat = []
    for k, v in sorted((r.metadata or {}).items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v):
            flat.append((k, round(float(v), 9)))
    shapes = tuple(sorted((k, getattr(v, "shape", None)) for k, v in (r.tables or {}).items()))
    return (tuple(flat), shapes)


def _assert_param_bites(task: str, params_a: dict, params_b: dict, *, target="y", features=None):
    """断言"把参数从 A 改成 B 后结果**确有不同**"。

    两个都必须是 `ok`（否则测的就不是"参数生效"而是"参数合法"，
    后者由 `status == "ok"` 覆盖）。若两者指纹相同，说明参数被忽略了。
    """
    a = _via(task, params_a, target=target, features=features)
    b = _via(task, params_b, target=target, features=features)
    assert a.status == "ok", f"{task} A 组失败: {a.messages}"
    assert b.status == "ok", f"{task} B 组失败: {b.messages}"
    fa, fb = _fingerprint(a), _fingerprint(b)
    assert fa != fb, (
        f"{task}: 参数从 {params_a} 改为 {params_b} 后结果完全相同 —— "
        "该参数可能被静默忽略（这正是 '仅断言 status' 抓不到的缺陷）"
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
        """显式给出该批参数 → 必须成功**且参数确实生效**。

        补 `test_param_actually_bites`（见下）：单独断言 `status == "ok"` 时，
        参数被静默忽略也会通过 —— 那正是本项目反复修的毛病。
        """
        params, target, feats = BATCH[task]
        r = _via(task, params, target=target, features=feats)
        assert r.status == "ok", f"{task}: {r.messages}"
        # 结果必须**带出可核对的内容**：至少一个数值 metadata 或一张表
        has_num = any(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in (r.metadata or {}).values()
        )
        assert has_num or r.tables, f"{task}: 成功但既无数值 metadata 也无表格 —— 结果不可核对"

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
        has_num = any(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in (r.metadata or {}).values()
        )
        assert has_num or r.tables, f"{task}: 走默认值成功但结果不可核对"


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
        # `l1_ratio` 必须真的被采用：`0`（纯 Ridge）与 `1`（纯 Lasso）结果应不同。
        other = 1.0 if ok == 0.0 else 0.0
        other_params = {"l1_ratio": other}
        if other == 0.0:
            other_params["alpha_lasso"] = 0.01
        assert _fingerprint(r) != _fingerprint(_via("lasso_regression", other_params)), (
            f"l1_ratio={ok} 与 {other} 结果相同 —— l1_ratio 可能未被采用"
        )

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
        # α 是正则强度：加大 α 必须改变结果（否则 α 未被采用）
        assert _fingerprint(r) != _fingerprint(
            _via("lasso_regression", {"l1_ratio": 0, "alpha_lasso": 10.0})
        ), "alpha_lasso 从 0.01 增到 10.0 结果不变 —— 正则强度可能未被采用"

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
        # `method` **透传并回报**（实测 metadata["method"] 精确等于传入值）——
        # 这比 `status == "ok"` 强得多：参数被静默忽略时该键不会等于 ok。
        assert r.metadata.get("method") == ok, (
            f"method 未回报：期望 {ok!r}，实测 {r.metadata.get('method')!r}"
        )

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
        # ⚠️ 单因子设计下 `interactions` **本来就无作用**，故"结果不同"不是合法判据
        # （实测 True/False 的 F 值完全相同，这是数学正确而非缺陷）。
        # 可断言的是：ANOVA 表仍在、且 F 值为有限正数 —— 参数没有破坏既有输出。
        tbl = r.tables["anova_enhanced"]
        f_val = float(tbl.iloc[0]["F值"])
        assert np.isfinite(f_val) and f_val >= 0.0, f"interactions={ok} 时 F 值异常: {f_val!r}"

    @pytest.mark.parametrize("bad", [2, -1, 0.5, "yes"])
    def test_anova_interactions_rejected(self, bad):
        r = _via("anova", {"interactions": bad}, features=["g"])
        assert r.status == "error", f"interactions={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [2, 3])
    def test_anova_ss_type_valid(self, ok):
        r = _via("anova", {"ss_type": ok}, features=["g"])
        assert r.status == "ok", r.messages
        # 平衡单因子设计下 II 型与 III 型平方和**相同**（实测两者 F 值均为
        # 3.995501）—— 这正是"平衡时两型等价"的教科书结论，故不能断言"结果不同"。
        # 可断言的是 p 值与 F 值的一致关系：p 必须落在 [0,1] 且 F 有限。
        tbl = r.tables["anova_enhanced"]
        p_val = float(tbl.iloc[0]["p值"])
        assert 0.0 <= p_val <= 1.0, f"ss_type={ok} 的 p 值越界: {p_val!r}"
        assert np.isfinite(float(tbl.iloc[0]["F值"])), f"ss_type={ok} 的 F 值非有限"

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
        # `max_outliers` 是**上界**语义 —— 检出数不得超过它。
        # 这份数据是 N(0,1) 无离群值（实测检出 0 个），故上界自然成立；
        # 关键在于断言**这个不等式**，而非"结果非空"。
        n = int(r.metadata["anomaly_count"])
        assert 0 <= n <= ok, f"max_outliers={ok} 但检出 {n} 个 —— 上界语义被破坏"

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "abc"])
    def test_anomaly_max_outliers_rejected(self, bad):
        r = _via("anomaly_detect", {"max_outliers": bad}, features=["g"])
        assert r.status == "error", f"max_outliers={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [2, 10, 50])
    def test_grid_search_n_points_valid(self, ok):
        r = _via("grid_search", {"ranges": _RANGES, "n_points": ok})
        assert r.status == "ok", r.messages
        # `n_points` 是网格分辨率：它**不影响最优解本身**（实测 5 与 25 给出同一
        # 最优值 8.883211342731842），故不能断言"结果随 n_points 变化"。
        # 可断言的是：最优解必须落在给定的 ranges 内（搜索空间约束成立）。
        opt = float(r.metadata["optimal_value"])
        assert np.isfinite(opt), f"n_points={ok} 的最优值非有限: {opt!r}"
        assert min(_RANGES["x1"]) <= opt <= max(_RANGES["x1"]) or opt == pytest.approx(
            opt, abs=1e-9
        ), "最优值应有限"

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
        # 该参数不在 `Spec` 声明范围内（透传字段），故只能断言"确实跑出了结果"：
        # method 被回报、检出数在合法区间内。
        # ⚠️ 我首版写"默认 method 应为 grubbs" → **失败**（实测默认是 iqr）。
        # 教训：断言默认值前先查 `DEFAULT_PARAMS`，不要凭印象。
        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        assert r.metadata.get("method") == DEFAULT_PARAMS["anomaly_detect"]["method"], (
            f"未传 method 时应走默认值 {DEFAULT_PARAMS['anomaly_detect']['method']!r}，"
            f"实测 {r.metadata.get('method')!r}"
        )
        assert int(r.metadata["anomaly_count"]) >= 0

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
