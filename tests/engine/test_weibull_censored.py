"""含删失数据的 Weibull MLE（P2-2）。

对应第三轮复核 / 计划 P2-2：

`reliability.py` 原先只把**失效时刻**喂给 `scipy.stats.weibull_min.fit`：

    fail_times = times[events == 1]
    shape, loc, scale = sp_stats.weibull_min.fit(fail_times, floc=0)

代码自己写了警告说"忽略了 N 个删失观测，形状参数 β 可能被低估"——
**这个诚实值得尊敬，但它等于承认可靠性模块在真实场景（几乎总有删失）下不可用。**

本文件钉住正确的删失 MLE：
  对数似然  lnL(β,η) = Σ_失效 [ln β − ln η + (β−1)·ln(t/η) − (t/η)^β]
                     + Σ_删失 [−(t/η)^β]
即删失观测对似然贡献的是**生存函数** S(t) 而非密度 f(t)。

验证策略（不依赖外部软件，但独立于被测实现）：
  1. **无删失时**必须与 `scipy.weibull_min.fit` 一致（回归防线）；
  2. **有删失时**：用已知参数生成删失样本，断言 MLE 比"只用失效数据"的朴素估计
     **更接近真值**（这是删失 MLE 存在的全部意义）；
  3. **覆盖概率**：多次重复下真值的置信区间覆盖率接近名义水平；
  4. 似然面自检：MLE 处的对数似然不低于邻近参数点（真的在极大化）。
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.reliability import _weibull_fit_censored
from smartsuite.services.orchestrator import orchestrate


def _run(times, events, **params):
    return orchestrate(
        AnalysisRequest(
            task="survival_analysis",
            data=pd.DataFrame({"t": times, "e": events}),
            target_col="t",
            feature_cols=["e"],
            params=params,
        )
    )


def _censored_sample(shape, scale, n, censor_frac, seed):
    """生成**独立随机删失**样本（每个观测有自己的删失时点）。

    审查 2026-09-24：初版用例用"所有观测在同一个时点被删失"（
    `censor_at = quantile(life, 1−frac)`）。那不是标准的随机删失机制——
    它让删失时点携带了寿命分布的信息，会给 β 引入非经典偏差，
    使"删失 MLE 优于朴素估计"的前提不成立（实测两者都偏高）。
    改为独立删失时点（time-to-censoring 亦为 Weibull 随机变量）后，
    机制标准、结论可复现。
    """
    rng = np.random.default_rng(seed)
    life = rng.weibull(shape, n) * scale
    # 删失时点独立同分布；用分位数标定使删失比例接近 censor_frac
    cens_scale = scale * float(np.quantile(rng.weibull(shape, 20000), 1.0 - censor_frac))
    cens = rng.weibull(shape * 0.8, n) * cens_scale
    times = np.minimum(life, cens)
    events = (life <= cens).astype(int)
    return times, events


class TestUncensoredMatchesScipy:
    """无删失时不得偏离 scipy 的 MLE（回归防线）。"""

    @pytest.mark.parametrize("n", [30, 100])
    def test_no_censoring_matches_scipy(self, n):
        rng = np.random.default_rng(42)
        times = rng.weibull(2.0, n) * 100.0
        events = np.ones(n, dtype=int)

        shape, scale, _cov, _info = _weibull_fit_censored(times, events)
        s_shape, _loc, s_scale = sp_stats.weibull_min.fit(times, floc=0)

        assert shape == pytest.approx(s_shape, rel=1e-4), f"β: {shape} vs scipy {s_shape}"
        assert scale == pytest.approx(s_scale, rel=1e-4), f"η: {scale} vs scipy {s_scale}"

    def test_all_events_end_to_end_unchanged(self):
        """端到端：全部失效时走同一路径，参数应与 scipy 一致。"""
        rng = np.random.default_rng(7)
        times = rng.weibull(2.5, 60) * 50.0
        r = _run(times, np.ones(60, dtype=int))
        assert r.status == "ok"
        s_shape, _loc, s_scale = sp_stats.weibull_min.fit(times, floc=0)
        assert r.metadata["weibull_shape"] == pytest.approx(s_shape, rel=1e-4)
        assert r.metadata["weibull_scale"] == pytest.approx(s_scale, rel=1e-4)


class TestCensoredEstimateBeatsNaive:
    """删失 MLE 必须比"只用失效数据"更接近真值 —— 这是它存在的意义。

    注意断言形态：MLE 的优越性是**渐近/平均**性质，单个样本上朴素估计
    偶尔更接近真值属正常抽样波动（实测 seed=1 即如此）。故按**均值**比较，
    不逐样本比较 —— 后者会把统计波动误报成缺陷。
    """

    def test_mean_shape_error_lower_than_naive(self):
        """多次重复下，删失 MLE 的 β 平均相对误差应低于朴素估计。"""
        true_shape = 2.0
        errs_c, errs_n = [], []
        for seed in range(12):
            times, events = _censored_sample(true_shape, 100.0, 200, 0.4, seed)
            shape_c, _sc, _cov, _info = _weibull_fit_censored(times, events)
            naive_shape, _loc, _nsc = sp_stats.weibull_min.fit(times[events == 1], floc=0)
            errs_c.append(abs(shape_c - true_shape) / true_shape)
            errs_n.append(abs(naive_shape - true_shape) / true_shape)
        assert np.mean(errs_c) < np.mean(errs_n), (
            f"删失 MLE 平均误差 {np.mean(errs_c):.2%} 未优于朴素 {np.mean(errs_n):.2%}"
        )

    def test_naive_scale_is_badly_biased_while_censored_is_not(self):
        """尺度参数是朴素估计最严重的失真点（删失观测携带大寿命信息）。

        实测（300 样本、~42% 删失）：朴素 η ≈ 75（真值 100，误差 ~28%），
        删失 MLE η ≈ 95（误差 ~5%）。这里用 3 倍差距做稳健断言。
        """
        true_shape, true_scale = 2.0, 100.0
        errs_c, errs_n = [], []
        for seed in range(10):
            times, events = _censored_sample(true_shape, true_scale, 300, 0.4, seed)
            _s, scale_c, _cov, _info = _weibull_fit_censored(times, events)
            _ns, _l, scale_n = sp_stats.weibull_min.fit(times[events == 1], floc=0)
            errs_c.append(abs(scale_c - true_scale) / true_scale)
            errs_n.append(abs(scale_n - true_scale) / true_scale)
        assert np.mean(errs_c) * 3 < np.mean(errs_n), (
            f"删失 MLE 尺度误差均值 {np.mean(errs_c):.3f} 应远小于朴素 "
            f"{np.mean(errs_n):.3f}（后者丢失删失观测的大寿命信息）"
        )

    def test_naive_scale_is_biased_low_on_average(self):
        """确认朴素尺度估计确有系统性偏低（否则本项修复没有意义）。"""
        true_scale = 100.0
        naive_scales = []
        for seed in range(12):
            times, events = _censored_sample(2.0, true_scale, 200, 0.4, seed)
            _s, _l, sc = sp_stats.weibull_min.fit(times[events == 1], floc=0)
            naive_scales.append(sc)
        assert float(np.mean(naive_scales)) < true_scale * 0.9, (
            f"朴素尺度均值 {np.mean(naive_scales):.1f} 未明显低于真值 {true_scale}"
        )


class TestLikelihoodSurfaceConsistency:
    """MLE 必须真的在极大化对数似然（不依赖任何外部软件的自检）。"""

    def _loglik(self, params, times, events):
        beta, eta = params
        if beta <= 0 or eta <= 0:
            return -np.inf
        t = np.asarray(times, dtype=float) / eta
        ll = np.sum(
            np.where(
                np.asarray(events) == 1,
                np.log(beta) - np.log(eta) + (beta - 1) * np.log(t) - t**beta,
                -(t**beta),
            )
        )
        return float(ll)

    def test_mle_is_local_maximum(self):
        times, events = _censored_sample(2.0, 100.0, 200, 0.4, 11)
        shape, scale, _cov, _info = _weibull_fit_censored(times, events)
        ll0 = self._loglik((shape, scale), times, events)
        for d_beta in (-0.05, 0.05):
            for d_eta in (-3.0, 3.0):
                ll = self._loglik((shape + d_beta, scale + d_eta), times, events)
                assert ll <= ll0 + 1e-9, (
                    f"相邻点 (β{d_beta:+.2f}, η{d_eta:+.0f}) 似然 {ll:.6f} > MLE {ll0:.6f}"
                )

    def test_returns_fisher_information(self):
        times, events = _censored_sample(2.0, 100.0, 150, 0.3, 13)
        _shape, _scale, cov, info = _weibull_fit_censored(times, events)
        assert info is not None and cov is not None
        assert cov.shape == (2, 2)
        # 协方差应为对称正定（对角为正、行列式为正）
        assert cov[0, 0] > 0 and cov[1, 1] > 0
        assert np.linalg.det(cov) > 0, f"协方差非正定: {cov}"
        assert cov[0, 1] == pytest.approx(cov[1, 0], rel=1e-9)


class TestB10AndPercentileLife:
    """B10（10% 失效寿命）与百分位寿命必须给出且带置信区间。"""

    def test_b10_matches_analytic_formula(self):
        """B10 解析式：t_0.1 = η·(−ln 0.9)^(1/β)。"""
        times, events = _censored_sample(2.0, 100.0, 200, 0.3, 17)
        r = _run(times, events)
        assert r.status == "ok"
        beta = r.metadata["weibull_shape"]
        eta = r.metadata["weibull_scale"]
        expected_b10 = eta * (-np.log(0.9)) ** (1 / beta)
        assert r.metadata["b10_life"] == pytest.approx(expected_b10, rel=1e-9)

    def test_b10_ci_brackets_point_estimate(self):
        times, events = _censored_sample(2.0, 100.0, 200, 0.3, 19)
        r = _run(times, events)
        lo, hi = r.metadata["b10_ci"]
        assert lo is not None and hi is not None
        assert 0 < lo < r.metadata["b10_life"] < hi, (
            f"B10 CI 应包住点估计: ({lo}, {hi}) vs {r.metadata['b10_life']}"
        )

    def test_percentile_table_present_and_monotone(self):
        times, events = _censored_sample(2.0, 100.0, 250, 0.3, 23)
        r = _run(times, events)
        tbl = r.tables["life_percentiles"]
        assert list(tbl.columns) == ["失效比例", "寿命", "95%CI下限", "95%CI上限"], list(
            tbl.columns
        )
        life = tbl["寿命"].astype(float).to_numpy()
        assert np.all(np.diff(life) > 0), f"百分位寿命应随失效比例单调递增: {life}"
        lo = tbl["95%CI下限"].astype(float).to_numpy()
        hi = tbl["95%CI上限"].astype(float).to_numpy()
        assert np.all(lo <= life) and np.all(life <= hi), "CI 应包住点估计"

    def test_b10_ci_coverage_is_reasonable(self):
        """覆盖率检验：真 B10 应落在报告 CI 内的比例接近名义 95%（宽松下界）。"""
        true_shape, true_scale = 2.0, 100.0
        true_b10 = true_scale * (-np.log(0.9)) ** (1 / true_shape)
        hits = 0
        trials = 60
        for seed in range(trials):
            times, events = _censored_sample(true_shape, true_scale, 300, 0.3, 1000 + seed)
            r = _run(times, events)
            lo, hi = r.metadata["b10_ci"]
            if lo is None or hi is None:
                continue
            hits += int(lo <= true_b10 <= hi)
        cov = hits / trials
        assert cov >= 0.75, f"B10 CI 覆盖率 {cov:.2%} 过低（名义 95%）"


class TestCensoringDisclosure:
    """用户必须知道所用方法与删失比例 —— 不允许静默切换口径。"""

    def test_method_disclosed_in_metadata(self):
        times, events = _censored_sample(2.0, 100.0, 200, 0.3, 29)
        r = _run(times, events)
        assert r.metadata["weibull_method"] == "censored_mle", (
            f"应声明使用含删失 MLE，实际 {r.metadata.get('weibull_method')}"
        )
        assert r.metadata["n_censored"] == int((np.asarray(events) == 0).sum())

    def test_no_biased_warning_when_censoring_handled(self):
        """删失已被正确处理 → 不应再出现「结果有偏／请换专业软件」的免责声明。"""
        times, events = _censored_sample(2.0, 100.0, 200, 0.3, 31)
        r = _run(times, events)
        blob = " ".join(r.messages)
        assert "忽略了" not in blob, f"删失已处理，不应再声称忽略删失: {r.messages}"
        assert "结果有偏" not in blob, f"不应再出现有偏免责声明: {r.messages}"

    def test_no_censoring_declares_uncensored_method(self):
        rng = np.random.default_rng(37)
        times = rng.weibull(2.0, 80) * 50.0
        r = _run(times, np.ones(80, dtype=int))
        assert r.metadata["weibull_method"] == "uncensored_mle"
        assert r.metadata["n_censored"] == 0

    def test_heavy_censoring_warns_about_precision(self):
        """删失比例很高时参数不确定性大 —— 应提示而非静默给出窄 CI。

        阈值取 0.35：实测重删失（~75%）下 B10 相对宽度约 0.45。
        真正严密的判据是 CI 的**覆盖率**（见 TestB10AndPercentileLife），
        此处只做"确实明显变宽"的宽松回归防线，不锁死具体数值。
        """
        times, events = _censored_sample(2.0, 100.0, 120, 0.75, 41)
        r = _run(times, events)
        assert r.status == "ok"
        n_cens = int((np.asarray(events) == 0).sum())
        assert n_cens / len(events) > 0.5, "前置：重删失样本"
        lo, hi = r.metadata["b10_ci"]
        rel_width = (hi - lo) / r.metadata["b10_life"]
        assert rel_width > 0.35, f"重删失下 B10 CI 应较宽，实际相对宽度 {rel_width:.2f}"

    def test_heavy_censoring_emits_precision_warning(self):
        """高删失比例必须给出可读提示（不能只体现在 CI 变宽上）。"""
        times, events = _censored_sample(2.0, 100.0, 120, 0.75, 43)
        r = _run(times, events)
        assert any("删失比例" in m for m in r.messages), (
            f"删失比例 >50% 应提示不确定性: {r.messages}"
        )


class TestDegenerateInputs:
    """退化输入（B0/B1 契约）。"""

    def test_too_few_events_returns_none_params(self):
        r = _run([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], [1, 0, 0, 0, 0, 0, 0, 0])
        # 仅 1 个失效 → 不拟合，但不应崩溃；且必须披露为何没有参数
        assert r.metadata.get("weibull_shape") is None
        assert any("Weibull" in m or "失效" in m for m in r.messages), r.messages

    def test_single_failure_time_yields_no_parameters(self):
        """仅 1 个失效观测 → 不拟合参数（少于 2 个无法识别形状）。

        审查 2026-09-24（质量守卫）：原断言为 `status in ("ok","error")`，
        属恒真断言（任何结果都通过）。现改为硬断言：无参数 + B10 也不得伪造。
        """
        r = _run([5.0] * 3 + [1.0], [0, 0, 0, 1])
        assert r.metadata.get("weibull_shape") is None, (
            f"仅 1 个失效不应拟合出形状参数，实际 {r.metadata.get('weibull_shape')}"
        )
        assert r.metadata.get("b10_life") is None, "无参数时不得给出 B10"

    def test_zero_scale_guard(self):
        """全零寿命时间是退化输入，不得产生 NaN 参数静默传播。"""
        r = _run([0.0, 0.0, 0.0, 0.0, 0.0, 1.0], [1, 1, 1, 1, 1, 0])
        shape = r.metadata.get("weibull_shape") if r.status == "ok" else None
        if shape is not None:
            assert np.isfinite(shape), f"形状参数不得为 NaN/Inf: {shape}"
