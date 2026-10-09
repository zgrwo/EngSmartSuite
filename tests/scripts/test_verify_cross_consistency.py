"""`verify_cross_consistency.py` 的**手册覆盖度**门禁自测（审查 2026-10-09 G-7）。

## 背景：job 名"手册数值一致性"高估了覆盖面

`quality.yml` 的 `manual-parity` job 跑本脚本，但脚本只校验
`MANUAL_EXPECTATIONS` 登记的 **11/42** 个任务（`process_capability` 不在其中）。
实测注入：把手册 §7.5 的 `Cp 1.279` 改成 `1.100` → 本脚本
`用户手册验证: 11/11 passed` + `*** ALL PASSED ***` + **exit 0**（假绿）。
真实漂移由 `ci.yml quick` 的 `verify_manual_claims.py`（38 条 CLAIM）兜住，
故定级 P2；问题是**分母口径可疑 + job 名过度声称**。

## 本文件的判据

① 脚本必须**如实报告**覆盖面（登记项 / 手册含数值结果的任务节 / 全部任务）；
② 登记表**只增不减**（`MANUAL_REGISTRY_FLOOR`）——删条目 = 把门禁调松，必须 FAIL；
③ 手册含数值结果的任务节数不得低于 `MANUAL_SECTION_FLOOR`（手册被删减即 FAIL）；
④ 每个登记项都必须对得上手册里含数值的任务节，除非具名登记
   `MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC`（防"登记到不存在的节 → 静默空转"）；
⑤ job 名不得再声称全量（写实为"抽样"并指向真正承担全量的门禁）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_cross_consistency.py"
QUALITY_YML = ROOT / ".github" / "workflows" / "quality.yml"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

#: 本脚本是**模块级脚本**（末尾 `sys.exit`），不得 `exec_module` 进测试进程 ——
#: 实测会把测试会话的退出码污染成 0 并让 pytest 报 INTERNALERROR
#: （`tooling-pitfalls.md` #20 同族：验证脚本的 `__main__` 守卫被绕过）。
#: 故：常量/判据走 `--json` 出口，纯函数走**子进程垫片**（见 `_shim`）。
_SHIM = """
import importlib.util
import json
import sys


