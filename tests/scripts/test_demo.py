"""`scripts/demo.py` 端到端契约（审查 2026-09-19 C6）。

演示脚本是「新用户接触项目的第一条命令」，因此按**用户实际用法**验证：以子进程跑
`python scripts/demo.py --outdir <tmp>`，断言退出码、产出文件名与报告体积。

不 import 模块而走子进程：既避开 scripts/ 的导入路径约定，也顺带验证「脚本可独立
执行」这件事本身（`python scripts/demo.py` 是 README 与 gallery 承诺的入口）。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEMO = _ROOT / "scripts" / "demo.py"
_EXPECTED = {"correlation.html", "process_capability.html", "regression.html"}


def _run_demo(outdir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DEMO), "--outdir", str(outdir), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_ROOT,
    )


def test_demo_produces_three_self_contained_reports(tmp_path):
    """一条命令出三份报告，且每份都非空壳（自包含 HTML 内嵌图表 → 体积可观）。"""
    proc = _run_demo(tmp_path)

    assert proc.returncode == 0, f"demo 应成功退出：\n{proc.stdout[-800:]}\n{proc.stderr[-800:]}"
    assert "完成 3/3" in proc.stdout, proc.stdout[-500:]

    produced = {p.name for p in tmp_path.glob("*.html")}
    assert produced == _EXPECTED, f"实际产出：{sorted(produced)}"
    for name in _EXPECTED:
        size = (tmp_path / name).stat().st_size
        assert size > 10_000, f"{name} 体积过小（{size}B），可能未内嵌图表"


def test_demo_all_tasks_report_ok_status(tmp_path):
    """三个任务都必须成功 —— 演示数据变更导致失败时应在此处立即暴露。"""
    proc = _run_demo(tmp_path)

    assert proc.stdout.count("✓") == 3, proc.stdout
    assert "✗" not in proc.stdout, f"有任务失败：{proc.stdout}"


def test_demo_png_flag_exports_figures(tmp_path):
    """`--png` 额外导出图片文件（默认只出 HTML）。"""
    proc = _run_demo(tmp_path, "--png")

    assert proc.returncode == 0, proc.stderr[-500:]
    pngs = sorted(p.name for p in tmp_path.glob("*.png"))
    assert pngs, "指定 --png 后应有图片产出"
    assert all(p.stat().st_size > 0 for p in tmp_path.glob("*.png"))


def test_demo_reports_are_written_to_requested_dir(tmp_path):
    """输出目录可指定且会被自动创建（用户不必先 mkdir）。"""
    target = tmp_path / "nested" / "out"

    proc = _run_demo(target)

    assert proc.returncode == 0, proc.stderr[-500:]
    assert target.is_dir()
    assert {p.name for p in target.glob("*.html")} == _EXPECTED


@pytest.mark.parametrize("bad_dir", ["/nonexistent-root-dir/deep"])
def test_demo_fails_visibly_when_data_dir_missing(tmp_path, bad_dir):
    """数据目录不存在时必须明确报错且退出码非 0（不得静默产出空目录）。"""
    proc = _run_demo(tmp_path, "--data-dir", bad_dir)

    assert proc.returncode != 0, "缺数据时应失败退出"
    assert "缺少演示数据" in proc.stdout
