"""边界契约回归测试（B0–B3）— 见 docs/governance/boundary-contract.md。

覆盖第三轮复核（logs/reports/verify-round3/R3-复核清单.md）确认的 P0/P1 缺陷：

  P0-1  spc_xbar 子组 n≥380 时 math.gamma 溢出 → 崩溃 + 误报「数据中可能存在极端值」
  P0-4  compare_digest 遇非 ASCII token 抛 TypeError → 500 HTML
  P1-6  ±Inf 清洗覆盖不全，且被误归因为「常量列（标准差为 0）」

所有用例在修复前为红（先写测试 → 修复 → 转绿）。
"""

import re
import secrets
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


class TestInfNotBlamedAsConstant:
    """含 ±Inf 的数据不得被报告为「常量列 / 标准差为零」。"""

    @pytest.mark.parametrize("label,req_kwargs", _INF_TASKS, ids=[t[0] for t in _INF_TASKS])
    def test_inf_never_reported_as_constant_column(self, label, req_kwargs):
        df = _inf_frame()
        r = orchestrate(AnalysisRequest(data=df, **req_kwargs))
        blob = " ".join(r.messages or [])
        assert "常量" not in blob and "标准差为 0" not in blob and "标准差为零" not in blob, (
            f"[{label}] 错误归因：含 +Inf 的数据被报为常量列。messages={r.messages}"
        )


class TestBoundaryContractSourceGuard:
    """源码级防线：错误归因与清洗重复不得回流。"""

    # 输入清洗的两种既有合法形态（见 docs/governance/boundary-contract.md「执行点」）
    _SANCTIONED = ("drop_non_finite", "clean_series", "clean_frame")
    # 输入清洗特征：`<标识符> = <标识符>[np.isfinite(<标识符>)]`
    # 注意**不**匹配 `mask = ...`（掩码构建，见 partition_finite）与
    # `x = arr[bool_mask]`（已是布尔掩码，非 isfinite 直判）
    _INPUT_CLEANUP = re.compile(r"^\s*(\w+)\s*=\s*\1\[np\.isfinite\(\1\)\]")

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
        """做了输入级 ±Inf 清洗的模块，必须同时向用户披露（B1 契约要求）。

        未披露的静默清洗会让用户看到"N=20"却不知道实际只用 19 个观测。
        """
        offenders = []
        for path in _ENGINE.rglob("*.py"):
            if path.name in {"_guard.py", "_utils.py"}:
                continue
            src = path.read_text(encoding="utf-8")
            cleans_input = any(self._INPUT_CLEANUP.match(line) for line in src.splitlines())
            if not cleans_input:
                continue
            discloses = any(k in src for k in (*self._SANCTIONED, "BoundaryReport"))
            if not discloses:
                offenders.append(str(path.relative_to(_ENGINE)))
        assert not offenders, (
            f"以下模块做了输入级非有限值清洗但未披露（应在 messages 中给出剔除数量）: {offenders}"
        )
