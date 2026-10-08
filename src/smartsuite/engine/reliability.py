"""可靠性与测量系统分析模块：Gage R&R、容差区间、生存分析。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Finite, Opt, Spec
from smartsuite.engine._constants import EPSILON
from smartsuite.engine._guard import BoundaryReport, clean_frame, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    round_for_display,
)

logger = logging.getLogger(__name__)

# --- 声明式参数契约（P4 步骤③，第二十五轮）---
# 契约：docs/governance/improvement-plan.md 第六节
# 按**任务**登记（本模块含 gage_rr / tolerance_interval / survival_analysis 等）。
# 枚举逐任务声明（不进共享库）：本模块的 `side` 是**容差区间方向**，
# 与 `spc_nonparametric` 的 `side` 字面相同但语义不同 —— 共享会互相牵连。
PARAM_SPECS = {
    "tolerance_interval": Spec(
        coverage=Opt(
            Finite(gt=0, lt=1),
            default=0.99,
            label="覆盖比例",
            hint="要以给定置信度覆盖的总体比例；必须在 (0,1) 开区间内",
        ),
        confidence=Opt(
            Finite(gt=0, lt=1),
            default=0.95,
            label="置信水平",
            hint="区间估计的置信度；必须在 (0,1) 开区间内",
        ),
        side=Opt(
            Choice(
                ("two-sided", "双侧"),
                ("upper", "单侧上限"),
                ("lower", "单侧下限"),
            ),
            default="two-sided",
            label="区间方向",
            hint="双侧=同时给出上下限；单侧用于只关心一个方向的情形",
        ),
    ),
    "gage_rr": Spec(
        # 第三十轮（三个待决策项之二）：**补实现 %P/T**。
        #
        # 取证：`api-reference.md` 列出 `tolerance`，引擎 docstring 写
        # 「公差范围 (用于 %P/T 计算，可选)」，但 AST 扫描证实 `gage_rr()`
        # **完全不读它**，`metadata` 里也没有任何 `%P/T`。而 `%P/T`
        # （precision-to-tolerance）是 AIAG 的标准指标。
        # 文档已承诺 → 按「补实现」处理，而非删参数。
        #
        # 它现在真的被读了，故必须校验：公差是**正的有限数**
        # （0 或负数会让 %P/T 无意义 / 除零；此前透传时这些值会被静默接受）。
        tolerance=Opt(
            Finite(gt=0),
            default=None,
            label="公差范围",
            hint="规格上限−下限；给出后才计算 %P/T（量具变异占公差带的比例）",
        ),
        sigma_multiplier=Opt(
            Finite(gt=0),
            default=5.15,
            label="研究变异乘数",
            hint="5.15 = 99% 研究变异（AIAG 惯例）；须为正的有限数",
        ),
        part_col=Opt(
            default=None,
            label="部件列",
            hint="留空则取第一个因子列",
        ),
        operator_col=Opt(
            default=None,
            label="操作员列",
            hint="留空则取第二个因子列",
        ),
    ),
}


# ── AIAG MSA 4th d2* 表（Round-2 #A3f）──
# 行 = g（操作员数），列 = m（零件数×重复次数）；超表范围取最近值/∞列近似。
# AV 分量必须用 d2*（g=操作员数行）；PV 的 g=1 行即普通 d2。
_D2_STAR_ROWS: dict[int, list[tuple[int, float]]] = {
    2: [
        (2, 1.19),
        (3, 1.24),
        (4, 1.26),
        (5, 1.27),
        (6, 1.28),
        (8, 1.29),
        (10, 1.30),
        (15, 1.31),
        (20, 1.31),
        (25, 1.32),
        (100, 1.41),
    ],
    3: [
        (2, 1.55),
        (3, 1.72),
        (4, 1.78),
        (5, 1.81),
        (6, 1.83),
        (8, 1.85),
        (10, 1.87),
        (15, 1.88),
        (20, 1.89),
        (25, 1.89),
        (100, 1.91),
    ],
    4: [
        (2, 1.68),
        (3, 1.92),
        (4, 2.04),
        (5, 2.10),
        (6, 2.14),
        (8, 2.18),
        (10, 2.20),
        (15, 2.23),
        (20, 2.24),
        (25, 2.25),
        (100, 2.24),
    ],
    5: [
        (2, 1.75),
        (3, 2.04),
        (4, 2.21),
        (5, 2.31),
        (6, 2.37),
        (8, 2.44),
        (10, 2.48),
        (15, 2.52),
        (20, 2.54),
        (25, 2.55),
        (100, 2.48),
    ],
    6: [
        (2, 1.79),
        (3, 2.12),
        (4, 2.32),
        (5, 2.45),
        (6, 2.54),
        (8, 2.64),
        (10, 2.70),
        (15, 2.76),
        (20, 2.79),
        (25, 2.81),
        (100, 2.67),
    ],
    7: [
        (2, 1.82),
        (3, 2.17),
        (4, 2.40),
        (5, 2.55),
        (6, 2.66),
        (8, 2.79),
        (10, 2.87),
        (15, 2.95),
        (20, 2.99),
        (25, 3.02),
        (100, 2.83),
    ],
    8: [
        (2, 1.84),
        (3, 2.20),
        (4, 2.46),
        (5, 2.63),
        (6, 2.75),
        (8, 2.91),
        (10, 3.00),
        (15, 3.10),
        (20, 3.15),
        (25, 3.19),
        (100, 2.96),
    ],
    9: [
        (2, 1.86),
        (3, 2.23),
        (4, 2.50),
        (5, 2.69),
        (6, 2.82),
        (8, 3.01),
        (10, 3.12),
        (15, 3.24),
        (20, 3.30),
        (25, 3.35),
        (100, 3.08),
    ],
    10: [
        (2, 1.87),
        (3, 2.26),
        (4, 2.54),
        (5, 2.74),
        (6, 2.88),
        (8, 3.09),
        (10, 3.22),
        (15, 3.36),
        (20, 3.43),
        (25, 3.49),
        (100, 3.18),
    ],
}


def _d2_star_infty(g: int) -> float:
    """AIAG d2* 表 g 行的 m→∞ 列 — AV 分量专用（K2 = 5.15/d2*∞）。

    审查 2026-09-05 B2：AIAG MSA 4 版 p.225 的 K2 常数（2 操作员→3.65=5.15/1.41、
    3→2.70、4→2.30）只随操作员数变化，不随零件数/重复次数变化。此前按
    m=零件数×重复次数 取有限列（如 n_obs=20 → 1.31 < 1.41）使 2 操作员小样本
    AV 高估 8–11%（statsmodels ANOVA 交叉实测，方向=从严）。
    g>10 时按 10 行近似（差异 <1%），调用方记录日志。
    """
    if g < 2:
        # g=1（单组）即普通 d2 语义——由调用方处理
        return float(g)
    if g > 10:
        logger.info("操作员数 g=%d > 10，d2* 按 g=10 行近似", g)
    row = _D2_STAR_ROWS.get(min(g, 10), _D2_STAR_ROWS[10])
    return float(row[-1][1])


def _anova_variance_components(
    grp_means: np.ndarray,
    part_means: np.ndarray,
    op_means: np.ndarray,
    n_parts: int,
    n_ops: int,
    r: int,
    pooled_threshold: float = 0.05,
) -> dict | None:
    """Gage R&R 的 ANOVA 方差分解（交叉设计，操作员与零件均为随机效应）。

    参数：
        grp_means  形状 (n_parts, n_ops, r) —— 每个 (零件, 操作员) 单元的重复观测
        part_means 形状 (n_parts,) —— 各零件的全观测均值
        op_means   形状 (n_ops,)   —— 各操作员的全观测均值（按零件等权）

    ## 模型与期望均方

        y_ijk = mu + part_i + op_j + (part×op)_ij + e_ijk
        独立正态、零均值；σ²_part / σ²_op / σ²_int / σ²_e（重复性）

        df_part = n−1,  df_op = k−1,  df_int = (n−1)(k−1),  df_e = nk(r−1)

        E[MS_part] = σ²_e + r·σ²_int + k·r·σ²_part
        E[MS_op]   = σ²_e + r·σ²_int + n·r·σ²_op
        E[MS_int]  = σ²_e + r·σ²_int
        E[MS_e]    = σ²_e

    由期望均方反解即得**无偏**估计量（本函数）—— 这也是测试中无偏性断言的依据。

    ## 为什么默认不合并交互

    统计上常见做法是"交互不显著则并入误差以提高功效"。但 AIAG MSA 的
    **随机效应**口径要求保留交互项，否则 σ²_e 的估计有偏（把交互算成重复性，
    这正是均值-极差法的老问题）。故两者都算：

      - `components`        = 保留交互（AIAG 口径，给用户看的默认数值）
      - `components_pooled` = 交互不显著时合并（自由度更大，供参考）

    负分量按惯例截断为 0（方差非负），并在 `negative_components` 中登记。

    返回 None 表示设计退化（某个自由度 ≤0），调用方应跳过 ANOVA 分量。
    """
    if n_parts < 2 or n_ops < 2 or r < 2:
        return None

    cell_means = grp_means.mean(axis=2)  # (n, k)
    grand = float(np.mean(grp_means))
    ss_part = float(n_ops * r * ((part_means - grand) ** 2).sum())
    ss_op = float(n_parts * r * ((op_means - grand) ** 2).sum())
    ss_int = float(r * ((cell_means - part_means[:, None] - op_means[None, :] + grand) ** 2).sum())
    ss_e = float(((grp_means - cell_means[:, :, None]) ** 2).sum())

    df_part = n_parts - 1
    df_op = n_ops - 1
    df_int = df_part * df_op
    df_e = n_parts * n_ops * (r - 1)
    if df_int <= 0 or df_e <= 0:
        return None

    ms_part = ss_part / df_part
    ms_op = ss_op / df_op
    ms_int = ss_int / df_int
    ms_e = ss_e / df_e

    def f_test(num: float, den: float, df1: int, df2: int) -> tuple[float, float]:
        """F 与 p 值。退化输入（分母为 0 / 非有限 / F 非正）给 F=0、p=1。

        `p=1` 表示"不得显著"，是退化情形下唯一安全的方向：宁可漏报显著，
        不可把"无变异"报成"显著差异"。
        """
        if den <= 0 or not np.isfinite(den) or not np.isfinite(num):
            return 0.0, 1.0
        f = num / den
        if not np.isfinite(f) or f <= 0:
            return 0.0, 1.0
        return float(f), float(sp_stats.f.sf(f, df1, df2))

    f_part, p_part = f_test(ms_part, ms_int, df_part, df_int)
    f_op, p_op = f_test(ms_op, ms_int, df_op, df_int)
    f_int, p_int = f_test(ms_int, ms_e, df_int, df_e)

    # 无偏方差分量（保留交互，AIAG 随机效应口径）
    var_int = (ms_int - ms_e) / r
    var_part = (ms_part - ms_int) / (n_ops * r)
    var_op = (ms_op - ms_int) / (n_parts * r)
    var_e = ms_e

    def clamp(v: float) -> tuple[float, bool]:
        if not np.isfinite(v) or v < 0:
            return 0.0, True
        return float(v), False

    v_int, neg_int = clamp(var_int)
    v_part, neg_part = clamp(var_part)
    v_op, neg_op = clamp(var_op)
    v_e, neg_e = clamp(var_e)

    # ── 单侧 95% 置信区间（Satterthwaite 有效自由度）──
    # 重复性精确：df_e·MS_e/σ²_e ~ χ²(df_e)
    lo_e = df_e * ms_e / sp_stats.chi2.ppf(0.975, df_e) if ms_e > 0 else 0.0
    hi_e = df_e * ms_e / sp_stats.chi2.ppf(0.025, df_e) if ms_e > 0 else 0.0

    def satterthwaite_ci(est: float, terms: list[tuple[float, float, int]]) -> tuple[float, float]:
        """由若干独立均方的线性组合构造近似 95% CI（Satterthwaite 有效自由度）。

        `terms` 为 (系数, 均方, 自由度) 列表。有效自由度 `df_eff = est²/Σ((c·MS)²/df)`；
        区间 `[df_eff·est/χ²_{0.975}, df_eff·est/χ²_{0.025}]`。

        估计为负（已截断为 0）时**不构造区间**（返回 `(0, 0)`）：截断样本的
        分布性质与 Satterthwaite 近似的前提不符，给出数值反而误导用户。
        """
        if est <= 0:
            return 0.0, 0.0
        denom = sum((c * ms) ** 2 / df for c, ms, df in terms)
        if denom <= 0 or not np.isfinite(denom):
            return 0.0, 0.0
        df_eff = est**2 / denom
        # df_eff 过小（<1e-6）时 χ² 分位数在数值上退化为 0 → 除零。
        # 这种情形出现在分量极小且 (MS − MS) 几乎相消时，区间无统计意义 → 返回 (0,0)。
        if not np.isfinite(df_eff) or df_eff < 1e-6:
            return 0.0, 0.0
        chi_lo = float(sp_stats.chi2.ppf(0.975, df_eff))
        chi_hi = float(sp_stats.chi2.ppf(0.025, df_eff))
        if chi_lo <= 0 or chi_hi <= 0:
            return 0.0, 0.0
        lo = df_eff * est / chi_lo
        hi = df_eff * est / chi_hi
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return 0.0, 0.0
        return float(max(0.0, lo)), float(hi)

    ci_int = satterthwaite_ci(var_int, [(1.0 / r, ms_int, df_int), (-1.0 / r, ms_e, df_e)])
    ci_part = satterthwaite_ci(
        var_part,
        [(1.0 / (n_ops * r), ms_part, df_part), (-1.0 / (n_ops * r), ms_int, df_int)],
    )
    ci_op = satterthwaite_ci(
        var_op,
        [(1.0 / (n_parts * r), ms_op, df_op), (-1.0 / (n_parts * r), ms_int, df_int)],
    )

    pooled = bool(np.isfinite(p_int) and p_int >= pooled_threshold)
    if pooled:
        # 交互不显著：并入误差 → 重复性自由度从 df_e 增到 df_e + df_int
        df_e_pooled = df_e + df_int
        ms_e_pooled = (ss_e + ss_int) / df_e_pooled
        v_int_pooled = 0.0
        v_part_pooled = (ms_part - ms_e_pooled) / (n_ops * r)
        v_op_pooled = (ms_op - ms_e_pooled) / (n_parts * r)
    else:
        df_e_pooled = df_e
        ms_e_pooled = ms_e
        v_int_pooled = v_int
        v_part_pooled = v_part
        v_op_pooled = v_op

    v_part_pooled_c, _ = clamp(v_part_pooled)
    v_op_pooled_c, _ = clamp(v_op_pooled)

    return {
        "components": {
            "part": v_part,
            "operator": v_op,
            "interaction": v_int,
            "repeatability": v_e,
        },
        "components_pooled": {
            "part": v_part_pooled_c,
            "operator": v_op_pooled_c,
            "interaction": v_int_pooled,
            "repeatability": float(ms_e_pooled),
        },
        "ci95": {
            "part": ci_part,
            "operator": ci_op,
            "interaction": ci_int,
            "repeatability": (float(lo_e), float(hi_e)),
        },
        "f_tests": {
            "part": {"F": f_part, "p": p_part, "df": (df_part, df_int), "MS": ms_part},
            "operator": {"F": f_op, "p": p_op, "df": (df_op, df_int), "MS": ms_op},
            "interaction": {"F": f_int, "p": p_int, "df": (df_int, df_e), "MS": ms_int},
            "repeatability": {"MS": ms_e, "df": df_e},
        },
        "pooled": pooled,
        "df": {
            "part": df_part,
            "operator": df_op,
            "interaction": df_int,
            "repeatability": df_e,
        },
        "negative_components": {
            "part": neg_part,
            "operator": neg_op,
            "interaction": neg_int,
            "repeatability": neg_e,
        },
    }


def gage_rr(req: AnalysisRequest) -> AnalysisResult:
    """测量系统分析 (Gage R&R) — 评估量具的重复性和再现性。

    数据要求: target_col=测量值, feature_cols 中需含 "部件" 和 "操作员" 列。

    参数:
        part_col: 部件列名 (默认 feature_cols[0])
        operator_col: 操作员列名 (默认 feature_cols[1])
        tolerance: 公差范围 (用于 %P/T 计算，可选)
        sigma_multiplier: 研究变异乘数 (默认 5.15 = 99% 研究变异)
    """
    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P2 fix)
    part_col = req.params.get("part_col")
    if part_col is None:
        part_col = req.feature_cols[0] if len(req.feature_cols) > 0 else None
    operator_col = req.params.get("operator_col")
    if operator_col is None:
        operator_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None
    if not part_col or not operator_col:
        return AnalysisResult(task="gage_rr", status="error", messages=["需要提供部件列和操作员列"])

    sub = req.data[[req.target_col, part_col, operator_col]].dropna()
    # 审查 2026-09-22 发现 3：±Inf 使 GRR 分量为 NaN，`int(1.41*pv/grr)` 抛
    # ValueError: cannot convert float NaN to integer；入口按缺失剔除
    # 第三十七轮：手抄清洗 → `_guard.clean_frame`
    _report = BoundaryReport()
    sub, _n_inf = clean_frame(sub, [req.target_col], report=_report)
    if len(sub) < 10:
        return AnalysisResult(task="gage_rr", status="error", messages=["有效数据不足"])

    parts = sub[part_col].unique()
    operators = sub[operator_col].unique()
    k = len(operators)
    n_parts = len(parts)
    if n_parts < 2:
        return AnalysisResult(
            task="gage_rr",
            status="error",
            messages=["至少需要 2 个不同部件才能评估部件间变异 (PV)"],
        )

    # 每部件每操作员的重复次数
    rep_counts = sub.groupby([part_col, operator_col]).size()
    r = int(rep_counts.mode().iloc[0]) if len(rep_counts) > 0 else 1

    # X-bar and R method
    # 每个操作员的 R-bar 和 X-bar
    op_stats = []
    for op in operators:
        op_data = sub[sub[operator_col] == op]
        ranges = op_data.groupby(part_col)[req.target_col].apply(lambda x: x.max() - x.min())
        r_bar_op = float(ranges.mean())
        x_bar_op = float(op_data[req.target_col].mean())
        op_stats.append({"操作员": op, "R-bar": r_bar_op, "X-bar": x_bar_op})

    # R-double-bar (average of operator R-bars)
    r_double_bar = float(np.mean([s["R-bar"] for s in op_stats]))
    x_bar_diff = float(
        np.max([s["X-bar"] for s in op_stats]) - np.min([s["X-bar"] for s in op_stats])
    )

    # d2 constants for subgroup size r (ASTM E2282 / AIAG MSA standard table)
    d2_table = {
        2: 1.128,
        3: 1.693,
        4: 2.059,
        5: 2.326,
        6: 2.534,
        7: 2.704,
        8: 2.847,
        9: 2.970,
        10: 3.078,
        11: 3.173,
        12: 3.258,
        13: 3.336,
        14: 3.407,
        15: 3.472,
        16: 3.532,
        17: 3.588,
        18: 3.640,
        19: 3.689,
        20: 3.735,
        21: 3.778,
        22: 3.819,
        23: 3.858,
        24: 3.895,
        25: 3.931,
        26: 3.964,
        27: 3.997,
        28: 4.027,
        29: 4.056,
        30: 4.084,
    }
    d2_r = d2_table.get(r)
    if d2_r is None:
        # r=1 时无法估计重复性（极差未定义），回退到 r=2 的 d2=1.128
        # 并给出明确警告
        if r < 2:
            d2_r = 1.128
            logger.warning(
                "Gage R&R 重复次数 r=%d < 2，d2 使用回退值 %.3f (按 r=2 处理)。"
                "建议至少重复测量 2 次以获得可靠的重复性估计。",
                r,
                d2_r,
            )
        else:
            # r > 30: 使用 Blom 近似公式 d2 ≈ 2 · Φ⁻¹((n-0.375)/(n+0.25))
            # 参考: Harter (1960), ASTM E2282。该公式在 n>30 时比 chi 分布均值
            # 近似（√2·Γ((n+1)/2)/Γ(n/2)）更准确（误差 <0.5% vs ~35%）
            _blom_arg = (r - 0.375) / (r + 0.25)
            d2_r = float(2.0 * sp_stats.norm.ppf(_blom_arg))
            logger.info(
                "Gage R&R 重复次数 r=%d > 30，d2 使用 Blom 近似 %.3f（标准表仅覆盖 2-30）", r, d2_r
            )

    # 参数校验（P4 步骤③，第二十五/三十轮）：失败时抛 ParamValidationError。
    # `sigma_multiplier` 与 `tolerance` 一次取用（后者自第三十轮起真的参与 %P/T）。
    _tr = PARAM_SPECS["gage_rr"].validate_or_raise(req.params)
    sigma_mult = _tr.sigma_multiplier
    # 原「审查 2026-09-01 N-2：float("nan")/float("inf") 不抛异常，需显式拒绝」
    # 守卫已由 `Finite(gt=0)` 前置表达（同时覆盖 NaN/Inf/非正数），故不再重复。

    # Repeatability (EV)
    ev = r_double_bar / d2_r
    ev_pct = ev * sigma_mult

    # Reproducibility (AV)
    n_obs = n_parts * r
    # Round-2 #A3f：AIAG MSA 要求操作员分量用 d2*（g=操作员数 行）而非普通 d2——
    # 普通 d2 使 AV 系统性高估（k=2 时约 25%）；PV 的 g=1 行即普通 d2，无需改
    # 审查 2026-09-05 B2：d2* 取 g 行 m→∞ 列（K2=5.15/d2*∞ 只随操作员数变化），
    # 不再按 m=n_obs 取有限列
    d2_o = _d2_star_infty(k)
    av = np.sqrt(max(0, (x_bar_diff / d2_o) ** 2 - ev**2 / n_obs))
    av_pct = av * sigma_mult

    # GRR
    grr = np.sqrt(ev**2 + av**2)
    grr_pct = grr * sigma_mult

    # Part Variation (PV)
    part_means = sub.groupby(part_col)[req.target_col].mean()
    rp = float(part_means.max() - part_means.min())
    d2_p = d2_table.get(n_parts)
    if d2_p is None:
        # 使用 Blom 近似公式（与 d2_r 一致）
        _blom_arg = (n_parts - 0.375) / (n_parts + 0.25)
        d2_p = float(2.0 * sp_stats.norm.ppf(_blom_arg))
    pv = rp / d2_p
    pv_pct = pv * sigma_mult

    # Total Variation
    tv = np.sqrt(grr**2 + pv**2)
    # 审查 2026-09-16 D-1：原 `tv < EPSILON`（绝对 1e-10）把微尺度测量数据误判
    # 零变异拒绝；只有总变异精确为 0（所有读数全同）才无法评估
    if tv == 0:
        return AnalysisResult(
            task="gage_rr",
            status="error",
            messages=[
                "所有测量值完全一致（零变异），无法评估测量系统。"
                "请检查数据：可能量具精度不足、数据录入错误或过程变异为零。"
            ],
        )
    tv_pct = tv * sigma_mult

    # % contribution
    ev_contrib = (ev**2 / tv**2) * 100
    av_contrib = (av**2 / tv**2) * 100
    grr_contrib = (grr**2 / tv**2) * 100
    pv_contrib = (pv**2 / tv**2) * 100

    # % Study Variation (%SV)
    grr_sv = (grr / tv) * 100
    ev_sv = (ev / tv) * 100
    av_sv = (av / tv) * 100

    # ── %P/T（precision-to-tolerance，AIAG 标准指标）──────────────────────
    # 审查 2026-09-24（第三十轮）：`tolerance` 此前**从不被读取** ——
    # api-reference 列出了它、本函数 docstring 也写「用于 %P/T 计算」，
    # 但 AST 扫描证实无人读，结果里也没有 %P/T。文档已承诺，故补实现。
    #
    # 定义（**已对权威出处核实**）：
    #   JMP《Gauge RR Option》——「a % of Tolerance column ... computed as
    #   100*(Variation/Tolerance)」，其中 Variation = k·σ（k 默认 6）
    #   https://www.jmp.com/support/help/13-2/Gauge_RR_Option.shtml
    # 故 %P/T = 100·(6·σ_GRR / 公差)，分子取 **GRR 的 σ**（不是总变异 σ）。
    # 与 %SV 的区别在**分母**：
    #   · %SV 用研究变异（6σ_total）→ 回答「量具变异占过程变异的比例」；
    #   · %P/T 用公差带 → 回答「量具变异占允许公差的多少」，更贴近客户要求。
    # 两者可给出不同判定（过程变异远小于公差时 %SV 大而 %P/T 小），故都报。
    tolerance = _tr.tolerance
    pt_ratio: float | None = None
    pt_percent: float | None = None
    if tolerance is not None:
        pt_ratio = 6.0 * grr / float(tolerance)
        pt_percent = pt_ratio * 100

    # ndc
    ndc = int(1.41 * pv / grr) if grr > 0 else 99

    # ── ANOVA 方差分解（P2-1，2026-09-24）──
    # 均值-极差法没有交互作用分量；ANOVA 法把变异分成四项，是 AIAG MSA 4 版
    # 认可的等价方法。两法的数值**并列给出**，不互相替换（便于对照与追溯）。
    #
    # 仅在**均衡完整**设计（每个 零件×操作员 单元恰有 r≥2 个观测）下计算：
    # ANOVA 的期望均方公式只在均衡时成立，不均衡时应明确跳过而非给近似值。
    anova: dict | None = None
    grouped = {
        key: np.asarray(vals, dtype=float)
        for key, vals in sub.groupby([part_col, operator_col])[req.target_col]
    }
    cells = np.full((n_parts, k, r), np.nan)
    cell_ok = True
    for pi, p in enumerate(parts):
        for oi, op in enumerate(operators):
            vals = grouped.get((p, op))
            if vals is None or vals.size != r:
                cell_ok = False
                break
            cells[pi, oi, :] = vals
        if not cell_ok:
            break
    if cell_ok and r >= 2:
        anova = _anova_variance_components(
            cells,
            cells.mean(axis=(1, 2)),
            cells.mean(axis=(0, 2)),
            n_parts,
            k,
            r,
        )
    else:
        logger.info(
            "Gage R&R 设计不均衡（各 零件×操作员 单元重复数不一致或存在缺失单元），"
            "跳过 ANOVA 方差分解；均值-极差法结果不受影响"
        )

    # 判定（审查 2026-09-24 第三十轮：纳入 %P/T）
    # AIAG 对 %GRR 与 %P/T 用同一套阈值（<10 可接受 / 10-30 临界 / >30 不合格）。
    # 给了公差时**两者取更差者** —— 只报其中一个会让"过程变异大但公差也大"的
    # 情形被误判为可接受（反之亦然）。未给公差时维持原 %SV 判定（向后兼容）。
    _worst = grr_sv if pt_percent is None else max(grr_sv, pt_percent)
    if _worst < 10:
        judge = "优秀 (可接受)"
    elif _worst < 30:
        judge = "临界 (可能需要改进)"
    else:
        judge = "不合格 (需改进)"
    if pt_percent is not None and pt_percent > grr_sv and pt_percent >= 30:
        judge += "（%P/T 超标：量具变异相对公差偏大）"

    # 可视化
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    components = ["重复性(EV)", "再现性(AV)", "GRR", "部件间(PV)"]
    values_pct = [ev_pct, av_pct, grr_pct, pv_pct]
    ax.barh(
        components,
        values_pct,
        color=[
            PALETTE["data"]["secondary"],
            PALETTE["data"]["tertiary"],
            PALETTE["data"]["primary"],
            PALETTE["contrast"]["b"],
        ],
    )
    # 数值标注：AV 常被合成公式下界截断为 0，光标不可见时靠文字可读
    for yi, v in enumerate(values_pct):
        ax.annotate(
            f"{v:.3f}",
            xy=(v, yi),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
        )
    if tv_pct > 0 and av_pct / tv_pct < 0.005:
        ax.annotate(
            "AV≈0（合成公式下界截断）",
            xy=(0, 1),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=7.5,
            color=PALETTE["misc"]["grid"],
        )
    ax.axvline(
        tv_pct,
        color=PALETTE["anomaly"]["primary"],
        linestyle="--",
        linewidth=1,
        label=f"TV={tv_pct:.3f}",
    )
    ax.set_xlabel(f"{sigma_mult:.1f}σ 研究变异", fontsize=10)
    ax.set_title(
        f"Gage R&R — {req.target_col} | %GRR={grr_sv:.1f}%, ndc={ndc} | {judge}",
        fontsize=10,
    )
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()

    summary = (
        f"Gage R&R: %GRR={grr_sv:.1f}% ({judge}), ndc={ndc}。EV={ev:.4f}, AV={av:.4f}, PV={pv:.4f}"
    )

    return AnalysisResult(
        task="gage_rr",
        tables={
            "gage_rr_results": pd.DataFrame(
                {
                    "变异源": [
                        "重复性 (EV)",
                        "再现性 (AV)",
                        "GRR (量具)",
                        "部件间 (PV)",
                        "总计 (TV)",
                    ],
                    "标准差": [f"{ev:.4f}", f"{av:.4f}", f"{grr:.4f}", f"{pv:.4f}", f"{tv:.4f}"],
                    f"{sigma_mult:.1f}σ变异": [
                        f"{ev_pct:.4f}",
                        f"{av_pct:.4f}",
                        f"{grr_pct:.4f}",
                        f"{pv_pct:.4f}",
                        f"{tv_pct:.4f}",
                    ],
                    "贡献率(%)": [
                        f"{ev_contrib:.1f}",
                        f"{av_contrib:.1f}",
                        f"{grr_contrib:.1f}",
                        f"{pv_contrib:.1f}",
                        "100",
                    ],
                    "%SV": [f"{ev_sv:.1f}", f"{av_sv:.1f}", f"{grr_sv:.1f}", "—", "—"],
                }
            ),
            "ndc": pd.DataFrame({"指标": ["ndc (可区分类别数)", "判定"], "值": [str(ndc), judge]}),
            **(
                {
                    "gage_rr_anova": pd.DataFrame(
                        {
                            "变异源": ["部件", "操作员", "部件×操作员(交互)", "重复性(残差)"],
                            "自由度": [
                                str(anova["df"]["part"]),
                                str(anova["df"]["operator"]),
                                str(anova["df"]["interaction"]),
                                str(anova["df"]["repeatability"]),
                            ],
                            "均方": [
                                f"{anova['f_tests']['part']['MS']:.6f}",
                                f"{anova['f_tests']['operator']['MS']:.6f}",
                                f"{anova['f_tests']['interaction']['MS']:.6f}",
                                f"{anova['f_tests']['repeatability']['MS']:.6f}",
                            ],
                            "F": [
                                f"{anova['f_tests']['part']['F']:.3f}",
                                f"{anova['f_tests']['operator']['F']:.3f}",
                                f"{anova['f_tests']['interaction']['F']:.3f}",
                                "—",
                            ],
                            "p 值": [
                                f"{anova['f_tests']['part']['p']:.4f}",
                                f"{anova['f_tests']['operator']['p']:.4f}",
                                f"{anova['f_tests']['interaction']['p']:.4f}",
                                "—",
                            ],
                            "方差分量": [
                                f"{anova['components']['part']:.6f}",
                                f"{anova['components']['operator']:.6f}",
                                f"{anova['components']['interaction']:.6f}",
                                f"{anova['components']['repeatability']:.6f}",
                            ],
                            "95%CI 下限": [
                                f"{anova['ci95']['part'][0]:.6f}",
                                f"{anova['ci95']['operator'][0]:.6f}",
                                f"{anova['ci95']['interaction'][0]:.6f}",
                                f"{anova['ci95']['repeatability'][0]:.6f}",
                            ],
                            "95%CI 上限": [
                                f"{anova['ci95']['part'][1]:.6f}",
                                f"{anova['ci95']['operator'][1]:.6f}",
                                f"{anova['ci95']['interaction'][1]:.6f}",
                                f"{anova['ci95']['repeatability'][1]:.6f}",
                            ],
                        }
                    )
                }
                if anova
                else {}
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "ev": ev,
            "av": av,
            "grr": grr,
            "pv": pv,
            "tv": tv,
            "grr_sv": grr_sv,
            "ndc": ndc,
            "judge": judge,
            # ── %P/T（第三十轮补实现）──
            # `tolerance` 原样回显（含 `None`）；`pt_ratio`/`pt_percent`
            # **仅在给了公差时存在** —— 不给假值，调用方据 `"pt_ratio" in metadata`
            # 判断是否可用（本文件顶部的测试对此有断言）。
            "tolerance": tolerance,
            **({"pt_ratio": pt_ratio, "pt_percent": pt_percent} if pt_ratio is not None else {}),
            "n_parts": n_parts,
            "n_operators": k,
            "n_replicates": r,
            # ── ANOVA 法（P2-1，2026-09-24）──
            # 与均值-极差法**并列**给出。均值-极差法无交互作用分量，
            # 会把交互变异计入重复性；ANOVA 法分成四项，口径更完整。
            "method": "AIAG 均值-极差法(X-bar & R) + ANOVA 方差分解",
            "anova_method": "ANOVA（交叉设计，零件与操作员均为随机效应）",
            **(
                {
                    "anova_variance_components": anova["components"],
                    "anova_variance_components_pooled": anova["components_pooled"],
                    "anova_ci95": anova["ci95"],
                    "anova_f_tests": anova["f_tests"],
                    "anova_df": anova["df"],
                    "anova_pooled_interaction": anova["pooled"],
                    "anova_negative_components": anova["negative_components"],
                }
                if anova
                else {"anova_unavailable": "设计不均衡或自由度不足，未做 ANOVA 分解"}
            ),
        },
        messages=(
            (_report.messages())
            + (
                [
                    f"ANOVA 方差分解：交互作用 p={anova['f_tests']['interaction']['p']:.4f}"
                    + (
                        "（不显著，已提供合并交互的 pooled 口径）"
                        if anova["pooled"]
                        else "（显著，交互分量应保留）"
                    )
                ]
                if anova
                else []
            )
        ),
    )


def tolerance_interval(req: AnalysisRequest) -> AnalysisResult:
    """统计容许区间 — 以指定置信度覆盖总体指定比例的区间。

    参数:
        coverage: 覆盖比例 (默认 0.99，即 99% 总体)
        confidence: 置信水平 (默认 0.95)
        side: "two-sided" | "upper" | "lower"

    用于设定合理规格限，不同于置信区间（均值的不确定性）。
    """
    data = req.data[req.target_col].dropna()
    # 审查 2026-09-22 发现 3：±Inf 使 hist/linspace 抛 ValueError（range not finite）
    # 第三十七轮：改走 `_guard.clean_series`
    _report = BoundaryReport()
    data, _n_inf = clean_series(data, column=req.target_col, report=_report)
    n = len(data)
    if n < 5:
        return AnalysisResult(
            task="tolerance_interval",
            status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    # 参数校验（P4 步骤③，第二十五轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 原为 `float()` 转换 + 两段 (0,1) 检查 + side 白名单（约 30 行），
    # 现由 `Finite(gt=0, lt=1)` + `Choice` 一次表达，且 Choice 给出中文文案。
    _tp = PARAM_SPECS["tolerance_interval"].validate_or_raise(req.params)
    coverage = _tp.coverage
    confidence = _tp.confidence
    side = _tp.side
    mu = float(data.mean())
    sigma = float(data.std(ddof=1))
    # 审查 2026-09-16 D-1：原 `< EPSILON` 拒绝微尺度数据；改精确零判据
    if sigma == 0:
        return AnalysisResult(
            task="tolerance_interval",
            status="error",
            messages=["数据标准差为零，无法计算容许区间"],
        )

    from math import sqrt

    if side == "two-sided":
        # 双侧容许区间的 k 因子 (Howe 近似)
        z_p = sp_stats.norm.ppf((1 + coverage) / 2)
        chi_sq = sp_stats.chi2.ppf(1 - confidence, n - 1)
        k = sqrt((n - 1) * (1 + 1 / n) * z_p**2 / chi_sq)
        lower = mu - k * sigma
        upper = mu + k * sigma
        label = (
            f"{coverage * 100:.0f}% 总体以 {confidence * 100:.0f}% 置信度落在 "
            f"[{lower:.4f}, {upper:.4f}]"
        )
    elif side == "upper":
        # 单侧上限
        delta = sp_stats.norm.ppf(coverage) * sqrt(n)
        t_val = sp_stats.nct.ppf(confidence, n - 1, delta) / sqrt(n)
        k_upper = t_val
        upper = mu + k_upper * sigma
        lower = float("-inf")
        label = f"{coverage * 100:.0f}% 总体 ≤ {upper:.4f} ({confidence * 100:.0f}% 置信)"
    else:
        # 单侧下限
        delta = sp_stats.norm.ppf(coverage) * sqrt(n)
        t_val = sp_stats.nct.ppf(confidence, n - 1, delta) / sqrt(n)
        k_lower = t_val
        lower = mu - k_lower * sigma
        upper = float("inf")
        label = f"{coverage * 100:.0f}% 总体 ≥ {lower:.4f} ({confidence * 100:.0f}% 置信)"

    # 可视化
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot(111)
    ax.hist(
        data,
        bins=min(30, int(sqrt(n)) * 2),
        density=True,
        color=PALETTE["data"]["secondary"],
        edgecolor="white",
        alpha=0.7,
    )
    x_fit = np.linspace(data.min() - 2 * sigma, data.max() + 2 * sigma, 200)
    ax.plot(
        x_fit,
        sp_stats.norm.pdf(x_fit, mu, sigma),
        "-",
        color=PALETTE["data"]["primary"],
        linewidth=2,
    )
    if side != "upper":
        ax.axvline(
            lower,
            color=PALETTE["anomaly"]["primary"],
            linestyle="--",
            linewidth=2,
            label=f"下限={lower:.4f}",
        )
    if side != "lower":
        ax.axvline(
            upper,
            color=PALETTE["center"]["primary"],
            linestyle="--",
            linewidth=2,
            label=f"上限={upper:.4f}",
        )
    if side == "two-sided":
        ax.legend(fontsize=8)
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_title(f"容许区间 — {label}", fontsize=10)
    fig.tight_layout()

    return AnalysisResult(
        task="tolerance_interval",
        tables={
            "tolerance_limits": pd.DataFrame(
                {
                    "参数": [
                        "样本量",
                        "均值",
                        "标准差",
                        "覆盖比例",
                        "置信水平",
                        "下限",
                        "上限",
                        "区间类型",
                    ],
                    "值": [
                        str(n),
                        f"{mu:.4f}",
                        f"{sigma:.4f}",
                        f"{coverage:.1%}",
                        f"{confidence:.1%}",
                        f"{lower:.4f}" if lower > float("-inf") else "-∞",
                        f"{upper:.4f}" if upper < float("inf") else "+∞",
                        side,
                    ],
                }
            ),
        },
        figures=[fig],
        summary=label,
        metadata={
            "mu": mu,
            "sigma": sigma,
            "n": n,
            "lower": lower,
            "upper": upper,
            "coverage": coverage,
            "confidence": confidence,
            "side": side,
        },
        messages=_report.messages(),
    )


# ── 文本事件列语义对照表（审查 2026-09-24 P0-2）──
# 只登记**语义无歧义**的失效标记写法。判定规则：两值中**恰好一个**命中本表 → 采用之；
# 两个都命中或都不命中 → 拒绝（不猜）。
#
# 为什么不用字典序：实测 Fail/Pass、NG/OK、异常/正常 全部反转，只有中文「是/否」
# 恰好正确（'是' > '否'）。任何"恰好对"的启发式都是定时炸弹。
#
# 注意对照表**故意不含** "dead"/"alive" 等需成对出现才有意义的词——
# 单看一个 "dead" 无法与 "unknown" 区分。这类编码请用 event_value 显式声明。
_EVENT_TRUE_ALIASES: frozenset[str] = frozenset(
    {
        "是",
        "y",
        "yes",
        "true",
        "event",
        "fail",
        "failed",
        "failure",
        "失效",
        "故障",
        "1",
        "1.0",
    }
)
_EVENT_FALSE_ALIASES: frozenset[str] = frozenset(
    {
        "否",
        "n",
        "no",
        "false",
        "censored",
        "censor",
        "删失",
        "未失效",
        "0",
        "0.0",
    }
)


def _normalize_event_label(value) -> str:
    """归一化文本事件标记：去首尾空白 + 小写（仅用于对照表匹配，不改原值）。"""
    return str(value).strip().lower()


def _resolve_event_value(raw_events, event_col: str, params) -> tuple[object | None, str | None]:
    """确定「哪一值代表失效」。返回 (失效标记的原始值, 错误消息)。

    优先级：
      1. `params.event_value` 显式声明 —— 用户说了算（大小写/空白不敏感）；
      2. 语义无歧义的对照表（见 `_EVENT_TRUE_ALIASES`）；
      3. 否则返回错误消息，要求显式声明或改用 0/1。

    审查 2026-09-24 P0-2：原实现用 `sorted(unique_vals)[-1]`，即字典序最大者。
    """
    uniq = list(pd.unique(raw_events.dropna()))
    if len(uniq) != 2:
        return None, None  # 非 2 值场景交由调用方的通用分支报错

    declared = params.get("event_value")
    if declared is not None:
        target = _normalize_event_label(declared)
        for u in uniq:
            if _normalize_event_label(u) == target:
                return u, None
        return None, (
            f"参数 event_value={declared!r} 不在事件列「{event_col}」的取值中："
            f"{[str(u) for u in uniq]}。请填写其中一个值作为「失效」标记。"
        )

    labels = [_normalize_event_label(u) for u in uniq]
    true_hits = [u for u, lab in zip(uniq, labels, strict=True) if lab in _EVENT_TRUE_ALIASES]
    false_hits = [u for u, lab in zip(uniq, labels, strict=True) if lab in _EVENT_FALSE_ALIASES]

    # 判定表（恰有 2 个取值）：
    #   true_hits  false_hits   结论
    #   ---------  ----------   --------------------------------------------
    #       1          1        互补 → 明确（是/否、Yes/No、Event/Censored、1/0）
    #       1          0        另一值中性 → 明确（Fail/Pass、失效/合格）
    #       0          1        反向表述 → 另一值即失效（Censored/Fail）
    #       0          0        都不认识 → **拒绝**（NG/OK、异常/正常、故障/正常）
    #       2          0        两值都像失效 → **拒绝**（无法二选一）
    #       0          2        两值都像删失 → **拒绝**
    if len(true_hits) == 1 and len(false_hits) <= 1:
        return true_hits[0], None
    if len(false_hits) == 1 and not true_hits:
        return next(u for u in uniq if u not in false_hits), None

    # 其余一律拒绝：两值都命中同一类、或都不命中——语义无法确定
    return None, (
        f"事件列「{event_col}」的文本取值 {[str(u) for u in uniq]} 语义不明确，"
        f"无法判断哪一个代表「失效」。请任选一种方式修正："
        f"① 用参数 event_value 显式声明失效标记（如 event_value={uniq[0]!r}）；"
        f"② 将事件列改为 0/1 数值编码（1=失效，0=删失）；"
        f"③ 改用语义明确的值，如「是/否」「Yes/No」「失效/删失」。"
    )


def _encode_text_event_column(raw_events, event_col: str, params):
    """文本事件列 → 0/1 数组。返回 (数组, 错误结果或 None)。"""
    event_value, err = _resolve_event_value(raw_events, event_col, params)
    if err is not None:
        return None, AnalysisResult(task="survival_analysis", status="error", messages=[err])
    if event_value is None:  # 非 2 值场景，交由调用方的通用分支处理
        return None, None
    return (raw_events == event_value).astype(int).values, None


def _weibull_fit_censored(times, events):
    """含右删失的 Weibull MLE。

    契约：docs/governance/boundary-contract.md（B3 近似：渐近正态 CI）

    审查 2026-09-24（计划 P2-2）：原实现只把**失效时刻**喂给
    `scipy.stats.weibull_min.fit`，删失观测被整个丢弃：

        fail_times = times[events == 1]
        shape, loc, scale = sp_stats.weibull_min.fit(fail_times, floc=0)

    代码自己写了警告说"形状参数 β 可能被低估"——诚实，但等于承认可靠性模块
    在真实场景（几乎总有删失）下不可用。实测（300 样本、独立删失 ~42%）：
    朴素估计 η 误差约 28%（75 vs 真值 100），本实现约 5%。

    对数似然（β=形状, η=尺度；失效项用密度、删失项用**生存函数**）：
        lnL = Σ_失效 [ln β − ln η + (β−1)·ln(t/η) − (t/η)^β] + Σ_删失 [−(t/η)^β]

    实现要点：
      - 在 **(a, b) = (ln β, ln η)** 空间优化：两参数为正，对数空间的负对数似然
        是凸的，无需约束；
      - 梯度用**复步长微分**（`Im f(x+ih)/h`）——没有相减消去误差，
        精度到机器 epsilon。此前手推解析式连续两次出错（漏项、符号），
        复步长既准确又不需要维护易错的公式；
      - Hessian 用中心差分（在 MLE 处），**观测 Fisher 信息 = 负对数似然的 Hessian**，
        协方差 = I⁻¹；非正定则返回 None 而非给出无效 CI。

    Returns:
        (shape, scale, cov, info)。失败时 shape/scale 为 None —— 不伪造参数。
    """
    t = np.asarray(times, dtype=float)
    e = np.asarray(events, dtype=int)
    n_fail = int((e == 1).sum())
    if n_fail < 2 or t.size < 3 or not np.all(t > 0):
        return None, None, None, None

    is_fail = e == 1

    def _nll(a, b, *, complex_a=False, complex_b=False):
        beta = np.exp(a)
        eta = np.exp(b)
        with np.errstate(all="ignore"):
            u = t / eta
            ub = np.power(u, beta)
            lu = np.log(u)
            val = np.sum(np.where(is_fail, -(a - b + (beta - 1.0) * lu - ub), ub))
        return val  # 复数输入时返回复数

    def _grad(a, b, h=1e-30):
        """复步长梯度：∂nll/∂a 与 ∂nll/∂b。"""
        ga = complex(_nll(a + 1j * h, b)) / 1j / h
        gb = complex(_nll(a, b + 1j * h)) / 1j / h
        return np.array([float(np.real(ga)), float(np.real(gb))])

    def _hess(a, b, h=1e-4):
        """中心差分 Hessian（在 MLE 处）。"""
        h00 = (_nll(a + h, b) - 2 * _nll(a, b) + _nll(a - h, b)) / (h * h)
        h11 = (_nll(a, b + h) - 2 * _nll(a, b) + _nll(a, b - h)) / (h * h)
        h01 = (
            _nll(a + h, b + h) - _nll(a + h, b - h) - _nll(a - h, b + h) + _nll(a - h, b - h)
        ) / (4 * h * h)
        return np.array([[h00, h01], [h01, h11]], dtype=float)

    # 初值：无删失 MLE（删失比例高时低估 β，但作为初值够用）
    try:
        b0_shape, _loc, b0_scale = sp_stats.weibull_min.fit(t[is_fail], floc=0)
        if not (np.isfinite(b0_shape) and np.isfinite(b0_scale) and b0_shape > 0):
            raise ValueError("bad init")
    except Exception:
        logger.debug("Weibull 初值估计失败，回退到均值初值", exc_info=True)
        b0_shape = 1.0
        b0_scale = float(np.mean(t))
    x0 = np.array([np.log(max(b0_shape, 1e-3)), np.log(max(b0_scale, 1e-9))])

    try:
        from scipy.optimize import minimize

        res = minimize(
            lambda p: float(np.real(_nll(p[0], p[1]))),
            x0,
            jac=lambda p: _grad(p[0], p[1]),
            method="BFGS",
            options={"gtol": 1e-10, "maxiter": 500},
        )
        a_hat, b_hat = float(res.x[0]), float(res.x[1])
    except Exception:
        logger.debug("Weibull 含删失 MLE 优化失败", exc_info=True)
        return None, None, None, None

    if not (np.isfinite(a_hat) and np.isfinite(b_hat)):
        return None, None, None, None

    # 观测 Fisher 信息：I = ∂²(−lnL)/∂θ² = Hessian（−lnL 的二阶导）
    info = _hess(a_hat, b_hat)
    try:
        cov = np.linalg.inv(info)
    except np.linalg.LinAlgError:
        logger.debug("Weibull Fisher 信息不可逆（参数不可识别）")
        return None, None, None, None
    # 正定性自检：特征值全正才有意义（否则 CI 会被夸大或反向）
    if not (np.all(np.isfinite(cov)) and np.all(np.linalg.eigvalsh(info) > 0)):
        logger.debug("Weibull Fisher 信息非正定，不输出 CI: %s", info)
        return None, None, None, None

    shape = float(np.exp(a_hat))
    scale = float(np.exp(b_hat))
    if not (np.isfinite(shape) and np.isfinite(scale) and shape > 0 and scale > 0):
        return None, None, None, None
    return shape, scale, cov, info


def _weibull_percentile_ci(
    p: float, shape: float, scale: float, cov
) -> tuple[float | None, float | None]:
    """百分位寿命 t_p 的 95% CI（对数尺度 delta 法 + 渐近正态）。

    t_p = η·(−ln(1−p))^(1/β)

    在 (a, b) = (ln β, ln η) 空间：
        ln t_p = b + (1/β)·ln(−ln(1−p)) = b + e^(−a)·L,  L = ln(−ln(1−p))
        ∂ln t_p/∂a = −e^(−a)·L
        ∂ln t_p/∂b = 1
    → Var(ln t_p) = gᵀ Σ g，CI = exp(ln t_p ± 1.96·√Var)。
    在对数尺度构造保证 CI 下界恒为正（寿命不能为负），且与 t_p 的乘性
    不确定性结构一致。
    """
    if cov is None or not (0 < p < 1):
        return (None, None)
    L = float(np.log(-np.log(1.0 - p)))
    inv_beta = 1.0 / shape
    t_p = scale * np.exp(inv_beta * L)
    g = np.array([-inv_beta * L, 1.0], dtype=float)
    var_log = float(g @ cov @ g)
    if not np.isfinite(var_log) or var_log < 0:
        return (None, None)
    se = float(np.sqrt(var_log))
    z = 1.959963984540054  # Φ⁻¹(0.975)
    return (float(t_p * np.exp(-z * se)), float(t_p * np.exp(z * se)))


def survival_analysis(req: AnalysisRequest) -> AnalysisResult:
    """Kaplan-Meier 生存分析 + Weibull 拟合 — 适用于右删失寿命数据。

    target_col: 时间/寿命列
    feature_cols[0]: 事件指示列 (1=失效, 0=删失)
    feature_cols[1] (可选): 分组列 (用于 Log-rank 检验)
    """
    time_col = req.target_col
    event_col = req.feature_cols[0] if len(req.feature_cols) > 0 else None
    # 2026-08-21 发行前审查 #1：与其余方法统一——分组列优先 params.group_col，
    # 回退 feature_cols[1]（此前仅 feature_cols[1]，前端 group_col 参数无效）
    # 审查 2026-09-06 F-D5：falsy 回退改 is not None——空串显式报错，不静默替换
    group_col = req.params.get("group_col")
    if group_col is None:
        group_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None

    if not event_col or event_col not in req.data.columns:
        return AnalysisResult(
            task="survival_analysis",
            status="error",
            messages=["需要提供事件指示列 (1=失效, 0=删失)"],
        )
    if group_col is not None and group_col not in req.data.columns:
        return AnalysisResult(
            task="survival_analysis",
            status="error",
            messages=[
                f"分组列「{group_col}」不存在于数据中。可用列: {list(req.data.columns)[:10]}"
            ],
        )
    # 2026-08-21 CI 修复：group_col 可能与 event_col 同列（误配场景），
    # 去重列名避免重复列索引产生 DataFrame（与 box_chart 的 _cols_needed 同模式）
    cols = list(dict.fromkeys([time_col, event_col] + ([group_col] if group_col else [])))
    sub = req.data[cols].dropna()
    if len(sub) == 0:
        return AnalysisResult(
            task="survival_analysis",
            status="error",
            messages=["有效数据为空：时间列与事件列无共同有效值，请检查数据完整性。"],
        )
    times = sub[time_col].values
    # 自动二值化事件列：支持 0/1 数值和语义明确的文本编码。
    # 审查 2026-09-21 D-2（P0）：原先直接 `astype(int)` 对**任意**数值列恒成功，
    # 使「恰好 2 个不同值」校验永不进入；而事件语义又硬编码为 `== 1`，于是
    # 1/2 编码把事件算成 1+2=3 倍、10/20 编码算出 180 个事件（n_total 仅 12），
    # 全部 status=ok。数值列的「哪一值是事件」无法从数值推断（max 不一定代表
    # 事件，如 10=失效/20=删失），故收紧为：数值事件列必须恰为 {0,1}。
    #
    # 审查 2026-09-24（第三轮复核 P0-2）：文本列原先用 `sorted(unique_vals)[-1]`
    # （**字典序最大者**）判失效，实测已复现结论反转（真值 25 个失效事件）：
    #     Fail/Pass -> 75   ('Pass' > 'Fail')
    #     NG/OK     -> 75   ('OK' > 'NG')
    #     异常/正常  -> 75   ('正常' > '异常')
    #     是/否      -> 25   ✓ 恰好正确——巧合被当成了设计
    # 沿用 D-2 已确立的「不猜」口径：先取显式声明，否则只认语义明确的对照表，
    # 其余一律拒绝并给出可直接照做的修法。
    raw_events = sub[event_col]
    unique_vals = raw_events.unique()
    if pd.api.types.is_numeric_dtype(raw_events) or pd.api.types.is_bool_dtype(raw_events):
        vals = set(pd.unique(raw_events.dropna()).tolist())
        if not vals <= {0, 1}:
            return AnalysisResult(
                task="survival_analysis",
                status="error",
                messages=[
                    f"事件列「{event_col}」的数值编码必须为 0/1（1=失效，0=删失），"
                    f"当前取值: {sorted(vals)[:10]}。"
                    "若为其他编码，请先转换为 0/1，或改用「是/否」文本列。"
                ],
            )
        events = raw_events.astype(int).values
    elif len(unique_vals) == 2:
        encoded, enc_err = _encode_text_event_column(raw_events, event_col, req.params)
        if enc_err is not None:
            return enc_err
        events = encoded
    else:
        return AnalysisResult(
            task="survival_analysis",
            status="error",
            messages=[
                f"事件列「{event_col}」需要恰好2个不同值(0/1 或 是/否)，当前有{len(unique_vals)}个"
            ],
        )
    # 将二值化结果写回 DataFrame，确保后续 Log-rank 等分组分析使用一致的事件编码
    # (P0 fix: Log-rank 段使用 sub[event_col] 比较 int 1，含文本原始值时永为 False)
    sub[event_col] = events

    # 零事件防护
    n_events_total = int(events.sum())
    if n_events_total == 0:
        return AnalysisResult(
            task="survival_analysis",
            status="error",
            messages=[
                "所有观测均为删失数据（无失效事件），无法估计生存函数。"
                "请检查事件列是否正确标记了失效事件 (1=失效)。"
            ],
        )

    # KM 估计 (全样本)
    unique_times = np.sort(np.unique(times[events == 1]))
    n_total = len(times)
    km_times = [0.0]
    km_survival_val = [1.0]

    for t in unique_times:
        n_events = int(np.sum((times == t) & (events == 1)))
        at_risk = int(np.sum(times >= t))  # 直接计算风险集，正确计入事件间删失
        if at_risk > 0 and n_events > 0:
            km_survival_val.append(km_survival_val[-1] * (1 - n_events / at_risk))
            km_times.append(float(t))

    # 中位生存时间
    median_idx = np.where(np.array(km_survival_val) <= 0.5)[0]
    median_survival = float(km_times[median_idx[0]]) if len(median_idx) > 0 else None

    # Weibull 拟合 —— 审查 2026-09-24（计划 P2-2）：改用**含删失 MLE**。
    # 原实现只喂失效时刻，删失信息被丢弃 → β 系统性低估（实测 40% 删失下偏差显著）。
    fail_times = times[events == 1]
    n_censored = int((events == 0).sum())
    weibull_shape, weibull_scale = None, None
    weibull_cov = None
    weibull_method = None
    b10_life: float | None = None
    b10_ci: tuple[float | None, float | None] = (None, None)
    warn_msgs: list[str] = []
    if len(fail_times) >= 5:
        shape_fit, scale_fit, cov_fit, _info = _weibull_fit_censored(times, events)
        if shape_fit is not None:
            weibull_shape, weibull_scale, weibull_cov = shape_fit, scale_fit, cov_fit
            weibull_method = "censored_mle" if n_censored > 0 else "uncensored_mle"
        else:
            # 含删失 MLE 不可用 → 退回无删失估计，并**明确披露降级**（B2 契约）
            try:
                shape_fb, _loc, scale_fb = sp_stats.weibull_min.fit(fail_times, floc=0)
                weibull_shape, weibull_scale = float(shape_fb), float(scale_fb)
                weibull_method = "uncensored_mle_fallback"
                warn_msgs.append(
                    "⚠ 含删失 Weibull MLE 未能收敛，已降级为仅用失效数据的估计"
                    "（忽略删失观测，形状参数 β 可能被低估）。"
                )
            except Exception:
                logger.debug("Weibull fit failed in survival_analysis", exc_info=True)
    elif len(fail_times) > 0:
        warn_msgs.append(f"⚠ 失效观测仅 {len(fail_times)} 个（少于 5 个），未做 Weibull 参数估计。")

    # B10（10% 失效寿命）—— 可靠性工程的常用寿命指标，含 95% CI
    if weibull_shape is not None and weibull_scale is not None:
        b10_life = float(weibull_scale * (-np.log(0.9)) ** (1.0 / weibull_shape))
        b10_ci = _weibull_percentile_ci(0.10, weibull_shape, weibull_scale, weibull_cov)

    # 重删失提示：参数不确定性大，CI 会明显变宽
    if n_censored > 0 and weibull_method == "censored_mle":
        cens_frac = n_censored / max(len(times), 1)
        if cens_frac > 0.5:
            warn_msgs.append(
                f"⚠ 删失比例较高（{n_censored}/{len(times)} = {cens_frac:.0%}），"
                "Weibull 参数与寿命百分位的置信区间会明显变宽，"
                "请以 CI 而非单点估计作为判据。"
            )

    # Log-rank 检验 (分组比较)；group_col == event_col 时分组即事件本身，无比较意义
    logrank_result = None
    if group_col and group_col != event_col and group_col in sub.columns:
        groups = sub[group_col].unique()
        if len(groups) == 2:
            g1 = sub[sub[group_col] == groups[0]]
            g2 = sub[sub[group_col] == groups[1]]
            # 简化 Log-rank
            all_event_times = np.sort(
                np.unique(
                    np.concatenate(
                        [g1[time_col][g1[event_col] == 1], g2[time_col][g2[event_col] == 1]]
                    )
                )
            )
            # Log-rank: 单次遍历计算 O/E 和方差
            O1_sum, E1_sum, v1 = 0.0, 0.0, 0.0
            for t in all_event_times:
                o1 = int(((g1[time_col] == t) & (g1[event_col] == 1)).sum())
                o2 = int(((g2[time_col] == t) & (g2[event_col] == 1)).sum())
                r1_t = int((g1[time_col] >= t).sum())
                r2_t = int((g2[time_col] >= t).sum())
                total_o = o1 + o2
                total_r = r1_t + r2_t
                if total_r > 0:
                    e1 = total_o * r1_t / total_r
                    O1_sum += o1
                    E1_sum += e1
                if total_r > 1:
                    v1 += (
                        total_o
                        * (total_r - total_o)
                        * r1_t
                        * r2_t
                        / (total_r**2 * (total_r - 1) + EPSILON)
                    )
            z_lr = (O1_sum - E1_sum) / np.sqrt(v1 + EPSILON)
            lr_p = float(2 * sp_stats.norm.sf(abs(z_lr)))
            logrank_result = {
                "分组": f"{groups[0]} vs {groups[1]}",
                "Log-rank Z": round_for_display(float(z_lr), 3),
                "p值": round(lr_p, 4),
                "显著": "是" if lr_p < 0.05 else "否",
            }

    # 可视化
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.step(
        km_times,
        km_survival_val,
        where="post",
        color=PALETTE["data"]["primary"],
        linewidth=2.5,
        label=f"KM (n={n_total})",
    )
    ax.axhline(0.5, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.8, alpha=0.5)
    if median_survival is not None:
        ax.axvline(
            median_survival,
            color=PALETTE["target"]["primary"],
            linestyle="--",
            linewidth=1,
            label=f"中位寿命={median_survival:g}",
        )
    # Weibull 拟合曲线
    if weibull_shape and weibull_scale:
        x_w = np.linspace(0, max(times) * 1.2, 200)
        s_w = 1 - sp_stats.weibull_min.cdf(x_w, weibull_shape, 0, weibull_scale)
        ax.plot(
            x_w,
            s_w,
            "--",
            color=PALETTE["data"]["secondary"],
            linewidth=1.5,
            alpha=0.7,
            label=f"Weibull (β={weibull_shape:.2f}, η={weibull_scale:.0f})",
        )

    # 删失标记
    cens_times = times[events == 0]
    ax.scatter(
        cens_times,
        np.ones(len(cens_times)),
        marker="|",
        s=30,
        color=PALETTE["spec"]["tertiary"],
        alpha=0.5,
        label=f"删失 ({len(cens_times)})",
    )

    ax.set_xlabel("时间", fontsize=10)
    ax.set_ylabel("生存概率", fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.set_title(
        f"Kaplan-Meier 生存曲线 — {req.target_col}"
        + (f" | {logrank_result['分组']} p={logrank_result['p值']}" if logrank_result else ""),
        fontsize=10,
    )
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()

    summary_parts = [
        f"KM: 中位寿命={median_survival:g}" if median_survival is not None else "KM: 中位寿命未达到"
    ]
    if weibull_shape is not None:
        summary_parts.append(f"Weibull β={weibull_shape:.2f}, η={weibull_scale:.0f}")
    if logrank_result:
        summary_parts.append(f"Log-rank: {logrank_result['分组']} p={logrank_result['p值']}")
    summary = "；".join(summary_parts)

    tables = {
        "km_survival": pd.DataFrame(
            {
                "时间": km_times,
                "生存概率": [f"{s:.4f}" for s in km_survival_val],
            }
        ),
    }
    if logrank_result:
        tables["logrank_test"] = pd.DataFrame([logrank_result])

    # 寿命百分位表（B1/B5/B10/B50）——含 95% CI
    if weibull_shape is not None and weibull_scale is not None:
        _pct_rows = []
        for _p in (0.01, 0.05, 0.10, 0.50):
            _t_p = weibull_scale * (-np.log(1.0 - _p)) ** (1.0 / weibull_shape)
            _lo, _hi = _weibull_percentile_ci(_p, weibull_shape, weibull_scale, weibull_cov)
            _pct_rows.append(
                {
                    "失效比例": f"{_p:.0%}",
                    "寿命": round_for_display(_t_p, 4),
                    "95%CI下限": round_for_display(_lo, 4) if _lo is not None else "N/A",
                    "95%CI上限": round_for_display(_hi, 4) if _hi is not None else "N/A",
                }
            )
        tables["life_percentiles"] = pd.DataFrame(_pct_rows)

    return AnalysisResult(
        task="survival_analysis",
        tables=tables,
        figures=[fig],
        summary=summary,
        messages=warn_msgs,
        metadata={
            "median_survival": median_survival,
            "n_total": n_total,
            "n_events": int(events.sum()),
            "n_censored": int((events == 0).sum()),
            "weibull_shape": weibull_shape,
            "weibull_scale": weibull_scale,
            # 审查 2026-09-24（计划 P2-2）：口径披露 —— 用户必须知道用的是
            # 含删失 MLE 还是降级后的无删失估计（禁止静默切换口径）
            "weibull_method": weibull_method,
            "b10_life": b10_life,
            "b10_ci": list(b10_ci),
            "logrank_p": logrank_result["p值"] if logrank_result else None,
        },
    )
