"""边界契约回归测试（B0–B3）— 见 docs/governance/boundary-contract.md。

覆盖第三轮复核（logs/reports/verify-round3/R3-复核清单.md）确认的 P0/P1 缺陷：

  P0-1  spc_xbar 子组 n≥380 时 math.gamma 溢出 → 崩溃 + 误报「数据中可能存在极端值」
  P0-4  compare_digest 遇非 ASCII token 抛 TypeError → 500 HTML
  P1-6  ±Inf 清洗覆盖不全，且被误归因为「常量列（标准差为 0）」

所有用例在修复前为红（先写测试 → 修复 → 转绿）。
"""

import ast
import inspect
import re
import secrets
import textwrap
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.spc_charts.we_rules import _xbar_s_constants, c4
from smartsuite.services.orchestrator import orchestrate

_ENGINE = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "engine"


# ══════════════════════════════════════════════════════════════
# c4 原语：精度与数值稳定性（ASTM 表 + 独立 lgamma 路径）
# ══════════════════════════════════════════════════════════════


class TestC4Primitive:
    """`c4()` 是独立的公共原语，其数值契约单独钉住。"""

    # ASTM E2587 / Montgomery 附录表（四位小数）——外部参考值
    _ASTM_C4 = {
        2: 0.7979,
        3: 0.8862,
        4: 0.9213,
        5: 0.9400,
        6: 0.9515,
        7: 0.9594,
        8: 0.9650,
        9: 0.9693,
        10: 0.9727,
        15: 0.9823,
        20: 0.9869,
        25: 0.9896,
    }

    @pytest.mark.parametrize("n,expected", sorted(_ASTM_C4.items()))
    def test_matches_astm_table(self, n, expected):
        """与 ASTM/Montgomery 附录表一致，误差不超过表的四位小数精度。"""
        assert c4(n) == pytest.approx(expected, abs=5e-5)

    def test_matches_independent_lgamma_path_for_all_sizes(self):
        """与独立 lgamma 对数域路径逐值一致（相对误差 < 1e-13）。

        这是"同一结果的两条独立计算路径"——比查表更能钉住大 n 区间。
        """
        import math

        for n in (2, 3, 5, 10, 25, 50, 100, 200, 379, 400, 1000, 5000, 20000):
            ref = math.exp(
                0.5 * math.log(2.0 / (n - 1)) + math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0)
            )
            assert c4(n) == pytest.approx(ref, rel=1e-13), f"n={n}"

    def test_monotonic_increasing_and_converges_to_one(self):
        vals = [c4(n) for n in (2, 5, 10, 25, 100, 1000, 5000, 20000)]
        assert all(b > a for a, b in zip(vals, vals[1:], strict=False)), vals
        assert vals[-1] == pytest.approx(1.0, abs=1e-4)

    def test_no_overflow_at_extreme_n(self):
        """回归防线：原 math.gamma 实现在 n=380 即 OverflowError。"""
        for n in (380, 400, 5000, 100_000):
            val = c4(n)
            assert np.isfinite(val), f"n={n} 溢出"
            assert 0.0 < val <= 1.0


# ══════════════════════════════════════════════════════════════
# P0-1  c4 数值稳定性：math.gamma 在 n≥380 溢出
# ══════════════════════════════════════════════════════════════


class TestC4NumericStability:
    """c4 计算必须在大子组下保持有限、精确、不崩溃。"""

    @pytest.mark.parametrize("n", [2, 3, 5, 10, 25, 50, 100, 200, 379, 380, 400, 1000, 5000])
    def test_c4_is_finite_and_bounded(self, n):
        """任何 n≥2 都必须返回有限 c4，且 0 < c4 < 1（c4 是 σ 的无偏修正因子）。"""
        c4, a3, b3, b4 = _xbar_s_constants(n)
        assert np.isfinite(c4), f"n={n}: c4={c4} 非有限"
        assert 0.0 < c4 < 1.0, f"n={n}: c4={c4} 越界 (0,1)"
        assert np.isfinite(a3) and a3 > 0, f"n={n}: A3={a3} 非正或非有限"
        assert np.isfinite(b3) and np.isfinite(b4) and b4 > b3, f"n={n}: B3/B4 非法"

    @pytest.mark.parametrize("n", [2, 5, 10, 25, 100, 400, 5000])
    def test_c4_matches_independent_lgamma_path(self, n):
        """与独立 lgamma 对数域路径一致（相对误差 < 1e-12）。

        独立路径：ln c4 = 0.5*ln(2/(n-1)) + lgamma(n/2) - lgamma((n-1)/2)
        """
        import math

        c4 = _xbar_s_constants(n)[0]
        ref = math.exp(
            0.5 * math.log(2.0 / (n - 1)) + math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0)
        )
        assert c4 == pytest.approx(ref, rel=1e-12), f"n={n}: {c4} vs {ref}"

    def test_c4_converges_to_one(self):
        """n→∞ 时 c4→1（理论上限），且单调递增。"""
        prev = 0.0
        for n in (10, 50, 200, 1000, 5000):
            c4 = _xbar_s_constants(n)[0]
            assert c4 > prev, f"n={n}: c4 未单调递增"
            prev = c4
        assert prev == pytest.approx(1.0, abs=1e-4)

    @pytest.mark.parametrize("n_sub", [380, 400, 500])
    def test_xbar_chart_large_subgroup_does_not_crash(self, n_sub):
        """端到端：单一子组含 n 个同 X 值观测时，X-bar 图必须可用（不得崩溃）。"""
        rng = np.random.default_rng(1)
        df = pd.DataFrame({"日期": ["D1"] * n_sub, "测量": rng.normal(10, 0.5, n_sub)})
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar", data=df, target_col="测量", feature_cols=["日期"], params={}
            )
        )
        assert r.status == "ok", f"n={n_sub} 应可出图，实际: {r.status} / {r.messages}"
        # 数值契约：子组大小如实上报、控制限有限且有序、走 S 图分支
        assert r.metadata["subgroup_size"] == n_sub
        assert r.metadata["chart_type"] == "xbar_s"
        cl, ucl, lcl = r.metadata["xbar_mean"], r.metadata["ucl_x"], r.metadata["lcl_x"]
        assert all(np.isfinite(v) for v in (cl, ucl, lcl)), f"控制限非有限: {cl},{ucl},{lcl}"
        assert ucl > cl > lcl
        assert r.metadata["sigma_xbar"] > 0

    @pytest.mark.parametrize("n_sub", [400])
    def test_large_subgroup_error_never_blames_extreme_values(self, n_sub):
        """错误归因防线：大子组问题的提示不得指向「极端值」或「数据范围」。

        同时硬断言分析**成功**（修复后 n=400 应正常出图）——若将来回归为报错，
        必须报出与"子组大小"相关的正确原因，而不是"极端值"。
        """
        rng = np.random.default_rng(1)
        df = pd.DataFrame({"日期": ["D1"] * n_sub, "测量": rng.normal(10, 0.5, n_sub)})
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar", data=df, target_col="测量", feature_cols=["日期"], params={}
            )
        )
        blob = " ".join(r.messages)
        assert "极端值" not in blob, f"错误归因（归咎数据范围）: {r.messages}"
        assert r.status == "ok", f"n={n_sub} 应正常出图: {r.messages}"
        # 真实数值断言：控制限必须围绕数据均值，且子组大小如实报告
        assert r.metadata["subgroup_size"] == n_sub
        cl = float(r.metadata["xbar_mean"])
        assert cl == pytest.approx(float(df["测量"].mean()), abs=1e-3)
        assert r.metadata["ucl_x"] > cl > r.metadata["lcl_x"]
        # 大子组应走 S 图（n>25），且 S 控制限非负
        assert r.metadata["chart_type"] == "xbar_s"
        assert r.metadata["s_bar"] > 0
        assert r.metadata["lcl_s"] >= 0


