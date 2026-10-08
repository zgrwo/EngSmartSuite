"""声明式参数契约的测试（阶段 P4 基础设施）。

契约：docs/governance/improvement-plan.md §六

本文件锁定三件事：

1. **校验语义**：每个校验器接受什么、拒绝什么、给什么错误码；
2. **`None` 的语义**：与引擎既有约定一致（`None` = 未提供）；
3. **内省输出**：`defaults()` / `labels()` / `hints()` 的形状 —— 它们将来是
   `DEFAULT_PARAMS` / `TASK_PARAMS` / `PARAM_META` / `PARAM_LABELS` / `PARAM_HINTS`
   五份平行字典的**唯一来源**，形状变了会连带影响前端与文档生成。

> 本模块首版在 `Choice` 的签名上连续踩两处（`aliases` 被当候选值、
> 随后又位置冲突），故 `test_choice_signature_is_variadic` 单独立一条防回归。
"""

from __future__ import annotations

import numpy as np
import pytest

from smartsuite.core.exceptions import ParamValidationError, SmartSuiteError
from smartsuite.core.param_spec import (
    Choice,
    CrossRule,
    Custom,
    Finite,
    Integer,
    Opt,
    ParamError,
    Req,
    Spec,
    Text,
    ValidatedParams,
    Violation,
)


def _spec() -> Spec:
    return Spec(
        usl=Opt(Finite(gt=0), label="规格上限 (USL)", hint="USL 应大于 LSL"),
        lsl=Opt(Finite(gt=0), label="规格下限 (LSL)"),
        alpha=Opt(Finite(gt=0, lt=1), default=0.05, label="显著性水平 α"),
        transform=Opt(Choice("boxcox"), label="正态化变换"),
        subgroup_size=Opt(Integer(min=2), label="子组大小"),
        model=Req(Choice("linear", "gbm", aliases={"ols": "linear"}), label="模型"),
        note=Opt(Text(allow_empty=False), default="x", label="备注"),
    )


