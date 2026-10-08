"""`/api/tasks` 下发参数标签/提示的契约测试（阶段 P4 步骤④续）。

契约：docs/governance/improvement-plan.md §六（目标：删除前端平行字典）

## 背景

前端 `params.js` 有三份字典描述"参数长什么样"：

| 字典 | 行数 | 内容 |
|:---|---:|:---|
| `PARAM_LABELS` | 37 | 参数的中文名 |
| `PARAM_HINTS` | 13 | 参数的填写提示 |
| `PARAM_META` | 169 | 控件类型 + 下拉选项显示文案 |

`PARAM_LABELS` / `PARAM_HINTS` 的内容**本来就是 `Spec` 里已有的**
（`Opt(..., label=..., hint=...)`），属纯重复。本文件锁定它们改由
`/api/tasks` 派发。

## 作用域（关键设计）

前端查找顺序是 `PARAM_LABELS[k + '@' + task] || PARAM_LABELS[k] || k`，
即存在**任务级覆盖**（`method` 全局是"异常检测方法"，但 `doe_design` 下是"设计方法"）。
故下发的数据结构与之前 `TASK_PARAMS` 不同：

    params:  { task: { name: default } }        # 任务级（每个任务一套键）
    labels:  { "name@task": label, name: label } # 全局 + 任务级覆盖

**缺失时的行为**：前端回落到参数名本身（`|| k`），所以尚未声明 `Spec` 的任务
不会出现空白标签，只是显示英文参数名 —— 可接受，且随迁移推进自动变好。
这使本项能**先于步骤③ 完成**，无需等所有任务迁移完。
"""

from __future__ import annotations

import json

import pytest

from smartsuite.services.orchestrator import TASK_REGISTRY
from smartsuite.web.app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _spec_of(task_key: str):
    """取某任务的 `PARAM_SPEC`（复用服务层派生逻辑的同一入口）。

    审查 2026-09-24（第二十轮）：改为**按任务键**解析 —— 原先按模块路径取，
    会让同模块的其他任务继承邻居的 Spec（见 `param_labels.spec_for_task` 的说明）。
    """
    from smartsuite.services.param_labels import spec_for_task

    return spec_for_task(task_key)


def _payload(client) -> dict:
    r = client.get("/api/tasks")
    assert r.status_code == 200
    return json.loads(r.data)


class TestLabelsAndHintsDispatched:
    """端点必须下发 `labels` / `hints` 两份派生数据。"""

    def test_provides_param_labels_and_hints_keys(self, client):
        d = _payload(client)
        assert "param_labels" in d, "应下发 param_labels（取代前端 PARAM_LABELS）"
        assert "param_hints" in d, "应下发 param_hints（取代前端 PARAM_HINTS）"

    def test_both_are_objects(self, client):
        d = _payload(client)
        assert isinstance(d["param_labels"], dict)
        assert isinstance(d["param_hints"], dict)

    def test_existing_task_labels_are_not_replaced(self, client):
        """⚠️ 既有 `labels` 键已被占用为**任务**标签（TASK_LABELS）。

        参数标签必须放在**另一个键**里，否则会破坏任务按钮的渲染。
        本条是接口设计的回归防线（注意 TASK_LABELS 的值带英文前缀，
        如 `"ANOVA方差分析"`，故断言"含"而非"等于"）。
        """
        d = _payload(client)
        label = d["labels"].get("anova", "")
        assert "方差分析" in label, f"labels 应仍是任务标签；实际 {label!r}"
        assert all("@" not in k for k in d["labels"]), "任务标签不应出现 name@task 形态"

    def test_param_labels_are_in_separate_key(self, client):
        d = _payload(client)
        assert "param_labels" in d, "参数标签应放在 param_labels（避免与任务标签冲突）"
        assert "param_hints" in d, "参数提示应放在 param_hints"


