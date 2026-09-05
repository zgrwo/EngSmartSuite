#!/usr/bin/env python3
"""
run_affected_tests.py — 影响范围测试路由（git-diff → 受影响测试）

背景（来源：VibeCodingTemplate run-affected-tests.py）：
  全量测试耗时较长，增量开发只该跑受影响的测试。本脚本用 git diff
  定位变更的源文件，按映射表路由到对应测试，只运行受影响的部分。

映射约定（套件专属，见 map_source_to_tests）：
  - src/smartsuite/engine/*.py      → tests/test_engine/
  - src/smartsuite/services/*.py    → tests/test_services/
  - src/smartsuite/core/*.py        → tests/test_services/
  - src/smartsuite/web/*.py         → E2E + 集成测试（web 变更影响面最大）
  - src/smartsuite/cli.py           → 集成 + 差分测试
  - scripts/*.py / *.sh             → tests/scripts/ 下 stem 子串匹配；
                                      无匹配时 *.md/*.sh/*.yaml 等文档/配置类 → SKIP
  - templates/*.yaml                → 服务层 + 工作流测试；
                                      new_analysis.py/README.md 脚手架 → SKIP
  - tests/**                        → 直接运行变更的测试文件
  - 文档/配置变更（*.md / .github/）→ SKIP（无测试）
  - 无匹配 → FAIL（提示"可能缺测"，不静默跳过，防门禁说谎）

用法：
  python scripts/run_affected_tests.py                # 默认：HEAD~1 变更
  python scripts/run_affected_tests.py --base main    # 对比 main..HEAD
  python scripts/run_affected_tests.py --dry-run      # 只打印将运行的测试

退出码：0 = 找到并（尝试）运行；1 = 无对应测试 / git 错误 / 测试失败
"""

import argparse
import contextlib
import subprocess
import sys
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# 映射表：src 子目录前缀 → 目标测试（目录或文件，相对 ROOT）
_SRC_TEST_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("src/smartsuite/engine/", ("tests/test_engine",)),
    ("src/smartsuite/services/", ("tests/test_services",)),
    ("src/smartsuite/core/", ("tests/test_services",)),
    (
        "src/smartsuite/web/",
        (
            "tests/test_web_e2e.py",
            "tests/test_integration.py",
            "tests/test_integration_chemical.py",
            "tests/test_integration_reliability.py",
            "tests/test_integration_warranty.py",
        ),
    ),
    (
        "src/smartsuite/cli.py",
        ("tests/test_integration.py", "tests/test_master_integration.py", "tests/test_services"),
    ),
    (
        "templates/",
        ("tests/test_services", "tests/test_workflows.py"),
    ),
]

# 免测路径前缀（文档/配置/CI，SKIP）
_SKIP_PREFIXES = (
    "skills/",
    "docs/",
    ".github/",
    ".claude/",
    ".qoder/",
    "logs/",
)
_SKIP_SUFFIXES = (".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini", ".bat", ".sh")

# 既有治理脚本豁免（早于本工具，已由 CI 直接执行覆盖，见 ci.yml/quality.yml）：
#   新增脚本不在此列——必须配 tests/scripts/ 测试（缺测即失败，防门禁说谎）
_EXEMPT_SCRIPTS = {
    "common.py",
    "doctor.py",  # 环境诊断胶水（交互工具，无 CI 要求）
    "falsy_audit.py",
    "gen_requirements.py",
    "generate_images.py",
    "generate_test_data.py",
    "run_smartsuite.py",
    "setup_offline.py",
    "verify_all.py",  # 一键验证胶水（各步骤由 CI 独立 job 覆盖）
    "verify_consistency.py",
    "verify_cross_consistency.py",
    "verify_manual_claims.py",
}