class TestValidators:
    """各校验器的行为。"""

    def test_finite_accepts_numeric_strings(self):
        val, err = Finite().check("10.5")
        assert err is None and val == 10.5 and isinstance(val, float)

    @pytest.mark.parametrize("bad", ["inf", "-inf", "nan", float("inf"), float("nan")])
    def test_finite_rejects_non_finite(self, bad):
        """NaN/Inf 必须被拒绝（sentinel-contract L1：不可估计不得伪造）。

        原症状：`float("inf")` 不抛异常，故 `try: float(x)` 会静默放过。
        """
        val, err = Finite().check(bad)
        assert err is not None, f"应被拒绝但通过了: {bad!r}"
        assert err.code == "NOT_FINITE", err
        assert val is None, f"拒绝时值应为 None，实际 {val!r}"

    @pytest.mark.parametrize("bad", ["abc", "", "1,5"])
    def test_finite_reports_not_numeric_with_distinct_code(self, bad):
        """非数值与 NaN/Inf 是**不同**错误，必须给不同码（禁止错误归因）。"""
        val, err = Finite().check(bad)
        assert err is not None, f"应被拒绝但通过了: {bad!r}"
        assert err.code == "NOT_NUMERIC", err
        assert val is None, f"拒绝时值应为 None，实际 {val!r}"

    def test_finite_reports_out_of_range_with_distinct_code(self):
        _, err = Finite(gt=0, lt=1).check(2)
        assert err.code == "OUT_OF_RANGE", err

    def test_finite_rejects_bool(self):
        """bool 是 int 子类，`float(True)` 会得到 1.0 —— 语义上不该当数值接受。"""
        _, err = Finite().check(True)
        assert err.code == "NOT_NUMERIC", err

    def test_finite_bounds_all_four_operators(self):
        for kwargs, ok_val, bad_val in (
            ({"gt": 0}, 1, 0),
            ({"ge": 0}, 0, -1),
            ({"lt": 10}, 9, 10),
            ({"le": 10}, 10, 11),
        ):
            v, e = Finite(**kwargs).check(ok_val)
            assert e is None, f"合法值却被拒: {kwargs}, {ok_val}"
            assert v == float(ok_val), (kwargs, v)
            _, e2 = Finite(**kwargs).check(bad_val)
            assert e2 is not None, f"越界应被拒绝: {kwargs}, {bad_val}"
            assert e2.code == "OUT_OF_RANGE", (kwargs, e2)

    def test_integer_rejects_fractional(self):
        _, err = Integer().check("2.5")
        assert err.code == "NOT_INTEGER", err

    def test_integer_accepts_integral_float_and_string(self):
        for raw in (5, 5.0, "5"):
            val, err = Integer().check(raw)
            assert err is None and val == 5 and isinstance(val, int), (raw, val, err)

    def test_integer_bounds(self):
        _, err = Integer(min=2).check(1)
        assert err.code == "OUT_OF_RANGE", err
        _, err2 = Integer(max=9).check(10)
        assert err2.code == "OUT_OF_RANGE", err2

    def test_integer_rejects_bool(self):
        _, err = Integer().check(True)
        assert err.code == "NOT_INTEGER", err

    def test_choice_signature_is_variadic(self):
        """**签名防回归**：`Choice("a", "b", aliases={...})` 必须可用。

        首版 `aliases` 走 dataclass 字段因而可位置传入，连续两处失败：
        ① `Choice("linear", {"ols": "linear"})` 把 dict 当候选值；
        ② 改 kw_only 后 `Choice("linear", "gbm")` 报参数冲突。
        正确形态是显式 `__init__(*allowed, aliases=..., case_sensitive=...)`。
        """
        ch = Choice("linear", "gbm", aliases={"ols": "linear"})
        assert ch.allowed == ("linear", "gbm")
        assert ch.aliases == {"ols": "linear"}
        assert ch.check("ols")[0] == "linear"

    def test_choice_normalizes_case_and_whitespace(self):
        ch = Choice("linear", "gbm")
        for raw in ("linear", "LINEAR", " Linear ", "GbM"):
            val, err = ch.check(raw)
            assert err is None and val in ("linear", "gbm"), (raw, val, err)

    def test_choice_rejects_unknown_and_lists_options(self):
        _, err = Choice("linear", "gbm").check("rf")
        assert err.code == "NOT_IN_CHOICES", err
        assert "linear" in err.message and "gbm" in err.message, err.message

    def test_choice_without_candidates_raises(self):
        with pytest.raises(ValueError, match="至少需要一个候选值"):
            Choice()

    def test_choice_accepts_non_string_values(self):
        """非字符串候选值（如整数）应可匹配；字符串 `"3"` **不**匹配整数 `3`。

        这也是有意行为：`Choice(2, 3)` 用于 Web 下拉（值是数字），
        而 YAML 里可能写成 `"3"` —— 类型不同即不匹配，需要接受时显式给别名。
        """
        ch = Choice(2, 3)
        assert ch.check(3)[0] == 3
        _, err = ch.check("3")
        assert err.code == "NOT_IN_CHOICES", err
        ch_alias = Choice(2, 3, aliases={"2": 2, "3": 3})
        assert ch_alias.check("3")[0] == 3

    def test_text_strip_and_non_empty(self):
        assert Text().check("  a  ")[0] == "a"
        _, err = Text(allow_empty=False).check("   ")
        assert err.code == "EMPTY_TEXT", err

    def test_text_max_len(self):
        _, err = Text(max_len=3).check("abcd")
        assert err.code == "TEXT_TOO_LONG", err

    def test_custom_validator(self):
        def fn(raw):
            return (
                (raw * 2, None) if raw != "bad" else (None, Violation("不接受 bad", "CUSTOM_BAD"))
            )

        ch = Custom(fn)
        assert ch.check(3)[0] == 6
        _, err = ch.check("bad")
        assert err.code == "CUSTOM_BAD", err