class TestDerivedFromSpec:
    """标签必须**派生自 `Spec`**，而非另抄一份。"""

    def test_migrated_task_label_matches_spec(self, client):
        """已迁移任务（有 `PARAM_SPEC`）的标签必须与 Spec 里的逐字一致。"""
        from smartsuite.engine.capability import PARAM_SPEC

        d = _payload(client)
        spec_labels = PARAM_SPEC.labels()
        for name, label in spec_labels.items():
            key = f"{name}@process_capability"
            got = d["param_labels"].get(key) or d["param_labels"].get(name)
            assert got == label, f"{key}: 下发 {got!r} vs Spec {label!r}"

    def test_migrated_attribute_task_labels_match_spec(self, client):
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        d = _payload(client)
        for name, label in PARAM_SPEC.labels().items():
            key = f"{name}@spc_attribute"
            got = d["param_labels"].get(key) or d["param_labels"].get(name)
            assert got == label, f"{key}: 下发 {got!r} vs Spec {label!r}"

    def test_hints_derived_from_spec(self, client):
        from smartsuite.engine.capability import PARAM_SPEC

        d = _payload(client)
        for name, hint in PARAM_SPEC.hints().items():
            key = f"{name}@process_capability"
            got = d["param_hints"].get(key) or d["param_hints"].get(name)
            assert got == hint, f"{key}: 下发 {got!r} vs Spec {hint!r}"

    def test_all_labels_are_chinese(self, client):
        """所有下发的标签必须含中文（面向工艺用户）。"""
        d = _payload(client)
        for key, label in d["param_labels"].items():
            assert any("\u4e00" <= ch <= "\u9fff" for ch in label), f"{key} → {label!r}"

    def test_all_names_correspond_to_declared_params(self, client):
        """每个标签的**参数名部分**必须确实被引擎读取（防止张冠李戴）。

        审查 2026-09-24：首版断言"参数名必须存在于某任务的 `default_params`"，
        但那**过严** —— `Spec` 可以合法声明比 `default_params` 更多的参数：

          - `process_capability` 的 `transform` / `subgroup_col` / `subgroup_size`
            是引擎支持但未列入默认值表的可选项；
          - `spc_attribute` 的 `filter_groups` 由运行时的分组筛选注入。

        正确的判据是"该参数名确实**存在于参数的唯一来源里**"——要么被 `Spec`
        声明（已迁移任务：`req.params` 经 `PARAM_SPEC.validate_or_raise` 统一读取），
        要么在引擎源码里被 `req.params.get(...)` / `params[...]` 直接读取。
        两者都要算（首版只查后者，把 `lsl` 这类走 Spec 的参数误判为不存在）。
        """
        import re
        from pathlib import Path

        d = _payload(client)
        engine_dir = Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "engine"
        engine_src = "\n".join(p.read_text(encoding="utf-8") for p in engine_dir.rglob("*.py"))
        read_names = set(re.findall(r'req\.params\.get\(\s*"(\w+)"', engine_src))
        # 表单里由控件收集、或经合并默认值进入 params 的键，也在源码中以其他
        # 形式出现（如 params["x"]）；这里补上这种读取形态
        read_names |= set(re.findall(r'params\[\s*"(\w+)"\s*\]', engine_src))

        # 走 Spec 的参数（已迁移任务）
        for task_key in TASK_REGISTRY:
            spec = _spec_of(task_key)
            if spec is not None:
                read_names.update(spec.field_names)

        for key in d["param_labels"]:
            name = key.split("@", 1)[0]
            assert name in read_names, (
                f"标签 {key!r} 的参数名 {name!r} 既未被 Spec 声明、"
                "也未在引擎源码中被 req.params 读取"
            )

    def test_task_scoped_override_wins_in_lookup_order(self, client):
        """模拟前端查找顺序：`name@task` 优先于 `name`。

        若某参数在全局与任务级都有标签，前端会取任务级的 —— 本用例断言
        下发的数据在该顺序下给出 Spec 里的值（即任务级覆盖确实生效）。
        """
        from smartsuite.engine.capability import PARAM_SPEC

        d = _payload(client)
        task = "process_capability"
        for name, label in PARAM_SPEC.labels().items():
            resolved = d["param_labels"].get(f"{name}@{task}") or d["param_labels"].get(name)
            assert resolved == label, f"{name}: 查找顺序下取到 {resolved!r}，期望 {label!r}"


