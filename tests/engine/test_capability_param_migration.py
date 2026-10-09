"""`process_capability` 参数校验的迁移对拍（阶段 P4 步骤②）。

契约：docs/governance/improvement-plan.md §六（双轨期"逐任务迁移，两套并存"）

## 本文件的双重角色

1. **迁移前**：锁定手写校验的**确切行为**（拒绝哪些输入、给什么文案）——
   这是迁移的验收基准。任何一条变了都说明迁移改变了行为。
2. **迁移后**：同一批用例必须仍然全绿。若某条行为**有意改变**（如错误码规范化），
   必须在此文件里显式改写并注明原因，不得默默改掉。

## 覆盖范围

`process_capability` 的参数校验分两类：

- **纯参数校验**（usl / lsl / target / transform）→ 迁移到 `Spec`；
- **依赖数据的校验**（样本量 ≥3、非恒定列、子组参数）→ **留在引擎**，
  因为 `Spec` 按设计不做依赖数据的检查（那属 `_guard.py` 的 B0–B3 职责）。

故本文件的用例按这两类分开，前者是迁移对象，后者是"必须保持不变"的基线。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.core.exceptions import ParamValidationError
from smartsuite.engine.capability import process_capability_analysis
from smartsuite.services.orchestrator import orchestrate


def _via_orchestrator(df: pd.DataFrame | None = None, **params):
    """经**编排层**执行 —— 对应 Web/CLI 用户实际看到的路径。

    审查 2026-09-24（P4 步骤③）：参数校验失败在引擎层**抛异常**
    （`ParamValidationError`），由 `orchestrator` 的
    `except SmartSuiteError → build_error_result()` 转成 `status="error"`。
    故本文件分两层验证：
      - 引擎层：`pytest.raises(ParamValidationError)`；
      - 编排层：`status == "error"` + 精确中文文案（用户可见）。
    """
    return orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=_frame() if df is None else df,
            target_col="y",
            params=params,
        )
    )


def _frame(n: int = 50, seed: int = 0) -> pd.DataFrame:
    return pd.DataFrame({"y": np.random.default_rng(seed).normal(50, 1.0, n)})


def _run(df: pd.DataFrame | None = None, **params):
    return process_capability_analysis(
        AnalysisRequest(
            task="process_capability",
            data=_frame() if df is None else df,
            target_col="y",
            params=params,
        )
    )


class TestPureParamValidationBaseline:
    """**纯参数校验**——迁移到 `Spec` 的对象。这些确切文案是迁移的验收基准。"""

    def test_valid_specs_still_work(self):
        r = _run(usl=53.0, lsl=47.0, target=50.0)
        assert r.status == "ok", r.messages
        assert r.metadata["cp"] > 0

    def test_numeric_strings_accepted(self):
        """Web/CLI 会传字符串数字 —— 必须被接受（迁移后同样）。"""
        r = _run(usl="53", lsl="47", target="50")
        assert r.status == "ok", r.messages

    @pytest.mark.parametrize("bad", ["abc", "1,5", "x1"])
    def test_non_numeric_spec_is_rejected(self, bad):
        """非数值规格限必须拒绝（不得静默当 None —— 那会掩盖用户输入错误）。"""
        r = _via_orchestrator(usl=bad, lsl=47.0)
        assert r.status == "error", f"usl={bad!r} 应被拒绝，实际 {r.status}"
        assert r.messages, "拒绝时必须给出消息"

    def test_empty_string_means_not_provided_at_orchestrator(self):
        """**两层语义差异（有意，非缺陷）**：空串在编排层被归一为"未提供"。

        依据 `orchestrator._normalize_empty_params`（审查 2026-09-19 E11）：
        `k in defaults` 时用默认值替换空串 —— 这正是 Web 表单"清空输入框"的语义，
        清空 `usl` 后应当**不给规格限**（只算描述统计），而不是报错。

        故同一输入在两层行为不同，且两者都对：
          - 编排层（Web/CLI 用户路径）：`""` → `None` → 不报错；
          - 引擎层（直接调用）：`""` → `NOT_NUMERIC` → 抛异常。

        本用例与下一条分别钉住两层，避免日后有人"修"掉其中一层。
        """
        r = _via_orchestrator(usl="", lsl=47.0)
        assert r.status == "ok", f"空串应被当作未提供：{r.messages}"
        assert r.metadata["cp"] is None, "未给 usl+lsl 双侧时不应算出 Cp"

    def test_empty_string_is_rejected_by_engine_directly(self):
        """引擎层直接调用时空串是**非法输入**（`float('')` 失败），必须抛异常。

        与上一条互为对照：引擎不做表单语义归一，那属编排层职责。
        """
        with pytest.raises(ParamValidationError) as ei:
            process_capability_analysis(
                AnalysisRequest(
                    task="process_capability",
                    data=_frame(),
                    target_col="y",
                    params={"usl": "", "lsl": 47.0},
                )
            )
        assert ei.value.code == "E_PARAM_NOT_NUMERIC", ei.value.code
        assert ei.value.field_name == "usl"

    @pytest.mark.parametrize("field", ["usl", "lsl", "target"])
    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), "inf", "nan"])
    def test_non_finite_spec_is_rejected(self, field, bad):
        """NaN/Inf 必须显式拒绝（sentinel-contract L1）。

        原症状（审查 2026-09-05 C1）：`float("inf")` 不抛异常，
        故 `try: float(x)` 会静默放过 → `cp=inf` 静默输出。
        """
        kwargs = {"usl": 53.0, "lsl": 47.0, field: bad}
        r = _via_orchestrator(**kwargs)
        assert r.status == "error", f"{field}={bad!r} 应被拒绝，实际 {r.status}"

    def test_usl_le_lsl_is_rejected(self):
        """交叉规则：USL ≤ LSL 必须拒绝（否则 Cp 为负或零，无物理意义）。"""
        for usl, lsl in ((47.0, 53.0), (50.0, 50.0)):
            r = _via_orchestrator(usl=usl, lsl=lsl)
            assert r.status == "error", f"USL={usl} LSL={lsl} 应被拒绝"
            assert any("规格限无效" in m for m in r.messages), r.messages

    def test_missing_specs_are_allowed(self):
        """不给规格限是合法的（只算描述统计），不得报错。"""
        r = _run()
        assert r.status == "ok", r.messages
        assert r.metadata["cp"] is None and r.metadata["cpk"] is None

    def test_only_one_sided_spec_is_allowed(self):
        """单侧规格限合法（只算对应的 Cpk/Ppk）。"""
        r_up = _run(usl=53.0)
        assert r_up.status == "ok" and r_up.metadata["cpk"] is not None
        assert r_up.metadata["cp"] is None, "单侧不应给出 Cp"
        r_lo = _run(lsl=47.0)
        assert r_lo.status == "ok" and r_lo.metadata["cpk"] is not None


class TestDataDependentValidationStays:
    """**依赖数据的校验**必须留在引擎（`Spec` 按设计不做这类检查）。"""

    def test_too_few_points_rejected(self):
        r = _run(_frame(n=2))
        assert r.status == "error"
        assert any("有效数据不足" in m for m in r.messages), r.messages

    def test_constant_column_rejected(self):
        r = _run(pd.DataFrame({"y": [1.0] * 20}))
        assert r.status == "error"
        assert any("常量列" in m for m in r.messages), r.messages

    def test_infinite_values_are_dropped_with_note(self):
        """±Inf 混入时应剔除并披露（不报错）—— 与"参数为 Inf"是两件事。"""
        vals = list(np.random.default_rng(1).normal(50, 1.0, 30)) + [np.inf, -np.inf]
        r = _run(pd.DataFrame({"y": vals}), usl=53.0, lsl=47.0)
        assert r.status == "ok", r.messages
        assert any("非有限" in m or "Inf" in m for m in r.messages), r.messages


class TestSubgroupParamsBaseline:
    """子组参数的校验（依赖数据 → 留在引擎，但行为必须不变）。"""

    def test_both_subgroup_params_rejected_as_ambiguous(self):
        r = _run(subgroup_col="g", subgroup_size=5, **{"usl": 53.0, "lsl": 47.0})
        assert r.status == "error"
        assert any("二选一" in m for m in r.messages), r.messages

    def test_missing_subgroup_col_rejected(self):
        df = _frame()
        df["g"] = "A"
        r = _run(df, subgroup_col="不存在", usl=53.0, lsl=47.0)
        assert r.status == "error"
        assert any("不存在" in m for m in r.messages), r.messages

    def test_subgroup_size_too_large_rejected(self):
        r = _run(subgroup_size=1000, usl=53.0, lsl=47.0)
        assert r.status == "error"
        assert any("子组" in m for m in r.messages), r.messages

    def test_single_group_rejected(self):
        df = _frame()
        df["g"] = "ONLY"
        r = _run(df, subgroup_col="g", usl=53.0, lsl=47.0)
        assert r.status == "error"


class TestMessageQualityBaseline:
    """文案质量要求（迁移不得让文案变差）。"""

    @pytest.mark.parametrize(
        "params",
        [
            {"usl": "abc", "lsl": 47.0},
            {"usl": float("inf"), "lsl": 47.0},
            {"usl": 47.0, "lsl": 53.0},
            {"lsl": "xyz"},
            {"target": "oop"},
        ],
    )
    def test_every_rejection_message_is_chinese_and_actionable(self, params):
        """拒绝文案必须：① 含中文；② 指明是哪个参数；③ 不含 traceback/内部路径。"""
        r = _via_orchestrator(**params)
        assert r.status == "error", params
        for msg in r.messages:
            assert any("\u4e00" <= ch <= "\u9fff" for ch in msg), f"非中文文案: {msg!r}"
            for leaked in ("Traceback", "site-packages", "smartsuite/", 'File "'):
                assert leaked not in msg, f"文案泄漏内部细节 {leaked!r}: {msg!r}"

    def test_spec_error_names_the_offending_parameter(self):
        """文案必须能让用户定位到具体参数（含参数名或中文标签）。"""
        r = _via_orchestrator(usl="abc", lsl=47.0)
        joined = " ".join(r.messages)
        assert ("USL" in joined) or ("规格上限" in joined), joined


class TestSpecObjectContract:
    """迁移目标：`Spec` 对象本身（迁移后引擎必须用它）。"""

    def test_spec_exists_and_declares_expected_fields(self):
        """`process_capability` 的参数契约应声明这几个字段。

        这是迁移的**结构验收**：字段集合一旦确定，前端 `TASK_PARAMS`
        与文档参数段都可从它派生。
        """
        from smartsuite.engine.capability import PARAM_SPEC

        assert set(PARAM_SPEC.field_names) == {
            "usl",
            "lsl",
            "target",
            "transform",
            "subgroup_col",
            "subgroup_size",
        }, PARAM_SPEC.field_names

    def test_spec_defaults_match_engine_expectations(self):
        """`Spec.defaults()` 必须与引擎实际接受的缺省一致。"""
        from smartsuite.engine.capability import PARAM_SPEC

        d = PARAM_SPEC.defaults()
        assert d["usl"] is None and d["lsl"] is None and d["target"] is None
        # 审查 2026-10-09 P2-8：`transform` 的缺省由 `None` 改为 `""`（「不做变换」）。
        # 原因：面板把它渲染为 `<select>`，`None` 匹配不上任何 `selected` → 浏览器
        # 自动选第一个选项；若第一个选项是 boxcox，Web 用户就被**强制开启**变换。
        # 故 Choice 补了空值选项且默认取该空值。引擎判定仍是 `transform == "boxcox"`，
        # 故 `""` 与 `None` 行为逐字等价（实测 cp 与 boxcox_lambda 完全相同）。
        assert d["transform"] in ("", None)
        assert d["subgroup_col"] in (None, "")
        assert d["subgroup_size"] is None

    def test_spec_has_no_required_fields(self):
        """过程能力的参数**全部可选**（不给规格限也能算描述统计）。"""
        from smartsuite.engine.capability import PARAM_SPEC

        assert PARAM_SPEC.required_fields() == []

    def test_spec_labels_are_chinese(self):
        from smartsuite.engine.capability import PARAM_SPEC

        for name, label in PARAM_SPEC.labels().items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), f"{name} 标签非中文: {label}"

    def test_spec_rejects_bad_usl_with_param_error(self):
        """`Spec.validate` 对非法 usl 必须给出 `ParamError`（含码与中文消息）。"""
        from smartsuite.engine.capability import PARAM_SPEC

        params, err = PARAM_SPEC.validate({"usl": "abc"})
        assert params is None and err is not None
        assert err.code.startswith("E_")
        assert err.field_name == "usl"
        assert "USL" in err.message or "规格上限" in err.message

    def test_spec_enforces_usl_gt_lsl_cross_rule(self):
        from smartsuite.engine.capability import PARAM_SPEC

        params, err = PARAM_SPEC.validate({"usl": 47.0, "lsl": 53.0})
        assert params is None and err is not None
        assert "规格限无效" in err.message, err.message

    def test_spec_accepts_valid_input_and_converts(self):
        from smartsuite.engine.capability import PARAM_SPEC

        params, err = PARAM_SPEC.validate({"usl": "53", "lsl": "47", "subgroup_size": "5"})
        assert err is None, err
        assert params.usl == 53.0 and isinstance(params.usl, float)
        assert params.lsl == 47.0
        assert params.subgroup_size == 5 and isinstance(params.subgroup_size, int)

    def test_spec_agrees_with_engine_on_every_baseline_case(self):
        """**对拍**：对同一批输入，`Spec` 的判定与引擎的判定必须一致。

        这是双轨期最关键的一条 —— 若两者对某输入给出不同结论，
        迁移就会改变行为。用例覆盖上面所有基线情形。
        """
        from smartsuite.engine.capability import PARAM_SPEC

        spec_inputs = [
            {},  # 全缺省 → 双方都应通过
            {"usl": 53.0, "lsl": 47.0},  # 合法
            {"usl": "53", "lsl": "47"},  # 字符串合法
            {"usl": 53.0},  # 单侧合法
            {"lsl": 47.0},  # 单侧合法
            {"usl": "abc", "lsl": 47.0},  # 非法 → 双方都应拒绝
            {"usl": float("inf"), "lsl": 47.0},  # 非有限 → 拒绝
            {"usl": 53.0, "lsl": float("nan")},  # 非有限 → 拒绝
            {"target": "oop"},  # 非法 → 拒绝
            {"usl": 47.0, "lsl": 53.0},  # 交叉规则 → 拒绝
            {"usl": 50.0, "lsl": 50.0},  # 交叉规则 → 拒绝
        ]
        for raw in spec_inputs:
            params, err = PARAM_SPEC.validate(raw)
            spec_ok = err is None

            # 引擎判定：只喂参数（数据固定合法），故 status 只反映参数校验
            engine_ok = _via_orchestrator(**raw).status == "ok"

            assert spec_ok == engine_ok, (
                f"对输入 {raw} 判定不一致：Spec={'通过' if spec_ok else err.code} "
                f"引擎={'ok' if engine_ok else 'error'}（{_via_orchestrator(**raw).messages}）"
            )
