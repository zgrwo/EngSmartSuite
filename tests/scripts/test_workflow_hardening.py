"""CI 门禁**不得被静默 defuse**（审查 2026-10-09 G-4）。

## 背景：门禁能被一行 YAML 关掉，而全部治理测试全绿

注入实测（`logs/reports/2026-10-09-review-r2g-g.md` I8）：给 3 个门禁步骤各插一行
`continue-on-error: true`（`quality.yml` 的 `falsy-audit`、`release.yml` 的两处
"校验 tag 与版本链一致"）后，`pytest tests/scripts/` **307 passed / EXIT 0**。

根因：整套接线守卫只回答"脚本有没有到达路径"（`test_ci_layer_coverage.py`），
**不回答"到达路径会不会把失败吞掉"** —— CI 配置本身被当作可信输入，
没有任何测试把它当**被测对象**做负向校验。发版链上"tag == pyproject == manifest"
是发行断言，被 `continue-on-error` 吞掉后仍会构建并上传错版产物，而 CI 全绿。

## 本文件的判据

对**全部** `.github/workflows/*.yml` 解析出的每个 step：

  ① **门禁类步骤**（跑 `scripts/verify_*` / `*_gate.py` / `truth_coverage` /
     `falsy_audit` / `test_quality_guard` / `validate-commit-msg` / `check_*.mjs`，
     或 pytest / ruff / mypy 这类判定命令）**一律不得**带
     `continue-on-error: true`（含 `"true"` 字符串形态）；
  ② 上述门禁步骤的 `run:` 文本里不得出现 `|| true` / `|| :` / 尾随 `; true`
     这类把退出码丢掉、让步骤自己变绿的写法；
  ③ 门禁步骤的 `run:` 里凡出现管道 `|`，必须已 `set -o pipefail`
     （否则管道左端的失败被右端掩盖 —— `| tail -5` 的经典形态）。

**为什么不给出具名白名单**：本轮把仓库现状全部对齐（`security.yml` 的
`|| { …; exit 1; }` 是 fail-closed，本来就不违规），故零例外可直接硬断言；
将来若真需要例外，必须在这里显式登记理由并**同时**在 `FROZEN_ALLOWED` 说明，
而不是靠"没人发现"。

负向用例覆盖三种注入形态（`continue-on-error` / `|| true` / 管道缺 pipefail），
并额外用**真实仓库文件**做一次端到端注入（改写临时目录里的副本，
仓库工作区只读不写）。
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

#: 门禁脚本/命令的形态（判定命令一律适用）
GATE_SCRIPT_RE = re.compile(
    r"(?:scripts[/\\])?(?:"
    r"verify_[A-Za-z0-9_]+\.py"
    r"|[A-Za-z0-9_]+_gate\.py"
    r"|truth_coverage\.py"
    r"|falsy_audit\.py"
    r"|test_quality_guard\.py"
    r"|validate-commit-msg\.sh"
    r"|check_[A-Za-z0-9_]+\.mjs"
    r")"
)
#: 判定类命令（非 scripts/ 下的门禁脚本，但同样是"会红/会绿"的门禁）
GATE_COMMAND_RE = re.compile(
    r"(?:\bpytest\b|\bruff\s+(?:check|format)\b|\bmypy\b|\bdependency-review-action\b)"
)

#: 把退出码丢掉、让步骤自己变绿的写法
SUPPRESS_RE = re.compile(r"\|\|\s*(?:true|:)(?:\s|$)|\|\|\s*true\s*;|;\s*true\s*$", re.MULTILINE)
#: 管道（用于要求 pipefail；`| tail` / `2>&1 |` 都算）
PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")
PIPEFAIL_RE = re.compile(r"set\s+-o\s+pipefail|set\s+-eo\s+pipefail|bash\s+-o\s+pipefail")
#: **清场命令的容错**（`kill $PID 2>/dev/null || true`）：重定向已丢弃输出、
#: 且进程已在退出 —— 它不承载任何判定，故不计入 `|| true` 违约。
#: （真门禁的 `cmd || true` 没有 `/dev/null` 重定向，仍会被抓。）
CLEANUP_SUPPRESS_RE = re.compile(r"2?>\s*/dev/null\s*\|\|\s*(?:true|:)\s*$")

#: 唯一允许的具名例外（键 = `<workflow>:<job>:<step 序号>` → 理由）。
#: 本轮为空：仓库现状已全部对齐，新增例外必须写明理由。
FROZEN_ALLOWED: dict[str, str] = {}


def _iter_steps(data: dict):
    """(job 名, step 序号, step dict) —— 覆盖全部 job。"""
    for job_name, job in (data.get("jobs") or {}).items():
        for idx, step in enumerate(job.get("steps") or [], 1):
            yield job_name, idx, step


def is_gate_step(step: dict) -> bool:
    """该 step 是否属"门禁类"（跑判定脚本/命令）。"""
    run = step.get("run")
    if not run:
        return False
    text = str(run)
    return bool(GATE_SCRIPT_RE.search(text) or GATE_COMMAND_RE.search(text))


def _as_bool(value: object) -> bool:
    """`continue-on-error` 的 YAML 真值形态：True / "true" / "${{ … }}"。

    表达式形态（`${{ … }}`）**不算通过** —— 它同样能让失败被吞掉，且无法静态判定，
    出现即要求人工登记（见 FROZEN_ALLOWED）。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "on"} or "${{" in value
    return False