class TestGracefulDegradation:
    """尚未迁移的任务不得让接口失败或缺键。"""

    def test_unmigrated_tasks_are_simply_absent_not_broken(self, client):
        """没有 `PARAM_SPEC` 的任务可以没有标签条目 —— 前端回落到参数名。

        关键是**不能**因此报错，也不能给出错误（张冠李戴）的标签。

        注意：只有**冲突**的标签才带 `@task` 后缀（见 `param_labels._derive`）；
        取值一致的标签是全局的、不带后缀。故本用例既看带后缀的，也看全局标签
        能否覆盖已迁移任务的参数名。
        """
        d = _payload(client)
        scoped_tasks = {k.split("@", 1)[1] for k in d["param_labels"] if "@" in k}
        assert scoped_tasks <= set(TASK_REGISTRY), scoped_tasks

        # 已迁移任务的参数名应能从派生标签里查到（全局或任务级都算）
        for task_key in ("process_capability", "spc_attribute"):
            spec = _spec_of(task_key)
            assert spec is not None, f"{task_key} 应有 PARAM_SPEC"
            for name in spec.field_names:
                got = d["param_labels"].get(f"{name}@{task_key}") or d["param_labels"].get(name)
                assert got, f"{task_key}.{name} 应有派生标签，实际缺失"

    def test_endpoint_survives_every_task_having_no_spec(self, client, monkeypatch):
        """极端情形：所有任务都没有 Spec → 仍须返回 200 且结构完整。"""
        import smartsuite.services.param_labels as pl

        monkeypatch.setattr(pl, "spec_for_task", lambda key: None)
        r = client.get("/api/tasks")
        assert r.status_code == 200
        d = json.loads(r.data)
        assert d["param_labels"] == {}
        assert d["param_hints"] == {}
        assert len(d["params"]) == len(TASK_REGISTRY)


