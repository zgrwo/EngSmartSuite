"""verify_docs.py 各检查向量测试（用 tmp 迷你仓库构造场景）。"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "verify_docs.py"
mod = importlib.util.spec_from_file_location("verify_docs", SPEC)
verify_docs = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(verify_docs)


# ── 迷你仓库构造 ──────────────────────────────────────────────

TREE_OK = """\
```
Mini/
├── src/
├── tests/
├── docs/
│   ├── specification/
│   │   └── api-reference.md
│   └── governance/
│       └── project-structure.md
├── skills/
└── README.md
```
"""

TREE_AGENTS_OK = """\
```
Mini/
├── src/
├── tests/
├── docs/
├── skills/
└── README.md
```
"""


def build_repo(tmp_path: Path) -> Path:
    """构造基础迷你仓库（目录树一致、无断链、无语义问题）。"""
    root = tmp_path / "repo"
    for d in ("src", "tests", "docs", "skills"):
        (root / d).mkdir(parents=True)
    (root / "docs" / "specification").mkdir()
    (root / "docs" / "governance").mkdir()
    (root / "docs" / "governance" / "project-structure.md").write_text(TREE_OK, encoding="utf-8")
    (root / "AGENTS.md").write_text(TREE_AGENTS_OK, encoding="utf-8")
    (root / "docs" / "specification" / "api-reference.md").write_text(
        "# API\n\n见 [README](README.md)\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# Mini\n\n参考 [docs/specification/api-reference.md](docs/specification/api-reference.md)\n",
        encoding="utf-8",
    )
    (root / "scripts").mkdir()
    (root / "src" / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return root


# ── 向量 1：markdown 链接断链 ─────────────────────────────────


def test_check_links_reports_broken_and_passes_ok(tmp_path):
    root = build_repo(tmp_path)
    doc_files = ["README.md"]
    assert verify_docs.check_links(root, doc_files) == []
    (root / "README.md").write_text("[坏链](docs/specification/ghost.md)\n", encoding="utf-8")
    problems = verify_docs.check_links(root, doc_files)
    assert any("docs/specification/ghost.md" in p for p in problems)


def test_check_links_skips_http_and_anchor(tmp_path):
    root = build_repo(tmp_path)
    (root / "README.md").write_text(
        "[外链](https://example.com) [锚点](#sec) [占位]({{X}})\n", encoding="utf-8"
    )
    assert verify_docs.check_links(root, ["README.md"]) == []


# ── 向量 2：反引号根路径 ──────────────────────────────────────


def test_check_backtick_paths(tmp_path):
    root = build_repo(tmp_path)
    (root / "scripts" / "verify_docs.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text(
        "存在 `scripts/verify_docs.py`，缺失 `scripts/ghost.py`，占位 `{Name}.py` 跳过\n",
        encoding="utf-8",
    )
    problems = verify_docs.check_backtick_paths(root, ["README.md"])
    assert any("scripts/ghost.py" in p for p in problems)
    assert not any("verify_docs.py" in p for p in problems)


# ── 向量 3：目录树声明存在性 ──────────────────────────────────


def test_check_dirs_reports_missing_declared_dir(tmp_path):
    root = build_repo(tmp_path)
    assert verify_docs.check_dirs(root) == []
    (root / "docs" / "governance" / "project-structure.md").write_text(
        TREE_OK.replace("└── README.md", "├── ghostdir/\n└── README.md"), encoding="utf-8"
    )
    problems = verify_docs.check_dirs(root)
    assert any("ghostdir" in p for p in problems)


# ── 向量 4：双目录树漂移 ──────────────────────────────────────


def test_check_agents_tree_reports_drift(tmp_path):
    root = build_repo(tmp_path)
    assert verify_docs.check_agents_tree(root) == []
    (root / "AGENTS.md").write_text(
        "```\nMini/\n├── src/\n├── docs/\n└── README.md\n```\n", encoding="utf-8"
    )
    problems = verify_docs.check_agents_tree(root)
    assert any("tests" in p for p in problems)


# ── 向量 5：语义检查（裸 except / TODO / 裸 input）────────────


def test_bare_except_detected(tmp_path):
    root = build_repo(tmp_path)
    (root / "src" / "bad.py").write_text("try:\n    f()\nexcept:\n    pass\n", encoding="utf-8")
    problems = verify_docs.check_semantic_consistency(root, [])
    assert any("bad.py" in p for p in problems)


def test_todo_in_doc_detected(tmp_path):
    root = build_repo(tmp_path)
    (root / "README.md").write_text("- TODO: 待补充\n", encoding="utf-8")
    problems = verify_docs.check_semantic_consistency(root, ["README.md"])
    assert any("TODO" in p for p in problems)


def test_bare_input_in_verify_script_detected(tmp_path):
    root = build_repo(tmp_path)
    (root / "scripts" / "verify_something.py").write_text("x = input('输入: ')\n", encoding="utf-8")
    problems = verify_docs.check_semantic_consistency(root, [])
    assert any("verify_something.py" in p for p in problems)


# ── 向量 6：版本一致性 ────────────────────────────────────────


def test_version_consistency(tmp_path):
    root = build_repo(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n', encoding="utf-8")
    (root / ".release-please-manifest.json").write_text(
        json.dumps({".": "1.0.1"}), encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.1] - 2026-01-01\n", encoding="utf-8")
    assert verify_docs.check_version_consistency(root) == []
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.2"\n', encoding="utf-8")
    problems = verify_docs.check_version_consistency(root)
    assert any("1.0.2" in p for p in problems)


# ── 向量 7：未声明文件（--strict）────────────────────────────


def test_undeclared_root_file_strict_only(tmp_path):
    root = build_repo(tmp_path)
    (root / "STRANGER.md").write_text("x", encoding="utf-8")
    assert verify_docs.check_undeclared(root, strict=False) == []
    problems = verify_docs.check_undeclared(root, strict=True)
    assert any("STRANGER.md" in p for p in problems)


def test_subdir_undeclared_strict(tmp_path):
    root = build_repo(tmp_path)
    (root / "docs" / "extra.md").write_text("x", encoding="utf-8")
    problems = verify_docs.check_subdir_undeclared(root, strict=True)
    assert any("docs/extra.md" in p for p in problems)
    assert verify_docs.check_subdir_undeclared(root, strict=False) == []


# ── 向量 6b：git tag 版本漂移（审查 2026-09-05 E1）────────────


def test_semver_key_and_latest_tag():
    assert verify_docs._semver_key("v1.2.3") == (1, 2, 3)
    assert verify_docs._semver_key("2.0.0") == (2, 0, 0)
    assert verify_docs._semver_key("v1.2") is None
    assert verify_docs._latest_semver_tag(["v1.2.2", "v1.2.10", "v2.0.0", "nightly"]) == "v2.0.0"
    assert verify_docs._latest_semver_tag([]) == ""


def test_git_tag_version_detects_behind_chain(monkeypatch):
    class _FakeRes:
        stdout = "v1.2.2\nv1.2.3\n"

    monkeypatch.setattr(verify_docs.subprocess, "run", lambda *a, **k: _FakeRes())
    problems = verify_docs.check_git_tag_version(Path("x"), "1.2.2")
    assert any("v1.2.3" in p for p in problems)


def test_git_tag_version_chain_ahead_or_equal_ok(monkeypatch):
    class _FakeRes:
        stdout = "v1.2.2\n"

    monkeypatch.setattr(verify_docs.subprocess, "run", lambda *a, **k: _FakeRes())
    # 链 > tag = 发版间隙（版本已 bump、tag 待打）；链 == tag 正常
    assert verify_docs.check_git_tag_version(Path("x"), "1.2.3") == []
    assert verify_docs.check_git_tag_version(Path("x"), "1.2.2") == []


def test_git_tag_version_orphan_tag_surfaces(monkeypatch):
    class _FakeRes:
        stdout = "v1.2.2\nv2.0.0\n"  # 模拟孤立 v2.0.0 tag

    monkeypatch.setattr(verify_docs.subprocess, "run", lambda *a, **k: _FakeRes())
    problems = verify_docs.check_git_tag_version(Path("x"), "1.2.2")
    assert any("v2.0.0" in p for p in problems)


def test_git_tag_version_skips_without_git(monkeypatch):
    def _boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(verify_docs.subprocess, "run", _boom)
    assert verify_docs.check_git_tag_version(Path("x"), "1.2.2") == []
