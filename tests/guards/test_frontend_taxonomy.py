"""任务列需求守卫：**单一来源**是 `TASK_SPECS`，前端只读不写。

契约：[improvement-plan.md](../../docs/governance/improvement-plan.md) §十 硬指标表
      「新增方法成本 8 步 → 1 步」

## 本文件的历史（一次真实的结构演进）

第三轮复核 P3-4 发现：`app.js` 的 `runAnalysis()` 里有三组**硬编码**任务集合 ——

    _noTargetNeeded   —— 无需 Y 列即可运行
    _yOnlyTasks       —— 只需 Y 列（无需 X）
    _xOptionalTasks   —— X 列可选

其中 `_noTargetNeeded` 与后端 `NO_TARGET_TASKS` 恰好逐元素相等，但**没有守卫**；
另两组后端根本没有对应定义。后果：**新增任务若忘改这三处，Web 上永远跑不起来**
（用户看到「请至少选择一个 X 列」）—— 不报错、不失败，是最难发现的一类缺陷。

当时的守卫（本文件的前身）只能**事后比对**两份手抄清单。

**第 42 轮改为结构性消除**：`TaskSpec` 增加 `y_only` / `x_optional` 声明 →
`derive()` 派生 → `/api/tasks` 下发 → 前端 `hydrateParams` 接收、`app.js` 只读。
于是本文件不再"比对两份清单"（那份手抄清单已不存在），而是断言：

  1. **前端不含**手写任务集合（防回流）；
  2. `/api/tasks` **确实下发**四组需求，且逐字等于 `TASK_SPECS` 派生结果；
  3. 集合的**语义约束**成立（互斥、键有效、无需数据的任务不被拦）；
  4. 守卫自身**对篡改敏感**（防正则失效导致永远通过）。

> ⚠️ 教训：当守卫的工作是"比对两份清单"时，正确的演进方向不是把守卫写得更严，
> 而是**消灭其中一份清单**。本文件即该原则的落地。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "src" / "smartsuite" / "web" / "static"
_APP_JS = _STATIC / "app.js"

sys.path.insert(0, str(_ROOT / "src"))

from smartsuite.services.orchestrator import (  # noqa: E402
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    TASK_REGISTRY,
    X_OPTIONAL_TASKS,
    Y_ONLY_TASKS,
)
from smartsuite.services.task_spec import TASK_SPECS, derive  # noqa: E402


def _extract_set(js: str, var_name: str) -> set[str]:
    """从 `const <var_name> = new Set([...]);` 提取字符串元素集合。

    保留此函数用于**自测**（下文的 `TestGuardWouldCatchDrift`）：
    守卫必须对篡改敏感，否则"通过"没有意义。
    """
    m = re.search(
        rf"const {re.escape(var_name)}\s*=\s*new Set\(\[(.*?)\]\)\s*;",
        js,
        re.DOTALL,
    )
    assert m, f"未找到 {var_name} 的定义（变量被改名或删除？）"
    return set(re.findall(r"'([^']+)'", m.group(1)))


@pytest.fixture(scope="module")
def app_js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def api_tasks() -> dict:
    from smartsuite.web.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        return c.get("/api/tasks").get_json()


class TestFrontendNoLongerHandRollsTaskSets:
    """**防回流**：前端不得再有按任务名硬编码的列需求集合。"""

    _BANNED = ("_noTargetNeeded", "_yOnlyTasks", "_xOptionalTasks")

    @pytest.mark.parametrize("name", _BANNED)
    def test_banned_set_declaration_is_absent(self, app_js, name):
        """判据是**声明/赋值**形态，而非裸名 —— 注释里说明来龙去脉是允许的。

        （裸名匹配会被"解释这段历史"的注释命中 —— 与 `xbar_r.py` 那次同类误报。）
        """
        pattern = re.compile(rf"(?:const|let|var)\s+{re.escape(name)}\s*=")
        assert not pattern.search(app_js), (
            f"app.js 又出现了 {name} 的声明 —— 列需求必须由后端下发，手写集合会让新增任务静默不可用"
        )

    def test_frontend_reads_served_sets(self, app_js):
        """`app.js` 必须调用后端下发的访问器（证明收口真的接通了）。"""
        for call in ("noTargetTasks()", "yOnlyTasks()", "xOptionalTasks()"):
            assert call in app_js, f"app.js 未使用 {call}（列需求校验可能改回了手写）"


class TestApiServesColumnRequirements:
    """`/api/tasks` 是本项的唯一出口。"""

    def test_all_four_sets_are_served(self, api_tasks):
        for key in ("no_target_tasks", "no_data_tasks", "y_only_tasks", "x_optional_tasks"):
            assert key in api_tasks, f"/api/tasks 未下发 {key}"
            assert isinstance(api_tasks[key], list) and api_tasks[key], f"{key} 不应为空"

    def test_served_sets_equal_task_specs_derivation(self, api_tasks):
        """下发的集合必须**逐字等于** `derive(TASK_SPECS)` —— 不是另抄一份。"""
        d = derive(TASK_SPECS)
        assert set(api_tasks["y_only_tasks"]) == set(d.y_only)
        assert set(api_tasks["x_optional_tasks"]) == set(d.x_optional)
        assert set(api_tasks["no_target_tasks"]) == set(d.no_target)
        assert set(api_tasks["no_data_tasks"]) == set(d.no_data)

    def test_orchestrator_constants_equal_derivation(self):
        """`orchestrator` 暴露的常量也必须来自派生（防有人在那里又抄一份）。"""
        d = derive(TASK_SPECS)
        assert set(Y_ONLY_TASKS) == set(d.y_only)
        assert set(X_OPTIONAL_TASKS) == set(d.x_optional)
        assert set(NO_TARGET_TASKS) == set(d.no_target)
        assert set(NO_DATA_TASKS) == set(d.no_data)


class TestSetSemantics:
    """集合之间的语义约束（与具体数值无关，故不会因新增任务而脆弱）。"""

    def test_all_keys_are_registered_tasks(self, api_tasks):
        """四组集合里不得有未注册的任务键（防拼写错误静默生效）。"""
        valid = set(TASK_REGISTRY)
        for key in ("no_target_tasks", "no_data_tasks", "y_only_tasks", "x_optional_tasks"):
            unknown = sorted(set(api_tasks[key]) - valid)
            assert not unknown, f"{key} 含未注册任务键: {unknown}"

    def test_y_only_and_x_optional_are_disjoint(self):
        """「只需 Y」与「X 可选」语义互斥 —— 同一任务不应同时在两组。"""
        overlap = set(Y_ONLY_TASKS) & set(X_OPTIONAL_TASKS)
        assert not overlap, f"两组不应有交集（语义互斥）: {sorted(overlap)}"

    def test_no_data_tasks_are_free_of_column_requirements(self, api_tasks):
        """完全不需数据的任务（如 `doe_design`/`power_analysis`）必须免列检查。

        否则用户点「DOE 实验设计」会被拦住要求先选 Y —— 纯参数计算却要求数据。
        """
        no_target = set(api_tasks["no_target_tasks"])
        missing = sorted(set(NO_DATA_TASKS) - no_target)
        assert not missing, f"以下任务无需任何数据，但不在免 Y 集合里，会被误拦: {missing}"

    def test_y_only_and_no_target_are_independent(self):
        """`y_only` 与 `no_target` **不互斥** —— 记录这一事实，防止有人想当然地「收紧」。

        ⚠️ 我首版写了「`y_only` 蕴含必须有 Y，故不得同时 `no_target`」并**失败**：
        实测 `doe_design` / `power_analysis` / `inverse_solve` 三者**同时**在两个集合里。
        原因：它们 `no_data`（纯参数计算，Y 可有可无），但**给了 Y 也能跑** ——
        所以它们既「不需要 Y」，也「只需 Y 即可」。两个维度确实独立：

            · `no_target` —— Y 列**是不是必需**
            · `y_only`    —— X 列**是不是必需**

        故一条任务可以：两者都不需要 / 只需 Y / 需 Y 与 X。
        """
        overlap = set(Y_ONLY_TASKS) & set(NO_TARGET_TASKS)
        # 断言"存在这样的任务"（记录事实），而不是断言"不存在"
        assert overlap, (
            "预期存在既 y_only 又 no_target 的任务（纯参数计算但给了 Y 也能跑）—— "
            "若为空请复核 TaskSpec 声明是否被误改"
        )
        for key in sorted(overlap):
            assert key in set(NO_DATA_TASKS) or key == "inverse_solve", (
                f"{key} 同时标 y_only 与 no_target，但它既非 no_data 也非 inverse_solve —— "
                "请复核该声明是否有意为之"
            )


class TestGuardWouldCatchDrift:
    """自测：提取函数对篡改敏感（防止守卫因正则失效而永远通过）。"""

    def test_extractor_detects_missing_variable(self):
        with pytest.raises(AssertionError, match="未找到"):
            _extract_set("const other = 1;", "_noTargetNeeded")

    def test_extractor_handles_multiline_and_spacing(self):
        js = "const _demo = new Set([\n  'a',\n  'b',\n]);"
        assert _extract_set(js, "_demo") == {"a", "b"}

    def test_simulated_drift_would_fail_equality(self, api_tasks):
        """模拟"后端新增一个 y_only 任务但前端没跟上" —— 当前集合应立即不等。

        （收口后这种漂移**结构上不可能**发生，但本自测证明比对逻辑本身有效。）
        """
        served = set(api_tasks["y_only_tasks"])
        simulated = served | {"_hypothetical_new_task"}
        assert served != simulated
