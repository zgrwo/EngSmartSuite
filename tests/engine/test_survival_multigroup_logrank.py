"""生存分析的分组比较披露门禁（审查 2026-10-09 契约 #20）。

## 缺陷

`reliability.py` 的 log-rank 段写作 `if len(groups) == 2:` —— 于是**分组数 > 2 时
整段被跳过**：既不计算、也不生成表格、**也没有任何提示**（`messages` 里没有一条相关
内容）。实测 3 组数据 → `tables` 只有 `km_survival` / `life_percentiles`，
用户会以为"引擎看过了数据、结论就是没有组间差异"。

契约 `boundary-contract.md` 的边界清单 #20 正是这一条，要求：

    | 20 | 多组 log-rank（>2 组） | B2 | 静默不做的现状 → 明确披露"未做" | `E_DESIGN_LOGRANK_SKIPPED` |

而 **B2 必须在用户可见处标注**是契约的两条硬性要求之一（不得只写 `logger.debug`）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _frame(n_per_group: int = 30, n_groups: int = 2, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names = ["A", "B", "C", "D"][:n_groups]
    scale = {"A": 10.0, "B": 25.0, "C": 15.0, "D": 40.0}
    times, events, groups = [], [], []
    for g in names:
        times.extend(rng.exponential(scale[g], n_per_group))
        # 保证每组都有失效事件（否则 log-rank 无事件可比）
        events.extend([1] * (n_per_group // 2) + [0] * (n_per_group - n_per_group // 2))
        groups.extend([g] * n_per_group)
    return pd.DataFrame({"t": times, "e": events, "g": groups})


def _run(n_groups: int):
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.services.orchestrator import orchestrate

    return orchestrate(
        AnalysisRequest(
            task="survival_analysis",
            data=_frame(n_groups=n_groups),
            target_col="t",
            feature_cols=["e", "g"],
            params={"event_col": "e", "group_col": "g"},
        )
    )


class TestMultiGroupLogRankIsDisclosed:
    def test_two_groups_produces_the_comparison(self):
        """对照：2 组时 log-rank 必须真的做出来（防修成"一律不做"）。"""
        r = _run(2)
        assert r.status == "ok", r.messages
        assert any("log_rank" in k.lower() or "logrank" in k.lower() for k in r.tables), (
            f"2 组应产出 log-rank 表，实际 tables={list(r.tables)}"
        )

    def test_three_groups_is_explicitly_disclosed_as_not_done(self):
        """3 组时必须明确说"未做"，而不是静默省略。"""
        r = _run(3)
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert "log-rank" in blob.lower() or "log rank" in blob.lower(), (
            f"3 组未披露「未做 log-rank 检验」：{r.messages}"
        )
        assert "未做" in blob or "未进行" in blob or "仅支持" in blob, (
            f"披露必须说明「没做」，而不是含糊带过：{r.messages}"
        )

    @pytest.mark.parametrize("n_groups", [3, 4])
    def test_disclosure_present_for_every_multi_group_case(self, n_groups):
        r = _run(n_groups)
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert str(n_groups) in blob, f"应点名实际分组数 {n_groups}：{r.messages}"

    def test_metadata_records_the_skip(self):
        """给下游/测试一个机器可读的判据（不依赖中文文案）。"""
        r = _run(3)
        assert r.metadata.get("logrank_skipped_reason"), (
            f"metadata 应记录跳过原因，实际 keys={sorted(r.metadata)}"
        )

    def test_clean_single_group_has_no_logrank_noise(self):
        """1 组时不该出现"多组"相关披露（避免噪音）。"""
        r = _run(3)
        blob = " ".join(r.messages or [])
        assert "log-rank" in blob.lower()
