"""CI 门禁分层守卫：PR 门禁（quick job）必须覆盖全部可进程内运行的测试。

对应第三轮复核 P3-6（logs/reports/verify-round3/R3-复核清单.md）：

`tests/security/`（21 例）与 `tests/crossval/`（15 例）此前**只在 full 矩阵
（main push 才跑）**，PR 阶段可静默合入安全回归与数值口径回归。
摸底时还发现 quick job 的集成测试只列了 2/8 个文件，
漏掉 chemical / reliability / warranty / workflows / packaging 五个（33 例）。

本守卫把"哪些测试必须在 PR 门禁跑"从**人工维护的清单**变成**由目录结构推导**：
新增测试目录/文件若未接入 quick job 即 FAIL，避免又一次静默漂移。

例外（有意不纳入 PR 门禁）：
  - `tests/integration/test_web_e2e.py`：需运行中的 HTTP 服务器，由 e2e job 覆盖。

审查 2026-10-09 P2-12：上述只校验「**测试**是否接入 CI」，校验不到「**门禁脚本**
是否有 CI 到达路径」—— 注入实测 I12：新增孤儿门禁 `scripts/zz_orphan_gate.py`
（无任何调用方、自身恒 exit 1）后本文件仍 10 passed / EXIT=0。
现补 `TestGateScriptsAreWired`：`scripts/` 下的**门禁类文件**每个都必须在
workflow 的 `run:` 文本或 `tests/scripts/*.py` 包装里被引用；非门禁的共用助手
与本地工具须在 `EXEMPT_GATE_SCRIPTS` / `NON_GATE_LOCAL_TOOLS` **具名登记理由**。
"""

import ast
import fnmatch
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
TESTS_DIR = ROOT / "tests"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
SCRIPTS_DIR = ROOT / "scripts"
TESTS_SCRIPTS_DIR = ROOT / "tests" / "scripts"
_SCRIPTS_REL = SCRIPTS_DIR.relative_to(ROOT).as_posix()
_SELF = Path(__file__).resolve()
_SELF_REL = _SELF.relative_to(TESTS_DIR).as_posix()

#: scripts/ 下参与"门禁 vs 本地工具"清册的扩展名（README.md 等文档不参与）
SCRIPT_SUFFIXES = (".py", ".mjs", ".sh")

# 有意不在 quick job 中运行的测试文件（须写明理由）
EXCLUDED_FROM_QUICK = {
    "tests/integration/test_web_e2e.py": "需运行中的服务器，由 e2e job 覆盖",
}

# ── 门禁脚本 → CI 接线（审查 2026-10-09 P2-12 / G-6 第二轮）────────────────────
#
# 「门禁类」= 自身带判据、失败即表示"仓库状态不合格"的脚本。它们必须有**到达路径**
# （workflow 的 run: 直接调用，或 tests/scripts/ 的 pytest 包装），否则等于没有门禁。
#
# ⚠️ 审查 2026-10-09 G-6 实测的两个漏洞（本轮的修复目标）：
#   (b) 模式**封闭**：新门禁若命名落在模式外（如 `audit_*.py`、`lint_*.py`）完全
#       不可见 —— 注入 `scripts/r2g_silent_orphan.py` 后仍 39 passed / EXIT 0；
#   (c) 「文本提及即接线」：判据是**子串搜索**，任何注释/docstring 提及都算接线
#       —— 注入 `scripts/verify_r2g_ghost.py`（恒 exit 1、无人执行）+ 一行注释后
#       307 passed / EXIT 0。
# 现判据（两层，均不依赖"人记得登记"）：
#   ① **默认须表态**：`scripts/` 下每个脚本必须要么匹配 `GATE_PATTERNS`（→ 门禁，
#      必须有执行证据），要么在 `NON_GATE_LOCAL_TOOLS` **具名登记理由**（→ 本地工具）。
#      新脚本未被分类即 FAIL ⇒ 漏项不再是默认态。
#   ② **接线 = 执行点**：`workflow 步骤命令里的命令行参数` 或 `tests/scripts/*.py 里
#      指向它的字符串字面量`（docstring 与整行注释**不算**）。从不验证"是否真的跑过"
#      的文本子串判据被彻底移除。
GATE_PATTERNS = (
    "check_*.mjs",  # 前端/导出流静态门禁（经 tests/scripts/ 包装进 CI）
    "*.mjs",  # 其余 Node 脚本（非门禁的共用助手须具名豁免）
    "*_gate.py",  # claims_gate / templates_gate
    "verify_*.py",  # verify_docs / verify_consistency / verify_cross_consistency …
    "truth_coverage.py",
    "falsy_audit.py",
    "test_quality_guard.py",
    "validate-commit-msg.sh",  # 唯一非 Python 门禁（ci.yml 提交规范检查调用）
)

