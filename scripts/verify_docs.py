#!/usr/bin/env python3
"""
verify_docs.py — 文档一致性验证（源自 VibeCodingTemplate verify-docs.py，按套件裁剪）

检查向量：
  1. 文档中相对链接（markdown）指向的文件是否存在
  2. 反引号内以已知根目录前缀开头的相对路径引用是否存在（`scripts/xxx.py` 类）
  3. project-structure.md 目录树声明的顶层目录是否真实存在
  4. AGENTS.md 与 project-structure.md 的目录树顶层条目集合一致（双目录树防漂移）
  5. 语义交叉检查：裸 except 捕获 / `except Exception` 无日志（src/ 生产代码）/
     标题未独占行首 / 文档 TODO/FIXME 残留 / verify_* 脚本裸 input 调用
  6. 版本一致性门禁：.release-please-manifest.json == pyproject.toml == CHANGELOG 最新发布
  7. （--strict）根级未声明文件/目录 + src/、docs/、skills/、tests/、scripts/、
     templates/、.github/、benchmarks/ 子目录直接文件未登记
     （.gitignore 忽略的本地生成产物豁免）

规则：
  - 含占位符（{{...}} / {Name} / <...>）的引用跳过（模式串而非真实路径）
  - logs/、docs/、packages/、build/ 等本地/运行时目录不参与存在性检查
  - 扫描跳过注释/docstring 行（防教学文字自误报）

用法：
  python scripts/verify_docs.py            # 基础检查
  python scripts/verify_docs.py --strict   # 含未声明文件检查

退出码：0 = 通过；1 = 发现断链/缺失
"""

import argparse
import ast
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# 本地/运行时/工具目录（不入库或无需声明），不参与存在性与未声明检查
EXCLUDED_DIRS = {
    ".coverage",  # 覆盖率运行产物（.gitignore 已忽略）
    ".benchmarks",  # pytest-benchmark 本地缓存（.gitignore 已忽略）
    ".mypy_cache",  # mypy 类型检查缓存（.gitignore 已忽略）
    ".git",
    ".claude",
    ".codegraph",
    ".hypothesis",  # hypothesis 示例数据库（.gitignore 已忽略）
    ".opencode-goal",  # opencode goal 会话产物（.gitignore 已忽略）
    ".pytest_cache",
    ".qoder",
    ".ruff_cache",
    ".superpowers",  # Superpowers 会话产物（.gitignore 已忽略）
    ".venv",
    "build",
    "dist",  # 构建产物（.gitignore 已忽略）
    "logs",
    "packages",  # 离线安装缓存（.gitignore 忽略）
    "site",  # mkdocs 文档站构建产物（.gitignore 已忽略）
    "__pycache__",
}

# 需核对"目录内文件已登记"的关键子目录（目录树即契约）
# 审查 2026-08-19 第二轮 #5：从 docs/skills 扩展至 tests/、scripts/、templates/
# 审查 2026-09-22 发现 9：补 src/（目录树已逐项列出 src/smartsuite/**，此前新增
# 源码文件无门禁——实测注入 src/smartsuite/engine/spc_charts/zz_*.py 退出 0）
_SUBDIR_CHECK = ("src", "docs", "skills", "tests", "scripts", "templates", ".github", "benchmarks")

# 反引号路径检查：仅检查以已知根目录前缀开头的引用（语义明确指向仓库内路径）
_KNOWN_ROOT_PREFIXES = (
    "scripts/",
    "docs/",
    "skills/",
    "templates/",
    ".github/",
    "tests/",
    "src/",
)
_BACKTICK_SKIP_MARKERS = ("xxx", "nnn", "{{", "{", "}", "<", ">", "*", "...")
_BACKTICK_SKIP_PREFIXES = (".claude/", ".codegraph/", ".qoder/", "docs/superpowers/")
_BACKTICK_SKIP_DOCS = {"CHANGELOG.md"}  # 历史记录，引用已删文件属正常


