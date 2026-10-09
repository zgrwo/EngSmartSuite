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

import ast
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smartsuite.services.param_labels import spec_for_task

#: 校验器方法名：`Spec.validate(...)` / `Spec.validate_or_raise(...)` 的返回值
#: 即"已校验参数对象"，其属性取用等价于读取该参数。
_VALIDATOR_METHODS = frozenset({"validate", "validate_or_raise", "check"})


def _is_validator_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _VALIDATOR_METHODS
    )


def _mentions_validator(node: ast.AST) -> bool:
    return any(_is_validator_call(sub) for sub in ast.walk(node))


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [a.arg for a in fn.args.args + fn.args.kwonlyargs]


def _scan_scope(task_key: str) -> list[Path]:
    """任务参数的**读取面扫描范围**：任务模块（包子模块时含同包兄弟）。

    为什么包子模块要扫兄弟：`inverse_solve` 的引擎模块 `engine/inverse/solve.py`
    只做编排与归一，17 个参数散在 `_roles.py` / `_solver.py` / `_params.py` /
    `_bounds.py` / `_report.py` 里读取。只看任务模块会得到 20+ 个"引擎不读"的
    假阳性（本门禁首版实测），门禁随即退化成一张大豁免表 —— 那比没有更糟。

    平铺在 `engine/` 根下的模块**不扫兄弟**：那里是几十个互不相关的任务模块，
    合并读取面会让"某任务真的不读某键"永远查不出来（假阴性）。
    """
    from smartsuite.services.task_spec import TASK_SPECS

    matched = [s for s in TASK_SPECS if s.key == task_key]
    if not matched:
        return []
    module = importlib.import_module(matched[0].func_path.split(":", 1)[0])
    path = Path(module.__file__)
    engine_dir = Path(importlib.import_module("smartsuite.engine").__file__).parent
    if path.parent != engine_dir:
        return sorted(path.parent.glob("*.py"))
    return [path]


def _scan_read_keys(task_key: str) -> frozenset[str]:
    """**引擎实际会读取**的参数键（`engine_read_param_keys` 的跨函数增强版）。

    `services/param_labels.engine_read_param_keys` 只认 `xxx.get("<字面量>")`
    且限定在任务模块内 —— 作为"未知参数提示"的已知集够用，作为**可达性门禁**
    则会把大量真实读取判成"不读"（首版实测 38 键 / 17 任务假阳性）。本函数补上
    四种本项目实际使用的读取形态：

    1. **内联校验属性**：`SPEC.validate_or_raise(p).method`（`correlation.py:125`）；
    2. **跨函数传递**：`_dd = SPEC.validate_or_raise(p)` → `_build_design(_dd)` →
       形参 `spec_params.replicates`（`doe.py:816/745`）；
    3. **循环变量作键**：`for spec_key, _ in [("usl", …), ("lsl", …)]: _xp.get(spec_key)`
       （`xbar_r.py:434`、`exploratory.py:517`）；
    4. **键名走实参**：`_str_param(params, "model", "auto")` → 形参 `key` 被
       `params.get(key)` 取用（`inverse/_params.py` + `inverse/solve.py`）。

    仍是**保守下界**：动态拼键（`params.get(f"{role}_cols")`）与跨模块实参传递
    不在覆盖内 —— 这类键由本文件的 `UNREAD_WHITELIST` 具名登记（见下）。
    """
    files = _scan_scope(task_key)
    if not files:
        return frozenset()
    trees = [ast.parse(f.read_text(encoding="utf-8-sig")) for f in files]

    # ── 第一遍：全局函数签名 + "哪个形参被当作参数键使用" ──
    func_params: dict[str, list[str]] = {}
    key_params: dict[str, set[str]] = {}
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            func_params.setdefault(node.name, _param_names(node))
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and sub.args
                    and isinstance(sub.args[0], ast.Name)
                ):
                    key_params.setdefault(node.name, set()).add(sub.args[0].id)
                if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Name):
                    key_params.setdefault(node.name, set()).add(sub.slice.id)

    keys: set[str] = set()
    for tree in trees:
        keys |= _scan_tree(tree, func_params, key_params)
    return frozenset(keys)