#: 允许**无执行证据**的门禁类文件（键 = `scripts/` 下的文件名）→ 理由。
#:
#: 登记是「经审定的例外」：新门禁若没有任何 workflow/tests 执行点，
#: `TestGateScriptsAreWired` 会 FAIL 并点名，除非在此写明理由；
#: 且条目数受 `GATE_WIRING_FREEZE_BASELINE` 封顶（见该常量）。
GATE_WIRING_FREEZE: dict[str, str] = {
    "claims_gate.py": (
        "库模块（非独立执行体）：无 `__main__`、自身不产出结论；判据函数 "
        "`classify_missing` 由 tests/scripts/test_claims_gate.py 导入直接调用"
        "（import 形式，非 subprocess 执行点）。故无『执行点证据』但它并非孤儿"
    ),
    "templates_gate.py": (
        "库模块：判据函数 `validate_template_tasks` 由 verify_consistency.py 与 "
        "tests/scripts/test_templates_gate.py 导入后直接调用 —— 执行点是「函数调用」"
        "而非「进程执行」，故不在本守卫的执行点证据内；它随 verify_consistency 进 CI"
    ),
    "_probe_python.mjs": (
        "共用解释器探测助手（**非门禁**）：自身无判据，被 check_*.mjs 以 "
        "`import { resolvePython } from './_probe_python.mjs'` 导入；测试侧由 "
        "tests/scripts/test_python_probe.py 用 NODE 直接加载执行该文件。"
        "命中 `*.mjs` 是因为模式要覆盖全部 Node 脚本 —— 登记以免把助手误当门禁"
    ),
    "verify_all.py": (
        "本地一键入口（AGENTS.md「一键全量验证」）：编排其它门禁、自身不判据，"
        "由开发者在仓库根手动运行 —— 有意不作 CI 门禁（其覆盖的步骤由 CI 各 job "
        "分别承担）。独立入口的『直接运行』判据由 tests/scripts/test_verify_all* 之外"
        "的本地约定承担，故无执行点证据"
    ),
}

#: `GATE_WIRING_FREEZE` 的封顶条数。新增条目必须**显式**上调本常量 ——
#: 目的是把"我又加了一个没有执行点的门禁"变成一次可见、可审、可 review 的改动，
#: 而不是让冻结表悄悄长大（同 `WEAK_ASSERT_EXEMPT` 的具名豁免模式）。
GATE_WIRING_FREEZE_BASELINE = 4

#: 非门禁类的本地工具清单（**不作 CI 门禁是有意设计**；登记以防"看起来没人管"）。
#: 这些文件不匹配 `GATE_PATTERNS`，故不参与接线校验，仅作可审计清册。
#: ⚠️ 与旧实现的差别：清册不再是"可选补充"，而是**默认须表态**的另一半 ——
#: `TestScriptInventoryIsExplicit` 要求 scripts/ 下每个脚本要么是门禁、要么在这里。
NON_GATE_LOCAL_TOOLS: dict[str, str] = {
    "new_task.py": "本地脚手架（注册链生成器）：由 tests/scripts/test_new_task.py 覆盖，非 CI 门禁",
    "demo.py": "本地演示脚本（tests/scripts/test_demo.py 跑它，但它是演示而非判据）",
    "doctor.py": "本地环境诊断（AGENTS.md「环境诊断」）：诊断环境就绪性，不对仓库状态判红",
    "generate_images.py": "本地文档配图生成",
    "generate_test_data.py": "本地测试数据生成",
    "gen_requirements.py": "本地 requirements 生成",
    "retry.py": "本地重试工具",
    "run_smartsuite.py": "本地启动器",
    "setup_offline.py": "本地离线安装辅助",
    "common.py": "共用助手（child_env 等），被多个门禁导入，自身无判据",
    "manual_claims_freshness.py": (
        "库模块（CLAIM 锚点解析，唯一实现）：CI 判据由 verify_manual_claims.py 承担"
        "（ci.yml quick 直接调用，进程内调用本模块的 check_manual_freshness）；"
        "本文件的**独立入口** `python scripts/manual_claims_freshness.py` 仅作本地"
        "快速校验，由 tests/scripts/test_manual_claims_freshness.py 以 subprocess 真跑。"
        "审查 2026-10-09 G-3：其独立入口曾可被 runpy 跨模块 sys.exit 污染成"
        "『exit 0 且零结论输出』，现改为自建命名空间 exec（不再代理被导入脚本退出码）"
    ),
    "run_affected_tests.py": "本地增量测试路由（AGENTS.md），非 CI 门禁",
}


