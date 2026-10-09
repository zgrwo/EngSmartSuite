"""参数解析的溢出/静默兜底回归防线（审查 2026-10-09 P1-3 / P1-8）。

P1-3 两个缺陷面：

1. **`OverflowError` 穿透**：`float(int)` 超过 1.8e308 会抛 `OverflowError`，
   而 `except (ValueError, TypeError)` **抓不到它** → 400 位整数参数（可经
   YAML/CLI/JSON 构造）会一路冒到 orchestrator 的兜底 except，
   报「数值溢出。[数据] 请检查数据范围是否极端」—— 把**参数**问题归因到**数据**。
   （`float("1e400")` 走字符串路径返回 `inf`，所以历史只补了字符串那一半。）
2. **静默兜成"有意义的数值"**：`safe_float('abc', 1.0)` 返回 `1.0` —— 一个合法且会
   改变结论的正则化强度，用户看到"跑完了"而实际用的不是他写的值。

P1-8：`grid_search.n_points` 的夹紧是静默的（`_n_points_requested` 存了原值却从未
出现在任何文案里 = 死变量），而网格密度直接决定"最优参数"的精度（属 B2 降级）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestOverflowErrorIsCaught:
    """400 位整数是合法 JSON/YAML 字面量，必须在参数层被拒，而不是穿到数据层。"""

    HUGE = 10**400  # float(HUGE) → OverflowError: int too large to convert to float

    def test_safe_float_returns_default_instead_of_raising(self):
        from smartsuite.engine._utils import safe_float

        assert safe_float(self.HUGE, 0.05) == 0.05

    def test_check_finite_param_rejects_as_param_problem(self):
        from smartsuite.engine._guard import check_finite_param

        value, issue = check_finite_param(self.HUGE, "usl")
        assert value is None
        assert issue is not None
        # 关键：错误码必须是「参数」而非「数据」
        assert issue.code == "E_PARAM_NOT_NUMERIC", issue.detail
        assert "usl" in issue.detail

    def test_yaml_big_int_reaches_param_layer(self):
        """端到端：`usl: 1e400` 走 YAML → 参数层拒绝，且**不提"数据"**。"""
        import yaml

        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        params = yaml.safe_load(f"usl: {self.HUGE}")
        rng = np.random.default_rng(5)
        df = pd.DataFrame({"y": rng.normal(50, 5, 120)})
        r = orchestrate(
            AnalysisRequest(
                task="process_capability", data=df, target_col="y", feature_cols=[], params=params
            )
        )
        assert r.status == "error", r.summary
        blob = " ".join(r.messages or [])
        # 必须点名是**参数**（用中文标签「规格上限 (USL)」），而不是笼统的"数值溢出"
        assert "USL" in blob or "usl" in blob, f"必须点名是哪个参数：{blob}"
        # 且不得把它归因到数据（P1-3 的原缺陷正是归因到了「[数据] 请检查数据范围」）
        assert "[数据]" not in blob, f"参数问题不得归因到数据：{blob}"
        assert "异常（成因未归类）" not in blob, f"不得落进未归类兜底：{blob}"


class TestLassoAlphaIsNotSilentlyDefaulted:
    """`alpha_lasso` 解析失败必须显式拒绝，不得静默用 1.0 跑完。"""

    @staticmethod
    def _frame():
        rng = np.random.default_rng(7)
        return pd.DataFrame(
            {
                "y": rng.normal(50, 5, 80) + 0.3 * rng.normal(0, 1, 80),
                "x1": rng.normal(0, 1, 80),
                "x2": rng.normal(0, 1, 80),
            }
        )

    @pytest.mark.parametrize("bad", ["abc", "null", "1e400"])
    def test_bad_alpha_is_rejected(self, bad):
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        r = orchestrate(
            AnalysisRequest(
                task="lasso_regression",
                data=self._frame(),
                target_col="y",
                feature_cols=["x1", "x2"],
                params={"alpha_lasso": bad},
            )
        )
        assert r.status == "error", f"alpha_lasso={bad!r} 不应静默兜成 1.0 后跑完：{r.summary}"
        assert "alpha_lasso" in " ".join(r.messages or []), r.messages

    def test_auto_sentinel_is_honored_not_coerced_to_one(self):
        """`alpha_lasso='auto'` 必须真的走"自动搜索 α"，而不是被悄悄换成 1.0。

        这是本条最锋利的一刀：旧实现 `_safe_float('auto', 1.0)` 把 `float('auto')`
        的 ValueError 兜成 **1.0** —— 于是 `'auto'` 与显式 `1.0` 给出**完全相同**的结果，
        看起来"支持 auto"，实际两者都没做 CV 搜索。
        故断言：`'auto'` 的所选 α 必须与显式 `1.0` **不同**，且与"不传 α"一致。
        """
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        def _alpha_of(params):
            r = orchestrate(
                AnalysisRequest(
                    task="lasso_regression",
                    data=self._frame(),
                    target_col="y",
                    feature_cols=["x1", "x2"],
                    params=params,
                )
            )
            assert r.status == "ok", f"params={params}: {r.messages}"
            return float(r.metadata["best_alpha"])

        auto, explicit_one, absent = (
            _alpha_of({"alpha_lasso": "auto"}),
            _alpha_of({"alpha_lasso": 1.0}),
            _alpha_of({}),
        )
        assert auto != pytest.approx(explicit_one), (
            f"'auto' 与显式 1.0 结果相同（{auto}）—— 说明 'auto' 仍被静默兜成了 1.0"
        )
        assert auto == pytest.approx(absent), (
            f"'auto' 应与「不传 α」等价（同为 CV 自选），实际 auto={auto} absent={absent}"
        )

    def test_valid_alpha_and_absent_alpha_still_work(self):
        """防修得过严：合法值与"不给"都必须照常出结果，且 R² 是有限实数。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        # `""` 是「未提供」哨兵（orchestrator 的空值归一）、`"auto"` 是**合法哨兵**
        # （引擎自行搜索 α）—— 两者都不是非法值，都必须照常跑。
        # ⚠️ `"auto"` 是我第一版修 P1-3 时误拒的（被 batch5 的既有用例抓住），
        # 这里把它显式列进"必须放行"清单，防止下次再收窄过头。
        for params in (
            {},
            {"alpha_lasso": 0.01},
            {"alpha_lasso": "0.01"},
            {"alpha_lasso": ""},
            {"alpha_lasso": "auto"},
        ):
            r = orchestrate(
                AnalysisRequest(
                    task="lasso_regression",
                    data=self._frame(),
                    target_col="y",
                    feature_cols=["x1", "x2"],
                    params=params,
                )
            )
            assert r.status == "ok", f"params={params}: {r.messages}"
            # 真实值断言（不只 status）：模型确实跑出了有限的 R²，且选中的变量数合理
            r2 = r.metadata.get("r_squared")
            if r2 is None:
                r2 = r.metadata.get("test_r2")
            assert r2 is not None and np.isfinite(float(r2)), (
                f"params={params}: metadata={r.metadata}"
            )
            assert "选中" in r.summary, f"params={params}: {r.summary}"


