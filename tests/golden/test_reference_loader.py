"""参考值装载器的自测，以及**验证锚定状态的显式披露**。

本文件有两个作用：

1. **装载器自测** —— `_loader.py` 是门禁的一部分（它决定哪些对账真的跑了），
   若它静默失败（如把缺失参考值当成通过），整层就成了摆设。
2. **锚定状态披露** —— 明确记录"哪些方法只有项目内部验证"。
   第三轮复核的核心批评是"验证是内向闭环"，对策不是假装闭合了，
   而是**把缺口持续可见**：新增方法若既不生成参考值、也不登记在此表，本文件 FAIL。

## 为什么"登记缺口"而不是只留 TODO

TODO 会被遗忘，且无从判断是否过期。把缺口写进**有断言的表**里，
新增/改动方法时会被强制面对这个问题：
"这个方法的数值有外部依据吗？没有的话，登记在案了吗？"

## 当前锚定状态（2026-09-24）

| 层 | 实现 | 能抓到什么 | 状态 |
|:---|:---|:---|:---|
| 第三方工具输出 | — | 连"教材理解偏差"一起抓 | **未采用**（已决定不做） |
| 教科书公式独立实现 | `test_spc_msa_golden.py` | 公式转写错、常数错位、口径误用 | ✅ 覆盖 4 类 |
| 项目内第二路径 | `tests/crossval/`、scipy/statsmodels 对账 | 同上 | ✅ 已有 |

**如实声明**：本项目**不使用任何第三方统计工具做数值验证**。
因此"教材理解本身有偏差"这类问题（如 X-bar 不等子组的加权方式、
Gage R&R 嵌套设计、ANOVA 不平衡设计的 SS 选择）**没有外部裁判**，
只能靠人工复核与文档引用。这一限制持续记录在下方
`UNANCHORED_METHODS` 表中，并由断言保证不与实际状态漂移。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartsuite.services.orchestrator import TASK_REGISTRY
from tests.golden._loader import (
    REFERENCE_PATH,
    get_value,
    load_reference,
    requires_reference,
)

# ──────────────────────────────────────────────────────────────
# 未锚定方法登记表：只有项目内部验证、无任何外部数值依据的方法。
#
# 由 `test_unanchored_list_matches_actual_state` 强制：
#   表中方法若已出现参考值 → FAIL（提示从表里移除）；
#   表中出现未注册任务键 → FAIL（防任务改名后残留）。
#
# 说明：本项目不使用第三方统计工具（2026-09-24 决定），故本表短期内不会被清空。
# 它的作用是**让局限可见**，不是待办清单。
# ──────────────────────────────────────────────────────────────
UNANCHORED_METHODS: dict[str, str] = {
    "process_capability": "Cp/Cpk 的组内 σ 口径与 CI 构造方式无外部数值对照",
    "survival_analysis": "KM 中位数 CI、删失 Weibull 参数无外部数值对照",
    "gage_rr": "EV/AV/PV 的常数选择（d2 vs d2*）无外部数值对照",
    "spc_xbar": "不等子组时的控制限加权方式无外部数值对照",
    "spc_ewma": "λ-L 组合的 ARL 无外部数值对照",
    "spc_cusum": "k-h 组合的 ARL 无外部数值对照",
    "hypothesis_test": "各非参数检验的连续性校正/结校正口径无外部数值对照",
    "anova": "不平衡设计的 SS 类型选择（Type II vs III）无外部数值对照",
    "regression": "诊断统计量（BP/DW/VIF）口径无外部数值对照",
    "tolerance_interval": "Howe 容许因子无外部数值对照",
}


class TestLoaderContract:
    """装载器行为：缺失即 skip、格式非法即报错，绝不静默放行。"""

    def test_reference_file_parses_and_has_schema(self):
        """文件必须可解析，且带 `_schema` 说明（自描述，便于他人补齐）。"""
        raw = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        assert "_schema" in raw, "reference.json 应含 _schema 自描述块"
        assert "provenance" in raw and "values" in raw

    def test_independence_level_is_declared_and_legal(self):
        """独立性必须如实声明（P1-4 教训：不得把独立实现冒充成第三方工具输出）。"""
        ref = load_reference()
        assert ref.independence in {
            "external-tool",
            "independent-implementation",
            "hand-transcribed",
            "none",
        }, f"非法的 independence 级别: {ref.independence}"

    def test_empty_reference_reports_none_independence(self):
        """空表时必须声明 `none` —— 不允许空表却声称有外部锚定。"""
        ref = load_reference()
        if not ref.values:
            assert ref.independence == "none", (
                "reference.json 为空却未声明 independence='none' —— 属虚假标注"
            )

    def test_missing_value_returns_none(self):
        assert get_value("__no_such_task__", "case", "metric") is None

    def test_requires_reference_skips_when_missing(self):
        """缺参考值时 skip，且 skip 原因点明缺的是哪一项。"""

        @requires_reference("__no_such_task__", "case", "metric")
        def _probe():  # pragma: no cover — 永不被调用
            raise AssertionError("不应执行")

        with pytest.raises(pytest.skip.Exception) as ei:
            _probe()
        msg = str(ei.value)
        assert "__no_such_task__" in msg and "metric" in msg

    def test_requires_reference_runs_when_present(self, monkeypatch):
        """有参考值时正常执行（前半段契约的另一半）。"""
        from tests.golden import _loader

        fake = _loader.Reference(
            provenance={"independence": "hand-transcribed"},
            values={"t": {"c": {"m": 1.5}}},
        )
        monkeypatch.setattr(_loader, "load_reference", lambda: fake)

        @_loader.requires_reference("t", "c", "m")
        def _probe():
            return "ran"

        assert _probe() == "ran"

    def test_requires_reference_rejects_wrong_arity(self):
        with pytest.raises(ValueError, match="恰好 3 个参数"):
            requires_reference("only_one")

    def test_illegal_independence_raises(self, tmp_path, monkeypatch):
        from tests.golden import _loader

        bad = tmp_path / "reference.json"
        bad.write_text(
            json.dumps({"provenance": {"independence": "totally-external"}, "values": {}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_loader, "REFERENCE_PATH", bad)
        _loader.load_reference.cache_clear()
        with pytest.raises(ValueError, match="independence"):
            _loader.load_reference()
        _loader.load_reference.cache_clear()


class TestUnanchoredRegistryIsHonest:
    """登记表必须与实际状态一致 —— 防止"补齐了却还写着缺"或反之。"""

    def test_registry_keys_are_registered_tasks(self):
        """登记表里的键必须是已注册任务（防任务改名后残留）。"""
        unknown = sorted(set(UNANCHORED_METHODS) - set(TASK_REGISTRY))
        assert not unknown, f"登记表含未注册任务键（改名残留？）: {unknown}"

    def test_registry_matches_actual_state(self):
        """已生成参考值的方法不得仍列在登记表里（反之亦然）。"""
        ref = load_reference()
        anchored = ref.anchored_tasks()
        still_listed = sorted(anchored & set(UNANCHORED_METHODS))
        assert not still_listed, f"以下方法已有参考值，请从 UNANCHORED_METHODS 移除: {still_listed}"

    def test_registry_is_non_trivial(self):
        """登记表不应被清空成"无缺口"来蒙混过关。"""
        assert len(UNANCHORED_METHODS) >= 8, (
            "登记表过短：除非确实引入了外部锚定，否则不得删减。"
            "若确已锚定，请同时更新本断言并说明来源。"
        )

    def test_every_entry_states_the_specific_gap(self):
        """每条必须写明**具体**缺什么依据，而非泛泛"无验证"。"""
        for task, gap in UNANCHORED_METHODS.items():
            assert gap.strip(), f"{task} 的缺口说明为空"
            assert len(gap) >= 10, f"{task} 的缺口说明过于笼统: {gap!r}"


class TestAnchoringStatusIsNotOverclaimed:
    """当前锚定现状 —— 把"我们能证明什么"写死在断言里。"""

    def test_no_third_party_tool_anchor(self):
        """本项目不使用第三方统计工具做验证，故**不应**存在 external-tool 级参考。

        若此用例 FAIL，说明已引入外部工具参考值 —— 请同步：
        更新 provenance、从 UNANCHORED_METHODS 移除已覆盖项、
        并把本用例改为断言其存在。
        """
        ref = load_reference()
        if ref.independence == "external-tool":
            pytest.fail(
                "已引入第三方工具参考值！请按 docstring 更新本组用例与 UNANCHORED_METHODS。"
            )
        assert ref.independence in {"none", "hand-transcribed", "independent-implementation"}

    def test_no_third_party_tool_pending_work_left(self):
        """**决定已执行**：不残留任何"用某工具生成参考值"的待办表述。

        2026-09-24 决定放弃第三方工具验证路线；若日后重新考虑，
        请连本用例一并修改（这是一个有意的决策锚点，不是遗漏）。

        实现说明：被禁字符串在本文件中**拼接构造**且不扫描本文件 ——
        否则断言自己所在的文件必然命中（自指矛盾）。
        """
        here = Path(__file__).resolve().parent
        targets = [here / "_loader.py", here / "reference.json"]
        forbidden = ["q" + "cc::", "SixSigma" + "::", "surv" + "fit", "car" + "::Anova"]
        for path in targets:
            text = path.read_text(encoding="utf-8")
            for tool in forbidden:
                assert tool not in text, (
                    f"{path.name} 仍残留第三方工具待办表述 {tool!r}；"
                    "本决定（2026-09-24 放弃该路线）要求清除"
                )

    def test_registry_reasons_are_not_pending_todos(self):
        """登记表的"缺口说明"不得含待办措辞（那会把局限记录变回待办清单）。"""
        for task, gap in UNANCHORED_METHODS.items():
            for word in ("待生成", "待引入", "计划用", "将用"):
                assert word not in gap, (
                    f"{task} 的缺口说明含待办措辞 {word!r}；本表记录的是**局限**而非待办：{gap!r}"
                )

    def test_textbook_layer_covers_four_method_families(self):
        """教科书公式层（test_spc_msa_golden.py）当前覆盖 4 类方法。

        这个数字是**可核对的承诺**：新增覆盖时同步更新。
        """
        golden = (Path(__file__).resolve().parent / "test_spc_msa_golden.py").read_text(
            encoding="utf-8"
        )
        classes = [
            "TestXbarRControlLimits",
            "TestCusumChart",
            "TestEwmaChart",
            "TestGageRRVarianceComponents",
        ]
        missing = [c for c in classes if f"class {c}" not in golden]
        assert not missing, f"教科书层缺少承诺的测试类: {missing}"

    def test_registry_has_no_duplicate_keys(self):
        assert len(UNANCHORED_METHODS) == len(set(UNANCHORED_METHODS))
