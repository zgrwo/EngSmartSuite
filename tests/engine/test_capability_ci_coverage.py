"""过程能力指数置信区间的统计性质检验（覆盖率）。

对应第三轮复核 P0-3（logs/reports/verify-round3/R3-复核清单.md）：
`capability.py` 的 Cp/Cpk 用**移动极差法**估计组内 σ（`mean(MR)/1.128`），
但 `_cp_confidence_interval` 用 `dof = n−1` 构造 χ² 区间。

MR 估计量不是样本方差的缩放——它由 **n−1 个高度相关的移动极差**构成
（相邻 MR 共享一个观测），因此有效自由度远小于 n−1。

实测（20000 次蒙特卡洛，n=100）：MR-σ 的有效自由度 df_eff ≈ 60.0 ≈ 0.606(n−1)。
沿用 n−1 会使 CI 过窄 → **Cpk 下限虚高** → 而"Cpk 下限 ≥1.33"正是放行判据。

本文件用**覆盖率检验**替代"与另一个公式比接近"的同义反复：
真 Cp 已知（生成数据时设定），统计它落入报告 CI 的比例应达到名义 95%。
"""

import numpy as np
import pytest

from smartsuite.engine.capability import (
    _cp_confidence_interval,
    _cpk_confidence_interval,
    _mr_dof_eff,
)


def _coverage(ci_fn, *, n, k, rng, alpha=0.05, cpk=False):
    """返回 (覆盖率, 平均 CI 半宽)。

    数据由已知参数的正态分布生成：
      - 组内 σ_true = 1.0 → 真 Cp = (USL−LSL)/(6·1.0)
      - 均值偏移 0.5σ → 真 Cpk = min((USL−μ)/(3σ), (μ−LSL)/(3σ))
    模拟"引擎从样本估计 σ 后构造区间"的过程。
    """
    usl, lsl = 3.0, -3.0  # 真 Cp = 1.0
    mu_shift = 0.5
    hits = 0
    widths = []
    for _ in range(k):
        x = rng.normal(mu_shift, 1.0, n)
        mr = np.abs(np.diff(x))
        sigma_hat = mr.mean() / 1.128
        if not np.isfinite(sigma_hat) or sigma_hat <= 0:
            continue
        mu_hat = x.mean()
        if cpk:
            stat = min((usl - mu_hat) / (3 * sigma_hat), (mu_hat - lsl) / (3 * sigma_hat))
            true = min((usl - mu_shift) / 3.0, (mu_shift - lsl) / 3.0)
        else:
            stat = (usl - lsl) / (6 * sigma_hat)
            true = (usl - lsl) / 6.0
        lo, hi = ci_fn(stat, n, alpha)
        if lo is None or hi is None:
            continue
        hits += int(lo <= true <= hi)
        widths.append(hi - lo)
    return hits / k, float(np.mean(widths))


class TestCpConfidenceIntervalCoverage:
    """Cp 的 95% CI 必须真的覆盖 95%（当前约 78%）。"""

    def test_cp_ci_coverage_is_near_nominal(self):
        """n=100、2000 次重复：覆盖率应落在 [0.93, 0.97]（名义 0.95）。"""
        rng = np.random.default_rng(20260924)
        cov, width = _coverage(_cp_confidence_interval, n=100, k=2000, rng=rng)
        assert 0.93 <= cov <= 0.97, (
            f"Cp 95%CI 实际覆盖率 {cov:.3f}，偏离名义 0.95 过多（平均半宽 {width / 2:.4f}）"
        )

    def test_cp_ci_is_wide_enough_for_mr_sigma(self):
        """CI 半宽必须反映 MR 估计量的不确定性，而非样本方差的（约 1.28 倍差距）。"""
        rng = np.random.default_rng(7)
        n = 100
        _, width = _coverage(_cp_confidence_interval, n=n, k=1500, rng=rng)
        # 解析参照：χ² 区间半宽的相对量级 ~ z_{0.025}·sqrt(1/(2·df_eff))
        df_eff = _mr_dof_eff(n)
        rel_expected = 2 * 1.959964 * np.sqrt(1.0 / (2.0 * df_eff))
        rel_actual = width  # 真 Cp = 1.0 → 宽度即相对宽度
        assert rel_actual == pytest.approx(rel_expected, rel=0.12), (
            f"CI 相对宽度 {rel_actual:.4f} 与 df_eff={df_eff:.1f} 的解析值 {rel_expected:.4f} 不符"
        )


