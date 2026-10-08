"""共享参数声明库的测试（阶段 P4 步骤③的**加速器**）。

## 为什么需要它（第二十轮的量产化判断）

第二十轮做里程碑复盘时实测：**42 个任务里只有 3 个有 `PARAM_SPEC`，剩 39 个**，
而计划总预算 40 轮 —— 按"每轮手工迁一个任务"的节奏**不可能达成目标**。

复盘同时发现可批量化的证据：`DEFAULT_PARAMS` 的 **114 个参数槽位里只有 83 个
不同参数名**，其中 `alpha` 出现在 **9** 个任务、`group_col` **8** 个、
`usl`/`lsl`/`target` 各 3 个、`method`/`random_state`/`ci_level` 各 3 个。

故把"每个任务各自重写同样字段"改为"引用共享声明"：
迁移一个含 3 个常用参数的任务，从"写 3 份声明"变为"引 3 个常量 + 写少量专有项"。

## 共享的判据（严格）

只有**标签、提示、校验器、默认值全部相同**才能共享。
参数名相同但标签/取值域不同的**不得**共享 —— 例如：
  - `alpha`：9 个任务都是 (0,1)、都叫"显著性水平 α" → 可共享；
  - `method`：`anomaly_detect` 是"异常检测方法"、`doe_design` 是"设计方法"
    → **不可**共享（语义无关）；
  - `mode`：`power_analysis` 是"所需样本量/已达功效"、`box_chart` 是箱体图布局
    → **不可**共享。

这条判据是防止"为省事而共享语义不同的字段"—— 那会重演第十七轮的选项跨任务泄漏。
"""

from __future__ import annotations


from smartsuite.core.param_spec import Choice, Finite, Integer, Spec
from smartsuite.core import param_specs_common as common


class TestAlphaField:
    """`alpha` —— 出现最多的可共享字段（9 个任务）。"""

    def test_open_unit_interval(self):
        """α 必须在 (0,1) 开区间（与既有实现一致）。"""
        for bad in (0, 1, -0.1, 1.5):
            _, err = common.ALPHA.validator.check(bad)
            assert err is not None, f"alpha={bad} 应被拒绝"
        for ok in (0.01, 0.05, 0.5, 0.99):
            val, err = common.ALPHA.validator.check(ok)
            assert err is None and val == ok, (ok, err)

    def test_default_is_point_zero_five(self):
        assert common.ALPHA.default == 0.05

    def test_label_and_hint_are_chinese(self):
        assert any("\u4e00" <= ch <= "\u9fff" for ch in common.ALPHA.label)
        assert any("\u4e00" <= ch <= "\u9fff" for ch in common.ALPHA.hint)

    def test_rejects_nan_and_inf(self):
        for bad in (float("nan"), float("inf"), "nan", "inf"):
            _, err = common.ALPHA.validator.check(bad)
            assert err is not None, f"alpha={bad!r} 应被拒绝"

    def test_usable_in_a_spec(self):
        spec = Spec(alpha=common.ALPHA)
        ok, err = spec.validate({"alpha": "0.01"})
        assert err is None and ok.alpha == 0.01

    def test_is_not_required(self):
        assert not common.ALPHA.required