class TestGridSearchClampIsDisclosed:
    """网格密度被夹紧时必须披露（B2 降级：最优参数精度随之变化）。"""

    @staticmethod
    def _frame():
        rng = np.random.default_rng(11)
        return pd.DataFrame(
            {"y": rng.normal(50, 5, 200), "a": rng.normal(0, 1, 200), "b": rng.normal(0, 1, 200)}
        )

    def _run(self, n_points):
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        return orchestrate(
            AnalysisRequest(
                task="grid_search",
                data=self._frame(),
                target_col="y",
                feature_cols=["a", "b"],
                params={"ranges": {"a": (-2, 2), "b": (-2, 2)}, "n_points": n_points},
            )
        )

    def test_clamped_request_is_disclosed_with_both_numbers(self):
        r = self._run(80)
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert "网格密度已按上限调整" in blob, f"夹紧必须披露：{r.messages}"
        # 名与量一致：请求值与实际值都要出现
        assert "80" in blob and "30" in blob, blob
        assert r.metadata["n_points_requested"] == 80
        assert r.metadata["n_points_used"] == 30

    def test_unclamped_request_has_no_spurious_note(self):
        r = self._run(10)
        assert r.status == "ok", r.messages
        assert r.messages == [], f"未夹紧时不得有噪音披露：{r.messages}"
        assert r.metadata["n_points_requested"] == r.metadata["n_points_used"] == 10
