"""`spc_attribute` 参数校验的迁移对拍（阶段 P4 步骤③）。

契约：docs/governance/improvement-plan.md §六

## 迁移范围

`spc_attribute` 的参数只有 `chart_type` 是**纯参数校验**（可进 `Spec`）；
`group_col` / `n_col` / `subgroup_col` 都需引用实际列，属**依赖数据**的检查，
留在引擎（走 `_guard.py`）。

## 迁移中发现的**两处行为缺陷**（本轮修复，故"迁移前快照"在此处不同于 engine）

1. **`None` 不回落默认值**：原来是 `req.params.get("chart_type", "p")` ——
   键存在但值为 `None` 时返回 `None`（默认值不生效），随后报
   "不支持的图表类型: None"。这违反引擎的既有约定（`None` = 未提供，
   见 `core/param_spec.py` 的说明），且**归因误导**（用户并没有"选了 None"）。
   `task_spec` 的默认值是 `"p"`，故正常 Web/CLI 路径不触发；
   但直接调用（Python API / 测试）会踩到。
2. **大小写与空白不归一**：`"P"` / `"p "` 被拒。其他 `Choice` 校验器已支持
   归一化，Web 表单与 YAML 模板里写 `"P"` 很自然，不该因大小写报错。

两处都是**有意改变**，故在此文件显式记录，而非默默改掉。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.spc_charts.attribute import attribute_chart
from smartsuite.services.orchestrator import orchestrate


def _via_orchestrator(df: pd.DataFrame | None = None, **params):
    """经**编排层**执行 —— 对应 Web/CLI 用户实际看到的路径。

    参数校验失败在引擎层抛 `ParamValidationError`，由编排层转成
    `status="error"` + 精确中文文案。本文件分两层验证。
    """
    base = {"group_col": "g"}
    base.update(params)
    return orchestrate(
        AnalysisRequest(
            task="spc_attribute",
            data=_frame() if df is None else df,
            target_col="defects",
            feature_cols=["g"],
            params=base,
        )
    )


def _frame(n_groups: int = 12, per_group: int = 4, kind: str = "count") -> pd.DataFrame:
    """构造满足"至少 5 组"的计数型数据。

    `kind="fraction"` 时目标列为 0/1（供 p/np 图使用）。
    """
    rng = np.random.default_rng(0)
    rows = []
    for g in range(n_groups):
        for _ in range(per_group):
            val = int(rng.integers(0, 2)) if kind == "fraction" else int(rng.integers(0, 4))
            rows.append({"g": f"G{g:02d}", "defects": val, "n": 100})
    return pd.DataFrame(rows)


def _run(df: pd.DataFrame | None = None, **params):
    base = {"group_col": "g"}
    base.update(params)
    return attribute_chart(
        AnalysisRequest(
            task="spc_attribute",
            data=_frame() if df is None else df,
            target_col="defects",
            feature_cols=["g"],
            params=base,
        )
    )


class TestChartTypeAccepts:
    """四种合法类型必须可用，且 `chart_type` 反映到 metadata。"""

    @pytest.mark.parametrize(
        "chart_type,col_kind",
        [("p", "fraction"), ("np", "fraction"), ("c", "count"), ("u", "count")],
    )
    def test_each_type_runs(self, chart_type, col_kind):
        r = _run(_frame(kind=col_kind), chart_type=chart_type, n_col="n")
        assert r.status == "ok", f"{chart_type} 应可用：{r.messages}"
        assert r.metadata["chart_type"] == chart_type

    def test_absent_chart_type_defaults_to_p(self):
        """不给 `chart_type` 时默认 p 图（原行为保持）。"""
        r = _run(_frame(kind="fraction"))
        assert r.status == "ok", r.messages
        assert r.metadata["chart_type"] == "p"


class TestChartTypeNoneFallsBackToDefault:
    """**行为修复 ①**：`None` = 未提供 → 用默认值（与引擎既有约定一致）。"""

    def test_none_chart_type_uses_default_not_error(self):
        """`chart_type=None` 必须走默认 p 图，而不是报"不支持的图表类型: None"。

        迁移前：`params.get("chart_type", "p")` 在键存在且为 None 时返回 None，
        默认值不生效 → 报错。这条断言把修复钉住。
        """
        r = _run(_frame(kind="fraction"), chart_type=None)
        assert r.status == "ok", f"None 应回落默认 p 图，实际：{r.messages}"
        assert r.metadata["chart_type"] == "p"

    def test_none_and_absent_are_equivalent(self):
        """显式 `None` 与完全不传，行为必须一致（引擎的 `None` 语义）。"""
        r_none = _run(_frame(kind="fraction"), chart_type=None)
        r_absent = _run(_frame(kind="fraction"))
        assert r_none.status == r_absent.status == "ok"
        assert r_none.metadata["chart_type"] == r_absent.metadata["chart_type"] == "p"
        assert r_none.metadata["cl"] == pytest.approx(r_absent.metadata["cl"], rel=1e-12)


class TestChartTypeNormalization:
    """**行为修复 ②**：大小写与首尾空白归一（与 `Choice` 校验器一致）。"""

    @pytest.mark.parametrize("raw", ["p", "P", " p ", "p\n"])
    def test_lowercase_p_variants(self, raw):
        r = _run(_frame(kind="fraction"), chart_type=raw)
        assert r.status == "ok", f"{raw!r} 应被归一为 p 图：{r.messages}"
        assert r.metadata["chart_type"] == "p"

    @pytest.mark.parametrize("raw", ["C", " c ", "U", "NP"])
    def test_other_variants(self, raw):
        r = _run(_frame(), chart_type=raw, n_col="n")
        assert r.status == "ok", f"{raw!r} 应被归一：{r.messages}"
        assert r.metadata["chart_type"] == raw.strip().lower()


class TestChartTypeRejects:
    """非法取值必须明确拒绝，且提示列出合法选项。"""

    @pytest.mark.parametrize("bad", ["x", "xbar", "pp", "p-chart", "1", "%%"])
    def test_unknown_type_rejected_with_options(self, bad):
        r = _via_orchestrator(chart_type=bad)
        assert r.status == "error", f"{bad!r} 应被拒绝"
        msg = " ".join(r.messages)
        # 提示应指明是哪个字段（`Spec` 用**中文标签**，比参数名更友好）
        assert "控制图类型" in msg or "chart_type" in msg, msg
        for opt in ("p", "np", "c", "u"):
            assert opt in msg, f"提示应列出合法选项 {opt!r}：{msg}"

    @pytest.mark.parametrize("bad", [123, 1.5, ["p"], {"a": 1}])
    def test_non_string_type_rejected(self, bad):
        r = _via_orchestrator(chart_type=bad)
        assert r.status == "error", f"{bad!r} 应被拒绝"


class TestParamSpecContract:
    """迁移目标：`PARAM_SPEC` 对象及其与引擎的一致性。"""

    def test_spec_declares_expected_fields(self):
        """`subgroup_col` 已于 2026-10-09（审查 P2-8）删除 —— 它是**死声明**。

        `attribute_chart` 全文不读该键（实测传一个不存在的列名，结果与完全不传
        逐字相同）。留着它会让人以为"面板能设"，补进 `default_params` 更会造出
        一个假参数，故按"Spec 只声明引擎真的会读的字段"原则删除。
        """
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        assert set(PARAM_SPEC.field_names) == {
            "chart_type",
            "group_col",
            "n_col",
            "filter_groups",
        }, PARAM_SPEC.field_names

    def test_spec_defaults_chart_type_to_p(self):
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        assert PARAM_SPEC.defaults()["chart_type"] == "p"

    def test_spec_has_no_required_fields(self):
        """计数型控制图的参数全可选（`chart_type` 有默认值）。"""
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        assert PARAM_SPEC.required_fields() == []

    def test_spec_labels_are_chinese(self):
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        for name, label in PARAM_SPEC.labels().items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), f"{name} 标签非中文: {label}"

    def test_spec_normalizes_like_engine(self):
        """对拍：`Spec` 对大小写/空白的归一结果必须与引擎一致。"""
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        for raw in ("p", "P", " p ", "np", "NP", "c", "u"):
            params, err = PARAM_SPEC.validate({"chart_type": raw})
            assert err is None, (raw, err)
            engine_type = _run(
                _frame(kind="fraction" if raw.strip().lower() in ("p", "np") else "count"),
                chart_type=raw,
                n_col="n",
            ).metadata.get("chart_type")
            assert params.chart_type == engine_type, (raw, params.chart_type, engine_type)

    def test_spec_agrees_with_engine_on_rejection(self):
        """对拍：非法取值上 `Spec` 与引擎都必须拒绝。"""
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        for raw in ("x", "xbar", "", 123):
            _, err = PARAM_SPEC.validate({"chart_type": raw})
            engine_status = _via_orchestrator(chart_type=raw).status
            assert (err is not None) == (engine_status == "error"), (
                f"{raw!r}: Spec={'拒绝' if err else '通过'} 引擎={engine_status}"
            )

    def test_spec_treats_none_as_absent(self):
        """`Spec` 对 `None` 用默认值（与修复后的引擎一致）。"""
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        params, err = PARAM_SPEC.validate({"chart_type": None})
        assert err is None
        assert params.chart_type == "p"
        assert "chart_type" in params.used_defaults


class TestDataDependentValidationStays:
    """依赖数据的校验留在引擎 —— 行为不得因迁移而改变。"""

    def test_negative_aggregate_count_rejected(self):
        """**组内聚合为负**时必须拒绝（负值会使 sqrt 内为负 → NaN 控制限静默污染）。

        ⚠️ 注意语义：检查的是 `agg["count"]`（组内**求和**），不是单行值。
        c 图的 CL 用 `sum(count)/sum(size)`（均值型），单行 −1 会被平均掉 ——
        这是常规做法，不是缺口（本文件首版误把它当成缺口，已纠正）。
        故本用例构造"整组求和为负"的数据。
        """
        df = _frame(n_groups=12, per_group=4)
        # 让第一组（4 行）全部为负 → 该组 sum(count) < 0
        df.loc[df.index[:4], "defects"] = -3
        r = _run(df, chart_type="c")
        assert r.status == "error", f"组内求和为负应被拒绝，实际 {r.status}"
        assert any("负" in m for m in r.messages), r.messages

    def test_single_negative_row_is_averaged_not_rejected(self):
        """对照：单行负值在均值型口径下被平均掉，**不应**报错（钉住正确语义）。"""
        df = _frame(n_groups=12, per_group=4)
        df.loc[0, "defects"] = -1
        r = _run(df, chart_type="c")
        assert r.status == "ok", f"单行负值不应导致拒绝：{r.messages}"

    def test_missing_n_col_is_rejected_not_silently_ignored(self):
        """**本轮发现的行为缺陷（迁移外，但同模块，一并修）**。

        原实现是 `if n_col and n_col in data.columns:` —— 用户显式给了
        `n_col` 但列名打错时，条件为假，引擎**静默回落到 `size`（行数）**，
        控制限随之算错且没有任何提示。这违反 boundary-contract 的
        "禁止静默降级"：用户以为在按实际检验数计算，实际用的是行数。

        本用例要求：显式指定的 `n_col` 不存在时必须**明确拒绝**。
        """
        r = _run(_frame(), chart_type="c", n_col="不存在的列")
        assert r.status == "error", "引用不存在的 n_col 应报错，而非静默用行数代替"
        assert any("n_col" in m or "样本量" in m for m in r.messages), r.messages

    def test_absent_n_col_still_allowed(self):
        """不给 `n_col` 仍然合法（用行数作样本量是文档化的既有行为）。"""
        r = _run(_frame(), chart_type="c")
        assert r.status == "ok", r.messages

    def test_p_chart_requires_fraction_data(self):
        """p 图的数据必须是 0/1 比例；给计数值应拒绝（原行为的硬约束）。"""
        r = _run(_frame(kind="count"), chart_type="p")
        assert r.status == "error"
        assert any("0/1" in m or "不良率" in m for m in r.messages), r.messages

    def test_unequal_sizes_rejected_for_np_and_c(self):
        """np/c 图要求等样本量（P2-6 的修复，必须保持）。"""
        df = _frame(kind="fraction")
        df.loc[df.index[:6], "n"] = 50
        r = _run(df, chart_type="np", n_col="n")
        assert r.status == "error"
        assert any("样本量" in m or "不等" in m for m in r.messages), r.messages

    def test_too_few_groups_rejected(self):
        r = _run(_frame(n_groups=2), chart_type="c")
        assert r.status == "error"
        assert any("分组" in m for m in r.messages), r.messages
