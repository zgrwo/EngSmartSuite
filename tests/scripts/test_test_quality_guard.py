"""test_quality_guard.py 检测逻辑测试（弱断言 / 无意义命名 / 缺测）。

夹具文件刻意含弱断言与坏命名——守卫实现须将其列入自测豁免
（SELF_TEST_FILES = {"test_test_quality_guard.py"}），避免告警疲劳。
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "test_quality_guard.py"
mod = importlib.util.spec_from_file_location("test_quality_guard", SPEC)
guard = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(guard)


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── 弱断言检测 ───────────────────────────────────────────────


def test_weak_assert_only_detected(tmp_path):
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_result_not_none():\n    r = compute()\n    assert r is not None\n"),
    )
    problems = guard.check_weak_asserts(tests)
    assert any("test_result_not_none" in p for p in problems)


def test_strong_assert_not_flagged(tmp_path):
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_result_value():\n    r = compute()\n    assert r == 42\n"),
    )
    assert guard.check_weak_asserts(tests) == []


# ── 无意义命名检测 ───────────────────────────────────────────


def test_bad_test_name_detected(tmp_path):
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(root, "tests/test_demo.py", ("def test_1():\n    assert 1 == 1\n"))
    problems = guard.check_naming(tests)
    assert any("test_1" in p for p in problems)


def test_descriptive_name_not_flagged(tmp_path):
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root, "tests/test_demo.py", ("def test_divide_by_zero_returns_nan():\n    assert True\n")
    )
    assert guard.check_naming(tests) == []


# ── 缺测检测（src 公共函数 vs 测试引用）──────────────────────


def test_missing_test_reference_detected(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    tests = root / "tests"
    _write(root, "src/pkg/mod.py", "def orphan_func():\n    return 1\n")
    _write(root, "tests/test_mod.py", "def test_other():\n    assert True\n")
    problems = guard.check_missing_tests(src, tests)
    assert any("orphan_func" in p for p in problems)


def test_referenced_function_not_flagged(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    tests = root / "tests"
    _write(root, "src/pkg/mod.py", "def covered_func():\n    return 1\n")
    _write(root, "tests/test_mod.py", "def test_covered():\n    assert covered_func() == 1\n")
    assert guard.check_missing_tests(src, tests) == []


def test_private_functions_ignored(tmp_path):
    root = tmp_path / "repo"
    src = root / "src"
    tests = root / "tests"
    _write(root, "src/pkg/mod.py", "def _helper():\n    return 1\n")
    _write(root, "tests/test_mod.py", "def test_x():\n    assert True\n")
    assert guard.check_missing_tests(src, tests) == []


def test_self_test_file_exempt_from_weak_asserts(tmp_path):
    # 本文件（自测夹具）含弱断言式写法，必须被 SELF_TEST_FILES 豁免
    assert "test_test_quality_guard.py" in guard.SELF_TEST_FILES


# ── 状态断言分级（第二轮 #4b）────────────────────────────────


def test_error_status_assert_not_weak(tmp_path):
    """assert status == 'error' 是有效断言（error 路径验证），不判弱。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_error_path():\n    r = compute()\n    assert r.status == 'error'\n"),
    )
    assert guard.check_status_only_asserts(tests) == []
    assert guard.check_weak_asserts(tests) == []


def test_ok_status_only_still_weak(tmp_path):
    """仅 assert status == 'ok' 仍判弱（需配套具体值断言）。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_ok_only():\n    r = compute()\n    assert r.status == 'ok'\n"),
    )
    problems = guard.check_status_only_asserts(tests)
    assert any("test_ok_only" in p for p in problems)


# ── 恒真断言（第二轮 #4c）────────────────────────────────────


def test_ok_warning_tuple_not_always_true(tmp_path):
    """('ok','warning') 不含 error——error 结果会失败，是有效断言，不判恒真。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_ok_warning():\n    r = compute()\n    assert r.status in ('ok', 'warning')\n"),
    )
    assert guard.check_status_only_asserts(tests) == []


def test_ok_error_tuple_is_always_true(tmp_path):
    """('ok','error') 覆盖全部可能状态——判恒真。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        ("def test_ok_error():\n    r = compute()\n    assert r.status in ('ok', 'error')\n"),
    )
    problems = guard.check_status_only_asserts(tests)
    assert any("恒真" in p and "test_ok_error" in p for p in problems)


# ── 守卫架空（第二轮 #4a：AST 块归属 + else 双分支豁免）──────


def test_guard_with_else_both_assert_not_flagged(tmp_path):
    """if status=='ok' 有 else 且两分支都断言 → 不判守卫架空。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        (
            "def test_dual_branch():\n"
            "    r = compute()\n"
            "    if r.status == 'ok':\n"
            "        assert len(r.summary) > 0\n"
            "    else:\n"
            "        assert len(r.messages) > 0\n"
        ),
    )
    problems = guard.check_status_only_asserts(tests)
    assert not any("守卫架空" in p for p in problems)


def test_guard_without_else_flagged(tmp_path):
    """if status=='ok' 无 else 分支且守卫内断言 → 判守卫架空。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        (
            "def test_guarded():\n"
            "    r = compute()\n"
            "    if r.status == 'ok':\n"
            "        assert len(r.summary) > 0\n"
        ),
    )
    problems = guard.check_status_only_asserts(tests)
    assert any("守卫架空" in p and "test_guarded" in p for p in problems)


def test_error_guard_inside_not_flagged(tmp_path):
    """if status=='error' 守卫（非 ok 守卫）不触发架空检测。"""
    root = tmp_path / "repo"
    tests = root / "tests"
    _write(
        root,
        "tests/test_demo.py",
        (
            "def test_error_guard():\n"
            "    r = compute()\n"
            "    if r.status == 'error':\n"
            "        assert len(r.messages) > 0\n"
        ),
    )
    problems = guard.check_status_only_asserts(tests)
    assert not any("守卫架空" in p for p in problems)
