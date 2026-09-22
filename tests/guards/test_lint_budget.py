"""per-file-ignore 预算与有效性守卫（审查 2026-09-19 B8）。

`pyproject.toml` 的 `per-file-ignores` 是「对 lint 规则的行业性让步」，一旦只增不减就会
累积成无人敢碰的黑名单（本项目曾从 18 条起）。本文件把两条纪律变成可执行约束：

1. **条数预算**：不得超过 9 条（B8 收敛后的现状，18 → 16 → 10 → 9）；
2. **每条都必须仍在生效**：把豁免整段去掉后跑 ruff，该规则在该文件里必须仍有违规 ——
   否则说明代码已经改好、豁免成了无用残留，应删除。

第 2 条是 B8 的核心方法（也修正了一个方法论错误：`ruff check --isolated` 会忽略
`preview` 等配置，统计不准，必须用「完整配置去掉该段」的方式复核）。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    # Python 3.10：stdlib tomllib 仅 3.11+（requires-python >= 3.10），
    # 而 pytest 在 <3.11 依赖 tomli（uv.lock 已锁），故回退导入保证
    # full 矩阵 3.10 也能执行本守卫（2026-09-22 main 矩阵实测修复）。
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"

# B8 收敛后的预算（2026-09-19：18 → 16 → 10 → 9）
_BUDGET = 9


def _per_file_ignores() -> dict[str, list[str]]:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]["lint"][
        "per-file-ignores"
    ]


def _config_without_ignores(tmp_path: Path) -> Path:
    """复制 pyproject 并整段删除 per-file-ignores（保留其余 ruff 配置，含 preview）。"""
    text = _PYPROJECT.read_text(encoding="utf-8")
    start = text.index("[tool.ruff.lint.per-file-ignores]")
    rest = text[start + 1 :]
    match = re.search(r"^\[", rest, re.MULTILINE)
    end = start + 1 + match.start() if match else len(text)

    tmp = tmp_path / "pyproject.toml"
    tmp.write_text(text[:start] + text[end:], encoding="utf-8")
    return tmp


def _rule_counts_without_ignores(tmp_path: Path) -> dict[tuple[str, str], int]:
    """`{(文件相对路径, 规则): 违规数}` —— 在无豁免配置下统计。"""
    config = _config_without_ignores(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(config),
            "--output-format",
            "json",
            str(_ROOT / "src"),
            str(_ROOT / "tests"),
            str(_ROOT / "scripts"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_ROOT,
    )
    payload = json.loads(proc.stdout or "[]")

    counts: dict[tuple[str, str], int] = {}
    for item in payload:
        rel = Path(item["filename"]).resolve().relative_to(_ROOT).as_posix()
        counts[(rel, item["code"])] = counts.get((rel, item["code"]), 0) + 1
    return counts


def test_per_file_ignore_count_within_budget():
    """豁免条数不得超过预算（只减不增；新增需先在此说明理由并同步下调预算）。"""
    ignores = _per_file_ignores()

    assert len(ignores) <= _BUDGET, (
        f"per-file-ignores 共 {len(ignores)} 条，超预算 {_BUDGET} 条 —— "
        f"优先用等价改写消除违规，而不是新增豁免：{sorted(ignores)}"
    )


def test_every_ignore_entry_has_a_reason_comment():
    """每条豁免都必须写明理由（源码级检查：配置段内每行都有行尾注释）。"""
    text = _PYPROJECT.read_text(encoding="utf-8")
    start = text.index("[tool.ruff.lint.per-file-ignores]")
    block = text[start:].split("\n[", 1)[0]
    entries = [ln for ln in block.splitlines() if ln.strip().startswith('"')]

    assert entries, "未解析到豁免条目"
    missing = [ln for ln in entries if "#" not in ln]
    assert not missing, f"以下豁免缺少理由注释：{missing}"


@pytest.mark.parametrize(
    ("path_pattern", "rule"),
    sorted(
        (path, rule)
        for path, rules in tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"][
            "lint"
        ]["per-file-ignores"].items()
        for rule in rules
    ),
    ids=lambda v: str(v).replace("*", "star"),
)
def test_ignore_entry_is_still_needed(tmp_path, path_pattern, rule):
    """豁免必须仍然生效：去掉整段豁免后，该规则在该文件里应仍有违规。

    若此用例失败，说明该处代码已改好 —— 删除这条豁免（B8 的收敛机制）。
    """
    counts = _rule_counts_without_ignores(tmp_path)

    if path_pattern.endswith("*"):
        prefix = path_pattern[:-1]
        hits = sum(
            n for (path, code), n in counts.items() if path.startswith(prefix) and code == rule
        )
    else:
        hits = counts.get((path_pattern, rule), 0)

    assert hits > 0, (
        f"豁免项「{path_pattern} → {rule}」已无实际违规（代码可能已改写）："
        f"请从 pyproject.toml 移除该豁免并下调预算"
    )
