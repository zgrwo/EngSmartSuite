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
_SELF = Path(__file__).resolve()

# 有意不在 quick job 中运行的测试文件（须写明理由）
EXCLUDED_FROM_QUICK = {
    "tests/integration/test_web_e2e.py": "需运行中的服务器，由 e2e job 覆盖",
}

# ── 门禁脚本 → CI 接线（审查 2026-10-09 P2-12）──────────────────────────────
#
# 「门禁类」= 自身带判据、失败即表示"仓库状态不合格"的脚本。它们必须有**到达路径**
# （workflow 的 run: 直接调用，或 tests/scripts/ 的 pytest 包装），否则等于没有门禁。
GATE_PATTERNS = (
    "check_*.mjs",  # 前端/导出流静态门禁（经 tests/scripts/ 包装进 CI）
    "*.mjs",  # 其余 Node 脚本（非门禁的共用助手须具名豁免）
    "*_gate.py",  # claims_gate / templates_gate
    "verify_*.py",  # verify_docs / verify_consistency / verify_cross_consistency …
    "truth_coverage.py",
    "falsy_audit.py",
    "test_quality_guard.py",
)

#: 允许**无引用**的门禁类文件（键 = `scripts/` 下的文件名）→ 理由。
#:
#: 登记是「经审定的例外」：新增门禁脚本若无人调用，`TestGateScriptsAreWired`
#: 会 FAIL 并点名，除非在此写明理由。
EXEMPT_GATE_SCRIPTS: dict[str, str] = {
    "_probe_python.mjs": (
        "共用解释器探测助手（**非门禁**）：自身无判据，只被 check_*.mjs 与 "
        "tests/scripts/test_python_probe.py 调用。命中 `*.mjs` 模式是因为"
        "模式要覆盖全部 Node 脚本；登记豁免以免把助手误当门禁"
    ),
    "verify_all.py": (
        "本地一键入口（AGENTS.md「一键全量验证」）：编排其它门禁、自身不判据，"
        "由开发者在仓库根手动运行 —— 不作 CI 门禁"
    ),
}

#: 非门禁类的本地工具清单（**不作 CI 门禁是有意设计**；登记以防"看起来没人管"）。
#: 这些文件不匹配 `GATE_PATTERNS`，故不参与接线校验，仅作可审计清册。
NON_GATE_LOCAL_TOOLS: dict[str, str] = {
    "new_task.py": "本地脚手架（注册链生成器）：由 tests/scripts/test_new_task.py 覆盖，非 CI 门禁",
    "demo.py": "本地演示脚本",
    "doctor.py": "本地环境诊断（AGENTS.md「环境诊断」）",
    "generate_images.py": "本地文档配图生成",
    "generate_test_data.py": "本地测试数据生成",
    "gen_requirements.py": "本地 requirements 生成",
    "retry.py": "本地重试工具",
    "run_smartsuite.py": "本地启动器",
    "setup_offline.py": "本地离线安装辅助",
    "common.py": "共用助手（child_env 等），被多个门禁导入，自身无判据",
    "manual_claims_freshness.py": "库模块（CLAIM 锚点解析），由 verify_manual_claims.py 与 tests/scripts 包装调用",
    "run_affected_tests.py": "本地增量测试路由（AGENTS.md），非 CI 门禁",
}


def iter_gate_scripts(scripts_dir: Path = SCRIPTS_DIR) -> list[str]:
    """`scripts/` 下的门禁类文件名（按 `GATE_PATTERNS` 匹配）。"""
    if not scripts_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in scripts_dir.iterdir()
        if p.is_file() and any(fnmatch.fnmatch(p.name, pat) for pat in GATE_PATTERNS)
    )


