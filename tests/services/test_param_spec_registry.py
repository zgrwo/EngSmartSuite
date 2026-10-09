"""`PARAM_SPEC` 的**按任务**解析（修一个真实缺陷）。

## 缺陷（第二十轮发现）

`services/param_labels.py::_spec_for_task(func_path)` 按**模块路径**取
`PARAM_SPEC`。但一个模块常含多个任务：

| 模块 | 含任务 |
|:---|:---|
| `engine/exploratory.py` | `box_chart` / `scatter_plot` / `bootstrap_ci` / `median_ci` |
| `engine/root_cause/association.py` | `contingency` / `cohens_kappa` / `cronbach_alpha` |
| `engine/root_cause/distribution.py` | `distribution_summary` / `normality_check` |
| `engine/root_cause/inference.py` | `proportion_ci` / `variance_test` |

故模块级 `PARAM_SPEC` 只属于**其中一个**任务，但派生逻辑会让同模块的**其他**
任务也拿到它 —— 即 `cohens_kappa` 会继承 `contingency` 的 `alpha` 标签、
`proportion_ci` 会继承 `variance_test` 的 `group_col`。

这正是第十七轮遇到过的"选项跨任务泄漏"同族问题：**共用的东西被当成了自己的**。
标签错只是显示问题，但**选项错是功能问题**（用户被提供引擎不认的值）——
而 `param_options` 走同一条派生路径，故同样受影响。

## 修法

`PARAM_SPEC` 改为**按任务注册**：任务模块里用
`PARAM_SPECS = {"task_key": Spec(...)}` 声明，解析时先查该映射，
再回落到模块级 `PARAM_SPEC`（单任务模块的简写形式）。
"""

from __future__ import annotations

import pytest

from smartsuite.services.param_labels import spec_for_task


class TestSpecIsResolvedPerTask:
    """同模块的多个任务**不得**互相继承 `PARAM_SPEC`。"""

    def test_single_task_module_still_works(self):
        """单任务模块（`capability` / `design`）沿用模块级 `PARAM_SPEC`。"""
        assert spec_for_task("process_capability") is not None
        assert spec_for_task("power_analysis") is not None

    @pytest.mark.parametrize(
        "task",
        [
            # 以下任务与**别的任务同模块**，且自身尚未迁移 → 必须返回 None。
            # 注意：迁移某个任务后，请把它从本表移出 —— 本表是"尚未迁移"的**活清单**。
            # 已移出：`distribution_summary`（第二十一轮）、`proportion_ci`（第二十二轮）。
            "cohens_kappa",
            "cronbach_alpha",
        ],
    )
    def test_task_without_own_spec_gets_none(self, task):
        """**核心断言**：同模块里没有自己 Spec 的任务必须返回 `None`。

        返回别人的 Spec 会让它的参数拿到错误的标签/提示/**选项** ——
        后者是功能问题。修复前这些任务全部会返回同模块邻居的 Spec。
        """
        assert spec_for_task(task) is None, (
            f"{task} 不该有 Spec（同模块的 Spec 属于别的任务）；"
            "若确实为它新增了 Spec，请把它从本用例的参数表里移出"
        )

    def test_task_with_own_spec_gets_it(self):
        """有自己 Spec 的任务必须拿到**自己**的（而非同模块邻居的）。"""
        from smartsuite.core.param_specs_common import ALPHA
        from smartsuite.engine.root_cause.association import PARAM_SPECS

        assert spec_for_task("contingency") is PARAM_SPECS["contingency"]
        assert PARAM_SPECS["contingency"].field_names == ["alpha"]
        assert PARAM_SPECS["contingency"]._fields["alpha"] is ALPHA

    def test_inference_tasks_do_not_share(self):
        """`proportion_ci` 与 `variance_test` 同模块，但两者**各有自己的** Spec。

        实测两者的 `DEFAULT_PARAMS` 不同（`proportion_ci` 有 `success_value`、
        `variance_test` 有 `group_col`），故**不可能**共用一份 ——
        这正是"按任务登记"要保证的：同模块的条目互不干扰。
        """
        s_vt = spec_for_task("variance_test")
        s_pc = spec_for_task("proportion_ci")
        assert s_vt is not s_pc, "两个任务必须各有独立 Spec"
        assert set(s_vt.field_names) == {"group_col", "alpha"}
        assert set(s_pc.field_names) == {"ci_level", "success_value"}

    def test_unknown_task_returns_none(self):
        assert spec_for_task("no_such_task") is None


