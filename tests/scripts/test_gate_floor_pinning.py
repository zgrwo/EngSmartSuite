"""门禁下限的**独立钉桩**（审查 2026-10-09 G-5，维度 E1 自校验）。

## 背景：期望值取自被测实现 = 门禁自我放行

`scripts/truth_coverage.py` 的 `FLOOR` 是"独立真值覆盖率不得跌破"的唯一防退化锚点，
而它**就在被它约束的脚本里**。原包装测试 `tests/scripts/test_truth_coverage.py:94-105`
的判据是 `data["ratio"] >= data["floor"]`，`data["floor"]` 由被测脚本自己回填 ——
实测把 `FLOOR` 从 0.10 改成 0.01 后，包装测试仍 **25 passed / EXIT 0**：
门禁给自己发了通行证。

## 本文件的作用

把下限的**期望值**从被测脚本里**独立**出来（字面量 `EXPECTED_FLOOR`），使：

  · 单改 `truth_coverage.py` 的 `FLOOR`（不改本文件）→ **FAIL**；
  · 要合法调整下限，必须**同时**改本文件的字面量 —— 一次可见、可审、
    会被 review 拦下的改动，而不是一次静默的自我放行。

这与 `ai-review-prompt.md`「期望值不得取自被测实现」同一条纪律；
同族先例：`tests/scripts/test_verify_docs.py` 对问题集的独立期望。

⚠️ 本文件**不得**把 `EXPECTED_FLOOR` 写成 `truth_coverage.FLOOR` ——
那正是本条要修的自校验形态。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "truth_coverage.py"

sys.path.insert(0, str(ROOT / "scripts"))
import truth_coverage as tc  # noqa: E402

#: 独立下限期望（**字面量**，2026-10-09 审查 G-5 钉桩）。
#:
#: 与 `scripts/truth_coverage.py` 的 `FLOOR` 必须相等。调整下限时两处一起改，
#: 并在两边都写清"为什么这次可以降/必须升"（只升不降是默认纪律）。
EXPECTED_FLOOR = 0.10

#: 余量下限（百分点）：覆盖率基线 12.2%（22/180）与下限 10% 之间应有实际缓冲。
#: 若基线退化到"贴着下限"，本断言先红 —— 比等到跌破下限才发现更早。
MIN_MARGIN_PP = 1.0

#: CI 强制点：`ci.yml` quick job 通过 tests/scripts/ 跑本包装；`verify_all.py`
#: 是唯一直接跑 truth_coverage 的本地入口。下限只有在**至少一处**被强制执行才有意义。
GATE_ENTRYPOINTS = ("tests/scripts/test_truth_coverage.py", "scripts/verify_all.py")


def _report() -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert proc.returncode == 0, f"门禁失败：\n{proc.stdout}\n{proc.stderr}"
    import json

    return json.loads(proc.stdout)


class TestFloorIsPinnedIndependently:
    """下限常量的期望值必须**独立于**被测脚本。"""

    def test_floor_literal_is_exactly_pinned(self):
        """`FLOOR` 必须等于本文件的独立字面量（改脚本不改本文件即 FAIL）。"""
        assert tc.FLOOR == EXPECTED_FLOOR, (
            f"scripts/truth_coverage.py 的 FLOOR={tc.FLOOR!r} 与本文件的独立期望 "
            f"EXPECTED_FLOOR={EXPECTED_FLOOR!r} 不一致。\n"
            "若这是**有意**下调下限：请同时改 tests/scripts/test_gate_floor_pinning.py "
            "的 EXPECTED_FLOOR 并在理由里说明；若只是为了让覆盖率门禁变绿，"
            "那是自校验（审查 G-5），不允许。"
        )

    def test_reported_floor_matches_pinned_literal(self):
        """门禁**报告出来的** floor 也必须等于独立字面量（防 CLI 内改口径）。"""
        data = _report()
        assert data["floor"] == EXPECTED_FLOOR, (
            f"门禁报告 floor={data['floor']!r}，独立期望 {EXPECTED_FLOOR!r}"
        )

    def test_expanded_floor_still_fails(self):
        """**反面守卫**：把门禁下限抬到本文件的独立期望之上仍必须 FAIL。

        证明"比较运算符接通"这件事不能替代"期望值正确"，但仍是必要的另一半 ——
        若门禁对任何 floor 都返回 0，上面两条断言也没有意义。
        """
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--floor", str(EXPECTED_FLOOR * 3)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert proc.returncode == 1, f"抬高下限后仍通过（门禁未生效）：\n{proc.stdout}"
        assert "FAIL" in proc.stdout

    def test_ratio_keeps_real_margin_over_pinned_floor(self):
        """当前覆盖率必须比独立下限高出至少 `MIN_MARGIN_PP` 个百分点。

        （基线随各批次合入测试浮动，但"贴着下限"本身就是该报警的状态。）
        """
        data = _report()
        margin_pp = (data["ratio"] - EXPECTED_FLOOR) * 100
        assert margin_pp >= MIN_MARGIN_PP, (
            f"独立真值覆盖率 {data['ratio']:.2%} 距下限 {EXPECTED_FLOOR:.0%} 仅 "
            f"{margin_pp:.2f}pp（要求 ≥ {MIN_MARGIN_PP}pp）——"
            "覆盖率正在贴近下限，请补独立真值断言而不是下调下限"
        )

    def test_floor_is_actually_enforced_somewhere(self):
        """下限必须真的在某个入口被强制执行（否则钉住的是个没人跑的数）。"""
        missing = [p for p in GATE_ENTRYPOINTS if not (ROOT / p).is_file()]
        assert not missing, f"下限的强制入口不存在: {missing}"
        pkg = (ROOT / "tests/scripts/test_truth_coverage.py").read_text(encoding="utf-8")
        assert 'data["ratio"] >= data["floor"]' in pkg or (
            "data['ratio'] >= data['floor']" in pkg
        ), "包装测试未断言 ratio >= floor（下限在 CI 路径上无人执行）"


class TestPinnedFloorMatchesDocumentedBaseline:
    """下限与运行输出/文档记录的口径不得分叉。"""

    @staticmethod
    def _run(*extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    def test_default_run_prints_pinned_floor(self):
        """默认运行必须打印**被钉住**的下限（防"打印 10% 却按 1% 判"）。"""
        proc = self._run()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert f"{EXPECTED_FLOOR * 100:.1f}%" in proc.stdout, (
            f"运行输出未出现独立钉住的下限 {EXPECTED_FLOOR * 100:.1f}%：\n{proc.stdout}"
        )

    def test_explicit_floor_is_echoed_verbatim(self):
        """显式传入的 floor 必须原样出现在输出里（输出的是**判定用的那个值**）。

        这条同时锁住"打印与判定同源"：若某天输出改成常量而判定仍用 CLI 参数
        （或反之），`--floor 0.99` 的回显就会对不上。
        """
        proc = self._run("--floor", "0.99")
        assert proc.returncode == 1, f"floor=0.99 应失败：\n{proc.stdout}"
        assert "99.0%" in proc.stdout, f"输出未回显判定用的下限：\n{proc.stdout}"
        assert f"{EXPECTED_FLOOR * 100:.1f}%" != "99.0%"

    def test_pinned_literal_is_documented_as_only_up(self):
        """常量注释必须写明「只升不降」并指向本文件（防后来者顺手改）。

        只断言**契约性文字**（"只升不降" + 指向本测试文件的说明）——
        这部分是搭配本轮修复一起写入脚本的；FLOOR 数值本身由上面三条判据钉住。
        """
        src = SCRIPT.read_text(encoding="utf-8")
        for token in ("只升不降", "test_gate_floor_pinning.py", "不得就地调低"):
            assert token in src, f"truth_coverage.py 的 FLOOR 注释缺 {token!r}（钉桩说明已丢失）"
