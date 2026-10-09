"""`scripts/new_task.py` 脚手架测试（审查 2026-10-09 P3-14）。

背景：本脚本 370 行、本轮新增，却**零测试、零引用** —— 它生成的是"注册链骨架 +
断言骨架"，出错会**静默产出坏骨架**（例如把 `__all__` 的行内注释抹掉、把新条目
插到 `TASK_SPECS` 之外导致语法错误、桩缺 `from __future__` 位置约束）。

脚本**没有 `--dry-run`**，故本文件用 `tmp_path` 造迷你仓库跑**真实生成**，
再对产物逐项断言（不是断言"函数被调用过"）：

  · `__all__` **原地插入**（保注释、按函数段字母序）且仍可解析；
  · `TASK_SPECS` 新条目插在**闭合括号之前**（元组结构不破）；
  · 模板 / 测试骨架 / api-reference 条目生成；
  · 幂等：同键第二次运行必须拒绝（返回 1）且不重复写入；
  · 产物必须是**可解析**的 Python（坏骨架会在 CI 里以难查的语法错误爆掉）。

外加真实仓库的 `--check` 守卫：42 个任务的登记完整度必须全绿。
"""

import argparse
import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "new_task.py"
_mod = importlib.util.spec_from_file_location("new_task", SPEC)
new_task = importlib.util.module_from_spec(_mod)
assert _mod and _mod.loader
_mod.loader.exec_module(new_task)


ENGINE_INIT = '''"""engine 包 —— 迷你夹具。"""

__all__ = [
    "ALPHA",  # 公开统计常量（注释必须被保留）
    "aaa_func",
    "zzz_func",
]
'''

ENGINE_MOD = '''"""迷你引擎模块。"""

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def aaa_func(req: AnalysisRequest) -> AnalysisResult:
    return AnalysisResult(task="aaa", status="error", messages=["未实现"])
'''

TASK_SPEC = '''"""迷你 task_spec。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    key: str
    func_path: str
    group: str
    label: str
    y_only: bool = False
    x_optional: bool = False
    no_data: bool = False
    no_target: bool = False


TASK_SPECS: tuple[TaskSpec, ...] = (
    TaskSpec(
        key="aaa",
        func_path="smartsuite.engine.demo:aaa_func",
        group="要因筛选",
        label="甲",
    ),
)
'''


def _build_mini_repo(tmp_path: Path, monkeypatch) -> Path:
    """造迷你仓库并把 new_task.ROOT 指向它（生成器全部路径都基于 ROOT）。"""
    root = tmp_path / "repo"
    (root / "src" / "smartsuite" / "engine").mkdir(parents=True)
    (root / "src" / "smartsuite" / "services").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "tests" / "engine").mkdir(parents=True)
    (root / "docs" / "specification").mkdir(parents=True)
    (root / "src" / "smartsuite" / "engine" / "__init__.py").write_text(
        ENGINE_INIT, encoding="utf-8"
    )
    (root / "src" / "smartsuite" / "engine" / "demo.py").write_text(ENGINE_MOD, encoding="utf-8")
    (root / "src" / "smartsuite" / "services" / "task_spec.py").write_text(
        TASK_SPEC, encoding="utf-8"
    )
    (root / "templates" / "example_aaa.yaml").write_text("task: aaa\n", encoding="utf-8")
    (root / "docs" / "specification" / "api-reference.md").write_text(
        "# API\n\n### aaa\n- **Task Key**: `aaa`\n", encoding="utf-8"
    )
    monkeypatch.setattr(new_task, "ROOT", root)
    return root


def _args(**over) -> argparse.Namespace:
    base = {
        "key": "mmm_new",
        "label": "我的新方法",
        "group": "高级分析",
        "module": "smartsuite.engine.demo",
        "func": "mmm_new",
        "requires": "yx",
        "check": False,
    }
    base.update(over)
    return argparse.Namespace(**base)


def test_generate_returns_0_and_produces_all_artifacts(tmp_path, monkeypatch):
    """正常生成：退出码 0 + 5 类产物齐全（引擎桩/__all__/注册/模板/测试/api-reference）。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args()) == 0

    engine = (root / "src" / "smartsuite" / "engine" / "demo.py").read_text(encoding="utf-8")
    assert "def mmm_new(req: AnalysisRequest) -> AnalysisResult:" in engine
    assert 'status="error"' in engine, "桩必须返回 error（否则测试骨架不会先红）"

    init = (root / "src" / "smartsuite" / "engine" / "__init__.py").read_text(encoding="utf-8")
    assert '"mmm_new",' in init

    spec = (root / "src" / "smartsuite" / "services" / "task_spec.py").read_text(encoding="utf-8")
    assert 'key="mmm_new",' in spec
    assert 'func_path="smartsuite.engine.demo:mmm_new",' in spec

    assert (
        (root / "templates" / "example_mmm_new.yaml")
        .read_text(encoding="utf-8")
        .startswith("# 我的新方法")
    )
    assert (root / "tests" / "engine" / "test_mmm_new.py").is_file()
    assert "### mmm_new" in (root / "docs" / "specification" / "api-reference.md").read_text(
        encoding="utf-8"
    )


def test_generated_python_is_parseable(tmp_path, monkeypatch):
    """产物必须可解析 —— 坏骨架会在 CI 里以难查的语法错误爆掉（P3-14 的立项理由）。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args()) == 0
    for rel in (
        "src/smartsuite/engine/demo.py",
        "src/smartsuite/engine/__init__.py",
        "src/smartsuite/services/task_spec.py",
        "tests/engine/test_mmm_new.py",
    ):
        src = (root / rel).read_text(encoding="utf-8")
        ast.parse(src)  # 抛 SyntaxError 即失败