class TestCpkConfidenceIntervalCoverage:
    """Cpk 的 95% CI 也必须反映 MR-σ 的不确定性。"""

    def test_cpk_ci_coverage_is_near_nominal(self):
        rng = np.random.default_rng(20260925)
        cov, width = _coverage(_cpk_confidence_interval, n=100, k=2000, rng=rng, cpk=True)
        assert 0.90 <= cov <= 0.985, (
            f"Cpk 95%CI 实际覆盖率 {cov:.3f}，偏离名义 0.95 过多（平均半宽 {width / 2:.4f}）"
        )

    def test_cpk_ci_lower_bound_is_not_inflated(self):
        """回归防线：Cpk 下限不得系统性高于真值。

        旧实现（dof=n−1）在 n=100 时 CI 过窄约 28% → 下限虚高。
        统计 2000 次重复中"下限 > 真 Cpk"的比例，应接近 (1−0.95)/2 ≈ 2.5%，
        而不是显著更高。
        """
        rng = np.random.default_rng(11)
        n, k = 100, 2000
        usl, lsl, mu_shift = 3.0, -3.0, 0.5
        true_cpk = min((usl - mu_shift) / 3.0, (mu_shift - lsl) / 3.0)
        above = 0
        for _ in range(k):
            x = rng.normal(mu_shift, 1.0, n)
            sigma_hat = np.abs(np.diff(x)).mean() / 1.128
            mu_hat = x.mean()
            stat = min((usl - mu_hat) / (3 * sigma_hat), (mu_hat - lsl) / (3 * sigma_hat))
            lo, _ = _cpk_confidence_interval(stat, n)
            above += int(lo > true_cpk)
        frac = above / k
        assert frac <= 0.06, (
            f"有 {frac:.1%} 的样本给出「Cpk 下限 > 真 Cpk」，远超单侧 2.5%（CI 过窄，下限虚高）"
        )


class TestMrDofEffective:
    """`_mr_dof_eff` 本身的性质。"""

    def test_matches_monte_carlo(self):
        """与蒙特卡洛实测的有效自由度一致（相对误差 < 10%）。"""
        rng = np.random.default_rng(13)
        for n in (30, 100):
            sds = np.array(
                [np.abs(np.diff(rng.normal(0, 1, n))).mean() / 1.128 for _ in range(4000)]
            )
            cv2 = sds.var() / sds.mean() ** 2
            df_mc = 1.0 / (2.0 * cv2)
            assert _mr_dof_eff(n) == pytest.approx(df_mc, rel=0.10), (
                f"n={n}: _mr_dof_eff={_mr_dof_eff(n):.1f} vs 蒙特卡洛 {df_mc:.1f}"
            )

    def test_is_less_than_n_minus_one(self):
        """必须严格小于 n−1（这正是原实现的错误所在）。"""
        for n in (10, 50, 100, 500):
            assert _mr_dof_eff(n) < n - 1

    @pytest.mark.parametrize("n", [0, 1, -5])
    def test_degenerate_n_returns_non_positive(self, n):
        """n < 2 时无有效自由度，调用方应据此跳过 CI（而非产出虚假区间）。"""
        assert _mr_dof_eff(n) <= 0

    def test_n2_has_one_moving_range(self):
        """n=2 只有 1 个移动极差 → df_eff = 0.606（正但很小），CI 应非常宽。"""
        df = _mr_dof_eff(2)
        assert 0 < df < 1
        lo, hi = _cp_confidence_interval(1.0, 2)
        assert lo is not None and (hi - lo) > 1.0, "n=2 的 CI 应极宽（信息量极小）"

    def test_ratio_is_stable_across_n(self):
        """df_eff/(n−1) 是常数（实测 n=20..200 波动 < 0.01），这是按系数实现的依据。"""
        ratios = [_mr_dof_eff(n) / (n - 1) for n in (20, 50, 100, 200)]
        assert max(ratios) - min(ratios) < 0.01, f"df_eff/(n-1) 应恒定，实测 {ratios}"