def collect_doc_files(root: Path) -> list[str]:
    """动态收集需要检查链接的文档（根 *.md + docs/ + skills/ + scripts/README）。

    用 glob 而非硬编码列表：新增规则/技能文档自动纳入检查，免维护。
    """
    docs = sorted(p.relative_to(root).as_posix() for p in root.glob("*.md"))
    docs.extend(sorted(p.relative_to(root).as_posix() for p in (root / "docs").rglob("*.md")))
    docs.extend(sorted(p.relative_to(root).as_posix() for p in (root / "skills").glob("*.md")))
    readme = root / "scripts" / "README.md"
    if readme.exists():
        docs.append("scripts/README.md")
    # 豁免：docs/superpowers 为会话产物（gitignore），不参与链接/反引号存在性检查
    return [d for d in docs if not d.startswith(("docs/superpowers/",))]


# ── 目录树解析（project-structure.md 即契约）──────────────────


def _parse_top_entries(root: Path, doc: str) -> list[str]:
    """从目录树（markdown 代码块）解析顶层条目（目录 + 根级文件）。"""
    path = root / doc
    if not path.exists():
        return []
    entries: list[str] = []
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        m = re.match(r"^[├└]──\s+([^#\s]+)", s)
        if m:
            entries.append(m.group(1).rstrip("/"))
    return entries


def _parse_tree_paths(root: Path) -> tuple[set[str], set[str]]:
    """解析目录树的**任意深度**条目 → (已声明文件相对路径集, 已声明目录相对路径集)。

    审查 2026-09-21 F4-1：原 `_parse_nested_files` 只解析「顶层目录 → 直接文件」
    一层，而目录树本身逐项列出了两层文件（`.github/ISSUE_TEMPLATE/*.md`、
    `docs/governance/*.md`）——两层以上完全不校验，实测漏登记 16 个文件
    （含 `docs/adr/0004-*.md`、`.github/workflows/{benchmarks,docs}.yml`、
    `tests/scripts/test_common.py` 等）而 `--strict` 仍退出 0。现按缩进栈解析任意深度。
    """
    path = root / "docs" / "governance" / "project-structure.md"
    declared: set[str] = set()
    dirs: set[str] = set()
    in_block = False
    stack: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.rstrip()
        if s.strip().startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        m = re.match(r"^((?:│   |    )*)(?:├──|└──)\s+(.*)$", s)
        if not m:
            continue
        depth = len(m.group(1)) // 4
        raw = m.group(2).strip()
        is_dir = raw.split("#")[0].strip().endswith("/")
        name = raw.split("#")[0].strip().rstrip("/")
        if not name or name == "...":
            stack = stack[:depth]
            continue
        stack = stack[:depth] + [name]
        entry = "/".join(stack)
        (dirs if is_dir else declared).add(entry)
    return declared, dirs


def _recursive_dirs(dirs: set[str], declared: set[str]) -> set[str]:
    """返回「已声明至少一个子项」的目录集——只有这些目录才要求全部文件登记。

    汇总性目录（如 `docs/user-manual/images/`：树里只写目录本身、不逐项列图）
    的内容豁免登记，否则递归检查会对配图等资产产生大量假阳性。
    """
    return {d for d in dirs if any(x.startswith(d + "/") for x in declared)}


# ── 向量 1：markdown 相对链接 ────────────────────────────────


def check_links(root: Path, doc_files: list[str]) -> list[str]:
    problems: list[str] = []
    link_re = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:\s+\"[^\"]*\")?\)")
    for doc in doc_files:
        path = root / doc
        if not path.exists():
            problems.append(f"[缺失文档] {doc}")
            continue
        for m in link_re.finditer(path.read_text(encoding="utf-8")):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if "{{" in target:
                continue  # 占位符链接：初始化替换前无法验证
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                problems.append(f"[断链] {doc} -> {target}")
    return problems


# ── 向量 2：反引号根路径 ─────────────────────────────────────


def _is_pattern_like(s: str) -> bool:
    low = s.lower()
    return any(mk in low for mk in _BACKTICK_SKIP_MARKERS)