class TestNoneSemantics:
    """`None` = 未提供（与引擎既有约定一致）。"""

    def test_optional_none_uses_default(self):
        """可选字段收到 `None` → 用默认值，不报错。

        依据：引擎的 `DEFAULT_PARAMS` **有意注入 `None`**，
        Web 表单留空也会变 `None`；若把 `None` 当错误，"表单留空"会被误判。
        """
        ok, err = _spec().validate({"model": "linear", "alpha": None})
        assert err is None and ok.alpha == 0.05

    def test_optional_none_with_none_default_stays_none(self):
        ok, err = _spec().validate({"model": "linear", "usl": None})
        assert err is None and ok.usl is None

    def test_required_none_is_rejected(self):
        _, err = _spec().validate({"model": None})
        assert err.code == "E_PARAM_REQUIRED_MISSING", err

    def test_required_absent_is_rejected(self):
        _, err = _spec().validate({})
        assert err is not None and err.code == "E_PARAM_REQUIRED_MISSING"
        assert "模型" in err.message

    def test_none_is_counted_as_default_usage(self):
        """显式传 `None` **算**用了默认值 —— 最终值确实来自声明默认值。

        这条把语义钉住：`used_defaults` 记录"最终值来自默认值"的字段，
        供调用方判断用户是否表达过意图（例如 Web 表单留空 vs 填了值）。
        """
        ok, _ = _spec().validate({"model": "linear", "alpha": None})
        assert ok.alpha == 0.05
        assert "alpha" in ok.used_defaults, ok.used_defaults

    def test_absent_field_is_also_counted(self):
        """完全没传同一字段时，行为应与显式传 `None` 一致（都是"未提供"）。"""
        ok_absent, _ = _spec().validate({"model": "linear"})
        ok_none, _ = _spec().validate({"model": "linear", "alpha": None})
        assert ok_absent.alpha == ok_none.alpha == 0.05
        assert "alpha" in ok_absent.used_defaults
        assert "alpha" in ok_none.used_defaults


class TestSpecValidate:
    """`Spec.validate` 的整体行为。"""

    def test_happy_path_converts_types(self):
        ok, err = _spec().validate({"model": "linear", "usl": "10.5", "subgroup_size": "5"})
        assert err is None
        assert ok.usl == 10.5 and isinstance(ok.usl, float)
        assert ok.subgroup_size == 5 and isinstance(ok.subgroup_size, int)
        assert ok.alpha == 0.05  # 默认值

    def test_fails_fast_on_first_error(self):
        """快速失败：只返回第一个错误（前端一次改一项）。"""
        _, err = _spec().validate({"usl": "inf"})  # usl 错 + model 缺失
        assert err.field_name == "usl", "应按声明顺序先报 usl"

    def test_validate_all_collects_every_error(self):
        errors = _spec().validate_all({"usl": "inf", "alpha": "9"})
        codes = {e.code for e in errors}
        assert "E_PARAM_NOT_FINITE" in codes
        assert "E_PARAM_OUT_OF_RANGE" in codes
        assert "E_PARAM_REQUIRED_MISSING" in codes, "model 缺失也应被收集"
        assert len(errors) == 3, [e.code for e in errors]

    def test_empty_or_none_params(self):
        _, err = _spec().validate(None)
        assert err.code == "E_PARAM_REQUIRED_MISSING", err
        _, err2 = _spec().validate({})

    def test_unknown_keys_are_ignored_by_default(self):
        """未知键不影响校验（严格性由调用方决定，见 `test_unknown_attr_raises`）。"""
        ok, err = _spec().validate({"model": "linear", "not_a_param": 1})
        assert err is None
        assert "not_a_param" not in ok

    def test_cross_rule_rejects(self):
        spec = _spec().cross(
            CrossRule(
                "usl",
                lambda p: p["usl"] is None or p["lsl"] is None or p["usl"] > p["lsl"],
                "E_SPEC_INVERTED",
                "规格上下限颠倒（USL 必须大于 LSL）。",
            )
        )
        _, err = spec.validate({"model": "linear", "usl": 5, "lsl": 10})
        assert err is not None and err.code == "E_SPEC_INVERTED"
        assert "颠倒" in err.message

    def test_cross_rule_sees_converted_values(self):
        """交叉规则收到的是**已强转**的值 —— 故可直接比较数值。"""
        spec = _spec().cross(CrossRule("usl", lambda p: p["usl"] > p["lsl"], "E_INV", "颠倒"))
        # 字符串输入也应能正确比较（证明规则看到的是 float 而非 str）
        ok, err = spec.validate({"model": "linear", "usl": "10", "lsl": "5"})
        assert err is None, err

    def test_cross_rules_skipped_when_field_errors(self):
        """单字段有错时不检查交叉规则（避免误导性二次报错）。"""
        spec = _spec().cross(CrossRule("usl", lambda p: False, "E_INV", "颠倒"))
        _, err = spec.validate({"model": "linear", "usl": "inf"})
        assert err.code == "E_PARAM_NOT_FINITE", err

    def test_spec_requires_at_least_one_field(self):
        with pytest.raises(ValueError, match="至少需要一个字段"):
            Spec()


