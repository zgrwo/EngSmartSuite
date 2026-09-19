"""spc_charts 子包共享助手（自然排序 / 分组解析）。"""

import pandas as pd

from smartsuite.core.contracts import AnalysisRequest


def _natural_sort_key(v):
    """数值优先的自然排序键（Round-2 #A5）。

    numpy>=2.0 下 np.int64/np.float64 不再是 int/float 子类，
    isinstance(v, (int, float)) 会漏判 → 数值列退回字符串字典序（1,10,11,2）。
    用 numbers.Number 覆盖全部数值类型；bool 视为字符串（避免 True/1 混淆）。
    """
    import numbers
    from typing import Any, cast

    if isinstance(v, numbers.Number) and not isinstance(v, bool):
        # typeshed 的 Number 未声明 __float__（int/float/np 标量运行时均有）；
        # cast 仅为类型层断言，运行时无操作
        return (0, float(cast(Any, v)))
    return (1, str(v))


def _resolve_groups(req: AnalysisRequest) -> tuple[pd.Series, list, bool, str, list]:
    """解析分组参数，返回 (group_vals, group_names, has_groups, y_col)。

    CUSUM 和 EWMA 共享的分组解析逻辑，消除 ~15 行重复代码。
    处理 group_col 提取、has_groups 分支、filter_groups 筛选。
    """
    y_col = req.target_col
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in req.data.columns)

    if has_groups:
        group_vals = req.data[group_col]
        group_names = sorted(group_vals.dropna().unique())
    else:
        group_vals = pd.Series("_default", index=req.data.index)
        group_names = ["_default"]

    # ── 前端分组筛选支持 ──
    all_group_names = list(group_names)  # 2026-08-21 #F2：全量分组（metadata 供筛选栏常驻）
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        group_names = [g for g in group_names if str(g) in filter_set]
        if not group_names:
            group_names = sorted(group_vals.dropna().unique())

    return group_vals, group_names, has_groups, y_col, all_group_names