class TestEveryUiSelectableValueIsAccepted:
    """面板**能选中**的每个值，引擎都必须接受（审查 2026-10-09 P0-2）。

    ## 缺陷链条

    1. `params.js:403` 把 `Choice` 渲染为 `<select><option value="${val}">`；
    2. DOM 的 `option.value` **必然是字符串**；
    3. `getParams`（`params.js:509`）只对 `<input>` 做 `Number()` 转换，`<select>` 原样下发字符串。

    于是对 `allowed` 含非字符串值的 `Choice`：前端只能发出字符串形式，
    若该 Choice 未登记对应别名，引擎**必然拒绝** → 该任务在 Web 端 100% 不可用。

    实测实例：`anova.interactions = Choice((0,"不含交互"),(1,"含两两交互"))` 无别名 →
    四个可选交互全部报「参数「含两两交互 (0/1)」(interactions) 取值无效: '0'；可选值：0, 1」。
    同模块的 `ss_type` 因 `aliases={"2":2,"3":3}` 而幸免（`anova.py:38-39` 的注释
    已写明该风险，却漏了 `interactions`）—— 属「同族修复不完整」。

    ## 判据选择

    `Choice` 的严格语义（整数候选不匹配字符串写法）是**有意设计**，且被
    `tests/core/test_param_spec_choice_options.py::test_normalization_unaffected_by_labels`
    钉住（该模块注释记明「这条曾在本模块首版写反过」）。故**不得**为了让本用例通过
    去放宽 `Choice` —— 正确做法是给缺失的 Choice 补 `aliases`（项目既有机制）。
    """

    def test_string_form_of_every_option_is_accepted(self):
        from smartsuite.services.param_labels import derive_param_options, spec_for_task

        offenders: list[str] = []
        checked = 0
        for key, opts in derive_param_options().items():
            name, _, task = key.partition("@")
            spec = spec_for_task(task)
            if spec is None:
                continue
            field = spec._fields.get(name)
            if field is None or field.validator is None:
                continue
            for value, _label in opts:
                checked += 1
                _norm, err = field.validator.check(str(value))
                if err is not None:
                    offenders.append(
                        f"{key}: 前端只能发出 {str(value)!r}，引擎拒绝 —— {err.message}"
                    )
        assert checked > 0, "未枚举到任何选项，扫描器失效（本用例会变成恒真断言）"
        assert not offenders, (
            "以下选项在前端**可选中**但引擎**必然拒绝**（该任务 Web 端不可用）：\n  "
            + "\n  ".join(offenders)
        )

    def test_anova_interactions_accepts_select_string(self):
        """`anova.interactions` 必须接受下拉框发出的 `"0"`/`"1"`（P0-2 实例）。"""
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("anova")
        assert spec is not None
        for raw in ("0", "1"):
            _params, err = spec.validate({"interactions": raw})
            assert err is None, f"interactions={raw!r} 应被接受（下拉框只能发出字符串）"