class TestParamOptionsDispatched:
    """`/api/tasks` 下发 `param_options`（下拉选项的值 + 显示文案）。

    这是 `PARAM_META`（169 行，最后一份大重复）可被删除的前置：
    它的 23 条 `select` 需要"每个可选值显示什么"，而这在 `Spec` 里原本无处声明。
    第十七轮给 `Choice` 加了 `(值, 文案)` 候选项形态与 `options()`。
    """

    def test_provides_param_options_key(self, client):
        d = _payload(client)
        assert "param_options" in d, "应下发 param_options（取代前端 PARAM_META.options）"

    def test_options_are_value_label_pairs(self, client):
        d = _payload(client)
        for key, opts in d["param_options"].items():
            assert isinstance(opts, list), key
            for pair in opts:
                assert isinstance(pair, list) and len(pair) == 2, (key, pair)
                assert isinstance(pair[1], str), (key, pair)

    def test_migrated_task_options_match_spec(self, client):
        """已迁移任务的选项必须与 `Spec` 里的 `Choice` 逐条一致。"""
        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        d = _payload(client)
        expected = dict(PARAM_SPEC._fields["chart_type"].validator.options())
        # 严格任务级：键为 `name@task`（见 derive_param_options 的说明）
        got = dict(d["param_options"]["chart_type@spc_attribute"])
        assert got == expected, f"下发 {got} vs Spec {expected}"

    def test_only_choice_fields_have_options(self, client):
        """只有 `Choice` 字段出现在 `param_options` 里（数值/文本字段无选项）。

        防止把非枚举字段也塞进来 —— 前端会因此把它们渲染成下拉框。
        """
        d = _payload(client)
        for task_key in TASK_REGISTRY:
            spec = _spec_of(task_key)
            if spec is None:
                continue
            choice_names = {
                name
                for name, f in spec._fields.items()
                if f.validator is not None and hasattr(f.validator, "options")
            }
            for name in choice_names:
                scoped = f"{name}@{task_key}"
                assert scoped in d["param_options"] or name in d["param_options"], (
                    f"{scoped} 是 Choice 字段却没有选项"
                )

    def test_options_cover_all_choice_fields(self, client):
        """反向：`param_options` 里的每一项都必须对应某任务真实的 `Choice` 字段。"""
        d = _payload(client)
        seen: set[str] = set()
        for task_key in TASK_REGISTRY:
            spec = _spec_of(task_key)
            if spec is None:
                continue
            for name, f in spec._fields.items():
                if f.validator is not None and hasattr(f.validator, "options"):
                    seen.add(name)
                    seen.add(f"{name}@{task_key}")
        for key in d["param_options"]:
            assert key in seen, f"选项 {key!r} 不对应任何 Choice 字段"

    def test_derive_param_options_directly(self, monkeypatch):
        """直接驱动 `derive_param_options`（守卫要求公共函数有直接测试引用）。

        注意假 Spec 对所有任务生效，故每个任务都会得到一条 `mode@<task>`
        —— 这正体现了"严格任务级"的设计（不设全局兜底）。
        """
        import smartsuite.services.param_labels as pl
        from smartsuite.core.param_spec import Choice, Opt, Spec

        fake = Spec(mode=Opt(Choice(("a", "甲"), ("b", "乙")), default="a", label="模式"))
        monkeypatch.setattr(pl, "spec_for_task", lambda key: fake)
        opts = pl.derive_param_options()
        scoped = {k: v for k, v in opts.items() if k.startswith("mode@")}
        assert scoped, f"应产出 name@task 形式的选项: {opts}"
        assert all(v == [["a", "甲"], ["b", "乙"]] for v in scoped.values()), scoped
        assert "mode" not in opts, "不得有全局键（会跨任务泄漏）"

    def test_derive_param_options_empty_without_specs(self, monkeypatch):
        import smartsuite.services.param_labels as pl

        monkeypatch.setattr(pl, "spec_for_task", lambda key: None)
        assert pl.derive_param_options() == {}

    def test_global_options_never_leak_to_a_different_task(self, client):
        """**跨任务隔离**：某任务的下拉选项不得被另一个任务拿到。

        这是本轮引入的真实风险类别：`param_options` 用"全局键兜底"的查找顺序
        （`name@task` → `name`），而多个任务会共用参数名但语义不同 ——
        例如 `method` 在 `anomaly_detect` 是"异常检测方法"、在 `doe_design` 是
        "设计方法"、在 `correlation` 是"相关方法"（实测共 12 个参数名被多任务共用）。

        若某任务的下拉选项被**全局**下发，另一个语义不同的任务就会渲染出
        错误的选项（用户选了引擎不认的值 → 报错或静默走默认分支）。

        本用例逐任务比对：**前端查找顺序**下解析出的选项，必须来自该任务自己的
        `Spec`；若解析出选项而该任务并未声明 `Choice`，即为泄漏。
        """
        d = _payload(client)
        options = d["param_options"]
        for task_key in TASK_REGISTRY:
            spec = _spec_of(task_key)
            # 该任务真实声明了选项的参数名
            own = (
                {
                    name
                    for name, f in spec._fields.items()
                    if f.validator is not None and hasattr(f.validator, "options")
                }
                if spec is not None
                else set()
            )
            task_params = set(d["params"].get(task_key, {}))
            for name in task_params:
                # 模拟前端查找顺序
                resolved = options.get(f"{name}@{task_key}") or options.get(name)
                if resolved is None:
                    continue  # 无选项 → 文本框（正常）
                assert name in own, (
                    f"{task_key}.{name} 解析出了选项 {resolved}，"
                    "但该任务的 Spec 未声明 Choice —— 选项从别的任务泄漏过来了"
                )

    def test_shared_param_name_options_are_always_task_scoped(self, monkeypatch):
        """选项**一律**逐任务作用域化（`name@task`），不设全局兜底。

        审查 2026-09-24（第十七轮）：首版复用了标签那套"值一致就下发全局键"的
        策略，结果被 `test_global_options_never_leak_to_a_different_task` 抓出——
        当时只有 `power_analysis` 迁移了 `mode`，被当作"无冲突"下发全局，
        导致 `box_chart.mode`（箱体图布局）也渲染出 `required_n`/`achieved`。

        即：标签/提示搞错只是显示难看，**选项搞错是功能错误**（用户被提供
        引擎不认的值）。故这里断言得更严：任何选项键都必须带 `@task`。
        """
        import smartsuite.services.param_labels as pl

        opts = pl.derive_param_options()
        unscoped = [k for k in opts if "@" not in k]
        assert not unscoped, f"选项不得有全局键（会跨任务泄漏）: {unscoped}"

    def test_options_only_for_declaring_tasks(self):
        """逐任务核对：选项键只应出现在**真的声明了该 Choice** 的任务下。"""
        from smartsuite.services.param_labels import derive_param_options

        opts = derive_param_options()
        for key in opts:
            name, task_key = key.split("@", 1)
            spec = _spec_of(task_key)
            assert spec is not None, f"{key}: 任务 {task_key} 不应有 Spec"
            validator = spec._fields.get(name)
            validator = validator.validator if validator is not None else None
            assert validator is not None and hasattr(validator, "options"), (
                f"{key}: 该任务未声明 {name} 为 Choice"
            )