def check_backtick_paths(root: Path, doc_files: list[str]) -> list[str]:
    problems: list[str] = []
    code_re = re.compile(r"`([^`\s]+)`")
    for doc in doc_files:
        if doc in _BACKTICK_SKIP_DOCS:
            continue
        path = root / doc
        if not path.exists():
            continue
        for m in code_re.finditer(path.read_text(encoding="utf-8")):
            raw = m.group(1)
            target = raw.replace("\\", "/")  # Windows 反斜杠 → 正斜杠
            if target.startswith("./"):
                target = target[2:]
            if not target.startswith(_KNOWN_ROOT_PREFIXES):
                continue
            if target.startswith(_BACKTICK_SKIP_PREFIXES):
                continue
            if _is_pattern_like(target):
                continue
            resolved = (root / target.rstrip("/")).resolve()
            if not resolved.exists():
                problems.append(f"[反引号路径失效] {doc} -> `{raw}`（指向不存在的文件？）")
    return problems


# ── 向量 3：目录树声明存在性 ─────────────────────────────────


def check_dirs(root: Path) -> list[str]:
    problems: list[str] = []
    declared = [e for e in _parse_top_entries(root, "docs/governance/project-structure.md")]
    if not declared:
        problems.append(
            "[配置错误] 无法从 project-structure.md 目录树解析顶层条目（目录树格式异常？）"
        )
        return problems
    for d in declared:
        if d in EXCLUDED_DIRS:
            continue
        if not (root / d).exists():
            problems.append(f"[缺失目录] {d}/（project-structure.md 已声明）")
    return problems


# ── 向量 4：双目录树漂移 ─────────────────────────────────────


def check_agents_tree(root: Path) -> list[str]:
    problems: list[str] = []
    ps_entries = set(_parse_top_entries(root, "docs/governance/project-structure.md"))
    # 文件名统一为大写 AGENTS.md（与 AI 代理惯例一致）；Linux 大小写敏感，
    # 此处路径必须与实际文件名精确匹配，否则双目录树检查恒失败
    agents_entries = set(_parse_top_entries(root, "AGENTS.md"))
    if not ps_entries or not agents_entries:
        if not agents_entries:
            problems.append("[配置错误] 无法从 AGENTS.md 目录树解析顶层条目（格式异常？）")
        return problems
    for e in sorted(ps_entries - agents_entries):
        problems.append(
            f"[目录树漂移] project-structure.md 声明 {e}，AGENTS.md 未收录（请同步 AGENTS.md）"
        )
    for e in sorted(agents_entries - ps_entries):
        problems.append(f"[目录树漂移] AGENTS.md 声明 {e}，project-structure.md 未收录")
    return problems


# ── 向量 5：语义交叉检查 ─────────────────────────────────────


def _check_bare_handlers(root: Path) -> list[str]:
    """裸 except 捕获（src/ 生产代码 + scripts/ 治理脚本；跳过注释/docstring 行）。"""
    problems: list[str] = []
    for base_name in ("src", "scripts"):
        base = root / base_name
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.relative_to(root).parts):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            in_docstring = False
            for i, line in enumerate(lines, 1):
                stripped = line.split("#", 1)[0]
                # docstring 状态按行内三引号出现次数奇偶翻转（单行 docstring 成对出现不翻转）
                q = stripped.count('"""') + stripped.count("'''")
                if q:
                    if q % 2 == 1:
                        in_docstring = not in_docstring
                    continue
                if in_docstring:
                    continue
                if re.search(r"except\s*:", stripped):
                    problems.append(
                        f"[语义检查] 裸 except 捕获残留于 {p.relative_to(root)}:{i}"
                        "（红线规则：无裸 except，须记录日志或显式处理）"
                    )
    return problems


_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"}


def _handler_logs(handler: ast.ExceptHandler) -> bool:
    """处理器体内是否有 logging 调用（按方法名判定，兼容 logger/_logger/log 命名）。"""
    for node in ast.walk(handler):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
        ):
            return True
    return False


