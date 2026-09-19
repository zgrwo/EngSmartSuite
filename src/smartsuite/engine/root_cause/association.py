"""关联与信度：列联表/Cramers V、Kappa、Cronbach α。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    CRAMERS_V_LARGE,
    CRAMERS_V_MEDIUM,
    CRAMERS_V_SMALL,
    EPSILON,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine._utils import threshold_label

logger = logging.getLogger(__name__)


def _cramers_v_interpretation(v):
    """Cramér's V 效应量解读 (df≥1 通用阈值, Cohen 1988)。"""
    return threshold_label(v, [CRAMERS_V_SMALL, CRAMERS_V_MEDIUM, CRAMERS_V_LARGE])


def _cramers_v_ci(v: float, n: int, k: int, df: int, alpha: float = 0.05) -> tuple[float, float]:
    """Cramér's V 的 95% CI（基于非中心 χ² 的 CDF 反演）。

    k = min(rows, cols) - 1（V 标准化因子）
    df = (rows-1)*(cols-1)（列联表实际自由度）
    """
    if n < 2 or k < 1 or v < 0 or df < 1:
        return (float("nan"), float("nan"))
    try:
        from scipy.optimize import brentq

        chi2_obs = v**2 * n * k
        df_chi = df  # 使用列联表实际自由度

        def _cdf_minus_target(lam, target):
            return sp_stats.ncx2.cdf(chi2_obs, df_chi, max(0.0, lam)) - target

        # λ_L: cdf(chi2_obs | λ_L) = 1 - alpha/2
        target_lo = 1.0 - alpha / 2
        cdf_at_0 = float(sp_stats.ncx2.cdf(chi2_obs, df_chi, 0))
        if cdf_at_0 >= target_lo:
            hi_bound = max(chi2_obs + 50, 100)
            while (
                float(sp_stats.ncx2.cdf(chi2_obs, df_chi, hi_bound)) > target_lo and hi_bound < 1e6
            ):
                hi_bound *= 3
            try:
                lam_l = brentq(_cdf_minus_target, 0, hi_bound, args=(target_lo,), xtol=1e-8)
            except (ValueError, RuntimeError):
                lam_l = 0.0
        else:
            lam_l = 0.0

        # λ_U: cdf(chi2_obs | λ_U) = alpha/2
        target_hi = alpha / 2
        hi_bound = max(chi2_obs * 4 + 100, 200)
        while float(sp_stats.ncx2.cdf(chi2_obs, df_chi, hi_bound)) > target_hi and hi_bound < 1e6:
            hi_bound *= 3
        try:
            lam_u = brentq(_cdf_minus_target, 0, hi_bound, args=(target_hi,), xtol=1e-8)
        except (ValueError, RuntimeError):
            lam_u = 0.0

        v_lo = max(0.0, np.sqrt(lam_l / (n * k)))
        v_hi = min(1.0, np.sqrt(lam_u / (n * k)))
        if v_lo > v_hi:
            v_lo, v_hi = 0.0, max(v_lo, v_hi)
        return (float(v_lo), float(v_hi))
    except Exception:
        logger.debug("Cramér's V CI 计算失败", exc_info=True)
        return (float("nan"), float("nan"))