def _script_files(scripts_dir: Path) -> list[Path]:
    """`scripts/` 下参与清册的脚本文件（.py / .mjs / .sh）。"""
    if not scripts_dir.is_dir():
        return []
    return sorted(p for p in scripts_dir.iterdir() if p.is_file() and p.suffix in SCRIPT_SUFFIXES)


def classify_script(name: str) -> str:
    """返回 `"gate"` 或 `"local"`（门禁类 / 本地工具类）。"""
    return "gate" if any(fnmatch.fnmatch(name, pat) for pat in GATE_PATTERNS) else "local"


def unclassified_scripts(
    scripts_dir: Path = SCRIPTS_DIR, inventory: dict[str, str] | None = None
) -> list[str]:
    """既不是门禁模式、又未登记进本地工具清册的脚本（默认须表态，漏项既 FAIL）。

    这是 G-6(b) 的修复：旧判据是**封闭白名单**（只有匹配模式的才检查），
    命名落在模式外的新门禁**完全不可见**；现在"未被分类"本身就是失败。
    """
    inventory = NON_GATE_LOCAL_TOOLS if inventory is None else inventory
    return [
        p.name
        for p in _script_files(scripts_dir)
        if classify_script(p.name) == "local" and p.name not in inventory
    ]


def iter_gate_scripts(scripts_dir: Path = SCRIPTS_DIR) -> list[str]:
    """`scripts/` 下的门禁类文件名（按 `GATE_PATTERNS` 匹配）。"""
    return [p.name for p in _script_files(scripts_dir) if classify_script(p.name) == "gate"]


def workflow_run_commands(
    workflows_dir: Path = WORKFLOWS_DIR, scripts_dir: Path = SCRIPTS_DIR
) -> set[str]:
    """全部 workflow `run:` 文本里出现的**本仓脚本文件名**（命令行参数形态）。

    与旧实现的差别（G-6c）：这里读的是**步骤命令**（`run:`），不是整份 YAML 文本
    —— YAML 注释、step 的 `name:` 文案、`if:` 条件都不再能"制造接线"。
    返回的是**文件名**（`verify_docs.py`），与 `tests/scripts` 侧证据同口径。
    """
    names = {p.name for p in _script_files(scripts_dir)}
    tokens: set[str] = set()
    for wf in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for job in (data.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                run = step.get("run")
                if not run:
                    continue
                for tok in re.split(r"[\s|;&()<>\"'`]+", str(run)):
                    if tok:
                        tokens.add(tok.strip())
    return {_basename(t) for t in tokens if _basename(t) in names} if names else set()


def _basename(tok: str) -> str:
    """命令行片段 → 文件名（`scripts/verify_docs.py` / `./scripts/x.mjs` → `x.mjs`）。"""
    return re.split(r"[/\\]", tok)[-1]


def _docstring_lines(tree: ast.AST) -> set[int]:
    """模块 / 类 / 函数 docstring 的起始行号（这些字面量不算"指向脚本的引用"）。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.add(first.value.lineno)
    return lines


def _rel_scripts_dir(scripts_dir: Path) -> str:
    """`scripts_dir` 相对仓库根（不在仓内时退回目录名，供 tmp_path 用例）。"""
    try:
        return scripts_dir.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return scripts_dir.name


def _test_file_evidence(path: Path, scripts_dir: Path) -> set[str]:
    """某测试文件里**指向 scripts/ 下脚本**的字符串字面量（去掉 docstring）。

    为什么不用 `name in source` 子串判据：那会把注释/docstring 里的提及也算成接线
    （G-6c 的 ghost gate 正是这样被判为"已接线"的）。这里只取 AST 的字面量、
    且剔除 docstring —— 整行注释不进 AST，天然被排除。

    反向写法：把 `tests/scripts/*.py` 拼成一个字面量池，用**白名单路径模式**
    （只可能是本仓脚本：`.py` / `.mjs` / `.sh` + 存在的路径形状）去池里找，
    而不是拿文件名去池里做裸子串搜索。故整行注释里的提及、
    以及模块/函数 docstring 里的提及，都不算证据。
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    skip = _docstring_lines(tree)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.lineno not in skip
    ]
    return _script_paths_in("\n".join(literals), scripts_dir)


