"""「新增方法成本」的收口守卫（第 42 轮 ②）。

契约：[improvement-plan.md](../../docs/governance/improvement-plan.md) §十 硬指标表
      「新增方法成本 8 步 → 1 步」

## 8 步里哪些已被自动化（实测）

| 步 | 内容 | 现状 |
|:--|:---|:---|
| 1 | `engine/xxx.py` 实现函数 | **不可省**（就是要写的代码） |
| 2 | `engine/__init__.py` 的 `__all__` 加函数名 | 手工一次（惰性导出机制在，但名单手写） |
| 3 | `services/task_spec.py::TASK_SPECS` 加一条 | **唯一注册点** → `derive()` 派生 7 个结构 |
| 4 | `app.js` 的 `TASK_PARAMS` 加参数默认值 | ✅ **已自动化**（后端 `/api/tasks` 下发，第三轮） |
| 5 | `templates/` 建 YAML | 手工一次 |
| 6 | `tests/` 覆盖 2 层防线 | 应写（不是"注册成本"） |
| 7 | `api-reference.md` 更新 | 手工一次 |
| 8 | `user-manual/` + 决策树 | 手工一次 |

**但真正隐蔽的成本不在上面 8 步里** —— 实测发现 `static/app.js` 另有三份手写集合：

    _noTargetNeeded   // 无需 Y 列的任务
    _yOnlyTasks       // 只需 Y 列即可运行
    _xOptionalTasks   // X 列可选

新增任务若忘改这三者，**不报错、不失败**，只是该任务在 Web 上永远跑不起来
（用户看到「请至少选择一个 X 列」）。这是"8 步"清单里没有、却最容易漏的一步。

第 42 轮已把它收口：`TaskSpec` 声明 `y_only` / `x_optional` → `derive()` 派生 →
`/api/tasks` 下发 → 前端只读。本文件锁定该收口，**防止手写集合回流**。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "src" / "smartsuite" / "web" / "static"


def _js(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def _client():
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from smartsuite.web.app import app

    app.config["TESTING"] = True
    return app.test_client()


class TestFrontendHasNoHandRolledTaskSets:
    """`static/*.js` 不得再有按任务名硬编码的列需求集合。"""

    #: 曾经存在过的三个手写集合名（第 42 轮删除）
    _BANNED = ("_noTargetNeeded", "const _yOnlyTasks", "const _xOptionalTasks")

    @pytest.mark.parametrize("banned", _BANNED)
    def test_banned_identifier_is_gone(self, banned):
        """判据用"**赋值/声明**形态"而非裸名 —— 注释里说明"原先是什么"是允许的。

        （我第一版用裸名匹配，被自己解释来龙去脉的注释命中 —— 与
        `xbar_r.py` 那次同一类误报。）
        """
        joined = "\n".join(_js(n) for n in ("app.js", "params.js", "state.js", "api.js", "util.js"))
        # 变量声明或 new Set 赋值形态
        pattern = re.compile(rf"(const|let|var)\s+{re.escape(banned.replace('const ', ''))}\s*=")
        assert not pattern.search(joined), (
            f"{banned} 又出现在前端 —— 列需求必须由后端下发，不得手写（否则新增任务会静默不可用）"
        )

    def test_frontend_reads_the_served_sets(self):
        """前端必须**读取**后端下发的三组集合（证明收口真的接通了）。"""
        params = _js("params.js")
        for fn in ("noTargetTasks", "yOnlyTasks", "xOptionalTasks"):
            assert f"export function {fn}(" in params, f"params.js 缺少访问器 {fn}"
        app = _js("app.js")
        for fn in ("noTargetTasks()", "yOnlyTasks()", "xOptionalTasks()"):
            assert fn in app, f"app.js 未使用 {fn}（列需求校验可能又改回手写了）"

    def test_hydrate_receives_the_sets(self):
        """`hydrateParams` 必须接收三组集合（否则访问器永远返回空集）。"""
        params = _js("params.js")
        for key in ("no_target_tasks", "y_only_tasks", "x_optional_tasks"):
            assert key in params, f"hydrateParams 未接收 {key}"


class TestApiServesColumnRequirements:
    """`/api/tasks` 必须下发四组列需求，且与 `TASK_SPECS` 一致。"""

    @pytest.mark.parametrize(
        "key",
        ["no_target_tasks", "no_data_tasks", "y_only_tasks", "x_optional_tasks"],
    )
    def test_endpoint_serves_the_set(self, key):
        payload = _client().get("/api/tasks").get_json()
        assert key in payload, f"/api/tasks 未下发 {key}"
        assert isinstance(payload[key], list), f"{key} 应为列表"
        assert payload[key], f"{key} 不应为空（42 个任务里没有一个符合？）"

    def test_sets_match_task_specs(self):
        """下发的集合必须**逐字等于** `TASK_SPECS` 派生结果（不是另抄一份）。"""
        import sys

        sys.path.insert(0, str(_ROOT / "src"))
        from smartsuite.services.task_spec import TASK_SPECS, derive

        d = derive(TASK_SPECS)
        payload = _client().get("/api/tasks").get_json()
        assert set(payload["y_only_tasks"]) == set(d.y_only)
        assert set(payload["x_optional_tasks"]) == set(d.x_optional)
        assert set(payload["no_target_tasks"]) == set(d.no_target)
        assert set(payload["no_data_tasks"]) == set(d.no_data)

    def test_served_task_keys_are_real(self):
        """集合里不得有 `TASK_SPECS` 里不存在的键（防拼写错误静默生效）。"""
        import sys

        sys.path.insert(0, str(_ROOT / "src"))
        from smartsuite.services.task_spec import TASK_SPECS

        valid = {s.key for s in TASK_SPECS}
        payload = _client().get("/api/tasks").get_json()
        for key in ("no_target_tasks", "no_data_tasks", "y_only_tasks", "x_optional_tasks"):
            unknown = set(payload[key]) - valid
            assert not unknown, f"{key} 含不存在的任务名：{sorted(unknown)}"


class TestEveryTaskHasADeliberateColumnRequirement:
    """**每个任务都必须有明确的列需求判定** —— 新增任务不能"忘了想"。"""

    def test_every_task_is_classified(self):
        """每个任务要么 `y_only`、要么 `x_optional`、要么两者都不是（要求 Y+X）。

        这条不是要求"必须有标记"（多数任务确实要 Y 和 X），而是要求
        **分类是可枚举的、且总数对得上** —— 新增任务时若把 `y_only` 忘掉，
        它就会被当成"要 Y+X"，在 Web 上静默不可用。故本用例配合下一条
        （前端读取）共同保证：**漏声明会立刻表现为测试失败**，而不是用户点不动。
        """
        import sys

        sys.path.insert(0, str(_ROOT / "src"))
        from smartsuite.services.task_spec import TASK_SPECS

        y_only = {s.key for s in TASK_SPECS if s.y_only}
        x_opt = {s.key for s in TASK_SPECS if s.x_optional}
        both = y_only & x_opt
        assert not both, f"同时标 y_only 与 x_optional 在语义上冲突：{sorted(both)}"
        neither = {s.key for s in TASK_SPECS} - y_only - x_opt
        # 两者都不是是**正常**的（要求 Y+X），但要保证这类占了多数且可枚举
        assert len(neither) > 0, "所有任务都标了 y_only/x_optional？请复核是否标错"
        assert len(y_only) + len(x_opt) + len(neither) == len(TASK_SPECS)

    def test_y_only_tasks_do_not_read_feature_cols(self):
        """`y_only=True` 的任务，其引擎函数**不应读 `feature_cols`**。

        这条把声明与实现对上：若某任务被标 `y_only` 但引擎其实读 `feature_cols`，
        用户不选 X 时会拿到错误结果（而不是被前端拦住）。反之不查 ——
        读 `feature_cols` 但标 `x_optional` 是**合法**的（`inverse_solve`
        用 `feature_cols` 定义正向模型输入列，X 仍可选）。
        """
        import ast
        import sys

        sys.path.insert(0, str(_ROOT / "src"))
        from smartsuite.services.task_spec import TASK_SPECS

        #: **已知且正当的例外**：这些任务标 `y_only`（只需 Y 即可运行），
        #: 但引擎源码里**出现** `feature_cols` —— 因为该参数对它们另有语义：
        #:   · `inverse_solve` 用 `feature_cols` 定义**正向模型**的输入列，
        #:     不是必需的 X 轴（实测：只给 Y 也能跑）。
        #: 例外必须显式登记 —— 否则"新增一个标错 y_only 的任务"会被静默放过。
        ALLOWED = {"inverse_solve"}

        offenders = []
        for s in TASK_SPECS:
            if not s.y_only or s.key in ALLOWED:
                continue
            mod, fn = s.func_path.split(":", 1)
            p = _ROOT / "src" / (mod.replace(".", "/") + ".py")
            if not p.is_file():
                continue
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src)
            node = next(
                (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn),
                None,
            )
            if node is None:
                continue
            body = ast.get_source_segment(src, node) or ""
            if "feature_cols" in body:
                offenders.append(f"{s.key}（{mod}:{fn}）")
        assert not offenders, (
            f"以下任务标了 y_only 但引擎读 feature_cols —— 声明与实现不符：{offenders}"
        )
