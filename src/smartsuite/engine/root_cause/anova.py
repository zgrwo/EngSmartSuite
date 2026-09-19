"""单因素方差分析。"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from statsmodels.formula.api import ols

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine._utils import shapiro_p
from smartsuite.engine.root_cause._shared import _effect_interpretation

logger = logging.getLogger(__name__)


def _eta_squared(aov_table):
    """计算偏 η² 效应量。"""
    ss_residual = aov_table["sum_sq"].get("Residual", 0)
    ss_total = sum(aov_table["sum_sq"])
    effect_sizes = {}
    # 安全获取 Resudual 自由度，防止除零和 NaN 传播 (P2 fix: NaN > any number → NaN)
    if "Residual" in aov_table.index:
        _df_r = float(aov_table.loc["Residual", "df"])
        df_residual = max(_df_r, 1) if not np.isnan(_df_r) else 1
    else:
        df_residual = 1
    ms_residual = ss_residual / df_residual

    for idx in aov_table.index:
        if idx == "Residual":
            continue
        ss_effect = aov_table.loc[idx, "sum_sq"]
        # 偏 η² = SS_effect / (SS_effect + SS_residual)
        eta2 = ss_effect / (ss_effect + ss_residual) if (ss_effect + ss_residual) > 0 else 0
        # ω² 近似
        _df_e = float(aov_table.loc[idx, "df"])
        df_effect = max(_df_e, 1) if not np.isnan(_df_e) else 1
        denom = ss_total + ms_residual
        omega2 = (ss_effect - df_effect * ms_residual) / denom if denom > 0 else 0
        omega2 = max(0, omega2)
        effect_sizes[idx] = {"η²": float(eta2), "ω²": float(omega2)}
    return effect_sizes


def anova_analysis(req: AnalysisRequest) -> AnalysisResult:
    """多因子 ANOVA 方差分析，含效应量、假设检验前提验证和事后比较。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if req.target_col not in req.data.columns:
        return AnalysisResult(
            task="anova", status="error", messages=[f"目标列「{req.target_col}」不存在于数据中"]
        )

    if len(cols) < 1:
        return AnalysisResult(
            task="anova", status="error", messages=["没有可用于 ANOVA 分析的特征列"]
        )

    # Round-2 #A2：常量目标列 → R²=-inf 且浮点噪声被当显著效应（虚假 p<0.05）
    if req.data[req.target_col].nunique(dropna=True) <= 1:
        return AnalysisResult(
            task="anova",
            status="error",
            messages=[f"目标列「{req.target_col}」为常量列（无变异），ANOVA 无意义。"],
        )

    # 审查 2026-08-19 #1.4：连续特征被当因子时水平数 = 唯一值数，
    # n=6000 连续数据 → 数千个箱体 → matplotlib 原生崩溃（进程被杀，无 traceback）。
    # 水平数超限时明确报错，引导用户改用回归或先分箱。
    _level_counts = {c: int(req.data[c].nunique(dropna=True)) for c in cols}
    _high_card = {c: k for c, k in _level_counts.items() if k > 200}
    if _high_card:
        return AnalysisResult(
            task="anova",
            status="error",
            messages=[
                "因子列水平数过多，ANOVA 按因子处理会生成数千个分组，无法分析: "
                + ", ".join(f"「{c}」({k} 个水平)" for c, k in _high_card.items())
                + "。若为连续变量请改用 regression 分析，或先对数据分箱。"
            ],
        )
    # Round-2 P3：30-200 水平空洞——水平数中等但每组样本不足（<2）时
    # 统计量无意义且常产生 NaN p 值；显式拒绝
    for _c in cols:
        _vc = req.data[_c].value_counts(dropna=True)
        if len(_vc) >= 2 and _vc.min() < 2:
            return AnalysisResult(
                task="anova",
                status="error",
                messages=[
                    f"因子列「{_c}」存在样本量不足 2 的水平（{len(_vc)} 个水平），"
                    "ANOVA 结果不可靠。请检查数据或减少因子水平数。"
                ],
            )

    # 构建公式：可选两两交互项
    # Round-2 #A2o：patsy Q() 不支持 SQL 式 '' 转义——含单引号列名必然解析失败，
    # 直接拒绝并提示重命名（此前失败被通用错误掩盖）
    if chr(39) in req.target_col or any(chr(39) in c for c in cols):
        return AnalysisResult(
            task="anova",
            status="error",
            messages=["列名包含单引号（'），patsy 公式无法解析。请重命名相关列后重试。"],
        )
    _escaped = [c.replace(chr(39), chr(39) + chr(39)) for c in cols]
    _escaped_target = req.target_col.replace(chr(39), chr(39) + chr(39))
    terms = [f"Q('{ec}')" for ec in _escaped]
    if req.params.get("interactions") and len(cols) >= 2:
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                terms.append(f"Q('{_escaped[i]}'):Q('{_escaped[j]}')")
    formula = f"Q('{_escaped_target}') ~ " + " + ".join(terms)

    warn_msgs: list[str] = []
    try:
        model = ols(formula, data=req.data).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
    except Exception:
        logger.debug("ANOVA 模型拟合失败", exc_info=True)
        return AnalysisResult(
            task="anova",
            status="error",
            messages=["ANOVA 模型拟合失败，请检查数据是否包含缺失值或非数值列"],
        )

    # ── 假设检验前提验证 ──

    # Levene 方差齐性检验（按第一个因子分组）
    first_col = cols[0]
    clean = req.data[[req.target_col, first_col]].dropna()
    group_levels = clean[first_col].unique()
    if len(group_levels) >= 2 and len(group_levels) <= 20:
        group_samples = [
            clean[clean[first_col] == lv][req.target_col].values for lv in group_levels
        ]
        if all(len(gs) >= 2 for gs in group_samples):
            _, levene_p = sp_stats.levene(*group_samples)
            if levene_p < 0.05:
                warn_msgs.append(
                    f"⚠ 方差齐性检验 (Levene) p={levene_p:.4f}<0.05，方差不等，ANOVA 结果可能不可靠"
                )

    # 残差正态性检验
    residuals = model.resid
    if len(residuals) >= 3 and len(residuals) <= 5000:
        sw_p = shapiro_p(residuals)
        if sw_p < 0.05:
            warn_msgs.append(
                f"⚠ 残差正态性检验 (Shapiro-Wilk) p={sw_p:.4f}<0.05，"
                "ANOVA 对正态性偏离有一定稳健性，但严重偏离可能影响结果"
            )
    elif len(residuals) > 5000:
        warn_msgs.append(
            "样本量 > 5000，Shapiro-Wilk 不适用。请参考 Q-Q 图或使用偏度/峰度评估正态性"
        )

    # ── 效应量计算 ──
    effect_sizes = _eta_squared(anova_table)

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="anova",
            status="error",
            messages=[f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}"],
        )
    sig_factors: list[tuple[str, str]] = []  # (raw_col_name, formatted_display_str)
    for i, col in enumerate(cols):
        _esc_key = _escaped[i]
        try:
            p_val = anova_table.loc[f"Q('{_esc_key}')", "PR(>F)"]
            es = effect_sizes.get(f"Q('{_esc_key}')", {})
            eta2 = es.get("η²", 0)
            if p_val < alpha:
                sig_factors.append((col, f"{col}(p={p_val:.4f}, η²={eta2:.3f})"))
        except KeyError:
            warn_msgs.append(f"因子「{col}」在 ANOVA 结果表中未找到")

    # ── 事后检验 (Tukey HSD) 仅当显著因子数≥1 时执行 ──
    # 限制最多 50 个水平，避免组合爆炸导致超时 (50 水平 = 1225 对)
    _MAX_TUKEY_GROUPS = 50
    posthoc_results: list[dict] = []
    if sig_factors:
        from itertools import combinations

        from statsmodels.stats.multicomp import pairwise_tukeyhsd

        for i, col in enumerate(cols):
            _esc_key = _escaped[i]
            try:
                p_val = anova_table.loc[f"Q('{_esc_key}')", "PR(>F)"]
                n_groups = req.data[col].nunique()
                if p_val < alpha and n_groups >= 2:
                    if n_groups > _MAX_TUKEY_GROUPS:
                        warn_msgs.append(
                            f"⚠ 因子「{col}」有 {n_groups} 个水平，超过事后检验上限"
                            f"({_MAX_TUKEY_GROUPS})，跳过 Tukey HSD 以避免超时"
                        )
                        continue
                    _pair = req.data[[req.target_col, col]].dropna()
                    tukey = pairwise_tukeyhsd(_pair[req.target_col], _pair[col], alpha=alpha)
                    # 使用公开 API 遍历所有成对比较
                    # NOTE: combinations(groups, 2) 与 tukey.meandiffs 的顺序相同
                    #       (两者都基于 np.triu_indices / lexicographic row-major order)
                    #       statsmodels 未文档化此约定，但 pair_idx < len() guard 提供安全网
                    groups = list(tukey.groupsunique)
                    for pair_idx, (g1, g2) in enumerate(combinations(groups, 2)):
                        if pair_idx < len(tukey.pvalues):
                            posthoc_results.append(
                                {
                                    "因子": col,
                                    "对比": f"{g1} vs {g2}",
                                    "均值差": float(tukey.meandiffs[pair_idx]),
                                    "p值": float(tukey.pvalues[pair_idx]),
                                    "显著": "是" if tukey.reject[pair_idx] else "否",
                                }
                            )
            except (KeyError, IndexError, ValueError, TypeError) as e:
                logger.debug("Tukey HSD 事后检验提取失败 (因子: %s): %s", col, e, exc_info=True)

    # ── 构建 ANOVA 增强表 (含效应量) ──
    anova_enhanced_rows = []
    for idx in anova_table.index:
        row = {
            "来源": idx,
            "自由度": int(anova_table.loc[idx, "df"]),
            "平方和": float(anova_table.loc[idx, "sum_sq"]),
            "均方": float(anova_table.loc[idx, "sum_sq"]) / max(anova_table.loc[idx, "df"], 1),
            "F值": float(anova_table.loc[idx, "F"])
            if not pd.isna(anova_table.loc[idx, "F"])
            else None,
            "p值": float(anova_table.loc[idx, "PR(>F)"])
            if not pd.isna(anova_table.loc[idx, "PR(>F)"])
            else None,
        }
        es = effect_sizes.get(idx, {})
        row["η²"] = es.get("η²", None)
        row["ω²"] = es.get("ω²", None)
        row["效应量解读"] = (
            _effect_interpretation(es.get("η²", 0)) if es.get("η²") is not None else ""
        )
        anova_enhanced_rows.append(row)
    anova_enhanced = pd.DataFrame(anova_enhanced_rows)

    # ── 汇总 ──
    if sig_factors:
        summary = (
            f"显著影响「{req.target_col}」的因子: {'; '.join(sf[1] for sf in sig_factors)}。"
            f"模型 R²={model.rsquared:.3f}, 调整 R²={model.rsquared_adj:.3f}"
        )
    else:
        summary = (
            f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})。"
            f"模型 R²={model.rsquared:.4f}, 调整 R²={model.rsquared_adj:.4f}"
        )

    coef_df = pd.DataFrame(
        {
            "变量": list(model.params.index)
            if hasattr(model.params, "index")
            else model.model.exog_names,
            "系数": np.asarray(model.params),
            "标准误": np.asarray(model.bse),
            "t值": np.asarray(model.tvalues),
            "p值": np.asarray(model.pvalues),
        }
    )

    # ── 箱线图：按第一个显著因子分组，含显著性注释 ──
    fig_box = Figure(figsize=(max(len(cols) * 2.0, 6), 4.5))
    ax_box = fig_box.add_subplot(111)
    group_col = sig_factors[0][0] if sig_factors else cols[0]
    groups = req.data[[req.target_col, group_col]].dropna()
    group_names = sorted(groups[group_col].unique(), key=str)
    group_data = [groups[groups[group_col] == g][req.target_col].values for g in group_names]
    bp = ax_box.boxplot(
        group_data,
        tick_labels=[f"{g}\n(n={len(d)})" for g, d in zip(group_names, group_data, strict=True)],
        patch_artist=True,
        widths=0.5,
    )
    # 根据分组数量自适应标签旋转
    if len(group_names) > 6:
        for label in ax_box.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")
    ax_box.tick_params(labelsize=9)
    for patch in bp["boxes"]:
        patch.set_facecolor(PALETTE["data"]["secondary"])
    # 叠加散点
    for i, gdata in enumerate(group_data, 1):
        # 可复现 jitter（种子基于组序号）
        jitter = np.random.default_rng(20260819 + i).uniform(-0.12, 0.12, len(gdata))
        ax_box.scatter(
            np.full(len(gdata), i) + jitter,
            gdata,
            alpha=0.3,
            s=10,
            color=PALETTE["misc"]["grid"],
            zorder=3,
        )
    ax_box.set_xlabel(group_col, fontsize=10)
    ax_box.set_ylabel(req.target_col, fontsize=10)
    ax_box.set_title(f"箱线图 — {req.target_col} by {group_col}", fontsize=11)
    fig_box.tight_layout()
    figures = [fig_box]

    # ── 交互效应图 (≥2个因子时) ──
    if len(cols) >= 2:
        f1, f2 = cols[0], cols[1]
        sub_int = req.data[[req.target_col, f1, f2]].dropna()
        # 仅对类别有限的列做交互图
        if sub_int[f1].nunique() <= 10 and sub_int[f2].nunique() <= 10:
            try:
                means = sub_int.groupby([f1, f2])[req.target_col].mean().unstack()
                fig_int = Figure(figsize=(max(len(means.columns) * 1.5, 5), 4))
                ax_int = fig_int.add_subplot(111)
                for col_name in means.columns:
                    ax_int.plot(
                        means.index,
                        means[col_name],
                        "o-",
                        markersize=6,
                        linewidth=1.5,
                        label=str(col_name),
                    )
                ax_int.set_xlabel(f1, fontsize=10)
                ax_int.set_ylabel(f"{req.target_col} 均值", fontsize=10)
                ax_int.set_title(f"交互效应图 — {f1} × {f2}", fontsize=11)
                ax_int.legend(title=f2, fontsize=8, title_fontsize=8)
                ax_int.grid(True, alpha=0.3)
                fig_int.tight_layout()
                figures.append(fig_int)
            except Exception:
                logger.debug("交互效应图生成失败", exc_info=True)  # 交互图生成失败不影响主分析

    # ── 返回 ──
    result_tables = {
        "anova_enhanced": anova_enhanced,
        "coefficients": coef_df,
    }
    if posthoc_results:
        result_tables["posthoc_tukey"] = pd.DataFrame(posthoc_results)

    return AnalysisResult(
        task="anova",
        tables=result_tables,
        figures=figures,
        summary=summary,
        metadata={
            "r_squared": model.rsquared,
            "r_squared_adj": model.rsquared_adj,
            "effect_sizes": effect_sizes,
            "effect_size_ci": _eta_squared_ci(
                float(model.fvalue), int(model.df_model), int(model.df_resid)
            ),
        },
        messages=warn_msgs,
    )


