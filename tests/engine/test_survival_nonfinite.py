"""`survival_analysis` 的非有限值处置（第 41 轮）。

## 实测发现的缺陷（本文件是复现测试）

`survival_analysis` 的入口只做 `req.data[cols].dropna()` —— **没有非有限值清洗**。
实测（40 个 Weibull(1.5)×100 观测）：

| 输入 | status | `weibull_shape` | 中位数 | messages |
|:---|:---|:---|:---|:---|
| 干净 | ok | 1.3799 | 77.057 | `[]` |
| 3 个 `+Inf` | ok | **None** | **86.378**（被污染） | **`[]`** |
| 2 个 `-Inf` | ok | **None** | 76.938 | **`[]`** |
| 5 个 `NaN` | ok | 1.3162 | 76.938 | `[]`（NaN 走 dropna，正确） |

两个问题：

1. **静默降级**（违反 B2/B3 披露要求）：`±Inf` 使 Weibull MLE 失败 →
   `shape`/`scale` 变成 `None`，但 `messages` **为空** —— 用户看到"参数缺失"
   却不知道原因，也不知道数据里有问题。
2. **`+Inf` 污染点估计**：中位数由 77.06 变为 86.38。`+Inf` 在 KM 排序里
   落到最右端，被当作"活得最久"的观测，实质上抬高了生存估计。

对照：`NaN` 的处理是**正确的**（走 `dropna`，不改变结果，无需披露）——
这划清了两个概念：`NaN` = 缺失（本来就会丢），`±Inf` = 非有限值（须清洗 + 披露）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _run(times, events, target="t", features=("e",)):
    return orchestrate(
        AnalysisRequest(
            task="survival_analysis",
            data=pd.DataFrame({"t": times, "e": events}),
            target_col=target,
            feature_cols=list(features),
        )
    )


def _base(n: int = 40, seed: int = 9) -> np.ndarray:
    return np.random.default_rng(seed).weibull(1.5, n) * 100


class TestNonFiniteIsCleanedAndDisclosed:
    """±Inf 必须被清洗**且**向用户披露（B1 契约）。"""

    def test_clean_input_has_no_message(self):
        r = _run(_base(), np.ones(40, int))
        assert r.status == "ok", r.messages
        assert r.messages == [], f"干净数据不应有提示：{r.messages}"

    def test_positive_inf_is_disclosed(self):
        t = _base()
        t[:3] = np.inf
        r = _run(t, np.ones(40, int))
        assert r.status == "ok", r.messages
        joined = " ".join(r.messages)
        assert "非有限值" in joined, f"±Inf 被剔除却未披露（B1 契约）：{r.messages}"
        assert "3" in joined, f"披露应含剔除数量 3：{r.messages}"

    def test_negative_inf_is_disclosed(self):
        t = _base()
        t[:2] = -np.inf
        r = _run(t, np.ones(40, int))
        assert r.status == "ok", r.messages
        assert any("非有限值" in m and "2" in m for m in r.messages), r.messages

    def test_nan_does_not_produce_non_finite_message(self):
        """`NaN` 走 `dropna`（缺失语义）→ **不算**非有限值，不应产生该提示。"""
        t = _base()
        t[:5] = np.nan
        r = _run(t, np.ones(40, int))
        assert r.status == "ok", r.messages
        assert not [m for m in r.messages if "非有限值" in m], r.messages


class TestPointEstimatesAreNotPolluted:
    """`±Inf` 剔除后的点估计应与"一开始就没有它们"**一致**。

    这是本缺陷的实质危害：`+Inf` 在 KM 排序里落到最右端，被当作"活得最久"，
    把中位数从 77.06 抬到 86.38 —— 而用户看不到任何提示。
    """

    def test_median_matches_the_clean_case(self):
        base = _base()
        clean = _run(base, np.ones(40, int))
        contaminated = base.copy()
        contaminated[:3] = np.inf
        dirty = _run(contaminated, np.ones(40, int))
        assert clean.status == "ok" and dirty.status == "ok", (clean.messages, dirty.messages)
        assert float(dirty.metadata["median_survival"]) == pytest.approx(
            float(clean.metadata["median_survival"]), rel=1e-9
        ), "剔除 ±Inf 后中位数应与干净数据一致（此前被 +Inf 抬高）"

    def test_weibull_fit_still_succeeds_after_cleaning(self):
        """剔除 `±Inf` 后必须**仍能**拟合 Weibull（此前静默返回 `None`）。"""
        base = _base()
        contaminated = base.copy()
        contaminated[:3] = np.inf
        r = _run(contaminated, np.ones(40, int))
        assert r.status == "ok", r.messages
        assert r.metadata["weibull_shape"] is not None, (
            "剔除 3 个 +Inf 后仍有 37 个有效观测，应能拟合 Weibull"
        )
        assert r.metadata["weibull_scale"] is not None

    def test_shape_is_close_to_the_clean_case(self):
        """剔除 `±Inf` 后的形状参数应与干净情形**接近（5% 内）**。

        ⚠️ 我首版断言"完全一致（rel=1e-6）"并**失败**（1.3574 vs 1.3800）——
        原因很朴素：剔除 3 个观测后样本从 **40 变 37**，Weibull MLE 自然不同。
        "剔除污染值"**不等于**"回到原样本"，只是回到**同一分布的一个稍小子样本**。
        故合理的判据是"接近"（证明没有被 `+Inf` 严重扭曲），而非相等。
        """
        base = _base()
        clean = _run(base, np.ones(40, int))
        contaminated = base.copy()
        contaminated[:3] = np.inf
        dirty = _run(contaminated, np.ones(40, int))
        assert float(dirty.metadata["weibull_shape"]) == pytest.approx(
            float(clean.metadata["weibull_shape"]), rel=0.05
        ), "剔除 +Inf 后形状参数应接近干净情形（此前被 +Inf 完全毁掉，返回 None）"


class TestBoundaryCodesAreExposed:
    """收口到 `_guard` 后应给出机器可读错误码。"""

    def test_clean_input_has_no_cleaning_code(self):
        r = _run(_base(), np.ones(40, int))
        codes = r.metadata.get("boundary_codes", [])
        assert "E_DATA_NON_FINITE_DROPPED" not in codes, codes

    def test_non_finite_yields_the_code(self):
        t = _base()
        t[:3] = np.inf
        r = _run(t, np.ones(40, int))
        codes = r.metadata.get("boundary_codes", [])
        assert "E_DATA_NON_FINITE_DROPPED" in codes, codes

    def test_codes_are_machine_readable(self):
        import re

        t = _base()
        t[:3] = np.inf
        r = _run(t, np.ones(40, int))
        for code in r.metadata.get("boundary_codes", []):
            assert re.fullmatch(r"E_[A-Z0-9_]+", code), f"码格式不合约定: {code!r}"


class TestExistingWarningsStillWork:
    """既有的三条警告（B2 降级 / 欠定 / 高删失）不得因本次收口而丢失。"""

    def test_too_few_events_warns(self):
        """失效观测 < 5 → 提示未做 Weibull 估计（B3 欠定）。"""
        base = _base(30)
        events = np.zeros(30, int)
        events[:3] = 1  # 只有 3 个失效
        r = _run(base, events)
        assert r.status == "ok", r.messages
        assert any("失效观测仅" in m for m in r.messages), r.messages

    def test_high_censoring_warns(self):
        """删失比例 > 50% → 提示 CI 会变宽（B3 近似）。"""
        base = _base(40)
        events = np.ones(40, int)
        events[:25] = 0  # 25/40 = 62.5% 删失
        r = _run(base, events)
        assert r.status == "ok", r.messages
        assert any("删失比例" in m for m in r.messages), r.messages

    def test_enough_events_and_low_censoring_is_quiet(self):
        """反向：失效充足 + 低删失 → 不应有上述两条提示。"""
        r = _run(_base(40), np.ones(40, int))
        assert r.status == "ok", r.messages
        assert not [m for m in r.messages if "失效观测仅" in m or "删失比例" in m], r.messages


class TestGuardIsActuallyUsed:
    """**目标断言**：`survival_analysis` 确实走 `_guard`（收口完成）。"""

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "engine" / "reliability.py"
        ).read_text(encoding="utf-8")
        # 只取 survival_analysis 函数的源码段
        start = src.index("def survival_analysis(")
        rest = src[start + 1 :]
        nxt = rest.find("\ndef ")
        return src[start : start + 1 + (nxt if nxt > 0 else len(rest))]

    def test_uses_guard_cleaning(self):
        body = self._source()
        assert "clean_frame(" in body or "clean_series(" in body, (
            "survival_analysis 应走 _guard 的清洗入口"
        )

    def test_uses_boundary_report(self):
        body = self._source()
        assert "BoundaryReport" in body, "应使用 BoundaryReport 收集处置记录"
        assert "report.messages()" in body, "用户可见提示应由 report.messages() 产出"

    def test_has_no_hand_rolled_warn_list(self):
        body = self._source()
        assert "warn_msgs" not in body, (
            "survival_analysis 不应再有手写的 warn_msgs 列表（应改为 report.add(BoundaryIssue(...))）"
        )