# ══════════════════════════════════════════════════════════════
# P0-4  CSRF token 比较：非 ASCII 不得抛 TypeError
# ══════════════════════════════════════════════════════════════


class TestCsrfTokenComparison:
    """require_csrf 必须在任意 token 字节序列下返回 403，而非抛异常。"""

    @pytest.mark.parametrize("token", ["é", "中", "中文token", "\u00ff", "ab\u4e2d"])
    def test_non_ascii_token_is_rejected_not_crashed(self, token):
        """复现：secrets.compare_digest 对非 ASCII str 抛 TypeError。"""
        # 先证明底层 API 的行为（这是缺陷来源）
        with pytest.raises(TypeError):
            secrets.compare_digest(token, "x" * 8)

        # 契约：应用层必须把它变成 403，而不是传播异常
        from smartsuite.web.app import app

        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post(
                "/api/analyze",
                json={"task": "normality_check", "targets": ["a"]},
                headers={"X-CSRF-Token": token},
            )
        assert resp.status_code == 403, (
            f"非 ASCII token 应返回 403，实际 {resp.status_code} "
            f"({resp.headers.get('Content-Type')})"
        )
        assert resp.headers.get("Content-Type", "").startswith("application/json"), (
            "API 路径必须返回 JSON"
        )


# ══════════════════════════════════════════════════════════════
# P1-6  ±Inf 处理与错误归因
# ══════════════════════════════════════════════════════════════

_INF_TASKS = [
    ("spc_cusum", {"task": "spc_cusum", "target_col": "v", "params": {"group_col": "g"}}),
    ("spc_xbar", {"task": "spc_xbar", "target_col": "v", "feature_cols": ["g"]}),
    ("spc_ewma", {"task": "spc_ewma", "target_col": "v", "params": {"group_col": "g"}}),
    (
        "process_capability",
        {"task": "process_capability", "target_col": "v", "params": {"usl": 3.0, "lsl": -1.0}},
    ),
]


def _inf_frame(n_per_group: int = 20) -> pd.DataFrame:
    """单组数据，含一个 +Inf —— σ 不可算，但数据并非常量。"""
    rng = np.random.default_rng(2)
    vals = list(rng.normal(1.0, 0.1, n_per_group - 1)) + [np.inf]
    return pd.DataFrame({"v": vals, "g": ["A"] * n_per_group})


def _run_with_warning_policy(req_kwargs: dict, policy: str):
    """在指定 warnings 过滤器下跑一次分析。

    ⚠️ **为什么必须显式设口径**（本文件最重要的一课，P0-6）：
    `pyproject.toml` 的 `filterwarnings = ["error", ...]` **只作用于 pytest**，
    生产（Web/CLI）不会把 numpy/pandas/scipy 的 `RuntimeWarning` 升为异常。
    于是**同一退化输入在 pytest 下走「异常兜底」分支、在生产下才走真实分支**：

        生产  → 「所有分组标准差均为零（常量数据）」（错误归因，守卫本该抓到）
        pytest → 「分析执行失败…（成因未归类）」（不含"常量"，**否定式断言空过**）

    即：一条*否定式*断言（`"常量" not in blob`）在 CI 里是**零信息**的 ——
    任何"更泛化的错误"都能满足它。本文件因此改为**正向断言**，
    并显式声明生产口径（与 `tests/guards/test_micro_scale_guards.py:252`、
    `tests/engine/test_edge_cases.py:850` 的既有做法一致）。
    """
    with warnings.catch_warnings():
        warnings.simplefilter(policy)
        return orchestrate(AnalysisRequest(data=_inf_frame(), **req_kwargs))


class TestInfNotBlamedAsConstant:
    """含 ±Inf 的数据：必须**如实披露剔除**，且不得被报告为「常量列」。

    这组用例同时是 P0-6「守卫假绿」的修复：原断言为否定式
    （`"常量" not in blob`）且被 warnings-as-errors 改变了代码路径，
    在 CI 里**必然通过**（实测：`-W ignore` 下同一条用例才 FAIL）。
    """

    @pytest.mark.parametrize("label,req_kwargs", _INF_TASKS, ids=[t[0] for t in _INF_TASKS])
    def test_inf_is_disclosed_and_never_blamed_as_constant(self, label, req_kwargs):
        """正向断言：含 +Inf 时**必须出现**「非有限值」披露（而非仅仅"没有说常量"）。"""
        r = _run_with_warning_policy(req_kwargs, "default")
        blob = " ".join(r.messages or [])
        assert "常量" not in blob and "标准差为 0" not in blob and "标准差为零" not in blob, (
            f"[{label}] 错误归因：含 +Inf 的数据被报为常量列。messages={r.messages}"
        )
        assert "非有限值" in blob, (
            f"[{label}] 剔除了 ±Inf 却未向用户披露（B1 契约要求「移除 + 披露数量与列名」）。"
            f"status={r.status} messages={r.messages}"
        )
        assert "1" in blob, f"[{label}] 披露必须含剔除数量（实测 1 个）：{r.messages}"

    @pytest.mark.parametrize("label,req_kwargs", _INF_TASKS, ids=[t[0] for t in _INF_TASKS])
    def test_verdict_is_identical_under_both_warning_policies(self, label, req_kwargs):
        """生产口径与 pytest 口径必须给出**同一结论** —— 这是假绿通道的正面封堵。

        生产：`filterwarnings` 默认为 default（Web/CLI 用户所见）。
        pytest：`pyproject.toml` 把第三方 `RuntimeWarning` 升为 error。

        两种口径下都必须：① 不误报常量；② 如实披露非有限值剔除。
        """
        for policy, tag in (("default", "生产口径"), ("error", "pytest 口径")):
            r = _run_with_warning_policy(req_kwargs, policy)
            blob = " ".join(r.messages or [])
            assert "常量" not in blob, f"[{label}/{tag}] 错误归因：{r.messages}"
            assert "非有限值" in blob, (
                f"[{label}/{tag}] 两种 warnings 口径给出了不同结论 —— "
                f"这正是 P0-6 假绿的成因。status={r.status} messages={r.messages}"
            )


