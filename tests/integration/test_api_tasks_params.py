"""`/api/tasks` 下发参数默认值的契约测试（阶段 P4 步骤④）。

契约：docs/governance/improvement-plan.md §六（目标：删除前端平行字典）

## 为什么这个端点要下发 `params`

前端 `web/static/params.js` 原先自己维护一份 `TASK_PARAMS`（42 个任务的
默认值），与后端 `services/task_spec.py::TASK_SPECS` 的 `default_params`
**逐字重复**。两份必须一致，靠 `scripts/verify_frontend_params.py`
每次门禁比对来维持 —— 这是典型的"手工一致性"，也是本计划阶段3 要消灭的对象。

改成由 `/api/tasks` 下发后：
- 后端是**唯一事实源**（SSOT），前端不再持有副本；
- 门禁的角色从"校验两份是否一致"变为"结构上不可能不一致"。

> 本端点此前只下发 `tasks`/`labels`/`groups`，且**前端从未调用**
> （任务按钮由服务端模板渲染）。本文件即为让它真正被使用而写的契约。
"""

from __future__ import annotations

import json

import pytest

from smartsuite.services.orchestrator import DEFAULT_PARAMS, TASK_LABELS, TASK_REGISTRY
from smartsuite.web.app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _payload(client) -> dict:
    r = client.get("/api/tasks")
    assert r.status_code == 200, r.status_code
    return json.loads(r.data)