def _script_paths_in(text: str, scripts_dir: Path) -> set[str]:
    """字面量池 → 命中的**脚本文件名**。

    ⚠️ 两个坑（都实测踩过）：
      ① 不能假设字面量池里看得到目录前缀：源码写成 `ROOT / "scripts" / "x.py"` 时，
         AST 的字面量是**分开**的多个片段，拼起来并不含 `scripts/x.py` 连续子串；
      ② 拿这些片段拼接去 `f"{rel}/" in joined` 比对会把 `"\n"` 之类的转义串当路径。
    故统一以**文件名**为锚（`scripts/` 下都是本仓独有的具体名，且全仓无同名文件，
    见 `test_script_names_are_unique`），路径前缀只用于人读日志，不参与判据。
    """
    text = text.replace("\\", "/")
    names = "|".join(re.escape(p.name) for p in _script_files(scripts_dir))
    if not names:
        return set()
    return {m.group("name") for m in re.finditer(rf"(?P<name>{names})(?![\w.])", text)}


def _looks_like_path(tok: str) -> bool:
    """命令行片段是否形如路径（含分隔符）——用于日志可读性，不参与判据。"""
    return "/" in tok or "\\" in tok


def wiring_evidence(
    scripts_dir: Path = SCRIPTS_DIR, tests_scripts_dir: Path = TESTS_SCRIPTS_DIR
) -> set[str]:
    """有**执行点证据**的脚本路径集合。

    证据来源只有两类（G-6 判据升级）：
      ① workflow 步骤命令里的命令行参数（`bash scripts/validate-commit-msg.sh`）；
      ② `tests/scripts/*.py` 里指向该脚本的字符串字面量（`ROOT / "scripts" / "x.py"`、
         `subprocess.run([... , "scripts/x.py"])` …）—— docstring / 注释不算。
    **本文件（冻结表所在地）被排除**，否则冻结键名会"自证被引用"
    （见 `test_self_reference_loophole_is_closed`）。
    """
    ev = set(workflow_run_commands())
    for p in sorted(tests_scripts_dir.glob("*.py")):
        if _is_self(p, tests_scripts_dir):
            continue
        ev |= _test_file_evidence(p, scripts_dir)
    return ev


def _is_self(path: Path, tests_scripts_dir: Path) -> bool:
    """该文件是否就是本文件（只对真实目录成立，tmp 目录里的同名文件不算）。"""
    return (
        path.name == _SELF.name
        and path.parent.resolve() == TESTS_SCRIPTS_DIR.resolve()
        and tests_scripts_dir.resolve() == TESTS_SCRIPTS_DIR.resolve()
    )


def unwired_gate_scripts(
    scripts_dir: Path,
    evidence: set[str] | None = None,
    frozen: dict[str, str] | None = None,
    tests_scripts_dir: Path = TESTS_SCRIPTS_DIR,
) -> list[str]:
    """返回**没有任何执行点证据**、也未登记冻结理由的门禁类文件名。

    判据（G-6 第二轮）：该文件名必须出现在证据集合里（证据 = workflow 步骤命令的
    命令行参数 + `tests/scripts/*.py` 的代码字面量），或 `frozen` 具名登记 ——
    不再接受"某处文本提到过它"。

    `evidence=None` 时自行收集（workflow 命令 + tests/scripts 字面量）。
    """
    frozen = GATE_WIRING_FREEZE if frozen is None else frozen
    if evidence is None:
        evidence = wiring_evidence(scripts_dir, tests_scripts_dir)
    ev = set(evidence)
    missing = []
    for p in _script_files(scripts_dir):
        if classify_script(p.name) != "gate" or p.name in frozen:
            continue
        if p.name not in ev and _rel_scripts_dir(scripts_dir) + "/" + p.name not in ev:
            missing.append(p.name)
    return missing


@pytest.fixture(scope="module")
def quick_runs() -> str:
    """quick job 中所有 `run:` 文本的拼接。"""
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = data["jobs"]["quick"]["steps"]
    return "\n".join((s.get("run") or "") for s in steps)


@pytest.fixture(scope="module")
def all_test_files() -> list[str]:
    """仓库内全部测试文件（相对路径，POSIX 分隔符）。"""
    out = []
    for p in sorted(TESTS_DIR.rglob("test_*.py")):
        out.append(p.relative_to(ROOT).as_posix())
    return out


