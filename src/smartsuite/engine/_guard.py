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

    ## 计数口径：`NaN` **计入**（`np.isfinite` 语义）

    契约依据 `boundary-contract.md` §B0–B3：

        | B1 | 清洗 | 可安全移除后继续 | 移除 + messages 披露**数量与列名** | `NaN`、`±Inf` |

    即 B1 的对象**同时包含 NaN 与 ±Inf**，两者都要披露数量与列名。

    ⚠️ 我曾在 2026-10-09 把这里改成"只计 ±Inf"，理由是"NaN 属缺失语义、
    应由 dropna 处理"。**那是错的** —— 契约明示 B1 含 NaN，且
    `tests/engine/test_boundary_guard.py` 有两条用例（`test_counts_non_finite` /
    `test_nan_is_treated_as_non_finite`）正是钉住这一点。已回退。

    相应地，`non_finite_detail` 的文案必须**同时提到 NaN 与 ±Inf**
    （原文案只说"±Inf 视为缺失"，与计数不符 —— 这才是真缺陷）。
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
    # ⚠️ 文案必须与 `partition_finite` 的计数口径一致：该函数用 `np.isfinite`，
    # **NaN 与 ±Inf 都计入**（契约 `boundary-contract.md` B1 明示两者皆属 B1）。
    # 原文案只写「±Inf 视为缺失」，而实际数字里含 NaN → 披露的"名"与"量"不符。
    # 2026-10-09 修正为同时点名两者。
    return f"⚠ {where}含 {n_dropped} 个非有限值（NaN 或 ±Inf），已剔除后分析"