def _plain(obj):
    if isinstance(obj, (set, frozenset, tuple)):
        return [_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


spec = importlib.util.spec_from_file_location("vcc_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass
calls = json.loads(sys.argv[2])
out = [[name, _plain(mod.__dict__[name](*args))] for name, args in calls]
print("__JSON__" + json.dumps(out, ensure_ascii=False))
"""


#: 逐函数在子进程里的调用缓存（键 = (函数名, 参数元组)）。
#:
#: ⚠️ 每次垫片调用都要**导入整个引擎与脚本主体**（实测 ≈30s）。故本文件在会话开始时
#: 由 `_warm_shims` **一次性**批量执行全部需要的调用并缓存 ——
#: 否则 14 条用例要跑 8 分钟（实测 443s，v1 形态）。
_CACHE: dict[tuple, object] = {}


def _shim(func: str, *args):
    """读预热缓存里的垫片结果（未预热即报错，防止又退化成 N 次子进程）。"""
    key = (func, args)
    if key not in _CACHE:
        raise AssertionError(
            f"垫片调用未预热：{key!r}。请在 `_warm_shims` 的 `_pending_seed` 里登记 ——"
            "本文件规定所有跨进程调用一次性批量执行（每次调用 ≈30s）"
        )
    return _CACHE[key]


def _run_pending(calls: list[tuple[str, tuple]]) -> None:
    """一次性跑掉一批垫片调用并写入 `_CACHE`。"""
    if not calls:
        return
    payload = [[func, list(args)] for func, args in calls]
    proc = subprocess.run(
        [sys.executable, "-c", _SHIM, str(SCRIPT), json.dumps(payload)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    assert proc.returncode == 0, f"垫片失败：\n{proc.stdout}\n{proc.stderr}"
    marker = [ln for ln in proc.stdout.splitlines() if ln.startswith("__JSON__")]
    assert marker, f"垫片无输出：\n{proc.stdout[-800:]}"
    results = json.loads(marker[-1][len("__JSON__") :])
    assert len(results) == len(calls), f"垫片返回条数不符：{len(results)} != {len(calls)}"
    for key, (_name, value) in zip(calls, results, strict=True):
        _CACHE[key] = value


def _warm_shims(manual_dir: Path) -> None:
    """预热本文件用到的全部垫片调用（一次子进程搞定）。"""
    if _CACHE:
        return
    _run_pending(
        [
            ("_registered_manual_tasks", ()),
            ("_manual_sections_total", (str(manual_dir),)),
            ("_manual_sections_with_numbers", (str(manual_dir),)),
            ("_manual_has_numeric_result", ("### 7.9 异常共识\n\n本节只讲方法与图。\n",)),
            ("_manual_has_numeric_result", ("| 指标 | 值 |\n|---|---|\n| A | 无 |\n",)),
            ("_manual_has_numeric_result", ("| Cp (短期能力) | 1.279 |\n",)),
        ]
    )


@pytest.fixture(scope="module", autouse=True)
def _prewarm_shims():
    """会话级预热：全部跨进程调用一次性完成。"""
    _warm_shims(ROOT / "docs" / "user-manual")
    yield


_REPORT_CACHE: dict | None = None


def _report(tmp_path: Path) -> dict:
    """真实跑一次门禁并取回机器可读报告（脚本 `--json` 出口）。

    本次运行约 30 秒，故**模块级缓存**：同一 pytest 会话内只跑一次。
    """
    global _REPORT_CACHE
    if _REPORT_CACHE is None:
        out = tmp_path / "xc.json"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        assert proc.returncode == 0, f"门禁失败：\n{proc.stdout}\n{proc.stderr}"
        assert out.is_file(), f"--json 未产出报告：\n{proc.stdout}"
        _REPORT_CACHE = json.loads(out.read_text(encoding="utf-8"))
    return _REPORT_CACHE


class TestManualSectionDetection:
    """「含数值结果的任务节」检测本身必须有效（G-6b 的教训：判据看不见 = 假绿）。"""

    def test_real_manual_detects_expected_number_of_sections(self):
        registered = _shim("_registered_manual_tasks")
        assert len(registered) == 11, f"登记表应为 11 项（实测基线），实际 {len(registered)}"
        sections_total = _shim("_manual_sections_total", str(ROOT / "docs" / "user-manual"))
        assert sections_total == 42, f"手册任务节 {sections_total} != 42（TASK_REGISTRY）"
        with_numbers, _ = _shim("_manual_sections_with_numbers", str(ROOT / "docs" / "user-manual"))
        assert len(with_numbers) >= 28, (
            f"检出含数值结果的任务节 {len(with_numbers)} 个，低于实测基线 28"
            " —— 检测口径失效或手册被删减"
        )

    def test_every_registered_check_has_a_numeric_manual_section(self, tmp_path):
        """每个登记项（除具名例外）都必须落在"含数值结果"的任务节里。

        否则该登记项检查的是手册里根本不存在的结果值 —— 看起来"有分母"，
        实际上永远对不上，属静默空转。
        """
        data = _report(tmp_path)
        with_numbers, _total = _shim(
            "_manual_sections_with_numbers", str(ROOT / "docs" / "user-manual")
        )
        exempt = set(data.get("manual_checks_without_manual_numeric") or [])
        registered = _shim("_registered_manual_tasks")
        stray = sorted(set(registered) - set(with_numbers) - exempt)
        assert not stray, f"登记项对不上手册含数值节（静默空转）: {stray}"

    def test_numeric_result_detection_is_not_trivially_true(self):
        """**负向**：纯散文节（无小数结果）不得被判为"含数值结果"。"""
        assert (
            _shim("_manual_has_numeric_result", "### 7.9 异常共识\n\n本节只讲方法与图。\n") is False
        )
        assert (
            _shim("_manual_has_numeric_result", "| 指标 | 值 |\n|---|---|\n| A | 无 |\n") is False
        )
        # 反面：真结果行必须被认出来
        assert _shim("_manual_has_numeric_result", "| Cp (短期能力) | 1.279 |\n") is True


class TestCoverageIsReportedHonestly:
    """覆盖度必须可见、可核对，且不得缩水。"""

    def test_report_fields_present_and_consistent(self, tmp_path):
        data = _report(tmp_path)
        for key in (
            "manual_registered",
            "manual_checks_total",
            "manual_sections_with_numbers",
            "manual_sections_total",
            "manual_registry_floor",
            "manual_section_floor",
            "task_registry_size",
            "manual_coverage_problems",
        ):
            assert key in data, f"报告缺 {key}"
        assert data["manual_coverage_problems"] == [], data["manual_coverage_problems"]
        assert data["manual_checks_total"] == data["manual_registered"], (
            "分母必须等于登记条目数常量（分母守恒）"
        )
        assert data["manual_registered"] >= data["manual_registry_floor"], (
            "登记表缩水：删条目 = 把门禁调松"
        )
        assert data["manual_sections_with_numbers"] >= data["manual_section_floor"]
        assert data["task_registry_size"] == 42, "TASK_REGISTRY 应为 42 个任务"
        assert data["manual_checks_passed"] <= data["manual_checks_total"]

    def test_registry_and_section_floors_are_pinned(self, tmp_path):
        """两条下限必须钉在当前实测值上（只准增加）。"""
        data = _report(tmp_path)
        assert data["manual_registry_floor"] == 11, (
            "登记数下限被改动 —— 若是有意增加登记项，请同步上调；若是删条目，那是把门禁调松，不允许"
        )
        assert data["manual_registered"] >= 11
        assert data["manual_section_floor"] == 28, (
            "手册含数值结果节的下限被改动（实测 28/42，只准增加）"
        )

    def test_shrink_is_detected_by_the_scanner(self, tmp_path):
        """**负向注入**：手册被删减必须被检出（判据真的会 bite）。

        只对**伪造目录**跑一次垫片（真实手册那次已在预热批里），断言检出数远低于
        下限 ⇒ 脚本主体会把 `len(with_numbers) < MANUAL_SECTION_FLOOR`
        写进 `manual_coverage_problems` 并使 exit_code=1（同段逻辑，见脚本汇总段）。
        """
        tiny = tmp_path / "user-manual"
        tiny.mkdir()
        (tiny / "07-spc.md").write_text(
            "### 7.5 过程能力 Cp/Cpk (`process_capability`)\n\n本节无结果值。\n",
            encoding="utf-8",
        )
        _run_pending([("_manual_sections_with_numbers", (str(tiny),))])
        with_numbers, total = _shim("_manual_sections_with_numbers", str(tiny))
        assert total == 1 and len(with_numbers) == 0
        assert len(with_numbers) < 28, "伪造手册未被判为低于下限 —— 判据失效"

    def test_script_prints_coverage_line(self, tmp_path):
        """人类可读输出必须写明覆盖度（否则 job 名的高估无人察觉）。"""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", str(tmp_path / "x.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        assert "手册覆盖度（G-7）" in proc.stdout, proc.stdout[-1200:]
        assert "只校验登记表内的任务" in proc.stdout, "输出未写实覆盖面"


class TestQualityJobNameIsHonest:
    """`quality.yml` 的 job 名不得再声称"手册数值一致性"（全量）。"""

    @staticmethod
    def _data() -> dict:
        return yaml.safe_load(QUALITY_YML.read_text(encoding="utf-8"))

    def test_job_name_declares_sampling(self):
        name = self._data()["jobs"]["manual-parity"]["name"]
        assert "抽样" in name or "登记" in name, f"manual-parity 的 job 名仍过度声称全量: {name!r}"
        assert "手册数值一致性" in name, "job 名应保留可检索的主题词"

    def test_job_name_points_to_full_coverage_gate(self):
        """写实之后必须指明"全量由谁承担"，否则读者不知道该信哪个 job。"""
        name = self._data()["jobs"]["manual-parity"]["name"]
        assert "ci.yml" in name or "CLAIM" in name, (
            f"job 名未指向真正承担全量的门禁（ci.yml 的手册 CLAIM）：{name!r}"
        )
        ci = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        runs = "\n".join(s.get("run") or "" for s in ci["jobs"]["quick"]["steps"])
        assert "verify_manual_claims.py" in runs, (
            "ci.yml quick 未跑 verify_manual_claims.py —— job 名的指向落空"
        )

    def test_job_still_runs_the_gate_script(self):
        steps = self._data()["jobs"]["manual-parity"]["steps"]
        runs = "\n".join(s.get("run") or "" for s in steps)
        assert "scripts/verify_cross_consistency.py" in runs, "manual-parity 未跑本门禁"


@pytest.mark.parametrize("task", ["correlation", "process_capability", "vif"])
def test_registered_task_exists_in_registry(task, tmp_path):
    """登记项必须都是真实任务（防拼写漂移让检查静默失效）。"""
    data = _report(tmp_path)
    assert data["task_registry_size"] == 42
    registered = set(_shim("_registered_manual_tasks"))
    assert task in registered, f"{task} 不在登记表内"


def test_exemptions_are_really_registered_checks(tmp_path):
    """`MANUAL_CHECKS_WITHOUT_MANUAL_NUMERIC` 的键必须是真登记项且写明理由。"""
    data = _report(tmp_path)
    exemptions = data.get("manual_checks_without_manual_numeric") or {}
    assert isinstance(exemptions, dict), "例外表应是 {任务: 理由}"
    registered = set(_shim("_registered_manual_tasks"))
    for task, reason in exemptions.items():
        assert task in registered, f"{task} 不是登记项，例外无意义"
        assert reason and len(reason.strip()) >= 10, f"{task} 的理由过短: {reason!r}"
