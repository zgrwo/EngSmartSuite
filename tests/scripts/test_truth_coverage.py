"""分析类数值真值覆盖率的 pytest 包装（选项 A，2026-09-24 用户选定）。

被包装的门禁：`scripts/truth_coverage.py`

## 为什么换掉原指标

原判据「有独立真值的测试 / **全部**测试」（≈6% → 目标 ≥25%）在第 43 轮
实测判定**结构性不可达**：1731 个测试函数中，「状态/文本」类（不崩 /
正确拒绝 / 文案正确）占 **32%** —— 其正确性判据本来就不是数值。
给它们塞数字断言会制造零信息断言，而 `scripts/test_quality_guard.py`
正是为拦截这类断言而存在的。

## 新口径

    「分析类任务的数值真值覆盖率」

分母只算**断言了分析结果数值**的测试（跑了 `AnalysisRequest` 且断言触及
`metadata`/`tables`/`summary`/`figures`，不是"仅 status / 仅文案"）；
分子是其中含 `pytest.approx(数字)` 的。

这条直接回答：**引擎算出的数，有多少被真值钉住？**

## 本文件的作用

1. 断言门禁**可运行**且数字**与代码一致**（防脚本坏掉后静默"通过"）；
2. 断言覆盖率**不低于记录的下限**（防退化）；
3. 断言**扫描器本身有效** —— 用人工样本证明它能把
   "有真值的测试"与"只有 status 的测试"区分开。
   （本会话已三次栽在"扫描器失效导致指标看起来没变"上。）
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "truth_coverage.py"


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


class TestTruthCoverageGate:
    """门禁可用性与下限。"""

    def test_script_exists(self):
        assert _SCRIPT.is_file(), f"缺少 {_SCRIPT}"

    def test_report_shape(self):
        data = _report()
        for key in ("truth", "result_asserts", "ratio", "floor"):
            assert key in data, f"报告缺 {key}"
        assert data["result_asserts"] > 0, "分母为 0 说明扫描器失效"
        assert 0.0 <= data["ratio"] <= 1.0

    def test_ratio_meets_recorded_floor(self):
        """覆盖率不得跌破下限（防退化）。

        实测基线（2026-09-24）：32/172 = 18.6%，下限 18%。
        """
        data = _report()
        assert data["ratio"] >= data["floor"], (
            f"覆盖率 {data['ratio']:.1%} 跌破下限 {data['floor']:.1%} —— "
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


class TestScannerIsEffective:
    """防"扫描器失效导致指标看起来没变"（本会话已三次踩坑）。"""

    def test_scanner_distinguishes_status_only_from_truth(self, tmp_path):
        """人工样本：只断言 status 的测试**不得**计入分子，含真值的**必须**计入。

        这条是本文件的核心防线 —— 若扫描器坏了（例如正则失配），
        分子恒为 0 或恒等于分母，而"18.6%"这类数字**看起来仍然正常**。
        """
        sys.path.insert(0, str(_ROOT / "scripts"))
        import truth_coverage as tc  # noqa: PLC0415

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
        num, den = tc._classify(sample)
        # 分母只含**触及结果**的那一条（`test_with_truth`）—— 另外两条
        # （仅 status / 仅文案）**按定义不进分母**，这正是本口径的意义所在。
        # ⚠️ 我上一版期望 den==2（把 status/文案两条也算进去）→ 失败，
        # 那是**我把口径记错了**，不是扫描器的错。
        assert den == 1, f"分母应只含触及结果的那条，实际 {den}"
        assert num == 1, f"该条含 approx(数字)，分子应为 1，实际 {num}"

    def test_status_only_tests_do_not_inflate_the_denominator(self, tmp_path):
        """**本口径的核心**：只断言 status / 文案的测试**不得**进分母。

        若扫描器坏了（例如把"跑了分析"当成"验了数值"），分母会虚高、
        覆盖率被稀释，而数字**看起来仍然正常**。本条即该情形的防线。
        """
        sys.path.insert(0, str(_ROOT / "scripts"))
        import truth_coverage as tc  # noqa: PLC0415

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
        num, den = tc._classify(sample)
        assert den == 0, f"仅 status/文案的测试不应进分母，实际 den={den}"
        assert num == 0