def clean_series(
    s: pd.Series, *, column: str = "", report: BoundaryReport | None = None
) -> tuple[pd.Series, int]:
    """B1 单列清洗：剔除 **NaN 与 ±Inf 两者**（`np.isfinite` 语义）。

    ⚠️ 原 docstring 写「NaN 视为缺失，交由调用方的 dropna 处理」——**与实现不符**
    （审查 2026-10-09 P2-2）：实测 `clean_series(pd.Series([1.0, nan, 2.0, inf]))`
    返回 `[1.0, 2.0]`、`n_dropped=2`，NaN 一并丢弃。口径以本模块顶部
    `partition_finite` 的权威说明为准（契约 `boundary-contract.md` B1 行明示
    B1 的清洗对象是「`NaN`、`±Inf`」）。

    与已删除的 `engine/_utils.drop_non_finite` 语义一致；
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
    frame: pd.DataFrame,
    cols: list[str],
    *,
    report: BoundaryReport | None = None,
    drop_nan: bool = True,
) -> tuple[pd.DataFrame, int]:
    """B1 多列清洗：按行剔除 cols 中任一列非有限的行。cols 须为数值列。

    `drop_nan=False` 时**只**剔除 ±Inf，NaN 留在原处交由调用方既有的缺失语义处理。
    为什么需要这个开关：`root_cause/correlation.py` 的 `.corr()` 用 pandas 的
    "**成对完整观测**"口径 —— 若在此按行剔除 NaN，一个因子列缺失较多就会把
    整表压成极小样本（实测把「逐因子跳过」退化为「整表样本不足」，
    见 `tests/engine/test_correlation_partial.py::test_insufficient_samples_skimmed_per_factor`）。
    两种模式**都产出披露**，区别只在文案里点名的对象（`±Inf` 或 `NaN 或 ±Inf`）。
    """
    if not cols:
        return frame, 0
    try:
        arr = frame[cols].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError):
        return frame, 0
    mask = np.isfinite(arr).all(axis=1) if drop_nan else (~np.isinf(arr)).all(axis=1)
    n_dropped = int((~mask).sum())
    if n_dropped and report is not None:
        kinds = "NaN 或 ±Inf" if drop_nan else "±Inf"
        report.add(
            BoundaryIssue(
                level="B1",
                code="E_DATA_NON_FINITE_DROPPED",
                detail=f"⚠ 数据含 {n_dropped} 行非有限值（{kinds}），已剔除后分析",
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


def _degenerate_column_code(s: pd.Series) -> str | None:
    """退化列的**单一**归因实现（顺序不可颠倒）：空列 → 样本不足 → 常量 → 有变异。

    抽出来的理由（审查 2026-10-09 P2-3）：`check_non_constant` 与
    `explain_undefined_sigma` 对**同一输入**曾给出矛盾错误码
    （全 NaN 列：前者「常量列（无变异）」/ 后者「有效观测不足 2 个」）——
    同文件两处各写一份判据，就必然漂移。
    """
    n_valid = int(s.notna().sum())
    if n_valid == 0:
        return "E_DATA_EMPTY_COLUMN"
    if n_valid < 2:
        return "E_DATA_INSUFFICIENT_N"
    if s.nunique(dropna=True) <= 1:
        return "E_DATA_CONSTANT_COLUMN"
    return None


def check_non_constant(
    s: pd.Series, *, what: str = "", report: BoundaryReport | None = None
) -> BoundaryIssue | None:
    """B0 退化列检查：按「整列为空 → 样本不足 → 常量」三段归因（顺序不可颠倒）。

    契约 `boundary-contract.md` 边界清单 #5/#6/#7 要求三种情形**给出不同错误码**：

    | 情形 | `code` | 文案要点 |
    |---|---|---|
    | 全为 NaN（无任何有效值） | `E_DATA_EMPTY_COLUMN` | 「整列为空」（区别于"样本不足"） |
    | 恰好 1 个有效值 | `E_DATA_INSUFFICIENT_N` | 「有效观测不足 2 个」 |
    | ≥2 个有效值且唯一值 ≤ 1 | `E_DATA_CONSTANT_COLUMN` | 「常量列（无变异）」 |

    ⚠️ 原实现把**全 NaN 列**也判为「常量列（无变异）」——与同模块
    `explain_undefined_sigma` 对同一输入给的「有效观测不足 2 个」自相矛盾，
    且用户按"常量列"去排查一个空列永远查不到原因（审查 2026-10-09 P2-3）。
    现两处共用 `_degenerate_column_code`，结构上不可能再漂移。

    注意与 `check_degenerate_numeric` 的分工：本函数**只**判列内容，
    不对 NaN 化的统计量做推断（避免把「含 Inf 导致 σ=NaN」误判为常量）。
    """
    label = what or "目标列"
    code = _degenerate_column_code(s)
    if code is None:
        return None
    if code == "E_DATA_EMPTY_COLUMN":
        detail = f"{label}整列为空（没有任何有效观测），无法进行任何统计计算"
    elif code == "E_DATA_INSUFFICIENT_N":
        n_valid = int(s.notna().sum())
        detail = f"{label}有效观测不足 2 个（当前 {n_valid} 个），无法估计标准差"
    else:
        detail = f"{label}为常量列（无变异），无法估计标准差"
    issue = BoundaryIssue(level="B0", code=code, detail=detail)
    if report is not None:
        report.add(issue)
    return issue


#: 量级上界（`log10(max|s|)`）：|y| ≳ 1e154 时 `Σy²` 在 float64 下溢出为 Inf，
#: 检验统计量随之变 NaN，判决静默翻转（审查 2026-10-09 P1-4）。
#: 取 1e150 留出安全余量 —— 工程数据的量级不可能接近该值。
_MAX_ABS_LOG10 = 150.0


def check_magnitude(
    s: pd.Series, *, what: str = "", report: BoundaryReport | None = None
) -> BoundaryIssue | None:
    """B0 量级上界守卫：`log10(max|s|) > 150` 即拒绝（`E_SCALE_EXTREME_MAGNITUDE`）。

    为什么需要：微尺度（量纲下界）方向已按历史 P0 系统性加固（相对阈值），
    **量纲上界此前未设任何守卫**。实测同一构造数据仅乘 `1e300`（相对关系不变）：
    `normality_check` / `spc_nonparametric` / `doe_analysis` / `outlier_consensus`
    等任务的**结论级翻转**，另有多任务把 inf/nan 直接写进结果表。

    根因是 `Σy²` 在 `|y| ≳ 1e154` 时溢出为 `inf`，随后 NaN 被"False 分支"
    或"NaN 原样入表"处置 —— 两种都不会报错，用户看到一个假的结论。

    本函数**只判断、不替调用方决定**（与模块内其他原语一致）：调用方拿到
    issue 后应 B0 拒绝并披露。返回 `None` 表示量级正常（含空列/非数值列 ——
    那些由 `check_non_constant` 负责）。
    """
    try:
        arr = np.asarray(s, dtype=float)
    except (TypeError, ValueError):
        return None
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    peak = float(np.max(np.abs(finite)))
    if peak == 0.0 or np.log10(peak) <= _MAX_ABS_LOG10:
        return None
    label = what or "数据"
    issue = BoundaryIssue(
        level="B0",
        code="E_SCALE_EXTREME_MAGNITUDE",
        detail=(
            f"{label}数值量级过大（最大绝对值 ≈ {peak:.3g}，超过 1e{int(_MAX_ABS_LOG10)}）："
            f"平方和会溢出为 Inf，使检验统计量与模型系数不可估计。"
            f"请先做单位换算或中心化后重试"
        ),
    )
    if report is not None:
        report.add(issue)
    return issue


def non_finite_tables(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """扫描结果表：返回 `{表名: 非有限值个数}`（只统计数据框的数值列）。

    这是**诊断计数**，不是判决判据 —— 判决见 `degenerate_tables`。
    """
    bad: dict[str, int] = {}
    for name, frame in (tables or {}).items():
        if not isinstance(frame, pd.DataFrame):
            continue
        try:
            arr = frame.select_dtypes(include=[np.number]).to_numpy(dtype=float)
        except (TypeError, ValueError):
            continue
        if arr.size == 0:
            continue
        n_bad = int((~np.isfinite(arr)).sum())
        if n_bad:
            bad[name] = n_bad
    return bad


def degenerate_tables(tables: dict[str, pd.DataFrame]) -> dict[str, str]:
    """结果表**不可用**的判据（唯一实现）：`{表名: 原因}`。

    为什么不能"见到 NaN 就拒绝"：本仓的哨兵契约把 `NaN` 定义为"**无法判定**"
    这一合法出口（例：`doe_analysis` 在完全共线时把 `t值/p值` 写成 NaN +
    「无法判定」，`tests/guards/test_micro_scale_guards.py` 有专门用例钉住它）。
    见到 NaN 一律报错会把**已固化的正确语义**改坏。

    故判据只有两条：

    1. **含 `±Inf`** —— Inf 从不是合法哨兵（既非"缺失"也非"无法判定"），
       出现在结果表里必然是溢出/发散；
    2. **数值块全部非有限** —— 模型一个参数都没估出来（等价于"没有结果"）。

    只有"某个 NaN"既不算 (1) 也不算 (2)，照常放行。
    """
    bad: dict[str, str] = {}
    for name, frame in (tables or {}).items():
        if not isinstance(frame, pd.DataFrame):
            continue
        try:
            arr = frame.select_dtypes(include=[np.number]).to_numpy(dtype=float)
        except (TypeError, ValueError):
            continue
        if arr.size == 0:
            continue
        n_inf = int(np.isinf(arr).sum())
        n_finite = int(np.isfinite(arr).sum())
        if n_inf:
            bad[name] = f"含 {n_inf} 个 ±Inf（溢出/发散，不是合法哨兵）"
        elif n_finite == 0:
            bad[name] = f"全部 {arr.size} 个数值均非有限（模型未估计出任何参数）"
    return bad


def check_tables_finite(
    tables: dict[str, pd.DataFrame],
    *,
    what: str = "",
    code: str = "E_NUMERIC_OUTPUT_NON_FINITE",
    report: BoundaryReport | None = None,
) -> BoundaryIssue | None:
    """B0 输出侧后置断言：结果表**退化**（见 `degenerate_tables`）即拒绝。

    与入口清洗互补：`clean_series` / `clean_frame` 管"进来的数据"，
    本函数管"出去的结果"。二者共同保证"非有限值既不静默进、也不静默出"，
    同时**不误伤** NaN 哨兵（"无法判定"必须能如实写进表里）。
    """
    bad = degenerate_tables(tables)
    if not bad:
        return None
    label = what or "分析结果"
    detail = (
        f"{label}不可用（"
        + "；".join(f"「{k}」{v}" for k, v in bad.items())
        + "），已中止以避免给出错误结论"
    )
    issue = BoundaryIssue(level="B0", code=code, detail=detail)
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

    正确做法是按固定优先级归因（**顺序不可颠倒，且实现与此一致**）：

        常量 → 样本量（有效观测 < 2）→ 非有限值 → 兜底

    ⚠️ 本 docstring 曾把 `非有限值` 排在 `样本量` 之前（审查 2026-10-09 P2-2）——
    那是**注释写反**，实现一向是正确的。颠倒顺序会立即产生错误归因：
    「[5.0, NaN]」剔除 NaN 后只剩 1 个有效值，属样本量问题；若先判「含非有限值」
    就会把用户引向错误的排查方向。
    """
    label = what or (f"「{column}」" if column else "数据")
    # 归因优先级与 `check_non_constant` **共用同一实现**（`_degenerate_column_code`）：
    # 常量 → 样本量（有效观测 < 2）→ 非有限值 → 兜底
    code = _degenerate_column_code(values)
    if code == "E_DATA_CONSTANT_COLUMN":
        return BoundaryIssue(
            level="B0",
            code=code,
            detail=f"{label}为常量列（所有观测相同），标准差为 0，无法估计控制限",
            column=column,
        )
    if code == "E_DATA_EMPTY_COLUMN":
        return BoundaryIssue(
            level="B0",
            code=code,
            detail=f"{label}整列为空（没有任何有效观测），无法估计标准差",
            column=column,
        )
    if code == "E_DATA_INSUFFICIENT_N":
        return BoundaryIssue(
            level="B0",
            code=code,
            detail=f"{label}有效观测不足 2 个，无法估计标准差",
            column=column,
        )
    _, n_non_finite = partition_finite(values)
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