def get_changed_files(base: str) -> list[str] | None:
    """返回变更的文件相对路径列表：base..HEAD 提交 + 未提交工作区改动。

    默认 base=HEAD~1 只含已提交变更，会漏掉开发者最关心的未提交工作区改动，
    导致工具在核心场景（改完代码跑增量测试）静默 SKIP。这里显式合并
    `git diff --name-only`（未暂存+已暂存）以覆盖工作区。
    """
    try:
        results = []
        for args in (
            ["git", "diff", "--name-only", base, "HEAD"],
            ["git", "diff", "--name-only"],
            ["git", "diff", "--cached", "--name-only"],
            # 未跟踪的新文件（git diff 不覆盖）——新建脚本/测试必须进路由
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                cwd=ROOT,
            )
            if r.returncode == 0:
                results.extend(r.stdout.splitlines())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    seen: set[str] = set()
    out = []
    for line in results:
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _find_script_test(path: str) -> str | None:
    """scripts/ 下文件 → tests/scripts/ 按 stem 子串匹配（连字符归一化为下划线）。"""
    stem = Path(path).stem.lower().replace("-", "_")
    if not stem or stem.startswith("__"):
        return None
    for p in sorted((ROOT / "tests" / "scripts").glob("test_*.py")):
        if stem in p.name.lower():
            return f"tests/scripts/{p.name}"
    return None


def map_source_to_tests(rel_path: str) -> tuple[str, list[str]]:
    """变更文件 → (kind, 目标测试列表)。kind ∈ {"run", "skip", "fail"}。

    - run:  有对应测试，返回目标测试路径
    - skip: 文档/配置类变更，无需测试（CLI 打印提示）
    - fail: 无法映射或无对应测试（防"缺测"静默通过）
    """
    p = rel_path.replace("\\", "/")
    if p.startswith("tests/"):
        return "run", [p] if p.endswith(".py") else []
    if p.startswith("scripts/"):
        hit = _find_script_test(p)
        if hit:
            return "run", [hit]
        stem = Path(p).name
        # 文档/配置类脚本（README.md / *.sh / *.yaml）无对应测试 → SKIP；
        # 其余无测试的脚本视为缺测（fail），防门禁说谎
        if stem in _EXEMPT_SCRIPTS or p.endswith(_SKIP_SUFFIXES):
            return "skip", []
        return "fail", []
    if p.startswith("templates/"):
        if p.endswith(".yaml"):
            return "run", ["tests/test_services", "tests/test_workflows.py"]
        # new_analysis.py 脚手架 / README.md：无直接测试（11 步注册链由一致性门禁覆盖）→ SKIP
        if p.endswith((".py", ".md")):
            return "skip", []
        return "fail", []
    if p.startswith("src/"):
        for prefix, targets in _SRC_TEST_MAP:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                return "run", list(targets)
        return "fail", []
    if p.startswith(_SKIP_PREFIXES) or p.endswith(_SKIP_SUFFIXES):
        return "skip", []
    # 未知路径
    return "fail", []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影响范围测试路由")
    parser.add_argument("--base", default="HEAD~1", help="对比基准（默认 HEAD~1）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不运行")
    args = parser.parse_args(argv)

    changed = get_changed_files(args.base)
    if changed is None:
        print("[FAIL] git 命令失败，无法确定变更文件（git 错误退出码 1）")
        return 1
    if not changed:
        print("[SKIP] 无文件变更（影响范围测试路由无需运行）")
        return 0

    target_tests: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for f in sorted(changed):
        kind, tests = map_source_to_tests(f)
        if kind == "run":
            target_tests.extend(tests)
        elif kind == "skip":
            skipped.append(f)
        else:
            missing.append(f)

    if missing:
        print(f"[FAIL] {len(missing)} 个变更文件无对应测试——疑似缺测，请补测试：")
        for f in missing:
            print(f"  - {f}")
        return 1

    if not target_tests:
        print(f"[SKIP] 变更均为免测文件（{len(skipped)} 个），无需运行测试")
        return 0

    target_tests = sorted(set(target_tests))
    print(f"变更文件 {len(changed)} 个 → 目标测试 {len(target_tests)} 个：")
    for t in target_tests:
        print(f"  {t}")
    if skipped:
        print(f"（免测文件 {len(skipped)} 个已跳过）")

    if args.dry_run:
        print("\n[dry-run] 完成，未实际运行")
        return 0

    r = subprocess.run(
        [sys.executable, "-m", "pytest", *target_tests, "-q", "--tb=short"], cwd=ROOT
    )
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