class TestValidateOrRaise:
    """`validate_or_raise()` —— 引擎函数用的抛异常入口（阶段 P4 步骤③）。

    契约：它必须与 `validate()` **判定完全一致**，只是把错误改成抛出。
    为什么需要它：引擎里每个 `return AnalysisResult(status="error")` 都是一处
    手写早退；改抛异常后由 `orchestrator` 的
    `except SmartSuiteError → build_error_result()` 统一转结果
    （见 `core/exceptions.py::ParamValidationError` 的说明）。
    """

    def test_returns_params_on_success(self):
        params = _spec().validate_or_raise({"model": "linear", "usl": "10.5"})
        assert params.usl == 10.5
        assert params.model == "linear"
        assert params.alpha == 0.05  # 默认值

    def test_raises_with_code_and_field_on_bad_value(self):
        with pytest.raises(ParamValidationError) as ei:
            _spec().validate_or_raise({"usl": "inf"})
        assert ei.value.code == "E_PARAM_NOT_FINITE", ei.value.code
        assert ei.value.field_name == "usl", ei.value.field_name
        assert "规格上限" in str(ei.value)

    def test_raises_on_missing_required(self):
        with pytest.raises(ParamValidationError) as ei:
            _spec().validate_or_raise({})
        assert ei.value.code == "E_PARAM_REQUIRED_MISSING"
        assert ei.value.field_name == "model"

    def test_raises_on_cross_rule_violation(self):
        spec = _spec().cross(CrossRule("usl", lambda p: p["usl"] > p["lsl"], "E_INV", "规格限颠倒"))
        with pytest.raises(ParamValidationError) as ei:
            spec.validate_or_raise({"model": "linear", "usl": 1.0, "lsl": 9.0})
        assert ei.value.code == "E_INV"

    def test_is_a_smartsuite_error_so_orchestrator_handles_it(self):
        """必须是 `SmartSuiteError` 子类 —— 否则编排层不会转成中文结果。

        这是"抛异常式迁移"能成立的**前提**：`orchestrator` 捕获的是
        `SmartSuiteError`，漏了这一层会变成未预期异常（提示索要数据样本，
        且日志级别不同）。
        """
        assert issubclass(ParamValidationError, SmartSuiteError)
        with pytest.raises(SmartSuiteError):
            _spec().validate_or_raise({"usl": "abc"})

    def test_agrees_with_validate_on_every_case(self):
        """对拍：`validate()` 判错的每一种输入，`validate_or_raise()` 都必须抛。"""
        spec = _spec()
        cases = [
            {},
            {"model": "x"},
            {"model": "linear", "usl": "inf"},
            {"model": "linear", "usl": "abc"},
            {"model": "linear", "alpha": "9"},
            {"model": "linear", "subgroup_size": "2.5"},
            {"model": "linear", "note": ""},
            {"model": "linear", "alpha": None},  # None → 用默认值 → 通过
        ]
        for raw in cases:
            _, err = spec.validate(raw)
            if err is None:
                assert spec.validate_or_raise(raw) is not None
            else:
                with pytest.raises(ParamValidationError) as ei:
                    spec.validate_or_raise(raw)
                # 同一输入必须给**同一个**错误码（两条路径不得漂移）
                assert ei.value.code == err.code, (raw, ei.value.code, err.code)
                assert ei.value.field_name == err.field_name, raw


class TestValidatedParams:
    """校验结果对象的访问语义。"""

    def test_attribute_access(self):
        ok, _ = _spec().validate({"model": "linear"})
        assert ok.model == "linear"
        assert isinstance(ok, ValidatedParams)

    def test_unknown_attribute_raises_not_returns_none(self):
        """未知参数名必须抛错 —— 静默返回 `None` 会让引擎走 fallback 掩盖拼写错误。"""
        ok, _ = _spec().validate({"model": "linear"})
        with pytest.raises(AttributeError, match="未在 Spec 中声明"):
            _ = ok.not_a_param

    def test_contains_and_get(self):
        ok, _ = _spec().validate({"model": "linear"})
        assert "model" in ok and "nope" not in ok
        assert ok.get("nope", 7) == 7
        assert set(ok.as_dict()) == set(_spec().field_names)