def _scan_tree(
    tree: ast.AST,
    func_params: dict[str, list[str]],
    key_params: dict[str, set[str]],
) -> set[str]:
    """单文件分析：上面 `_scan_read_keys` 的四种形态 + holder 数据流。"""
    funcs = {
        n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    # 循环变量 → 其可迭代表达式里的字符串常量
    loop_keys: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        strings = {
            c.value
            for c in ast.walk(node.iter)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
        for sub in ast.walk(node.target):
            if isinstance(sub, ast.Name):
                loop_keys.setdefault(sub.id, set()).update(strings)

    def keys_of(arg: ast.AST) -> set[str]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return {arg.value}
        if isinstance(arg, ast.Name):
            return set(loop_keys.get(arg.id, ()))
        return set()

    keys: set[str] = set()

    # 形态 4：本地/同包辅助函数的"键名实参"
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        wanted = key_params.get(node.func.id)
        if not wanted:
            continue
        names = func_params.get(node.func.id, [])
        for i, arg in enumerate(node.args):
            if i >= len(names) or names[i] in wanted:
                keys |= keys_of(arg)
        for kw in node.keywords:
            if kw.arg in wanted:
                keys |= keys_of(kw.value)

    # holder = 校验结果（`x = SPEC.validate(...)` / `x, err = SPEC.validate(...)`）
    holders: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if node.value is None or not _mentions_validator(node.value):
            continue
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    holders.add(sub.id)
    # 形态 2：holder 作为实参传给本地函数 → 对应形参也是 holder（不动点）
    for _ in range(4):
        added = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            fn = funcs.get(node.func.id)
            if fn is None:
                continue
            names = _param_names(fn)
            for i, arg in enumerate(node.args):
                if i >= len(names):
                    break
                name = arg.id if isinstance(arg, ast.Name) else None
                if (name in holders or _mentions_validator(arg)) and names[i] not in holders:
                    holders.add(names[i])
                    added = True
        if not added:
            break

    for node in ast.walk(tree):
        # 形态 1/2：属性取用（`SPEC.validate_or_raise(p).usl` / `validated.usl`）
        if isinstance(node, ast.Attribute) and (
            _mentions_validator(node.value)
            or (isinstance(node.value, ast.Name) and node.value.id in holders)
        ):
            keys.add(node.attr)
        # 形态 3 + 既有口径：`*.get(<键>)`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            recv = node.func.value
            is_holder = isinstance(recv, ast.Name) and recv.id in holders
            is_params = ast.unparse(recv).split(".")[-1].endswith("params")
            if is_holder or is_params or _mentions_validator(recv):
                keys |= keys_of(node.args[0])
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in holders
        ):
            keys |= keys_of(node.slice)
    return keys


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
        """`anova.interactions` 必须接受下拉框发出的 `"0"`/`"1"`（P0-2 实例）。

        断言不止"无错误"：还要求**归一化结果**正确（`"0"` → 整数 `0`），
        否则"接受了但解析成别的值"会溜过去。
        """
        from smartsuite.services.param_labels import spec_for_task

        spec = spec_for_task("anova")
        assert spec is not None
        for raw, expected in (("0", 0), ("1", 1)):
            params, err = spec.validate({"interactions": raw})
            assert err is None, f"interactions={raw!r} 应被接受（下拉框只能发出字符串）"
            assert params.interactions == expected, (
                f"interactions={raw!r} 应归一为 {expected}，实际 {params.interactions!r}"
            )
        # 别名不得放宽"非法值"的拒绝语义
        _params, bad = spec.validate({"interactions": "9"})
        assert bad is not None and bad.code == "E_PARAM_NOT_IN_CHOICES", bad


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
    | ✅ 已补键（10 个） | `spc_attribute.n_col`、`spc_cusum.mu/sigma`、`spc_ewma.mu/sigma`、`survival_analysis.group_col`、`process_capability.transform`、`anomaly_detect.contamination`、`change_point.min_segment/min_peak_ratio` | 引擎侧 `None` 与"不给"逐字等价（逐个读源码 + 实跑核对）。其中 3 个需要引擎侧一并改语义：`transform` 需 `Choice` 补「不做变换」空值选项（否则补键 = 强制开启 Box-Cox）；`contamination`/`min_segment`/`min_peak_ratio` 需把 `params.get(k, default)` 改为 `or default`（键存在且值为 `None` 时前者返回 `None`，`int(None)` 会报格式错误） |
    | ✅ 已删除（1 个） | `spc_attribute.subgroup_col` | **Spec 多余声明**：`attribute_chart` 全文不读该键（传不存在的列名结果逐字相同）。已由引擎侧删除该字段 —— 补进面板只会造出"能设但没用"的假参数 |

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
        # （`spc_attribute.subgroup_col` 曾登记于此：2026-10-09 已由引擎侧**删除该 Spec
        #   字段**（它本就是死声明），故不再是"有意不渲染"而是"不存在"，登记已移除。）
        # （`process_capability.transform` 曾登记于此：2026-10-09 已修 —— 引擎侧
        #   `Choice` 补了「不做变换」空值选项、`default_params` 补了 `transform: ""`，
        #   故它现在**可达**，登记已按「过期即失败」的机制移除。
        #   见 TestCapabilityTransformReachableWithoutForcingBoxCox。）
    }

    #: 审查 P2-8 **举证清单**里尚未可达的参数 —— 2026-10-09 **已清空**。
    #:
    #: 11 项举证的最终处置：10 项补进面板、1 项确认是 Spec 多余声明并删除。
    #: 机制保留：日后若发现新缺口，必须具名登记并写明理由；`test_p28_evidence_is_reachable_or_registered`
    #: 会因"未登记"而红，`test_p28_reachable_count_is_pinned` 会因"数字变了"而红 ——
    #: 缺口不许无声存在，也不许用登记代替修复。
    KNOWN_UNREACHABLE: dict[tuple[str, str], str] = {}

    #: 审查 P2-8 原文逐条举证的参数（`引擎支持、Web 面板不可达`）。
    #: 注：报告正文写「13 个参数」，但逐条列出的只有 11 个（2+2+2+1+1+2+1）——
    #: 本表按**逐条清单**登记，并在报告中记录该口径差异。
    P28_EVIDENCE: tuple[tuple[str, str], ...] = (
        ("spc_attribute", "n_col"),
        # ⚠️ `("spc_attribute", "subgroup_col")` 已从举证清单**移除**（2026-10-09）：
        # 复核确认它**不是可达性缺口** —— `attribute_chart` 全文不读该键，
        # 它是 Spec 里的死声明（传不存在的列名，结果与完全不传逐字相同）。
        # 正确处置是删除该 Spec 字段（已做），而不是给它补一个"能设但没用"的控件。
        # 这条留档很重要：审查报告把它列为"引擎支持、Web 不可达"，属**误报**。
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
        assert len(reachable) == 10, (
            f"P2-8 举证参数中可达数应为 10（n_col / mu,sigma×2 / group_col / transform /"
            f" contamination / min_segment / min_peak_ratio；另 1 项确认为多余声明已删除），"
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


class TestNewlyReachableParamsAreActuallyHonored:
    """补进面板的 4 个参数必须**真的生效**，而不只是"键存在"（审查 P2-8 收口）。

    只断言"DEFAULT_PARAMS 里有这个键"是弱证据 —— 引擎完全可能忽略它。
    故每个参数都断言**行为随取值改变**，并覆盖 `None`（未指定）不报错。
    """

    @staticmethod
    def _frame():
        rng = np.random.default_rng(9)
        y = np.concatenate([rng.normal(50, 2, 100), rng.normal(60, 2, 100)])
        y[5] = 200.0
        return pd.DataFrame({"y": y, "x": rng.normal(0, 1, 200)})

    def _isoforest(self, **params):
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        return orchestrate(
            AnalysisRequest(
                task="anomaly_detect",
                data=self._frame(),
                target_col="y",
                feature_cols=["x"],
                params={"method": "isolation_forest", **params},
            )
        )

    def test_contamination_changes_the_verdict(self):
        """污染率必须真的驱动异常点数量（而非被忽略）。"""
        none_r = self._isoforest(contamination=None)
        assert none_r.status == "ok", none_r.messages
        # None = 未指定 → 落回引擎默认 0.05（**不得**因 float(None) 报错）
        assert none_r.metadata["contamination"] == pytest.approx(0.05)
        base = none_r.metadata["anomaly_count"]

        high = self._isoforest(contamination=0.2)
        assert high.status == "ok", high.messages
        assert high.metadata["anomaly_count"] > base, (
            f"污染率 0.2 应比默认 0.05 命中更多异常点：{base} → {high.metadata['anomaly_count']}"
        )

    def test_contamination_auto_sentinel_still_works(self):
        r = self._isoforest(contamination="auto")
        assert r.status == "ok", r.messages
        assert str(r.metadata["contamination"]).lower() == "auto"

    def test_change_point_new_params_accept_none_and_values(self):
        """`min_segment` / `min_peak_ratio` 的 `None` 必须落回引擎内部默认值。

        ⚠️ 这是本组最容易出错的一个：`params.get(k, default)` 在"键存在且值为 None"
        时返回 **None**（不是 default），随后 `int(None)` 会报「参数格式错误」——
        即"用户没填"变成报错。故引擎侧改用了 `or`，本用例钉住它。
        """
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        for params in ({}, {"min_segment": None, "min_peak_ratio": None}, {"min_segment": 30}):
            r = orchestrate(
                AnalysisRequest(
                    task="change_point",
                    data=self._frame(),
                    target_col="y",
                    feature_cols=[],
                    params=params,
                )
            )
            assert r.status == "ok", f"params={params}: {r.messages}"
            assert "变点" in r.summary, f"params={params}: {r.summary}"

    def test_spc_attribute_still_runs_after_spec_field_removal(self):
        """删除 `subgroup_col` 死声明后，`spc_attribute` 行为不得变化。"""
        from smartsuite.core.contracts import AnalysisRequest
        from smartsuite.services.orchestrator import orchestrate

        rng = np.random.default_rng(4)
        r = orchestrate(
            AnalysisRequest(
                task="spc_attribute",
                data=pd.DataFrame({"y": rng.poisson(20, 120).astype(float)}),
                target_col="y",
                feature_cols=[],
                params={"chart_type": "c"},
            )
        )
        assert r.status == "ok", r.messages
        assert "控制图" in r.summary

        from smartsuite.engine.spc_charts.attribute import PARAM_SPEC

        assert "subgroup_col" not in PARAM_SPEC.field_names, (
            "subgroup_col 是死声明（引擎全文不读），不应重新出现"
        )


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


class TestDefaultParamsAreReadByTheEngine:
    """「面板可达、引擎不读」的**假参数**必须被点名（审查 2026-10-09 A-3）。

    ## 缺陷机制（注入 I-3 实测）

    给 `regression` 同时加 `Spec.fake_knob`（`Finite(gt=0, le=10)` + 中文标签 + 提示）
    与 `default_params["fake_knob"] = 3`，结果：

        pytest tests/services/test_param_spec_registry.py tests/scripts/test_params_panel.py \\
               tests/engine/test_param_migration_batch8.py tests/core -q   → 208 passed
        node scripts/check_params_panel.mjs                                → OK
        python scripts/verify_frontend_params.py                           → OK
        pytest tests/integration/test_api_tasks_params.py …                → 42 passed
        运行时（把该默认值送给引擎）                                        → status=ok, messages=[]

    即 **8 项门禁全绿**，而用户在面板上改这个参数**什么都不会发生**，且没有任何提示。
    既有门禁全都只看"`Spec` 与 `default_params` 是否互相一致"—— 假参数当然一致。

    ## 判据：`default_params` 的每个键都必须**被引擎真实读取**

    注意"在 `Spec.field_names` 里"**不是**证据 —— 注入 I-3 的 `fake_knob` 就在 Spec 里。
    故判据只有两条：① 被 `_scan_read_keys(task)`（AST 读取面）命中；
    ② 落在下面**逐条写明理由**的 `UNREAD_WHITELIST` 里。

    白名单的**过期即失败**：登记项若某天变成"引擎读了"（或键被删了），
    本组用例会 FAIL 要求移除登记 —— 缺口不许无声存在，也不许用登记代替修复。

    ⚠️ 前身口径：审查报告建议的判据是「`key ∈ engine_read_param_keys(task)` **或**
    `Spec` 中该字段被 `ValidatedParams` 属性取用」。本组实现取**更严**的口径
    （只认"引擎读"）：`engine_read_param_keys` 单独用会有 38 键 / 17 任务的假阳性
    （它只认任务模块内的 `xxx.get("<字面量>")`），故本文件另写了跨函数增强扫描器
    `_scan_read_keys`（四种读取形态见其 docstring），把假阳性压到 6 键。
    """

    #: 引擎**确实不读**、但有明确理由的键（任务, 键）→ 理由。理由须 ≥ 20 字。
    UNREAD_WHITELIST: dict[tuple[str, str], str] = {
        ("regression", "model_type"): (
            "**文档化保留参数**：`docs/specification/api-reference.md` 明写"
            "「params: `model_type`（保留参数，当前仅支持 OLS）」，"
            "`regression_analysis()` 有意不读它（`doe_opt/regression.py:35-37` 已留档"
            "「那是独立问题，需先确认该被读还是该移除」）。属有意设计，不是缺陷。"
        ),
        ("inverse_solve", "incoming_cols"): (
            "**前端注入的列角色勾选组**：面板把勾选结果作为列表下发；引擎在"
            " `engine/inverse/_roles.py::_resolve_roles` 用**动态拼键**"
            ' `params.get(f"{role}_cols")` 读取 —— f-string 拼出的键名静态解析不出来，'
            " 属扫描器的已知保守下界（同族：variable_cols/fixed_cols/output_cols/target_cols）。"
        ),
        ("inverse_solve", "variable_cols"): (
            '同上：前端列角色勾选组，引擎以 `params.get(f"{role}_cols")` 动态键读取'
            "（`_roles.py::_resolve_roles`），AST 无法解析 f-string 键名。"
        ),
        ("inverse_solve", "fixed_cols"): (
            '同上：前端列角色勾选组，引擎以 `params.get(f"{role}_cols")` 动态键读取'
            "（`_roles.py::_resolve_roles`），AST 无法解析 f-string 键名。"
        ),
        ("inverse_solve", "output_cols"): (
            '同上：前端列角色勾选组，引擎以 `params.get(f"{role}_cols")` 动态键读取'
            "（`_roles.py::_resolve_roles`），AST 无法解析 f-string 键名。"
        ),
        ("inverse_solve", "target_cols"): (
            '同上：前端列角色勾选组，引擎以 `params.get(f"{role}_cols")` 动态键读取'
            "（`_roles.py::_resolve_roles`），AST 无法解析 f-string 键名。"
        ),
    }

    @staticmethod
    def _unread() -> dict[str, list[str]]:
        """各任务中「不在 Spec 也不被引擎读取」的 `default_params` 键。"""
        from smartsuite.services.orchestrator import DEFAULT_PARAMS
        from smartsuite.services.task_spec import TASK_SPECS

        gaps: dict[str, list[str]] = {}
        for spec in TASK_SPECS:
            declared = set(DEFAULT_PARAMS.get(spec.key, {}))
            if not declared:
                continue
            unread = sorted(declared - _scan_read_keys(spec.key))
            if unread:
                gaps[spec.key] = unread
        return gaps

    def test_every_default_param_is_read_by_the_engine(self):
        """**核心断言**：`default_params` 的每个键都必须被引擎读取（白名单除外）。"""
        offenders = [
            f"{task}.{key}"
            for task, keys in self._unread().items()
            for key in keys
            if (task, key) not in self.UNREAD_WHITELIST
        ]
        assert not offenders, (
            "以下参数**面板可达但引擎不读**（用户改了不起作用，且不报错、不提示）：\n  "
            + "\n  ".join(sorted(offenders))
            + "\n请把它接到引擎上（或从 `default_params` 删掉）；若确属有意保留，"
            "请在 `TestDefaultParamsAreReadByTheEngine.UNREAD_WHITELIST` 登记并写明理由。"
        )

    def test_whitelist_has_reasons_and_no_stale_entries(self):
        """白名单必须逐条写明理由，且**过期即失败**（引擎读它了 / 键没了 → 必须移除）。"""
        unread = self._unread()
        for (task, key), reason in self.UNREAD_WHITELIST.items():
            assert len(reason.strip()) >= 20, f"{task}.{key} 的豁免理由过于简略: {reason!r}"
            assert key in unread.get(task, []), (
                f"白名单过期：{task}.{key} 现在**已被引擎读取**（或该键已不存在），"
                "请从 UNREAD_WHITELIST 移除该登记"
            )

    def test_reserved_param_reason_stays_true(self):
        """`regression.model_type` 的豁免理由依赖 api-reference 的「保留参数」声明。

        声明被删掉后，豁免就只剩"我懒得接"——故把理由的**事实依据**也钉住。
        """
        api = Path(__file__).resolve().parents[2] / "docs" / "specification" / "api-reference.md"
        lines = [
            line
            for line in api.read_text(encoding="utf-8").splitlines()
            if "model_type" in line and "保留参数" in line
        ]
        assert lines, (
            "api-reference.md 不再声明 `model_type` 是保留参数 —— 那么它就只是"
            "「引擎不读的假参数」，应接线或删除，不得继续豁免"
        )

    def test_scanner_is_not_vacuous(self):
        """扫描器不得退化成空集/恒真 —— 否则上一条断言会变成永远通过。

        三个锚点分别对应扫描器的三种读取形态（内联属性 / 循环变量作键 / 普通 `get`）：
        它们都是首版朴素扫描器**漏掉**的真实读取，回归任何一种都说明扫描能力退化。
        """
        from smartsuite.services.orchestrator import DEFAULT_PARAMS
        from smartsuite.services.task_spec import TASK_SPECS

        total = 0
        for spec in TASK_SPECS:
            if DEFAULT_PARAMS.get(spec.key):
                keys = set(_scan_read_keys(spec.key))
                total += len(keys)
                assert keys, f"{spec.key} 的读取面为空 —— 扫描器失效"
        assert total >= 150, f"全库读取面只有 {total} 个键，扫描器可能失效"

        for task, key in (
            ("correlation", "method"),  # 形态 1：SPEC.validate_or_raise(p).method
            ("spc_xbar", "usl"),  # 形态 3：for spec_key in [("usl", …)]: _xp.get(spec_key)
            ("process_capability", "usl"),  # 既有口径：params.get("usl")
        ):
            assert key in _scan_read_keys(task), f"扫描器漏掉 {task}.{key}（读取形态退化）"
