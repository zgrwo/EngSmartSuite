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