def workflow_run_text(workflows_dir: Path = WORKFLOWS_DIR) -> str:
    """全部 workflow 的 `run:` 文本拼接（含非 ci.yml 的 job）。"""
    chunks: list[str] = []
    for wf in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for job in (data.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                run = step.get("run")
                if run:
                    chunks.append(str(run))
    return "\n".join(chunks)


def wrapper_source_text(tests_scripts_dir: Path = TESTS_SCRIPTS_DIR) -> str:
    """`tests/scripts/*.py` 源码拼接 —— **排除本文件**。

    排除是必须的：豁免表的键名（`_probe_python.mjs` 等）就写在本文件里，
    若把本文件计入引用来源，每个登记项都会"自证被引用"，豁免表失去意义
    （见 `test_self_reference_loophole_is_closed`）。
    """
    chunks: list[str] = []
    for p in sorted(tests_scripts_dir.glob("*.py")):
        if p.resolve() == _SELF:
            continue
        chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def unwired_gate_scripts(scripts_dir: Path, haystack: str, exempt: dict[str, str]) -> list[str]:
    """返回既未被引用、也未登记豁免的门禁类文件名（审查 P2-12 的判据）。"""
    return [
        name
        for name in iter_gate_scripts(scripts_dir)
        if name not in haystack and name not in exempt
    ]


def _gate_haystack() -> str:
    return workflow_run_text() + "\n" + wrapper_source_text()


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
    """门禁脚本 → CI 接线（审查 2026-10-09 P2-12）。

    原守卫只问「**测试**有没有接入 CI」，新增的孤儿门禁脚本无人调用时仍全绿
    （注入 I12 实测 10 passed / EXIT=0）。本类补上「**门禁**有没有到达路径」。
    """

    def test_every_gate_script_is_wired_or_excused(self):
        """每个门禁类脚本都必须被 workflow `run:` 或 `tests/scripts/` 包装引用。"""
        missing = unwired_gate_scripts(SCRIPTS_DIR, _gate_haystack(), EXEMPT_GATE_SCRIPTS)
        assert not missing, (
            f"以下门禁脚本既未被 CI 引用、也未登记豁免: {missing}。"
            "请接入 workflow run: 或 tests/scripts/ 的 pytest 包装；"
            "确属共用助手/本地工具的，在 EXEMPT_GATE_SCRIPTS 具名登记理由。"
        )

    def test_orphan_gate_is_detected(self, tmp_path):
        """**负向注入**：新增孤儿门禁（无任何调用方）必须被点名。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check_wired.mjs").write_text("// 已接线\n")
        (scripts / "zz_orphan_gate.py").write_text("print('orphan')\nraise SystemExit(1)\n")
        missing = unwired_gate_scripts(scripts, "node scripts/check_wired.mjs", {})
        assert missing == ["zz_orphan_gate.py"], f"孤儿门禁未被点名: {missing}"

    def test_excused_gate_is_not_flagged(self, tmp_path):
        """**反面守卫**：具名豁免的门禁脚本不得被判为孤儿（否则豁免表形同虚设）。"""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "helper.mjs").write_text("// 共用助手\n")
        missing = unwired_gate_scripts(scripts, "", {"helper.mjs": "共用助手（非门禁）"})
        assert missing == []

    def test_real_repo_has_no_orphan_gate(self):
        """真实仓库现状：孤儿的门禁数必须为 0（与上面同一判据，独立复核用）。"""
        assert unwired_gate_scripts(SCRIPTS_DIR, _gate_haystack(), EXEMPT_GATE_SCRIPTS) == []

    def test_exemptions_have_reasons(self):
        """豁免必须写明理由（空理由/纯符号视为未登记）。"""
        for name, reason in EXEMPT_GATE_SCRIPTS.items():
            assert reason and len(reason.strip()) >= 8, f"{name} 的豁免理由过短: {reason!r}"

    def test_exemption_targets_and_inventory_exist(self):
        """登记表/清册的键必须都对应真实文件（防拼写漂移让条目静默失效）。"""
        for name in list(EXEMPT_GATE_SCRIPTS) + list(NON_GATE_LOCAL_TOOLS):
            assert (SCRIPTS_DIR / name).is_file(), f"登记项 {name} 在 scripts/ 下不存在"

    def test_exempted_entries_are_gate_class_or_documented_tools(self):
        """豁免键必须确实是门禁类（否则该用 NON_GATE_LOCAL_TOOLS 清册）。"""
        gate = set(iter_gate_scripts())
        stray = [n for n in EXEMPT_GATE_SCRIPTS if n not in gate]
        assert not stray, f"以下豁免项不匹配任何门禁模式，请移入 NON_GATE_LOCAL_TOOLS: {stray}"

    def test_self_reference_loophole_is_closed(self):
        """本文件（豁免表所在地）不得计入引用来源。

        否则 `EXEMPT_GATE_SCRIPTS` 的键名会"自证被引用"，接线校验对登记项失效。
        """
        text = wrapper_source_text()
        assert "EXEMPT_GATE_SCRIPTS" not in text, "本文件被计入了引用来源（自证循环）"
        assert "zz_orphan_gate" not in text
        # 对照：豁免键名确实写在本文件里 —— 若不排除本文件，它们会全部"被引用"
        self_src = Path(__file__).read_text(encoding="utf-8")
        assert "_probe_python.mjs" in self_src

    def test_local_tools_inventory_has_reasons(self):
        """非门禁本地工具清册同样须写明理由。"""
        for name, reason in NON_GATE_LOCAL_TOOLS.items():
            assert reason and len(reason.strip()) >= 4, f"{name} 的清册理由过短: {reason!r}"


RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"

#: 版本链断言脚本必须出现的两个 job（审查 2026-10-09 P2-13：原先只在手工路径）
VERSION_CHAIN_JOBS = ("release-please", "build-artifacts")


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
        """两条发版路径都必须显式断言 tag == pyproject == manifest。"""
        steps = self._data()["jobs"][job]["steps"]
        script = "\n".join(s.get("run") or "" for s in steps)
        assert "校验 tag 与版本链一致" in "\n".join(s.get("name") or "" for s in steps), (
            f"{job} 缺版本链断言步骤（自动路径原先只靠 extra-files 结构性保证）"
        )
        for token in ("pyproject.toml", ".release-please-manifest.json", "TAG_NAME"):
            assert token in script, f"{job} 的版本链断言缺 {token}"

    def test_auto_path_uses_release_output_tag(self):
        """自动路径必须以 release-please 的 tag_name 输出为断言对象（而非 ref_name）。"""
        steps = self._data()["jobs"]["release-please"]["steps"]
        step = next(s for s in steps if (s.get("name") or "").startswith("校验 tag 与版本链一致"))
        assert step["env"]["TAG_NAME"] == "${{ steps.release.outputs.tag_name }}"
        assert step.get("if") == "steps.release.outputs.release_created == 'true'"
