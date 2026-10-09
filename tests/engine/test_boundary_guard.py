"""`engine/_guard.py` 边界处理原语的单元测试。

契约：docs/governance/boundary-contract.md（B0–B3）
本文件是该契约"执行点"的直接验证——每个原语的边界行为单独钉住，
不依赖上层引擎模块的间接覆盖。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.engine._guard import (
    BoundaryIssue,
    BoundaryReport,
    check_finite_param,
    check_magnitude,
    check_n,
    check_non_constant,
    check_tables_finite,
    clean_frame,
    clean_series,
    degenerate_column_code,
    degenerate_column_reason,
    degenerate_tables,
    explain_undefined_sigma,
    first_degenerate_reason,
    non_finite_tables,
    partition_finite,
)


class TestDegenerateColumnReason:
    """三级归因的**文案源**与"逐列检查"入口（契约 #5 收口新增的公开执行点）。

    `degenerate_column_code`（判据）与 `degenerate_column_reason`（文案）必须同源：
    各引擎模块只负责拼自己的后果语（"无法估计回归系数"），原因一律来自此处，
    否则「整列为空」又会被各模块自己编成「常量列」。
    """

    def test_reason_phrases_match_the_code(self):
        assert (
            degenerate_column_reason(pd.Series([5.0, 5.0]), what="目标列「y」")
            == "目标列「y」为常量列（无变异）"
        )
        assert (
            degenerate_column_reason(pd.Series([np.nan, np.nan]), what="特征列「x」")
            == "特征列「x」整列为空（没有任何有效观测）"
        )
        assert (
            degenerate_column_reason(pd.Series([7.0]), what="目标列「y」")
            == "目标列「y」有效观测不足 2 个（当前 1 个）"
        )
        assert degenerate_column_reason(pd.Series([1.0, 2.0])) is None

    def test_reason_defaults_label_to_shuju(self):
        assert degenerate_column_reason(pd.Series([5.0, 5.0])) == "数据为常量列（无变异）"

    def test_reason_agrees_with_code_on_every_shape(self):
        """任取一列：有 reason ⟺ 有 code（两者不得各自判一遍）。"""
        for values in ([5.0, 5.0], [np.nan], [7.0], [1.0, 2.0], []):
            s = pd.Series(values, dtype=float)
            assert (degenerate_column_reason(s) is None) == (degenerate_column_code(s) is None), (
                values
            )

    def test_first_degenerate_reason_names_the_first_offender(self):
        frame = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 4.0, 4.0], "c": [np.nan] * 3})
        assert first_degenerate_reason(frame, ["a", "b", "c"], label="特征列") == (
            "特征列「b」为常量列（无变异）"
        )
        # 顺序敏感：a 正常 → 跳过；b 常量 → 命中（即使 c 更"空"也不越过 b）
        assert first_degenerate_reason(frame, ["b", "c"], label="特征列") == (
            "特征列「b」为常量列（无变异）"
        )

    def test_first_degenerate_reason_none_when_all_vary(self):
        frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        assert first_degenerate_reason(frame, ["a", "b"]) is None
        assert first_degenerate_reason(frame, []) is None


class TestPartitionFinite:
    def test_counts_only_inf_not_nan(self):
        """计数**只含 ±Inf**，NaN 不计（2026-10-09 口径裁定：契约 L4/B1）。

        判据是"这个值是不是缺失"：NaN 是缺失（`dropna()` 静默处理已是全库语义），
        ±Inf 是"看起来像数据、数值上不合法"（除零/溢出），必须披露数量与列名。
        """
        s = pd.Series([1.0, np.inf, 2.0, -np.inf, np.nan, 3.0])
        mask, n = partition_finite(s)
        # ±Inf 有 2 个；NaN 有 1 个但**不计入**
        assert n == 2
        # 掩码仍是 isfinite：NaN 仍要被剔除（只是不进披露的数字）
        assert list(mask) == [True, False, True, False, False, True]

    def test_nan_only_reports_zero(self):
        s = pd.Series([1.0, np.nan, 2.0])
        mask, n = partition_finite(s)
        assert n == 0
        assert list(mask) == [True, False, True]

    def test_all_finite(self):
        s = pd.Series([1.0, 2.0, 3.0])
        _, n = partition_finite(s)
        assert n == 0

    def test_non_numeric_returns_all_true(self):
        """非数值列没有"非有限"概念，不应误报。"""
        s = pd.Series(["甲", "乙", None])
        mask, n = partition_finite(s)
        assert n == 0
        assert mask.all()

    def test_empty_series(self):
        _, n = partition_finite(pd.Series([], dtype=float))
        assert n == 0


class TestCleanSeries:
    def test_drops_inf_and_reports(self):
        s = pd.Series([1.0, np.inf, 2.0, -np.inf, 3.0])
        report = BoundaryReport()
        out, n = clean_series(s, column="测量", report=report)
        assert n == 2
        assert out.tolist() == [1.0, 2.0, 3.0]
        msgs = report.messages()
        assert len(msgs) == 1
        assert "测量" in msgs[0] and "2" in msgs[0]

    def test_nan_is_dropped_silently(self):
        """NaN 仍被剔除（缺失语义），但**不产生披露**、计数为 0。"""
        s = pd.Series([1.0, np.nan, 2.0])
        report = BoundaryReport()
        out, n = clean_series(s, report=report)
        assert out.tolist() == [1.0, 2.0], "NaN 必须仍被剔除（与 dropna 语义一致）"
        assert n == 0
        assert report.messages() == [], f"NaN 不得产生披露：{report.messages()}"

    def test_inf_and_nan_together_counts_only_inf(self):
        """名与量必须一致：数字只数 ±Inf，文案也只说 ±Inf。"""
        s = pd.Series([1.0, np.nan, np.inf, 2.0])
        report = BoundaryReport()
        out, n = clean_series(s, column="y", report=report)
        assert out.tolist() == [1.0, 2.0]
        assert n == 1
        msg = report.messages()[0]
        assert "1 个 ±Inf" in msg, msg
        assert "NaN" not in msg, f"文案不得再点名 NaN：{msg}"

    def test_no_drop_no_message(self):
        report = BoundaryReport()
        _, n = clean_series(pd.Series([1.0, 2.0]), report=report)
        assert n == 0
        assert report.messages() == []

    def test_without_report_does_not_raise(self):
        out, n = clean_series(pd.Series([1.0, np.inf]))
        assert n == 1 and len(out) == 1


class TestCleanFrame:
    def test_drops_rows_with_any_non_finite(self):
        df = pd.DataFrame({"a": [1.0, np.inf, 3.0], "b": [1.0, 2.0, -np.inf]})
        report = BoundaryReport()
        out, n = clean_frame(df, ["a", "b"], report=report)
        assert n == 2
        assert len(out) == 1
        assert "2 行" in report.messages()[0]

    def test_empty_cols_is_noop(self):
        df = pd.DataFrame({"a": [np.inf]})
        out, n = clean_frame(df, [])
        assert n == 0 and len(out) == 1

    def test_non_numeric_cols_is_noop(self):
        df = pd.DataFrame({"a": ["甲", "乙"]})
        _, n = clean_frame(df, ["a"])
        assert n == 0


class TestCheckN:
    def test_below_minimum_returns_issue(self):
        report = BoundaryReport()
        issue = check_n(2, 3, what="有效数据", report=report)
        assert issue is not None
        assert issue.level == "B0"
        assert issue.code == "E_DATA_INSUFFICIENT_N"
        assert "3" in issue.detail and "2" in issue.detail
        assert report.codes() == ["E_DATA_INSUFFICIENT_N"]

    def test_at_minimum_passes(self):
        assert check_n(3, 3) is None

    def test_above_minimum_passes(self):
        assert check_n(100, 3) is None


class TestCheckNonConstant:
    def test_constant_returns_issue(self):
        report = BoundaryReport()
        issue = check_non_constant(pd.Series([5.0, 5.0, 5.0]), what="目标列", report=report)
        assert issue is not None
        assert issue.code == "E_DATA_CONSTANT_COLUMN"
        assert "常量" in issue.detail

    def test_varying_passes(self):
        assert check_non_constant(pd.Series([1.0, 2.0])) is None

    def test_all_nan_is_constant(self):
        """全 NaN 列无变异——应报常量（区别于"含 Inf 导致 σ 不可算"）。"""
        assert check_non_constant(pd.Series([np.nan, np.nan])) is not None

    def test_inf_only_column_is_constant(self):
        """全是同一个 Inf → 仍是常量列（nunique=1）；此时不该归因为"含 Inf"。"""
        assert check_non_constant(pd.Series([np.inf, np.inf])) is not None


class TestNonConstantAttribution:
    """审查 2026-10-09 P2-3：三种退化列必须给出**不同**错误码，不得都叫"常量列"。

    契约边界清单 #5/#6/#7 把「常量列」「样本量不足」「整列为空」列为三种情形。
    原实现把后两者都折进 `E_DATA_CONSTANT_COLUMN`，于是：
    - 用户按"常量列"排查一个空列，永远查不到原因（错误归因）；
    - 与同模块 `explain_undefined_sigma` 对**同一输入**给出的
      「有效观测不足 2 个」自相矛盾（同文件两个 SSOT 打架）。
    """

    def test_all_nan_column_is_empty_not_constant(self):
        report = BoundaryReport()
        issue = check_non_constant(pd.Series([np.nan, np.nan]), what="目标列「Y」", report=report)
        assert issue is not None
        assert issue.code == "E_DATA_EMPTY_COLUMN", (
            f"整列为空应报 E_DATA_EMPTY_COLUMN（区别于「样本不足」），实际 {issue.code}"
        )
        assert "为空" in issue.detail, issue.detail
        assert "常量" not in issue.detail, f"整列为空不是常量列——那是错误归因：{issue.detail}"

    def test_empty_series_is_empty_column(self):
        issue = check_non_constant(pd.Series([], dtype=float))
        assert issue is not None and issue.code == "E_DATA_EMPTY_COLUMN"

    def test_single_valid_observation_is_insufficient_n(self):
        """恰好 1 个有效值：无法断言"所有观测相同"，那是样本量问题（越权推断防线）。"""
        issue = check_non_constant(pd.Series([7.0]))
        assert issue is not None
        assert issue.code == "E_DATA_INSUFFICIENT_N", issue.code
        assert "常量" not in issue.detail, issue.detail

    def test_one_value_plus_nan_is_insufficient_n(self):
        issue = check_non_constant(pd.Series([7.0, np.nan]))
        assert issue is not None and issue.code == "E_DATA_INSUFFICIENT_N"

    def test_two_equal_values_is_constant(self):
        """≥2 个有效值且全部相同 → 才是真正的常量列。"""
        issue = check_non_constant(pd.Series([5.0, 5.0, np.nan]))
        assert issue is not None and issue.code == "E_DATA_CONSTANT_COLUMN"

    def test_codes_match_explain_undefined_sigma_on_same_input(self):
        """同一输入，两个入口的归因必须一致（本模块内不得自相矛盾）。"""
        for s in (pd.Series([np.nan, np.nan]), pd.Series([7.0, np.nan]), pd.Series([5.0, 5.0])):
            a = check_non_constant(s)
            b = explain_undefined_sigma(s)
            assert a is not None
            assert a.code == b.code, f"输入 {s.tolist()}：{a.code} vs {b.code}"


class TestCheckMagnitude:
    """审查 2026-10-09 P1-4：量纲上界此前**无任何守卫**。

    同一份数据仅乘 1e300（相对关系不变）时，`Σy²` 溢出为 Inf，
    多个任务的判决静默翻转（1e153 判正态 / 1e152 判非正态）。
    守卫必须是**相对的**（只看量级），且不影响微尺度数据。
    """

    def test_normal_magnitude_passes(self):
        assert check_magnitude(pd.Series([50.0, 51.0, 49.0])) is None

    def test_large_but_safe_magnitude_passes(self):
        """1e9 量级的真实工程数据（如 Pa 单位应力）必须照常可用。"""
        assert check_magnitude(pd.Series([1e9, 2e9, 3e9])) is None

    def test_at_cap_passes(self):
        assert check_magnitude(pd.Series([1e150, 1.0])) is None

    def test_extreme_magnitude_rejected(self):
        report = BoundaryReport()
        issue = check_magnitude(pd.Series([1e300, 1.0]), what="目标列「y」", report=report)
        assert issue is not None
        assert issue.code == "E_SCALE_EXTREME_MAGNITUDE"
        assert issue.level == "B0"
        assert "1e300" in issue.detail or "量级" in issue.detail
        assert report.codes() == ["E_SCALE_EXTREME_MAGNITUDE"]

    def test_detail_tells_the_user_what_to_do(self):
        """B0 拒绝必须带**可执行建议**（契约「输出要求」列）。"""
        issue = check_magnitude(pd.Series([-1e300]))
        assert issue is not None
        assert "单位换算" in issue.detail and "中心化" in issue.detail, issue.detail

    @pytest.mark.parametrize("scale", [1e-12, 1e-9, 1.0, 1e6, 1e12])
    def test_micro_and_mid_scale_pass(self, scale):
        """微尺度（历史 P0 方向）与中等量级都不得被这条守卫误伤。"""
        assert check_magnitude(pd.Series([scale, 2 * scale])) is None

    def test_non_finite_only_series_passes(self):
        """全为 ±Inf/NaN 时无有限峰值 —— 归因交给 `check_non_constant`，不得越权。"""
        assert check_magnitude(pd.Series([np.inf, np.inf])) is None
        assert check_magnitude(pd.Series([np.nan])) is None

    def test_non_finite_does_not_mask_peak(self):
        """峰值只看有限值：含一个 +Inf 的 1e300 数据仍应被读出真实量级。"""
        issue = check_magnitude(pd.Series([1e300, np.inf, 1.0]))
        assert issue is not None and issue.code == "E_SCALE_EXTREME_MAGNITUDE"

    def test_non_numeric_column_passes(self):
        assert check_magnitude(pd.Series(["甲", "乙"])) is None

    def test_without_report_does_not_raise(self):
        issue = check_magnitude(pd.Series([1e300]))
        assert issue is not None
        assert issue.code == "E_SCALE_EXTREME_MAGNITUDE" and issue.level == "B0"
        assert "1e300" in issue.detail or "1e+300" in issue.detail, issue.detail


class TestOutputTablesAreFinite:
    """出口侧后置断言：结果表**退化**时必须能被判出（P1-4 / P2-10）。

    判据是"含 ±Inf"或"数值块全部非有限"，**不是**"见到 NaN 就拒绝" ——
    本仓哨兵契约把 `NaN` 定义为"无法判定"这一合法出口
    （`doe_analysis` 完全共线时把 `t值/p值` 写成 NaN + 「无法判定」，
    `tests/guards/test_micro_scale_guards.py::test_doe_analysis_perfect_fit_not_fabricated_zero_t`
    专门钉住它）。一刀切会把已固化的正确语义改坏 —— 本类同时钉住两个方向。
    """

    def test_clean_tables_pass(self):
        assert check_tables_finite({"t": pd.DataFrame({"a": [1.0, 2.0]})}) is None

    def test_all_nan_numeric_block_rejected(self):
        """数值块全是 NaN → 模型一个参数都没估出来，等价于"没有结果"。"""
        report = BoundaryReport()
        issue = check_tables_finite(
            {"coefficients": pd.DataFrame({"coef": [np.nan, np.nan]})},
            what="「response_surface」",
            report=report,
        )
        assert issue is not None
        assert issue.level == "B0"
        assert "coefficients" in issue.detail
        assert report.messages() == [issue.detail]

    def test_inf_in_numeric_column_rejected(self):
        """Inf 从不是合法哨兵 —— 即使同表还有有限值也必须拒绝。"""
        issue = check_tables_finite({"t": pd.DataFrame({"a": [1.0, np.inf]})})
        assert issue is not None and "t" in issue.detail
        assert "±Inf" in issue.detail

    def test_lone_nan_sentinel_is_allowed(self):
        """**反向**：单个 NaN 是既定的"无法判定"哨兵，不得拒绝（防修得过严）。

        反例现场：`doe_analysis` 完全共线（残差≈0）时 `t值=NaN`、
        同表 `效应` 仍是有限值 —— 这是刻意保留的语义，不是缺陷。
        """
        df = pd.DataFrame({"因子": ["g"], "效应": [4.0], "t值": [np.nan], "p值": [np.nan]})
        assert check_tables_finite({"effect_estimates": df}) is None

    def test_text_placeholder_is_not_a_violation(self):
        """「N/A」/「无法判定」等**文本**占位同样合法（表必须能如实说"算不出"）。"""
        df = pd.DataFrame({"Shapiro-Wilk p": ["无法判定", "N/A"]})
        assert check_tables_finite({"t": df}) is None

    def test_custom_code_is_used(self):
        issue = check_tables_finite(
            {"coefficients": pd.DataFrame({"a": [np.nan]})}, code="E_NUMERIC_MODEL_DEGENERATE"
        )
        assert issue is not None and issue.code == "E_NUMERIC_MODEL_DEGENERATE"

    def test_non_finite_tables_counts_by_name(self):
        bad = non_finite_tables(
            {
                "ok": pd.DataFrame({"a": [1.0]}),
                "bad": pd.DataFrame({"a": [np.nan, np.inf, 1.0]}),
            }
        )
        assert bad == {"bad": 2}, bad

    def test_degenerate_tables_explains_the_reason(self):
        reasons = degenerate_tables(
            {
                "all_nan": pd.DataFrame({"a": [np.nan, np.nan]}),
                "has_inf": pd.DataFrame({"a": [1.0, -np.inf]}),
                "sentinel_ok": pd.DataFrame({"a": [4.0, np.nan]}),
            }
        )
        assert set(reasons) == {"all_nan", "has_inf"}, reasons
        assert "非有限" in reasons["all_nan"]
        assert "±Inf" in reasons["has_inf"]

    def test_non_dataframe_entries_are_ignored(self):
        assert non_finite_tables({"meta": "不是表"}) == {}


class TestCheckFiniteParam:
    def test_none_returns_none_pair(self):
        val, issue = check_finite_param(None, "k")
        assert val is None and issue is None

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, float("nan")])
    def test_non_finite_rejected(self, bad):
        report = BoundaryReport()
        val, issue = check_finite_param(bad, "k", report=report)
        assert val is None
        assert issue is not None
        assert issue.code == "E_PARAM_NON_FINITE"
        assert "k" in issue.detail
        assert report.codes() == ["E_PARAM_NON_FINITE"]

    def test_non_numeric_rejected(self):
        val, issue = check_finite_param("abc", "alpha")
        assert val is None
        assert issue is not None
        assert issue.code == "E_PARAM_NOT_NUMERIC"
        assert issue.level == "B0"
        assert "alpha" in issue.detail and "abc" in issue.detail

    def test_numeric_string_accepted(self):
        """CLI/YAML 传来的字符串数字必须照常可用（否则破坏既有入口）。"""
        val, issue = check_finite_param("0.05", "alpha")
        assert val == pytest.approx(0.05)
        assert issue is None

    def test_zero_is_accepted(self):
        """falsy 陷阱防线：0 是合法参数值。"""
        val, issue = check_finite_param(0, "h")
        assert val == 0.0 and issue is None


class TestExplainUndefinedSigma:
    """本模块存在的首要理由：σ 不可估计时给出**正确归因**。"""

    def test_constant_column_blames_constant(self):
        issue = explain_undefined_sigma(pd.Series([3.0, 3.0, 3.0]), column="v")
        assert issue.code == "E_DATA_CONSTANT_COLUMN"
        assert "常量" in issue.detail

    def test_inf_column_blames_non_finite(self):
        """关键回归：含 +Inf 时**不得**归因为常量列。"""
        issue = explain_undefined_sigma(pd.Series([1.0, np.inf, 2.0]), column="v")
        assert issue.code == "E_DATA_NON_FINITE_BLOCKS_SIGMA"
        assert "常量" not in issue.detail
        assert "非有限值" in issue.detail

    def test_inf_after_nan_drop_still_blames_non_finite(self):
        """NaN + Inf 混合：剔除 NaN 后仍有 Inf → 归因为非有限值。"""
        issue = explain_undefined_sigma(pd.Series([np.nan, np.inf, 1.0]), column="v")
        assert issue.code == "E_DATA_NON_FINITE_BLOCKS_SIGMA"

    def test_single_observation_blames_n(self):
        issue = explain_undefined_sigma(pd.Series([5.0, np.nan]), column="v")
        assert issue.code == "E_DATA_INSUFFICIENT_N"

    def test_unexplained_uses_generic_code(self):
        """非常量、无非有限值、样本量足够 —— 落到未知原因的兜底码，不撒谎。"""
        issue = explain_undefined_sigma(pd.Series([1.0, 2.0, 3.0]), column="v")
        assert issue.code == "E_NUMERIC_SIGMA_UNDEFINED"

    def test_three_causes_have_distinct_codes(self):
        """三种原因必须给出不同错误码——这是"可诊断性"的核心。"""
        codes = {
            explain_undefined_sigma(pd.Series([1.0, 1.0])).code,
            explain_undefined_sigma(pd.Series([1.0, np.inf])).code,
            explain_undefined_sigma(pd.Series([1.0, np.nan])).code,
            explain_undefined_sigma(pd.Series([1.0, 2.0])).code,
        }
        assert len(codes) == 4, f"四种情形应给出 4 个不同错误码，实际 {codes}"

    def test_priority_constant_beats_non_finite(self):
        """优先级第一档：≥2 个有效值且全同 → 常量（即使含 ±Inf）。

        实现与 docstring 的**唯一**权威顺序是：
            常量 → 样本量 → 非有限值 → 兜底
        （审查 2026-10-09 P2-2：docstring 曾把「非有限值」排在「样本量」前，与实现相反）。
        """
        assert explain_undefined_sigma(pd.Series([np.inf, np.inf])).code == (
            "E_DATA_CONSTANT_COLUMN"
        )

    def test_priority_insufficient_n_beats_non_finite(self):
        """优先级第二档：有效观测 < 2 → 样本量。

        `[5.0, NaN]` 剔除 NaN 后只剩 1 个有效值，属样本量问题；
        先判"含非有限值"会把用户引向错误的排查方向（错误归因）。
        """
        issue = explain_undefined_sigma(pd.Series([5.0, np.nan]))
        assert issue.code == "E_DATA_INSUFFICIENT_N", issue.code

    def test_priority_non_finite_beats_fallback(self):
        """优先级第三档：有效值足够、非常量、但含 ±Inf → 非有限值。"""
        issue = explain_undefined_sigma(pd.Series([5.0, np.inf]))
        assert issue.code == "E_DATA_NON_FINITE_BLOCKS_SIGMA", issue.code


class TestBoundaryReport:
    def test_messages_deduplicates(self):
        r = BoundaryReport()
        r.add(BoundaryIssue(level="B1", code="E_X", detail="同一句提示"))
        r.add(BoundaryIssue(level="B1", code="E_X", detail="同一句提示"))
        assert r.messages() == ["同一句提示"]

    def test_codes_deduplicates_preserving_order(self):
        r = BoundaryReport()
        r.add(BoundaryIssue(level="B0", code="E_B", detail="b"))
        r.add(BoundaryIssue(level="B1", code="E_A", detail="a"))
        r.add(BoundaryIssue(level="B1", code="E_B", detail="b2"))
        assert r.codes() == ["E_B", "E_A"]

    def test_empty_report_is_falsy(self):
        """空报告为假值 —— 便于调用方写 `if boundary:`。"""
        assert not BoundaryReport()
        r = BoundaryReport()
        r.add(BoundaryIssue(level="B0", code="E_X", detail="x"))
        assert r

    def test_levels_are_limited_to_contract_values(self):
        """B0–B3 是本契约的全部级别（防止随意新增）。"""
        valid = {"B0", "B1", "B2", "B3"}
        r = BoundaryReport()
        r.add(BoundaryIssue(level="B3", code="E_X", detail="近似"))
        assert all(i.level in valid for i in r.issues)
