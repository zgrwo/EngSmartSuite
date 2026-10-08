"""属性控制图（p/np/c/u）的样本量假设校验。

对应第三轮复核 P2-6（logs/reports/verify-round3/R3-复核清单.md）：

`attribute.py` 的 np 与 c 分支使用**常数控制限**：
    np:  ucl = np̄ + 3·sqrt(np̄(1−p̄))
    c:   ucl = c̄ + 3·sqrt(c̄)
这两条公式只在**各子组样本量相等**时成立。

但 `n_vals` 来自 `groupby(...)["y"].agg(count="sum", size="count")` 或用户的
`n_col`，**完全可能不等**（如各批次抽检数不同）。原实现对该情形**无任何校验**，
直接套常数限 → 静默给出错误的控制限与错误的违规判定（用户据此判定过程是否受控）。

对照：p 与 u 分支用的是**逐点变限**（`cl ± 3·sqrt(cl(1-cl)/n_i)`），
在不等样本量下仍然正确 —— 所以这不是"数值算错"，而是**公式适用条件未校验**。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def _attr_frame(counts, sizes, defect_col="不良数"):
    """构造属性图数据：每个子组一行，显式给出样本量列。"""
    rows = []
    for i, (c, n) in enumerate(zip(counts, sizes, strict=True), start=1):
        rows.append({"批次": f"B{i}", defect_col: c, "抽检数": n})
    return pd.DataFrame(rows)


def _run(df, chart_type, extra=None):
    params = {"chart_type": chart_type, "n_col": "抽检数"}
    if extra:
        params.update(extra)
    return orchestrate(
        AnalysisRequest(
            task="spc_attribute",
            data=df,
            target_col="不良数",
            feature_cols=["批次"],
            params=params,
        )
    )


def _ucl(result) -> float:
    """从 control_stats 表读首个 UCL。

    注意：表中数值经 `round_for_display` 作了 **4 位小数**展示舍入，
    故比对时容差应为 5e-5（半个末位），而非 1e-9 —— 否则测的是舍入而非公式。
    """
    return float(result.tables["control_stats"]["UCL"].iloc[0])


class TestNpChartEqualSampleSize:
    """np 图在样本量不等时不得给出常数控制限。"""

    def test_equal_sizes_still_work(self):
        """等样本量是 np 图的标准前提，必须保持可用。"""
        df = _attr_frame([3, 5, 2, 6, 4, 3], [100] * 6)
        r = _run(df, "np")
        assert r.status == "ok", f"等样本量 np 图应可用: {r.messages}"
        np_bar = float(df["不良数"].mean())
        expected_ucl = np_bar + 3 * np.sqrt(np_bar * (1 - np_bar / 100))
        assert _ucl(r) == pytest.approx(expected_ucl, abs=5e-5)

    def test_unequal_sizes_rejected_with_actionable_message(self):
        """不等样本量 → 拒绝，并指出正确替代（p 图或按等样本量分组）。"""
        df = _attr_frame([3, 5, 2, 6, 4, 3], [100, 120, 80, 150, 100, 200])
        r = _run(df, "np")
        assert r.status == "error", (
            f"不等样本量的 np 图必须拒绝（常数限不适用），实际 status={r.status}, 表={r.tables}"
        )
        blob = " ".join(r.messages)
        assert "样本量" in blob, f"消息应点明样本量问题: {r.messages}"
        assert ("p 图" in blob) or ("np" in blob), f"应给出替代方案: {r.messages}"

    def test_unequal_sizes_never_silently_produce_limits(self):
        """回归防线：无论 n 差异多小，只要不等就不能静默出限。"""
        for sizes in ([100, 101, 100, 100, 100, 100], [50, 500, 50, 50, 50, 50]):
            df = _attr_frame([3, 5, 2, 6, 4, 3], sizes)
            r = _run(df, "np")
            assert r.status == "error", f"n={sizes} 不等时应拒绝"


class TestCChartEqualSampleSize:
    """c 图同样只在子组大小相等时成立（每子组检查单位数一致）。"""

    def test_equal_sizes_still_work(self):
        df = _attr_frame([2, 4, 1, 5, 3, 2], [10] * 6)
        r = _run(df, "c")
        assert r.status == "ok", f"等样本量 c 图应可用: {r.messages}"
        c_bar = float(df["不良数"].mean())
        assert _ucl(r) == pytest.approx(c_bar + 3 * np.sqrt(c_bar), abs=5e-5)

    def test_unequal_sizes_rejected(self):
        df = _attr_frame([2, 4, 1, 5, 3, 2], [10, 20, 10, 10, 10, 30])
        r = _run(df, "c")
        assert r.status == "error", (
            f"不等子组大小的 c 图必须拒绝，实际 status={r.status}, 表={r.tables}"
        )
        assert "样本量" in " ".join(r.messages) or "子组" in " ".join(r.messages)


class TestVariableLimitChartsUnaffected:
    """p / u 图使用逐点变限，不等样本量下**必须保持可用**（不得被误伤）。"""

    @pytest.mark.parametrize("chart_type", ["p", "u"])
    def test_unequal_sizes_still_work(self, chart_type):
        """p/u 图在不等样本量下必须可用，且控制限逐点随 n_i 变化。

        真正的数值断言（而非仅 status==ok）：
          - CL 等于池化统计量；
          - UCL/LCL 逐点随 n_i 变化，且 LCL 非负；
          - 带宽与 n_i 反向（sqrt(1/n) 关系）。

        注意数据选择：不良率需足够高（此处 ≈30%），否则 `p̄ − 3√(p̄(1−p̄)/n) < 0`
        会被**正确**钳位到 0，LCL 全为 0 —— 那样测的是钳位而非变限。
        """
        sizes = [100, 120, 80, 150, 100, 200]
        # 不良率 ≈30%，保证各 n_i 下 LCL 均为正
        df = _attr_frame([30, 36, 24, 45, 30, 60], sizes)
        r = _run(df, chart_type)
        assert r.status == "ok", f"{chart_type} 图应支持不等样本量: {r.messages}"

        stats_tbl = r.tables["control_stats"]
        cl = float(r.metadata["cl"])
        pooled = float(df["不良数"].sum() / df["抽检数"].sum())
        assert cl == pytest.approx(pooled, abs=5e-5), (
            f"{chart_type} 图 CL 应为池化统计量 {pooled}，实际 {cl}"
        )

        ucl = stats_tbl["UCL"].astype(float).to_numpy()
        lcl = stats_tbl["LCL"].astype(float).to_numpy()
        assert len(set(np.round(ucl, 6))) > 1, f"UCL 应随 n_i 变化: {ucl}"
        assert (lcl > 0).all(), f"本数据下 LCL 应为正（否则测的是钳位）: {lcl}"
        assert len(set(np.round(lcl, 6))) > 1, f"LCL 应随 n_i 变化: {lcl}"
        # 带宽与 n_i 反向：n 越大带宽越窄
        widths = ucl - lcl
        order = np.argsort(sizes)
        assert widths[order[-1]] < widths[order[0]], (
            f"最大样本量的控制限带宽应小于最小样本量: widths={widths}"
        )

    def test_p_chart_limits_vary_with_n(self):
        """p 图的控制限必须逐点随 n_i 变化——这正是它与 np 图的分工。"""
        df = _attr_frame([3, 5, 2, 6, 4, 3], [100, 120, 80, 150, 100, 200])
        r = _run(df, "p")
        ucl = r.tables["control_stats"]["UCL"].astype(float).to_numpy()
        assert len(set(np.round(ucl, 9))) > 1, f"p 图 UCL 应随样本量变化，实际全部相同: {ucl}"


class TestBoundaryDisclosure:
    """不等样本量的判定必须可追溯到具体数值。"""

    def test_rejection_message_includes_sample_sizes(self):
        df = _attr_frame([3, 5, 2, 6, 4, 3], [100, 120, 80, 150, 100, 200])
        r = _run(df, "np")
        assert r.status == "error", "前置：不等样本量应被拒绝"
        blob = " ".join(r.messages)
        # 至少应出现一个真实子组大小，便于用户定位是哪几个子组不一致
        assert any(str(n) in blob for n in (100, 120, 80, 150, 200)), (
            f"消息应列出实际样本量以便定位: {r.messages}"
        )