class TestMissingColumnIsRejected:
    """P2-4：不存在的列名不得被静默忽略（B0 拒绝 + 列出可用列）。

    对照健康：`process_capability(subgroup_col=…)`、`hypothesis_test(group_col=…)`、
    `correlation`、`anova` 都已显式报错 —— 只有 `spc_cusum`/`spc_ewma` 的
    `group_col` 与 `spc_xbar` 的 `feature_cols` 会静默退化，用户以为已按分组分析。
    """

    _DF = pd.DataFrame(
        {
            "v": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0] * 4,
            "线别": (["A"] * 12 + ["B"] * 12),
        }
    )

    @pytest.mark.parametrize("task", ["spc_cusum", "spc_ewma"])
    def test_unknown_group_col_is_rejected(self, task):
        r = orchestrate(
            AnalysisRequest(task=task, data=self._DF, target_col="v", params={"group_col": "产线"})
        )
        assert r.status == "error", (
            f"{task}(group_col='产线') 应拒绝：数据中无该列，实际 status={r.status} "
            f"messages={r.messages}"
        )
        blob = " ".join(r.messages)
        assert "产线" in blob, f"错误消息应点名不存在的列：{r.messages}"
        assert "线别" in blob, f"错误消息应列出可用列供用户改选：{r.messages}"

    def test_unknown_feature_col_in_xbar_is_rejected(self):
        """`spc_xbar(feature_cols=['不存在子组列'])` 此前静默退化为 i_chart。"""
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar",
                data=self._DF,
                target_col="v",
                feature_cols=["不存在的子组列"],
            )
        )
        assert r.status == "error", (
            f"spc_xbar(feature_cols=['不存在的子组列']) 应拒绝，实际 status={r.status} "
            f"metadata.chart_type={r.metadata.get('chart_type')}"
        )
        blob = " ".join(r.messages)
        assert "不存在的子组列" in blob and "线别" in blob, r.messages

    def test_absent_group_col_still_runs(self):
        """反向：**未提供** group_col 是合法用法，不得被上面的校验误伤。

        真实值断言：未分组时全部数据进单一「全部」组 —— 组数=1、统计表分组名=「全部」、
        且均值等于整列均值（证明没有漏掉任何一行）。
        """
        r = orchestrate(AnalysisRequest(task="spc_cusum", data=self._DF, target_col="v"))
        assert r.status == "ok", r.messages
        assert r.metadata["n_groups"] == 1, r.metadata
        assert r.metadata["groups"] == [], r.metadata
        stats = r.tables["cusum_stats"]
        assert stats["分组"].tolist() == ["全部"], stats.to_dict()
        assert float(stats["均值(μ)"].iloc[0]) == pytest.approx(
            float(self._DF["v"].mean()), abs=1e-4
        )


class TestUnequalSubgroupIsDisclosed:
    """契约边界清单 #4（子组大小不一致）的**行为锁定**。

    背景：清单登记的现状是「⚠待规范（当前静默取 min(n)）」。2026-10-09 发版前实测
    **该登记已过期** —— `spc_xbar` 取 min(n) 的同时在 `messages` 与图表标题里都
    写明了这件事；本类把这一披露钉住，使"已规范"这一状态有据可依（契约口径：
    `✅已规范` = 代码已实现且有用例钉住）。

    同时锁定相邻三条不受影响的路径（避免"顺手统一"把它们改坏）：
      · `spc_attribute` 的 np / c 图 → 样本量不等时 **B0 拒绝** 并给出改图建议；
      · `spc_attribute` 的 p / u 图 → 逐点变限，**不降级**（数学上正确支持不等 n）；
      · `process_capability(subgroup_col=)` → 按 nᵢ−1 自由度池化（不取 min(n)）。
    """

    @staticmethod
    def _unequal_frame() -> pd.DataFrame:
        """两组大小不同（8 / 12）的正常数据 —— σ 有变异、非退化。"""
        rng = np.random.default_rng(7)
        values = np.concatenate([rng.normal(10.0, 0.5, 8), rng.normal(10.6, 0.5, 12)])
        return pd.DataFrame({"v": values, "g": ["A"] * 8 + ["B"] * 12})

    def test_xbar_min_n_is_stated_in_messages_and_metadata(self):
        r = orchestrate(
            AnalysisRequest(
                task="spc_xbar",
                data=self._unequal_frame(),
                target_col="v",
                feature_cols=["g"],
                params={},
            )
        )
        assert r.status == "ok", r.messages
        blob = " ".join(r.messages)
        assert "子组大小不一致" in blob, (
            f"子组大小不一致时必须向用户披露（契约 #4：不得静默取 min(n)）：{r.messages}"
        )
        assert "8" in blob, f"披露必须点名实际用的最小子组大小（实测 8）：{r.messages}"
        # 真实值断言：统一 n 如实上报为最小子组大小（而不是最大/平均）
        assert r.metadata["subgroup_size"] == 8, r.metadata
        cl, ucl, lcl = r.metadata["xbar_mean"], r.metadata["ucl_x"], r.metadata["lcl_x"]
        assert np.isfinite(cl) and ucl > cl > lcl

    @pytest.mark.parametrize("chart_type", ["np", "c"])
    def test_attribute_constant_limit_charts_reject_unequal_sizes(self, chart_type):
        """np / c 图的常数控制限在样本量不等时**必然错**，故必须 B0 拒绝并给建议。"""
        df = pd.DataFrame({"def": [3, 5, 2, 7, 4, 6], "tot": [50, 100, 80, 120, 60, 90]})
        r = orchestrate(
            AnalysisRequest(
                task="spc_attribute",
                data=df,
                target_col="def",
                feature_cols=[],
                params={"chart_type": chart_type, "n_col": "tot"},
            )
        )
        assert r.status == "error", f"{chart_type} 图不等样本量应拒绝：{r.status} / {r.messages}"
        blob = " ".join(r.messages)
        assert "最小 50" in blob and "最大 120" in blob, (
            f"{chart_type} 拒绝必须列出实际样本量范围（供用户定位）：{r.messages}"
        )
        assert "50" in blob and "120" in blob, r.messages

    @pytest.mark.parametrize("chart_type", ["p", "u"])
    def test_attribute_varying_limit_charts_accept_unequal_sizes(self, chart_type):
        """p / u 图逐点变限，不等样本量是**合法**输入（不得误伤为拒绝）。"""
        df = pd.DataFrame({"def": [3, 5, 2, 7, 4, 6], "tot": [50, 100, 80, 120, 60, 90]})
        r = orchestrate(
            AnalysisRequest(
                task="spc_attribute",
                data=df,
                target_col="def",
                feature_cols=[],
                params={"chart_type": chart_type, "n_col": "tot"},
            )
        )
        assert r.status == "ok", f"{chart_type} 图支持不等样本量：{r.status} / {r.messages}"
        assert r.metadata["n_points"] == 6, r.metadata

    def test_capability_pooled_subgroup_weights_by_group_size(self):
        """池化子组 σ 按自由度加权（不取 min(n)）：不等子组仍可给出能力指数。"""
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=self._unequal_frame(),
                target_col="v",
                feature_cols=[],
                params={"subgroup_col": "g", "usl": 13.0, "lsl": 7.0},
            )
        )
        assert r.status == "ok", r.messages
        assert r.metadata["within_sigma_method"] == "pooled_subgroup_col", r.metadata
        # 真实值断言：合并组内 σ 由两组各自的离差平方和加权而来（介于两组 σ 之间）
        group_a = self._unequal_frame().query("g == 'A'")["v"]
        group_b = self._unequal_frame().query("g == 'B'")["v"]
        ss = float(
            ((group_a - group_a.mean()) ** 2).sum() + ((group_b - group_b.mean()) ** 2).sum()
        )
        expected = (ss / (len(group_a) + len(group_b) - 2)) ** 0.5
        assert float(r.metadata["sigma_within"]) == pytest.approx(expected, rel=1e-9)


