"""参数标签/提示派生 —— 阶段 P4 步骤④（消灭前端平行字典）。

契约：docs/governance/improvement-plan.md §六

## 解决什么

前端 `web/static/params.js` 曾有三份字典描述"参数长什么样"：

| 字典 | 行数 | 内容 | 本模块 |
|:---|---:|:---|:---|
| `PARAM_LABELS` | 37 | 参数中文名 | ✅ 派生（本模块） |
| `PARAM_HINTS` | 13 | 填写提示 | ✅ 派生（本模块） |
| `PARAM_META` | 169 | 控件类型 + 下拉选项显示文案 | ⛔ 未覆盖（需 `Choice` 支持显示文案） |

前两份的内容**本来就在 `Spec` 里**（`Opt(..., label=..., hint=...)`），属纯重复。

## 数据结构：全局 + 任务级覆盖

前端查找顺序是 `PARAM_LABELS[k + '@' + task] || PARAM_LABELS[k] || k`，
即 `method` 全局是"异常检测方法"，但 `doe_design` 下覆盖为"设计方法"。
故下发扁平字典，键有两种形态：

    {"usl": "规格上限 (USL)", "method@doe_design": "设计方法", ...}

**为什么扁平而不按任务嵌套**：前端查找本来就是扁平查找，保持同构可以
零改动迁移；且全局标签只需存一份，不必在 42 个任务下各复制一遍。

## 缺失时的行为（渐进派生的关键）

未声明 `Spec` 的任务**没有**标签条目 —— 前端回落到参数名本身（`|| k`）。
因此本项**可以先于步骤③ 完成**：随着更多任务迁移，标签覆盖率自动提高，
中间态不会出现空白标签，只是显示英文参数名。
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from smartsuite.services.task_spec import TASK_SPECS

logger = logging.getLogger(__name__)


def _spec_for_task(func_path: str) -> Any | None:
    """按 `func_path` 取引擎模块的 `PARAM_SPEC`；不存在返回 `None`。

    ⚠️ **本函数按模块取，故只适用于"一个模块一个任务"的简写形式。**
    一个模块含多个任务时（如 `engine/exploratory.py` 有 4 个），模块级
    `PARAM_SPEC` 只属于其中一个 —— 用它会给同模块的其他任务**张冠李戴**
    （第二十轮实测发现该缺陷，见 `spec_for_task` 的说明）。

    新代码请用 `spec_for_task(task_key)`；本函数保留供 `_derive` 之外的
    兼容调用与测试使用。
    """
    module_path = func_path.split(":", 1)[0]
    try:
        module = importlib.import_module(module_path)
    except ImportError:  # pragma: no cover - 注册表错误会由别处门禁发现
        logger.warning("无法导入 %s", module_path)
        return None
    return getattr(module, "PARAM_SPEC", None)


def spec_for_task(task_key: str) -> Any | None:
    """按**任务键**取该任务自己的 `PARAM_SPEC`；没有则 `None`。

    ## 为什么必须按任务而非按模块（第二十轮发现的缺陷）

    `PARAM_SPEC` 原本按模块路径解析，但一个模块常含多个任务：

    | 模块 | 含任务 |
    |:---|:---|
    | `engine/exploratory.py` | `box_chart` / `scatter_plot` / `bootstrap_ci` / `median_ci` |
    | `engine/root_cause/association.py` | `contingency` / `cohens_kappa` / `cronbach_alpha` |
    | `engine/root_cause/distribution.py` | `distribution_summary` / `normality_check` |
    | `engine/root_cause/inference.py` | `proportion_ci` / `variance_test` |

    于是同模块的**其他**任务会继承邻居的 Spec —— `cohens_kappa` 拿到
    `contingency` 的 `alpha` 标签、`proportion_ci` 拿到 `variance_test` 的
    `group_col`。这与第十七轮的"选项跨任务泄漏"是同族问题：
    **共用的东西被当成了自己的**。标签错只是显示问题，**选项错是功能问题**。

    解析顺序：
      1. 模块的 `PARAM_SPECS[task_key]`（**推荐**：一个模块多个任务时用）；
      2. 模块级 `PARAM_SPEC`，**但仅当该模块只注册了一个任务**时
         （单任务模块的简写形式，如 `capability` / `design`）；
      3. 否则 `None` —— 明确"该任务尚未迁移"，让前端回落到旧字典。
    """
    matches = [s for s in TASK_SPECS if s.key == task_key]
    if not matches:
        return None
    module_path = matches[0].func_path.split(":", 1)[0]
    try:
        module = importlib.import_module(module_path)
    except ImportError:  # pragma: no cover
        logger.warning("无法导入 %s", module_path)
        return None

    registry = getattr(module, "PARAM_SPECS", None)
    if isinstance(registry, dict) and task_key in registry:
        return registry[task_key]

    # 模块级 `PARAM_SPEC` 只在"该模块独占一个任务"时才可信
    tasks_in_module = [s.key for s in TASK_SPECS if s.func_path.split(":", 1)[0] == module_path]
    if len(tasks_in_module) == 1 and tasks_in_module[0] == task_key:
        return getattr(module, "PARAM_SPEC", None)
    return None


def derive_param_labels() -> dict[str, str]:
    """派生参数标签字典（全局 + 任务级覆盖）。

    命名来源：`Spec.labels()`（即各 `Opt`/`Req` 的 `label` 参数）。

    冲突处理：若同一参数名在多个任务下给出**不同**标签，则各任务各存一条
    `name@task`（前端优先取它）；若所有给出该标签的任务**一致**，则只存一条
    全局 `name`（避免冗余，也避免"全局值该取谁"的歧义）。
    """
    return _derive(lambda spec: spec.labels())


def derive_param_hints() -> dict[str, str]:
    """派生参数提示字典（全局 + 任务级覆盖）。来源：`Spec.hints()`。

    只含**确实声明了 hint** 的字段（`Spec.hints()` 已过滤空串）。
    """
    return _derive(lambda spec: spec.hints())


def derive_param_options() -> dict[str, list[list[Any]]]:
    """派生下拉选项字典（**严格任务级**，不设全局兜底）。

    来源：各字段校验器的 `options()`（目前只有 `Choice` 有）。
    值形如 `[[值, 显示文案], ...]`（列表而非元组，便于 JSON 序列化）。

    ## 为什么选项与标签/提示不同 —— 必须逐任务作用域化

    标签/提示搞错只是**显示难看**（`alpha` 在 9 个任务里都叫"显著性水平 α"）；
    选项搞错是**功能错误**：用户会被提供一个引擎不认的值，要么报错，
    要么被 `Choice` 拒绝。实测共用参数名的情况很普遍（12 个参数名被多任务共用），
    例如 `mode` 在 `power_analysis` 是"所需样本量/已达功效"、在 `box_chart`
    是箱体图布局 —— 语义完全无关。

    审查 2026-09-24（第十七轮）：`derive_param_labels` 那套"值一致就下发全局键"
    的策略用在选项上**被测试抓出泄漏** —— 当时只有 `power_analysis` 迁移了
    `mode`，于是 `mode` 被当作"无冲突"下发全局，导致 `box_chart.mode`
    也渲染出 `required_n`/`achieved`（是文本框变下拉框的**功能回归**）。

    故选项一律用 `name@task`：只给**确实声明了该参数的 `Choice`** 的任务。
    """
    out: dict[str, list[list[Any]]] = {}
    for task_spec in TASK_SPECS:
        spec = spec_for_task(task_spec.key)
        if spec is None:
            continue
        for name, opts in _options_of(spec).items():
            out[f"{name}@{task_spec.key}"] = opts
    return out


def _options_of(spec: Any) -> dict[str, list[list[Any]]]:
    """取 `Spec` 里所有带 `options()` 的字段的选项。"""
    out: dict[str, list[list[Any]]] = {}
    for name, f in spec._fields.items():
        validator = f.validator
        if validator is not None and hasattr(validator, "options"):
            out[name] = [[v, label] for v, label in validator.options()]
    return out


def _derive(extract, as_list: bool = False) -> dict[str, Any]:
    """`extract(spec) -> {name: text}` 的通用派生。

    两遍是必要的：单遍无法知道后续任务是否会对同一参数给出不同取值。
    """
    per_task: list[tuple[str, dict[str, Any]]] = []
    for task_spec in TASK_SPECS:
        spec = spec_for_task(task_spec.key)
        if spec is None:
            continue
        values = extract(spec)
        if values:
            per_task.append((task_spec.key, dict(values)))

    # 参数名 → {取值: [任务...]}
    by_name: dict[str, dict[Any, list[str]]] = {}
    for task_key, values in per_task:
        for name, text in values.items():
            key = _hashable(text) if as_list else text
            by_name.setdefault(name, {}).setdefault(key, []).append(task_key)

    result: dict[str, Any] = {}
    for name, variants in by_name.items():
        if len(variants) == 1:
            stored = next(iter(variants))
            result[name] = _unhashable(stored) if as_list else stored
            continue
        # 多任务给出不同取值 → 逐任务各存一条（前端优先取 name@task）
        for stored, tasks in variants.items():
            value = _unhashable(stored) if as_list else stored
            for task_key in tasks:
                result[f"{name}@{task_key}"] = value
    return result


def _hashable(value: Any) -> Any:
    """把选项列表转成可哈希形态（用于"取值是否一致"的比较）。

    选项是 `[[值, 文案], ...]`，列表不可哈希，故转成嵌套元组。
    """
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    return value


def _unhashable(value: Any) -> Any:
    """`_hashable` 的逆：还原成 JSON 友好的列表形态。"""
    if isinstance(value, tuple):
        return [_unhashable(v) for v in value]
    return value
