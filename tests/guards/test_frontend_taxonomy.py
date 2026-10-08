"""前端任务分类学守卫：`app.js` 的硬编码任务集合必须与后端一致。

对应第三轮复核 P3-4（logs/reports/verify-round3/R3-复核清单.md）：

`app.js` 的 `runAnalysis()` 里有三组硬编码任务集合：

    _noTargetNeeded   —— 无需 Y 列即可运行
    _yOnlyTasks       —— 只需 Y 列（无需 X）
    _xOptionalTasks   —— X 列可选

其中 `_noTargetNeeded` 与后端 `NO_TARGET_TASKS`（`services/orchestrator.py`）
**逐元素相等**（2026-09-24 实测比对），但**没有任何守卫** ——
`verify_frontend_params.py` 只管 `TASK_PARAMS` 的键集与默认值。
后端新增一个 no_target 任务时，前端会静默变成"必须先选 Y"（功能不可达）。

`_yOnlyTasks` / `_xOptionalTasks` 后端**没有对应定义**，属纯前端启发式。
本守卫的分工：
  - 对**有后端定义**的 `_noTargetNeeded`：断言集合相等（硬契约）；
  - 对**无后端定义**的两组：断言每个键都是已注册任务（防拼写错误/任务改名残留），
    并钉住"它们必须是 `_noTargetNeeded` 的子集或与参数面板一致"的可验证性质。
"""

import re
from pathlib import Path

import pytest

from smartsuite.services.orchestrator import (
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    TASK_REGISTRY,
)

_JS = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web" / "static" / "app.js"


def _extract_set(js: str, var_name: str) -> set[str]:
    """从 `const <var_name> = new Set([...]);` 提取字符串元素集合。"""
    m = re.search(
        rf"const {re.escape(var_name)}\s*=\s*new Set\(\[(.*?)\]\)\s*;",
        js,
        re.DOTALL,
    )
    assert m, f"app.js 中未找到 {var_name} 的定义（变量被改名或删除？）"
    return set(re.findall(r"'([^']+)'", m.group(1)))


@pytest.fixture(scope="module")
def js() -> str:
    return _JS.read_text(encoding="utf-8")


class TestNoTargetNeededMatchesBackend:
    """有后端定义的集合必须严格一致。"""

    def test_set_equals_backend_no_target_tasks(self, js):
        frontend = _extract_set(js, "_noTargetNeeded")
        backend = set(NO_TARGET_TASKS)
        assert frontend == backend, (
            "app.js 的 _noTargetNeeded 与后端 NO_TARGET_TASKS 不一致：\n"
            f"  仅前端有（后端不支持无 Y）: {sorted(frontend - backend)}\n"
            f"  仅后端有（前端会强制选 Y，功能不可达）: {sorted(backend - frontend)}"
        )

    def test_set_is_non_empty(self, js):
        assert _extract_set(js, "_noTargetNeeded"), "集合不应为空"


class TestHeuristicSetsReferenceRealTasks:
    """无后端定义的两组启发式集合：至少保证键有效，防拼写/改名残留。"""

    @pytest.mark.parametrize("var", ["_yOnlyTasks", "_xOptionalTasks", "_noTargetNeeded"])
    def test_all_keys_are_registered_tasks(self, js, var):
        keys = _extract_set(js, var)
        unknown = sorted(keys - set(TASK_REGISTRY))
        assert not unknown, f"{var} 含未注册任务键（拼写错误或任务已改名）: {unknown}"

    @pytest.mark.parametrize("var", ["_yOnlyTasks", "_xOptionalTasks"])
    def test_heuristic_sets_are_disjoint(self, js, var):
        """「只需 Y」与「X 可选」语义互斥，同一任务不应同时在两组。"""
        overlap = _extract_set(js, "_yOnlyTasks") & _extract_set(js, "_xOptionalTasks")
        assert not overlap, (
            f"_yOnlyTasks 与 _xOptionalTasks 不应有交集（语义互斥）: {sorted(overlap)}"
        )

    def test_no_data_tasks_are_not_required_to_have_columns(self, js):
        """完全不需数据的任务（如 doe_design/power_analysis）必须在前端免列检查里。

        否则用户点「DOE 实验设计」会被拦住要求先选 Y —— 纯参数计算却要求数据。
        """
        no_target = _extract_set(js, "_noTargetNeeded")
        no_data = set(NO_DATA_TASKS)
        missing = sorted(no_data - no_target)
        assert not missing, f"以下任务无需任何数据，但未列入前端的免 Y 集合，会被误拦: {missing}"


class TestGuardWouldCatchDrift:
    """自测：提取函数对篡改敏感（防止守卫因正则失效而永远通过）。"""

    def test_extractor_detects_missing_variable(self):
        with pytest.raises(AssertionError, match="未找到"):
            _extract_set("const other = 1;", "_noTargetNeeded")

    def test_extractor_handles_multiline_and_spacing(self):
        js = "const _demo = new Set([\n  'a',\n  'b',\n]);"
        assert _extract_set(js, "_demo") == {"a", "b"}

    def test_simulated_drift_would_fail_equality(self, js):
        """模拟后端新增一个 no_target 任务 —— 当前集合应立即不等。"""
        frontend = _extract_set(js, "_noTargetNeeded")
        simulated_backend = set(frontend) | {"_hypothetical_new_task"}
        assert frontend != simulated_backend
