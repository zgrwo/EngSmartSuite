"""workflow 的**权限收敛 / 触发面 / 并发策略**静态门禁（审查 2026-10-09 G-11/G-14/G-16）。

本文件与 `test_workflow_hardening.py` 分工：
  · `test_workflow_hardening.py` —— 「门禁步骤会不会把失败吞掉」（continue-on-error / `|| true`）；
  · 本文件 —— 「workflow 的**授权与触发**是否最小/正确」（权限下移、事件区分、扫描器锁版本）。

## 背景

- **G-11**：`docs.yml` 的 `pages: write` + `id-token: write` 写在 workflow 顶层 ⇒
  PR 的 `build` job（跑 PR 分支里的 `mkdocs.yml` 与插件代码）也持有可部署 Pages /
  可签 OIDC 的令牌。同仓分支 PR 的 `GITHUB_TOKEN` **不被强制降级**（只有 fork PR 降）。
- **G-14**：`ci.yml` 的 `cancel-in-progress: true` 作用于 main push ⇒ 连续两次 push
  时第二次取消第一次正在跑的 `full` 全矩阵，而**不会重跑** ⇒ 发版可能"拿不到
  main 的完整矩阵结论"。`release.yml` 早已示范 `cancel-in-progress: false`。
- **G-16**：`security.yml` 的 `pip-audit` 原先不带版本 ⇒ 扫描器随发布漂移；
  另有一条 `pip install -e ".[dev]"` 在改审计源为 `uv.lock` 后已成冗余。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _triggers(data: dict) -> dict:
    """取出 `on:` 段。

    ⚠️ PyYAML 按 YAML 1.1 把裸 `on` 解析为布尔 `True`，故键可能是 `True` 而不是 `"on"`
    （本仓历史坑位，写测试时容易只判一处而漏掉另一处）。
    """
    return data.get("on") or data.get(True) or {}


def _strip_shell_comments(text: str) -> str:
    """去掉 shell 整行注释（`# …`）—— 注释里的示例命令不算"实际执行"。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class TestDocsWorkflowPermissions:
    """`docs.yml` 的部署能力只能授予**部署 job**（G-11）。"""

    def test_workflow_level_permissions_are_read_only(self):
        perms = _load("docs.yml").get("permissions")
        assert perms == {"contents": "read"}, (
            f"docs.yml 顶层权限应只有 contents: read，实际 {perms} —— "
            "pages: write / id-token: write 属部署专用能力，写在顶层会让 PR 的 build job 也拿到"
        )

    def test_deploy_job_has_deploy_permissions(self):
        perms = _load("docs.yml")["jobs"]["deploy"].get("permissions")
        assert perms == {"pages": "write", "id-token": "write"}, (
            f"deploy job 应具名持有 pages: write + id-token: write，实际 {perms}"
        )

    def test_build_job_has_no_write_permission(self):
        perms = _load("docs.yml")["jobs"]["build"].get("permissions")
        assert not perms or all(v == "read" for v in perms.values()), (
            f"build job（PR 也跑）不得有写权限，实际 {perms}"
        )

    def test_deploy_still_limited_to_push_or_dispatch(self):
        job = _load("docs.yml")["jobs"]["deploy"]
        cond = str(job.get("if") or "")
        assert "push" in cond and "workflow_dispatch" in cond, (
            f"deploy 必须仍限 push/dispatch，实际 if={cond!r}"
        )