# ══════════════════════════════════════════════════════════════
# 契约 #5：常量/无变异判据与归因的**单一实现**（源码级门禁）
# ══════════════════════════════════════════════════════════════


class TestDegenerateColumnAttributionSSOT:
    """契约边界清单 #5「各模块不一致」的源码级收口（2026-10-09 发版前收尾）。

    修复前实测（判据跑在 `HEAD` 源码副本上）：命中 **19 处**手写「常量列/无变异」判据
    （`x.nunique(dropna=True) <= 1` 一族），各写各的判据与文案，且都把
    「整列为空」（n_valid=0）与「只有 1 个有效观测」一并说成"常量列" ——
    用户按"常量列"去排查一个空列永远查不到原因（错误归因，硬性要求 2）。
    其中 17 处已改走 `_guard`，2 处（判的是**计数**而非观测列：子组大小一致性、
    设计单元平衡性）留在判据白名单。

    本类把两个不变量钉成门禁（互补，缺一不可）：

    ① **判据唯一**：源码里不得再出现手写的退化判据特征族，必须走 `_guard`；
    ② **归因唯一**：任何向用户报「常量列」的模块，必须能区分三级
       （常量 / 整列为空 / 有效观测不足），否则它就是在猜原因。

    两条都带**具名白名单**；白名单条目必须（a）仍在命中、（b）理由非空、
    （c）理由里点名的代码特征仍在文件里 —— 否则条目会被 `test_*_still_live`
    报红，要求人工复核（白名单不得漂移成"永久免死金牌"）。
    """

    #: 判据特征族（手写形态）
    _HANDWRITTEN_PREDICATES = (
        # ① `x.nunique(dropna=True) <= 1` / `== 1` / `< 2`
        re.compile(r"nunique\s*\([^)]*\)\s*(?:<=|==|<)\s*[12]\b"),
        # ①' 反向写法 `1 >= x.nunique()`
        re.compile(r"[12]\s*(?:>=|>)\s*\w+\.nunique\s*\("),
        # ② `np.unique(y).size <= 1`
        re.compile(r"np\.unique\s*\([^)]*\)\s*\.size\s*(?:<=|==|<)\s*[12]\b"),
        # ②' `len(set(x)) <= 1`
        re.compile(r"len\s*\(\s*set\s*\([^)]*\)\s*\)\s*(?:<=|==|<)\s*[12]\b"),
        # ③ 精确零方差 `x.std(...) == 0` / `x.var(...) == 0`
        re.compile(r"\.(?:std|var)\s*\([^)]*\)\s*==\s*0(?:\.0)?\b"),
        # ④ 极差为零 `x.max(...) == y.min(...)`
        re.compile(r"\.max\s*\([^)]*\)\s*==\s*\w+\.min\s*\("),
    )

    #: `_guard` 的合法入口（源码里出现任一即视为"已走单一实现"）
    _SANCTIONED = (
        "check_non_constant(",
        "degenerate_column_code(",
        "degenerate_column_reason(",
        "first_degenerate_reason(",
        "explain_undefined_sigma(",
    )

    #: ① 判据白名单 —— `{路径: {该行必须包含的片段: 理由}}`（**逐行**登记）
    _PREDICATE_WHITELIST: dict[str, dict[str, str]] = {
        "spc_charts/xbar_r.py": {
            "n_sizes.nunique() == 1": (
                "`n_sizes.nunique() == 1` 判的是**子组大小 n 是否一致**（契约 #4），"
                "不是数据列是否退化（契约 #5）—— 判据对象是计数列而不是观测列，"
                "没有「整列为空/样本不足」三级可分，故不适用 `_guard`。"
                "对应的不等子组披露由 `TestUnequalSubgroupIsDisclosed` 钉住"
            )
        },
        "root_cause/anova.py": {
            "len(set(cell_sizes)) <= 1": (
                "`design_balanced` 判的是**单元计数是否平衡**（设计平衡性，决定 Type II 与 "
                "III 是否有差异）：`cell_sizes` 是 `groupby().size()` 的计数结果，"
                "不是观测列，没有退化三级可分 —— 与契约 #4 同族"
            )
        },
    }

    #: ② 归因白名单 —— 报了「常量列」但**判据本身不是退化判据**的文件
    _BLAME_WHITELIST = {
        "detection/trend.py": (
            "判据是**相对方差** `σ ≤ 1e-12 · max|x|`（不是 `nunique` 退化判据）："
            "它额外覆盖'浮点意义上无变异'，由 `tests/guards/test_micro_scale_guards.py`"
            "（B-4）钉住 —— 改用 `_guard` 的精确退化判据会把 pico 级**真实**波动"
            "判成常量（正是当年 B-4 的误报）。故此处保留自己的判据，只报「无变异」"
        ),
        "spc_charts/xbar_r.py": (
            "同上：`_abs_scale == 0 or sigma_xbar <= 1e-12 · max|x|` 是相对方差判据；"
            "非有限 σ 已**先于**它由 `explain_undefined_sigma` 单独归因（R3-P1-6），"
            "故到达该分支的确实是'数值上无变异'，不构成错误归因"
        ),
        "spc_charts/nonparametric.py": (
            "同上（相对方差判据）。⚠ 该文件本轮由并行 agent 持有，"
            "本次收尾未改动它；口径与 trend/xbar_r 一致"
        ),
        "detection/_shared.py": (
            "`iqr == 0` 不是退化判据（IQR 可为 0 而数据并非常量，如 [1,2,2,2,2,3]）；"
            "docstring 里的「（常量列）」是术语沿用，函数本身返回 None 交由调用方"
            "给任务级中文报错"
        ),
    }

    #: ② 白名单条目必须真的**仍由相对方差判据触发**（否则理由过期）
    _RELATIVE_VARIANCE_MARK = "1e-12 *"

    @classmethod
    def _code_lines(cls, path: Path) -> list[tuple[int, str]]:
        """返回 `[(行号, 去注释后的源码行)]`（注释不算代码）。"""
        return [
            (i, ln.split("#", 1)[0])
            for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        ]

    @classmethod
    def _predicate_hits(cls) -> dict[str, list[tuple[int, str]]]:
        """`{相对路径: [(行号, 该行源码)]}`（只统计判据特征族命中的行）。"""
        hits: dict[str, list[tuple[int, str]]] = {}
        for path in sorted(_ENGINE.rglob("*.py")):
            if path.name == "_guard.py":  # 单一实现本身
                continue
            lines = [
                (i, code.strip())
                for i, code in cls._code_lines(path)
                if any(p.search(code) for p in cls._HANDWRITTEN_PREDICATES)
            ]
            if lines:
                hits[str(path.relative_to(_ENGINE)).replace("\\", "/")] = lines
        return hits

    @classmethod
    def _blame_files(cls) -> dict[str, list[int]]:
        """报了「常量列」的引擎模块（`_guard` 是文案源，不算调用方）。"""
        hits: dict[str, list[int]] = {}
        for path in sorted(_ENGINE.rglob("*.py")):
            if path.name == "_guard.py":
                continue
            lines = [i for i, code in cls._code_lines(path) if "常量列" in code]
            if lines:
                hits[str(path.relative_to(_ENGINE)).replace("\\", "/")] = lines
        return hits

    def _unwhitelisted_predicate_hits(self) -> list[str]:
        """① 未被 `_PREDICATE_WHITELIST` 逐行登记的命中。

        白名单**按行登记**（`{路径: {该行源码片段: 理由}}`）而不是按文件 ——
        按文件登记会让"该文件以后新增一处手写判据"也一并被放过。
        """
        offenders = []
        for rel, rows in self._predicate_hits().items():
            allowed = self._PREDICATE_WHITELIST.get(rel, {})
            for line_no, code in rows:
                if any(snippet in code for snippet in allowed):
                    continue
                offenders.append(f"{rel}:{line_no} —— {code}")
        return offenders

    def test_no_handwritten_degenerate_predicate(self):
        """① 手写退化判据必须清零（或已具名登记为例外）。"""
        offenders = self._unwhitelisted_predicate_hits()
        assert not offenders, (
            "以下位置仍手写「常量/无变异」判据 —— 应改用 `_guard.degenerate_column_code` "
            "（判据）与 `degenerate_column_reason` / `first_degenerate_reason`（文案），"
            "否则「整列为空」「有效观测不足」会被误报成「常量列」（契约 #5）:\n  "
            + "\n  ".join(offenders)
        )

    def test_constant_blame_files_have_three_level_attribution(self):
        """② 报「常量列」的模块必须能区分三级（否则是在猜原因）。"""
        offenders = []
        for rel, lines in self._blame_files().items():
            if rel in self._BLAME_WHITELIST:
                continue
            src = (_ENGINE / rel).read_text(encoding="utf-8")
            if not any(k in src for k in self._SANCTIONED):
                offenders.append(f"{rel}:{lines}")
        assert not offenders, (
            "以下模块向用户报「常量列」，但没有走 `_guard` 的三级归因 —— "
            "全 NaN 列 / 单有效观测会被它说成「常量列」（错误归因，硬性要求 2）:\n  "
            + "\n  ".join(offenders)
        )

    def test_predicate_whitelist_entries_are_live_and_justified(self):
        """① 白名单条目必须仍在命中，理由非空 —— 条目过期即 FAIL 要求删除。"""
        hits = self._predicate_hits()
        for rel, allowed in self._PREDICATE_WHITELIST.items():
            codes = [code for _ln, code in hits.get(rel, [])]
            for snippet, reason in allowed.items():
                assert any(snippet in code for code in codes), (
                    f"判据白名单 {rel} 的条目 {snippet!r} 已不再命中 —— "
                    f"该处判据已被改写，请删除条目并重新评估（否则守卫被悄悄放宽）"
                )
                assert len(reason) >= 20, f"白名单 {rel}/{snippet} 的理由太短：{reason!r}"

    def test_blame_whitelist_entries_are_live_and_justified(self):
        """② 白名单条目必须**仍然因为相对方差判据**而被豁免（理由不得过期）。

        若某天 trend/xbar_r 改成了 `_guard` 判据，`1e-12 *` 会消失 → 本条 FAIL，
        要求删除白名单条目；反之若有人把它们改成别的写法，也会被发现。
        """
        blame = self._blame_files()
        stale = sorted(set(self._BLAME_WHITELIST) - set(blame))
        assert not stale, f"归因白名单已不再命中（应删除）: {stale}"
        for rel, reason in self._BLAME_WHITELIST.items():
            assert len(reason) >= 20, f"白名单 {rel} 的理由太短：{reason!r}"
            src = (_ENGINE / rel).read_text(encoding="utf-8")
            if rel == "detection/_shared.py":
                assert "iqr == 0" in src, f"{rel} 的豁免理由（IQR==0 非退化判据）已过期"
            else:
                assert self._RELATIVE_VARIANCE_MARK in src, (
                    f"{rel} 的豁免理由是「相对方差判据 σ ≤ 1e-12·max|x|」，"
                    f"但源码里已找不到该特征 —— 请删除该白名单条目并重新评估"
                )

    def test_scanner_detects_every_known_predicate_form(self, tmp_path):
        """**负向注入**：六种手写形态各写一份样本，扫描器必须全部抓到。

        没有这条，「零违规」与「扫描器失效」无法区分。
        """
        forms = {
            "nunique.py": "def f(s):\n    return s.nunique(dropna=True) <= 1\n",
            "nunique_eq.py": "def f(s):\n    return s.nunique() == 1\n",
            "nunique_rev.py": "def f(s):\n    return 1 >= s.nunique(dropna=True)\n",
            "unique_size.py": "def f(y):\n    return np.unique(y).size <= 1\n",
            "len_set.py": "def f(x):\n    return len(set(x)) <= 1\n",
            "std_zero.py": "def f(x):\n    return np.std(x, ddof=1) == 0\n",
        }
        for name, body in forms.items():
            (tmp_path / name).write_text(body, encoding="utf-8")
        hits: dict[str, list[int]] = {}
        for path in sorted(tmp_path.rglob("*.py")):
            lines = [
                i
                for i, code in self._code_lines(path)
                if any(p.search(code) for p in self._HANDWRITTEN_PREDICATES)
            ]
            if lines:
                hits[path.name] = lines
        missing = sorted(set(forms) - set(hits))
        assert not missing, f"扫描器漏掉这些判据形态: {missing}"

    def test_guard_exposes_the_single_implementation(self):
        """单一实现必须在（否则上面的"必须改用 _guard"无法执行）。"""
        from smartsuite.engine import _guard

        for name in (
            "degenerate_column_code",
            "degenerate_column_reason",
            "first_degenerate_reason",
        ):
            assert hasattr(_guard, name), f"_guard 缺少 {name}"

    def test_attribution_is_three_level_and_order_stable(self):
        """行为契约：三级归因的顺序不可颠倒（**整列为空 → 样本不足 → 常量**）。

        （本 docstring 原写作「常量 → 空列 → 样本不足」，与实现相反 —— 属审查
        2026-10-09 R2BD-09 的同一处顺序漂移，随契约文档一并更正。）
        """
        from smartsuite.engine._guard import degenerate_column_code

        assert degenerate_column_code(pd.Series([5.0, 5.0])) == "E_DATA_CONSTANT_COLUMN"
        assert degenerate_column_code(pd.Series([np.nan, np.nan])) == "E_DATA_EMPTY_COLUMN"
        assert degenerate_column_code(pd.Series([7.0])) == "E_DATA_INSUFFICIENT_N"
        assert degenerate_column_code(pd.Series([1.0, 2.0])) is None
        # 判据等价性：`code is not None` ⟺ `nunique(dropna=True) <= 1`（收口不改分支）
        for series in (
            [5.0, 5.0],
            [np.nan, np.nan],
            [7.0],
            [7.0, np.nan],
            [1.0, 2.0],
            [],
        ):
            s = pd.Series(series, dtype=float)
            assert (degenerate_column_code(s) is not None) == (s.nunique(dropna=True) <= 1), series


