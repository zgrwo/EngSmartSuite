#!/usr/bin/env python3
"""
test_quality_guard.py — 测试质量守卫（弱断言/缺测/命名）

背景（来源：VibeCodingTemplate test-quality-guard.py）：
  lint 与覆盖率只保证"测试存在"，不保证"测试有效"。本脚本检测三类测试质量问题：
    1. 弱断言：`assert x is not None` / `assert len(x) > 0` 等作为**唯一**断言的测试方法
       （验证了"不是空"，但没有验证具体值，任何非空结果都能通过——形同虚设）
    2. 缺测：src/ 下公共函数无对应测试引用（源码改动了测试没跟上）
    3. 命名：测试方法名非描述性（test_1 / test_caseN 等无意义名）

用法：
  python scripts/test_quality_guard.py            # 基础检查（默认 src=src, tests=tests）

退出码：0 = 通过（弱断言仅 WARN）；1 = 存在 FAIL（缺测/命名）
"""

import argparse
import ast
import contextlib
import re
import sys
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# 弱断言模式：只有这类断言，无具体值验证
_WEAK_ASSERT_RE = re.compile(
    r"assert\s+\w+\s+is\s+not\s+None"  # assert x is not None
    r"|assert\s+len\([^)]*\)\s*[><]=?\s*0"  # assert len(x) > 0
    r"|assert\s+\w+\s*!=\s*None"  # assert x != None
    r"|assert\s+bool\("  # assert bool(x)
)
# 真实断言（验证具体值）
# expr 支持下标/属性/方法调用（df["col"].sum() == 5）、len(...)==N/!=N 形式
_STRONG_ASSERT_RE = re.compile(
    r"assert\s+\w+(?:\[.*?\]|\.\w+(?:\(.*?\))?)*\s*[=!]=\s*\w+(?:\(.*?\))?"
    r"|assert\s+\w+\s*in\s+"  # assert x in ...
    r"|assert\s+\w+(?:\[.*?\]|\.\w+(?:\(.*?\))?)*\s*[<>]=?\s*\w+(?:\(.*?\))?"
    r"|assert\s+\w+\s*is\s+True"  # assert x is True
    r"|assert\s+\w+\s*is\s+False"
    r"|assert\s+len\([^)]*\)\s*[=!]=\s*\S+"  # assert len(x) == N / != N
    r"|pytest\.raises"  # 异常断言
    # 审查 2026-08-19 #3.5：补充常见强断言形态（此前误报为弱）
    r"|assert\s+(?:all|any)\("  # assert all(...) / any(...)
    r"|assert\s+not\s+"  # assert not ...
    r"|assert\s+['\"]"  # assert "..." in / 与字面量比较
    r"|assert\s+\w+\.\w+\("  # assert x.isna()... 方法调用
)
# 无意义测试名：test_<纯数字/序号/caseN>
_BAD_NAME_RE = re.compile(r"test_(?:\d+|case\d+|test\d+|a|b|c|foo|bar|dummy)$")

# 审查 2026-08-19 #3.5 新增三类检测：
# 1) 仅状态断言：assert x.status == "ok"（带引号值，旧正则既不弱也不强 → 漏检）
_STATUS_ONLY_ASSERT_RE = re.compile(
    r"assert\s+\w+(?:\[[^\]]*\]|\.\w+)*\s*==\s*(?:['\"](?:ok|error|warning)['\"]|[A-Z_]+)"
)
# 2) 恒真断言：assert status in ("ok","error") —— 任何结果都通过
_ALWAYS_TRUE_STATUS_RE = re.compile(
    r"assert\s+\w+(?:\.\w+)*\s+in\s+\(\s*(?:['\"]ok['\"])\s*,\s*(?:['\"](?:error|warning)['\"])"
)
# 3) 守卫架空：if result.status == "ok": 内嵌断言（引擎报错时测试空转通过）
_STATUS_GUARD_RE = re.compile(r"if\s+\w+(?:\.\w+)*\.status\s*==\s*(?:['\"]ok['\"]|OK):")

# 自测夹具文件：刻意含弱断言以验证守卫逻辑，不应触发自 WARN（告警疲劳）
SELF_TEST_FILES = {"test_test_quality_guard.py"}

# 既有公共函数缺测豁免（每项必须注明理由；新增公共函数一律不豁免）：
#   - read_excel_range / to_excel：依赖 xlwings + Excel 实例（add-in 遗留路径，
#     docstring 明确 Web/CLI 不调用；导出请用 audit.export_workbook）
#   - upload / analyze / list_tasks / column_info / require_csrf / csrf_token：
#     Flask 视图/辅助函数，经 tests/test_web_e2e.py HTTP 层端到端覆盖，
#     直接函数级测试需 request context，收益低
EXEMPT_FUNCS = {
    "read_excel_range",
    "to_excel",
    "upload",
    "analyze",
    "list_tasks",
    "column_info",
    "require_csrf",
    "csrf_token",
}


