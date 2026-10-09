"""P1-2 回归测试：`trend_forecast` 的 ±Inf 披露与错误归因。

契约：[boundary-contract.md](../../docs/governance/boundary-contract.md)（B1 披露）
      [AGENTS.md](../../AGENTS.md) 红线「禁止错误归因」

## 缺陷（2026-10-09 发版前全量审查 P1-2）

原实现只 `req.data[col].dropna()` —— **不剔除 ±Inf**，于是 ±Inf 漏进 sklearn，
抛 `Input y contains infinity`，被 `except` 泛化成：

    趋势预测模型拟合失败，数据可能不足或存在共线性问题，
    请检查数据中是否包含足够的有效观测值。

两处归因**都未经证实**：
  · "数据不足" —— 上面的 `len(data) < 3` 已排除，此处至少 3 个点；
  · "共线性"   —— 本任务只有 1 个自变量（时间轴），共线性无从谈起。

实测：目标列含 4 个 ±Inf（**56 个有效点**）时报"数据不足"。

## 修法

入口经 `_guard.clean_series`（清洗与披露同源），失败文案只陈述已核实的事实。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.detection.trend import trend_forecast


def _run(y: np.ndarray):
    df = pd.DataFrame({"y": y, "t": np.arange(len(y), dtype=float)})
    return trend_forecast(
        AnalysisRequest(
            task="trend_forecast", data=df, target_col="y", feature_cols=["t"], params={}
        )
    )


def _with_inf(n_valid: int = 56, n_inf: int = 4) -> np.ndarray:
    base = np.linspace(10.0, 60.0, n_valid + n_inf)
    y = base.copy()
    y[n_valid:] = [np.inf, -np.inf, np.inf, -np.inf][:n_inf]
    return y


class TestNonFiniteIsDisclosed:
    """B1：非有限值被剔除时**必须**在用户可见处披露。"""

    def test_infinities_are_disclosed_with_count(self):
        r = _run(_with_inf())
        assert r.status == "ok", r.messages
        assert any("非有限" in str(m) for m in r.messages), (
            f"应披露非有限值，实测 messages={r.messages}"
        )
        assert "4" in " ".join(str(m) for m in r.messages), "披露应含具体数量"

    def test_boundary_code_is_exposed(self):
        """机器可读的错误码（与已迁移模块口径一致）。"""
        r = _run(_with_inf())
        assert r.metadata.get("boundary_codes") == ["E_DATA_NON_FINITE_DROPPED"]

    def test_clean_data_gets_no_message(self):
        """干净数据不得产生噪声提示。"""
        r = _run(np.linspace(10.0, 60.0, 60))
        assert r.status == "ok"
        assert r.messages == [], f"干净数据不应有提示: {r.messages}"

    def test_nan_is_handled_silently_as_missing(self):
        """NaN 属**缺失语义**（契约 L4），静默按 `dropna` 处理，**不披露**。

        这一段口径反复过两次，把结论钉死在这里，避免第三次返工：

        - 初版（反向断言「NaN 不应披露」）被当时的契约 B1 行（明示「`NaN`、`±Inf`」）
          证伪 → 改成「NaN 也披露且点名 NaN」；
        - 2026-10-09 **口径裁定**：判据是"这个值是不是缺失" —— NaN 是缺失
          （用户留空/采集失败，`dropna()` 静默处理已是全库语义），
          ±Inf 是"看起来像数据、数值上不合法"（除零/溢出），必须披露。
          契约遂拆为 **L4（缺失值，免披露）** 与 **B1（±Inf，必披露）** 两行，
          本用例与 `test_boundary_guard.py::TestPartitionFinite` 一并按裁定更新。

        注意"静默"仅指**不产生消息**：NaN 行仍会被剔除（与 `dropna` 一致）。
        """
        y = np.linspace(10.0, 60.0, 60).astype(float)
        y[:5] = np.nan
        r = _run(y)
        assert r.status == "ok"
        assert r.messages == [], f"NaN 不得产生披露（缺失语义，静默 dropna）：{r.messages}"


class TestNoMisattribution:
    """AGENTS 红线：真实原因不是 X，就不得输出关于 X 的提示。"""

    def test_inf_case_never_claims_insufficient_data(self):
        """核心回归：±Inf 且有效点充足时，**不得**说"数据不足"。"""
        r = _run(_with_inf(n_valid=56))
        blob = " ".join(str(m) for m in r.messages)
        assert "不足" not in blob, f"56 个有效点被误报为数据不足: {blob}"

    def test_inf_case_never_claims_collinearity(self):
        """单自变量任务提"共线性"是无从谈起的归因。"""
        r = _run(_with_inf())
        blob = " ".join(str(m) for m in r.messages)
        assert "共线" not in blob, f"单自变量任务不得提共线性: {blob}"

    def test_genuine_insufficiency_states_the_actual_count(self):
        """真的不足时，文案应给出**实际样本量**（可核查），而非泛泛而谈。"""
        r = _run(np.array([1.0, 2.0]))
        assert r.status == "error"
        assert any("2" in str(m) for m in r.messages), f"应报出实际有效点数 2，实测 {r.messages}"


class TestEstimationIsUnaffected:
    """清洗不得污染点估计：剔除 ±Inf 后应等价于"本来就没有这几行"。"""

    def test_slope_matches_the_clean_equivalent(self):
        r_inf = _run(_with_inf(n_valid=56, n_inf=4))
        # 干净对照必须用**同样的 56 个点**（`_with_inf` 的前 56 个是
        # `linspace(10,60,60)[:56]`）—— 我首版写成 `linspace(10,60,56)`，
        # 那是**另一组 x 范围**，斜率自然不同（0.847 vs 0.909）。
        r_clean = _run(np.linspace(10.0, 60.0, 60)[:56])
        assert r_inf.metadata["slope"] == pytest.approx(r_clean.metadata["slope"], rel=1e-9), (
            "剔除 ±Inf 后的斜率应与「本来就只有 56 点」一致"
        )

    def test_n_reflects_cleaned_count(self):
        r = _run(_with_inf(n_valid=56, n_inf=4))
        assert r.metadata["n"] == 56, f"n 应为清洗后的 56，实测 {r.metadata['n']}"
