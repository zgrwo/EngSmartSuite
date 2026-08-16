"""validate-commit-msg.sh 行为测试（Conventional Commits 校验规则）。"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate-commit-msg.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="需要 POSIX sh（Git Bash / WSL / Linux）"
)


def run(subject: str) -> int:
    """以 stdin 方式调用校验脚本，返回退出码。"""
    return subprocess.run(
        ["sh", str(SCRIPT)],
        input=subject,
        text=True,
        capture_output=True,
        cwd=ROOT,
    ).returncode


def test_valid_formats():
    """合法格式（含 scope/中文/破坏性标记/跳过特例）应通过。"""
    valid = [
        "fix(engine): 修复 anova 效应量计算",
        "feat: 新分析方法",
        "docs!: 破坏性文档变更",
        "ci(workflows): bump action version",
        "refactor(install): 重写离线安装",
        "Merge branch 'main'",
        "fixup! 之前的提交",
        "Revert 'feat: xxx'",
        "chore(repo): 添加 CODEOWNERS",
    ]
    for subject in valid:
        assert run(subject) == 0, f"应通过: {subject!r}"


def test_invalid_formats():
    """非法格式（无 type/缺冒号/空 subject/乱写）应拒绝。"""
    invalid = [
        "修复 bug",
        "fix(engine) 缺冒号",
        "fix(engine):",
        "x",
        "",
        "FIX(engine): 大写类型不支持",
        "fix(engine):  ",
    ]
    for subject in invalid:
        assert run(subject) == 1, f"应拒绝: {subject!r}"


def test_subject_length_limit():
    """标题长度上限 72 字符。"""
    assert run("fix: " + "长" * 73) == 1
    assert run("fix: " + "长" * 72) == 0