class TestBoundaryContractSourceGuard:
    """源码级防线：错误归因与清洗重复不得回流。"""

    # 输入清洗的**唯一**合法实现（见 docs/governance/boundary-contract.md「执行点」）
    _SANCTIONED = ("clean_series", "clean_frame", "check_magnitude", "check_tables_finite")

    #: 输入清洗特征族（P1-6：原正则只认 `x = x[np.isfinite(x)]` 一种形态，漏名/替换/掩码全漏）
    _INPUT_CLEANUP_PATTERNS = (
        # ① 同名形态：`x = x[np.isfinite(x)]`
        re.compile(r"^\s*(\w+)\s*=\s*\1\[\s*np\.isfinite\(\1\)\s*\]"),
        # ② **漏名形态**（P1-6 盲区）：`finite = arr[np.isfinite(arr)]`
        re.compile(r"^\s*\w+\s*=\s*\w+\[\s*np\.isfinite\(\w+\)\s*\]"),
        # ③ 掩码形态：`mask = np.isfinite(v1) & np.isfinite(v2)`
        re.compile(r"^\s*\w+\s*=\s*np\.isfinite\("),
        # ④ ±Inf → NaN 后 dropna：`.replace([np.inf, -np.inf], np.nan)`
        re.compile(r"\.replace\(\s*\[?\s*np\.inf"),
    )

    #: 已登记的例外 —— **每一条必须具名理由**（无理由的白名单等于没有守卫）。
    #: 由 `test_whitelist_entries_are_live_and_justified` 强制"仍在命中 + 理由非空"。
    _INPUT_CLEANUP_WHITELIST = {
        "spc_charts/attribute.py": (
            "`_unequal_sample_sizes` 只从**样本量列**取 min/max 做 B0 一致性校验，"
            "清洗结果不参与分析口径（且该文件本轮由并行 agent 持有，不可改）"
        ),
        "root_cause/modeling.py": (
            "VIF 绘图轴范围：只按有限值定 xlim 以免 matplotlib 抛错，数值表仍如实给出 inf"
        ),
        "inverse/_report.py": (
            "`_feature_scales` 只计算各特征列的量级判据 max|x|（**不剔除任何行**、"
            "不改样本口径），非有限时回退 1.0 —— 属内部数值归一，无 B1 披露义务。"
            "已核实回退分支实际不可达：前向路径传入的 `history` 已被 `solve.py` 的 "
            "`clean_mask` 按 `clean_cols`（与 `feature_cols` 同一常量过滤）清洗过；"
            "速率路径的 `finite_union` 掩码会在整列无有效值时报 '有效历史不足' 拒绝，"
            "故该回退只是防御性写法"
        ),
    }

    @classmethod
    def _scan(cls, root: Path) -> dict[str, list[int]]:
        """扫描输入清洗特征族 -> `{相对路径: [行号...]}`（`_guard`/`_utils` 是执行点本身）。"""
        hits: dict[str, list[int]] = {}
        for path in sorted(root.rglob("*.py")):
            if path.name in {"_guard.py", "_utils.py"}:
                continue
            src = path.read_text(encoding="utf-8")
            lines = [
                i
                for i, line in enumerate(src.splitlines(), start=1)
                if any(p.search(line) for p in cls._INPUT_CLEANUP_PATTERNS)
            ]
            if lines:
                hits[str(path.relative_to(root)).replace("\\", "/")] = lines
        return hits

    def test_no_constant_blame_without_non_finite_cleanup(self):
        """若模块报「标准差为 0/零」，它必须能区分「常量」与「含非有限值」。

        这是 P1-6 的根因防线：含 +Inf 的数据 σ 为 NaN，若模块只写
        「常量列（标准差为 0）」就是错误归因（用户查常量列永远查不到原因）。
        """
        offenders = []
        for path in _ENGINE.rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            if "标准差为 0" not in src and "标准差为零" not in src:
                continue
            can_distinguish = (
                any(k in src for k in self._SANCTIONED)
                or "np.isfinite" in src
                or "explain_undefined_sigma" in src
            )
            if not can_distinguish:
                offenders.append(str(path.relative_to(_ENGINE)))
        assert not offenders, (
            f"以下模块报「标准差为 0/零」但没有任何非有限值判别路径，存在错误归因风险: {offenders}"
        )

    def test_input_cleanup_is_reported(self):
        """做了输入级 ±Inf 清洗的模块，必须向用户披露（B1）或已具名登记为例外。

        未披露的静默清洗会让用户看到"N=20"却不知道实际只用 19 个观测。
        """
        offenders = []
        for rel, lines in self._scan(_ENGINE).items():
            if rel in self._INPUT_CLEANUP_WHITELIST:
                continue
            src = (_ENGINE / rel).read_text(encoding="utf-8")
            if any(k in src for k in (*self._SANCTIONED, "BoundaryReport")):
                continue
            offenders.append(f"{rel}:{lines}")
        assert not offenders, (
            "以下模块做了输入级非有限值清洗但未披露（应改用 _guard 的 "
            "clean_series/clean_frame，并在 messages 给出剔除数量）:\n  " + "\n  ".join(offenders)
        )

    def test_scanner_detects_every_known_cleanup_form(self, tmp_path):
        """**负向注入**：四种清洗形态各写一份"违规样本"，扫描器必须全部抓到。

        没有这条，上面的零违规就与"扫描器失效"无法区分（P1-6 的教训：
        原正则漏掉 `finite = arr[np.isfinite(arr)]`，于是 attribute.py 静默过关）。
        """
        forms = {
            "same_name.py": "def f(s):\n    s = s[np.isfinite(s)]\n    return s\n",
            "renamed.py": "def f(arr):\n    finite = arr[np.isfinite(arr)]\n    return finite\n",
            "pairwise.py": "def f(a, b):\n    mask = np.isfinite(a) & np.isfinite(b)\n    return mask\n",
            "replace.py": "def f(s):\n    return s.replace([np.inf, -np.inf], np.nan).dropna()\n",
        }
        for name, body in forms.items():
            (tmp_path / name).write_text(body, encoding="utf-8")
        hits = self._scan(tmp_path)
        missing = sorted(set(forms) - set(hits))
        assert not missing, f"扫描器漏掉这些清洗形态（正是 P1-6 的盲区）: {missing}"

    def test_whitelist_entries_are_live_and_justified(self):
        """白名单不得过期，也不得写成"无理由"—— 无理由的白名单等于删掉守卫。"""
        hits = self._scan(_ENGINE)
        stale = sorted(set(self._INPUT_CLEANUP_WHITELIST) - set(hits))
        assert not stale, f"白名单里这些条目已不再命中（应删除，否则守卫被悄悄放宽）: {stale}"
        for rel, reason in self._INPUT_CLEANUP_WHITELIST.items():
            assert len(reason) >= 20, f"白名单 {rel} 的理由太短，不足以说明为何合规：{reason!r}"


