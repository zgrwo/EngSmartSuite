"""批量迁移第八批（阶段 P4 步骤③，第二十六轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 2 个任务（剩余参数化任务里最后的中等规模两个）

| 任务 | 参数 | 共享字段 |
|:---|:---|:---|
| `box_chart` | `mode`, `show_stats`, `group_col`, `usl`, `lsl`, `ucl`, `lcl`, `cl`, `target` | ✅ `GROUP_COL`/`USL`/`LSL`/`TARGET` |
| `hypothesis_test` | `alpha`, `test`, `group_col`, `popmean`, `popmedian` | ✅ `ALPHA`/`GROUP_COL` |

## `hypothesis_test` 的 `alpha` 被读了 17 次

`hypothesis_test()` 是一个覆盖 **17 种检验类型**的大分派函数（约 1100 行），
里面 `alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)` 出现在**每个分支**里
（共 17 处）—— 每处都重复读取与转换同一次。迁移后**只在函数开头取一次**。

## 混合类型参数本轮一律**透传**（与 `scatter_plot.show_ci` 同族）

- `box_chart.show_stats`：默认值 `True`（**布尔**），引擎也接受字符串并做宽容归一。
  `Choice` 不支持布尔（别名解析在字符串归一之前），强上会让布尔输入被拒 = 行为回归。
- `hypothesis_test.test`：默认值是字符串、值集是**枚举**（17 种）→ 用 `Choice` 收口，
  **并给出中文文案**（前端下拉框需要）。

## `box_chart` 的参考线由**动态键循环**读取

`usl`/`lsl`/`ucl`/`lcl`/`cl` 在一个 `for key, color, style in [...]` 循环里读，
`target` 单独读 —— 与 `spc_xbar` 同构。迁移后改读 `Spec` 结果，语义不变。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 71) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a = rng.normal(50, 1.5, n // 2)
    b = rng.normal(52, 1.5, n - n // 2)
    return pd.DataFrame(
        {
            "y": np.concatenate([a, b]),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "g": (["A", "B"] * (n // 2))[:n],
            "three": (["P", "Q", "R"] * (n // 3 + 1))[:n],
        }
    )


def _via(task: str, params: dict, target: str = "y", features=None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=_frame(),
            target_col=target,
            feature_cols=features if features is not None else ["g"],
            params=params,
        )
    )


BATCH = {
    "box_chart": ({"mode": "facet", "group_col": "g"}, "y", ["g"]),
    "hypothesis_test": ({"test": "ttest_ind", "group_col": "g", "alpha": 0.05}, "y", ["g"]),
}


class TestSpecsAndDefaults:
    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_spec_exists(self, task):
        from smartsuite.services.param_labels import spec_for_task

        assert spec_for_task(task) is not None, f"{task} 缺少 PARAM_SPEC"

    @pytest.mark.parametrize("task", sorted(BATCH))
    def test_defaults_match_default_params(self, task):
        """主防线：`Spec.defaults()` 必须与 `DEFAULT_PARAMS[task]` 精确相等。"""
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


class TestBoxChart:
    @pytest.mark.parametrize("ok", ["facet", "nested"])
    def test_mode_valid(self, ok):
        r = _via("box_chart", {"mode": ok}, features=["g"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["grid", "FACET_", "faceted"])
    def test_mode_rejected(self, bad):
        r = _via("box_chart", {"mode": bad}, features=["g"])
        assert r.status == "error", f"mode={bad!r} 应被拒绝"

    @staticmethod
    def _hlines(result) -> set:
        ys = set()
        for ax in result.figures[0].axes:
            for ln in ax.get_lines():
                d = ln.get_ydata()
                if len(d) >= 2 and abs(float(d[0]) - float(d[-1])) < 1e-9:
                    ys.add(round(float(d[0]), 4))
        return ys

    def test_five_reference_lines_are_drawn(self):
        """`usl`/`lsl`/`ucl`/`lcl`/`cl`/`target` 六条参考线都应画出。

        这六个参数由**动态键循环**读取 → 迁移后必须仍生效。
        """
        r = _via(
            "box_chart",
            {
                "group_col": "g",
                "usl": 56.0,
                "lsl": 44.0,
                "ucl": 55.0,
                "lcl": 45.0,
                "cl": 50.0,
                "target": 51.0,
            },
            features=["g"],
        )
        assert r.status == "ok", r.messages
        drawn = self._hlines(r)
        for expected in (56.0, 44.0, 55.0, 45.0, 50.0, 51.0):
            assert expected in drawn, f"{expected} 参考线应被画出；实际 {sorted(drawn)}"

    @pytest.mark.parametrize("field", ["usl", "lsl", "ucl", "lcl", "cl", "target"])
    @pytest.mark.parametrize("bad", ["abc", float("inf"), float("nan")])
    def test_non_finite_reference_lines_rejected(self, field, bad):
        r = _via("box_chart", {field: bad}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize("field", ["usl", "lsl", "ucl", "lcl", "cl", "target"])
    def test_engine_raises_with_field(self, field):
        import importlib

        fn = importlib.import_module("smartsuite.engine.exploratory").box_chart
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task="box_chart",
                    data=_frame(),
                    target_col="y",
                    feature_cols=["g"],
                    params={field: "abc"},
                )
            )
        assert ei.value.field_name == field

    def test_show_stats_accepts_bool_and_string(self):
        """`show_stats` 是**混合类型**参数（默认 `True` 是布尔）→ 本轮透传。"""
        for value in (True, False, "true", "false"):
            r = _via("box_chart", {"show_stats": value}, features=["g"])
            assert r.status == "ok", f"show_stats={value!r} 应被接受: {r.messages}"

    def test_show_stats_silent_degradation_is_now_fixed(self):
        """**该静默降级已于第三十轮修掉**（与 `scatter_plot.show_ci` 同因同解）。

        两者都改用共享的 `BOOL_SWITCH`；修的是 `Choice` 的别名表达力缺口
        （别名原先只对 `str` 生效），而非给引擎打补丁。
        本用例保留为**回归防线**。
        """
        for value in ("maybe", "yes", 123):
            r = _via("box_chart", {"show_stats": value}, features=["g"])
            assert r.status == "error", (
                f"show_stats={value!r} 必须被明确拒绝 —— 静默降级已在第三十轮修复"
            )


class TestHypothesisTest:
    def test_all_17_test_types_have_spec_entries(self):
        """`test` 的 17 种取值都必须出现在 `Choice` 里（含中文文案）。"""
        from smartsuite.services.param_labels import spec_for_task

        validator = spec_for_task("hypothesis_test")._fields["test"].validator
        opts = dict(validator.options())
        assert len(opts) == 17, sorted(opts)
        for value, label in opts.items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), (value, label)

    def test_test_type_set_matches_engine_whitelist(self):
        """`Choice` 的值集必须与引擎的 `_HYPOTHESIS_TEST_TYPES` **完全一致**。

        这条防止两处清单漂移 —— 引擎加了新检验而 Spec 忘加（或反之）。
        """
        from smartsuite.engine.root_cause.hypothesis import _HYPOTHESIS_TEST_TYPES
        from smartsuite.services.param_labels import spec_for_task

        validator = spec_for_task("hypothesis_test")._fields["test"].validator
        assert set(dict(validator.options())) == set(_HYPOTHESIS_TEST_TYPES)

    @pytest.mark.parametrize(
        "ok",
        ["ttest_ind", "ttest_1samp", "mannwhitney", "kruskal_wallis", "auto"],
    )
    def test_common_types_still_work(self, ok):
        r = _via("hypothesis_test", {"test": ok, "group_col": "g"}, features=["g"])
        assert r.status == "ok", f"test={ok!r}: {r.messages}"

    def test_paired_type_needs_two_feature_columns(self):
        """`ttest_paired` 需要 2 个特征列（前后测量）。

        我首版把它放进"通用类型都能跑"的参数表、只给 1 个特征列 → 报
        「配对检验需要 2 个特征列」。**断言错层**（与多轮前同一类错误）。

        本用例**只断言"给了 2 列就不再报列数不足"** —— 此处的两列是独立随机列
        （不是真实的配对前后测量），故后续可能因数据原因失败；那不是本用例要管的。
        """
        r = _via("hypothesis_test", {"test": "ttest_paired"}, features=["x1", "x2"])
        assert not any("特征列" in m for m in r.messages), r.messages

    @pytest.mark.parametrize("bad", ["bogus", "ttest", "TTEST_IND_"])
    def test_unknown_type_rejected_with_options(self, bad):
        r = _via("hypothesis_test", {"test": bad, "group_col": "g"}, features=["g"])
        assert r.status == "error", f"test={bad!r} 应被拒绝"
        joined = " ".join(r.messages)
        assert "ttest_ind" in joined, f"提示应列出可选值: {joined}"

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_alpha_rejected(self, bad):
        r = _via("hypothesis_test", {"alpha": bad, "group_col": "g"}, features=["g"])
        assert r.status == "error", f"alpha={bad!r} 应被拒绝"

    def test_alpha_actually_affects_conclusion(self):
        """`alpha` 被读了 14 次（`hypothesis_test` 的每个分支一次）—— 迁移后必须仍真正生效。

        用相关系数检验（不依赖分组列）构造一个 **p 落在 (0.0001, 0.05) 之间**的样本，
        于是 `alpha=0.0001` 判"不显著"、`alpha=0.05` 判"显著" —— 结论随 alpha 翻转。
        夹具由扫描 seed 1..40 选出（seed=1，p≈0.0088），与真实 `scipy.pearsonr` 对拍一致。
        """
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 60)
        data = pd.DataFrame({"y": 0.42 * x + rng.normal(0, 1, 60), "x1": x})

        def _run(alpha: float):
            return orchestrate(
                AnalysisRequest(
                    task="hypothesis_test",
                    data=data,
                    target_col="y",
                    feature_cols=["x1"],
                    params={"test": "correlation", "alpha": alpha},
                )
            )

        strict, loose = _run(0.0001), _run(0.05)
        assert strict.status == "ok" and loose.status == "ok", strict.messages
        # 相关系数检验的 metadata 给的是 p_value/alpha（不像 t 检验给 significant）
        p_value = strict.metadata["p_value"]
        assert 0.0001 < p_value < 0.05, f"夹具的 p 值应落在两阈值之间，实际 {p_value}"
        assert strict.metadata["alpha"] == 0.0001
        assert loose.metadata["alpha"] == 0.05
        # 结论翻转：同一个 p 值在两种 alpha 下判定相反
        assert p_value > strict.metadata["alpha"]
        assert p_value < loose.metadata["alpha"]

    @pytest.mark.parametrize("field", ["popmean", "popmedian"])
    @pytest.mark.parametrize("bad", ["abc", float("inf"), float("nan")])
    def test_population_reference_rejected(self, field, bad):
        test = "ttest_1samp" if field == "popmean" else "wilcoxon_1samp"
        r = _via("hypothesis_test", {"test": test, field: bad, "group_col": "g"}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [-100.0, 0.0, 50.0])
    def test_popmean_valid(self, ok):
        r = _via(
            "hypothesis_test",
            {"test": "ttest_1samp", "popmean": ok, "group_col": "g"},
            features=["g"],
        )
        assert r.status == "ok", r.messages


class TestEngineRaises:
    @pytest.mark.parametrize(
        "task,field,bad,feats",
        [
            ("box_chart", "mode", "grid", ["g"]),
            ("box_chart", "usl", "abc", ["g"]),
            ("hypothesis_test", "test", "bogus", ["g"]),
            ("hypothesis_test", "alpha", 1.5, ["g"]),
        ],
    )
    def test_raises_with_field(self, task, field, bad, feats):
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
                    target_col="y",
                    feature_cols=feats,
                    params={field: bad},
                )
            )
        assert ei.value.field_name == field
