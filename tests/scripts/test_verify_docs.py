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
├── scripts/
├── AGENTS.md
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
├── scripts/
├── AGENTS.md
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


def test_except_exception_without_log_detected(tmp_path):
    """审查 2026-09-22 发现 10：`except Exception` 无日志必须被 AST 检查拦截。"""
    root = build_repo(tmp_path)
    (root / "src" / "bad.py").write_text(
        "try:\n    f()\nexcept Exception:\n    pass\n", encoding="utf-8"
    )
    problems = verify_docs.check_semantic_consistency(root, [])
    assert any("bad.py" in p and "日志" in p for p in problems), problems


def test_except_exception_with_log_passes(tmp_path):
    """对照：带 logging 调用的处理器不得误报（含 as e 与 logger.debug 变体）。"""
    root = build_repo(tmp_path)
    (root / "src" / "good.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except Exception as e:\n"
        "        logger.debug('x', exc_info=True)\n"
        "        return fallback(e)\n",
        encoding="utf-8",
    )
    problems = verify_docs.check_semantic_consistency(root, [])
    assert not any("good.py" in p for p in problems), problems


def test_heading_merged_into_line_detected(tmp_path):
    """审查 2026-09-22 发现 7：标题漏换行并入上一行必须被拦截。"""
    root = build_repo(tmp_path)
    (root / "README.md").write_text("- 说明文字。### 7.11 标题\n", encoding="utf-8")
    problems = verify_docs.check_semantic_consistency(root, ["README.md"])
    assert any("README.md" in p and "行首" in p for p in problems), problems


def test_heading_at_line_start_passes(tmp_path):
    """对照：独占行首的标题与代码围栏内的 ### 文本不得误报。"""
    root = build_repo(tmp_path)
    (root / "README.md").write_text(
        "### 7.11 正常标题\n\n```\n示例 ### 不是标题\n```\n", encoding="utf-8"
    )
    problems = verify_docs.check_semantic_consistency(root, ["README.md"])
    assert not any("README.md" in p for p in problems), problems


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


