"""边界契约回归测试（B0–B3）— 见 docs/governance/boundary-contract.md。

覆盖第三轮复核（logs/reports/verify-round3/R3-复核清单.md）确认的 P0/P1 缺陷：

  P0-1  spc_xbar 子组 n≥380 时 math.gamma 溢出 → 崩溃 + 误报「数据中可能存在极端值」
  P0-4  compare_digest 遇非 ASCII token 抛 TypeError → 500 HTML
  P1-6  ±Inf 清洗覆盖不全，且被误归因为「常量列（标准差为 0）」

所有用例在修复前为红（先写测试 → 修复 → 转绿）。
"""

import re
import secrets
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
            "`_feature_scales` 只计算各特征列的量级判据 max|x|（不剔除任何行），"
            "非有限时回退 1.0 —— 属内部数值归一，无 B1 披露义务"
        ),
        "inverse/_models.py": (
            "速率模型对**辅助时间列/配对标**做行筛选（缺有效时间的行已由 "
            "`logger.warning` 记录行数），不改变用户所选目标列的样本口径；"
            "该文件不在本批所有权内 —— ⚠ 已知缺口：其披露目前仅到日志，未进 messages"
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
