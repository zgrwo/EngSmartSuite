"""`templates/*.yaml` 的 `task` 键校验（审查 2026-09-21 G-7）。

`templates/` 是「配置驱动」的入口资产（42 个任务的方法变体模板），但原先**没有任何
门禁**保证其中的 `task` 键真实存在于 `TASK_REGISTRY`——任务改名或删除后，模板会静默
失效，用户跑到 `未知的分析任务` 才发现。实测 2026-09-21：45/45 合法，属**潜在盲区**
而非既有缺陷；本模块把它变成可被 CI 拦截的显式检查。

提炼为可导入纯函数（与 `claims_gate.py` 同模式）：`verify_consistency.py` 是模块级
「导入即执行」的脚本，无法被单测引用，而门禁自身也需要负向注入自测（G1 原则）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

_MISSING_TASK_SENTINEL = "<缺 task 键>"


def iter_template_tasks(templates_dir: Path) -> dict[str, str]:
    """返回 `{相对文件名: task 键}`。

    - 缺 `task` 键（或顶层不是映射）→ 值为 `<缺 task 键>` 哨兵（交由调用方判定为失败，
      不静默跳过）；
    - YAML 解析失败 → 值为 `<解析失败: 异常类型>`，同样视为失败（模板坏了必须有门禁可见）。

    返回相对文件名（而非绝对路径）便于稳定断言与友好报错。
    """
    result: dict[str, str] = {}
    for path in sorted(templates_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            result[path.name] = f"<解析失败: {type(exc).__name__}>"
            continue
        if not isinstance(data, dict) or "task" not in data:
            result[path.name] = _MISSING_TASK_SENTINEL
            continue
        result[path.name] = str(data["task"])
    return result


def validate_template_tasks(templates_dir: Path, known_tasks: set[str]) -> list[str]:
    """返回问题描述列表（空 = 全部合规）；每条含文件名与原因，供门禁直接打印。"""
    problems: list[str] = []
    for name, task in iter_template_tasks(templates_dir).items():
        if task == _MISSING_TASK_SENTINEL or task.startswith("<"):
            problems.append(f"{name}: {task}")
        elif task not in known_tasks:
            problems.append(f"{name}: 未注册的 task「{task}」")
    return problems
