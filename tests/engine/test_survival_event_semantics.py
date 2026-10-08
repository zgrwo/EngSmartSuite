"""生存分析事件列语义判定（文本编码）— P0-2 回归防线。

对应第三轮复核 P0-2（logs/reports/verify-round3/R3-复核清单.md）：

`reliability.py` 对文本事件列用 `sorted(unique_vals)[-1]`（**字典序最大者**）判定失效。
实测端到端复现（真值 40 个失效事件）：

    Fail/Pass  -> n_events=60   ← 'Pass' > 'Fail'，事件被整个搞反
    NG/OK      -> n_events=60   ← 'OK' > 'NG'
    异常/正常   -> n_events=60   ← '正常' > '异常'
    是/否       -> n_events=40   ✓ 恰好正确（'是' > '否'）
    1/0        -> n_events=40   ✓ 数值分支

即只有中文「是/否」这一种编码恰好正确——**巧合被当成了设计**。
KM 曲线、Weibull、log-rank 全部随之反转，且 status 仍是 ok。

修复原则（沿用既有 D-2 决定的口径：不猜）：
  1. 优先取显式声明的失效值（`params.event_value`）；
  2. 否则只接受**语义明确**的固定对照表；
  3. 其余一律 B0 拒绝，并在消息中给出可直接照做的修法。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.reliability import survival_analysis

# 25 个早期失效（真事件）+ 75 个晚期删失；任一编码下真 n_events 恒为 25
_N_FAIL, _N_CENS = 25, 75


def _survival_frame(fail_label, cens_label):
    rng = np.random.default_rng(1)
    times = np.concatenate([rng.uniform(1, 10, _N_FAIL), rng.uniform(20, 40, _N_CENS)])
    labels = [fail_label] * _N_FAIL + [cens_label] * _N_CENS
    return pd.DataFrame({"life": times, "status": labels})


def _run(fail_label, cens_label, **params):
    return survival_analysis(
        AnalysisRequest(
            task="survival_analysis",
            data=_survival_frame(fail_label, cens_label),
            target_col="life",
            feature_cols=["status"],
            params=params,
        )
    )


class TestAmbiguousTextEventEncodingIsRejected:
    """语义不明的文本编码必须拒绝，不得按字典序猜测。"""

    @pytest.mark.parametrize(
        "fail_label,cens_label",
        [
            ("NG", "OK"),
            ("异常", "正常"),
            ("不良", "良品"),
            ("bad", "good"),
            ("A", "B"),
        ],
    )
    def test_ambiguous_pair_is_rejected_with_actionable_message(self, fail_label, cens_label):
        r = _run(fail_label, cens_label)
        assert r.status == "error", (
            f"{fail_label}/{cens_label} 语义不明，必须拒绝而非猜测。"
            f"实际 status={r.status}, n_events={r.metadata.get('n_events')}（真值 {_N_FAIL}）"
        )
        blob = " ".join(r.messages)
        assert "事件" in blob, f"消息应点明事件列问题: {r.messages}"
        # 必须给出可照做的修法（哨兵契约：不可估计要给建议，不伪造结果）
        assert ("event_value" in blob) or ("0/1" in blob), (
            f"消息应给出修法（显式声明 event_value 或改用 0/1）: {r.messages}"
        )

    def test_no_silent_success_for_any_ambiguous_pair(self):
        """遍历一批常见工艺术语：**必须全部拒绝**（不是"若 ok 则再查数值"）。

        旧写法用 `if r.status == "ok"` 守卫断言，引擎报错时整个循环空转通过——
        属被架空的断言（test_quality_guard 会告警）。改为前置硬断言。
        """
        pairs = [
            ("NG", "OK"),
            ("异常", "正常"),
            ("不良", "良品"),
            ("bad", "good"),
            ("A", "B"),
        ]
        for fail_label, cens_label in pairs:
            r = _run(fail_label, cens_label)
            assert r.status == "error", (
                f"{fail_label}/{cens_label} 应当拒绝，实际 status={r.status} "
                f"n_events={r.metadata.get('n_events')}（真值 {_N_FAIL}）"
            )
            assert "km_survival" not in r.tables, f"{fail_label}/{cens_label} 拒绝时不应产出 KM 表"


class TestExplicitEventValueIsHonored:
    """显式声明 event_value 时必须按其语义计算，不受字典序影响。"""

    @pytest.mark.parametrize(
        "fail_label,cens_label",
        [("Fail", "Pass"), ("NG", "OK"), ("异常", "正常"), ("Pass", "Fail")],
    )
    def test_explicit_event_value_fixes_semantics(self, fail_label, cens_label):
        r = _run(fail_label, cens_label, event_value=fail_label)
        assert r.status == "ok", f"显式声明后应可分析: {r.messages}"
        assert r.metadata.get("n_events") == _N_FAIL, (
            f"event_value={fail_label!r} 时事件数应为 {_N_FAIL}，实际 {r.metadata.get('n_events')}"
        )

    def test_explicit_event_value_reversed_gives_reversed_count(self):
        """把 event_value 指到删失值上，事件数应变成删失数——证明参数真的生效。"""
        r = _run("Fail", "Pass", event_value="Pass")
        assert r.status == "ok"
        assert r.metadata.get("n_events") == _N_CENS


class TestUnambiguousPairsStillWork:
    """语义明确的固定对照表必须保持可用（不得因收紧而破坏既有能力）。"""

    @pytest.mark.parametrize(
        "fail_label,cens_label",
        [
            ("是", "否"),
            ("Yes", "No"),
            ("yes", "no"),
            ("YES", "NO"),
            ("失效", "删失"),
            ("Event", "Censored"),
            ("event", "censored"),
            ("True", "False"),
            ("Fail", "Censored"),
            ("Fail", "Pass"),
            ("失效", "合格"),
            ("故障", "正常"),
            ("1", "0"),
        ],
    )
    def test_recognized_pairs_compute_correct_event_count(self, fail_label, cens_label):
        r = _run(fail_label, cens_label)
        assert r.status == "ok", f"{fail_label}/{cens_label} 应被识别: {r.messages}"
        assert r.metadata.get("n_events") == _N_FAIL, (
            f"{fail_label}/{cens_label} 事件数应为 {_N_FAIL}，实际 {r.metadata.get('n_events')}"
        )

    @pytest.mark.parametrize(
        "fail_label,cens_label",
        [("Dead", "Alive"), ("dead", "alive"), ("通过", "不通过")],
    )
    def test_pairs_needing_explicit_declaration_still_work_with_it(self, fail_label, cens_label):
        """对照表故意不含需成对才成立的词（Dead/Alive）——显式声明后必须可用。"""
        assert _run(fail_label, cens_label).status == "error", "语义不明的配对应先拒绝"
        r = _run(fail_label, cens_label, event_value=fail_label)
        assert r.status == "ok", f"显式声明后应可分析: {r.messages}"
        assert r.metadata.get("n_events") == _N_FAIL


class TestNumericEncodingUnchanged:
    """数值路径的既有契约（必须恰为 {0,1}）不得被本次修改破坏。"""

    @pytest.mark.parametrize("bad", [[1, 2], [10, 20], [0, 1, 2]])
    def test_non_binary_numeric_still_rejected(self, bad):
        times = list(range(1, 1 + len(bad) * 4))
        events = (bad * 4)[: len(times)]
        r = survival_analysis(
            AnalysisRequest(
                task="survival_analysis",
                data=pd.DataFrame({"t": times, "e": events}),
                target_col="t",
                feature_cols=["e"],
            )
        )
        assert r.status == "error", f"{bad} 应报错"
        assert any("事件" in m for m in r.messages)

    def test_zero_one_still_works(self):
        times = list(range(1, 13))
        events = [1, 0] * 6
        r = survival_analysis(
            AnalysisRequest(
                task="survival_analysis",
                data=pd.DataFrame({"t": times, "e": events}),
                target_col="t",
                feature_cols=["e"],
            )
        )
        assert r.status == "ok"
        assert r.metadata.get("n_events") == 6