def _check_exception_handlers_without_log(root: Path) -> list[str]:
    """生产代码 `except Exception` 必须记录日志（红线；审查 2026-09-22 发现 10）。

    裸 `except:` 由 `_check_bare_handlers` 行级扫描覆盖（src + scripts）；本检查
    用 AST 补生产代码（src/）的 `except Exception`（含 `as e`）无任何 logging
    调用的违例——scripts/ 为治理脚本，其处理器多以返回值/结果记录显式处理，
    不纳入本检查避免噪音。
    """
    problems: list[str] = []
    base = root / "src"
    if not base.exists():
        return problems
    for p in base.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in p.relative_to(root).parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            exc_type = node.type
            if not (isinstance(exc_type, ast.Name) and exc_type.id == "Exception"):
                continue
            if not _handler_logs(node):
                problems.append(
                    f"[语义检查] {p.relative_to(root)}:{node.lineno} `except Exception` "
                    "未记录日志（红线规则：catch 块必须有日志/重抛/返回错误值）"
                )
    return problems


def _check_heading_line_start(root: Path, doc_files: list[str]) -> list[str]:
    """`### ` 及以上标题必须独占行首（审查 2026-09-22 发现 7 的防复发检查）。

    标题被误并入上一行 bullet（漏换行）会使导航/锚点/渲染层级静默失效。
    跳过代码围栏内容；行内正文若出现「文字### 标题」形态即判定结构损坏。
    """
    problems: list[str] = []
    heading_re = re.compile(r"\S#{3,6}\s")
    for doc in doc_files:
        path = root / doc
        if not path.exists():
            continue
        in_fence = False
        for i, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if heading_re.search(line) and not line.startswith("#"):
                problems.append(
                    f"[语义检查] {doc}:{i} 标题未独占行首（疑似漏换行并入上一行；"
                    "请检查渲染层级/锚点）"
                )
    return problems


def _check_unclosed_todos(root: Path, doc_files: list[str]) -> list[str]:
    problems: list[str] = []
    for doc in doc_files:
        p = root / doc
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r"^\s*(?:[-*]?\s*)?(TODO|FIXME)\s*[:：]", text, re.MULTILINE):
            problems.append(
                f"[语义检查] {doc} 含未闭合 {m.group(1)} 待办（第 "
                f"{text[: m.start()].count(chr(10)) + 1} 行）——已完成请移除，未完成请登记"
            )
    return problems


def _check_bare_input_calls(root: Path) -> list[str]:
    """CI 调用的验证脚本禁裸 input()（CI 无 TTY 时挂起）。"""
    problems: list[str] = []
    ci_scripts = [
        p for p in (root / "scripts").glob("*.py") if p.name.startswith(("verify_", "falsy_"))
    ]
    for p in sorted(ci_scripts):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        in_docstring = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.split("#", 1)[0]
            if "input|raw_input" in stripped or "re.search" in stripped:
                continue
            q = stripped.count('"""') + stripped.count("'''")
            if q:
                if q % 2 == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if re.search(r"(?:^|\s)(input|raw_input)\s*\(", stripped):
                problems.append(
                    f"[语义检查] {p.name} 第 {line_no} 行含裸 input 调用"
                    "——CI 无交互环境会挂起，请改为参数/环境变量"
                )
    return problems


def check_semantic_consistency(root: Path, doc_files: list[str]) -> list[str]:
    return (
        _check_bare_handlers(root)
        + _check_exception_handlers_without_log(root)
        + _check_heading_line_start(root, doc_files)
        + _check_unclosed_todos(root, doc_files)
        + _check_bare_input_calls(root)
    )


# ── 向量 6：版本一致性 ───────────────────────────────────────


def _semver_key(version: str) -> tuple[int, int, int] | None:
    """解析 vX.Y.Z / X.Y.Z 为可比较元组；非语义化版本返回 None。"""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _latest_semver_tag(tags: list[str]) -> str:
    """从 tag 列表中取最大语义化版本（非 vX.Y.Z 格式忽略）；无则返回空串。"""
    best_tag, best_key = "", None
    for tag in tags:
        key = _semver_key(tag)
        if key and (best_key is None or key > best_key):
            best_tag, best_key = tag.strip(), key
    return best_tag


