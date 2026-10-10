"""跨环境/跨版本健壮性 —— 远端 CI 分叉暴露的两类**环境耦合失败**（2026-10-10）。

这两条都不是本机（Windows + 最新 scipy/sklearn + 有中文字体）能复现的，
而是远端 CI 的三条腿分别暴露出来的：

## ① 旧 scipy 上 A-D 的**开区间契约失效**（py3.10 分叉；CI `quick` + `quality`）

`scipy < 1.16` 的 `anderson()` 既没有 `pvalue` 字段、也不接受 `method="interpolate"`。
原实现落到 `ad_p = None` 并渲染「（p 需查表）」—— 于是 **P1-9 的"表外必须写成开区间、
不得把钳制端点当真 p"在旧 scipy 上失效**，同一份数据在新旧环境给出两套口径
（实测分叉上 `stat=14.948` → 「p 需查表」，而本机 → 「p≤0.01」）。
修法：用**临界值表**推两端边界（只推超出表范围的两端，表内仍标"需查表"，不伪造精确 p）。

## ② sklearn `ConvergenceWarning` 把"未完全收敛"变成"引擎缺陷"（`quality` 覆盖率腿）

CV 估计器未收敛时 sklearn 发 `ConvergenceWarning`；在 `-W error` 口径下它变成异常逃出
引擎，被 orchestrator 兜底成「未归类的异常」——**把 B3 近似错误归因成引擎缺陷/数据异常**。
修法：就地 `catch_warnings(record=True)` 捕获并**披露**（不静默、也不当失败）。

> 两类问题的共同教训：**"只在本机能过"的测试等于没有测试**。
> 本文件的用例都显式构造出远端的环境条件（旧 scipy 签名 / 强制告警），
> 而不是依赖跑测机器的字体、库版本。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

# ── ① 旧 scipy 的 A-D 开区间 ──────────────────────────────────────────────


class _LegacyAndersonResult:
    """复刻 `scipy < 1.16` 的返回值：**没有** `pvalue` 字段。"""

    def __init__(self, real):
        self.statistic = real.statistic
        self.critical_values = real.critical_values
        self.significance_level = real.significance_level


def _patch_legacy_anderson(monkeypatch):
    """让 `scipy.stats.anderson` 表现得像旧版（无 `pvalue`、不认 `method=`）。

    ⚠️ 真实调用必须**屏蔽 `FutureWarning`**：现代 scipy(≥1.17) 在不传 `method=` 时会告警
    「users must choose a p-value calculation method…」，而 pytest 的
    `filterwarnings=["error"]` 把它变成异常 → 外层 except → 渲染成 `N/A`
    （我第一版就是这么写的，实测把"旧 scipy 行为"测成了"异常兜底"）。
    **真实的旧 scipy 根本没有这条告警**，故模拟时必须忽略它 —— 否则测的不是代码而是环境噪音。
    """
    from scipy import stats as sp_stats

    real = sp_stats.anderson

    def _legacy(d, dist="norm", **kwargs):
        if "method" in kwargs:
            raise TypeError("anderson() got an unexpected keyword argument 'method'")
        with warnings.catch_warnings():
            # 旧 scipy 无此告警；它只是"我们正站在新 scipy 上模拟旧行为"的产物
            warnings.simplefilter("ignore", FutureWarning)
            return _LegacyAndersonResult(real(d, dist=dist))

    monkeypatch.setattr(sp_stats, "anderson", _legacy)
    return real


class TestAndersonDarlingOpenIntervalOnLegacyScipy:
    """旧 scipy 上同样不得伪造精确 p，且**两端开区间必须与新版一致**。"""

    @staticmethod
    def _ad_cell(y: np.ndarray) -> str:
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        r = orchestrate(
            AnalysisRequest(
                task="normality_check",
                data=pd.DataFrame({"y": y}),
                target_col="y",
                feature_cols=[],
                params={},
            )
        )
        assert r.status == "ok", r.messages
        return str(r.tables["normality_results"]["Anderson-Darling"].iloc[0])

    def test_extreme_non_normal_reports_open_interval_lo(self, monkeypatch):
        _patch_legacy_anderson(monkeypatch)
        rng = np.random.default_rng(3)
        ad = self._ad_cell(rng.normal(0, 1, 200) ** 3)
        assert "≤0.01" in ad or "<0.01" in ad, f"旧 scipy 上应给出下界开区间，实际 {ad!r}"

    def test_well_behaved_normal_reports_open_interval_hi(self, monkeypatch):
        _patch_legacy_anderson(monkeypatch)
        rng = np.random.default_rng(3)
        ad = self._ad_cell(rng.normal(0, 1, 200))
        assert "≥0.15" in ad or ">0.15" in ad, f"旧 scipy 上应给出上界开区间，实际 {ad!r}"

    def test_legacy_and_modern_agree_outside_the_table(self, monkeypatch):
        """**跨版本口径一致性**只对**表外**成立 —— 这条是本次修复的核心不变式。

        表外：两端开区间是"从临界值表就能确定"的结论，新旧 scipy 必须**逐字一致**。
        表内：新版能插值出精确 p，旧版**结构上做不到**（无 `pvalue`）→ 只能标"需查表"。
        要求表内也一致是**不合理的强求**（会逼实现去伪造一个插值值），故分开断言。

        ⚠️ 数据集**必须真的落在表外**（scipy 的 norm 临界值表 ≈ [0.559 … 1.031]）：
        我第一版用 n=200 的正态当"表外上界"，实测 stat≈0.917 落在**表内**，
        断言因此失败 —— 现在改为数据驱动判定，并显式要求"至少一个表外样本"，
        防止用例退化成空转。
        """
        rng = np.random.default_rng(11)
        cases = [
            rng.normal(0, 1, 200) ** 3,  # 极端重尾：stat ≫ 表上界
            rng.normal(0, 1, 5000),  # 大样本标准正态：stat ≪ 表下界
        ]
        modern = [self._ad_cell(y) for y in cases]

        _patch_legacy_anderson(monkeypatch)
        legacy = [self._ad_cell(y) for y in cases]

        n_outside = 0
        for m, legacy_cell in zip(modern, legacy, strict=True):
            if "参考值" in m:
                # 表内：旧版结构上无法插值 —— 允许"需查表"，但**绝不允许伪造精确 p**
                assert "需查表" in legacy_cell, f"表内应标「需查表」，实际 {legacy_cell!r}"
            else:
                n_outside += 1
                assert m == legacy_cell, (
                    "表外口径在新旧 scipy 上必须逐字一致（P1-9 开区间契约）：\n"
                    f"  modern={m!r}\n  legacy={legacy_cell!r}"
                )
        assert n_outside >= 1, f"没有样本落在临界值表外 —— 本用例退化为空转（modern={modern}）"

    def test_legacy_in_table_says_needs_table_not_a_fake_p(self, monkeypatch):
        """表内：旧 scipy 必须**明说需要查表**，不得伪造精确 p（P1-9 的底线）。"""
        _patch_legacy_anderson(monkeypatch)
        rng = np.random.default_rng(11)
        rng.normal(0, 1, 200) ** 3  # 保持与上一条相同的随机序列位置
        ad = self._ad_cell(rng.normal(0, 1, 200))
        # stat 落在临界值表内部（实测 ≈0.917 ∈ (0.559, 1.031)）
        assert "需查表" in ad, f"表内应标「需查表」，实际 {ad!r}"
        assert "参考值" not in ad, f"旧 scipy 不得伪造精确 p：{ad!r}"

    def test_never_fakes_a_precise_p_outside_table(self, monkeypatch):
        """反向断言：表外**不得**出现精确 p 值（这才是 P1-9 要防的）。"""
        _patch_legacy_anderson(monkeypatch)
        rng = np.random.default_rng(3)
        ad = self._ad_cell(rng.normal(0, 1, 200) ** 3)
        assert "参考值" not in ad, f"表外不得给出精确 p：{ad!r}"


# ── ② sklearn ConvergenceWarning ────────────────────────────────────────────


class TestConvergenceWarningIsDisclosedNotFatal:
    """未收敛是 **B3 近似**，必须"出结果 + 披露"，不得变成"引擎缺陷"。"""

    @staticmethod
    def _frame():
        rng = np.random.default_rng(7)
        return pd.DataFrame(
            {
                "y": rng.normal(50, 5, 80) + 0.3 * rng.normal(0, 1, 80),
                "x1": rng.normal(0, 1, 80),
                "x2": rng.normal(0, 1, 80),
            }
        )

    @pytest.fixture
    def noisy_lasso(self, monkeypatch):
        """让 `LassoCV.fit` 必定发一次 `ConvergenceWarning`（复刻分叉上的真实情形）。"""
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LassoCV

        real_fit = LassoCV.fit

        def _fit(self, X, y, **kwargs):  # noqa: N803 — 复刻 sklearn 的签名（大写 X）
            warnings.warn("Objective did not converge.", ConvergenceWarning, stacklevel=1)
            return real_fit(self, X, y, **kwargs)

        monkeypatch.setattr(LassoCV, "fit", _fit)
        return ConvergenceWarning

    @pytest.mark.parametrize("policy", ["default", "error"])
    def test_result_is_ok_under_both_warning_policies(self, noisy_lasso, policy):
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        with warnings.catch_warnings():
            warnings.simplefilter(policy)
            # 与 pyproject.toml 一致：字体/layout 告警是环境噪音，不是本用例要测的东西
            warnings.filterwarnings("ignore", message=r"Glyph .* missing from font")
            warnings.filterwarnings("ignore", message=r"Tight layout not applied")
            r = orchestrate(
                AnalysisRequest(
                    task="lasso_regression",
                    data=self._frame(),
                    target_col="y",
                    feature_cols=["x1", "x2"],
                    params={},
                )
            )
        assert r.status == "ok", (
            f"[{policy} 口径] 未收敛告警不得让分析失败（那是错误归因）：{r.messages}"
        )
        blob = " ".join(r.messages or [])
        assert "未完全收敛" in blob, f"[{policy} 口径] 必须披露未收敛：{r.messages}"
        assert "B3 近似" in blob, f"披露应说明这是近似而非失败：{blob}"
        assert r.metadata["converged"] is False

    def test_silent_when_no_warning(self):
        """反向噪音门禁：正常收敛时不得出现"未完全收敛"字样。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        r = orchestrate(
            AnalysisRequest(
                task="lasso_regression",
                data=self._frame(),
                target_col="y",
                feature_cols=["x1", "x2"],
                params={},
            )
        )
        assert r.status == "ok", r.messages
        assert not any("未完全收敛" in str(m) for m in (r.messages or [])), r.messages
        assert r.metadata["converged"] is True

    def test_single_disclosure_channel(self, noisy_lasso):
        """只有一条披露通道 —— 防止"两个机制各报一次"（我第一版就是双通道）。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        r = orchestrate(
            AnalysisRequest(
                task="lasso_regression",
                data=self._frame(),
                target_col="y",
                feature_cols=["x1", "x2"],
                params={},
            )
        )
        n = sum(1 for m in (r.messages or []) if "未完全收敛" in str(m) or "未收敛" in str(m))
        assert n == 1, f"未收敛只应披露一次，实际 {n} 条：{r.messages}"