class TestParamReachability:
    """参数可达性：`Spec` 声明的东西必须**在 Web 面板上真的能设**（审查 2026-10-09 P2-8）。

    ## 缺陷机制（两条平行来源）

    | 面板的什么 | 来自哪里 |
    |:---|:---|
    | **控件键集**（渲染哪些控件） | `TaskSpec.default_params` → `/api/tasks` → `params.js::showParams` 遍历它 |
    | **标签 / 提示 / 选项** | 引擎模块的 `Spec`（`Opt(..., label=..., hint=...)`） |

    两者一旦不一致，就出现"引擎支持、`Spec` 有中文标签、面板却没有控件"的
    **不可达参数** —— 用户无从设置，且**不报错、不失败**（属最难发现的一类缺陷）。

    实测（2026-10-09 全量审查）：报告称 7 个任务 13 个参数如此（逐条列出的实为 11 个）。
    其中 `spc_cusum` 的 `messages` 还在建议用户「通过参数 mu/sigma 指定已知受控状态的
    参数」—— **提示去设一个 Web 上根本不存在的参数**。

    ## 本轮结果（P2-8 修复的实际边界）

    | 结果 | 参数 | 原因 |
    |:---|:---|:---|
    | ✅ 已补键（7 个） | `spc_attribute.n_col`、`spc_cusum.mu/sigma`、`spc_ewma.mu/sigma`、`survival_analysis.group_col`、`process_capability.transform` | 引擎侧 `None` 与"不给"逐字等价（逐个读源码 + 实跑核对）；`transform` 另需引擎侧 `Choice` 补「不做变换」空值选项（否则补键 = 强制开启 Box-Cox） |
    | ⛔ 仍不可达（4 个） | `spc_attribute.subgroup_col`、`anomaly_detect.contamination`、`change_point.min_peak_ratio/min_segment` | 补键会造出假参数 / 破坏引擎侧 `Spec.defaults() == DEFAULT_PARAMS` 主防线 / 引擎默认值依赖样本量 —— **都需改 engine 侧**，已在 `KNOWN_UNREACHABLE` 逐条登记 |

    ## 判据

    对每个已迁移任务断言 `set(Spec.field_names) ⊆ set(DEFAULT_PARAMS[task])`；
    差异必须为空，或落在下面**逐条写明理由**的白名单里。
    """

    #: `Spec` 声明但 `default_params` **有意不渲染**的字段（必须逐条给理由）。
    SPEC_ONLY: dict[tuple[str, str], str] = {
        ("spc_attribute", "filter_groups"): (
            "Web 运行时注入项：由前端分组筛选栏在提交前塞进 params，不是参数面板里"
            "用户填写的字段（引擎 `attribute_chart` 直接读 `req.params.get('filter_groups')`）。"
        ),
        ("spc_attribute", "subgroup_col"): (
            "**Spec 声明多余**（本轮实测）：`attribute_chart` 全文不读该键 —— 传一个"
            "不存在的列名，结果与完全不传逐字相同。加进 `default_params` 只会造出"
            "「面板能设、引擎不看」的假参数（与 `multi_objective.direction` 同族）。"
            "正确修法是删除该 Spec 字段，而 `engine/spc_charts/attribute.py` 不在本批所有权内。"
        ),
        # （`process_capability.transform` 曾登记于此：2026-10-09 已修 —— 引擎侧
        #   `Choice` 补了「不做变换」空值选项、`default_params` 补了 `transform: ""`，
        #   故它现在**可达**，登记已按「过期即失败」的机制移除。
        #   见 TestCapabilityTransformReachableWithoutForcingBoxCox。）
    }

    #: 审查 P2-8 **举证清单**里尚未可达的参数（登记即承认缺口）。
    #: 一旦补齐，本表会因「登记过期」而失败，强制移除 —— 缺口不许无声存在。
    KNOWN_UNREACHABLE: dict[tuple[str, str], str] = {
        ("spc_attribute", "subgroup_col"): (
            "引擎不读该键（见 SPEC_ONLY）→ 补键会造假参数；须先由引擎侧删除 Spec 字段。"
        ),
        ("anomaly_detect", "contamination"): (
            "`Spec` **有意不声明**它（支持 `(0,0.5]` 数值或字符串 'auto' 双形态，见"
            "`anomaly.py:24-27`）。补键会打破 `tests/engine/test_param_migration_batch5.py`"
            "的 `Spec.defaults() == DEFAULT_PARAMS[task]` 主防线（精确相等），"
            "而修该防线必须先给它声明 `Spec` 字段 —— `engine/detection/anomaly.py` 不在本批所有权内。"
        ),
        ("change_point", "min_peak_ratio"): (
            "同上：`change_point` 的 `Spec` 只声明 `n_changepoints`，补键会打破"
            "`tests/engine/test_param_migration_batch3.py` 的同一条主防线；"
            "引擎默认值 2.0 已在源码核对（`change_point.py:54`）。"
        ),
        ("change_point", "min_segment"): (
            "**引擎默认值依赖样本量**：`_def_ms = min(max(10, n // 20), (n - 1) // 2)`"
            "（`change_point.py:48`），`DEFAULT_PARAMS` 只能给静态值 —— 给 `None` 或 `''` 会让"
            "`params.get('min_segment', _def_ms)` 命中已存在的键而返回 None/''，"
            "在 `int()` 处报「变点检测参数格式错误」（已实测复现）；给 10 则 n=20 时"
            "触发 `2*min_segment >= n` 直接报错。须引擎侧改为"
            "`params.get('min_segment') or _def_ms` 才能补键。"
        ),
    }

    #: 审查 P2-8 原文逐条举证的参数（`引擎支持、Web 面板不可达`）。
    #: 注：报告正文写「13 个参数」，但逐条列出的只有 11 个（2+2+2+1+1+2+1）——
    #: 本表按**逐条清单**登记，并在报告中记录该口径差异。
    P28_EVIDENCE: tuple[tuple[str, str], ...] = (
        ("spc_attribute", "n_col"),
        ("spc_attribute", "subgroup_col"),
        ("spc_cusum", "mu"),
        ("spc_cusum", "sigma"),
        ("spc_ewma", "mu"),
        ("spc_ewma", "sigma"),
        ("process_capability", "transform"),
        ("anomaly_detect", "contamination"),
        ("change_point", "min_peak_ratio"),
        ("change_point", "min_segment"),
        ("survival_analysis", "group_col"),
    )

    @staticmethod
    def _gap(task: str) -> set[str]:
        """某任务「Spec 声明 − 面板渲染」的字段差集（无 Spec 的任务视为空集）。"""
        from smartsuite.services.orchestrator import DEFAULT_PARAMS
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task(task)
        if spec is None:
            return set()
        return set(spec.field_names) - set(DEFAULT_PARAMS.get(task, {}))

    def test_spec_fields_are_reachable(self):
        """**核心断言**：`Spec` 的每个字段都要在面板上有控件（白名单除外）。"""
        from smartsuite.services.task_spec import TASK_SPECS

        offenders: list[str] = []
        for s in TASK_SPECS:
            for name in sorted(self._gap(s.key)):
                if (s.key, name) not in self.SPEC_ONLY:
                    offenders.append(f"{s.key}.{name}")
        assert not offenders, (
            "以下参数 `Spec` 已声明（有中文标签/提示）却不在 `default_params` 里 —— "
            "Web 面板永远不会渲染它们的控件（用户无从设置、且不报错）：\n  "
            + "\n  ".join(offenders)
            + "\n请补 `TaskSpec.default_params` 键；若确属有意不渲染，"
            "请在 `TestParamReachability.SPEC_ONLY` 登记并写明理由。"
        )

    def test_spec_only_whitelist_has_reasons_and_no_stale_entries(self):
        """白名单必须**逐条写明理由**，且不得过期（缺口补齐后必须移除登记）。"""
        for (task, name), reason in self.SPEC_ONLY.items():
            assert len(reason.strip()) >= 20, f"{task}.{name} 的白名单理由过于简略: {reason!r}"
            assert name in self._gap(task), (
                f"白名单过期：{task}.{name} 现在已在 `default_params` 里（面板可达），"
                "请从 SPEC_ONLY 移除该登记"
            )

    def test_p28_evidence_is_reachable_or_registered(self):
        """审查 P2-8 举证的每个参数：要么已可达，要么在缺口表中登记。"""
        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        unreachable = [
            (task, name)
            for task, name in self.P28_EVIDENCE
            if name not in DEFAULT_PARAMS.get(task, {})
        ]
        unregistered = [f"{t}.{n}" for t, n in unreachable if (t, n) not in self.KNOWN_UNREACHABLE]
        assert not unregistered, (
            f"P2-8 举证参数仍不可达且未登记原因：{unregistered} —— 补键或登记理由，二者必居其一"
        )
        stale = [f"{t}.{n}" for (t, n) in self.KNOWN_UNREACHABLE if n in DEFAULT_PARAMS.get(t, {})]
        assert not stale, f"缺口登记过期（这些参数已可达，请移出 KNOWN_UNREACHABLE）：{stale}"

    def test_p28_reachable_count_is_pinned(self):
        """把「本轮补齐了 6 个」钉住 —— 数字变化必须是有意的。

        为什么钉数字：若有人再往 `default_params` 里删键（或把补上的键改回去），
        上一条用例会因"未登记"而红；但若有人**同时**在图省事地补一条登记，
        缺口就会无声扩大。这条防止"用登记代替修复"。
        """
        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        reachable = sorted(
            f"{t}.{n}" for t, n in self.P28_EVIDENCE if n in DEFAULT_PARAMS.get(t, {})
        )
        assert len(reachable) == 7, (
            f"P2-8 举证参数中可达数应为 7（本轮补齐 n_col / mu,sigma×2 / group_col / transform），"
            f"实际 {len(reachable)}：{reachable}"
        )
        for pinned in (
            "spc_attribute.n_col",
            "spc_cusum.mu",
            "spc_cusum.sigma",
            "spc_ewma.mu",
            "spc_ewma.sigma",
            "survival_analysis.group_col",
        ):
            assert pinned in reachable, f"{pinned} 应已可达：{reachable}"