class TestTasksEndpointContract:
    """端点现有契约（不得因新增字段而破坏）。"""

    def test_returns_200_and_json(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert r.is_json, r.content_type

    def test_keeps_existing_keys(self, client):
        """`tasks` / `labels` / `groups` 三个既有键必须保留（向后兼容）。"""
        d = _payload(client)
        for key in ("tasks", "labels", "groups"):
            assert key in d, f"既有键 {key} 丢失"

    def test_task_list_matches_registry(self, client):
        d = _payload(client)
        assert set(d["tasks"]) == set(TASK_REGISTRY), "任务集应与注册表一致"

    def test_labels_match_server_side_labels(self, client):
        d = _payload(client)
        assert d["labels"] == TASK_LABELS


class TestTasksEndpointProvidesDefaults:
    """**新增字段** `params`：各任务的参数默认值（取代前端 `TASK_PARAMS`）。"""

    def test_provides_params_key(self, client):
        d = _payload(client)
        assert "params" in d, "应下发 params（前端 TASK_PARAMS 的替代）"

    def test_params_covers_every_task(self, client):
        d = _payload(client)
        assert set(d["params"]) == set(TASK_REGISTRY), (
            "每个任务都要有默认值条目（前端据此决定是否显示参数面板）"
        )

    def test_params_matches_default_params_exactly(self, client):
        """**核心断言**：下发的默认值必须与 `DEFAULT_PARAMS` 逐任务、逐键一致。

        这条取代了原先"前端 JS 字典 vs 后端字典"的门禁比对 ——
        现在比对的是同一个源，故不可能漂移。
        """
        d = _payload(client)
        for task, expected in DEFAULT_PARAMS.items():
            assert d["params"][task] == expected, (
                f"{task} 的默认值不一致：下发 {d['params'][task]} vs 后端 {expected}"
            )

    def test_params_keys_match_default_params_keys(self, client):
        d = _payload(client)
        for task in TASK_REGISTRY:
            assert set(d["params"][task]) == set(DEFAULT_PARAMS[task]), task

    def test_task_without_params_is_empty_dict_not_missing(self, client):
        """无参数的任务应下发 `{}`（而非缺失）——前端据此隐藏参数面板。

        `{}` 与"缺失"在前端语义不同：缺失会被当成"未知任务"。
        """
        d = _payload(client)
        for task in TASK_REGISTRY:
            assert isinstance(d["params"][task], dict), task

    def test_values_are_json_serializable_scalars(self, client):
        """下发的值必须是 JSON 可表示的标量/列表（前端直接用作表单初值）。"""
        d = _payload(client)
        raw = json.dumps(d)  # 不能抛
        restored = json.loads(raw)
        assert restored["params"] == d["params"]

    def test_empty_string_defaults_are_preserved(self, client):
        """空串默认值必须原样下发（不能变成 None）——`verify_frontend_params.py`
        的既有白名单记录了这类差异，前端依赖空串渲染空输入框。"""
        d = _payload(client)
        # process_capability 的 subgroup_col 默认是 ""
        assert d["params"]["process_capability"]["subgroup_col"] == ""

    def test_newly_reachable_params_are_served(self, client):
        """P2-8 修复的**用户可见效果**：这些键必须出现在下发载荷里。

        面板的控件键集**就是**这里下发的 `params`（`params.js::showParams` 遍历它），
        所以"补键"是否生效，唯一可信的判据是本端点下发的载荷 —— 光看
        `TaskSpec.default_params` 只证明了一半。

        审查 2026-10-09 P2-8：本次补齐 7 个参数。其中 6 个值一律 `None`（"未指定"，
        与其在引擎里"未提供则由数据估计/回退"的语义一致）；`process_capability.transform`
        例外 —— 它必须是 `""`（「不做变换」），因为在 `<select>` 里 `None` 匹配不上任何
        `selected`，浏览器会自动选第一个选项（=开启 Box-Cox）。故同时断言它的**取值**。
        其余 4 个（`spc_attribute.subgroup_col`、`anomaly_detect.contamination`、
        `change_point.min_peak_ratio/min_segment`）**有意未补**，理由逐条登记在
        `tests/services/test_param_spec_registry.py::TestParamReachability`。
        """
        d = _payload(client)
        expected_none_keys = {
            "spc_attribute": ["n_col"],
            "spc_cusum": ["mu", "sigma"],
            "spc_ewma": ["mu", "sigma"],
            "survival_analysis": ["group_col"],
        }
        for task, keys in expected_none_keys.items():
            served = d["params"][task]
            missing = [k for k in keys if k not in served]
            assert not missing, f"{task} 未下发 {missing} —— Web 面板不会有对应控件（P2-8 复发）"
            assert all(served[k] is None for k in keys), (
                f"{task} 的 {keys} 默认值应为 None（引擎按'未指定'回退），"
                f"实际 {[(k, served[k]) for k in keys]}"
            )
        # `transform` 现在**可以**下发，但默认值必须是「不做变换」空值 ——
        # 若下发 None，`<select>` 会自动选中第一个选项（=强制开启 Box-Cox）。
        assert d["params"]["process_capability"].get("transform") == "", (
            "process_capability.transform 的默认值必须是 ''（不做变换）："
            "None 会让浏览器自动选中首个选项（=强制开启 Box-Cox）"
        )


class TestNoDuplicateFrontendDictionary:
    """**结构验收**：前端不得再持有自己的默认值字典。

    这是阶段 P4 步骤④ 的目标本身 —— 若前端仍有 `TASK_PARAMS` 字面量，
    本条失败，提醒迁移未完成（或有人又加回去了）。
    """

    def test_frontend_has_no_task_params_literal(self):
        """前端不得持有**非空**的默认值字典字面量。

        允许的两种形态（都是新架构的一部分，**不得误报**）：
          - `let TASK_PARAMS = {};`  —— 空缓存初始化
          - `TASK_PARAMS = params;`  —— 从 `/api/tasks` 灌入

        真正要禁的是"又把 42 个任务的默认值抄回前端"。
        （本条首版把上面两种都误报为"仍有副本"，故加 `[^}]+` 要求字面量非空。）
        """
        import re
        from pathlib import Path

        static = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web" / "static"
        literal_re = re.compile(r"TASK_PARAMS\s*=\s*\{[^}]+\}")
        offenders = []
        for js in static.glob("*.js"):
            text = js.read_text(encoding="utf-8")
            # 只看代码，忽略注释里的说明性提及
            code = "\n".join(line.split("//", 1)[0] for line in text.splitlines())
            if literal_re.search(code):
                offenders.append(js.name)
        assert not offenders, f"前端仍持有默认值字典（应改为从 /api/tasks 取）：{offenders}"

    def test_frontend_hydrates_from_api(self):
        """`app.js` 必须真的调用 `hydrateParams` 并请求 `/api/tasks`。

        否则默认值永远不会到位 → 所有任务退化为"无参数"（**静默功能缺失**：
        用户点任务会直接用引擎默认值跑，看不到参数面板）。
        """
        from pathlib import Path

        static = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "web" / "static"
        app_js = (static / "app.js").read_text(encoding="utf-8")
        assert "hydrateParams(" in app_js, "app.js 未调用 hydrateParams()"
        assert "/api/tasks" in app_js, "app.js 未请求 /api/tasks"