class TestQuickJobCoversAllTestDirs:
    """每个测试子目录都必须被 quick job 覆盖（按目录粒度）。"""

    def test_every_test_subdir_is_referenced(self, quick_runs):
        subdirs = sorted(
            {p.parent.relative_to(ROOT).as_posix() for p in TESTS_DIR.rglob("test_*.py")}
        )
        missing = []
        for d in subdirs:
            if d == "tests":
                continue
            # 目录被整体引用（`tests/xxx/`）或其中任一文件被单独引用即算覆盖
            if f"{d}/" in quick_runs:
                continue
            if any(f"{d}/" in line for line in quick_runs.splitlines() if "pytest" in line):
                continue
            missing.append(d)
        assert not missing, (
            f"以下测试目录未接入 PR 门禁（quick job）: {missing}。"
            "若为有意排除，请在 EXCLUDED_FROM_QUICK 登记理由。"
        )

    def test_security_dir_is_in_quick(self, quick_runs):
        """安全回归必须在 PR 阶段跑（不该只在 main push 才验证）。"""
        assert "tests/security/" in quick_runs

    def test_crossval_dir_is_in_quick(self, quick_runs):
        """交叉验证必须在 PR 阶段跑。"""
        assert "tests/crossval/" in quick_runs


class TestQuickJobCoversIntegrationFiles:
    """集成测试目录未被整体引用，须逐文件登记 —— 逐个断言避免漏项。"""

    def _integration_files(self) -> list[str]:
        return [
            p.name
            for p in sorted((TESTS_DIR / "integration").glob("test_*.py"))
            if p.name != "__init__.py"
        ]

    def test_every_integration_file_is_covered_or_excused(self, quick_runs):
        missing = []
        for name in self._integration_files():
            rel = f"tests/integration/{name}"
            if rel in EXCLUDED_FROM_QUICK:
                continue
            if name in quick_runs:
                continue
            missing.append(rel)
        assert not missing, f"以下集成测试文件既未接入 quick job 也未登记排除理由: {missing}"

    def test_only_web_e2e_is_excused(self):
        """排除清单必须精确等于已知的服务器依赖项（防止随意扩大豁免）。"""
        assert set(EXCLUDED_FROM_QUICK) == {"tests/integration/test_web_e2e.py"}

    def test_excused_file_really_needs_a_server(self):
        """被排除的文件必须确实依赖服务器（否则排除理由不成立）。"""
        src = (ROOT / "tests/integration/test_web_e2e.py").read_text(encoding="utf-8")
        assert "pytest.skip" in src and "5050" in src, (
            "test_web_e2e.py 的排除理由（需服务器）与源码不符，请复核"
        )

    def test_web_e2e_is_covered_by_e2e_job(self):
        """被 quick 排除的，必须确有别的 job 覆盖（不允许"没人跑"）。"""
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        e2e = "\n".join((s.get("run") or "") for s in data["jobs"]["e2e"]["steps"])
        assert "test_web_e2e.py" in e2e


class TestQuickJobStaysReasonable:
    """quick 是 PR 门禁，须保持轻量（防止不知不觉变重）。"""

    def test_quick_job_has_timeout(self):
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        assert "timeout-minutes" in data["jobs"]["quick"], "quick job 必须有超时上限"

    def test_quick_job_does_not_run_full_suite_twice(self, quick_runs):
        """quick 不应出现裸 `pytest tests/`（那等于把 full job 搬进 PR 门禁）。

        注意区分：`pytest tests/xxx/` 是分层运行，属正常。
        """
        bare = [
            line
            for line in quick_runs.splitlines()
            if re.search(r"pytest\s+tests/\s*($|-)", line.strip())
        ]
        assert not bare, f"quick job 不应跑全量裸 pytest tests/: {bare}"

    def test_full_job_still_runs_whole_suite(self):
        """分层不能以牺牲全量为代价 —— full job 必须仍跑 `pytest tests/`。"""
        data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        full = "\n".join((s.get("run") or "") for s in data["jobs"]["full"]["steps"])
        assert re.search(r"pytest\s+tests/\s+-q", full), "full job 应跑全量测试"


