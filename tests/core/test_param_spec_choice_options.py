"""`Choice` 选项显示文案的测试（阶段 P4 步骤④前置）。

契约：docs/governance/improvement-plan.md §六

## 补的是哪一处表达力缺口

`Spec` 原本能声明参数名、标签、提示、可选值 —— 但**不能声明"每个可选值显示什么"**。
而前端 `PARAM_META` 里 23 条 `select` 正是这种数据：

    ss_type: { type: 'select', label: '平方和类型',
               options: [[2, 'Type II（引擎默认）'], [3, 'Type III（Minitab/SAS 默认）']] }

引擎侧只有 `_SUPPORTED_SS_TYPES = (2, 3)`（裸值，无文案）。故 `PARAM_META`
无法派生 —— 这是它成为**最后一份大重复**（169 行）的原因。

本模块给 `Choice` 加 `options()` 与 `labeled()`，把"值 + 显示文案"一起声明，
使派生成为可能。

## 设计取舍

- **标签可选**：不写标签的候选值，前端显示该值本身（`str(value)`）——
  避免为了满足接口而给 `p/np/c/u` 这种自明值硬写文案。
- **`options()` 与 `allowed` 保持同步**：`options()` 必须覆盖全部 `allowed`，
  且顺序一致（下拉顺序即声明顺序，有语义）。
- **别名归一化后再给选项**：`aliases` 的值若不在 `allowed` 里，也应在选项中出现
  （用户能选到它），但不重复。
"""

from __future__ import annotations

import pytest

from smartsuite.core.param_spec import Choice, Opt, Spec, Violation


class TestLabeledOptions:
    """带显示文案的候选值。"""

    def test_options_exposes_value_label_pairs(self):
        ch = Choice((2, "Type II（引擎默认）"), (3, "Type III（Minitab/SAS 默认）"))
        assert ch.options() == [(2, "Type II（引擎默认）"), (3, "Type III（Minitab/SAS 默认）")]

    def test_plain_values_get_str_label(self):
        """未给文案的候选值，显示文案即其 `str()`。"""
        ch = Choice("p", "np", "c", "u")
        assert ch.options() == [("p", "p"), ("np", "np"), ("c", "c"), ("u", "u")]

    def test_mixed_plain_and_labeled(self):
        """允许混用：自明值可不给文案，需解释的值给文案。"""
        ch = Choice("linear", ("gbm", "梯度提升（需较多数据）"))
        assert ch.options() == [("linear", "linear"), ("gbm", "梯度提升（需较多数据）")]

    def test_allowed_still_contains_only_values(self):
        """`allowed` 语义不变：只含**值**（不含文案），以免破坏既有校验与 `in` 判断。"""
        ch = Choice((2, "Type II"), (3, "Type III"))
        assert ch.allowed == (2, 3)
        assert ch.check(2)[0] == 2
        assert ch.check(3)[0] == 3

    def test_options_order_follows_declaration(self):
        """顺序即声明顺序 —— 下拉顺序有语义（如默认项在前）。"""
        ch = Choice((3, "Type III"), (2, "Type II"))
        assert [v for v, _ in ch.options()] == [3, 2]

    def test_check_rejects_value_not_in_allowed(self):
        ch = Choice((2, "Type II"), (3, "Type III"))
        _, err = ch.check(4)
        assert err is not None and err.code == "NOT_IN_CHOICES"
        # 提示里应给出**值**（而非文案）
        assert "2" in err.message and "3" in err.message

    def test_aliases_appear_in_options_when_distinct(self):
        """别名若指向 `allowed` 之外的值，也应出现在选项里（否则用户选不到）。"""
        ch = Choice("linear", aliases={"ols": "ols_linear"})
        values = [v for v, _ in ch.options()]
        assert "linear" in values
        assert "ols_linear" in values, f"别名目标值应在选项中: {values}"

    def test_alias_to_allowed_does_not_duplicate(self):
        """别名指向 `allowed` 内的值时不重复出现。"""
        ch = Choice("linear", "gbm", aliases={"ols": "linear"})
        values = [v for v, _ in ch.options()]
        assert values.count("linear") == 1, values

    def test_normalization_unaffected_by_labels(self):
        """带文案不影响既有校验语义。

        两类既有语义都要保住：
          - **字符串**候选值大小写归一（`Choice("Required_N")` 接受 `"required_n"`）；
          - **非字符串**候选值不接受字符串写法（`Choice(2, 3)` 拒绝 `"2"`；
            需要时由 `aliases` 显式登记 —— 这条曾在本模块首版写反过）。
        """
        ch = Choice((2, "Type II"), (3, "Type III"))
        _, err = ch.check("2")
        assert err is not None and err.code == "NOT_IN_CHOICES", "整数候选不应匹配字符串"
        assert ch.check(2)[0] == 2

        ch2 = Choice("Required_N", "achieved")
        assert ch2.check("required_n")[0] == "Required_N", "字符串候选应大小写归一"

        ch3 = Choice((2, "Type II"), (3, "Type III"), aliases={"2": 2, "3": 3})
        assert ch3.check("3")[0] == 3, "显式别名应可接受字符串写法"

    def test_labeled_options_work_through_spec(self):
        """端到端：`Spec` 校验与内省在带文案的 `Choice` 上正常。"""
        spec = Spec(
            ss_type=Opt(Choice((2, "Type II"), (3, "Type III")), default=2, label="平方和类型")
        )
        ok, err = spec.validate({"ss_type": 3})
        assert err is None and ok.ss_type == 3
        assert spec.labels()["ss_type"] == "平方和类型"

    def test_choice_without_candidates_still_raises(self):
        with pytest.raises(ValueError, match="至少需要一个候选值"):
            Choice()

    def test_empty_label_falls_back_to_str_value(self):
        """文案为空串时回落到 `str(值)`（不显示空白选项）。"""
        ch = Choice((2, ""), (3, "Type III"))
        assert ch.options() == [(2, "2"), (3, "Type III")]

    def test_labeled_accepts_non_string_values(self):
        ch = Choice((1.5, "一点五"), (True, "真"))
        opts = dict(ch.options())
        assert opts[1.5] == "一点五"
        assert opts[True] == "真"

    def test_options_is_a_method_not_attribute(self):
        """必须是方法：`options` 若做成属性会与 dataclass 字段/构造参数混淆
        （`Choice(*allowed, aliases=..., case_sensitive=...)` 已用显式 `__init__`，
        再加字段会破坏该签名）。"""
        ch = Choice("a")
        assert callable(ch.options)


class TestCustomValidatorStillWorks:
    """回归：`Violation` 与 `Custom` 不受本次改动影响。"""

    def test_custom_with_labeled_choice_in_same_spec(self):
        def fn(raw):
            return (raw, None) if raw != "bad" else (None, Violation("不接受 bad", "BAD"))

        from smartsuite.core.param_spec import Custom

        spec = Spec(
            mode=Opt(Choice(("a", "甲"), ("b", "乙")), default="a", label="模式"),
            extra=Opt(Custom(fn), default="ok", label="额外"),
        )
        ok, err = spec.validate({"mode": "b", "extra": "bad"})
        assert ok is None and err is not None and err.code == "E_PARAM_BAD"