class TestDerivationLogic:
    """`derive_param_labels` / `derive_param_hints` 的直接测试。

    端到端用例只覆盖"当前真实迁移状态"（标签少、几乎无冲突），
    而**冲突处理**这条核心逻辑在当前状态下走不到。故用假 Spec 直接驱动。
    """

    def _fake_spec(self, labels: dict[str, str], hints: dict[str, str] | None = None):
        from smartsuite.core.param_spec import Opt, Spec

        fields = {
            name: Opt(label=label, hint=(hints or {}).get(name, ""))
            for name, label in labels.items()
        }
        return Spec(**fields)

    def test_derive_param_labels_emits_global_when_values_agree(self, monkeypatch):
        """多任务对同一参数给出**相同**标签 → 只存一条全局键（不冗余）。"""
        import smartsuite.services.param_labels as pl

        fake = self._fake_spec({"alpha": "显著性水平 α"})
        monkeypatch.setattr(pl, "spec_for_task", lambda key: fake)
        labels = pl.derive_param_labels()
        assert labels.get("alpha") == "显著性水平 α"
        assert not any("@" in k for k in labels), f"值一致时不应产生任务级键: {labels}"

    def test_derive_param_labels_scopes_on_conflict(self, monkeypatch):
        """多任务对同一参数给出**不同**标签 → 逐任务各存 `name@task`。"""
        import smartsuite.services.param_labels as pl

        a = self._fake_spec({"method": "异常检测方法"})
        b = self._fake_spec({"method": "设计方法"})
        calls = {"n": 0}

        def fake_spec_for(path):
            calls["n"] += 1
            return a if calls["n"] % 2 else b

        monkeypatch.setattr(pl, "spec_for_task", fake_spec_for)
        labels = pl.derive_param_labels()
        assert "method" not in labels, "有冲突时不应给全局键（否则取值有歧义）"
        scoped = {k: v for k, v in labels.items() if k.startswith("method@")}
        assert "异常检测方法" in scoped.values(), scoped
        assert "设计方法" in scoped.values(), scoped

    def test_derive_param_labels_task_match_uses_engine_registry(self, monkeypatch):
        """任务名的来源必须是 `TASK_SPECS`（不是调用方传入），故 `@` 后缀可信。"""
        import smartsuite.services.param_labels as pl
        from smartsuite.services.task_spec import TASK_SPECS

        valid_keys = {s.key for s in TASK_SPECS}
        for key in pl.derive_param_labels():
            if "@" in key:
                assert key.split("@", 1)[1] in valid_keys, key

    def test_derive_param_hints_filters_empty(self, monkeypatch):
        """`hints()` 已过滤空串 → 未声明 hint 的字段不应出现空值条目。"""
        import smartsuite.services.param_labels as pl

        fake = self._fake_spec({"usl": "规格上限"}, hints={"usl": "应大于 LSL"})
        monkeypatch.setattr(pl, "spec_for_task", lambda key: fake)
        hints = pl.derive_param_hints()
        assert hints.get("usl") == "应大于 LSL"
        assert all(v for v in hints.values()), "不应出现空串提示"

    def test_derive_returns_empty_when_no_specs(self, monkeypatch):
        import smartsuite.services.param_labels as pl

        monkeypatch.setattr(pl, "spec_for_task", lambda key: None)
        assert pl.derive_param_labels() == {}
        assert pl.derive_param_hints() == {}

    def test_derive_param_hints_is_directly_testable(self, monkeypatch):
        """直接驱动 `derive_param_hints`（守卫要求公共函数有直接测试引用）。"""
        import smartsuite.services.param_labels as pl

        fake = self._fake_spec({"a": "A 标签"}, hints={"a": "A 提示"})
        monkeypatch.setattr(pl, "spec_for_task", lambda key: fake)
        assert pl.derive_param_hints().get("a") == "A 提示"