class TestUnknownParamDetectionOnRealSpecs:
    """真实任务 `Spec` 上的未知键检测（审查 2026-10-09 P2-5）。

    复现原文：`process_capability(usll=70, lsll=30)` → `status=ok`、`cp=None`、
    `cpk=None`、`messages=[]`（`usl=70,lsl=30,bogus_xyz=1` 亦同）。

    ⚠️ **接入待定**：把检测结果并入 `AnalysisResult.messages` 需改
    `services/orchestrator.py`（不在本批文件所有权内）—— 本组只证明
    "检测已实现且对真实 Spec 有效"，是否接入由主审查者决定。
    """

    def test_capability_typo_is_detected(self):
        """原文实例：`{"usll": 70}` 必须返回 `["usll"]`。"""
        from smartsuite.engine.capability import PARAM_SPEC

        assert PARAM_SPEC.unknown_fields({"usll": 70}) == ["usll"]
        assert PARAM_SPEC.unknown_fields({"usll": 70, "lsll": 30}) == ["lsll", "usll"]
        assert PARAM_SPEC.unknown_fields({"usl": 70, "lsl": 30, "bogus_xyz": 1}) == ["bogus_xyz"]

    def test_capability_typo_message_names_available_params(self):
        from smartsuite.engine.capability import PARAM_SPEC

        msg = PARAM_SPEC.unknown_message({"usll": 70})
        assert msg is not None
        assert "usll" in msg and "usl" in msg, msg

    def test_no_spec_reports_its_own_defaults_as_unknown(self):
        """**交叉自检**：任何任务的 `Spec.defaults()` 送回去都不得含未知键。

        这条同时防止两类错误：`defaults()` 派生出拼接错的键名，或
        `default_params` 与 `Spec` 之间出现新的漂移（P2-8 的同族）。
        """
        from smartsuite.services.param_labels import spec_for_task
        from smartsuite.services.task_spec import TASK_SPECS

        offenders: list[str] = []
        checked = 0
        for s in TASK_SPECS:
            spec = spec_for_task(s.key)
            if spec is None:
                continue
            checked += 1
            unknown = spec.unknown_fields(spec.defaults())
            if unknown:
                offenders.append(f"{s.key}: {unknown}")
        assert checked >= 10, f"只检查到 {checked} 个任务 —— 扫描器可能失效（用例会变恒真）"
        assert not offenders, f"以下任务的 Spec.defaults() 含自己都不认识的键：{offenders}"


