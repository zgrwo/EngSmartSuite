"""分析类数值真值覆盖率的 pytest 包装（选项 A，2026-09-24 用户选定）。

被包装的门禁：`scripts/truth_coverage.py`

## 为什么换掉原指标

原判据「有独立真值的测试 / **全部**测试」（≈6% → 目标 ≥25%）在第 43 轮
实测判定**结构性不可达**：1731 个测试函数中，「状态/文本」类（不崩 /
正确拒绝 / 文案正确）占 **32%** —— 其正确性判据本来就不是数值。
给它们塞数字断言会制造零信息断言，而 `scripts/test_quality_guard.py`
正是为拦截这类断言而存在的。

## 新口径

分母只算**断言了分析结果数值**的测试（跑了 `AnalysisRequest` 且断言触及
`metadata`/`tables`/`summary`/`figures`，不是"仅 status / 仅文案"）；
分子只算其中的**独立真值**（外部裁判：手工公式 / statsmodels / scipy /
手册原文 / 数据端解析值）。

这条直接回答：**引擎算出的数，有多少被独立真值钉住？**

## 本文件的作用

1. 断言门禁**可运行**且数字**与代码一致**（防脚本坏掉后静默"通过"）；
2. 断言覆盖率**不低于记录的下限**（防退化）；
3. 断言**扫描器本身有效** —— 用人工样本证明它能把"有真值的测试"与
   "只有 status 的测试"区分开，并把"引擎自洽锁"从分子里摘出去
   （审查 2026-10-09 P2-14）；
4. 断言**解析失败不静默**（审查 2026-10-09 P3-10）。
   （本会话已三次栽在"扫描器失效导致指标看起来没变"上。）
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "truth_coverage.py"

sys.path.insert(0, str(_ROOT / "scripts"))
import truth_coverage as tc  # noqa: E402


def _report() -> dict:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert proc.returncode == 0, f"门禁失败：\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


#: 登记为「引擎自洽锁」但**允许 0 命中**的条目（须注明理由，防登记表腐烂）。
_ALLOW_ZERO_HIT = {
    # 该文件用 `_compare_3paths` 助手而非直接 `orchestrate(`，当前不在分母内
    "tests/services/test_manual_parity.py",
}


class TestTruthCoverageGate:
    """门禁可用性与下限。"""

    def test_script_exists(self):
        assert _SCRIPT.is_file(), f"缺少 {_SCRIPT}"

    def test_report_shape(self):
        data = _report()
        for key in (
            "truth",
            "snapshot_locks",
            "result_asserts",
            "ratio",
            "floor",
            "snapshot_hits",
            "parse_errors",
        ):
            assert key in data, f"报告缺 {key}"
        assert data["result_asserts"] > 0, "分母为 0 说明扫描器失效"
        assert 0.0 <= data["ratio"] <= 1.0
        assert data["truth"] + data["snapshot_locks"] <= data["result_asserts"], (
            "分子（独立真值 + 自洽锁）不得超过分母"
        )

    def test_ratio_meets_recorded_floor(self):
        """覆盖率不得跌破下限（防退化）。

        实测基线（2026-10-09，分子分级口径）：20/174 = 11.5%
        （同日复测 22/176 = 12.5%，随各批次合入浮动），下限 10%。
        ⚠️ 旧口径（含引擎自洽锁）为 18.6%/下限 18% —— 数字下降是**口径变严**。
        """
        data = _report()
        assert data["ratio"] >= data["floor"], (
            f"独立真值覆盖率 {data['ratio']:.1%} 跌破下限 {data['floor']:.1%} —— "
            "新增分析测试若只断言 status，或既有真值断言被删，会触发本断言"
        )

    def test_floor_actually_bites(self):
        """把下限抬到当前值之上时门禁必须失败 —— 否则它是个摆设。

        （一个永远通过的门禁与没有门禁等价。）
        """
        data = _report()
        stricter = min(0.99, data["ratio"] + 0.2)
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--floor", str(stricter)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        assert proc.returncode == 1, "抬低下限后门禁仍通过 —— 门禁未生效"
        assert "FAIL" in proc.stdout


class TestSnapshotLockRegistry:
    """审查 2026-10-09 P2-14：引擎自洽锁不得计入独立真值。"""

    def test_real_repo_snapshot_locks_are_detected(self):
        """登记表里的条目必须真的命中（防"登记了但从未生效"）。"""
        data = _report()
        hits = data["snapshot_hits"]
        stale = []
        for key in tc.ENGINE_SNAPSHOT_LOCKS:
            if key in _ALLOW_ZERO_HIT:
                continue
            if "::" in key:
                rel, name = key.split("::", 1)
                if name not in hits.get(rel, []):
                    stale.append(key)
            elif not hits.get(key):
                stale.append(key)
        assert not stale, f"以下自洽锁登记未命中任何测试（登记表已腐烂）: {stale}"

    def test_manual_scale_invariance_tests_are_not_counted_as_truth(self):
        """实测：微尺度守卫与不变量测试的 `approx(期望)` 取自引擎自身另一尺度输出。"""
        data = _report()
        assert data["snapshot_locks"] >= 12, (
            f"自洽锁应至少 12 条（实测 7 微尺度 + 4 不变量 + 1 图表内部一致性），"
            f"实际 {data['snapshot_locks']}"
        )

    def test_snapshot_marker_downgrades_truth(self, tmp_path):
        """就地标记 `# truth-source: engine-snapshot` → 该测试计入自洽锁而非独立真值。"""
        sample = tmp_path / "test_marker.py"
        sample.write_text(
            "import pytest\n"
            "from smartsuite.core.contracts import AnalysisRequest\n"
            "from smartsuite.services.orchestrator import orchestrate\n"
            "\n"
            "def test_engine_snapshot():\n"
            "    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
            "    # truth-source: engine-snapshot  期望值抄自引擎上次输出\n"
            "    assert r.metadata['cp'] == pytest.approx(1.3333, abs=0.01)\n",
            encoding="utf-8",
        )
        num, snap, den, err, names = tc._classify(sample)
        assert err == "" and den == 1
        assert (num, snap) == (0, 1), f"标记为引擎快照应计入 snap：num={num} snap={snap}"
        assert names == ["test_engine_snapshot"]

    def test_independent_marker_overrides_registry(self, tmp_path, monkeypatch):
        """`# truth-source: independent` 覆盖登记表（就地认定为独立真值）。"""
        monkeypatch.setitem(tc.ENGINE_SNAPSHOT_LOCKS, "tests/fake/test_x.py", "测试用登记")
        monkeypatch.setattr(tc, "ROOT", tmp_path)
        sample = tmp_path / "tests" / "fake" / "test_x.py"
        sample.parent.mkdir(parents=True)
        sample.write_text(
            "import pytest\n"
            "from smartsuite.core.contracts import AnalysisRequest\n"
            "from smartsuite.services.orchestrator import orchestrate\n"
            "\n"
            "def test_external():\n"
            "    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
            "    # truth-source: independent  期望值取自手册原文\n"
            "    assert r.metadata['cp'] == pytest.approx(1.3333, abs=0.01)\n",
            encoding="utf-8",
        )
        num, snap, den, err, _names = tc._classify(sample)
        assert err == "" and den == 1
        assert (num, snap) == (1, 0), f"independent 标记应覆盖登记表：num={num} snap={snap}"


class TestScannerIsEffective:
    """防"扫描器失效导致指标看起来没变"（本会话已三次踩坑）。"""

    def test_scanner_distinguishes_status_only_from_truth(self, tmp_path):
        """人工样本：只断言 status 的测试**不得**计入分子，含真值的**必须**计入。

        这条是本文件的核心防线 —— 若扫描器坏了（例如正则失配），
        分子恒为 0 或恒等于分母，而"11.5%"这类数字**看起来仍然正常**。
        """
        sample = tmp_path / "test_sample.py"
        sample.write_text(
            "import pytest\n"
            "from smartsuite.core.contracts import AnalysisRequest\n"
            "from smartsuite.services.orchestrator import orchestrate\n"
            "\n"
            "def test_status_only():\n"
            "    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
            "    assert r.status == 'ok'\n"
            "\n"
            "def test_with_truth():\n"
            "    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
            "    assert r.metadata['cp'] == pytest.approx(1.3333, abs=0.01)\n"
            "\n"
            "def test_message_only():\n"
            # ⚠️ 三个样本**都必须真的跑分析** —— 我首版让这一条没有
            # `orchestrate(`，于是它被 `RUNS_ANALYSIS` 过滤掉、分母只有 1 而非 2。
            # 教训：**给扫描器做自测时，样本必须与真实测试走同一路径**，
            # 否则测的是"扫描器对这个假样本的行为"，而不是真实场景。
            "    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
            "    assert '常量' in r.messages[0]\n",
            encoding="utf-8",
        )
        num, snap, den, err, _names = tc._classify(sample)
        # 分母只含**触及结果**的那一条（`test_with_truth`）—— 另外两条
        # （仅 status / 仅文案）**按定义不进分母**，这正是本口径的意义所在。
        assert err == ""
        assert den == 1, f"分母应只含触及结果的那条，实际 {den}"
        assert num == 1, f"该条含 approx(数字)，独立真值应为 1，实际 {num}"
        assert snap == 0

    def test_status_only_tests_do_not_inflate_the_denominator(self, tmp_path):
        """**本口径的核心**：只断言 status / 文案的测试**不得**进分母。

        若扫描器坏了（例如把"跑了分析"当成"验了数值"），分母会虚高、
        覆盖率被稀释，而数字**看起来仍然正常**。本条即该情形的防线。
        """
        q = chr(39)
        body = "".join(
            f"def test_{name}():\n"
            f"    r = orchestrate(AnalysisRequest(task={q}x{q}, data=None, target_col={q}y{q}))\n"
            f"    {assertion}\n\n"
            for name, assertion in (
                ("status_only", f"assert r.status == {q}ok{q}"),
                ("message_only", f"assert {q}常量{q} in r.messages[0]"),
            )
        )
        sample = tmp_path / "test_sample2.py"
        sample.write_text(
            "import pytest\n"
            "from smartsuite.core.contracts import AnalysisRequest\n"
            "from smartsuite.services.orchestrator import orchestrate\n\n" + body,
            encoding="utf-8",
        )
        num, snap, den, _err, _names = tc._classify(sample)
        assert den == 0, f"仅 status/文案的测试不应进分母，实际 den={den}"
        assert num == 0
        assert snap == 0


class TestParseFailureIsNotSilent:
    """审查 2026-10-09 P3-10：解析失败不得静默从分母消失。"""

    def test_bom_file_is_parsed(self, tmp_path):
        """带 BOM 的测试文件必须被正常解析（`utf-8` 会 SyntaxError）。"""
        sample = tmp_path / "test_bom.py"
        sample.write_bytes(
            b"\xef\xbb\xbf"
            + (
                b"import pytest\n"
                b"from smartsuite.core.contracts import AnalysisRequest\n"
                b"from smartsuite.services.orchestrator import orchestrate\n"
                b"\n"
                b"def test_with_truth():\n"
                b"    r = orchestrate(AnalysisRequest(task='x', data=None, target_col='y'))\n"
                b"    assert r.metadata['cp'] == pytest.approx(1.3333, abs=0.01)\n"
            )
        )
        num, _snap, den, err, _names = tc._classify(sample)
        assert err == "", f"BOM 不应导致解析失败: {err}"
        assert (num, den) == (1, 1), "带 BOM 的文件必须照常计入分子/分母"

    def test_parse_failure_is_reported_and_fails_gate(self, tmp_path, monkeypatch, capsys):
        """语法错误的文件 → 计入 `parse_errors` 且门禁 FAIL（旧行为是静默跳过）。"""
        tests_dir = tmp_path / "tests"
        (tests_dir / "engine").mkdir(parents=True)
        (tests_dir / "engine" / "test_broken.py").write_text("def test_x(:\n    pass\n")
        monkeypatch.setattr(tc, "ROOT", tmp_path)
        data = tc.collect()
        assert [r["file"] for r in data["parse_errors"]] == ["tests/engine/test_broken.py"]
        assert tc.main(["--json"]) == 1, "存在解析失败时门禁必须返回 1"
        capsys.readouterr()
        assert tc.main([]) == 1
        out = capsys.readouterr().out
        assert "无法解析" in out and "test_broken.py" in out

    def test_real_repo_has_no_parse_errors(self):
        """真实仓库当前不得有无法解析的测试文件。"""
        data = _report()
        assert data["parse_errors"] == [], f"存在无法解析的测试文件: {data['parse_errors']}"


@pytest.mark.parametrize(
    "marker", ["# truth-source: engine-snapshot", "# truth-source: independent"]
)
def test_markers_are_recognized(marker):
    """标记常量必须与登记表用法一致（防拼写漂移使标记静默失效）。"""
    assert marker in (tc.SNAPSHOT_MARKER, tc.INDEPENDENT_MARKER)
