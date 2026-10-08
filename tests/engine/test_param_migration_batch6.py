"""批量迁移第七批（阶段 P4 步骤③，第二十五轮）。

契约：docs/governance/improvement-plan.md §六

## 本批 5 个任务

| 任务 | 参数 | 共享字段 |
|:---|:---|:---|
| `spc_xbar` | `group_col`, `usl`, `lsl`, `target` | ✅ 全部（4/4，**零专有声明**） |
| `scatter_plot` | `fit`, `show_ci`, `group_col` | ✅ `GROUP_COL` |
| `tolerance_interval` | `side`, `coverage`, `confidence` | 自声明 |
| `bootstrap_ci` | `statistic`, `n_bootstrap`, `ci_level`, `random_state` | ✅ `CI_LEVEL`/`RANDOM_STATE` |
| `gage_rr` | `tolerance`, `sigma_multiplier`, `part_col`, `operator_col` | 自声明 |

## 迁移顺带修掉的三处「静默降级」（迁移前**实测**基线）

1. **`scatter_plot.fit` 完全没有白名单校验** —— `fit="lin"` / `"poly"` 等拼写错误
   会静默走"不拟合"分支（`if fit_type == "linear"` 不成立即无拟合线），
   用户以为画了趋势线。迁移后由 `Choice` 明确拒绝。
2. **`bootstrap_ci.n_bootstrap` 静默夹紧 + 静默回落** —— 实测：

   | 传入 | 实际使用 |
   |:---|:---|
   | `50` / `0` / `-5` / `1.5` | **100**（夹紧） |
   | `20000` | **10000**（夹紧） |
   | `"abc"` / `inf` | **2000**（静默回落默认值） |

   用户传 20000 只得到 10000 却毫不知情。迁移后 `Integer(min=100, max=10000)`
   明确拒绝越界值。
3. **`tolerance_interval.side`** 原有白名单（守卫已存在）→ 改由 `Choice` 表达
   并**给出可选值的中文文案**。

## `scatter_plot.show_ci` 的形态陷阱

`DEFAULT_PARAMS["scatter_plot"]["show_ci"]` 是**字符串 `'true'`**（不是布尔），
且引擎做字符串归一。`Choice` 的别名解析发生在**字符串归一之前**，
故无法给 `True`/`False` 注册别名。
**决定：Spec 只接受 `'true'`/`'false'`**（正是默认值表的形态），
"字符串 → 布尔"的转换留在引擎。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.services.orchestrator import DEFAULT_PARAMS, orchestrate


def _frame(n: int = 60, seed: int = 61) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 1.5, n),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "g": (["A", "B"] * (n // 2))[:n],
            "t": np.arange(n),
            # `gage_rr` 需要**两个不同列**（部件列 + 操作员列）：
            # 只给一列会让 `sub[[target, part_col, operator_col]]` 塌缩成 Series
            # （列名重复时 pandas 返回 DataFrame，但同名部件/操作员语义也不对）。
            "part": [f"P{i % 10:02d}" for i in range(n)],
            "op": [f"O{i % 3}" for i in range(n)],
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
    "spc_xbar": ({"group_col": "g"}, "y", ["g"]),
    "scatter_plot": ({"fit": "none", "show_ci": "true", "group_col": "g"}, "y", ["x1", "g"]),
    "tolerance_interval": ({"side": "two-sided", "coverage": 0.99, "confidence": 0.95}, "y", []),
    "bootstrap_ci": (
        {"statistic": "mean", "n_bootstrap": 500, "ci_level": 0.95, "random_state": 42},
        "y",
        [],
    ),
    "gage_rr": (
        {"tolerance": 5.0, "sigma_multiplier": 5.15, "part_col": "part", "operator_col": "op"},
        "y",
        ["part", "op"],
    ),
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

    def test_spc_xbar_is_fully_shared(self):
        """`spc_xbar` 的 4 个参数**全部**来自共享字段库（零专有声明）。

        这是第二十轮建库时的目标形态，值得单独钉住 ——
        若将来有人给它加参数，本用例会失败并促使重新审视"能否共享"。
        """
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("spc_xbar")
        assert set(spec.field_names) == {"group_col", "usl", "lsl", "target"}


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


class TestSpcXbar:
    """`usl`/`lsl` 由**动态键循环**读取 → 迁移后必须仍生效。"""

    @staticmethod
    def _hlines(result) -> set:
        """取出所有**水平**参考线的 y 值（首末点相同即视为水平线）。"""
        ys = set()
        for ax in result.figures[0].axes:
            for ln in ax.get_lines():
                d = ln.get_ydata()
                if len(d) >= 2 and abs(float(d[0]) - float(d[-1])) < 1e-9:
                    ys.add(round(float(d[0]), 4))
        return ys

    def test_spec_limits_affect_result(self):
        """给出 USL/LSL 必须真正画出规格限参考线（证明 Spec 取的值被引擎用到）。

        规格限**不进入 metadata/tables** —— 它们只影响图形（axhline 参考线）。
        故本用例比较图形里的水平线集合；首版断言 metadata 不等，是我的断言找错了载体。
        """
        without = _via("spc_xbar", {"group_col": "g"}, features=["g"])
        with_limits = _via("spc_xbar", {"group_col": "g", "usl": 54.0, "lsl": 46.0}, features=["g"])
        assert without.status == "ok" and with_limits.status == "ok"
        assert 54.0 not in self._hlines(without), "未给规格限时不应有 54.0 参考线"
        assert 46.0 not in self._hlines(without), "未给规格限时不应有 46.0 参考线"
        assert 54.0 in self._hlines(with_limits), "USL=54 应画出 54.0 参考线"
        assert 46.0 in self._hlines(with_limits), "LSL=46 应画出 46.0 参考线"

    @pytest.mark.parametrize("field", ["usl", "lsl", "target"])
    @pytest.mark.parametrize("bad", ["abc", float("inf"), float("nan")])
    def test_non_finite_spec_limits_rejected(self, field, bad):
        """规格限必须为有限数值 —— 原引擎已有此校验，迁移后须保持。"""
        r = _via("spc_xbar", {field: bad}, features=["g"])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize("base", [-1e6, 0, 1e6])
    def test_spec_limits_any_finite_value_accepted(self, base):
        """规格限只要求"有限"，**不设区间** —— 数值可正可负可零。"""
        r = _via("spc_xbar", {"usl": base + 5, "lsl": base - 5}, features=["g"])
        assert r.status == "ok", f"usl/lsl 取 {base}±5 应被接受: {r.messages}"

    @pytest.mark.parametrize("field", ["usl", "lsl", "target"])
    def test_engine_raises_with_field(self, field):
        import importlib

        fn = importlib.import_module("smartsuite.engine.spc_charts.xbar_r").xbar_r_chart
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task="spc_xbar",
                    data=_frame(),
                    target_col="y",
                    feature_cols=["g"],
                    params={field: "abc"},
                )
            )
        assert ei.value.field_name == field


class TestScatterPlot:
    """`fit` 此前**无白名单**（拼错静默变成"不拟合"）—— 迁移后明确拒绝。"""

    @pytest.mark.parametrize("ok", ["none", "linear", "lowess"])
    def test_fit_valid(self, ok):
        r = _via("scatter_plot", {"fit": ok}, features=["x1"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["poly", "lin", "quadratic", "smooth"])
    def test_fit_rejected_after_migration(self, bad):
        """**行为改进**：迁移前实测 `fit="lin"` 返回 `ok` 且**不画趋势线**。

        引擎用 `if fit_type == "linear"` / `elif fit_type == "lowess"` 分支，
        拼错的值静默落到"两者都不是"= 不拟合。用户以为画了线，实际没有。
        """
        r = _via("scatter_plot", {"fit": bad}, features=["x1"])
        assert r.status == "error", f"fit={bad!r} 应被拒绝（迁移前被静默接受）"

    def test_fit_case_insensitive(self):
        """`Choice` 大小写归一 —— `"LINEAR"` 应等价于 `"linear"`。"""
        r = _via("scatter_plot", {"fit": "LINEAR"}, features=["x1"])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("ok", ["true", "false", "True", "FALSE"])
    def test_show_ci_string_forms_accepted(self, ok):
        """默认值是**字符串** `'true'`，Spec 只接受 `'true'`/`'false'`（大小写归一）。"""
        r = _via("scatter_plot", {"show_ci": ok}, features=["x1"])
        assert r.status == "ok", f"show_ci={ok!r} 应被接受: {r.messages}"

    def test_show_ci_accepts_bool_and_string(self):
        """`show_ci` 是**混合类型**参数（本轮改为透传字段，未强转类型）。

        默认值是字符串 `"true"`，但布尔 `True` 也是既有测试在用的输入，
        故 Spec 只声明默认值与文案、不做类型校验。
        """
        for value in ("true", "false", True, False):
            r = _via("scatter_plot", {"show_ci": value}, features=["x1"])
            assert r.status == "ok", f"show_ci={value!r} 应被接受: {r.messages}"

    def test_show_ci_silent_degradation_is_now_fixed(self):
        """**该静默降级已于第三十轮修掉**（本用例随之从"钉住现状"改为"防回归"）。

        迁移前的引擎归一是 `str.lower() not in ("false","0","no","")` ——
        `"maybe"` / `"yes"` / `123` 都不在排除表里，于是**静默变 True**
        （用户以为关掉了置信带却还在显示）。

        修法不是给引擎打补丁，而是补上 `Choice` 的表达力缺口：
        `Choice.check` 的别名原先只对 `str` 生效，故无法声明「布尔 `True` 也是
        `'true'` 的别名」。放宽后 `show_ci` 可用共享的 `BOOL_SWITCH` 收口。

        本用例保留为**回归防线**：非法值必须被拒绝，不得退回"静默当作 True"。
        """
        for value in ("maybe", "yes", 123):
            r = _via("scatter_plot", {"show_ci": value}, features=["x1"])
            assert r.status == "error", (
                f"show_ci={value!r} 必须被明确拒绝 —— 静默降级已在第三十轮修复，不得回退"
            )


class TestToleranceInterval:
    @pytest.mark.parametrize("ok", ["two-sided", "upper", "lower"])
    def test_side_valid(self, ok):
        r = _via("tolerance_interval", {"side": ok}, features=[])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["one-sided", "both", "two_sided"])
    def test_side_rejected(self, bad):
        """注意 `"one-sided"` 应被拒 —— 实际值集是 `two-sided/upper/lower`。"""
        r = _via("tolerance_interval", {"side": bad}, features=[])
        assert r.status == "error", f"side={bad!r} 应被拒绝"

    @pytest.mark.parametrize("field", ["coverage", "confidence"])
    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, float("nan"), "abc"])
    def test_open_interval_rejected(self, field, bad):
        """`coverage` / `confidence` 都是 **(0,1) 开区间**。"""
        r = _via("tolerance_interval", {field: bad}, features=[])
        assert r.status == "error", f"{field}={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [0.5, 0.9, 0.99])
    def test_valid_values(self, ok):
        r = _via("tolerance_interval", {"coverage": ok, "confidence": ok}, features=[])
        assert r.status == "ok", r.messages


class TestBootstrapCi:
    @pytest.mark.parametrize("ok", ["mean", "median", "std", "var"])
    def test_statistic_valid(self, ok):
        r = _via("bootstrap_ci", {"statistic": ok}, features=[])
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["mode", "sum", "MEAN_"])
    def test_statistic_rejected(self, bad):
        r = _via("bootstrap_ci", {"statistic": bad}, features=[])
        assert r.status == "error", f"statistic={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [0, -100, 1.5, "abc", float("inf"), 20_000, 50])
    def test_n_bootstrap_rejected_after_migration(self, bad):
        """**行为改进**：迁移前实测 `n_bootstrap` 被**静默夹紧/回落**。

        | 传入 | 迁移前实际使用 |
        |:---|:---|
        | `50` / `0` / `-5` / `1.5` | **100**（夹紧） |
        | `20000` | **10000**（夹紧） |
        | `"abc"` / `inf` | **2000**（静默回落默认值） |

        用户传 20000 只拿到 10000 却毫不知情。迁移后由
        `Integer(min=100, max=10000)` 明确拒绝（B0）。
        """
        r = _via("bootstrap_ci", {"n_bootstrap": bad}, features=[])
        assert r.status == "error", f"n_bootstrap={bad!r} 应被拒绝（迁移前被静默调整）"

    @pytest.mark.parametrize("ok", [100, 500, 10000])
    def test_n_bootstrap_boundaries_inclusive(self, ok):
        """`[100, 10000]` **闭**区间（原夹紧逻辑的上下界）。"""
        r = _via("bootstrap_ci", {"n_bootstrap": ok}, features=[])
        assert r.status == "ok", f"n_bootstrap={ok} 应被接受: {r.messages}"

    @pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5, "abc"])
    def test_ci_level_rejected(self, bad):
        r = _via("bootstrap_ci", {"ci_level": bad}, features=[])
        assert r.status == "error", f"ci_level={bad!r} 应被拒绝"

    @pytest.mark.parametrize("bad", [-1, 1.5, "abc"])
    def test_random_state_rejected(self, bad):
        r = _via("bootstrap_ci", {"random_state": bad}, features=[])
        assert r.status == "error", f"random_state={bad!r} 应被拒绝"


class TestGageRr:
    def test_gage_rr_tolerance_is_now_wired(self):
        """**该缺陷已于第三十轮修掉**（本用例随之从"钉住现状"改为"防回归"）。

        迁移前 AST 扫描证实 `gage_rr()` **完全不读** `tolerance`
        （而 `api-reference` 列出它、docstring 也写「用于 %P/T 计算」）。
        第三十轮按「文档已承诺 → 补实现」处理：`tolerance` 现在参与 `%P/T`
        计算（`= 100·6·σ_GRR / 公差`，出处见 `reliability.py` 的注释）。

        本用例保留为**回归防线**：它必须真的影响结果，且非法值必须被拒绝。
        """
        base = _via("gage_rr", {"tolerance": 5.0}, features=["part", "op"])
        other = _via("gage_rr", {"tolerance": 999.0}, features=["part", "op"])
        assert base.status == "ok" and other.status == "ok", base.messages
        assert base.metadata != other.metadata, (
            "tolerance 必须影响结果（%P/T）—— 若又变成不读，说明接线被回退"
        )
        # 它现在真的被读了，故非法值必须被拒绝（此前透传时会被静默接受）
        assert _via("gage_rr", {"tolerance": "abc"}, features=["part", "op"]).status == "error"

    @pytest.mark.parametrize("bad", [0, -1, float("inf"), "abc"])
    def test_sigma_multiplier_rejected(self, bad):
        """`sigma_multiplier` 须为正的有限数（原引擎已有 `isfinite` 守卫）。"""
        r = _via("gage_rr", {"sigma_multiplier": bad}, features=["part", "op"])
        assert r.status == "error", f"sigma_multiplier={bad!r} 应被拒绝"

    @pytest.mark.parametrize("ok", [5.15, 6.0])
    def test_sigma_multiplier_valid(self, ok):
        r = _via("gage_rr", {"sigma_multiplier": ok}, features=["part", "op"])
        assert r.status == "ok", r.messages


class TestEngineRaises:
    @pytest.mark.parametrize(
        "task,field,bad,feats",
        [
            ("scatter_plot", "fit", "poly", ["x1"]),
            ("tolerance_interval", "side", "both", []),
            ("bootstrap_ci", "statistic", "mode", []),
            ("gage_rr", "sigma_multiplier", 0, ["part", "op"]),
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