# ══════════════════════════════════════════════════════════════
# 契约文档 ↔ `_guard` 实现：归因顺序 / 接入面（R2BD-09 / R2BD-07）
# ══════════════════════════════════════════════════════════════

_CONTRACT = _ENGINE.parents[2] / "docs" / "governance" / "boundary-contract.md"

#: 错误码 → 契约文档里的归因标签（文档两处措辞不同，此处做**显式**别名归一）。
_CODE_LABEL = {
    "E_DATA_EMPTY_COLUMN": "整列为空",
    "E_DATA_INSUFFICIENT_N": "样本不足",
    "E_DATA_CONSTANT_COLUMN": "常量",
    "E_DATA_NON_FINITE_BLOCKS_SIGMA": "非有限值",
    "E_NUMERIC_SIGMA_UNDEFINED": "兜底",
}

#: 标签 → 错误码（行为级判据用）
_CODE_LABEL_INVERSE = {label: code for code, label in _CODE_LABEL.items()}

#: 文档措辞 → 归一标签（`样本量` == `样本不足`；`非有限` == `非有限值`）
_LABEL_ALIAS = {"样本量": "样本不足", "非有限": "非有限值"}

_ORDER_RE = re.compile(
    r"((?:整列为空|样本不足|样本量|常量|非有限值|非有限|兜底)"
    r"(?:\s*→\s*(?:整列为空|样本不足|样本量|常量|非有限值|非有限|兜底))+)"
)


