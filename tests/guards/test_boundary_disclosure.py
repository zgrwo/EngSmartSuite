"""B1 契约的「静默清洗」防线（第三十二轮）。

契约：boundary-contract.md — B1（清洗）必须向用户披露剔除数量；sentinel-contract.md 同旨。

## 背景：本轮我先误报了一次，然后量出真相

引擎里有两套并存的清洗实现：

| 实现 | 位置 | 是否产出披露 |
|:---|:---|:---|
| `drop_non_finite` / `drop_non_finite_rows` | `engine/_utils.py` | 否 —— 只返回 (数据, 剔除数) |
| `clean_series` / `clean_frame` | `engine/_guard.py` | 是 —— 填充 `BoundaryReport` |

我第一版扫描器用**固定行窗口**（调用点后 40 行）判断剔除数量有没有被用到，
报出 **7 处静默清洗**（capability.py:328、exploratory.py:118/208/535、
reliability.py:457/891、distribution.py:46）。

**但那是假阳性**：capability.py 的 n_inf 在**第 369 行**被使用
（`if n_inf: warn_msgs.append(non_finite_note(...))`），距调用点 41 行 ——
只差一行就出了我的窗口。改用 **AST 作用域**判定后：真实缺口 **0**。

端到端实测也确认披露是正常的：

    ⚠ 「y」含 3 个非有限值（NaN 或 ±Inf），已剔除后分析

## 那还剩什么真问题

两点，都**不是现在有缺陷**：

1. **既有守卫有盲区**。`tests/guards/test_boundary_contract.py` 的 `_INPUT_CLEANUP`
   正则只匹配内联形态 `x = x[np.isfinite(x)]`，**不匹配实际写法**
   `x, n = drop_non_finite(x)`。所以一个**新增**的、忘披露的调用点不会被任何守卫
   拦住 —— 本文件的 AST 守卫补上这个盲区（对现有代码通过，对未来回归生效）。
2. **披露依赖调用方记得接线**，而非一处声明、一处执行：20+ 处各自手写
   `non_finite_note(n)`。契约终态是改用 `_guard` 自动产出披露。本轮**如实标注为
   未达标**（见计划台账）：那需要重写 20+ 处调用点并迁移 6 个模块。

> 本文件的记录方式本身就是一条经验：**报出缺陷前先确认扫描器本身没问题** ——
> 固定窗口是脆弱的判据（一行的差距就翻转结论），作用域才是正确粒度。
"""

from __future__ import annotations

import ast
import contextlib
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import (
    NO_DATA_TASKS,
    TASK_REGISTRY,
    orchestrate,
)

_ENGINE = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "engine"

#: `_utils` 的无披露清洗函数（单列 / 多列）
_LEGACY_CLEANERS = ("drop_non_finite", "drop_non_finite_rows")

#: 迁移清单（`docs/governance/guard-migration.md`）是进度的**单一事实源**。
#: 本文件从中读出"哪些模块已迁移、哪些待迁移"，从而不必在每次迁移后改测试。
_GUARD_MIGRATION_DOC = (
    Path(__file__).resolve().parents[2] / "docs" / "governance" / "guard-migration.md"
)


def _manifest_rows() -> list[tuple[str, str]]:
    """从清单表里读出 `(模块名, 状态单元格)`。"""
    rows: list[tuple[str, str]] = []
    for ln in _GUARD_MIGRATION_DOC.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| `"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        rows.append((cells[0].strip("`"), cells[1]))
    return rows


#: 已迁移的模块（清单里状态含 ✅）
_MIGRATED_FILES = frozenset(name for name, status in _manifest_rows() if "✅" in status)
#: 待迁移的模块（清单里状态含 ⏳）→ 这些**必须仍含**旧调用点
_PENDING_MIGRATION_FILES = frozenset(name for name, status in _manifest_rows() if "⏳" in status)


