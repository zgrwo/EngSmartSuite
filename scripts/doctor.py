#!/usr/bin/env python3
"""
doctor.py — 环境就绪性诊断（Environment Doctor）

背景（源自 VibeCodingTemplate doctor.py）：
  verify_all.py 验证"项目正确性"，本脚本诊断"环境就绪性"——新开发者跑通门禁前的第一步。
  相比 verify 的 PASS/FAIL 门禁，doctor 给出可操作的修复指引（缺什么依赖、缺什么目录）。

用法：
  python scripts/doctor.py

检查项：
  - Python 版本（>=3.10）
  - git 仓库状态
  - 必需工具（ruff / pytest）
  - 关键目录（src / tests / rules / skills / scripts / templates / .github）
  - 关键文件（agents.md / pyproject.toml）

退出码：0 = 全部就绪；1 = 存在失败项（输出修复指引）
"""

import argparse
import contextlib
import subprocess
import sys
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 10)

# 必需目录/文件（相对 ROOT）——套件基线
REQUIRED_DIRS = ["src", "tests", "rules", "skills", "scripts", "templates", ".github"]
REQUIRED_FILES = ["agents.md", "pyproject.toml", "README.md"]
# 必需 Python 工具（import 名 + 包名）
REQUIRED_TOOLS = [
    ("ruff", "ruff"),
    ("pytest", "pytest"),
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def check_python() -> tuple[bool, str]:
    cur = sys.version_info[:2]
    ok = cur >= MIN_PYTHON
    return ok, (
        f"Python {cur[0]}.{cur[1]} >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
        if ok
        else f"Python {cur[0]}.{cur[1]} < {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    )


def check_git() -> tuple[bool, str]:
    r = _run(["git", "rev-parse", "--is-inside-work-tree"])
    if r.returncode == 0:
        return True, "git 仓库就绪"
    return False, "当前目录不在 git 仓库（git init 或进入仓库目录）"


def check_tool(import_name: str, package: str) -> tuple[bool, str]:
    try:
        __import__(import_name)
        return True, f"{package} 已安装"
    except ImportError:
        return False, f"{package} 未安装 — 运行: pip install {package}"


def check_dir(path: str) -> tuple[bool, str]:
    ok = (ROOT / path).is_dir()
    return ok, (f"{path}/ 存在" if ok else f"{path}/ 缺失（{ROOT / path}）")


def check_file(path: str) -> tuple[bool, str]:
    ok = (ROOT / path).is_file()
    return ok, (f"{path} 存在" if ok else f"{path} 缺失（{ROOT / path}）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="环境就绪性诊断")
    parser.parse_args(argv)

    checks: list[tuple[str, tuple[bool, str]]] = [
        ("Python 版本", check_python()),
        ("git", check_git()),
    ]
    for import_name, package in REQUIRED_TOOLS:
        checks.append((f"工具 {package}", check_tool(import_name, package)))
    for d in REQUIRED_DIRS:
        checks.append((f"目录 {d}/", check_dir(d)))
    for f in REQUIRED_FILES:
        checks.append((f"文件 {f}", check_file(f)))

    print("EngSmartSuite 环境检查")
    print("=" * 50)
    passed = failed = 0
    for _label, (ok, msg) in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {msg}")
        passed += ok
        failed += not ok
    print()
    print(f"结果: {passed} 项通过, {failed} 项失败")
    if failed:
        print("\n请修复上方 FAIL 项后运行验证：python scripts/verify_all.py")
        return 1
    print("\n环境就绪。可运行：python scripts/verify_all.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
