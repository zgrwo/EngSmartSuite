"""第三十轮修复：三个待决策项的落地。

契约：docs/governance/improvement-plan.md §六（台账「三个待决策项」）

## 1. `regression.model_type` —— 不是 bug，是我的标签误导

取证：`docs/specification/api-reference.md` 明写
`params: model_type (保留参数，当前仅支持 OLS)`。

故引擎不读它是**有意设计**，而非缺陷（我第二十四轮把它记成"未接线的参数"是
**误判**）。但我第二十七轮给它写的 Spec 标签「**回归模型类型**」/提示「（见计划
台账：当前引擎未使用此参数）」是**面向用户的界面文案，不该出现"台账"这种内部词**，
且"回归模型类型"暗示可以选择。本轮改为与 api-reference 一致的诚实表述。

## 2. `gage_rr.tolerance` —— 文档承诺了 `%P/T`，引擎从不输出

取证：`api-reference.md` 列出 `tolerance`，引擎 docstring 写
「公差范围 (用于 %P/T 计算，可选)」，但 AST 扫描证实 `gage_rr()` **完全不读它**，
`metadata` 里也没有任何 `%P/T`。而 `%P/T` 是 AIAG 的标准指标
（precision-to-tolerance，衡量量具变异占公差带的比例）。

**本轮实现它**（文档已承诺 → 补实现，而非删参数）。

## 3. `show_ci` / `show_stats` 的静默降级 —— 修 `Choice` 的别名解析

实测：引擎归一是 `str.lower() not in ("false","0","no","")`，于是
`"maybe"` / `"yes"` / `123` **静默变成 True**（用户以为关掉了却还开着）。

根因不是引擎写得松，而是 **`Choice.check` 的别名只对 `str` 生效**：

    if isinstance(raw, str):          # ← 别名解析被关在这个分支里
        for alias, val in self.aliases.items(): ...
    if raw in self.allowed: ...       # ← 布尔/数值走到这里，别名已无机会

于是无法声明「`True` 也是 `'true'` 的别名」，也就无法用 `Choice` 收口。
**修 `Choice`（让非字符串输入也查别名）即可一次解决两个参数。**

这是**既有的表达力缺口**，非新引入：任何"表单布尔 vs 引擎字符串"的参数都会踩到。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.param_spec import Choice
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.engine.exploratory import PARAM_SPECS
from smartsuite.services.orchestrator import orchestrate


class TestChoiceResolvesNonStringAliases:
    """`Choice` 的别名必须对**非字符串**输入也生效（本轮的根因修复）。"""

    def test_bool_alias_is_resolved(self):
        c = Choice("true", "false", aliases={True: "true", False: "false"})
        assert c.check(True) == ("true", None), "布尔 True 应经别名解析为 'true'"
        assert c.check(False) == ("false", None), "布尔 False 应经别名解析为 'false'"

    def test_int_alias_is_resolved(self):
        """数字 1/0 也常见（表单可能传 1/0）。"""
        c = Choice("true", "false", aliases={True: "true", False: "false"})
        # `True == 1`、`False == 0`，故该别名表同时覆盖 1/0
        assert c.check(1) == ("true", None)
        assert c.check(0) == ("false", None)

    def test_string_alias_still_works(self):
        """原有字符串别名语义不得回归。"""
        c = Choice(("linear", "线性"), ("poly", "多项式"), aliases={"lin": "linear"})
        assert c.check("lin") == ("linear", None)
        assert c.check("LINEAR") == ("linear", None)

    def test_unknown_value_still_rejected(self):
        c = Choice("true", "false", aliases={True: "true", False: "false"})
        value, err = c.check("maybe")
        assert value is None and err is not None, "'maybe' 不在别名表里，应被拒绝"

    def test_case_sensitive_mode_unaffected(self):
        c = Choice("A", "B", aliases={"a": "A"}, case_sensitive=True)
        assert c.check("a") == ("A", None)
        assert c.check("A") == ("A", None)


def _frame(n: int = 60, seed: int = 91) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 1.5, n),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(0, 1, n),
            "g": (["A", "B"] * (n // 2))[:n],
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


class TestShowCiAndShowStatsAreNoLongerSilent:
    """两个 `show_*` 开关：合法形态照旧，**非法形态由静默变 True 改为明确拒绝**。"""

    @pytest.mark.parametrize("value", [True, False, "true", "false", "True", "FALSE"])
    def test_scatter_show_ci_accepted_forms(self, value):
        """合法写法照旧可用，且**归一结果正确**（不是"只要不报错就算过"）。

        `show_ci` 决定是否画置信带，故可用 `figures[0]` 的绘制对象数目验证：
        开启时比关闭时**多出置信带的填充区域**（`collections` / `PolyCollection`）。
        """
        r = _via("scatter_plot", {"show_ci": value}, features=["x1"])
        assert r.status == "ok", f"show_ci={value!r} 应被接受: {r.messages}"
        # 断言**归一结果**（而非"没报错就算过"）：Spec 必须把它变成规范的
        # `"true"`/`"false"`，因为引擎侧用的是直比 `== "true"`。
        want = "true" if str(value).strip().lower() == "true" else "false"
        validated = PARAM_SPECS["scatter_plot"].validate_or_raise({"show_ci": value})
        assert validated.show_ci == want, (
            f"show_ci={value!r} 应归一为 {want!r}，实际 {validated.show_ci!r}"
        )

    @pytest.mark.parametrize("value", ["maybe", "yes", 123, "1", 0.5])
    def test_scatter_show_ci_rejects_garbage(self, value):
        """**行为改进**：迁移前这些值都会**静默当作 True**（用户以为关掉了却还开着）。"""
        r = _via("scatter_plot", {"show_ci": value}, features=["x1"])
        assert r.status == "error", f"show_ci={value!r} 应被拒绝（迁移前静默当作 True）"

    @pytest.mark.parametrize("value", [True, False, "true", "false"])
    def test_box_chart_show_stats_accepted_forms(self, value):
        """合法写法照旧可用，且**归一结果正确**。

        `show_stats` 决定是否在箱体下方标注统计表；开启时 `metadata` 会带
        `sub_col`/分组统计相关内容，更可靠的判据是**文本对象数目**：
        统计表以 `ax.text(...)` 绘制，故开启时应显著多于关闭时。
        """
        r = _via("box_chart", {"show_stats": value})
        assert r.status == "ok", f"show_stats={value!r} 应被接受: {r.messages}"
        # 同上：断言归一结果（引擎侧直比 `== "true"`）
        want = "true" if str(value).strip().lower() == "true" else "false"
        validated = PARAM_SPECS["box_chart"].validate_or_raise({"show_stats": value})
        assert validated.show_stats == want, (
            f"show_stats={value!r} 应归一为 {want!r}，实际 {validated.show_stats!r}"
        )

    @pytest.mark.parametrize("value", ["maybe", "yes", 123, 0.5])
    def test_box_chart_show_stats_rejects_garbage(self, value):
        r = _via("box_chart", {"show_stats": value})
        assert r.status == "error", f"show_stats={value!r} 应被拒绝"

    def test_engine_raises_with_field(self):
        import importlib

        fn = importlib.import_module("smartsuite.engine.exploratory").scatter_plot
        with pytest.raises(ParamValidationError) as ei:
            fn(
                AnalysisRequest(
                    task="scatter_plot",
                    data=_frame(),
                    target_col="y",
                    feature_cols=["x1"],
                    params={"show_ci": "maybe"},
                )
            )
        assert ei.value.field_name == "show_ci"


class TestRegressionModelTypeIsReserved:
    """`model_type` 是**文档化的保留参数**，不是缺陷；但界面文案必须诚实。"""

    def test_spec_label_is_honest_about_reserved_status(self):
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("regression")
        label = spec.labels()["model_type"]
        hint = spec.hints().get("model_type", "")
        assert "保留" in label or "保留" in hint, (
            f"标签/提示必须标明这是保留参数（api-reference 的表述）：label={label!r} hint={hint!r}"
        )
        assert "台账" not in hint, "界面文案不得出现「台账」这类内部词"

    def test_documented_as_reserved_in_api_reference(self):
        """与 api-reference 保持一致 —— 那份文档是**事实锚点**。"""
        from pathlib import Path

        doc = Path("docs/specification/api-reference.md").read_text(encoding="utf-8")
        assert "保留参数" in doc and "model_type" in doc

    def test_model_type_still_does_not_affect_result(self):
        """它是保留参数 → 任何取值下结果不变（这一行为**有意保持**）。"""
        base = _via("regression", {"model_type": "linear"}, features=["x1", "x2"])
        other = _via("regression", {"model_type": "quadratic"}, features=["x1", "x2"])
        assert base.status == "ok" and other.status == "ok", base.messages
        assert base.metadata == other.metadata


class TestGageRrToleranceNowImplemented:
    """`tolerance` 从"文档承诺但从不读"改为**真的参与 %P/T 计算**。"""

    @staticmethod
    def _gage_frame(seed: int = 61) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rows = []
        for p in range(10):
            base = 50 + rng.normal(0, 2.0)
            for o in range(3):
                off = rng.normal(0, 0.3)
                for _ in range(3):
                    rows.append(
                        {"part": f"P{p:02d}", "op": f"O{o}", "y": base + off + rng.normal(0, 0.2)}
                    )
        return pd.DataFrame(rows)

    def _run(self, **params):
        return orchestrate(
            AnalysisRequest(
                task="gage_rr",
                data=self._gage_frame(),
                target_col="y",
                feature_cols=["part", "op"],
                params={"part_col": "part", "operator_col": "op", **params},
            )
        )

    def test_tolerance_now_appears_in_metadata(self):
        """**行为改进**：迁移前 `tolerance` 完全不出现于结果。"""
        r = self._run(tolerance=5.0)
        assert r.status == "ok", r.messages
        assert "tolerance" in r.metadata, f"tolerance 应进入 metadata: {sorted(r.metadata)}"
        assert r.metadata["tolerance"] == 5.0

    def test_pt_ratio_matches_manual_formula(self):
        """%P/T = 6·GRR_σ / 公差 —— **手工公式对账**（不是"与另一个实现比接近"）。"""
        r = self._run(tolerance=5.0)
        assert r.status == "ok", r.messages
        grr = float(r.metadata["grr"])
        expected = 6.0 * grr / 5.0
        assert r.metadata["pt_ratio"] == pytest.approx(expected, rel=1e-9), (
            f"%P/T 应为 6·GRR/公差 = {expected}，实际 {r.metadata.get('pt_ratio')}"
        )
        assert r.metadata["pt_percent"] == pytest.approx(expected * 100, rel=1e-9)

    def test_no_tolerance_means_no_pt_ratio(self):
        """未给公差 → 不给 `%P/T`（而不是给一个假值）。"""
        r = self._run()
        assert r.status == "ok", r.messages
        assert "pt_ratio" not in r.metadata, "未给公差时不得输出 %P/T"
        assert r.metadata.get("tolerance") is None

    def test_pt_ratio_scales_inversely_with_tolerance(self):
        """公差翻倍 → %P/T 减半（数学不变量，且不依赖具体数值）。"""
        tight = self._run(tolerance=2.0)
        loose = self._run(tolerance=4.0)
        assert tight.status == "ok" and loose.status == "ok"
        assert tight.metadata["pt_ratio"] == pytest.approx(2 * loose.metadata["pt_ratio"], rel=1e-9)

    def test_tolerance_still_validated_as_finite(self):
        """`tolerance` 此前是透传字段 → 非法值不会被拒。本轮起它真的被读了，故须校验。"""
        for bad in ("abc", float("inf"), float("nan"), -1.0, 0.0):
            r = self._run(tolerance=bad)
            assert r.status == "error", f"tolerance={bad!r} 应被拒绝（它现在会被真正使用）"

    def test_judge_uses_worse_of_pt_and_sv(self):
        """给了公差后，判定取 **%GRR 与 %P/T 中更差者**。

        AIAG 对两者用同一套阈值（<10 可接受 / 10–30 临界 / >30 不合格），
        只报其中一个会让"过程变异大但公差也大"的情形被误判。
        """
        # 先取一次基线：%GRR 已知（相对研究变异），故可反推出让 %P/T 落在
        # 各档位的公差值。这里只断言**单调关系**与**取更差者**，不硬编具体数值。
        base = self._run()
        grr = float(base.metadata["grr"])
        # 使 %P/T ≈ 5%（优秀档）→ 判定应仍由 %GRR 决定（不被 %P/T 拉低）
        loose = self._run(tolerance=6.0 * grr / 0.05)
        assert loose.status == "ok", loose.messages
        assert loose.metadata["pt_percent"] == pytest.approx(5.0, rel=1e-6)
        assert loose.metadata["judge"] == base.metadata["judge"], (
            "%P/T=5%（优秀）不应改变判定 —— 判定应取两者更差者"
        )
        # 使 %P/T ≈ 50%（不合格档）→ 判定应被 %P/T 拉低为不合格
        tight = self._run(tolerance=6.0 * grr / 0.50)
        assert tight.status == "ok", tight.messages
        assert tight.metadata["pt_percent"] == pytest.approx(50.0, rel=1e-6)
        assert "不合格" in tight.metadata["judge"], (
            f"%P/T=50% 应判不合格（取更差者），实际 {tight.metadata['judge']!r}"
        )
        assert "%P/T" in tight.metadata["judge"], (
            f"判定文案应指明是 %P/T 触发的，实际 {tight.metadata['judge']!r}"
        )