class TestCiConcurrencyByEvent:
    """`ci.yml` 的取消策略必须按事件区分（G-14）。"""

    def test_cancel_in_progress_is_not_a_bare_true(self):
        conc = _load("ci.yml").get("concurrency") or {}
        value = conc.get("cancel-in-progress")
        assert value is not True, (
            "ci.yml 的 cancel-in-progress 不得是无条件 true —— "
            "main push 上取消会丢弃正在跑的 full 全矩阵且不会重跑"
        )
        assert "${{" in str(value), f"应按事件表达式取值，实际 {value!r}"
        assert "pull_request" in str(value), f"表达式应只在 PR 上取消，实际 {value!r}"

    def test_release_workflow_never_cancels(self):
        """对照项：发版链的"不可中断"不得被顺手改掉（保持项）。"""
        conc = _load("release.yml").get("concurrency") or {}
        assert conc.get("cancel-in-progress") is False

    def test_main_push_trigger_exists(self):
        """main push 必须仍在 ci.yml 的触发面内（否则上面的讨论失去意义）。"""
        push = _triggers(_load("ci.yml")).get("push") or {}
        assert "main" in (push.get("branches") or []), "ci.yml 应在 main push 上触发"


class TestSecurityWorkflowScannerIsPinned:
    """`security.yml` 的扫描器必须锁版本，且不留冗余安装（G-16）。"""

    @staticmethod
    def _audit_run(*, strip_comments: bool = True) -> str:
        """pip-audit 步骤的 `run:` 文本（默认去掉整行注释）。"""
        for _job, job in (_load("security.yml").get("jobs") or {}).items():
            for step in job.get("steps") or []:
                run = str(step.get("run") or "")
                if "pip_audit" in run or "pip-audit" in run:
                    return _strip_shell_comments(run) if strip_comments else run
        raise AssertionError("security.yml 找不到 pip-audit 步骤")

    def test_scanner_version_is_pinned(self):
        run = self._audit_run()
        assert re.search(r"pip-audit==\d+\.\d+", run), (
            "pip-audit 必须锁版本（`pip-audit==X.Y.Z`）—— 不固定版本时扫描器随发布漂移，"
            f"新建/修改判定会让本 job 无故变红。实际 run:\n{run}"
        )

    def test_no_redundant_project_install(self):
        run = self._audit_run()
        assert 'pip install -e ".[dev]"' not in run, (
            '审计源已改为 `uv export --frozen` 的锁定集，`pip install -e ".[dev]"` '
            "是旧路径的遗留（既不参与审计，又每次装一遍全部依赖）"
        )

    def test_audit_source_is_the_lockfile(self):
        run = self._audit_run()
        assert "uv export --frozen" in run and "-r locked-reqs.txt" in run, (
            "审计对象必须是 uv.lock 的锁定集（保持项：不得退回未锁定口径）"
        )
        assert "locked-reqs.txt" in run

    def test_lockfile_export_failure_is_fail_closed(self):
        """保持项：导出失败 / 锁定集为空 / 无锁文件三种情形都必须 exit 1。"""
        raw = self._audit_run(strip_comments=False)
        assert raw.count("exit 1") >= 3, (
            "pip-audit 步骤应保留三处 fail-closed 出口（导出失败 / 锁定集为空 / 无锁文件）"
        )


class TestReleaseVersionChainHasFourVectors:
    """`release.yml` 的版本链断言必须真的覆盖四向量（G-12）。"""

    @pytest.mark.parametrize("job", ["release-please", "build-artifacts"])
    def test_changelog_vector_present(self, job):
        steps = _load("release.yml")["jobs"][job]["steps"]
        script = "\n".join(s.get("run") or "" for s in steps)
        assert "CHANGELOG.md" in script, f"{job} 的版本链断言缺 CHANGELOG 向量"
        assert re.search(r"\^##\\s\*\\\[\(\\d\+\\\.\\d\+\\\.\\d\+\)\\\]", script), (
            f"{job} 的 CHANGELOG 判据必须与 verify_docs.py 的表达式同源（SSOT）"
        )

    @pytest.mark.parametrize("job", ["release-please", "build-artifacts"])
    def test_step_name_matches_four_vectors(self, job):
        names = "\n".join(s.get("name") or "" for s in _load("release.yml")["jobs"][job]["steps"])
        assert "manifest == CHANGELOG" in names, (
            f"{job} 的步骤名未写实四向量（避免再次出现『注释说四、断言只做三』）：{names!r}"
        )
