"""falsy_audit.py 门禁自测（审查 2026-09-06 G3：负向注入转正 tests/scripts）。

负向：注入 `if threshold:`（HIGH 风险数值变量）→ FAIL 且 exit=1，findings 点名；
      注入 `params.get(key) or default`（历史 M-4 同族，审查 2026-09-06 F-D2）
      → HIGH 键名 FAIL，未知键名 MEDIUM 可见不阻断。
正向：干净目录 → exit=0；
回归：真实仓库扫描范围（engine + services + web + cli）零 HIGH 守卫。

隔离要点：main() 会把 sys.stdout 换成「包装 sys.stdout.buffer 的新 TextIOWrapper」，
该包装被 GC 时会**关闭底层缓冲**——若直接跑在 pytest 捕获流上会污染会话级捕获
（teardown 报 "I/O operation on closed file"）。故测试自备 BytesIO 作为 stdout，
让 main 的包装只作用于测试自有缓冲；退出后读自有缓冲断言输出。
"""

import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "falsy_audit.py"
mod = importlib.util.spec_from_file_location("falsy_audit", SPEC)
falsy_audit = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(falsy_audit)


BAD_CODE = """\
def demo(threshold):
    if threshold:
        pass
    return threshold
"""


OR_CODE_HIGH = """\
def demo(params):
    n = params.get("contamination") or 1
    return n
"""


OR_CODE_MEDIUM = """\
def demo(params):
    n = params.get("unknown_key") or 3
    return n
"""


def _setup_scan_dirs(tmp_path, monkeypatch, file_code):
    """构造隔离扫描目录并替换模块级 SCAN_PATHS（保持与真实 main() 同路径）。"""
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    sample = scan_dir / "sample.py"
    sample.write_text(file_code, encoding="utf-8")
    # audit_file 用 ROOT 做 relative_to 展示，main() 读模块级 SCAN_PATHS——一并替换保持封闭
    monkeypatch.setattr(falsy_audit, "ROOT", tmp_path)
    monkeypatch.setattr(falsy_audit, "SCAN_PATHS", [scan_dir])
    return sample


def _run_main_expect_exit():
    """以自有 BytesIO 为 stdout 运行 main()，返回 (退出码, 输出文本)。

    关键：my_wrapper 必须用局部变量持有强引用——main() 替换 sys.stdout 的瞬间，
    原包装若无人引用会被 GC 并**关闭底层缓冲**，导致 main 内部 print 即报
    "I/O operation on closed file"。
    """
    own = io.BytesIO()
    saved = sys.stdout
    my_wrapper = io.TextIOWrapper(own, encoding="utf-8", errors="replace")
    sys.stdout = my_wrapper
    try:
        with pytest.raises(SystemExit) as excinfo:
            falsy_audit.main()
        sys.stdout.flush()
        return excinfo.value.code, own.getvalue().decode("utf-8", "replace")
    finally:
        sys.stdout = saved


def test_negative_injection_threshold_exits_1(tmp_path, monkeypatch):
    """注入 `if threshold:` → exit=1、HIGH=1，findings 点名 threshold/行号（6.4 契约）。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, BAD_CODE)
    code, out = _run_main_expect_exit()
    assert code == 1
    assert "HIGH:   1" in out
    findings = falsy_audit.audit_file(sample)
    assert any(f["risk"] == "HIGH" and f["var"] == "threshold" and f["line"] == 2 for f in findings)


def test_negative_injection_or_default_exits_1(tmp_path, monkeypatch):
    """注入 `params.get(key) or default`（历史 M-4 同款）→ exit=1，HIGH 点名键名（F-D2）。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, OR_CODE_HIGH)
    code, out = _run_main_expect_exit()
    assert code == 1, f"params.get('contamination') or 1 应判 HIGH: {out}"
    assert "HIGH:   1" in out
    findings = falsy_audit.audit_file(sample)
    or_findings = [f for f in findings if f.get("kind") == "or_default"]
    assert any(
        f["var"] == "contamination" and f["risk"] == "HIGH" and f["line"] == 2 for f in or_findings
    ), f"findings 应点名 contamination: {or_findings}"


def test_or_default_unknown_key_medium_not_blocking(tmp_path, monkeypatch):
    """未知键名的 `or` 回退 → MEDIUM（可见不阻断），gate 依旧 exit=0。"""
    sample = _setup_scan_dirs(tmp_path, monkeypatch, OR_CODE_MEDIUM)
    code, out = _run_main_expect_exit()
    assert code == 0
    findings = falsy_audit.audit_file(sample)
    assert any(
        f.get("kind") == "or_default" and f["var"] == "unknown_key" and f["risk"] == "MEDIUM"
        for f in findings
    ), f"未知键 or 回退应记 MEDIUM: {findings}"


def test_clean_dir_exits_0(tmp_path, monkeypatch):
    """无 HIGH 风险的干净文件 → exit=0、HIGH=0（`if flag:` 为 LOW，仍入 findings 但不阻断）。"""
    sample = _setup_scan_dirs(
        tmp_path, monkeypatch, "def demo(flag):\n    if flag:\n        pass\n    return flag\n"
    )
    code, out = _run_main_expect_exit()
    assert code == 0
    assert "HIGH:   0" in out
    findings = falsy_audit.audit_file(sample)
    assert not any(f["risk"] == "HIGH" for f in findings)


def test_real_repo_scan_zero_high():
    """真实仓库扫描范围（engine+services+web+cli）守卫：零 HIGH（若引入 HIGH 模式应修源码）。"""
    code, _ = _run_main_expect_exit()
    assert code == 0