def _rel(path: Path) -> str:
    """输出相对路径；位于仓库外时回退绝对路径（防 relative_to ValueError）。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _extract_test_methods(path: Path) -> list[tuple[str, str]]:
    """解析 Python 测试文件，返回 [(方法名, 方法源码)]。"""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    methods: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            src = ast.get_source_segment(text, node) or ""
            methods.append((node.name, src))
    return methods


def _method_has_strong_assert(src: str) -> bool:
    """方法体是否含真实断言（排除注释）。"""
    for line in src.splitlines():
        stripped = line.split("#", 1)[0]
        if _STRONG_ASSERT_RE.search(stripped):
            return True
    return False


def _method_is_weak_only(src: str) -> bool:
    """方法只有弱断言（且无强断言）→ 视为弱。"""
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    return bool(_WEAK_ASSERT_RE.search(code)) and not _method_has_strong_assert(src)


def _assert_lines(code_lines: list[str]) -> list[tuple[str, str]]:
    """返回 [(assert 行原文, 缩进)]。"""
    out = []
    for line in code_lines:
        stripped = line.strip()
        if stripped.startswith("assert"):
            indent = len(line) - len(line.lstrip())
            out.append((stripped, indent))
    return out


def check_status_only_asserts(tests_dir: Path) -> list[str]:
    """检测三类隐蔽弱断言（审查 2026-08-19 #3.5，WARN 不阻断）：
    1) assert x.status == "ok" 仅状态断言（旧正则漏检）
    2) assert status in ("ok","error") 恒真断言
    3) if status=="ok": 守卫架空（引擎报错时空转通过）
    """
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        if p.name in SELF_TEST_FILES:
            continue
        for name, src in _extract_test_methods(p):
            code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
            code = "\n".join(code_lines)
            rel = _rel(p)
            if _ALWAYS_TRUE_STATUS_RE.search(code):
                problems.append(
                    f"[WARN] {rel}:{name} 恒真断言（status in (ok,error)）——任何结果都能通过，"
                    "请断言具体数值/状态"
                )
            # 守卫行缩进：逐行匹配（search 的 start() 是拼接串索引，不可用于行定位）
            guard_indent = None
            for _line in code_lines:
                if _STATUS_GUARD_RE.search(_line):
                    guard_indent = len(_line) - len(_line.lstrip())
                    break
            if guard_indent is not None:
                # 守卫块内是否存在更深缩进的断言
                has_guarded_assert = any(
                    stripped.startswith("assert") and indent > guard_indent
                    for stripped, indent in _assert_lines(code_lines)
                )
                if has_guarded_assert:
                    problems.append(
                        f"[WARN] {rel}:{name} 断言被 if status=='ok' 守卫架空——"
                        "引擎报错时测试空转通过，应改为前置硬断言"
                    )
            asserts = _assert_lines(code_lines)
            if not asserts:
                continue
            has_strong = _method_has_strong_assert(src)
            only_status = all(
                _STATUS_ONLY_ASSERT_RE.search(stripped) or _WEAK_ASSERT_RE.search(stripped)
                for stripped, _ in asserts
            )
            if asserts and not has_strong and only_status:
                problems.append(
                    f"[WARN] {rel}:{name} 仅状态/弱断言（status=='ok' 或 is not None）——"
                    "不验证具体值，请补真实断言"
                )
    return problems


def check_weak_asserts(tests_dir: Path) -> list[str]:
    """检测弱断言测试方法（WARN，不阻断）。"""
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        if p.name in SELF_TEST_FILES:
            continue
        for name, src in _extract_test_methods(p):
            if _method_is_weak_only(src):
                rel = _rel(p)
                problems.append(
                    f"[WARN] {rel}:{name} 仅弱断言（is not None / len>0 / bool()），"
                    "不验证具体值——任何非空结果都能通过，请补真实断言"
                )
    return problems


def check_naming(tests_dir: Path) -> list[str]:
    """检测无意义测试命名（FAIL）。"""
    problems: list[str] = []
    if not tests_dir.is_dir():
        return problems
    for p in sorted(tests_dir.rglob("test_*.py")):
        for name, _ in _extract_test_methods(p):
            if _BAD_NAME_RE.search(name):
                rel = _rel(p)
                problems.append(
                    f"[FAIL] {rel}:{name} 无意义测试名——请改为描述性名称"
                    "（如 test_divide_by_zero_returns_nan）"
                )
    return problems


def check_missing_tests(src_dir: Path, tests_dir: Path) -> list[str]:
    """src/ 公共函数 vs tests/ 测试引用对应检测（防"改代码没更测试"）。"""
    problems: list[str] = []
    if not src_dir.is_dir() or not tests_dir.is_dir():
        return problems
    tested: set[str] = set()
    for p in tests_dir.rglob("test_*.py"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tested.update(re.findall(r"\b(\w+)\(", text))
    for p in sorted(src_dir.rglob("*.py")):
        if p.name.startswith("__"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            is_public = isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
            if is_public and node.name not in tested and node.name not in EXEMPT_FUNCS:
                rel = _rel(p)
                problems.append(f"[FAIL] {rel}:{node.name} 无对应测试引用——新增公共函数必须配测试")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测试质量守卫")
    parser.add_argument("--src", default="src", help="源码目录（默认 src）")
    parser.add_argument("--tests", default="tests", help="测试目录（默认 tests）")
    args = parser.parse_args(argv)

    src_dir = ROOT / args.src
    tests_dir = ROOT / args.tests

    problems: list[str] = []
    problems += check_weak_asserts(tests_dir)
    problems += check_status_only_asserts(tests_dir)
    problems += check_naming(tests_dir)
    problems += check_missing_tests(src_dir, tests_dir)

    if not problems:
        print("[OK] 测试质量守卫通过")
        return 0
    for p in problems:
        print(p)
    if any(p.startswith("[FAIL]") for p in problems):
        return 1
    print("[OK] 测试质量守卫通过（仅弱断言 WARN，已提示）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
