"""角色识别与请求/历史行拆分（原 inverse.py，2026-09-21 拆分）。"""

from dataclasses import dataclass, field

import pandas as pd

from smartsuite.engine.inverse._params import _str_param

DEFAULT_PREFIXES = {
    "incoming": ("incoming", "来料"),
    "variable": ("variable", "变量", "可调"),
    "fixed": ("fixed", "固定"),
    "output": ("output", "输出"),
    "target": ("target", "目标"),
}


@dataclass
class RoleMap:
    incoming: list[str] = field(default_factory=list)
    variable: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    target: list[str] = field(default_factory=list)
    time: str | None = None


def _split_param_cols(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _match_by_prefix(columns, prefixes) -> list[str]:
    lowered = [(c, str(c).lower()) for c in columns]
    return [c for c, low in lowered if low.startswith(tuple(p.lower() for p in prefixes))]


def _resolve_roles(df: pd.DataFrame, params: dict) -> RoleMap:
    roles = RoleMap()
    for role, prefixes in DEFAULT_PREFIXES.items():
        explicit = _split_param_cols(params.get(f"{role}_cols"))
        cols = explicit if explicit else _match_by_prefix(df.columns, prefixes)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"参数指定的{role}_cols列不存在: {missing}")
        setattr(roles, role, cols)
    time_col = _str_param(params, "time_col", "")
    if time_col and time_col not in df.columns:
        raise ValueError(f"参数指定的 time_col 列不存在: {time_col}")
    roles.time = time_col or None
    if not roles.output:
        raise ValueError(f"未识别到输出列（前缀 output/输出），可用列: {list(df.columns)[:10]}")
    if not roles.incoming and not roles.variable:
        raise ValueError("未识别到来料列与可调参数列，请通过 params 指定")
    for col in set(roles.incoming + roles.variable + roles.fixed + roles.output + roles.target):
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return roles


def _split_rows(df: pd.DataFrame, roles: RoleMap):
    """行分类：历史行（变量+输出完整）/ 请求行（变量留空 + 来料完整 + 目标可用）。

    请求行的目标可用 = 输出列完整 **或** target 角色列存在取值（审查 2026-09-13
    C-1：此前只认输出列，target_cols 通道被架空）；逐输出的目标优先级在解算
    循环中仍为 target 列优先、输出列回退。
    """
    var_cols = roles.variable + (
        [roles.time] if roles.time and roles.time not in roles.variable else []
    )
    has_vars = df[var_cols].notna().all(axis=1) if var_cols else pd.Series(False, index=df.index)
    out_ok = df[roles.output].notna().all(axis=1)
    target_ok = (
        df[roles.target].notna().any(axis=1) if roles.target else pd.Series(False, index=df.index)
    )
    incoming_ok = (
        df[roles.incoming].notna().all(axis=1)
        if roles.incoming
        else pd.Series(True, index=df.index)
    )
    history = df[has_vars & out_ok]
    request = df[(~has_vars) & incoming_ok & (out_ok | target_ok)]
    skipped = []
    for idx in df.index:
        if idx in history.index or idx in request.index:
            continue
        reasons = []
        if not out_ok.loc[idx] and not target_ok.loc[idx]:
            reasons.append("缺少输出值或目标值")
        if not incoming_ok.loc[idx]:
            reasons.append("缺少来料条件")
        if not reasons:
            reasons.append("行类型无法判定（变量与输出组合不完整）")
        skipped.append((int(idx), "; ".join(reasons)))
    return history, request, skipped