class TestGateScriptsAreWired:
    """门禁脚本 → CI 接线（审查 2026-10-09 P2-12，判据于 G-6 第二轮升级）。

    原守卫只问「**测试**有没有接入 CI」，新增的孤儿门禁脚本无人调用时仍全绿
    （注入 I12 实测 10 passed / EXIT=0）。P2-12 补了「**门禁**有没有到达路径」，
    但判据仍是两处漏洞：模式外命名隐形（G-6b）、文本提及即算接线（G-6c）。
    本类的判据现为：**执行点证据**（workflow 命令参数 / tests 里的字面量路径）
    + **默认须表态**（未分类即 FAIL）。
    """

    def test_every_gate_script_is_wired_or_excused(self):
        """每个门禁类脚本都必须有执行点证据，或在冻结表具名登记理由。"""
        missing = unwired_gate_scripts(SCRIPTS_DIR, wiring_evidence(), GATE_WIRING_FREEZE)
        assert not missing, (
            f"以下门禁脚本没有任何**执行点**（workflow 命令 args / tests 字面量路径）、"
            f"也未登记冻结理由: {missing}。"
            "请接入 workflow run: 或 tests/scripts/ 的 pytest 包装（subprocess 真跑）；"
            "确属库模块/共用助手的，在 GATE_WIRING_FREEZE 具名登记理由。"
        )

    def test_orphan_gate_is_detected(self, tmp_path):
        """**负向注入**：新增孤儿门禁（无任何调用方）必须被点名。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check_wired.mjs").write_text("// 已接线\n")
        (scripts / "zz_orphan_gate.py").write_text("print('orphan')\nraise SystemExit(1)\n")
        missing = unwired_gate_scripts(
            scripts, {"check_wired.mjs"}, {}, tests_scripts_dir=tmp_path / "none"
        )
        assert missing == ["zz_orphan_gate.py"], f"孤儿门禁未被点名: {missing}"

    def test_ghost_gate_mentioning_only_in_comment_is_detected(self, tmp_path):
        """**G-6c 负向注入**：仅被注释/docstring 提及的门禁必须仍被判为孤儿。

        审查实测原形：新增 `scripts/verify_r2g_ghost.py`（恒 exit 1、无人执行），
        在某个测试文件里加一行注释提及它的路径 → 旧判据（子串搜索）判为"已接线"，
        307 passed / EXIT 0。本用例把该形态转正为回归用例。
        """
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "verify_r2g_ghost.py").write_text("raise SystemExit(1)\n")
        tests = tmp_path / "tst"
        tests.mkdir()
        (tests / "test_ghost_wired.py").write_text(
            '"""本文件说明：相关检查见 scripts/verify_r2g_ghost.py。"""\n'
            "\n"
            "# 备注（仅为字符串提及）：相关检查见 scripts/verify_r2g_ghost.py\n"
            "def test_noop():\n"
            "    assert True\n",
            encoding="utf-8",
        )
        missing = unwired_gate_scripts(scripts, set(), {}, tests_scripts_dir=tests)
        assert missing == ["verify_r2g_ghost.py"], (
            f"注释/docstring 提及被当成了接线（G-6c 回归）: {missing}"
        )

    def test_real_execution_point_counts_as_wired(self, tmp_path):
        """**反面守卫**：真正被 subprocess 执行的路径字面量必须算接线。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "verify_r2g_real.py").write_text("print('ok')\n")
        tests = tmp_path / "tst"
        tests.mkdir()
        (tests / "test_real_wired.py").write_text(
            "import subprocess\n"
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[1]\n"
            "SCRIPT = ROOT / 'scripts' / 'verify_r2g_real.py'\n"
            "\n"
            "def test_runs():\n"
            "    subprocess.run(['python', str(SCRIPT)], check=True)\n",
            encoding="utf-8",
        )
        assert unwired_gate_scripts(scripts, None, {}, tests_scripts_dir=tests) == []

    def test_excused_gate_is_not_flagged(self, tmp_path):
        """**反面守卫**：具名冻结的门禁脚本不得被判为孤儿（否则冻结表形同虚设）。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "helper.mjs").write_text("// 共用助手\n")
        missing = unwired_gate_scripts(
            scripts,
            set(),
            {"helper.mjs": "共用助手（非门禁）"},
            tests_scripts_dir=tmp_path / "none",
        )
        assert missing == []

    def test_real_repo_has_no_orphan_gate(self):
        """真实仓库现状：孤儿的门禁数必须为 0（与上面同一判据，独立复核用）。"""
        assert unwired_gate_scripts(SCRIPTS_DIR, wiring_evidence(), GATE_WIRING_FREEZE) == []

    def test_wiring_evidence_really_contains_gate_scripts(self):
        """本守卫**本身有效**：真实证据集必须覆盖已知已接线的门禁。

        G-6(b) 的教训：判据看不见文件时，一切"没发现问题"都没有意义 ——
        故先钉住"证据集认得出这些"，再谈"零孤儿"。
        """
        ev = wiring_evidence()
        must = {
            "verify_docs.py",
            "verify_consistency.py",
            "verify_manual_claims.py",
            "falsy_audit.py",
            "validate-commit-msg.sh",
            "test_quality_guard.py",
            "truth_coverage.py",
            "check_params_panel.mjs",
        }
        assert must <= ev, f"证据集缺少这些已接线的门禁（判据失效）: {sorted(must - ev)}"
        assert len(iter_gate_scripts()) >= 10, "门禁分类器把文件都漏掉了"

    def test_workflow_command_evidence_is_from_run_only(self):
        """workflow 证据只认 `run:` 里的命令 —— 注释/`name:`/`if:` 都不算接线。"""
        cmds = workflow_run_commands()
        assert "verify_docs.py" in cmds, "真实 workflow 未认出 verify_docs.py"
        # `validate-commit-msg.sh` 出现在 ci.yml 的**回显文案**里（run 内的 echo），
        # 同时也确实是 `bash scripts/validate-commit-msg.sh` 的执行点 —— 两者都读得到；
        # 但 `verify_manual_claims.py` 只在注释里被 ci.yml 提及过，必须在 run: 中真实执行
        assert "verify_manual_claims.py" in cmds, "verify_manual_claims.py 应有 run: 执行点"

    def test_script_names_are_unique_across_scan_pool(self):
        """以**文件名**为锚的前提：`scripts/` 下无重名文件（否则判据会被同名混淆）。"""
        names = [p.name for p in _script_files(SCRIPTS_DIR)]
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert not dupes, f"scripts/ 下存在重名文件，文件名锚点判据失效: {dupes}"

    def test_exemptions_have_reasons(self):
        """冻结必须写明理由（空理由/纯符号视为未登记）。"""
        for name, reason in GATE_WIRING_FREEZE.items():
            assert reason and len(reason.strip()) >= 8, f"{name} 的冻结理由过短: {reason!r}"

    def test_freeze_table_does_not_grow_silently(self):
        """冻结表条数封顶：新增条目必须显式上调基线常量（可见、可审）。"""
        assert len(GATE_WIRING_FREEZE) <= GATE_WIRING_FREEZE_BASELINE, (
            f"GATE_WIRING_FREEZE 已有 {len(GATE_WIRING_FREEZE)} 条 > 基线 "
            f"{GATE_WIRING_FREEZE_BASELINE} —— 新加「没有执行点的门禁」必须显式上调 "
            "GATE_WIRING_FREEZE_BASELINE，并在理由里说明为何无法接入 CI"
        )

    def test_exemption_targets_and_inventory_exist(self):
        """登记表/清册的键必须都对应真实文件（防拼写漂移让条目静默失效）。"""
        for name in list(GATE_WIRING_FREEZE) + list(NON_GATE_LOCAL_TOOLS):
            assert (SCRIPTS_DIR / name).is_file(), f"登记项 {name} 在 scripts/ 下不存在"

    def test_exempted_entries_are_gate_class_or_documented_tools(self):
        """冻结键必须确实是门禁类（否则该用 NON_GATE_LOCAL_TOOLS 清册）。"""
        gate = set(iter_gate_scripts())
        stray = [n for n in GATE_WIRING_FREEZE if n not in gate]
        assert not stray, f"以下冻结项不匹配任何门禁模式，请移入 NON_GATE_LOCAL_TOOLS: {stray}"

    def test_self_reference_loophole_is_closed(self):
        """本文件（冻结表所在地）不得计入引用来源。

        否则 `GATE_WIRING_FREEZE` 的键名会"自证被引用"，接线校验对登记项失效。
        """
        for p in sorted(TESTS_SCRIPTS_DIR.glob("*.py")):
            if _is_self(p, TESTS_SCRIPTS_DIR):
                continue
            assert "GATE_WIRING_FREEZE" not in p.read_text(encoding="utf-8", errors="replace")
        # 对照：冻结键名确实写在本文件里 —— 若不排除本文件，它们会全部"被引用"
        self_src = Path(__file__).read_text(encoding="utf-8")
        assert "_probe_python.mjs" in self_src
        assert _is_self(_SELF, TESTS_SCRIPTS_DIR), "本文件的自我识别失效"

    def test_local_tools_inventory_has_reasons(self):
        """非门禁本地工具清册同样须写明理由。"""
        for name, reason in NON_GATE_LOCAL_TOOLS.items():
            assert reason and len(reason.strip()) >= 4, f"{name} 的清册理由过短: {reason!r}"


class TestScriptInventoryIsExplicit:
    """**G-6(b) 的修复**：`scripts/` 下每个脚本都必须被分类（默认须表态）。

    旧判据是封闭白名单 —— 只有匹配 `GATE_PATTERNS` 的文件才被检查，
    新门禁若命名为 `audit_*.py` / `lint_*.py` 就**完全隐形**（注入实测 39 passed）。
    现反转默认：未分类 = FAIL，新增脚本必须显式表态（是门禁 → 要执行点；
    是本地工具 → 进清册写理由）。
    """

    def test_every_script_is_classified(self):
        missing = unclassified_scripts()
        assert not missing, (
            f"以下 scripts/ 脚本既不是门禁类、也未登记进 NON_GATE_LOCAL_TOOLS: {missing}。"
            "请二选一表态：① 门禁 → 接入 CI/测试并确认执行点证据；"
            "② 本地工具 → 在 NON_GATE_LOCAL_TOOLS 写明理由"
        )

    def test_unknown_script_is_detected(self, tmp_path):
        """**负向注入（G-6b 原形）**：命名落在模式外的新脚本必须被点名。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "r2g_silent_orphan.py").write_text("raise SystemExit(1)\n")
        missing = unclassified_scripts(scripts, {})
        assert missing == ["r2g_silent_orphan.py"], f"模式外脚本未被点名: {missing}"

    def test_shell_gate_is_gate_class(self):
        """`validate-commit-msg.sh` 是唯一非 Python 门禁，必须被分类为门禁类。"""
        assert classify_script("validate-commit-msg.sh") == "gate"
        assert classify_script("doctor.py") == "local"


RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"

#: 版本链断言脚本必须出现的两个 job（审查 2026-10-09 P2-13：原先只在手工路径）
VERSION_CHAIN_JOBS = ("release-please", "build-artifacts")

#: 版本链断言的**四向量**（审查 2026-10-09 G-12：原实现只断言 3 个，
#: 注释却称"四向量"；现补 CHANGELOG.md 断言 —— 与 verify_docs.py:560-565 同源表达式）
VERSION_CHAIN_TOKENS = (
    "pyproject.toml",
    ".release-please-manifest.json",
    "CHANGELOG.md",
    "TAG_NAME",
)


class TestReleaseWorkflowHardening:
    """发版 workflow 的并发保护 / 权限收敛 / 双路径版本链断言（审查 P2-13）。"""

    @staticmethod
    def _data() -> dict:
        return yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))

    def test_concurrency_guard_present(self):
        """连续两次 main push 不得并发跑 release-please；发版中不得被取消。"""
        conc = self._data().get("concurrency")
        assert conc, "release.yml 缺 concurrency（连续 push 可并发跑 release-please）"
        assert conc.get("group") == "release-${{ github.ref }}"
        assert conc.get("cancel-in-progress") is False, (
            "发版过程不得被后续 push 取消（中断会留下有 tag 无产物的半成品）"
        )

    def test_build_artifacts_has_scoped_permissions(self):
        """上传产物只需 contents: write —— job 级收敛，不继承顶层 pull-requests: write。"""
        perms = self._data()["jobs"]["build-artifacts"].get("permissions")
        assert perms == {"contents": "write"}, f"build-artifacts 权限应收敛: {perms}"

    @pytest.mark.parametrize("job", VERSION_CHAIN_JOBS)
    def test_version_chain_asserted_on_both_paths(self, job):
        """两条发版路径都必须显式断言 tag == pyproject == manifest == CHANGELOG。

        审查 2026-10-09 G-12：token 列表加上 `CHANGELOG.md` —— 原实现只比对 3 个，
        `CHANGELOG` 从不参与（而它恰是唯一在 main/发版时点无守卫的向量）。
        """
        steps = self._data()["jobs"][job]["steps"]
        script = "\n".join(s.get("run") or "" for s in steps)
        assert "校验 tag 与版本链一致" in "\n".join(s.get("name") or "" for s in steps), (
            f"{job} 缺版本链断言步骤（自动路径原先只靠 extra-files 结构性保证）"
        )
        for token in VERSION_CHAIN_TOKENS:
            assert token in script, f"{job} 的版本链断言缺 {token}"

    @pytest.mark.parametrize("job", VERSION_CHAIN_JOBS)
    def test_version_chain_assertion_uses_verify_docs_regex(self, job):
        """CHANGELOG 判据必须与 `verify_docs.check_version_consistency` 同源（SSOT）。"""
        steps = self._data()["jobs"][job]["steps"]
        script = "\n".join(s.get("run") or "" for s in steps)
        assert r"^##\s*\[(\d+\.\d+\.\d+)\]" in script, (
            f"{job} 的 CHANGELOG 判据与 scripts/verify_docs.py 的表达式不同源"
        )

    def test_auto_path_uses_release_output_tag(self):
        """自动路径必须以 release-please 的 tag_name 输出为断言对象（而非 ref_name）。"""
        steps = self._data()["jobs"]["release-please"]["steps"]
        step = next(s for s in steps if (s.get("name") or "").startswith("校验 tag 与版本链一致"))
        assert step["env"]["TAG_NAME"] == "${{ steps.release.outputs.tag_name }}"
        assert step.get("if") == "steps.release.outputs.release_created == 'true'"