def contingency_analysis(req: AnalysisRequest) -> AnalysisResult:
    """列联表分析 — 检验两个分类变量是否独立。

    自动选择：期望频数≥5 用 Chi-square，否则用 Fisher's exact test。
    效应量: Cramér's V (Chi-square) 或 Odds Ratio (2×2 Fisher)。
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(task="contingency", status="error", messages=["需要至少 1 个因子列"])

    col1 = req.target_col
    col2 = req.feature_cols[0]
    if col1 not in req.data.columns or col2 not in req.data.columns:
        return AnalysisResult(task="contingency", status="error", messages=["目标列或因子列不存在"])

    sub = req.data[[col1, col2]].dropna()
    if len(sub) < 4:
        return AnalysisResult(task="contingency", status="error", messages=["有效数据不足"])

    # 审查 2026-08-19 #1.4：连续列被当类别 → crosstab 生成 n×n 巨型表
    # （6000 行连续数据 → 6000×6000 表，chi2_contingency/绘图原生崩溃）
    _n1, _n2 = int(sub[col1].nunique()), int(sub[col2].nunique())
    if _n1 > 200 or _n2 > 200:
        return AnalysisResult(
            task="contingency",
            status="error",
            messages=[
                f"列联表维度过高（{_n1} × {_n2}），无法分析。"
                f"列联表分析需要分类列（水平数较少），连续变量请改用 correlation/regression。"
            ],
        )

    # 列联表
    ctab = pd.crosstab(sub[col1], sub[col2])

    # Chi-square
    chi2, chi_p, dof, expected = sp_stats.chi2_contingency(ctab)
    min_expected = expected.min()

    # 自动选择：期望频数<5 或 (2×2 且样本少) → Fisher，否则 Chi-square
    if (min_expected < 5) or (ctab.shape == (2, 2) and len(sub) < 100):
        # Fisher's exact test
        if ctab.shape == (2, 2):
            odds_ratio, fish_p = sp_stats.fisher_exact(ctab)
            test_name = "Fisher 精确检验 (2×2)"
            stat = odds_ratio
            stat_label = "Odds Ratio"
            effect = float(odds_ratio)
            effect_name = "Odds Ratio (OR)"
            if effect > 2:
                effect_label = "强关联"
            elif effect > 1.5:
                effect_label = "中等关联"
            else:
                effect_label = "弱/无关联"
        else:
            # 非 2×2 表格无法使用 Fisher 精确检验 (scipy 不支持)
            # 期望频数不足时仍使用卡方检验，但标注局限性
            test_name = "卡方检验 (期望频数<5, 结果仅供参考)"
            fish_p = chi_p
            stat = chi2
            stat_label = "Chi²"
            # Cramér's V: 确保 min_dim >= 1 防止除零
            _ctab_shape = ctab.shape
            min_dim = max(1, min(*_ctab_shape) - 1) if min(*_ctab_shape) > 1 else 1
            effect = float(np.sqrt(chi2 / (len(sub) * min_dim + EPSILON)))
            effect_name = "Cramér's V"
            effect_label = _cramers_v_interpretation(effect)
        p_val = fish_p
    else:
        test_name = "卡方独立性检验"
        stat = chi2
        stat_label = "Chi²"
        p_val = chi_p
        # Cramér's V
        n_total = ctab.sum().sum()
        min_dim = min(*ctab.shape) - 1
        effect = float(np.sqrt(chi2 / (n_total * min_dim + EPSILON))) if min_dim > 0 else 0.0
        effect_name = "Cramér's V"
        effect_label = _cramers_v_interpretation(effect)

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="contingency",
            status="error",
            messages=[f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}"],
        )
    conclusion = "两变量存在显著关联" if p_val < alpha else "两变量未发现显著关联"

    # 可视化：分组柱状图（各保养日状态内原料类型占比；堆叠会把两个状态的占比相加，无意义）
    fig = Figure(figsize=(8, 4.5))
    ax = fig.add_subplot(111)
    ctab_pct = ctab.div(ctab.sum(axis=0), axis=1) * 100
    bar_colors = [
        PALETTE["data"]["primary"],
        PALETTE["data"]["secondary"],
        PALETTE["target"]["primary"],
        PALETTE["anomaly"]["primary"],
        PALETTE["contrast"]["b"],
        PALETTE["contrast"]["c"],
    ]
    ctab_pct.plot(
        kind="bar",
        ax=ax,
        color=bar_colors[: len(ctab_pct)],
        edgecolor="white",
        linewidth=0.5,
        width=0.75,
    )
    ax.set_xlabel(col1, fontsize=10)
    ax.set_ylabel("组内比例 (%)", fontsize=10)
    ax.set_title(
        f"{test_name}: {col1} vs {col2} "
        f"({stat_label}={stat:.3f}, p={p_val:.4f}, {effect_name}={effect:.3f})",
        fontsize=10,
    )
    ax.legend(title=col2, fontsize=8, title_fontsize=8)
    ax.tick_params(axis="x", rotation=45, labelsize=9)
    fig.tight_layout()

    summary = (
        f"{test_name}: {conclusion} (p={p_val:.4f}), {effect_name}={effect:.3f} ({effect_label})"
    )

    return AnalysisResult(
        task="contingency",
        tables={
            "contingency_table": ctab,
            "expected_frequencies": pd.DataFrame(expected, index=ctab.index, columns=ctab.columns),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "test": test_name,
            "statistic": float(stat),
            "p_value": float(p_val),
            "alpha": alpha,
            "effect_size": effect,
            "effect_name": effect_name,
            "effect_label": effect_label,
            "effect_size_ci": _cramers_v_ci(
                effect, int(ctab.sum().sum()), max(1, min(*ctab.shape) - 1), int(dof)
            )
            if effect_name == "Cramér's V"
            else (float("nan"), float("nan")),
            "degrees_of_freedom": int(dof) if min_expected >= 5 else None,
            "min_expected": float(min_expected),
        },
    )


def cohens_kappa(req: AnalysisRequest) -> AnalysisResult:
    """Cohen's Kappa — 两个评定者之间的一致性评估。

    feature_cols[0] 和 feature_cols[1] 分别对应两个评定者的评定结果。
    """
    if len(req.feature_cols) < 2:
        return AnalysisResult(task="cohens_kappa", status="error", messages=["需要 2 个评定者列"])

    c1, c2 = req.feature_cols[0], req.feature_cols[1]
    sub = req.data[[c1, c2]].dropna()
    if len(sub) < 3:
        return AnalysisResult(task="cohens_kappa", status="error", messages=["有效数据不足"])

    # 构建一致性矩阵
    ctab = pd.crosstab(sub[c1], sub[c2])
    n = ctab.sum().sum()
    # 观察一致率
    p_o = np.trace(ctab.values) / n
    # 期望一致率
    row_sums = ctab.sum(axis=1).values
    col_sums = ctab.sum(axis=0).values
    p_e = np.sum(row_sums * col_sums) / n**2
    # Round-2 #A2h：p_e≈1（全一致/单类别表）时 kappa 无定义——
    # 分母≈0 产生 kappa=0 并被误判为"低于随机一致"
    if p_e >= 1 - 1e-9:
        return AnalysisResult(
            task="cohens_kappa",
            status="error",
            messages=["评定者间一致性过高（期望一致率 p_e≈1），Kappa 统计量无定义。"],
        )
    # Kappa
    kappa = (p_o - p_e) / (1 - p_e + EPSILON)
    # 标准误 (Fleiss-Cohen-Everitt 公式，适用于大样本)
    # SE₀(κ) = √[p_o(1-p_o) / (n(1-p_e)²)]  是 H₀:κ=0 下的近似
    # 生产环境使用简化公式；如需精确 SE 可用 bootstrap 方法
    se_kappa = np.sqrt((p_o * (1 - p_o)) / (n * (1 - p_e) ** 2 + EPSILON))
    z_kappa = kappa / (se_kappa + EPSILON)
    p_val = float(2 * (1 - sp_stats.norm.cdf(abs(z_kappa))))

    # 判读
    if kappa > 0.8:
        level = "几乎完美一致"
    elif kappa > 0.6:
        level = "高度一致"
    elif kappa > 0.4:
        level = "中等一致"
    elif kappa > 0.2:
        level = "一般一致"
    elif kappa > 0:
        level = "轻微一致"
    else:
        level = "低于随机一致"

    return AnalysisResult(
        task="cohens_kappa",
        tables={
            "agreement_matrix": ctab,
            "kappa_result": pd.DataFrame(
                {
                    "指标": ["Kappa", "观察一致率", "期望一致率", "Z值", "p值", "样本量", "判读"],
                    "值": [
                        f"{kappa:.4f}",
                        f"{p_o:.1%}",
                        f"{p_e:.1%}",
                        f"{z_kappa:.3f}",
                        f"{p_val:.4f}",
                        str(n),
                        level,
                    ],
                }
            ),
        },
        summary=f"Cohen's Kappa={kappa:.3f} ({level}), p_o={p_o:.1%}, n={n}",
        metadata={
            "kappa": float(kappa),
            "p_o": float(p_o),
            "p_e": float(p_e),
            "z": float(z_kappa),
            "level": level,
        },
    )


def cronbach_alpha(req: AnalysisRequest) -> AnalysisResult:
    """Cronbach's α — 内部一致性信度分析。

    feature_cols 中的列视为量表的各个题项，计算 Cronbach's α 系数。
    α ≥ 0.9: 优秀, ≥ 0.8: 良好, ≥ 0.7: 可接受, < 0.7: 需改进。
    """
    items = [c for c in req.feature_cols if c in req.data.columns]
    if len(items) < 2:
        return AnalysisResult(
            task="cronbach_alpha", status="error", messages=["至少需要 2 个题项列"]
        )

    sub = req.data[items].dropna()
    k = len(items)
    n = len(sub)
    if n < 3:
        return AnalysisResult(task="cronbach_alpha", status="error", messages=["有效数据不足"])

    # 各项方差 + 总分方差
    item_vars = sub.var(ddof=1).values
    total_var = float(sub.sum(axis=1).var(ddof=1))
    # 审查 2026-09-16 D-2：方差带量纲，原 `< EPSILON` 误判微尺度量表为全零 → 精确零判据
    if total_var == 0:
        return AnalysisResult(
            task="cronbach_alpha", status="error", messages=["总分方差为零，无法计算 α"]
        )

    alpha = (k / (k - 1)) * (1 - np.sum(item_vars) / total_var)

    # Cronbach's α 异常值诊断警告
    warn_msgs = []
    if alpha < 0:
        warn_msgs.append(
            "⚠ Cronbach's α 为负值，可能原因: 项目编码方向不一致、"
            "负协方差项目存在、或量表结构性失效。建议检查项目编码方向。"
        )
    elif alpha > 1:
        warn_msgs.append(
            f"⚠ Cronbach's α 超过理论上限 1.0（当前 {alpha:.4f}），"
            "可能原因: 总分方差被低估或存在计算精度问题，请检查数据完整性。"
        )

    # 如果删除某项后的 α
    alpha_if_deleted = []
    for i, col in enumerate(items):
        sub_drop = sub.drop(columns=[col])
        kd = k - 1
        item_vars_drop = sub_drop.var(ddof=1).values
        total_var_drop = float(sub_drop.sum(axis=1).var(ddof=1))
        if total_var_drop > 0 and kd > 1:
            a_drop = (kd / (kd - 1)) * (1 - np.sum(item_vars_drop) / total_var_drop)
        else:
            a_drop = None
        # 项总相关：零方差列会导致 .corr() 返回 NaN，格式化时需防护
        item_total_corr = sub[col].corr(sub.drop(columns=[col]).sum(axis=1))
        if pd.isna(item_total_corr) or item_vars[i] == 0:
            corr_str = "N/A (零方差)"
        else:
            corr_str = f"{float(item_total_corr):.3f}"
        alpha_if_deleted.append(
            {
                "题项": col,
                "删除后α": f"{a_drop:.4f}" if a_drop is not None else "N/A",
                "变化": (
                    f"+{a_drop - alpha:.4f}"
                    if a_drop is not None and a_drop > alpha + 0.01
                    else f"{a_drop - alpha:.4f}"
                    if a_drop is not None
                    else "—"
                ),
                "方差": f"{item_vars[i]:.4f}",
                "项总相关": corr_str,
            }
        )

    if alpha > 1.0:
        # α > 1.0 在数学上不可能，标记为错误
        level = "无效 (超出理论范围)"
        status = "error"
    elif alpha < 0.0:
        # α < 0 表示项目编码方向不一致或负协方差，仍为可报告结果
        level = "不可接受"
        status = "ok"
    elif alpha >= 0.9:
        level = "优秀"
        status = "ok"
    elif alpha >= 0.8:
        level = "良好"
        status = "ok"
    elif alpha >= 0.7:
        level = "可接受"
        status = "ok"
    elif alpha >= 0.6:
        level = "需改进"
        status = "ok"
    else:
        level = "不可接受"
        status = "ok"

    return AnalysisResult(
        task="cronbach_alpha",
        status=status,
        tables={
            "alpha_summary": pd.DataFrame(
                {
                    "指标": ["Cronbach's α", "题项数", "样本量", "判读"],
                    "值": [f"{alpha:.4f}", str(k), str(n), level],
                }
            ),
            "item_analysis": pd.DataFrame(alpha_if_deleted),
        },
        summary=f"Cronbach's α={alpha:.3f} ({level}), {k} 题项, n={n}",
        metadata={"alpha": float(alpha), "k": k, "n": n, "level": level},
        messages=warn_msgs,
    )