def _eta_squared_ci(f_stat: float, df1: int, df2: int, alpha: float = 0.05) -> tuple[float, float]:
    """η² 的 95% CI（基于非中心 F 分布反演）。

    使用 Steiger (2004) 方法：通过非中心 F 的 CDF 反推非中心参数 λ，
    再转换为 η² = λ/(λ+N)。
    """
    if df1 < 1 or df2 < 1 or f_stat < 0:
        return (float("nan"), float("nan"))
    try:
        from scipy.optimize import brentq

        n_total = df1 + df2 + 1

        def _cdf_minus_target(lam, target):
            return sp_stats.ncf.cdf(f_stat, df1, df2, max(0.0, lam)) - target

        # λ_L: cdf(F_obs | λ_L) = 1 - alpha/2
        # cdf 随 λ 增大而减小
        target_lo = 1.0 - alpha / 2
        cdf_at_0 = float(sp_stats.ncf.cdf(f_stat, df1, df2, 0))
        if cdf_at_0 >= target_lo:
            # 需要增大 λ 使 cdf 降低到 target_lo
            hi_bound = max(f_stat * df1 + 50, 100)
            while (
                float(sp_stats.ncf.cdf(f_stat, df1, df2, hi_bound)) > target_lo and hi_bound < 1e6
            ):
                hi_bound *= 3
            try:
                lam_l = brentq(_cdf_minus_target, 0, hi_bound, args=(target_lo,), xtol=1e-8)
            except (ValueError, RuntimeError):
                lam_l = 0.0
        else:
            lam_l = 0.0

        # λ_U: cdf(F_obs | λ_U) = alpha/2
        target_hi = alpha / 2
        hi_bound = max(f_stat * df1 * 4 + 100, 200)
        while float(sp_stats.ncf.cdf(f_stat, df1, df2, hi_bound)) > target_hi and hi_bound < 1e6:
            hi_bound *= 3
        try:
            lam_u = brentq(_cdf_minus_target, 0, hi_bound, args=(target_hi,), xtol=1e-8)
        except (ValueError, RuntimeError):
            lam_u = 0.0

        eta2_lo = max(0.0, lam_l / (lam_l + n_total))
        eta2_hi = min(1.0, lam_u / (lam_u + n_total))
        if eta2_lo > eta2_hi:
            eta2_lo, eta2_hi = 0.0, max(eta2_lo, eta2_hi)
        return (float(eta2_lo), float(eta2_hi))
    except Exception:
        logger.debug("η² CI 计算失败", exc_info=True)
        return (float("nan"), float("nan"))