def _normalize_order(text: str) -> list[str]:
    """把契约里的箭头串归一成标签列表（`A → B → C` → `[A, B, C]`）。"""
    return [_LABEL_ALIAS.get(p.strip(), p.strip()) for p in text.split("→")]


def _row(num: int) -> str:
    """边界清单表里编号为 `num` 的那一行原文。"""
    for line in _CONTRACT.read_text(encoding="utf-8").splitlines():
        if re.match(rf"^\|\s*{num}\s*\|", line):
            return line
    raise AssertionError(f"契约表里找不到编号 {num} 的行")


def _code_literal(node: ast.AST) -> str | None:
    """语句子树里第一个可识别的错误码字面量（优先 `code=` 关键字，其次裸字符串）。

    两种实现形态都要认：`return "E_DATA_EMPTY_COLUMN"`（`degenerate_column_code`）
    与 `return BoundaryIssue(code="E_...")` / `if code == "E_...":`（`explain_undefined_sigma`）。
    """
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.keyword)
            and sub.arg == "code"
            and isinstance(sub.value, ast.Constant)
            and sub.value.value in _CODE_LABEL
        ):
            return sub.value.value
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and sub.value in _CODE_LABEL
        ):
            return sub.value
    return None


def _impl_order(function_name: str) -> list[str]:
    """从实现的**源码顺序**推出归因顺序（标签列表）。

    判据只认代码形态（分支里的错误码字面量），**剔除 docstring**、不看注释 ——
    否则"把注释改对、代码留错"会假绿（R2BD-09 的原形：只修了 `_guard` 的 docstring，
    契约文档与实现的顺序仍是反的）。
    """
    from smartsuite.engine import _guard

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(_guard, function_name))))
    node = tree.body[0]
    body = node.body[1:] if ast.get_docstring(node) else node.body
    order: list[str] = []
    for stmt in body:
        if isinstance(stmt, (ast.If, ast.Return)):
            code = _code_literal(stmt)
            if code is not None:
                order.append(_CODE_LABEL[code])
    return order


def _is_ordered_subsequence(short: list[str], long: list[str]) -> bool:
    """`short` 是否为 `long` 的**有序**子序列（允许文档省略未涉及的归因）。"""
    it = iter(long)
    return all(label in it for label in short)