def check_gate_step(step: dict, where: str) -> list[str]:
    """单个门禁 step 的违规清单（空 = 合规）。"""
    violations: list[str] = []
    if _as_bool(step.get("continue-on-error")):
        violations.append(
            f"{where}: 门禁步骤带 continue-on-error={step['continue-on-error']!r} "
            "—— 失败会被静默吞掉，CI 仍绿（审查 G-4 注入形态）"
        )
    run = str(step.get("run") or "")
    # 清场行的 `|| true`（带 `/dev/null` 重定向）不承载判定，先剔除再查
    judged = "\n".join(line for line in run.splitlines() if not CLEANUP_SUPPRESS_RE.search(line))
    if SUPPRESS_RE.search(judged):
        violations.append(
            f"{where}: 门禁命令里出现 `|| true` / `|| :` —— 退出码被丢弃，"
            "步骤永远变绿（审查 G-4 注入形态）"
        )
    if PIPE_RE.search(judged) and not PIPEFAIL_RE.search(run):
        violations.append(
            f"{where}: 门禁命令用了管道但未 `set -o pipefail` —— "
            "管道左端的失败会被 `| tail`/`| head` 之类掩盖（审查 G-4/G-13 形态）"
        )
    return violations


def scan_workflows(workflows_dir: Path = WORKFLOWS_DIR) -> list[str]:
    """全部 workflow 的门禁步骤违规清单（空 = 全部合规）。"""
    out: list[str] = []
    for wf in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for job_name, idx, step in _iter_steps(data):
            if not is_gate_step(step):
                continue
            name = step.get("name") or f"step#{idx}"
            key = f"{wf.name}:{job_name}:{idx}"
            if key in FROZEN_ALLOWED:
                continue
            out += check_gate_step(step, f"{wf.name} → job `{job_name}` → step 「{name}」")
    return out


def count_gate_steps(workflows_dir: Path = WORKFLOWS_DIR) -> int:
    """门禁步骤总数（用于证明本守卫**看得见**这些步骤，而不是空判据假绿）。"""
    total = 0
    for wf in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        total += sum(1 for _, _, step in _iter_steps(data) if is_gate_step(step))
    return total


