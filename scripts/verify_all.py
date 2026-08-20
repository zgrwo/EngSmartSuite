#!/usr/bin/env python3
"""
verify_all.py — 全量验证入口（一个命令完成全部治理验证）

职责：构建 + 测试 + 文档/测试质量验证一站式运行。
设计（源自 VibeCodingTemplate verify-all.py）：
  - 步骤失败即停（fail-fast），退出码可直接用于 CI 或提交前自检
  - 未检测到构建系统时显式 [跳过] 并提示，不假装通过

步骤清单（适配套件治理脚本）：
  1. 构建（compileall src/ 语法检查）
  2. 测试（pytest tests/）
  3. 文档一致性（verify_docs.py --strict：断链/目录树/裸异常/版本漂移）
  4. Falsy 审计（falsy_audit.py）
  5. 测试质量守卫（test_quality_guard.py：弱断言/缺测/命名）

注：verify_consistency.py（含 pytest 子进程，重）与 verify_manual_claims.py
（需真实分析运行）不纳入本入口，由 CI full job 与发布前流程覆盖。

用法：
  python scripts/verify_all.py            # 全量验证
  python scripts/verify_all.py --quick    # 仅构建 + 测试（跳过文档检查）

退出码：0 = 通过；非 0 = 失败（CI 可直接调用）
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run_step(name: str, cmd: list[str]) -> bool:
    """运行一个验证步骤，返回是否成功。"""
    print(f"\n=== {name} ===")
    print(f"  命令: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=ROOT)
    except OSError as e:
        print(f"  [FAIL] {name} 失败（工具未找到: {e}）")
        return False
    if result.returncode != 0:
        print(f"  [FAIL] {name} 失败 (退出码 {result.returncode})")
        return False
    print(f"  [OK] {name} 通过")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全量验证入口")
    parser.add_argument("--quick", action="store_true", help="仅构建 + 测试（跳过文档检查）")
    args = parser.parse_args(argv)

    # 审查 2026-08-19 #5.2：--basetemp 固定独立临时目录，
    # 避免 Windows 上 pytest-current junction 残留导致 sessionfinish 清理失败
    import tempfile as _tempfile

    _pytest_base = [
        PYTHON,
        "-m",
        "pytest",
        "tests/",
        "-q",
        f"--basetemp={os.path.join(_tempfile.gettempdir(), 'ss-verifyall-basetmp')}",
    ]
    steps: list[tuple[str, list[str]]] = [
        ("构建（语法检查）", [PYTHON, "-m", "compileall", "-q", "src"]),
        ("测试", _pytest_base),
    ]
    if not args.quick:
        steps += [
            ("文档一致性", [PYTHON, "scripts/verify_docs.py", "--strict"]),
            ("Falsy 审计", [PYTHON, "scripts/falsy_audit.py"]),
            ("测试质量守卫", [PYTHON, "scripts/test_quality_guard.py"]),
        ]

    all_passed = True
    for name, cmd in steps:
        if not run_step(name, cmd):
            all_passed = False
            break  # 任一步失败立即停止

    if all_passed:
        print("\n[OK] 全量验证通过")
        return 0
    print("\n[FAIL] 验证失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())