def test_version_consistency_checks_init_extra_file(tmp_path):
    """R-7：release-please extra-files 的 __init__.py __version__ 纳入版本链。"""
    root = build_repo(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.1"\n', encoding="utf-8")
    (root / ".release-please-manifest.json").write_text(
        json.dumps({".": "1.0.1"}), encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.1] - 2026-01-01\n", encoding="utf-8")
    pkg = root / "src" / "smartsuite"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text('__version__ = "1.0.1"\n', encoding="utf-8")
    assert verify_docs.check_version_consistency(root) == []
    init.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    problems = verify_docs.check_version_consistency(root)
    assert any("__init__.py" in p and "1.0.0" in p for p in problems)
    init.write_text("# 缺少版本声明\n", encoding="utf-8")
    problems = verify_docs.check_version_consistency(root)
    assert any("缺少 __version__" in p for p in problems)


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


def test_undeclared_excludes_build_artifacts(tmp_path):
    """回归：site/（mkdocs）与 dist/（uv build）是 .gitignore 忽略的构建产物，豁免登记。"""
    root = build_repo(tmp_path)
    (root / "site").mkdir()
    (root / "dist").mkdir()
    assert verify_docs.check_undeclared(root, strict=True) == []


def test_undeclared_excludes_tool_caches(tmp_path):
    """回归：.mypy_cache/（mypy）与 .benchmarks/（pytest-benchmark）本地缓存豁免登记。"""
    root = build_repo(tmp_path)
    (root / ".mypy_cache").mkdir()
    (root / ".benchmarks").mkdir()
    assert verify_docs.check_undeclared(root, strict=True) == []


def test_undeclared_exempts_gitignored_local_artifacts(tmp_path, monkeypatch):
    """回归（2026-09-19 F-2）：benchmark.json / htmlcov/ 等 .gitignore 忽略的本地产物豁免登记。

    _git_ignored_files 在非 git 的迷你仓库返回空集，此处 monkeypatch 模拟 git 命中。
    """
    root = build_repo(tmp_path)
    (root / "benchmark.json").write_text("{}", encoding="utf-8")
    (root / "htmlcov").mkdir()
    monkeypatch.setattr(verify_docs, "_git_ignored_files", lambda r, paths: {p.name for p in paths})
    assert verify_docs.check_undeclared(root, strict=True) == []


def test_undeclared_gitignored_does_not_mask_tracked_like_files(tmp_path):
    """反向守卫：非忽略文件仍必须登记（_git_ignored_files 空集路径）。"""
    root = build_repo(tmp_path)
    (root / "benchmark.json").write_text("{}", encoding="utf-8")
    problems = verify_docs.check_undeclared(root, strict=True)
    assert any("benchmark.json" in p for p in problems)


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


# ── F4-1（2026-09-21 审查）：嵌套目录未登记检查的递归盲区 ──────────────────
def test_nested_declared_dir_flags_undeclared_file(tmp_path):
    """被**逐项列出**的嵌套目录里，未声明的文件必须被拦截（审查 F4-1 P3）。

    原实现只解析/比对顶层目录下的**直接**文件（`_SUBDIR_CHECK` + 一层 `│ ├──`），
    故 `docs/adr/0004-*.md`、`.github/workflows/benchmarks.yml`、
    `tests/scripts/test_common.py` 这类两层文件完全不校验——实测漏登记 16 个文件
    而 `--strict` 仍退出 0。
    """
    root = build_repo(tmp_path)
    (root / "docs" / "specification" / "ghost.md").write_text("x", encoding="utf-8")
    problems = verify_docs.check_subdir_undeclared(root, strict=True)
    assert any("docs/specification/ghost.md" in p for p in problems), (
        f"嵌套目录内未声明文件未被拦截: {problems}"
    )


def test_nested_declared_file_passes(tmp_path):
    """已声明的嵌套文件不得误报（对照）。"""
    root = build_repo(tmp_path)
    assert verify_docs.check_subdir_undeclared(root, strict=True) == []


def test_summarized_dir_contents_are_exempt(tmp_path):
    """目录树中**未逐项列出子项**的目录（如 `images/`）→ 内容豁免登记。

    这是递归检查不产生大量假阳性的关键规则：只有「已声明至少一个子项」的目录
    才要求其全部文件登记；汇总性目录（手册配图等）仅声明目录本身。
    """
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    tree = (
        "```\nMini/\n"
        "├── docs/\n"
        "│   ├── images/          # 汇总目录，不逐项列出\n"
        "│   └── readme.md\n"
        "```\n"
    )
    (root / "docs" / "governance").mkdir()
    (root / "docs" / "governance" / "project-structure.md").write_text(tree, encoding="utf-8")
    (root / "docs" / "readme.md").write_text("x", encoding="utf-8")
    (root / "docs" / "images").mkdir()
    (root / "docs" / "images" / "a.png").write_bytes(b"x")

    assert verify_docs.check_subdir_undeclared(root, strict=True) == []


def test_dir_with_declared_child_requires_all_children(tmp_path):
    """反面：一旦目录声明了任一子项，其全部文件都必须登记。"""
    root = tmp_path / "repo"
    (root / "docs" / "governance").mkdir(parents=True)
    tree = "```\nMini/\n├── docs/\n│   ├── adr/\n│   │   └── 0001-a.md\n```\n"
    (root / "docs" / "governance" / "project-structure.md").write_text(tree, encoding="utf-8")
    (root / "docs" / "adr").mkdir()
    (root / "docs" / "adr" / "0001-a.md").write_text("x", encoding="utf-8")
    (root / "docs" / "adr" / "0002-b.md").write_text("x", encoding="utf-8")

    problems = verify_docs.check_subdir_undeclared(root, strict=True)
    assert any("docs/adr/0002-b.md" in p for p in problems), problems


# ── 发现 9（2026-09-22 审查）：src/ 未纳入未声明文件检查 ──────────────────
def test_src_undeclared_file_detected(tmp_path):
    """实验组注入：目录树已列出 src/ 子项时，新增未登记源码文件必须被拦截。

    修复前 `_SUBDIR_CHECK` 不含 "src" → 注入 src/smartsuite/.../zz_*.py 退出 0。
    """
    root = build_repo(tmp_path)
    tree = TREE_OK.replace("├── src/", "├── src/\n│   └── ok.py")
    (root / "docs" / "governance" / "project-structure.md").write_text(tree, encoding="utf-8")
    (root / "src" / "ghost.py").write_text("x", encoding="utf-8")
    problems = verify_docs.check_subdir_undeclared(root, strict=True)
    assert any("src/ghost.py" in p for p in problems), problems
    assert not any("src/ok.py" in p for p in problems), "已声明文件不得误报"


def test_src_summarized_dir_contents_are_exempt(tmp_path):
    """对照：目录树只声明 src/ 本身（未逐项列出）时，内容豁免登记（不产生噪音）。"""
    root = build_repo(tmp_path)
    problems = verify_docs.check_subdir_undeclared(root, strict=True)
    assert not any("src/ok.py" in p for p in problems), problems
