"""过程能力的子组/池化 within-σ 与 Pp/Ppk 置信区间（P2-5）。

## 为什么需要它

引擎原先的组内 σ **只有移动极差法**（`mean(|diff|)/1.128`），它隐含
**"数据行序 = 采样时间顺序"** 的假设。这对工艺数据是硬约束：

  - 从 Excel 里筛选/排序过一遍，行序就变了 → `Cp` 静默失真；
  - 数据本来是按批次成组采集的（每批 5 个），移动极差会把**批间跳变**
    算成"组内变异" → `Cp` 偏小、过程被误判为能力不足。

修法是提供**显式子组口径**：
  - `subgroup_col`：按某一列分组，各组内去均值后池化（不依赖行序）；
  - `subgroup_size`：按行序切成连续等长子组（即经典 X-bar/R 的合理子组）。

同时补 **Pp/Ppk 的置信区间** —— 原先只有 Cp/Cpk 有 CI，而 `Ppk` 常被直接
当放行判据用，没有区间就无法判断"Ppk=1.31 是否真的够 1.33"。

## 本文件怎么验证

1. **池化 σ 有闭式解**（`sqrt(Σ(x−x̄_g)²/(n−k))`）→ 可与引擎逐位对拍，
   这是**精确**验证而非近似比对。
2. **两种等价路径互证**：`subgroup_col`（每组标记相同）与 `subgroup_size`
   在同构数据上必须给出**相同**池化 σ。
3. **不变量**：池化 σ ≤ 整体 σ（去掉组间差异只会更小）；组内无差异时池化 σ=0。
4. **CI 覆盖率**（800 次蒙特卡洛）：Pp/Ppk 的名义 95% 区间实测覆盖率应≈0.95。
   这是**统计性质**检验，不依赖任何实现细节。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate
from smartsuite.engine.capability import process_capability_analysis


def _run(df: pd.DataFrame, target: str = "y", **params):
    base = {"usl": 10.0, "lsl": 0.0}
    base.update(params)
    return process_capability_analysis(
        AnalysisRequest(task="process_capability", data=df, target_col=target, params=base)
    )


def _pooled_sigma_reference(groups: list[np.ndarray]) -> float:
    """池化组内 σ 的闭式解：`sqrt(ΣΣ(x−x̄_g)² / (N−k))`。

    这是**教科书定义**（Montgomery 式 6.17 的样本标准差形式），
    与引擎实现相互独立，可直接对拍。
    """
    total = sum(len(g) for g in groups)
    k = len(groups)
    if total - k <= 0:
        return 0.0
    ss = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
    return float(np.sqrt(ss / (total - k)))


def _grouped_frame(
    seed: int = 0,
    n_groups: int = 20,
    size: int = 5,
    between_sd: float = 2.0,
    within_sd: float = 0.4,
) -> pd.DataFrame:
    """按批次成组采集的数据：组间有大跳变（between_sd），组内只有小变异。

    这正是"移动极差法会把组间跳变误算成组内变异"的场景。
    """
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_groups):
        center = rng.normal(50, between_sd)
        for _ in range(size):
            rows.append({"batch": f"B{g:02d}", "y": center + rng.normal(0, within_sd)})
    return pd.DataFrame(rows)


class TestPooledSigmaViaSubgroupColumn:
    """`subgroup_col` 路径：按列分组池化，不依赖行序。"""

    def test_matches_closed_form(self):
        """池化 σ 必须逐位等于闭式解 `sqrt(ΣΣ(x−x̄_g)²/(N−k))`。"""
        df = _grouped_frame(seed=1)
        r = _run(df, subgroup_col="batch")
        assert r.status == "ok", r.messages
        expected = _pooled_sigma_reference([g["y"].to_numpy() for _, g in df.groupby("batch")])
        assert r.metadata["sigma_within"] == pytest.approx(expected, rel=1e-9), (
            f"池化 σ 不符：引擎 {r.metadata['within_sigma']} vs 闭式解 {expected}"
        )

    def test_method_is_disclosed(self):
        """必须披露用了哪种组内 σ 口径（用户否则无从判断可信度）。"""
        r = _run(_grouped_frame(seed=2), subgroup_col="batch")
        assert r.metadata["within_sigma_method"] == "pooled_subgroup_col", (
            f"口径披露不符：{r.metadata.get('within_sigma_method')}"
        )

    def test_row_order_does_not_affect_result(self):
        """**核心价值**：打乱行序后结果必须完全不变（MR 法做不到这点）。"""
        df = _grouped_frame(seed=3)
        r_orig = _run(df, subgroup_col="batch")
        shuffled = df.sample(frac=1.0, random_state=42).reset_index(drop=True)
        r_shuf = _run(shuffled, subgroup_col="batch")
        assert r_shuf.metadata["sigma_within"] == pytest.approx(
            r_orig.metadata["sigma_within"], rel=1e-12
        ), "池化口径不应受行序影响"

    def test_moving_range_method_does_depend_on_row_order(self):
        """对照：MR 法**确实**受行序影响 —— 证明上一条不是空谈。"""
        df = _grouped_frame(seed=4)
        r_orig = _run(df)  # 默认 MR 法
        shuffled = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
        r_shuf = _run(shuffled)
        assert r_shuf.metadata["sigma_within"] != pytest.approx(
            r_orig.metadata["sigma_within"], rel=1e-6
        ), "MR 法本应受行序影响；若相同说明测试数据构造有问题"

    def test_pooled_not_greater_than_overall(self):
        """池化组内 σ ≤ 整体 σ（去掉组间差异只会更小）。"""
        for seed in range(5):
            r = _run(_grouped_frame(seed=seed), subgroup_col="batch")
            assert r.metadata["sigma_within"] <= r.metadata["sigma_overall"] + 1e-12, (
                f"seed={seed}: 池化 σ={r.metadata['within_sigma']} 不应大于整体 σ="
                f"{r.metadata['sigma_overall']}"
            )

    def test_constant_size_and_column_paths_agree(self):
        """`subgroup_col` 与 `subgroup_size` 在同构数据上必须给出相同池化 σ。

        两条独立代码路径互证（构造方式不同，数学定义相同）。
        """
        df = _grouped_frame(seed=5, n_groups=20, size=5)
        by_col = _run(df, subgroup_col="batch")
        by_size = _run(df, subgroup_size=5)
        assert by_size.metadata["sigma_within"] == pytest.approx(
            by_col.metadata["sigma_within"], rel=1e-9
        ), (
            f"两条路径不一致：by_col={by_col.metadata['within_sigma']} "
            f"by_size={by_size.metadata['within_sigma']}"
        )


class TestPooledSigmaViaSubgroupSize:
    """`subgroup_size` 路径：按行序切连续等长子组。"""

    def test_matches_closed_form(self):
        df = _grouped_frame(seed=6, n_groups=20, size=5)
        r = _run(df, subgroup_size=5)
        groups = [df["y"].to_numpy()[i : i + 5] for i in range(0, len(df), 5)]
        expected = _pooled_sigma_reference(groups)
        assert r.metadata["sigma_within"] == pytest.approx(expected, rel=1e-9)

    def test_method_is_disclosed(self):
        r = _run(_grouped_frame(seed=7), subgroup_size=5)
        assert r.metadata["within_sigma_method"] == "pooled_subgroup_size"

    def test_leftover_rows_are_disclosed(self):
        """样本量不是子组大小整数倍时，末尾余数如何处理必须披露。

        B2 契约：降级（丢弃末尾余数）必须在用户可见处标注，不得静默丢弃。
        断言同时检查"说清丢几个"与"说清实际用几个"，避免含糊提示。
        """
        df = _grouped_frame(seed=8, n_groups=20, size=5).iloc[:-2]  # 98 行 / 5
        r = _run(df, subgroup_size=5)
        assert r.status == "ok", r.messages
        msg = " ".join(r.messages)
        assert "整数倍" in msg, f"应说明样本量非子组大小整数倍：{r.messages}"
        assert "3 个观测未参与" in msg, f"应说清丢弃几个观测（实为 3 个）：{r.messages}"
        assert "95" in msg, f"应说清实际参与估计的观测数（实为 95）：{r.messages}"

    def test_too_large_subgroup_size_is_rejected(self):
        """子组大小 ≥ 样本量时无法分组 → B0 拒绝，不得回落到 MR 法。"""
        df = _grouped_frame(seed=9, n_groups=4, size=5)  # 20 行
        r = _run(df, subgroup_size=20)
        assert r.status == "error", f"应拒绝，实际 {r.status}"
        assert any("子组" in m for m in r.messages), r.messages

    def test_size_one_is_rejected(self):
        """子组大小为 1 时组内 σ 不可估 → 拒绝。

        审查 2026-09-24（P4 步骤③）：参数校验改抛异常后，用户可见结果由编排层
        产出，故此处经 `orchestrate` 断言 `status="error"`（与 Web/CLI 同路径）。
        """
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=_grouped_frame(seed=10),
                target_col="y",
                params={"usl": 10.0, "lsl": 0.0, "subgroup_size": 1},
            )
        )
        assert r.status == "error", f"应拒绝，实际 {r.status}"

    def test_non_integer_subgroup_size_is_rejected(self):
        for bad in (5.5, "abc"):
            r = orchestrate(
                AnalysisRequest(
                    task="process_capability",
                    data=_grouped_frame(seed=11),
                    target_col="y",
                    params={"usl": 10.0, "lsl": 0.0, "subgroup_size": bad},
                )
            )
            assert r.status == "error", f"subgroup_size={bad!r} 应被拒绝"


class TestSubgroupColumnValidation:
    """`subgroup_col` 的边界处理（B0 契约）。"""

    def test_missing_column_is_rejected(self):
        r = _run(_grouped_frame(seed=12), subgroup_col="不存在")
        assert r.status == "error"
        assert any("不存在" in m for m in r.messages), r.messages

    def test_single_distinct_group_is_rejected(self):
        """只有一组时"池化"退化为整体 σ，口径无意义 → 明确拒绝而非静默等价。"""
        df = _grouped_frame(seed=13)
        df["batch"] = "ONLY"
        r = _run(df, subgroup_col="batch")
        assert r.status == "error", f"应拒绝，实际 {r.status}"
        assert any("只有" in m or "1 个" in m or "一个" in m for m in r.messages), r.messages

    def test_group_with_single_observation_is_rejected(self):
        """存在只含 1 个观测的子组 → 该组对组内 σ 无贡献，应明确拒绝。

        （保留它会静默低估组内变异，属"静默降级"。）
        """
        df = _grouped_frame(seed=14, n_groups=10, size=5)
        df = pd.concat([df, pd.DataFrame({"batch": ["SOLO"], "y": [50.0]})], ignore_index=True)
        r = _run(df, subgroup_col="batch")
        assert r.status == "error", f"应拒绝，实际 {r.status}"
        assert any("1" in m and "子组" in m for m in r.messages), r.messages

    def test_cannot_specify_both_methods(self):
        """同时给 `subgroup_col` 与 `subgroup_size` 属歧义 → 拒绝（不得任选其一）。"""
        r = _run(_grouped_frame(seed=15), subgroup_col="batch", subgroup_size=5)
        assert r.status == "error", f"应拒绝歧义输入，实际 {r.status}"
        assert any("同时" in m or "二选一" in m for m in r.messages), r.messages


class TestPpPpkConfidenceIntervals:
    """Pp/Ppk 的置信区间（原先缺失）。"""

    def test_pp_and_ppk_have_ci(self):
        r = _run(_grouped_frame(seed=16))
        assert r.status == "ok", r.messages
        for key in ("pp_ci", "ppk_ci"):
            assert key in r.metadata, f"缺 {key}：{sorted(r.metadata)}"
            lo, hi = r.metadata[key]
            assert lo is not None and hi is not None, f"{key} 不应为 None"
            assert lo < hi, f"{key} 区间方向错误：{lo}, {hi}"

    def test_pp_ci_matches_chi2_formula(self):
        """Pp 的 CI 应等于 χ² 精确式（整体 σ 的自由度就是 n−1，无需收缩）。"""
        df = _grouped_frame(seed=17)
        r = _run(df)
        n = len(df)
        pp = r.metadata["pp"]
        dof = n - 1
        lo = pp * np.sqrt(sp_stats.chi2.ppf(0.025, dof) / dof)
        hi = pp * np.sqrt(sp_stats.chi2.ppf(0.975, dof) / dof)
        assert r.metadata["pp_ci"][0] == pytest.approx(float(lo), rel=1e-9)
        assert r.metadata["pp_ci"][1] == pytest.approx(float(hi), rel=1e-9)

    def test_pp_ci_is_wider_than_cp_ci(self):
        """Pp 的 CI 应比 Cp 的窄？不 —— 应更**窄**（df=n−1 > 0.606(n−1)）。

        整体 σ 用全部 n−1 自由度，而 MR-σ 只有 0.606(n−1)；
        自由度越大区间越窄，故 Pp 的 CI 应更窄。这是口径差异的直接体现。
        """
        df = _grouped_frame(seed=18)
        r = _run(df)
        cp_lo, cp_hi = r.metadata["cp_ci"]
        pp_lo, pp_hi = r.metadata["pp_ci"]
        assert (pp_hi - pp_lo) < (cp_hi - cp_lo), (
            f"Pp 的 CI 半宽({(pp_hi - pp_lo) / 2:.4f}) 应小于 Cp 的"
            f"({(cp_hi - cp_lo) / 2:.4f})，因为整体 σ 的自由度更大"
        )

    def test_ppk_ci_lower_bound_not_above_point_estimate(self):
        for seed in range(6):
            r = _run(_grouped_frame(seed=20 + seed))
            lo, _ = r.metadata["ppk_ci"]
            assert lo <= r.metadata["ppk"] + 1e-12, (
                f"seed={seed}: Ppk 下限 {lo} 不应高于点估计 {r.metadata['ppk']}"
            )

    def test_ci_is_none_without_specs(self):
        """没有规格限时不产出 CI（不得伪造区间）。"""
        df = _grouped_frame(seed=26)
        r = process_capability_analysis(
            AnalysisRequest(task="process_capability", data=df, target_col="y", params={})
        )
        assert r.status == "ok", r.messages
        assert r.metadata.get("pp_ci", (None, None)) == (None, None)

    def test_pp_ci_coverage_is_nominal(self):
        """**统计性质检验**：Pp 的名义 95% CI 实测覆盖率应≈0.95。

        800 次模拟，真值 Pp 已知（由真 σ 算出）。若 CI 构造错误
        （如自由度用错），覆盖率会明显偏离。
        允许区间 [0.93, 0.97]（800 次下二项标准误约 0.008）。
        """
        rng = np.random.default_rng(123)
        n, true_mu, true_sd = 100, 50.0, 1.0
        usl, lsl = true_mu + 3 * true_sd, true_mu - 3 * true_sd
        true_pp = (usl - lsl) / (6 * true_sd)

        covered = 0
        trials = 800
        for _ in range(trials):
            y = rng.normal(true_mu, true_sd, n)
            df = pd.DataFrame({"y": y})
            r = process_capability_analysis(
                AnalysisRequest(
                    task="process_capability",
                    data=df,
                    target_col="y",
                    params={"usl": usl, "lsl": lsl},
                )
            )
            lo, hi = r.metadata["pp_ci"]
            if lo <= true_pp <= hi:
                covered += 1
        rate = covered / trials
        assert 0.93 <= rate <= 0.97, (
            f"Pp 的 95% CI 实测覆盖率 {rate:.3f}（{covered}/{trials}）偏离名义值 —— "
            "区间构造或自由度可疑"
        )


class TestBackwardCompatibility:
    """不指定子组参数时行为与原先完全一致。"""

    def test_default_method_is_moving_range(self):
        r = _run(_grouped_frame(seed=30))
        assert r.metadata["within_sigma_method"] == "moving_range"

    def test_default_value_unchanged(self):
        """默认路径的 within_sigma 必须与 `mean(|diff|)/1.128` 逐位相同。"""
        df = _grouped_frame(seed=31)
        r = _run(df)
        expected = float(np.mean(np.abs(np.diff(df["y"].to_numpy()))) / 1.128)
        assert r.metadata["sigma_within"] == pytest.approx(expected, rel=1e-12)

    def test_cp_cpk_pp_ppk_still_present(self):
        r = _run(_grouped_frame(seed=32))
        for key in ("cp", "cpk", "pp", "ppk", "sigma_within", "sigma_overall"):
            assert key in r.metadata, f"既有 metadata 字段 {key} 消失"

    def test_moving_range_discloses_row_order_assumption(self):
        """用 MR 法时必须提示"隐含行序=时间顺序"假设（否则用户不知道风险）。"""
        r = _run(_grouped_frame(seed=33))
        assert any("行序" in m or "排序" in m for m in r.messages), (
            f"MR 法应披露行序假设：{r.messages}"
        )