class TestIntrospection:
    """内省输出 —— 将来是五份平行字典的唯一来源，形状必须稳定。"""

    def test_defaults_excludes_required_fields(self):
        d = _spec().defaults()
        assert "model" not in d, "必填字段不应有默认值"
        assert d["alpha"] == 0.05 and d["usl"] is None

    def test_labels_covers_every_field(self):
        spec = _spec()
        labels = spec.labels()
        assert set(labels) == set(spec.field_names)
        assert labels["usl"] == "规格上限 (USL)"

    def test_hints_only_for_fields_that_have_them(self):
        hints = _spec().hints()
        assert hints.get("usl") == "USL 应大于 LSL"
        assert "lsl" not in hints, "无 hint 的字段不应出现（空字符串也不该占用键）"

    def test_required_fields(self):
        assert _spec().required_fields() == ["model"]

    def test_defaults_derivable_to_plain_dict(self):
        """`defaults()` 必须可直接当 `DEFAULT_PARAMS[task]` 用（可 JSON 序列化）。"""
        import json

        d = _spec().defaults()
        assert json.loads(json.dumps(d)) == d


class TestFieldConstruction:
    """`Req` / `Opt` 的构造。"""

    def test_req_has_no_default(self):
        """`Req` 的 `default` 是哨兵 `_MISSING`（不是 `None`），故 `required` 为真。

        `None` 是**合法的输入值**（表示"未提供"），不能同时充当"无默认值"的标记。
        """
        f = Req(label="x")
        assert f.required
        assert f.default is not None, "必填字段的 default 是哨兵，不是 None"
        assert "MISSING" in repr(f.default)

    def test_opt_with_default(self):
        f = Opt(default=5, label="x")
        assert not f.required and f.default == 5

    def test_field_without_validator_passes_through(self):
        """结构复杂的参数用 `validator=None` 透传（形态校验留给引擎）。"""
        spec = Spec(raw=Opt(label="原始结构"))
        ok, err = spec.validate({"raw": {"nested": [1, 2]}})
        assert err is None and ok.raw == {"nested": [1, 2]}


class TestErrorSurfacing:
    """错误对象的内容可用于程序判定与用户提示。"""

    def test_param_error_fields(self):
        err = ParamError(code="E_X", field_name="f", message="m")
        assert err.code == "E_X" and err.field_name == "f" and err.message == "m"
        assert "[E_X]" in str(err)

    def test_every_error_message_is_chinese(self):
        """面向工艺用户：所有错误消息必须含中文。"""
        cases = [
            {"usl": "inf"},
            {"usl": "abc"},
            {"alpha": "2"},
            {"model": "x"},
            {"model": "linear", "subgroup_size": "2.5"},
            {"model": "linear", "note": ""},
        ]
        for raw in cases:
            for e in _spec().validate_all(raw):
                assert any("\u4e00" <= ch <= "\u9fff" for ch in e.message), (
                    f"错误消息应为中文：{e.message!r}（输入 {raw}）"
                )

    def test_error_codes_follow_naming_convention(self):
        """错误码沿用 `E_<域>_<原因>` 命名（boundary-contract.md）。"""
        for raw in ({"usl": "inf"}, {"model": "x"}, {}):
            for e in _spec().validate_all(raw):
                assert e.code.startswith("E_"), e.code
                assert e.code.isupper(), e.code


class TestNumpyInputs:
    """numpy 标量输入（来自 pandas 单元格）应可接受。"""

    def test_numpy_scalar_accepted(self):
        ok, err = _spec().validate({"model": "linear", "usl": np.float64(10.5)})
        assert err is None and ok.usl == 10.5
        ok2, err2 = _spec().validate({"model": "linear", "subgroup_size": np.int64(5)})
        assert err2 is None and ok2.subgroup_size == 5

    def test_numpy_nan_rejected(self):
        _, err = _spec().validate({"model": "linear", "usl": np.nan})
        assert err.code == "E_PARAM_NOT_FINITE", err
