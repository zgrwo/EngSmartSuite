"""`templates_gate.py` 判据自测（审查 2026-09-21 G-7）。

背景：`templates/*.yaml` 的 `task` 键此前**无任何门禁**——任务改名/删除后模板静默
失效（用户跑到「未知的分析任务」才发现）。判据提炼为可导入纯函数后，可对
「未注册 task / 缺 task 键 / YAML 损坏」逐一做负向注入，并用仓库态守卫钉住 45 个模板。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from templates_gate import iter_template_tasks, validate_template_tasks  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KNOWN = {"correlation", "anova"}


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_registered_task_passes(tmp_path):
    _write(tmp_path, "ok.yaml", "task: correlation\ntarget_col: y\n")
    assert validate_template_tasks(tmp_path, KNOWN) == []


def test_unregistered_task_flagged_with_name(tmp_path):
    """任务改名/删除后必须点名，而不是静默失效。"""
    _write(tmp_path, "renamed.yaml", "task: correlation_v2\ntarget_col: y\n")
    problems = validate_template_tasks(tmp_path, KNOWN)
    assert len(problems) == 1
    assert "renamed.yaml" in problems[0] and "correlation_v2" in problems[0]


def test_missing_task_key_flagged(tmp_path):
    """缺 task 键的模板同样是坏的（不能静默跳过）。"""
    _write(tmp_path, "no_task.yaml", "target_col: y\n")
    problems = validate_template_tasks(tmp_path, KNOWN)
    assert len(problems) == 1 and "no_task.yaml" in problems[0]


def test_broken_yaml_flagged(tmp_path):
    """YAML 损坏必须有门禁可见（而不是抛异常中断整个门禁）。"""
    _write(tmp_path, "broken.yaml", "task: [未闭合\n")
    problems = validate_template_tasks(tmp_path, KNOWN)
    assert len(problems) == 1
    assert "broken.yaml" in problems[0] and "解析失败" in problems[0]


def test_non_mapping_yaml_flagged(tmp_path):
    """顶层是列表/标量（非映射）也视为坏模板。"""
    _write(tmp_path, "list.yaml", "- task: correlation\n")
    problems = validate_template_tasks(tmp_path, KNOWN)
    assert len(problems) == 1 and "list.yaml" in problems[0]


def test_iter_returns_relative_names_sorted(tmp_path):
    _write(tmp_path, "b.yaml", "task: anova\n")
    _write(tmp_path, "a.yaml", "task: correlation\n")
    assert list(iter_template_tasks(tmp_path)) == ["a.yaml", "b.yaml"]


def test_real_repo_templates_all_registered():
    """仓库态守卫：45 个模板的 task 键必须全部在 TASK_REGISTRY 中。

    若本用例失败→说明新增/改名任务时漏改了 templates/，或模板名拼错。
    """
    from smartsuite.services.orchestrator import TASK_REGISTRY

    problems = validate_template_tasks(ROOT / "templates", set(TASK_REGISTRY))
    assert not problems, f"templates 存在未注册/损坏的 task 键: {problems}"