class TestAttributionOrderMatchesGuard:
    """契约文档的**归因顺序**必须与 `_guard` 的实现逐序一致（审查 2026-10-09 R2BD-09）。

    缺陷原形：契约两处写「常量 → 非有限 → 样本量 → 兜底」（#23 行 / 执行点表），
    实现是「…样本量 → 非有限…」—— 两处**互相颠倒**，且只有文档↔源码双向比对才能发现
    （改错那一版时 2078 项测试全绿）。

    顺序颠倒会产生**错误归因**：`[5.0, NaN]` 剔除 NaN 后只剩 1 个有效值，属样本量问题；
    先判「含非有限值」就把用户引向错误的排查方向（契约硬性要求 2）。
    """

    def test_degenerate_order_matches_contract_row_23(self):
        """#23 行的顺序 = `degenerate_column_code` 的返回分支顺序（逐项相等）。"""
        impl = _impl_order("degenerate_column_code")
        assert impl == ["整列为空", "样本不足", "常量"], (
            f"`degenerate_column_code` 的实测分支顺序变了：{impl} —— "
            "请同步契约 #23 行与本用例（顺序不可颠倒；`[5.0, NaN]` 属样本量而非非有限值）"
        )
        match = _ORDER_RE.search(_row(23))
        assert match is not None, f"#23 行找不到归因顺序串：{_row(23)}"
        doc = _normalize_order(match.group(1))
        assert doc[:3] == impl, (
            f"契约 #23 的归因顺序 {doc[:3]} 与实现 {impl} 不一致（文档↔实现漂移）—— "
            "改文档或改实现，二者必须同序"
        )

    def test_explain_sigma_order_matches_contract_execution_table(self):
        """执行点表的顺序必须与 `explain_undefined_sigma` 的真实分支顺序一致。"""
        impl = _impl_order("explain_undefined_sigma")
        # 关键优先级：退化三级（含"样本不足"）一律**先于**非有限值判据
        assert impl.index("样本不足") < impl.index("非有限值"), (
            f"`explain_undefined_sigma` 把「非有限值」排到了样本量之前：{impl} —— "
            "这会把 [5.0, NaN] 这类样本量问题误导成「含非有限值」"
        )
        assert impl[-1] == "兜底", f"最后一个分支不是兜底：{impl}"
        row = next(
            (
                line
                for line in _CONTRACT.read_text(encoding="utf-8").splitlines()
                if "explain_undefined_sigma" in line and _ORDER_RE.search(line)
            ),
            None,
        )
        assert row is not None, "执行点表里找不到 `explain_undefined_sigma` 的归因顺序串"
        doc = _normalize_order(_ORDER_RE.search(row).group(1))
        assert _is_ordered_subsequence(doc, impl), (
            f"执行点表声明的顺序 {doc} 不是实现顺序 {impl} 的有序子序列（文档↔实现漂移）"
        )

    def test_contract_order_predicts_guard_behavior(self):
        """把文档顺序当**优先级**用，必须能复现实现的每一次归因（行为级判据）。

        这条不依赖源码解析：把契约 #23 的顺序串解释成"第一个命中的判据胜出"，
        对 9 类输入逐个预测错误码，再与 `explain_undefined_sigma` 的真实返回比对。
        `(+inf,)`（单值 + 非有限）是**判别对**：按实现它属「样本不足」（先判），
        若文档把「非有限」提前，预测就会变成 `E_DATA_NON_FINITE_BLOCKS_SIGMA` → 红。
        """
        from smartsuite.engine._guard import explain_undefined_sigma

        doc = _normalize_order(_ORDER_RE.search(_row(23)).group(1))
        assert doc == ["整列为空", "样本不足", "常量", "非有限值", "兜底"], doc

        def n_valid(s: pd.Series) -> int:
            return int(s.notna().sum())

        predicates = {
            "整列为空": lambda s: n_valid(s) == 0,
            "样本不足": lambda s: 0 < n_valid(s) < 2,
            "常量": lambda s: n_valid(s) >= 2 and s.nunique(dropna=True) <= 1,
            "非有限值": lambda s: bool(np.isinf(s.to_numpy(dtype=float, na_value=np.nan)).any()),
            "兜底": lambda s: True,
        }
        cases = {
            (5.0, 5.0, 5.0, 5.0): "E_DATA_CONSTANT_COLUMN",
            (np.nan, np.nan, np.nan): "E_DATA_EMPTY_COLUMN",
            (5.0, np.nan, np.nan): "E_DATA_INSUFFICIENT_N",
            (np.inf,): "E_DATA_INSUFFICIENT_N",
            (np.inf, np.inf, np.inf): "E_DATA_CONSTANT_COLUMN",
            (1.0, 2.0, np.inf): "E_DATA_NON_FINITE_BLOCKS_SIGMA",
            (1.0, 2.0, -np.inf): "E_DATA_NON_FINITE_BLOCKS_SIGMA",
            (): "E_DATA_EMPTY_COLUMN",
            (1.0, 2.0): "E_NUMERIC_SIGMA_UNDEFINED",
        }
        for values, expected in cases.items():
            series = pd.Series(list(values), dtype=float)
            predicted = next(
                _CODE_LABEL_INVERSE[label] for label in doc if predicates[label](series)
            )
            assert predicted == expected, f"{values}: 文档顺序预测 {predicted} ≠ 期望 {expected}"
            actual = explain_undefined_sigma(series, what="T").code
            assert actual == expected, f"{values}: 实现返回 {actual} ≠ 期望 {expected}"


class TestCheckTablesFiniteCoverageIsDeclared:
    """契约 #22 的**接入面**必须与源码实测一致（审查 2026-10-09 R2BD-07）。

    缺陷原形：`check_tables_finite` 只接在 3/42 个任务上，契约却标 `✅已规范`
    —— 「代码已实现」被当成了「全覆盖」，出口保洁的实际覆盖率被高估 ~14 倍。

    判据（双向）：

    1. 契约 #22 行里**列出的任务名** == AST 实测接入 `check_tables_finite` 的任务集合；
    2. 只要接入面 ≠ 全部任务，状态列就**不得**写 `✅已规范`（应写 `⚠部分规范` 并给覆盖率）。

    本用例同时是那些数字的**来源**：现场实测，不另抄一份必然过期的计数。
    """

    @staticmethod
    def _measured() -> set[str]:
        from smartsuite.services.task_spec import TASK_SPECS

        hits: set[str] = set()
        for spec in TASK_SPECS:
            module, _, attr = spec.func_path.partition(":")
            path = Path(__file__).resolve().parents[2] / "src" / (module.replace(".", "/") + ".py")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == attr:
                    for sub in ast.walk(node):
                        if (
                            isinstance(sub, ast.Call)
                            and getattr(sub.func, "id", None) == "check_tables_finite"
                        ):
                            hits.add(spec.key)
        return hits

    @staticmethod
    def _declared() -> set[str]:
        from smartsuite.services.task_spec import TASK_SPECS

        keys = {s.key for s in TASK_SPECS}
        return {k for k in re.findall(r"`([a-z0-9_]+)`", _row(22)) if k in keys}

    def test_declared_coverage_matches_source(self):
        """契约 #22 行声明的接入清单 == 源码实测（列一份会过期的清单就必然漂移）。"""
        measured, declared = self._measured(), self._declared()
        assert measured, "AST 扫描没找到任何接入 `check_tables_finite` 的任务（扫描器失效）"
        assert declared == measured, (
            "契约 #22 行声明的接入清单与源码实测不一致：\n"
            f"  契约 - 实测 = {sorted(declared - measured)}\n"
            f"  实测 - 契约 = {sorted(measured - declared)}\n"
            "请同步该行的「已接入任务清单」（数字来源即本用例的 AST 实测）"
        )

    def test_status_reflects_partial_coverage(self):
        """未全覆盖时状态列不得写 `✅已规范`（R2BD-07 的原形）。"""
        from smartsuite.services.task_spec import TASK_SPECS

        covered = len(self._measured())
        total = len(TASK_SPECS)
        status = _row(22).strip().strip("|").split("|")[-1].strip()
        if covered < total:
            assert not status.startswith("✅"), (
                f"出口保洁只接了 {covered}/{total} 个任务，状态列却写「{status[:20]}…」—— "
                "「已实现」不等于「已全覆盖」，应写 `⚠部分规范` + 已接入清单"
            )
            assert f"{covered}/{total}" in status, f"状态列应写明覆盖率 {covered}/{total}：{status}"
        else:
            assert status.startswith("✅"), f"已全覆盖但状态列仍写：{status}"