def test_all_insert_is_in_place_and_keeps_comments(tmp_path, monkeypatch):
    """`__all__` **原地插入**：行内注释保留 + 函数段按字母序 + 常量段不动。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args()) == 0
    init = (root / "src" / "smartsuite" / "engine" / "__init__.py").read_text(encoding="utf-8")

    assert "# 公开统计常量（注释必须被保留）" in init, "原地插入被破坏：注释被抹掉"
    tree = ast.parse(init)
    all_block = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and n.targets[0].id == "__all__"  # type: ignore[attr-defined]
    )
    names = [e.value for e in all_block.value.elts]
    assert names[0] == "ALPHA", "常量段不得被重排"
    assert names[1:] == ["aaa_func", "mmm_new", "zzz_func"], f"函数段应按字母序: {names}"


def test_task_spec_entry_inserted_before_closing_paren(tmp_path, monkeypatch):
    """注册条目插在 `TASK_SPECS` 的**闭合括号之前**（元组结构不被破坏）。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args()) == 0
    spec = (root / "src" / "smartsuite" / "services" / "task_spec.py").read_text(encoding="utf-8")
    tree = ast.parse(spec)
    ann = next(
        n
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and n.target.id == "TASK_SPECS"  # type: ignore[attr-defined]
    )
    keys = [kw.value.value for elt in ann.value.elts for kw in elt.keywords if kw.arg == "key"]
    assert keys == ["aaa", "mmm_new"], f"新条目必须在元组内且不破坏既有条目: {keys}"


@pytest.mark.parametrize(
    "requires,flags",
    [
        ("y", ["y_only=True,", "no_target=True,"]),
        ("x-optional", ["x_optional=True,"]),
        ("yx", []),
        ("none", ["no_data=True,", "no_target=True,"]),
    ],
)
def test_requires_flags_are_written(tmp_path, monkeypatch, requires, flags):
    """`--requires` 必须落成 TaskSpec 的列需求声明（漏写 → Web 端静默不可用）。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args(requires=requires)) == 0
    spec = (root / "src" / "smartsuite" / "services" / "task_spec.py").read_text(encoding="utf-8")
    for flag in flags:
        assert flag in spec, f"requires={requires} 应写入 {flag}"
    if requires == "yx":
        assert "y_only=True," not in spec and "x_optional=True," not in spec


def test_second_run_is_rejected_and_idempotent(tmp_path, monkeypatch):
    """幂等：同键第二次运行返回 1（函数已存在），且不产生重复条目。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args()) == 0
    before = {
        rel: (root / rel).read_text(encoding="utf-8")
        for rel in (
            "src/smartsuite/engine/demo.py",
            "src/smartsuite/engine/__init__.py",
            "src/smartsuite/services/task_spec.py",
        )
    }
    assert new_task.generate(_args()) == 1
    for rel, text in before.items():
        assert (root / rel).read_text(encoding="utf-8") == text, f"{rel} 被第二次运行改写"


def test_missing_module_is_rejected(tmp_path, monkeypatch):
    """模块不存在 → 返回 1（不写坏任何文件）。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    assert new_task.generate(_args(module="smartsuite.engine.nope")) == 1
    init = (root / "src" / "smartsuite" / "engine" / "__init__.py").read_text(encoding="utf-8")
    assert "mmm_new" not in init


def test_repeat_all_insert_does_not_duplicate(tmp_path, monkeypatch):
    """`_insert_all_entry` 对已存在的名字返回 True 且**不重复插入**。"""
    root = _build_mini_repo(tmp_path, monkeypatch)
    init_path = root / "src" / "smartsuite" / "engine" / "__init__.py"
    assert new_task._insert_all_entry(init_path, "mmm_new") is True
    assert new_task._insert_all_entry(init_path, "mmm_new") is True
    text = init_path.read_text(encoding="utf-8")
    assert text.count('"mmm_new"') == 1, f"重复插入: {text}"


def test_insert_all_entry_fails_without_all_block(tmp_path):
    """没有 `__all__` 块 → 返回 False（调用方据此报错而非静默跳过）。"""
    p = tmp_path / "no_all.py"
    p.write_text("x = 1\n", encoding="utf-8")
    assert new_task._insert_all_entry(p, "f") is False


def test_insert_task_spec_fails_when_target_missing(tmp_path):
    """`TASK_SPECS` 缺失/结构不符 → 返回 False（不误改文件）。"""
    p = tmp_path / "no_specs.py"
    original = "OTHER = [1, 2]\n"
    p.write_text(original, encoding="utf-8")
    assert new_task._insert_task_spec(p, "    TaskSpec(),\n") is False
    assert p.read_text(encoding="utf-8") == original


def test_main_check_passes_on_real_repo(capsys):
    """真实仓库守卫：42 个任务的登记完整度（引擎函数/__all__/模板/api-reference）全绿。"""
    assert new_task.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "OK" in out and "登记完整度" in out


def test_main_requires_mandatory_args(capsys):
    """缺必填参数 → argparse 报错（不静默生成半成品）。"""
    with pytest.raises(SystemExit) as exc:
        new_task.main(["--key", "only_key"])
    assert exc.value.code == 2
    assert "--label" in capsys.readouterr().err
