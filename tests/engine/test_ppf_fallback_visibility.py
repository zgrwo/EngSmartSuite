"""PPF 回退必须用户可见（审查 2026-10-09 契约 #16）。

## 缺陷

`nonparametric.py` 的 `_ppf()` 在 `dist.ppf()` 抛异常时回退经验分位数，但**只写
`logger.debug`**；而图表标题仍写「拟合=Weibull」，`messages` 为空。
用户以为看到的是**理论分布**控制限，实际是经验分位数 —— 两者在**尾部差异最大**，
而控制限（0.99865 / 0.00135 分位）恰恰落在尾部。属契约硬性要求 1 明文禁止的
「只在 debug 日志里说明的降级」（B2）。

## 怎么造出 PPF 失败

真造一个让 `dist.ppf` 抛异常的分布很难（它的失败往往是返回 nan 而非抛错），
故用 monkeypatch 把候选分布的 `ppf` 统一替换成抛异常的桩 —— 这直接测的是
"**当 PPF 失败时**引擎怎么做"，正是契约要钉住的那条行为。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _frame(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame({"y": np.random.default_rng(3).normal(50, 5, n)})


#: 控制限用到的尾部分位（与引擎一致）
_TAIL_P = (0.99865, 0.97725, 0.8413, 0.00135, 0.02275, 0.1587)


def _patch_tail_ppf_failure(monkeypatch):
    """让**尾部** PPF 失败，其余照常。

    ⚠️ 不能把 `ppf` 整体替换成抛异常的桩：`scipy` 的 `fit()` / `kstest()` 内部也会调用
    `ppf`（初值估计），整体替换会在**拟合阶段**就抛错，异常根本到不了被守卫的
    `_ppf()` —— 那样测的就不是"控制限回退"而是"拟合失败"，且任务直接 error
    （实测被这条绊过一次）。故只对控制限用到的那几个尾部分位抛错。
    """
    from smartsuite.engine.spc_charts import nonparametric as mod

    def _wrap(dist):
        real = dist.ppf

        def _tail_boom(p, *args, **kwargs):
            if p in _TAIL_P:
                raise RuntimeError("模拟尾部 PPF 不可用")
            return real(p, *args, **kwargs)

        return _tail_boom

    for name in ("weibull_min", "norm", "lognorm"):
        dist = getattr(mod.sp_stats, name, None)
        if dist is not None:
            monkeypatch.setattr(dist, "ppf", _wrap(dist), raising=False)


def _run(params: dict | None = None):
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.services.orchestrator import orchestrate

    return orchestrate(
        AnalysisRequest(
            task="spc_nonparametric",
            data=_frame(),
            target_col="y",
            feature_cols=[],
            params=params or {},
        )
    )


class TestPpfFallbackIsVisible:
    def test_healthy_run_has_no_fallback_noise(self):
        """反向噪音门禁：PPF 正常时不得出现"回退"字样。"""
        r = _run()
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert "经验分位数" not in blob, f"PPF 正常时不应有回退披露：{r.messages}"
        assert not r.metadata.get("ppf_fallback"), r.metadata

    def test_ppf_failure_is_disclosed_in_messages(self, monkeypatch):
        """PPF 全失败 → 必须在 messages 里说清"控制限已不是理论分布限"。"""
        _patch_tail_ppf_failure(monkeypatch)

        r = _run()
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages or [])
        assert "经验分位数" in blob, f"PPF 回退必须披露：{r.messages}"
        assert "不再是理论分布限" in blob or "不再是理论分布" in blob, (
            f"披露必须说明口径已改变（用户最需要知道的就是这一点）：{r.messages}"
        )
        assert "⚠" in blob

    def test_ppf_failure_is_marked_on_the_figure_title(self, monkeypatch):
        """图也要标 —— 用户看图的时间远多于看消息。

        ⚠️ 引擎用**非交互** `matplotlib.figure.Figure`（不经过 pyplot），
        故 `plt.get_fignums()` 取不到它（我第一版就是这么写的，拿到空列表）。
        改为拦截 `Axes.set_title` 记录标题文本 —— 直接验证"标题被标注了"这件事。
        """
        _patch_tail_ppf_failure(monkeypatch)

        import matplotlib
        from matplotlib.axes import Axes

        matplotlib.use("Agg")
        titles: list[str] = []
        real_set_title = Axes.set_title

        def _capture(self, label, *args, **kwargs):
            titles.append(str(label))
            return real_set_title(self, label, *args, **kwargs)

        monkeypatch.setattr(Axes, "set_title", _capture)

        r = _run()
        assert r.figures, "应产出图"
        assert any("经验分位数" in t for t in titles), (
            f"图标题必须标注回退（控制限口径已变），实际标题={titles}"
        )

    def test_metadata_flag_is_machine_readable(self, monkeypatch):
        _patch_tail_ppf_failure(monkeypatch)

        r = _run()
        assert r.metadata.get("ppf_fallback") is True, (
            f"metadata 应有机器可读的回退标记，实际 keys={sorted(r.metadata)}"
        )


class TestPpfFallbackDoesNotCrash:
    @pytest.mark.parametrize("side", ["upper", "lower", "two-sided"])
    def test_all_sides_survive_ppf_failure(self, monkeypatch, side):
        _patch_tail_ppf_failure(monkeypatch)

        r = _run({"side": side})
        assert r.status == "ok", f"side={side}: {r.messages}"
        assert r.metadata.get("ppf_fallback") is True