def check_git_tag_version(root: Path, local_version: str) -> list[str]:
    """审查 2026-09-05 E1：版本链 vs git tag 漂移校验。

    此前三方版本向量（manifest/pyproject/CHANGELOG）全绿仍可能掩盖
    "本地链落后于已发布 tag"（如孤立 v2.0.0 tag、远端已发 v1.2.3 而本地链 1.2.2）。
    仅校验"落后"方向：链 > tag 属正常发版间隙（版本已 bump、tag 待 release-please 打出）。
    git 不可用或无 tag（CI shallow clone 默认不拉 tag）时跳过——面向本地发版前检查。
    """
    problems: list[str] = []
    if not local_version or _semver_key(local_version) is None:
        return problems
    try:
        res = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return problems
    latest = _latest_semver_tag(res.stdout.splitlines())
    latest_key = _semver_key(latest) if latest else None
    local_key = _semver_key(local_version)
    if latest_key and local_key and local_key < latest_key:
        problems.append(
            f"[版本漂移] 本地版本链 {local_version} 落后于最新 git tag {latest}——"
            "请先 git fetch origin --tags 核对远端已发布版本；"
            "若该 tag 为孤立/过期分叉提交请清理后再发版"
        )
    return problems


def check_version_consistency(root: Path) -> list[str]:
    problems: list[str] = []
    manifest_path = root / ".release-please-manifest.json"
    pyproject_path = root / "pyproject.toml"
    if not manifest_path.exists() or not pyproject_path.exists():
        return problems
    try:
        manifest_version = str(
            json.loads(manifest_path.read_text(encoding="utf-8")).get(".", "")
        ).strip()
    except (json.JSONDecodeError, OSError) as e:
        # 审查 2026-09-01 G-7：manifest 解析失败不再静默跳过——记录为问题
        problems.append(
            f"[版本漂移] .release-please-manifest.json 解析失败: {type(e).__name__}: {e}"
        )
        manifest_version = ""
    m = re.search(
        r'^version\s*=\s*["\']([^"\']+)["\']',
        pyproject_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    pyproject_version = m.group(1).strip() if m else ""
    if manifest_version and pyproject_version and manifest_version != pyproject_version:
        problems.append(
            f"[版本漂移] .release-please-manifest.json 版本 {manifest_version} != "
            f"pyproject.toml 版本 {pyproject_version}"
        )
    # 审查 2026-09-11 R-7：release-please extra-files（__init__.py __version__）
    # 纳入版本向量——此前只查 manifest/pyproject/CHANGELOG，手工改动可静默漂移
    init_path = root / "src" / "smartsuite" / "__init__.py"
    if init_path.exists():
        m_init = re.search(
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            init_path.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        init_version = m_init.group(1).strip() if m_init else ""
        if not init_version:
            problems.append(
                "[版本漂移] src/smartsuite/__init__.py 缺少 __version__"
                "（release-please extra-files 契约，版本链四向量无法闭合）"
            )
        elif pyproject_version and init_version != pyproject_version:
            problems.append(
                f"[版本漂移] pyproject.toml 版本 {pyproject_version} != "
                f"src/smartsuite/__init__.py __version__ {init_version}"
            )
    changelog_path = root / "CHANGELOG.md"
    if changelog_path.exists():
        m2 = re.search(
            r"^##\s*\[(\d+\.\d+\.\d+)\]",
            changelog_path.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        changelog_version = m2.group(1) if m2 else ""
        if manifest_version and changelog_version and manifest_version != changelog_version:
            problems.append(
                f"[版本漂移] .release-please-manifest.json {manifest_version} != "
                f"CHANGELOG 最新发布版本 {changelog_version}"
            )
    # 审查 2026-09-05 E1：版本链 vs git tag 漂移（tag 盲区校验）
    problems += check_git_tag_version(root, pyproject_version)
    return problems


# ── 向量 7：未声明文件（--strict）────────────────────────────


def check_undeclared(root: Path, strict: bool) -> list[str]:
    if not strict:
        return []
    problems: list[str] = []
    declared = set(_parse_top_entries(root, "docs/governance/project-structure.md"))
    if not declared:
        problems.append("[配置错误] 无法从 project-structure.md 解析顶层条目（目录树格式异常？）")
        return problems
    candidates = [
        p for p in root.iterdir() if p.name not in declared and p.name not in EXCLUDED_DIRS
    ]
    # 审查 2026-09-19 F-2：.gitignore 忽略的本地产物（benchmark.json / htmlcov/ 等）豁免登记；
    # 非 git 环境（迷你仓库/CI checkout 前）返回空集 → 行为与既有严格模式一致
    ignored = _git_ignored_files(root, candidates)
    for p in candidates:
        if p.name in ignored:
            continue
        if p.is_file():
            problems.append(f"[未声明文件] {p.name}（请同步 project-structure.md 目录树）")
        elif p.is_dir():
            problems.append(f"[未声明目录] {p.name}/（请同步 project-structure.md 目录树）")
    return problems


def _git_ignored_files(root: Path, paths: list[Path]) -> set[str]:
    """返回被 .gitignore 忽略的文件名集合（本地生成产物不要求登记目录树）。

    非 git 仓库（如测试用迷你仓库）或 git 不可用时返回空集——
    此时所有文件都要求登记，保证严格模式在 CI checkout 中生效。
    """
    if not paths:
        return set()
    try:
        # --stdin -z：NUL 分隔输入/输出，不做引号转义
        # （中文路径下 git 默认 core.quotePath 会对输出加引号，splitlines 会失效）
        payload = ("\x00".join(str(p) for p in paths) + "\x00").encode("utf-8")
        r = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],
            input=payload,
            capture_output=True,
            cwd=root,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if r.returncode not in (0, 1):
        return set()
    return {
        Path(line).name
        for line in r.stdout.decode("utf-8", "replace").split("\x00")
        if line.strip()
    }


def check_subdir_undeclared(root: Path, strict: bool) -> list[str]:
    """子目录未声明检查（**递归**，审查 2026-09-21 F4-1 起）。

    规则：文件所在目录若在目录树中被**逐项列出**（声明了至少一个子项），则该文件
    必须登记；汇总性目录（如 `images/`）的内容豁免。`__pycache__` 与 .gitignore
    忽略的本地产物同样豁免。
    """
    if not strict:
        return []
    declared, dirs = _parse_tree_paths(root)
    recursive = _recursive_dirs(dirs, declared)
    check_files = [
        p
        for sub in _SUBDIR_CHECK
        if (root / sub).is_dir()
        for p in (root / sub).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    # .gitignore 忽略的生成产物（如 scripts/verify_manual_claims_output.txt）豁免登记
    ignored = _git_ignored_files(root, check_files)
    problems: list[str] = []
    for p in sorted(check_files):
        rel = p.relative_to(root).as_posix()
        if p.name == ".gitkeep" or rel in declared or p.name in ignored:
            continue
        if p.parent.relative_to(root).as_posix() in recursive:
            problems.append(f"[未声明文件] {rel}（请同步 project-structure.md 目录树）")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文档一致性验证")
    parser.add_argument("--strict", action="store_true", help="含未声明文件检查")
    args = parser.parse_args(argv)

    doc_files = collect_doc_files(ROOT)
    problems = (
        check_links(ROOT, doc_files)
        + check_backtick_paths(ROOT, doc_files)
        + check_dirs(ROOT)
        + check_agents_tree(ROOT)
        + check_semantic_consistency(ROOT, doc_files)
        + check_version_consistency(ROOT)
        + check_subdir_undeclared(ROOT, args.strict)
        + check_undeclared(ROOT, args.strict)
    )
    if problems:
        print("[FAIL] 发现以下问题：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[OK] 文档一致性验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