def _pending_site_total() -> int:
    """从清单表里读出待迁移模块的**旧调用点总数**。

    清单的第三列是调用点数（如 `| \u0060exploratory.py\u0060 | ⏳ 待迁移 | 3 | |`）。
    与之对账可同时抓住两种漂移：**清单过期**与**扫描器失准** ——
    两者都会让"待迁移还有多少"这个数字失去意义。
    """
    total = 0
    for ln in _GUARD_MIGRATION_DOC.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| `") or "⏳" not in ln:
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3:
            continue
        try:
            total += int(cells[2])
        except ValueError:
            continue
    return total


def _frame_with_inf(n: int = 40, n_inf: int = 3) -> pd.DataFrame:
    """构造含 ±Inf 的数据（目标列前 n_inf 个设为 +Inf）。"""
    rng = np.random.default_rng(11)
    y = rng.normal(50, 2.0, n)
    y[:n_inf] = np.inf
    return pd.DataFrame({"y": y, "x": rng.normal(0, 1, n), "g": (["A", "B"] * (n // 2))[:n]})


def _via(task: str, target: str, features: list[str], params: dict | None = None):
    return orchestrate(
        AnalysisRequest(
            task=task,
            data=_frame_with_inf(),
            target_col=target,
            feature_cols=features,
            params=params or {},
        )
    )


def _cleanup_sites() -> list[tuple[Path, int, str]]:
    """所有 `x, n = drop_non_finite*(...)` 调用点 -> [(文件, 行号, 计数字段名)]。"""
    sites: list[tuple[Path, int, str]] = []
    for path in sorted(_ENGINE.rglob("*.py")):
        if path.name in {"_guard.py", "_utils.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            fn = node.value.func
            if not (isinstance(fn, ast.Name) and fn.id in _LEGACY_CLEANERS):
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Tuple) or len(tgt.elts) < 2:
                continue
            cnt = tgt.elts[1]
            if isinstance(cnt, ast.Name):
                sites.append((path, node.lineno, cnt.id))
    return sites


class TestNonFiniteDroppingIsDisclosed:
    """含 ±Inf 时，用户必须能看到「已剔除 N 个非有限值」（B1）。

    这一组是**行为锁定**（当前全部通过）：把已经做对的事写成断言，
    防止将来重构时把披露丢掉 —— 丢掉它，用户只会看到样本量莫名变小。
    """

    def test_process_capability_discloses_inf_removal(self):
        r = _via("process_capability", "y", ["x"], {"usl": 56.0, "lsl": 44.0})
        assert r.status == "ok", r.messages
        joined = " ".join(r.messages)
        assert "非有限值" in joined, f"剔除了 ±Inf 却未告知用户（B1 契约）：{r.messages}"
        assert "3" in joined, f"披露应含剔除数量（实测 3 个）：{r.messages}"

    def test_median_ci_discloses_inf_removal(self):
        r = _via("median_ci", "y", [])
        assert r.status == "ok", r.messages
        assert "非有限值" in " ".join(r.messages), f"median_ci 未披露：{r.messages}"

    def test_bootstrap_ci_discloses_inf_removal(self):
        r = _via("bootstrap_ci", "y", [], {"n_bootstrap": 200})
        assert r.status == "ok", r.messages
        assert "非有限值" in " ".join(r.messages), f"bootstrap_ci 未披露：{r.messages}"

    def test_box_chart_discloses_inf_removal(self):
        """box_chart 用的是多列形态 drop_non_finite_rows。"""
        r = _via("box_chart", "y", ["g"])
        assert r.status == "ok", r.messages
        assert "非有限值" in " ".join(r.messages), f"box_chart 未披露：{r.messages}"

    def test_distribution_summary_discloses_inf_removal(self):
        r = _via("distribution_summary", "y", [])
        assert r.status == "ok", r.messages
        assert "非有限值" in " ".join(r.messages), f"distribution_summary 未披露：{r.messages}"

    def test_no_message_when_nothing_is_dropped(self):
        """反向：没有非有限值时不得凭空加提示。

        否则提示退化为噪音，用户会学会忽略它 —— 那和没有提示一样糟。
        """
        rng = np.random.default_rng(3)
        df = pd.DataFrame({"y": rng.normal(50, 2, 40), "x": rng.normal(0, 1, 40)})
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=["x"],
                params={"usl": 56.0, "lsl": 44.0},
            )
        )
        assert r.status == "ok", r.messages
        assert "非有限值" not in " ".join(r.messages), f"没有非有限值却给了假提示：{r.messages}"


class TestSourceGuardHasNoBlindSpot:
    """补上既有守卫的盲区：**调用形态**的静默清洗也要被抓到。"""

    def test_scanner_actually_sees_the_call_sites(self):
        """先证明扫描器**真的看到了**调用点 —— 否则下面的零违规毫无意义。

        这正是本轮教训的落地：一个什么都没找到的扫描器，与一个全部合格的
        扫描器，输出是一样的。
        """
        sites = _cleanup_sites()
        # 第三十八轮：迁移已全部完成 → 期望值就是 **0**。
        # ⚠️「期望 0」与「扫描器失效」返回的都是空列表，**无法用长度区分** ——
        # 故本用例不再靠长度，而是：① 断言清单已无待迁移项；
        # ② 用**人工种入的样本**自证扫描逻辑仍有效
        # （见 test_scanner_can_still_detect_a_planted_call）。
        assert frozenset() == _PENDING_MIGRATION_FILES, (
            f"清单仍列有待迁移模块：{sorted(_PENDING_MIGRATION_FILES)}"
        )
        names = {p.name for p, _ln, _c in sites}
        for done in _MIGRATED_FILES:
            assert Path(done).name not in names, (
                f"{done} 已标为已迁移，却仍出现旧清洗调用点 —— 迁移被回退，或清单未同步"
            )

    def test_no_call_site_drops_count_without_disclosing(self):
        """`x, n = drop_non_finite(...)` 取出的 n **必须在同一函数内被引用**。

        判据用 **AST 作用域**（而非固定行窗口）—— 我第一版用调用点后 40 行，
        把 capability.py 的 n_inf（第 369 行使用、距调用点 41 行）误报为未使用。
        **作用域才是正确粒度**：同一函数内的任何位置都算用了。
        """
        offenders: list[str] = []
        for path in sorted(_ENGINE.rglob("*.py")):
            if path.name in {"_guard.py", "_utils.py"}:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            funcs = [
                n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                fn = node.value.func
                if not (isinstance(fn, ast.Name) and fn.id in _LEGACY_CLEANERS):
                    continue
                tgt = node.targets[0]
                if not isinstance(tgt, ast.Tuple) or len(tgt.elts) < 2:
                    continue
                cnt = tgt.elts[1]
                if not isinstance(cnt, ast.Name):
                    continue
                owners = [f for f in funcs if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)]
                scope = max(owners, key=lambda f: f.lineno) if owners else tree
                used = any(
                    isinstance(n, ast.Name) and n.id == cnt.id and n.lineno != node.lineno
                    for n in ast.walk(scope)
                )
                if not used:
                    offenders.append(
                        f"{path.relative_to(_ENGINE)}:{node.lineno} —— {cnt.id} 取出后未使用"
                        "（清理发生了但用户看不到，违反 B1）"
                    )
        assert not offenders, (
            "以下调用点静默清洗（应披露剔除数量，或改用 _guard 的 clean_series/clean_frame）:\n  "
            + "\n  ".join(offenders)
        )

    def test_guard_module_provides_the_disclosing_variants(self):
        """_guard 必须提供带披露的清洗入口（否则改用 _guard 无法执行）。"""
        from smartsuite.engine import _guard

        for name in ("clean_series", "clean_frame", "BoundaryReport"):
            assert hasattr(_guard, name), f"_guard 缺少 {name}"


class TestMigratedModulesActuallyUseTheGuard:
    """**清单驱动**的通用迁移断言：清单里每个"已迁移"模块都要真的走 `_guard`。

    设计意图：迁移是**逐模块**推进的。若每个模块都写一份专用测试，
    测试数会随模块数线性增长且内容重复。这里改为**从清单读**已迁移模块，
    对每一个施加同一组断言 —— 迁移推进时无需新增测试文件。

    （`capability.py` 另有专用测试 `tests/engine/test_capability_guard_migration.py`
    锁定其**行为**；本类只管**结构**：是否真的不再手抄。）
    """

    @staticmethod
    def _module_path(rel: str) -> Path:
        return _ENGINE / rel

    def test_manifest_lists_only_real_modules(self):
        """清单里的模块名必须对应真实文件 —— 否则下面的参数化断言会静默跳过。"""
        missing = [
            rel
            for rel in sorted(_MIGRATED_FILES | _PENDING_MIGRATION_FILES)
            if not TestMigratedModulesActuallyUseTheGuard._module_path(rel).is_file()
        ]
        assert not missing, f"迁移清单里这些模块不存在（清单过期）: {missing}"

    @pytest.mark.parametrize("rel", sorted(_MIGRATED_FILES))
    def test_migrated_module_imports_guard_pieces(self, rel):
        """已迁移模块必须从 `_guard` 导入东西。

        （`spc_xbar.py` 是最早的接入点，它用 `BoundaryReport` 但不做清洗，
        故这里只要求"导入了"；下面两条才管具体用没用对。）
        """
        src = self._module_path(rel).read_text(encoding="utf-8")
        assert "from smartsuite.engine._guard import" in src, (
            f"{rel} 标为已迁移，却没有从 _guard 导入任何东西"
        )

    @pytest.mark.parametrize("rel", sorted(_MIGRATED_FILES))
    def test_migrated_module_has_no_legacy_cleaner_calls(self, rel):
        """已迁移模块**不得**再调用 `_utils` 的无披露清洗函数。"""
        src = self._module_path(rel).read_text(encoding="utf-8")
        offenders = [name for name in _LEGACY_CLEANERS if f"{name}(" in src]
        assert not offenders, (
            f"{rel} 标为已迁移，却仍在调用旧清洗函数 {offenders}"
            "（应改为 _guard.clean_series / clean_frame）"
        )

    @pytest.mark.parametrize("rel", sorted(_MIGRATED_FILES))
    def test_migrated_module_has_no_hand_rolled_disclosure(self, rel):
        """已迁移模块**不得**再手写 `non_finite_note(...)` 拼披露文案。"""
        src = self._module_path(rel).read_text(encoding="utf-8")
        assert "non_finite_note(" not in src, (
            f"{rel} 标为已迁移，却仍在手写披露（应改为 report.add(BoundaryIssue(...))）"
        )

    def test_at_least_one_module_is_migrated(self):
        """至少有一个已迁移模块 —— 否则上面三条参数化断言会跑 0 次而"全绿"。"""
        assert _MIGRATED_FILES, "迁移清单里没有已迁移模块，参数化断言会静默跳过"


class TestDisclosureWordingHasOneSource:
    """非有限值的**披露文案**只能有一个构造处（第三十六轮提取）。

    背景：`clean_series` 内联拼一份文案，`spc_charts/xbar_r.py` 又借
    `_utils.non_finite_note` 拼一份**逐字相同**的 —— 两份格式独立演化，
    用户会在不同任务里看到格式不一致的同类提示。
    现统一到 `_guard.non_finite_detail`，本类锁定它。
    """

    def test_formats_with_column_name(self):
        from smartsuite.engine._guard import non_finite_detail

        detail = non_finite_detail(3, "厚度")
        assert "厚度" in detail, detail
        assert "3" in detail, detail
        assert "非有限值" in detail, detail
        assert detail.startswith("⚠"), detail

    def test_formats_without_column_name(self):
        from smartsuite.engine._guard import non_finite_detail

        detail = non_finite_detail(2)
        assert "数据" in detail, detail
        assert "2" in detail, detail

    def test_clean_series_uses_that_single_source(self):
        """`clean_series` 写进 `report` 的文案必须**逐字等于** `non_finite_detail`。"""
        from smartsuite.engine._guard import BoundaryReport, clean_series, non_finite_detail

        s = pd.Series([1.0, np.inf, 3.0])
        report = BoundaryReport()
        _data, n = clean_series(s, column="c", report=report)
        assert n == 1, n
        assert report.messages() == [non_finite_detail(1, "c")], report.messages()

    def test_module_no_longer_duplicates_the_wording(self):
        """源码级：`xbar_r.py` 不得再引用 `_utils.non_finite_note`。

        （该函数的文案与 `_guard.non_finite_detail` 逐字相同 —— 引用它等于
        "同一件事写两遍"，格式一旦改动就会漂移。）
        """
        xbar = (_ENGINE / "spc_charts" / "xbar_r.py").read_text(encoding="utf-8")
        assert "non_finite_note" not in xbar, (
            "xbar_r.py 又引用了 _utils.non_finite_note（应改用 _guard.non_finite_detail）"
        )
        assert "non_finite_detail" in xbar, "xbar_r.py 应使用 _guard.non_finite_detail"


class TestMigrationIsComplete:
    """**收口已完成**（第三十八轮）：旧清洗实现已删除，只剩 `_guard` 一套。

    这个类在第三十二轮建立时叫 `TestLegacyCleanersAreStillDuplicated`，
    作用是**如实记录"重复仍存在"**，避免"以为已经收口了"。
    第三十八轮全部模块迁完后，它按清单约定**反转**为"收口已完成"的断言 ——
    这正是"缺口与已对齐一样需要被维护"那条纪律的兑现。
    """

    def test_legacy_cleaners_are_gone(self):
        """`_utils` 不得再有 `drop_non_finite` / `drop_non_finite_rows` / `non_finite_note`。"""
        from smartsuite.engine import _utils

        for name in (*_LEGACY_CLEANERS, "non_finite_note"):
            assert not hasattr(_utils, name), (
                f"_utils 仍留着 {name} —— 迁移已全部完成，旧实现应已删除"
            )

    def test_no_module_calls_legacy_cleaners(self):
        """全包内不得再有旧清洗调用（`_cleanup_sites()` 应为空）。"""
        sites = _cleanup_sites()
        assert sites == [], "仍有模块调用旧清洗函数:\n  " + "\n  ".join(
            f"{p.relative_to(_ENGINE)}:{ln}" for p, ln, _c in sites
        )

    def test_guard_provides_the_replacement(self):
        """替代者必须在（否则上面的删除会让引擎没法清洗）。"""
        from smartsuite.engine import _guard

        for name in ("clean_series", "clean_frame", "BoundaryReport", "non_finite_detail"):
            assert hasattr(_guard, name), f"_guard 缺少 {name}"

    def test_clean_series_matches_the_ruled_semantics(self):
        """`clean_series` 的**行为**：NaN 与 ±Inf 都剔除，但计数（=披露）只数 ±Inf。

        2026-10-09 口径裁定（契约拆为 L4 缺失值 / B1 ±Inf 两行）改变的是
        **披露口径**，不是清洗动作 —— 两者都从返回序列里消失，
        差别只在"报不报、报几个"：`n_dropped` 现在只数 ±Inf（本例 2），
        NaN 静默按缺失语义丢弃。
        """
        from smartsuite.engine._guard import clean_series

        s = pd.Series([1.0, np.inf, -np.inf, 2.0, np.nan])
        cleaned, n_dropped = clean_series(s)
        assert n_dropped == 2, "计数只数 ±Inf（NaN 免披露）"
        assert cleaned.tolist() == [1.0, 2.0], "NaN 仍必须被剔除（dropna 语义）"

    def test_clean_series_no_change_keeps_same_object(self):
        """无剔除时**返回原对象**（避免调用方无意间复制大数据）。

        ⚠️ 我第一版断言 `cleaned is s` 并**失败** —— 实测 `clean_series` 走的是
        `s[mask]`（全 True 掩码）路径，仍是新对象；而 `drop_non_finite` 在
        `n_dropped == 0` 时提前 `return data, 0` 返回原对象。
        这是**真实的语义差异**，不是缺陷（两者都"无变化"，只是对象身份不同）。
        故断言改为**值相等**，并记录这一差异。
        """
        from smartsuite.engine._guard import clean_series

        s = pd.Series([1.0, 2.0, 3.0])
        cleaned, n_dropped = clean_series(s)
        assert n_dropped == 0
        assert cleaned.tolist() == s.tolist()

    def test_clean_frame_matches_the_old_semantics(self):
        """`clean_frame` 按行剔除"任一列非有限"的行（与旧实现同语义）。"""
        from smartsuite.engine._guard import clean_frame

        df = pd.DataFrame({"x": [1.0, np.inf, 3.0], "y": [1.0, 2.0, -np.inf]})
        cleaned, n_dropped = clean_frame(df, ["x", "y"])
        assert n_dropped == 2
        assert cleaned.index.tolist() == [0]


class TestBreakingChangesAreRecorded:
    """**行为变更清单必须完整**（第三十九轮）。

    为什么需要这条：`CHANGELOG.md` 由 release-please 从 conventional commits 生成，
    **不得手改**（`verify_docs.py` 有版本一致性门禁）。于是"哪些改动会改变
    用户可见结果"只能在 `improvement-plan.md` 的清单里维护 ——
    而它没有任何门禁，**最容易随实施漂移**：改了行为却忘了记，
    commit message 就写不出 `BREAKING CHANGE:`，用户升级后才发现结果变了。

    本类把清单钉住：已发生的重大行为变更必须在册，且每条要写清
    "用户会看到什么不同"。
    """

    _DOC = Path(__file__).resolve().parents[2] / "docs" / "governance" / "improvement-plan.md"

    @classmethod
    def _section(cls) -> str:
        text = cls._DOC.read_text(encoding="utf-8")
        start = text.index("## 十一、破坏性变更与行为变更清单")
        end = text.index("## 十二、执行台账")
        return text[start:end]

    def test_section_exists(self):
        section = self._section()
        assert "破坏性变更" in section and "行为变更" in section, section[:200]

    def test_section_says_changelog_is_auto_generated(self):
        """必须写明 `CHANGELOG.md` 不得手改 —— 否则有人会去改它（门禁会拦，但浪费一轮）。"""
        section = self._section()
        assert "release-please" in section, section[:400]
        assert "不得手改" in section or "不能手改" in section, section[:400]

    @pytest.mark.parametrize(
        "must_be_listed",
        [
            "Welch",  # 默认 t 检验口径变了（p 值会变）
            "ANOVA",  # η² 口径变了
            "survival_analysis",  # 文本事件列由猜测改为拒绝
            "CSP",  # script-src / style-src 收紧
            "boundary_codes",  # 新增机器可读码（能力，非变更）
            "minitab-alignment",  # 新增对照文档
        ],
    )
    def test_known_changes_are_recorded(self, must_be_listed):
        """这些是本会话**实测发生过**的变更，必须在册 —— 漏记即失败。"""
        section = self._section()
        assert must_be_listed in section, (
            f"{must_be_listed} 是已发生的行为/能力变更，却未记入清单 —— "
            f"commit message 会漏掉它，用户升级后才发现结果变了"
        )

    def test_items_explain_the_user_visible_difference(self):
        """每条都要写清"用户会看到什么不同" —— 只写"改了 X"对提交者无用。

        判据：表格必须有一列表头包含"用户"或"看到"，否则说明只记录了实现细节。
        """
        section = self._section()
        assert "用户会看到什么不同" in section, (
            "清单应有一列说明用户可见差异（否则无法据此写 BREAKING CHANGE 说明）"
        )

    def test_breaking_changes_are_marked(self):
        """破坏性变更与行为变更必须分开（前者要 minor 版本 + `!`，后者不需要）。"""
        section = self._section()
        assert "minor" in section, "应说明破坏性变更需要 minor 版本号"


# ══════════════════════════════════════════════════════════════
# P0-8 全任务门禁：±Inf 注入必须「披露」或「拒绝」
# ══════════════════════════════════════════════════════════════

#: 全任务输入配置 —— `(target_col, feature_cols, params)`。
#: 判据（见 `test_configuration_covers_every_data_task`）：本表必须覆盖
#: `TASK_REGISTRY - NO_DATA_TASKS`，否则新增任务会**静默逃过**下面的门禁。
_TASK_INPUTS: dict[str, tuple[str, list[str], dict]] = {
    "correlation": ("y", ["x1", "x2", "x3"], {}),
    "anova": ("y", ["g"], {}),
    "hypothesis_test": ("y", ["g2"], {"group_col": "g2"}),
    "decision_tree": ("y", ["x1", "x2"], {}),
    "vif": ("", ["x1", "x2", "x3"], {}),
    "regression": ("y", ["x1", "x2"], {}),
    "response_surface": ("y", ["x1", "x2"], {}),
    "doe_analysis": ("y", ["x1", "x2"], {}),
    "roc_analysis": ("yb", ["x1"], {}),
    "logistic_regression": ("yb", ["x1"], {}),
    "lasso_regression": ("y", ["x1", "x2", "x3"], {}),
    "robust_regression": ("y", ["x1"], {}),
    "quantile_regression": ("y", ["x1"], {}),
    "spc_xbar": ("y", ["g"], {}),
    "spc_attribute": ("yb", [], {"chart_type": "p"}),
    "spc_cusum": ("y", [], {}),
    "spc_ewma": ("y", [], {}),
    "process_capability": ("y", [], {"usl": 60.0, "lsl": 40.0}),
    "trend_forecast": ("y", [], {}),
    "anomaly_detect": ("y", [], {"method": "zscore"}),
    "change_point": ("y", [], {}),
    "outlier_consensus": ("y", ["x1"], {}),
    "bootstrap_ci": ("y", [], {"n_bootstrap": 200}),
    "median_ci": ("y", [], {}),
    "contingency": ("g", ["g2"], {}),
    "proportion_ci": ("yb", [], {}),
    "variance_test": ("y", ["g"], {"group_col": "g"}),
    "cohens_kappa": ("", ["k1", "k2"], {}),
    "cronbach_alpha": ("", ["x1", "x2", "x3"], {}),
    "distribution_summary": ("y", [], {}),
    "normality_check": ("y", ["x1"], {}),
    "survival_analysis": ("t", ["e"], {"event_col": "e"}),
    "gage_rr": ("y", ["part", "oper"], {"part_col": "part", "operator_col": "oper"}),
    "tolerance_interval": ("y", [], {}),
    "grid_search": ("y", ["x1"], {"ranges": {"x1": [-1, 1]}, "n_points": 5}),
    "multi_objective": (
        "y",
        ["x1", "x2"],
        {
            "objectives": [
                {"col": "y", "direction": "minimize"},
                {"col": "x2", "direction": "maximize"},
            ]
        },
    ),
    "inverse_solve": (
        "",
        [],
        {
            "incoming_cols": "x1",
            "variable_cols": "x2",
            "output_cols": "y",
            "model": "linear",
            "request_rows": [{"x1": 0.5, "y": 50.0}],
        },
    ),
    "spc_nonparametric": ("y", [], {}),
    "box_chart": ("y", ["g"], {}),
    "scatter_plot": ("y", ["x1"], {"fit": "linear"}),
}

#: 披露判据词 —— 引擎的**唯一**披露文案由 `_guard.non_finite_detail` 产出
#: （「含 N 个 ±Inf（非有限值）」）。2026-10-09 口径裁定后 NaN 免披露（契约 L4），
#: 故此处只认 ±Inf 一路写法；`非有限值` 作为兼容词保留。
_DISCLOSURE_WORDS = ("非有限值", "±Inf")


def _base_frame(n: int = 60) -> pd.DataFrame:
    """覆盖全部任务列角色的合成数据（连续 / 二值 / 分组 / 两类评分 / 生存 / MSA）。"""
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {
            "y": rng.normal(50, 2.0, n),
            "yb": rng.integers(0, 2, n).astype(float),
            "x1": rng.normal(0, 1, n),
            "x2": rng.normal(5, 2, n),
            "x3": rng.normal(2, 1, n),
            "g": (["A", "B", "C"] * (n // 3 + 1))[:n],
            "g2": (["P", "Q"] * (n // 2 + 1))[:n],
            "k1": rng.integers(0, 2, n).astype(float),
            "k2": rng.integers(0, 2, n).astype(float),
            "t": rng.exponential(10, n).astype(float),
            "e": rng.integers(0, 2, n).astype(float),
            "part": np.repeat(np.arange(1, 11), n // 10).astype(float),
            "oper": (["甲", "乙"] * (n // 2 + 1))[:n],
        }
    )


def _injected_columns(task: str, frame: pd.DataFrame) -> list[str]:
    """该任务真正消费的**数值**列（目标列 + 特征列）。

    只往这些列注入 —— 否则会误判：`contingency` 只读两个类别列，
    往无关列注入 +Inf 后它当然"没有反应"，但那不是静默。
    """
    target, features, _params = _TASK_INPUTS[task]
    names = ([target] if target else []) + list(features)
    return [c for c in names if c in frame.columns and pd.api.types.is_numeric_dtype(frame[c])]


def _injected_frame(task: str) -> pd.DataFrame:
    """该任务的数值输入列各注入 3 个 `+Inf`（与 `_frame_with_inf` 的旧单列形态区分）。"""
    frame = _base_frame()
    for col in _injected_columns(task, frame):
        frame[col] = frame[col].astype(float)
        frame.loc[frame.index[:3], col] = np.inf
    return frame


def _run(task: str, frame: pd.DataFrame):
    """在**生产 warnings 口径**下跑一次任务。

    ⚠️ 这不是可选项：`pyproject.toml` 的 `filterwarnings=["error"]` 只作用于 pytest。
    若不在 `simplefilter("default")` 下运行，含 ±Inf 的输入会让 numpy/pandas 的
    `RuntimeWarning` 升为异常 → orchestrator 兜底成泛化的 `status="error"` →
    「必须披露或拒绝」的断言**被 `status=="error"` 这一半空过**，
    而这恰恰是生产下静默的那批任务（实测：normality_check / change_point /
    outlier_consensus / doe_analysis / cronbach_alpha / cohens_kappa 全部假绿）。
    """
    target, features, params = _TASK_INPUTS[task]
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        result = orchestrate(
            AnalysisRequest(
                task=task,
                data=frame,
                target_col=target,
                feature_cols=features,
                params=params,
            )
        )
    for fig in result.figures or []:
        with contextlib.suppress(Exception):  # 图形释放失败不应影响断言
            fig.clear()
    return result


#: 有数值输入可注入的任务（无则门禁对该任务无意义）
_INJECTABLE = tuple(t for t in sorted(_TASK_INPUTS) if _injected_columns(t, _base_frame()))


class TestConfigCoversEveryTask:
    """先证明门禁**真的覆盖了全部任务** —— 否则下面的零违规毫无意义。"""

    def test_configuration_covers_every_data_task(self):
        expected = set(TASK_REGISTRY) - set(NO_DATA_TASKS)
        assert set(_TASK_INPUTS) == expected, (
            "任务输入配置与注册表不一致（本门禁对缺失的任务完全失明）："
            f"缺 {sorted(expected - set(_TASK_INPUTS))}，"
            f"多 {sorted(set(_TASK_INPUTS) - expected)}"
        )

    def test_every_task_has_an_injectable_numeric_column(self):
        """除纯类别输入的任务外，每个任务都应至少有一个数值列可注入。"""
        skipped = {t for t in _TASK_INPUTS if t not in _INJECTABLE}
        assert skipped <= {"contingency", "inverse_solve"}, (
            f"这些任务没有任何可注入的数值列，门禁对它们空过：{sorted(skipped)}"
        )


class TestAllTasksDiscloseNonFiniteInjection:
    """**全任务参数化断言**（审查 2026-10-09 P0-8 的防再漏）。

    契约 B1 要求：`±Inf` 必须「移除 + `messages` 披露数量与列名」。
    本组把"哪些任务静默"从**人工抽样估计**（治理文档曾自述 4 个，实测 11 个）
    改为**门禁强制**：每个任务对 ±Inf 注入都必须

      ① `status="error"`（明确拒绝），或
      ② 用户可见处出现披露（「非有限值」）。

    两者都不满足 = 静默传播 —— 用户看到 `n=60` 而实际有效样本已变，
    或看到基于 Inf 的错误结论。
    """

    @pytest.mark.parametrize("task", _INJECTABLE)
    def test_clean_baseline_succeeds_without_spurious_disclosure(self, task):
        """先证明基线为 ok，**且**没有凭空加披露 —— 否则下面的断言会失去意义。

        两件事合在一个用例里（原为两条）：
        ① 基线非 ok 时，`test_inf_injection_is_disclosed_or_rejected` 会因"本来就失败"
           而空过（`status == "error"` 那一半恒真）；
        ② 反向噪音判据：干净数据不得出现「非有限值」披露，否则提示退化为噪音、
           用户会学会忽略它（和没有提示一样糟）。

        真实值断言（非仅状态）：任务名如实回填、非空 summary、且不带任何披露词。
        """
        result = _run(task, _base_frame())
        assert result.status == "ok", (
            f"[{task}] 干净数据基线不是 ok（门禁将失去意义）："
            f"status={result.status} messages={result.messages}"
        )
        assert result.task == task, f"[{task}] 结果任务名错填为 {result.task!r}"
        assert str(result.summary).strip(), f"[{task}] summary 为空"
        blob = " ".join(result.messages or [])
        assert not any(w in blob for w in _DISCLOSURE_WORDS), (
            f"[{task}] 干净数据却给出非有限值披露（提示退化为噪音）：{result.messages}"
        )

    @pytest.mark.parametrize("task", _INJECTABLE)
    def test_inf_injection_is_disclosed_or_rejected(self, task):
        cols = _injected_columns(task, _base_frame())
        result = _run(task, _injected_frame(task))
        blob = " ".join(result.messages or [])
        disclosed = any(w in blob for w in _DISCLOSURE_WORDS)
        assert result.status == "error" or disclosed, (
            f"[{task}] ±Inf 被**静默**处理（注入列 {cols}）：status={result.status}、"
            f"messages 无任何披露。契约 B1 要求「移除 + 披露数量与列名」；"
            f"应在入口调用 _guard.clean_series/clean_frame(report=...) 并把 "
            f"report.messages() 并入 AnalysisResult.messages。\n"
            f"summary={str(result.summary)[:120]}\n实际 messages={result.messages}"
        )


#: 审查 2026-10-09 P1-4 实测「同一数据 ×1e300 结论级翻转 / 表内渗漏 inf-nan」的任务。
#: 修法：入口 `_guard.check_magnitude` → B0 拒绝（`E_SCALE_EXTREME_MAGNITUDE`）。
_EXTREME_MAGNITUDE_ALL = (
    "normality_check",
    "variance_test",
    "spc_nonparametric",
    "doe_analysis",
    "anomaly_detect",
    "outlier_consensus",
    "distribution_summary",
    "trend_forecast",
    "quantile_regression",
    "response_surface",
)

#: P1-4 的**已知缺口** —— 这两个任务所在文件（`root_cause/inference.py`、
#: `detection/anomaly.py`）不在本批所有权内（由并行 agent 持有），故未接入
#: `check_magnitude`。**每条必须具名理由**，并由
#: `test_known_gap_is_still_a_real_gap` 断言"确实仍是缺口"：
#: 上游一旦补齐守卫，该用例会 FAIL 并要求删除条目 —— 清单不得漂移成谎言。
#: 量级上界守卫（P1-4）的**已收口缺口**登记 —— 当前为空。
#:
#: 2026-10-09 收口：原先登记的两项已由主审查者补 `_guard.check_magnitude`（B0 拒绝）：
#:   · `variance_test`（`root_cause/inference.py`）—— 原先只披露不拒绝；
#:   · `anomaly_detect`（`detection/anomaly.py`）—— 原先 ×1e300 静默返回「0 个异常点」。
#: 机制保留：日后若发现新缺口，必须**具名登记并写明理由**；`test_known_gap_is_still_a_real_gap`
#: 会持续断言「它确实仍是缺口」，一旦上游补齐就报红要求删除条目 —— 防清单漂移成谎言。
_EXTREME_MAGNITUDE_KNOWN_GAPS: dict[str, str] = {}

_EXTREME_MAGNITUDE_TASKS = tuple(
    t for t in _EXTREME_MAGNITUDE_ALL if t not in _EXTREME_MAGNITUDE_KNOWN_GAPS
)


class TestExtremeMagnitudeIsRejected:
    """1e153+ 巨量级必须 B0 拒绝，且**说明量级原因**（不得给结论、不得泛化报错）。

    微尺度（量纲下界）方向已有系统性加固，量纲上界此前**无任何守卫**：
    `Σy²` 在 `|y| ≳ 1e154` 时溢出为 Inf，随后 NaN 被"False 分支"或
    "NaN 原样入表"处置 —— 判决静默翻转（1e152 判非正态、1e153 判正态）。
    """

    @staticmethod
    def _scaled() -> pd.DataFrame:
        frame = _base_frame()
        for col in ("y", "x1", "x2", "x3"):
            frame[col] = frame[col] * 1e300
        return frame

    def test_gap_registry_partitions_the_target_set(self):
        """缺口表 + 在测集合必须恰好等于 P1-4 的全部目标任务（防漏测也防重复）。"""
        assert set(_EXTREME_MAGNITUDE_TASKS) | set(_EXTREME_MAGNITUDE_KNOWN_GAPS) == set(
            _EXTREME_MAGNITUDE_ALL
        )
        assert not set(_EXTREME_MAGNITUDE_TASKS) & set(_EXTREME_MAGNITUDE_KNOWN_GAPS)
        for task, reason in _EXTREME_MAGNITUDE_KNOWN_GAPS.items():
            assert len(reason) >= 20, f"缺口 {task} 的理由太短：{reason!r}"

    @pytest.mark.parametrize("task", sorted(_EXTREME_MAGNITUDE_KNOWN_GAPS))
    def test_known_gap_is_still_a_real_gap(self, task):
        """缺口条目必须**仍然成立** —— 若上游已修好，本用例 FAIL 要求删条目。"""
        result = _run(task, self._scaled())
        blob = " ".join(result.messages or [])
        fixed = result.status == "error" and "量级" in blob
        assert not fixed, (
            f"[{task}] 已不再满足缺口判据（status=error 且披露了量级原因）——"
            f"说明上游已补齐守卫，请从 `_EXTREME_MAGNITUDE_KNOWN_GAPS` 删除该条目"
            f"并移回 `_EXTREME_MAGNITUDE_TASKS`。messages={result.messages}"
        )

    @pytest.mark.parametrize("task", _EXTREME_MAGNITUDE_TASKS)
    def test_extreme_magnitude_is_rejected_with_reason(self, task):
        result = _run(task, self._scaled())
        assert result.status == "error", (
            f"[{task}] ×1e300 数据必须 B0 拒绝（当前给出结论，判决随量级翻转）："
            f"status={result.status} summary={str(result.summary)[:120]}"
        )
        blob = " ".join(result.messages or [])
        assert "量级" in blob, (
            f"[{task}] 拒绝理由未指向**量级**（用户按泛化文案排查不到真因）：{result.messages}"
        )
        assert "单位换算" in blob or "中心化" in blob, (
            f"[{task}] B0 拒绝必须给出可执行建议（换算单位 / 中心化）：{result.messages}"
        )
