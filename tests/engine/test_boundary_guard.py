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
    check_n,
    check_non_constant,
    clean_frame,
    clean_series,
    explain_undefined_sigma,
    partition_finite,
)


class TestPartitionFinite:
    def test_counts_non_finite(self):
        s = pd.Series([1.0, np.inf, 2.0, -np.inf, np.nan, 3.0])
        mask, n = partition_finite(s)
        # NaN 与 ±Inf 都算非有限
        assert n == 3
        assert list(mask) == [True, False, True, False, False, True]

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

    def test_nan_is_treated_as_non_finite(self):
        """NaN 与 ±Inf 一并剔除（np.isfinite 语义），披露计数含 NaN。"""
        s = pd.Series([1.0, np.nan, 2.0])
        out, n = clean_series(s)
        assert n == 1
        assert out.tolist() == [1.0, 2.0]

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
