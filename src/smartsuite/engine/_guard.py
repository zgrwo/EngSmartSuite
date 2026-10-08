"""边界处理唯一执行点 — B0–B3 处置契约的落地实现。

契约定义见 `docs/governance/boundary-contract.md`（用户向）与
`sentinel-contract.md`（值级哨兵 L1–L5）。

为什么需要本模块
----------------
第三轮复核（`logs/reports/verify-round3/R3-复核清单.md`）确认的 P0/P1 缺陷有共同根因：
**退化输入的处理散落在各引擎函数里逐份手抄**，于是

- 覆盖不全：`np.isfinite` 清洗只进了 6/12 个相关模块；
- 披露不一：有的模块报「已剔除 N 个非有限值」，有的静默；
- **错误归因**：`+Inf` 让 σ 变成 NaN，模块却报「常量列（标准差为 0）」——
  用户按提示去查常量列，永远查不到原因。

本模块把"清洗 / 下限 / 常量 / 参数有限性"收敛为 4 类函数，任何引擎函数都必须经此处理，
不得再手写掩码（由 `tests/guards/test_boundary_contract.py` 源码级断言守护）。

设计约束
--------
- **零新增依赖**：只用 numpy/pandas（engine 层红线）。
- **不改判定语义**：本模块只做「判断 + 记录」，**不替调用方决定拒绝还是继续**。
  调用方拿到 `issues` 后自行选择 B0（拒绝）或 B1（清洗后继续），以保留各方法
  已有的、经测试固化的边界语义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

Level = Literal["B0", "B1", "B2", "B3"]


@dataclass(frozen=True)
class BoundaryIssue:
    """一条边界处置记录（契约要求 B2/B3 必须能被用户看到）。"""

    level: Level
    code: str
    detail: str
    column: str = ""


@dataclass
class BoundaryReport:
    """一次入口处理的处置汇总 — 供追加到 `AnalysisResult.messages`。"""

    issues: list[BoundaryIssue] = field(default_factory=list)

    def add(self, issue: BoundaryIssue) -> None:
        self.issues.append(issue)

    def messages(self) -> list[str]:
        """转用户可见的中文提示（顺序稳定，去重）。"""
        seen: set[str] = set()
        out: list[str] = []
        for it in self.issues:
            if it.detail in seen:
                continue
            seen.add(it.detail)
            out.append(it.detail)
        return out

    def codes(self) -> list[str]:
        """机器可读错误码（去重，保持顺序）——供 API 消费者与日志关联。"""
        seen: set[str] = set()
        out: list[str] = []
        for it in self.issues:
            if it.code in seen:
                continue
            seen.add(it.code)
            out.append(it.code)
        return out

    def __bool__(self) -> bool:
        return bool(self.issues)


def partition_finite(s: pd.Series) -> tuple[np.ndarray, int]:
    """返回 (有限值掩码, 非有限值个数)。非数值列按"不可判定"报 0。

    这是**唯一**允许出现 `np.isfinite` 掩码的地方（源码守卫会检查其他模块）。
    """
    try:
        arr = s.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError):
        # 非数值列（object/混合）：非有限值概念不适用
        return np.ones(len(s), dtype=bool), 0
    mask = np.isfinite(arr)
    return mask, int((~mask).sum())


def non_finite_detail(n_dropped: int, column: str = "") -> str:
    """**唯一**的非有限值披露文案构造处（B1）。

    第三十六轮提取：此前 `clean_series` 内联拼一份，`spc_charts/xbar_r.py`
    又借 `_utils.non_finite_note` 拼一份**逐字相同**的文案 —— 两份格式独立演化，
    用户会在不同任务里看到格式不一致的同类提示。

    注意 `clean_frame` 的文案是**多列/按行**语义（"含 N 行非有限值"），
    与本函数（单列语义）刻意不同，故不合并。
    """
    where = f"「{column}」" if column else "数据"
    return f"⚠ {where}含 {n_dropped} 个非有限值（±Inf 视为缺失），已剔除后分析"


def clean_series(
    s: pd.Series, *, column: str = "", report: BoundaryReport | None = None
) -> tuple[pd.Series, int]:
    """B1 单列清洗：剔除 ±Inf（NaN 视为缺失，交由调用方的 dropna 处理）。

    与 `engine/_utils.drop_non_finite` 语义一致（后者为既有实现，保留兼容）；
    本函数额外产出 `report`，使**披露**不再依赖调用方记得拼文案。

    Returns:
        (过滤后序列, 剔除个数)
    """
    mask, n_dropped = partition_finite(s)
    if n_dropped and report is not None:
        report.add(
            BoundaryIssue(
                level="B1",
                code="E_DATA_NON_FINITE_DROPPED",
                detail=non_finite_detail(n_dropped, column),
                column=column,
            )
        )
    if not n_dropped:
        return s, 0
    return s[mask], n_dropped


def clean_frame(
    frame: pd.DataFrame, cols: list[str], *, report: BoundaryReport | None = None
) -> tuple[pd.DataFrame, int]:
    """B1 多列清洗：按行剔除 cols 中任一列非有限的行。cols 须为数值列。"""
    if not cols:
        return frame, 0
    try:
        arr = frame[cols].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError):
        return frame, 0
    mask = np.isfinite(arr).all(axis=1)
    n_dropped = int((~mask).sum())
    if n_dropped and report is not None:
        report.add(
            BoundaryIssue(
                level="B1",
                code="E_DATA_NON_FINITE_DROPPED",
                detail=f"⚠ 数据含 {n_dropped} 行非有限值（±Inf 视为缺失），已剔除后分析",
            )
        )
    if not n_dropped:
        return frame, 0
    return frame[mask], n_dropped


def check_n(
    n: int, minimum: int, *, what: str = "", report: BoundaryReport | None = None
) -> BoundaryIssue | None:
    """B0 样本量下限检查。返回 issue（需拒绝）或 None（可继续）。"""
    if n >= minimum:
        return None
    label = what or "有效数据"
    issue = BoundaryIssue(
        level="B0",
        code="E_DATA_INSUFFICIENT_N",
        detail=f"{label}不足：至少需要 {minimum} 个观测值（当前 {n} 个）",
    )
    if report is not None:
        report.add(issue)
    return issue


def check_non_constant(
    s: pd.Series, *, what: str = "", report: BoundaryReport | None = None
) -> BoundaryIssue | None:
    """B0 常量列检查：唯一值 ≤ 1 → 无变异，无法估计标准差。

    注意与 `check_degenerate_numeric` 的分工：本函数**只**判唯一值，
    不对 NaN 化的统计量做推断（避免把「含 Inf 导致 σ=NaN」误判为常量）。
    """
    if s.nunique(dropna=True) > 1:
        return None
    label = what or "目标列"
    issue = BoundaryIssue(
        level="B0",
        code="E_DATA_CONSTANT_COLUMN",
        detail=f"{label}为常量列（无变异），无法估计标准差",
    )
    if report is not None:
        report.add(issue)
    return issue


def check_finite_param(
    value, name: str, *, report: BoundaryReport | None = None
) -> tuple[float | None, BoundaryIssue | None]:
    """B0 参数有限性检查：转 float 并拒绝 NaN/±Inf。

    审查 2026-09-21 D-1 的教训：`x <= 0` 作为「必须为正」的守卫会漏 NaN（比较恒 False）
    与 +Inf。此处统一为显式 isfinite 判定。

    Returns:
        (float 值或 None, issue 或 None)。value 为 None 时返回 (None, None)（未提供）。
    """
    if value is None:
        return None, None
    try:
        num = float(value)
    except (ValueError, TypeError):
        issue = BoundaryIssue(
            level="B0",
            code="E_PARAM_NOT_NUMERIC",
            detail=f"参数「{name}」必须为数值，当前收到 {value!r}",
        )
        if report is not None:
            report.add(issue)
        return None, issue
    if not np.isfinite(num):
        issue = BoundaryIssue(
            level="B0",
            code="E_PARAM_NON_FINITE",
            detail=f"参数「{name}」必须为有限数值（不能为 NaN 或 ±Inf），当前收到 {value!r}",
        )
        if report is not None:
            report.add(issue)
        return None, issue
    return num, None


def explain_undefined_sigma(
    values: pd.Series, *, column: str = "", what: str = ""
) -> BoundaryIssue:
    """σ 不可估计时的**正确归因** — 区分「常量」与「含非有限值」。

    这是本模块存在的首要理由。原反模式：

        if sigma <= 0 or not np.isfinite(sigma):
            return "目标列为常量列（标准差为 0）"     # ← +Inf 数据也走这里，误导

    正确做法是按固定优先级归因（顺序不可颠倒）：

        常量 → 非有限值 → 样本量 → 兜底

    颠倒会立即产生错误归因：「[5.0, NaN]」剔除 NaN 后只剩 1 个有效值，属样本量问题；
    若先判 "含非有限值" 就会把用户引向错误的排查方向。
    """
    label = what or (f"「{column}」" if column else "数据")
    n_valid = int(values.notna().sum())
    # 「常量」需要 ≥2 个有效值来确认。只有 1 个有效值（如 [5.0, NaN]）时
    # 无法断言"所有观测相同"——那是样本量不足，报常量属越权推断。
    if n_valid >= 2 and values.nunique(dropna=True) <= 1:
        return BoundaryIssue(
            level="B0",
            code="E_DATA_CONSTANT_COLUMN",
            detail=f"{label}为常量列（所有观测相同），标准差为 0，无法估计控制限",
            column=column,
        )
    _, n_non_finite = partition_finite(values)
    if n_valid < 2:
        return BoundaryIssue(
            level="B0",
            code="E_DATA_INSUFFICIENT_N",
            detail=f"{label}有效观测不足 2 个，无法估计标准差",
            column=column,
        )
    if n_non_finite:
        return BoundaryIssue(
            level="B0",
            code="E_DATA_NON_FINITE_BLOCKS_SIGMA",
            detail=(
                f"{label}含 {n_non_finite} 个非有限值（±Inf），导致标准差不可估计；请先剔除这些观测"
            ),
            column=column,
        )
    return BoundaryIssue(
        level="B0",
        code="E_NUMERIC_SIGMA_UNDEFINED",
        detail=f"{label}的标准差不可估计（非上述已知原因），请检查数据完整性",
        column=column,
    )