class TestRegistryShape:
    """`PARAM_SPECS` 的形状契约。"""

    def test_registry_maps_task_keys_to_specs(self):
        from smartsuite.engine.root_cause.association import PARAM_SPECS

        assert isinstance(PARAM_SPECS, dict)
        for key, spec in PARAM_SPECS.items():
            assert isinstance(key, str) and key
            assert hasattr(spec, "validate_or_raise"), key

    def test_registry_keys_are_real_tasks(self):
        from smartsuite.services.orchestrator import TASK_REGISTRY

        for module in (
            "smartsuite.engine.root_cause.association",
            "smartsuite.engine.root_cause.distribution",
            "smartsuite.engine.root_cause.inference",
            "smartsuite.engine.exploratory",
        ):
            mod = __import__(module, fromlist=["PARAM_SPECS"])
            for key in getattr(mod, "PARAM_SPECS", {}):
                assert key in TASK_REGISTRY, f"{module} 的 PARAM_SPECS 键 {key!r} 不是已注册任务"


class TestCapabilityTransformReachableWithoutForcingBoxCox:
    """`process_capability.transform` 必须在面板可达，**且默认不开启变换**。

    审查 2026-10-09 P2-8 的举证清单把它列为「引擎支持但 Web 不可达」。但**直接补键
    会引入回归**：原 `Choice("boxcox")` 只有一个选项，`params.js::buildParamInput`
    把它渲染成**无空选项**的 `<select>`，默认 `None` 匹配不上任何 `selected`
    → 浏览器自动选第一个 → 面板回读 `{"transform":"boxcox"}`，即 **Web 用户被强制
    开启 Box-Cox 且关不掉**（与 CLI / 引擎默认不一致）。

    故修法是两手同时做：① `Choice` 增加「不做变换」空值选项；② 默认值为该空值。
    本用例同时钉住这两点，防止只做一半（补了键却强制了变换）。
    """

    def test_transform_is_reachable_and_defaults_to_no_transform(self):
        from smartsuite.services.orchestrator import DEFAULT_PARAMS

        cfg = DEFAULT_PARAMS.get("process_capability", {})
        assert "transform" in cfg, "transform 应已补进 default_params（否则面板不渲染）"
        assert cfg["transform"] in ("", None), (
            f"默认必须为「不做变换」，否则 Web 用户会被强制开启 Box-Cox：{cfg['transform']!r}"
        )

    def test_choice_has_empty_option_and_accepts_it(self):
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("process_capability")
        assert spec is not None
        _params, err = spec.validate({"transform": ""})
        assert err is None, f"Choice 必须接受空值（「不做变换」）：{err and err.message}"
        _params, err = spec.validate({"transform": "boxcox"})
        assert err is None, f"Choice 仍须接受 boxcox：{err and err.message}"

        import importlib.util as _ilu
        from pathlib import Path as _Path

        _root = _Path(__file__).resolve().parents[2]
        _m = _ilu.spec_from_file_location(
            "verify_frontend_params", _root / "scripts" / "verify_frontend_params.py"
        )
        _vfp = _ilu.module_from_spec(_m)
        assert _m and _m.loader
        _m.loader.exec_module(_vfp)
        opts = _vfp.check()
        assert not opts, f"前端参数门禁应保持全绿：{opts}"