class TestOtherSharedFields:
    """其余共享字段的取值域必须与引擎既有行为一致。"""

    def test_ci_level_is_open_unit(self):
        """置信水平在 (0,1)（`ci_level` 出现在 3 个任务）。"""
        _, err = common.CI_LEVEL.validator.check(0)
        assert err is not None
        assert common.CI_LEVEL.default == 0.95

    def test_group_col_is_text(self):
        """分组/分类列名是**文本**，不做数值校验。

        注意：它是"列名"，故不能要求存在性（那依赖数据 → 留给引擎）。

        默认值是 `None`（"未提供"）—— 实测 `DEFAULT_PARAMS` 里 6 个任务如此；
        `process_capability` 有意用 `""`（需区分"显式留空"与"未提供"），
        故它不引用本常量。这条差异由批量迁移的对拍用例抓出（我最初统一写了 `""`）。
        """
        val, err = common.GROUP_COL.validator.check("  温度  ")
        assert err is None and val == "温度", (val, err)
        assert common.GROUP_COL.default is None

    def test_usl_lsl_are_finite_numbers(self):
        """规格限是有限数值（拒绝 NaN/Inf）。"""
        for f in (common.USL, common.LSL):
            _, err = f.validator.check(float("inf"))
            assert err is not None
            assert f.default is None

    def test_target_is_finite_number(self):
        _, err = common.TARGET.validator.check("abc")
        assert err is not None
        assert common.TARGET.default is None

    def test_random_state_is_non_negative_integer(self):
        _, err = common.RANDOM_STATE.validator.check(-1)
        assert err is not None
        assert common.RANDOM_STATE.default == 42

    def test_side_is_not_shared_because_value_sets_differ(self):
        """`side` **不得**共享 —— 我最初按 "two-sided/one-sided" 写进本库是错的。

        核对引擎源码后发现 `spc_nonparametric` 实际取
        `two-sided / upper / lower`，而 `tolerance_interval` 的同名参数是另一套
        含义（容差区间方向）。**枚举的值集就是语义本身**，故一律逐任务声明。
        """
        names = {n for n in dir(common) if n.isupper() and not n.startswith("_")}
        assert "SIDE" not in names, "side 的值集因任务而异，不得共享"

    #: 允许出现在共享库里的**唯一**枚举字段（第三十轮加入）。
    #: 判据不是"值集是否相同"（那种语义巧合一律逐任务声明），而是
    #: **"这个名字表示的东西本身就只有两个取值"** —— 布尔开关没有任务相关的语义，
    #: 而 `mode`/`method`/`side` 这些同名参数在不同任务里含义完全不同。
    #: `BOOL_SWITCH` 的别名表（`True`/`1` → `"true"`）也是"开关"这件事本身的一部分，
    #: 不随任务变化。
    ALLOWED_ENUM_FIELDS = frozenset({"BOOL_SWITCH"})

    def test_library_has_no_enum_fields_at_all(self):
        """更强的判据：本库**不含任何枚举字段**（值集差异风险太高）。

        第三十轮加入 `BOOL_SWITCH` 后，该判据改为"除白名单外不含枚举"。
        白名单的正当性见 `ALLOWED_ENUM_FIELDS` 的注释 —— 关键是这条判据
        **没有被削弱**：往库里加任何新的枚举字段仍会失败，必须显式改白名单。
        """
        import smartsuite.core.param_specs_common as lib

        offenders = []
        for name in dir(lib):
            if not name.isupper() or name.startswith("_"):
                continue
            field = getattr(lib, name)
            validator = getattr(field, "validator", None)
            if isinstance(validator, Choice) and name not in self.ALLOWED_ENUM_FIELDS:
                offenders.append(name)
        assert not offenders, (
            f"以下共享字段是枚举：{offenders} —— 枚举一律逐任务声明（见模块文档的判据）；"
            f"若确属「本身只有两个取值」的开关，请显式加入 ALLOWED_ENUM_FIELDS 并说明理由"
        )

    def test_allowed_enum_whitelist_is_actually_used(self):
        """白名单里的名字必须真实存在且确是枚举 —— 防止白名单变成"僵尸豁免"。"""
        import smartsuite.core.param_specs_common as lib

        for name in self.ALLOWED_ENUM_FIELDS:
            assert hasattr(lib, name), f"白名单里的 {name} 在共享库中不存在（白名单已过期）"
            field = getattr(lib, name)
            assert isinstance(getattr(field, "validator", None), Choice), (
                f"{name} 已不是枚举字段，应从白名单移除"
            )


class TestSharingDiscipline:
    """防止"为省事而共享语义不同的字段"。"""

    def test_method_and_mode_are_not_shared(self):
        """`method` / `mode` **不得**出现在共享库里。

        它们在多个任务里语义完全不同（`method`：异常检测/设计/相关；
        `mode`：功效分析模式/箱体图布局）。一旦共享，就会重演第十七轮的
        "选项跨任务泄漏" —— 用户被提供引擎不认的值。
        """
        names = {n for n in dir(common) if n.isupper() and not n.startswith("_")}
        assert "METHOD" not in names, "method 语义因任务而异，不得共享"
        assert "MODE" not in names, "mode 语义因任务而异，不得共享"

    def test_every_shared_field_has_label_and_documented_scope(self):
        """每个共享字段都应有中文标签，且模块文档说明其适用任务。"""
        src = common.__doc__ or ""
        for name in ("ALPHA", "GROUP_COL", "USL", "LSL", "TARGET", "CI_LEVEL"):
            field = getattr(common, name)
            assert field.label, f"{name} 缺 label"
            # 文档里应能查到该字段的适用说明（防止加了字段不写清适用范围）
            assert name.lower().replace("_", "") in src.lower().replace("_", "").replace("`", ""), (
                f"模块文档未说明 {name} 的适用范围"
            )

    def test_shared_fields_are_independent_objects(self):
        """共享常量被多个 Spec 引用时不得互相影响（`Field` 是 frozen dataclass）。"""
        a = Spec(alpha=common.ALPHA)
        b = Spec(alpha=common.ALPHA)
        ok_a, _ = a.validate({"alpha": 0.01})
        ok_b, _ = b.validate({"alpha": 0.9})
        assert ok_a.alpha == 0.01 and ok_b.alpha == 0.9
        assert common.ALPHA.default == 0.05, "共享常量本身不得被改动"

    def test_integer_and_finite_constants_are_the_right_types(self):
        """类型正确性（防止把 `Finite` 与 `Integer` 混用）。

        本库不含 `Choice`（枚举一律逐任务声明），故不在此断言枚举类型。
        """
        from smartsuite.core.param_spec import Text

        assert isinstance(common.RANDOM_STATE.validator, Integer)
        assert isinstance(common.ALPHA.validator, Finite)
        assert isinstance(common.GROUP_COL.validator, Text)
        assert isinstance(common.CI_LEVEL.validator, Finite)
        assert isinstance(common.USL.validator, Finite)
