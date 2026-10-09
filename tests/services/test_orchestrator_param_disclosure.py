"""未知参数名的披露门禁（审查 2026-10-09 P2-5）。

## 缺陷

`req.params` 里的未知键此前被**静默忽略**：实测 `process_capability(usll=70)`
返回 `status=ok`、`messages` 为空 —— 用户以为规格上限生效了，
实际算的是"没有规格限"的能力指数（Cp/Cpk 完全不同）。

## 为什么是"披露"而不是"拒绝"

多余键**不会让结果算错**，只会让用户的意图落空；而"多带了一个无关键"的调用
（例如前端把整份面板载荷原样发来）是合法且常见的。若改成拒绝，
会把这类正常调用打成失败 —— 属于"修一个坑挖一个坑"。
故口径是：**结果照常给，消息里点名拼错的键并列出可用参数**。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _frame(n: int = 120) -> pd.DataFrame:
    return pd.DataFrame({"y": np.random.default_rng(3).normal(50, 5, n)})


def _run(params: dict):
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.services.orchestrator import orchestrate

    return orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=_frame(),
            target_col="y",
            feature_cols=[],
            params=params,
        )
    )


class TestUnknownParamIsDisclosed:
    def test_typo_is_named_and_available_params_listed(self):
        r = _run({"usll": 70})
        # 不拒绝：结果照常给出
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert "usll" in blob, f"必须点名拼错的键：{r.messages}"
        assert "未被本任务使用" in blob, blob
        # 必须给出补救方向（可用参数名），否则用户只能猜
        assert "usl" in blob, f"必须列出可用参数：{blob}"

    @pytest.mark.parametrize("key", ["lsll", "usl_limit", "alpha"])
    def test_multiple_typos_each_named(self, key):
        r = _run({key: 1.0})
        assert r.status == "ok", r.messages
        assert key in " ".join(r.messages or []), r.messages

    def test_clean_params_have_no_note(self):
        """反向噪音门禁：合法入参不得出现任何"未知参数"提示。"""
        for params in ({}, {"usl": 70, "lsl": 30}, {"transform": "", "subgroup_size": 5}):
            r = _run(params)
            assert r.status == "ok", f"params={params}: {r.messages}"
            assert not any("未被本任务使用" in str(m) for m in (r.messages or [])), (
                f"params={params} 被误报未知参数：{r.messages}"
            )

    def test_disclosure_does_not_disturb_existing_messages(self):
        """披露是**追加**，不得挤掉引擎原有的消息。"""
        r = _run({"usll": 70})
        assert len(r.messages) >= 2, f"原有消息应被保留：{r.messages}"
        assert any("移动极差法" in str(m) for m in r.messages), r.messages


class TestNoFalsePositivesOnEngineReadKeys:
    """**零误报**是这条披露的生命线（我第一版就踩了）。

    引擎里有一批参数**确实读取、却从未在 Spec 声明**：`filter_groups`（图表分组筛选）、
    `ranges` / `objectives` / `weights`（结构化入参）、`alpha_lasso`、`group_col`
    （部分任务）…… 若"已知集"只取 Spec 字段，这些合法参数会被说成
    「未被本任务使用（可能拼写有误）」—— **错误归因**，用户会去改一个本来就对的参数，
    比不提示更糟。故已知集 = `Spec 字段 ∪ 面板默认值 ∪ 引擎读取面（AST 提取）`。
    """

    def test_no_task_flags_its_own_engine_read_keys(self):
        from smartsuite.services.orchestrator import DEFAULT_PARAMS
        from smartsuite.services.param_labels import engine_read_param_keys, spec_for_task
        from smartsuite.services.task_spec import TASK_SPECS

        offenders: list[str] = []
        for spec_meta in TASK_SPECS:
            spec = spec_for_task(spec_meta.key)
            if spec is None:
                continue
            read = engine_read_param_keys(spec_meta.key)
            known = set(DEFAULT_PARAMS.get(spec_meta.key, {})) | set(read)
            flagged = spec.unknown_fields(
                {k: 1 for k in read if k not in set(DEFAULT_PARAMS.get(spec_meta.key, {}))},
                extra_known=known,
            )
            if flagged:
                offenders.append(f"{spec_meta.key}: {flagged}")
        assert not offenders, (
            "以下任务的「引擎确实读取的参数」被误报为拼写错误（错误归因）：\n  "
            + "\n  ".join(offenders)
        )

    def test_scanner_is_not_vacuous(self):
        """扫描器必须真的提取到键 —— 否则上一条会因"读取面为空"而恒真（假绿）。"""
        from smartsuite.services.param_labels import engine_read_param_keys
        from smartsuite.services.task_spec import TASK_SPECS

        total = sum(len(engine_read_param_keys(s.key)) for s in TASK_SPECS)
        assert total >= 20, f"只提取到 {total} 个引擎读取键 —— 扫描器可能已失效"
        assert "filter_groups" in engine_read_param_keys("box_chart"), (
            "box_chart 的分组筛选参数应被提取到（已知读取点）"
        )

    def test_indirectly_read_key_is_still_flagged_correctly(self):
        """反例钉住：`event_col` **不是**参数（引擎取 `feature_cols[0]`），应被点名。

        这条防止我把"零误报"修过头 —— 下一步若有人为了让消息更少而把所有键都
        塞进白名单，本用例会红。
        """
        from smartsuite.services.param_labels import engine_read_param_keys, spec_for_task

        spec = spec_for_task("survival_analysis")
        known = set(engine_read_param_keys("survival_analysis"))
        assert "event_col" not in known, "event_col 来自 feature_cols，不是 params 键"
        assert spec.unknown_fields({"event_col": "e"}, extra_known=known) == ["event_col"]


class TestGlobalParamVocabulary:
    """`global_param_vocabulary()` —— 本产品"存在这个参数名"的判据。

    它决定披露文案的**措辞分级**：键在词汇表里（别的任务会用）→「其他任务会用到该
    参数名」；不在 →「可能拼写有误」。分级错了就是**错误指控**，故两者都要钉住。
    """

    def test_is_non_empty_and_cached(self):
        from smartsuite.services.param_labels import global_param_vocabulary

        vocab = global_param_vocabulary()
        assert isinstance(vocab, frozenset)
        assert len(vocab) >= 30, f"词汇表只含 {len(vocab)} 个键 —— 可能收集逻辑失效"
        # 返回 frozenset 且 lru_cache：同一对象（避免每次调用重建）
        assert global_param_vocabulary() is vocab

    @pytest.mark.parametrize("key", ["group_col", "usl", "alpha", "method"])
    def test_common_param_names_are_present(self, key):
        from smartsuite.services.param_labels import global_param_vocabulary

        assert key in global_param_vocabulary(), f"{key} 是本产品通用参数名，应在词汇表内"

    def test_typo_is_not_in_vocabulary(self):
        """拼错的键不该进词汇表 —— 否则真拼写错误也会被降级成"不适用"。"""
        from smartsuite.services.param_labels import global_param_vocabulary

        for typo in ("usll", "lsll", "zzz_not_a_param"):
            assert typo not in global_param_vocabulary()

    def test_used_for_two_tier_wording_end_to_end(self):
        """端到端：`anova` 同时收到"别处合法"与"真拼错"的键，措辞必须分开。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        rng = np.random.default_rng(1)
        df = pd.DataFrame({"y": rng.normal(0, 1, 60), "g": ["A", "B"] * 30})
        r = orchestrate(
            AnalysisRequest(
                task="anova",
                data=df,
                target_col="y",
                feature_cols=["g"],
                params={"group_col": "g", "usll": 70},
            )
        )
        assert r.status == "ok", r.messages
        note = " ".join(r.messages or [])
        assert "其他任务会用到该参数名" in note, f"group_col 应按「不适用」措辞：{note}"
        assert "可能拼写有误" in note, f"usll 应按「拼写错误」措辞：{note}"
        # 两句必须各自对应正确的键，不能串位
        assert note.index("group_col") < note.index("其他任务会用到该参数名") < note.index("usll")


class TestUnknownMessageBuilder:
    """`Spec.unknown_message` 的单元判据。"""

    def test_returns_none_when_all_keys_known(self):
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("process_capability")
        assert spec.unknown_message({"usl": 1.0, "lsl": 0.0}) is None

    def test_sorted_and_deduplicated(self):
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("process_capability")
        msg = spec.unknown_message({"zzz": 1, "aaa": 2})
        assert msg is not None
        assert msg.index("aaa") < msg.index("zzz"), f"应按字典序稳定输出：{msg}"