def _source_line(step: dict, path: Path) -> int | None:
    """该 step 在 YAML 源文件中的起始行号（用于把违规点名到行）。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    name = step.get("name")
    if not name:
        return None
    for i, line in enumerate(lines, 1):
        if str(name) in line and line.lstrip().startswith("- "):
            return i
    for i, line in enumerate(lines, 1):
        if str(name) in line:
            return i
    return None


class TestWorkflowGatesCannotBeDefused:
    """仓库现状：任何门禁步骤都不得被 `continue-on-error` / `|| true` / 缺 pipefail 削弱。"""

    def test_real_workflows_have_no_defused_gate(self):
        violations = scan_workflows()
        assert not violations, "\n".join(
            ["以下门禁步骤可被静默 defuse（审查 G-4）：", *[f"  - {v}" for v in violations]]
        )

    def test_scan_actually_sees_gate_steps(self):
        """**空判据防护**：门禁分类器必须真的看见若干门禁步骤。

        G-6(b) 的教训：判据看不见文件时，"零违规"没有任何意义。
        """
        assert count_gate_steps() >= 12, (
            f"只认出 {count_gate_steps()} 个门禁步骤 —— 分类正则可能已失效"
            "（真实仓库远不止这些：quick/full/quality/security 各 job 都跑门禁）"
        )

    def test_release_version_chain_step_is_gate_class(self):
        """发版版本链断言必须被认作门禁步骤（G-4 的原形就打在它身上）。"""
        data = yaml.safe_load((WORKFLOWS_DIR / "release.yml").read_text(encoding="utf-8"))
        found = False
        for job_name in ("release-please", "build-artifacts"):
            for _, _, step in _iter_steps({"jobs": {job_name: data["jobs"][job_name]}}):
                if (step.get("name") or "").startswith("校验 tag 与版本链一致"):
                    assert is_gate_step(step), f"{job_name} 的版本链断言未被认作门禁步骤"
                    found = True
        assert found, "release.yml 缺版本链断言步骤（前置条件不成立）"

    def test_no_frozen_exceptions_without_reason(self):
        """具名例外必须写明理由（本轮为空；新增即须可审）。"""
        for key, reason in FROZEN_ALLOWED.items():
            assert reason and len(reason.strip()) >= 10, f"{key} 的例外理由过短: {reason!r}"


class TestDefusedGateIsDetected:
    """**负向注入**：把本报告 I8 的三种形态逐一转正为回归用例。"""

    @staticmethod
    def _wf(tmp_path: Path, run: str, extra: str = "", tmp_name: str = "wf.yml") -> Path:
        wf = tmp_path / tmp_name
        body = textwrap.indent(run.rstrip("\n"), " " * 10)
        wf.write_text(
            "name: X\n"
            "on: [push]\n"
            "jobs:\n"
            "  g:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: 门禁步骤（注入目标）\n"
            f"{extra}"
            "        run: |\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return wf

    def test_continue_on_error_true_is_detected(self, tmp_path):
        """形态①：`continue-on-error: true` —— 审查 I8 的真实注入形态。"""
        wf = self._wf(
            tmp_path,
            "uv run python scripts/verify_docs.py --strict",
            "        continue-on-error: true\n",
        )
        v = scan_workflows(tmp_path)
        assert len(v) == 1, f"注入未被检出: {v}"
        assert "wf.yml" in v[0] and "continue-on-error" in v[0], v[0]
        assert "门禁步骤（注入目标）" in v[0], "违规未点名到具体步骤"

    def test_continue_on_error_string_true_is_detected(self, tmp_path):
        """形态①变体：`continue-on-error: "true"`（YAML 字符串）同样必须检出。"""
        self._wf(
            tmp_path,
            "uv run python scripts/falsy_audit.py",
            '        continue-on-error: "true"\n',
        )
        v = scan_workflows(tmp_path)
        assert len(v) == 1 and "continue-on-error" in v[0], v

    def test_continue_on_error_expression_is_detected(self, tmp_path):
        """形态①变体：`${{ … }}` 表达式形态也不得放行（无法静态判定 ⇒ 一律要求登记）。"""
        self._wf(
            tmp_path,
            "uv run python scripts/verify_consistency.py",
            "        continue-on-error: ${{ github.event_name == 'push' }}\n",
        )
        assert scan_workflows(tmp_path), "表达式形态的 continue-on-error 未被检出"

    def test_pipe_or_true_is_detected(self, tmp_path):
        """形态②：命令尾随 `|| true`（失败被吞、步骤永远绿）。"""
        self._wf(tmp_path, "uv run python scripts/truth_coverage.py || true")
        v = scan_workflows(tmp_path)
        assert len(v) == 1 and "|| true" in v[0], v

    def test_pipe_without_pipefail_is_detected(self, tmp_path):
        """形态③：门禁命令用管道却未 `set -o pipefail`（左端失败被 tail 掩盖）。"""
        self._wf(tmp_path, "uv run python scripts/verify_cross_consistency.py 2>&1 | tail -5")
        v = scan_workflows(tmp_path)
        assert len(v) == 1 and "pipefail" in v[0], v

    def test_pipe_with_pipefail_is_allowed(self, tmp_path):
        """**反面守卫**：已 `set -o pipefail` 的管道不得被误报（防过严假红）。"""
        self._wf(
            tmp_path,
            "set -o pipefail\nuv run python scripts/verify_cross_consistency.py 2>&1 | tail -5",
        )
        assert scan_workflows(tmp_path) == []

    def test_release_chain_injection_on_real_file_copy(self, tmp_path):
        """**端到端注入**：在 `release.yml` 的**副本**上注入 → 必须点名到文件/步骤。

        （副本写入 `tmp_path`，仓库工作区全程只读。）
        """
        src = (WORKFLOWS_DIR / "release.yml").read_text(encoding="utf-8")
        injected = src.replace(
            "      - name: 校验 tag 与版本链一致",
            "      - name: 校验 tag 与版本链一致\n        continue-on-error: true  # INJ-G4",
            1,
        )
        assert injected != src, "注入未命中（release.yml 的版本链步骤名已变化）"
        (tmp_path / "release.yml").write_text(injected, encoding="utf-8")
        v = scan_workflows(tmp_path)
        assert v, "在 release.yml 副本上的真实注入未被检出"
        assert any("release.yml" in x and "版本链" in x for x in v), v
        assert any("continue-on-error" in x for x in v), v

    def test_non_gate_step_may_have_continue_on_error(self, tmp_path):
        """**边界**：非门禁步骤（如"上传构件"）的 `continue-on-error` 不在本守卫范围。

        否则守卫会因无关的容错配置误红 —— 本守卫只对"判定类"步骤负责。
        """
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "name: X\n"
            "on: [push]\n"
            "jobs:\n"
            "  g:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: 上传基准构件\n"
            "        continue-on-error: true\n"
            "        uses: actions/upload-artifact@v7\n",
            encoding="utf-8",
        )
        assert scan_workflows(tmp_path) == []


class TestWorkflowSourceIsPointable:
    """违规必须能点名到**行**（可诊断性：只说"某个 workflow 有问题"等于没查）。"""

    def test_injected_violation_maps_to_line(self, tmp_path):
        wf = tmp_path / "wf.yml"
        wf.write_text(
            "name: X\n"
            "on: [push]\n"
            "jobs:\n"
            "  g:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: 门禁步骤\n"
            "        continue-on-error: true\n"
            "        run: uv run python scripts/test_quality_guard.py\n",
            encoding="utf-8",
        )
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        step = data["jobs"]["g"]["steps"][0]
        assert _source_line(step, wf) == 7

    @pytest.mark.parametrize("wf_name", ["ci.yml", "quality.yml", "release.yml", "security.yml"])
    def test_real_gate_steps_are_locatable(self, wf_name):
        """真实仓库里的门禁步骤必须都能定位到源文件行号（治理可读性）。"""
        path = WORKFLOWS_DIR / wf_name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        unlocatable = [
            (job, idx, step.get("name"))
            for job, idx, step in _iter_steps(data)
            if is_gate_step(step) and _source_line(step, path) is None
        ]
        assert not unlocatable, f"{wf_name} 有无法定位的门禁步骤（缺 name？）: {unlocatable}"
