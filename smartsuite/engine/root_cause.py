import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.engine._constants import (
    COHENS_D_LARGE, COHENS_D_MEDIUM, COHENS_D_SMALL,
    EPSILON, ETA_SQ_LARGE, ETA_SQ_MEDIUM, ETA_SQ_SMALL,
    SIG_EXTREME, SIG_HIGH, SIG_MODERATE, VIF_THRESHOLD,
)

logger = logging.getLogger(__name__)

from sklearn.tree import DecisionTreeRegressor, plot_tree
from statsmodels.formula.api import ols
from statsmodels.nonparametric.smoothers_lowess import lowess
from statsmodels.stats.outliers_influence import variance_inflation_factor

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE


def _significance_stars(p):
    """显著性星号标记（使用 _constants.py 中的 SIG_* 阈值）。"""
    if p is None or np.isnan(p):
        return ""
    if p < SIG_EXTREME:
        return "***"
    elif p < SIG_HIGH:
        return "**"
    elif p < SIG_MODERATE:
        return "*"
    return ""


def _binary_encode(series, col_name: str = ""):
    """验证二分类列并编码为 0/1。

    返回 (binary_array, error_msg)。
    成功时 error_msg 为 None，binary_array 为 int 型 numpy 数组。
    失败时 binary_array 为 None，error_msg 为中文错误描述。

    编码规则: 排序后的较大值 (sorted[-1]) 映射为 1，较小值映射为 0。
    注意: NaN 值会被编码为 0（因为 NaN != uv[1] 返回 False），调用方
    如需区分 NaN 和真实值，应先自行处理缺失值。
    """
    vals = series.dropna()
    unique_vals = vals.unique()
    if len(unique_vals) != 2:
        label = f"「{col_name}」" if col_name else "该列"
        return None, f"{label}不是二分类数据（唯一值数={len(unique_vals)}，需要恰好2个）"
    uv = sorted(unique_vals)
    n_nan = int(series.isna().sum())
    if n_nan > 0:
        logger.warning(
            "列「%s」存在 %d 个缺失值，将被编码为 0（与「%s」归为一类）。"
            "如需区分缺失值，请先填充后再分析。",
            col_name or "未知", n_nan, str(uv[0]),
        )
    return (series == uv[1]).astype(int).values, None


def correlation_analysis(req: AnalysisRequest) -> AnalysisResult:
    """相关性矩阵分析（Pearson/Spearman），含多重比较校正和显著性标记。"""
    if req.target_col not in req.data.columns:
        return AnalysisResult(task="correlation", status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中"])
    # 去重：防止 target_col 同时出现在 feature_cols 中导致重复列
    cols = list(dict.fromkeys(req.feature_cols + [req.target_col]))
    cols = [c for c in cols if c in req.data.columns]

    # 校验所有列为数值型，避免非数值列静默失败
    non_numeric = [c for c in cols if not pd.api.types.is_numeric_dtype(req.data[c])]
    if non_numeric:
        return AnalysisResult(task="correlation", status="error",
            messages=[f"以下列非数值型，无法计算相关性: {non_numeric}。"
                      "请使用数据预处理将类别列转换为数值型。"])

    method = req.params.get("method", "pearson")  # "pearson" | "spearman" | "kendall"
    if method == "spearman":
        corr = req.data[cols].corr(method="spearman")
        corr_label = "Spearman ρ"
    elif method == "kendall":
        corr = req.data[cols].corr(method="kendall")
        corr_label = "Kendall τ"
    else:
        corr = req.data[cols].corr(method="pearson")
        corr_label = "Pearson r"

    # p 值矩阵
    pmat = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for c1 in cols:
        for c2 in cols:
            mask = req.data[c1].notna() & req.data[c2].notna()
            if mask.sum() >= 3:
                if method == "spearman":
                    _, p = sp_stats.spearmanr(
                        req.data.loc[mask, c1], req.data.loc[mask, c2]
                    )
                elif method == "kendall":
                    _, p = sp_stats.kendalltau(
                        req.data.loc[mask, c1], req.data.loc[mask, c2]
                    )
                else:
                    _, p = sp_stats.pearsonr(
                        req.data.loc[mask, c1], req.data.loc[mask, c2]
                    )
                pmat.loc[c1, c2] = p
            else:
                pmat.loc[c1, c2] = np.nan

    # ── 多重比较校正 (Bonferroni) — 向量化 ──
    n_comparisons = len(cols) * (len(cols) - 1) // 2
    pmat_corrected = pmat.copy()
    if n_comparisons > 0:
        arr = np.array(pmat_corrected, dtype=float)  # 强制拷贝为可写数组
        triu_idx = np.triu_indices_from(arr, k=1)
        corrected = np.minimum(arr * n_comparisons, 1.0)
        arr[triu_idx] = corrected[triu_idx]
        # 对称镜像到下三角
        arr[(triu_idx[1], triu_idx[0])] = corrected[triu_idx]
        pmat_corrected = pd.DataFrame(arr, index=pmat.index, columns=pmat.columns)

    # ── 相关性 + 显著性标记矩阵 ──
    annotated = pd.DataFrame(index=cols, columns=cols, dtype=str)
    for i, c1 in enumerate(cols):
        for j, c2 in enumerate(cols):
            r = corr.iloc[i, j]
            p = pmat.iloc[i, j]
            stars = _significance_stars(p)  # _significance_stars 内部处理 NaN/None
            annotated.iloc[i, j] = f"{r:+.2f}{stars}"

    # 按相关系数降序排列（展示用）
    target_corr = corr[req.target_col].drop(req.target_col).sort_values(ascending=False)
    # 按绝对值找最强相关因子（正负同等对待）
    target_corr_abs = target_corr.abs().sort_values(ascending=False)
    top_factor = target_corr_abs.index[0] if len(target_corr_abs) > 0 else "N/A"
    top_value = target_corr[top_factor] if top_factor != "N/A" else 0

    # ── p 值校正报告 ──
    sig_before = int((pmat.values[np.triu_indices_from(pmat.values, k=1)] < 0.05).sum())
    sig_after = int((pmat_corrected.values[np.triu_indices_from(pmat_corrected.values, k=1)] < 0.05).sum())
    correction_note = (
        f"Bonferroni校正前 {sig_before} 对显著，校正后 {sig_after} 对显著"
        f"（{n_comparisons} 对比较）"
    )

    # ── 零方差提前检查：避免浪费图表生成计算 (P2 fix: 移到图表生成之前) ──
    if pd.isna(top_value):
        return AnalysisResult(task="correlation", status="error",
            messages=[f"目标列「{req.target_col}」方差为零（常量列），无法计算相关性分析。"
                      f"请检查数据中该列是否所有值相同。"])

    # ── 热力图增强：只标注显著单元格，添加星号 ──
    n = len(cols)
    fig = Figure(figsize=(max(n*0.95, 6), max(n*0.85, 4.5)))
    ax = fig.add_subplot(111)
    im = ax.imshow(corr.values, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
    ax.set_xticks(range(n))
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(n))
    ax.set_yticklabels(cols, fontsize=9)
    for i in range(n):
        for j in range(n):
            v = corr.values[i, j]
            p_raw = pmat.iloc[i, j]
            p_adj = pmat_corrected.iloc[i, j]
            if i == j:
                continue
            # 只标注 |r|>0.3 或显著的单元格
            is_sig = not np.isnan(p_adj) and p_adj < 0.05
            if abs(v) > 0.3 or is_sig:
                stars = _significance_stars(p_raw) if not np.isnan(p_raw) else ""
                ax.text(j, i, f"{v:+.2f}{stars}", ha="center", va="center",
                        fontsize=8 if n <= 15 else 6,
                        fontweight="bold" if is_sig else "normal",
                        color="white" if abs(v) > 0.65 else "black")
    fig.colorbar(im, ax=ax, shrink=0.8, label=corr_label)
    ax.set_title(
        f"相关性热力图 — {req.target_col}\n"
        f"({corr_label} | {correction_note})",
        fontsize=10,
    )
    fig.tight_layout()

    # ── 目标变量排序相关表 ──
    target_p_adj = {}
    for c in target_corr.index:
        ci = cols.index(c)
        ti = cols.index(req.target_col)
        target_p_adj[c] = float(pmat_corrected.iloc[ci, ti])

    # ── 初始化图表列表 ──
    figures = [fig]

    # ── 散点矩阵：目标 vs Top-N 相关性变量（最多 4×4 确保可读性）──
    top_n_scatter = min(4, len(target_corr))
    if top_n_scatter >= 2:
        top_vars = list(target_corr.index[:top_n_scatter])
        scatter_cols = [req.target_col] + [c for c in top_vars if c != req.target_col]
        scatter_cols = scatter_cols[:4]  # 最多 4×4
        if len(scatter_cols) >= 2:
            try:
                n_s = len(scatter_cols)
                fig_scatter = Figure(figsize=(n_s * 2.8, n_s * 2.5))
                for ri, cv1 in enumerate(scatter_cols):
                    for ci, cv2 in enumerate(scatter_cols):
                        ax = fig_scatter.add_subplot(n_s, n_s, ri * n_s + ci + 1)
                        sub = req.data[[cv1, cv2]].dropna()
                        if len(sub) < 2:
                            continue
                        if ri == ci:
                            vals = sub[cv1].values
                            ax.hist(vals, bins=min(15, len(vals)//2), color=PALETTE["data"]["secondary"],
                                   edgecolor="white", alpha=0.8)
                            ax.set_title(cv1, fontsize=9)
                        else:
                            ax.scatter(sub[cv1].values, sub[cv2].values, s=8,
                                      alpha=0.5, color=PALETTE["data"]["primary"])
                            # LOWESS 平滑趋势线
                            if len(sub) >= 20:
                                try:
                                    smoothed = lowess(sub[cv2].values, sub[cv1].values,
                                                     frac=0.3, return_sorted=True)
                                    ax.plot(smoothed[:, 0], smoothed[:, 1], "-",
                                           color=PALETTE["target"]["primary"], linewidth=1.5, alpha=0.7)
                                except (ValueError, RuntimeError):
                                    logger.debug("LOWESS 平滑失败", exc_info=True)
                                    pass
                            r_val = corr.loc[cv1, cv2] if cv1 in corr.index and cv2 in corr.columns else 0
                            ax.annotate(f"r={r_val:.2f}", xy=(0.95, 0.05),
                                       xycoords="axes fraction",
                                       ha="right", fontsize=7.5, color=PALETTE["target"]["primary"],
                                       bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7))
                        if ri == n_s - 1:
                            ax.set_xlabel(cv2, fontsize=8)
                        if ci == 0:
                            ax.set_ylabel(cv1, fontsize=8)
                        ax.tick_params(labelsize=7.5)
                fig_scatter.suptitle(
                    f"散点矩阵 — {req.target_col} vs Top{top_n_scatter} 相关变量",
                    fontsize=10,
                )
                fig_scatter.tight_layout()
                figures.append(fig_scatter)
            except Exception:
                logger.debug("散点矩阵生成失败", exc_info=True)
                pass  # 散点矩阵失败不影响主分析

    # ── 偏相关分析（控制混淆变量）──
    control_vars = req.params.get("control_vars", [])
    control_vars = [c for c in control_vars if c in req.data.columns and c != req.target_col
                    and pd.api.types.is_numeric_dtype(req.data[c])]
    direction = "正相关" if top_value >= 0 else "负相关"
    summary_parts = [
        f"与「{req.target_col}」相关性最强(|r|)的因子是「{top_factor}」"
        f"({corr_label.split()[0]}={top_value:+.3f}, {direction}, |r|={abs(top_value):.3f})",
        correction_note,
    ]
    partial_corr_meta: dict = {}
    partial_tables: dict = {}

    if control_vars and len(control_vars) > 0:
        # 计算偏相关：对每一对 (target, feature)，控制 control_vars
        feature_cols_only = [c for c in cols if c != req.target_col and c not in control_vars]
        partial_results = []
        for fc in feature_cols_only:
            all_vars = [req.target_col, fc] + control_vars
            sub = req.data[all_vars].dropna()
            if len(sub) < len(control_vars) + 3:
                continue
            # 回归 target ~ control_vars，取残差
            X_ctrl_target = sm.add_constant(sub[control_vars].astype(float))
            resid_target = sm.OLS(sub[req.target_col].astype(float), X_ctrl_target).fit().resid
            # 回归 feature ~ control_vars，取残差
            X_ctrl_feat = sm.add_constant(sub[control_vars].astype(float))
            resid_feat = sm.OLS(sub[fc].astype(float), X_ctrl_feat).fit().resid
            # 残差相关
            if len(resid_target) >= 3:
                r_partial, _ = sp_stats.pearsonr(resid_target, resid_feat)
                # 偏相关自由度修正: 残差来自两次回归(各消耗 k+1 df),
                # 偏相关有效 df = n - k - 2 (k=控制变量数)
                n = len(resid_target)
                k_ctrl = len(control_vars)
                df_partial = max(1, n - k_ctrl - 2)
                t_partial = r_partial * np.sqrt(df_partial / (1 - r_partial**2 + EPSILON))
                p_partial = float(2 * sp_stats.t.sf(abs(t_partial), df_partial))
            else:
                r_partial, p_partial = np.nan, np.nan
            # 零阶相关（原始）
            r_zero = corr.loc[req.target_col, fc] if req.target_col in corr.index and fc in corr.columns else np.nan
            partial_results.append({
                "因子": fc,
                "零阶相关(r)": round(float(r_zero), 4) if not np.isnan(r_zero) else None,
                "偏相关(r_partial)": round(float(r_partial), 4),
                "p值": round(float(p_partial), 4),
                "变化": (
                    "抑制" if not np.isnan(r_zero) and abs(r_partial) > abs(r_zero) + 0.05
                    else "削弱" if not np.isnan(r_zero) and abs(r_partial) < abs(r_zero) - 0.05
                    else "稳定"
                ),
            })
            partial_corr_meta[fc] = {
                "r_zero": float(r_zero) if not np.isnan(r_zero) else None,
                "r_partial": float(r_partial),
                "p_partial": float(p_partial),
            }

        if partial_results:
            partial_df = pd.DataFrame(partial_results).sort_values(
                "偏相关(r_partial)", key=abs, ascending=False
            )
            partial_tables["partial_correlations"] = partial_df

            # 偏相关柱状图对比
            fig_partial = Figure(figsize=(max(len(partial_df)*0.9, 6), 4))
            ax_p = fig_partial.add_subplot(111)
            x = np.arange(len(partial_df))
            width = 0.35
            zero_vals = [v if v is not None else 0 for v in partial_df["零阶相关(r)"]]
            partial_vals = partial_df["偏相关(r_partial)"].values
            ax_p.bar(x - width/2, zero_vals, width, label="零阶相关",
                    color=PALETTE["data"]["secondary"], alpha=0.8)
            ax_p.bar(x + width/2, partial_vals, width, label="偏相关(控制混淆)",
                    color=PALETTE["data"]["primary"], alpha=0.9)
            ax_p.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
            ax_p.set_xticks(x)
            ax_p.set_xticklabels(partial_df["因子"], rotation=45, ha="right", fontsize=9)
            ax_p.set_ylabel("相关系数", fontsize=10)
            ax_p.set_title(
                f"偏相关分析 — {req.target_col} | "
                f"控制变量: {', '.join(control_vars)}",
                fontsize=10,
            )
            ax_p.legend(fontsize=8)
            fig_partial.tight_layout()
            figures.append(fig_partial)

            # 最显著偏相关
            top_partial = partial_df.iloc[0]
            change_note = (
                f"（控制{', '.join(control_vars)}后"
                f"{'增强' if top_partial['变化'] == '抑制' else '减弱'}）"
                if top_partial["变化"] != "稳定" else ""
            )
            summary_parts.append(
                f"控制「{', '.join(control_vars)}」后，"
                f"最强偏相关: {top_partial['因子']} "
                f"(r_partial={top_partial['偏相关(r_partial)']:.3f}){change_note}"
            )

    return AnalysisResult(
        task="correlation",
        tables={
            "correlation_matrix": corr,
            "p_values_raw": pmat.astype(float),
            "p_values_corrected": pmat_corrected.astype(float),
            "annotated_matrix": annotated,
            **partial_tables,
        },
        figures=figures,
        summary="。".join(summary_parts),
        metadata={
            "target_correlations": target_corr.to_dict(),
            "method": method,
            "n_comparisons": n_comparisons,
            "sig_before_correction": sig_before,
            "sig_after_correction": sig_after,
            "target_p_adjusted": target_p_adj,
            "partial_correlations": partial_corr_meta,
            "control_vars": control_vars,
        },
    )


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


def threshold_label(value, thresholds, labels=("可忽略", "小", "中", "大")):
    """通用效应量阈值标签函数。

    Args:
        value: 待判定的效应量值
        thresholds: 升序阈值列表，如 [0.01, 0.06, 0.14]
        labels: 对应标签元组，比 thresholds 多一个元素
    """
    if not np.isfinite(value):
        return "N/A"
    for t, label in zip(thresholds, labels):
        if value < t:
            return label
    return labels[-1]


def _effect_interpretation(eta2):
    """η² 效应量解读 (Cohen 准则)。"""
    return threshold_label(eta2, [ETA_SQ_SMALL, ETA_SQ_MEDIUM, ETA_SQ_LARGE])


def _cramers_v_interpretation(v):
    """Cramér's V 效应量解读 (df≥1 通用阈值, Cohen 1988)。"""
    return threshold_label(v, [0.1, 0.3, 0.5])


def anova_analysis(req: AnalysisRequest) -> AnalysisResult:
    """多因子 ANOVA 方差分析，含效应量、假设检验前提验证和事后比较。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if req.target_col not in req.data.columns:
        return AnalysisResult(task="anova", status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中"])

    if len(cols) < 1:
        return AnalysisResult(task="anova", status="error",
            messages=["没有可用于 ANOVA 分析的特征列"])

    # 构建公式：可选两两交互项
    # 对列名中的单引号做 SQL-style 转义（patsy Q() 语法要求）
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
        return AnalysisResult(task="anova", status="error",
            messages=["ANOVA 模型拟合失败，请检查数据是否包含缺失值或非数值列"])

    # ── 假设检验前提验证 ──

    # Levene 方差齐性检验（按第一个因子分组）
    first_col = cols[0]
    clean = req.data[[req.target_col, first_col]].dropna()
    group_levels = clean[first_col].unique()
    if len(group_levels) >= 2 and len(group_levels) <= 20:
        group_samples = [clean[clean[first_col] == lv][req.target_col].values
                        for lv in group_levels]
        if all(len(gs) >= 2 for gs in group_samples):
            _, levene_p = sp_stats.levene(*group_samples)
            if levene_p < 0.05:
                warn_msgs.append(
                    f"⚠ 方差齐性检验 (Levene) p={levene_p:.4f}<0.05，"
                    f"方差不等，ANOVA 结果可能不可靠"
                )

    # 残差正态性检验
    residuals = model.resid
    if len(residuals) >= 3 and len(residuals) <= 5000:
        _, sw_p = sp_stats.shapiro(residuals)
        if sw_p < 0.05:
            warn_msgs.append(
                f"⚠ 残差正态性检验 (Shapiro-Wilk) p={sw_p:.4f}<0.05，"
                "ANOVA 对正态性偏离有一定稳健性，但严重偏离可能影响结果"
            )
    elif len(residuals) > 5000:
        warn_msgs.append(
            "样本量 > 5000，Shapiro-Wilk 不适用。"
            "请参考 Q-Q 图或使用偏度/峰度评估正态性"
        )

    # ── 效应量计算 ──
    effect_sizes = _eta_squared(anova_table)

    alpha = req.params.get("alpha", 0.05)
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
                    tukey = pairwise_tukeyhsd(
                        req.data[req.target_col].dropna(),
                        req.data.loc[req.data[req.target_col].notna(), col],
                        alpha=alpha
                    )
                    # 使用公开 API 遍历所有成对比较
                    groups = list(tukey.groupsunique)
                    for pair_idx, (g1, g2) in enumerate(combinations(groups, 2)):
                        if pair_idx < len(tukey.pvalues):
                            posthoc_results.append({
                                "因子": col,
                                "对比": f"{g1} vs {g2}",
                                "均值差": float(tukey.meandiffs[pair_idx]),
                                "p值": float(tukey.pvalues[pair_idx]),
                                "显著": "是" if tukey.reject[pair_idx] else "否",
                            })
            except (KeyError, IndexError, ValueError) as e:
                logger.debug("Tukey HSD 事后检验提取失败 (因子: %s): %s", col, e, exc_info=True)

    # ── 构建 ANOVA 增强表 (含效应量) ──
    anova_enhanced_rows = []
    for idx in anova_table.index:
        row = {
            "来源": idx,
            "自由度": int(anova_table.loc[idx, "df"]),
            "平方和": float(anova_table.loc[idx, "sum_sq"]),
            "均方": float(anova_table.loc[idx, "sum_sq"]) / max(anova_table.loc[idx, "df"], 1),
            "F值": float(anova_table.loc[idx, "F"]) if not pd.isna(anova_table.loc[idx, "F"]) else None,
            "p值": float(anova_table.loc[idx, "PR(>F)"]) if not pd.isna(anova_table.loc[idx, "PR(>F)"]) else None,
        }
        es = effect_sizes.get(idx, {})
        row["η²"] = es.get("η²", None)
        row["ω²"] = es.get("ω²", None)
        row["效应量解读"] = _effect_interpretation(es.get("η²", 0)) if es.get("η²") is not None else ""
        anova_enhanced_rows.append(row)
    anova_enhanced = pd.DataFrame(anova_enhanced_rows)

    # ── 汇总 ──
    if sig_factors:
        summary = (f"显著影响「{req.target_col}」的因子: {'; '.join(sf[1] for sf in sig_factors)}。"
                   f"模型 R²={model.rsquared:.3f}, 调整 R²={model.rsquared_adj:.3f}")
    else:
        summary = (f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})。"
                   f"模型 R²={model.rsquared:.4f}, 调整 R²={model.rsquared_adj:.4f}")

    coef_df = pd.DataFrame({
        "变量": list(model.params.index) if hasattr(model.params, 'index') else model.model.exog_names,
        "系数": np.asarray(model.params),
        "标准误": np.asarray(model.bse), "t值": np.asarray(model.tvalues), "p值": np.asarray(model.pvalues),
    })

    # ── 箱线图：按第一个显著因子分组，含显著性注释 ──
    fig_box = Figure(figsize=(max(len(cols)*2.0, 6), 4.5))
    ax_box = fig_box.add_subplot(111)
    group_col = sig_factors[0][0] if sig_factors else cols[0]
    groups = req.data[[req.target_col, group_col]].dropna()
    group_names = sorted(groups[group_col].unique(), key=str)
    group_data = [groups[groups[group_col] == g][req.target_col].values for g in group_names]
    bp = ax_box.boxplot(group_data, tick_labels=[
        f"{g}\n(n={len(d)})" for g, d in zip(group_names, group_data)
    ], patch_artist=True, widths=0.5)
    # 根据分组数量自适应标签旋转
    if len(group_names) > 6:
        for label in ax_box.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")
    ax_box.tick_params(labelsize=9)
    for patch in bp['boxes']:
        patch.set_facecolor(PALETTE["data"]["secondary"])
    # 叠加散点
    for i, gdata in enumerate(group_data, 1):
        jitter = np.random.uniform(-0.12, 0.12, len(gdata))
        ax_box.scatter(np.full(len(gdata), i) + jitter, gdata,
                       alpha=0.3, s=10, color=PALETTE["misc"]["grid"], zorder=3)
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
                fig_int = Figure(figsize=(max(len(means.columns)*1.5, 5), 4))
                ax_int = fig_int.add_subplot(111)
                for col_name in means.columns:
                    ax_int.plot(means.index, means[col_name], "o-", markersize=6,
                               linewidth=1.5, label=str(col_name))
                ax_int.set_xlabel(f1, fontsize=10)
                ax_int.set_ylabel(f"{req.target_col} 均值", fontsize=10)
                ax_int.set_title(f"交互效应图 — {f1} × {f2}", fontsize=11)
                ax_int.legend(title=f2, fontsize=8, title_fontsize=8)
                ax_int.grid(True, alpha=0.3)
                fig_int.tight_layout()
                figures.append(fig_int)
            except Exception:
                logger.debug("交互效应图生成失败", exc_info=True)
                pass  # 交互图生成失败不影响主分析

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
        },
        messages=warn_msgs,
    )


def _cohens_d(x, y, warn_list: list[str] | None = None):
    """Cohen's d 效应量 (Hedges' g 校正小样本偏差)。

    当样本量不足时返回 0.0 并向 warn_list 追加警告消息。
    """
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        if warn_list is not None:
            warn_list.append(
                f"⚠ 效应量计算: 样本量不足 (n1={n1}, n2={n2})，Cohen's d 无法可靠估计，已返回 0"
            )
        return 0.0
    s1, s2 = np.std(x, ddof=1), np.std(y, ddof=1)
    # 合并标准差
    sp = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    if sp < EPSILON:
        return 0.0
    d = (np.mean(x) - np.mean(y)) / sp
    # Hedges' g 小样本校正因子
    correction = 1 - 3 / (4 * (n1 + n2) - 9)
    return float(d * correction)


def _cliffs_delta(x, y):
    """Cliff's delta — 非参数效应量，适用于 Mann-Whitney。值域 [-1, 1]。

    使用基于排序的 O(n log n) 向量化实现，避免 O(n²) Python 循环。
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    n1, n2 = len(x_arr), len(y_arr)
    if n1 == 0 or n2 == 0:
        return 0.0

    # 对 y 排序后，用 searchsorted 批量统计
    y_sorted = np.sort(y_arr)
    # lt_count: y 中严格小于各 xi 的元素总数
    lt_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="left")))
    # le_count: y 中小于等于各 xi 的元素总数
    le_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="right")))
    # dominance = #(xi > yj) - #(xi < yj) = 2*lt_count + eq_count - n1*n2
    dominance = lt_count + le_count - n1 * n2
    return float(dominance / (n1 * n2))


def _effect_size_label(d, test_type="cohens_d"):
    """效应量大小解读标签（Cohen's d 使用 _constants.py 阈值）。"""
    ad = abs(d)
    if test_type == "cohens_d":
        return threshold_label(ad, [COHENS_D_SMALL, COHENS_D_MEDIUM, COHENS_D_LARGE])
    if test_type == "correlation":
        return threshold_label(ad, [0.1, 0.3, 0.5])
    # cliffs_delta
    return threshold_label(ad, [0.147, 0.33, 0.474])


# ── 假设检验分支调度 ── 新增检验类型只需在此注册 + 实现私有函数
def _ht_cochran_q(req: AnalysisRequest) -> AnalysisResult:
    """Cochran Q 检验 (3+ 配对二分类条件)。"""
    measure_cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(measure_cols) < 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=["Cochran Q 需要至少 2 个二分类条件列"])
    sub = req.data[measure_cols].dropna()
    if len(sub) < 3:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=["有效数据不足(至少3行)"])
    k = len(measure_cols)
    binary = pd.DataFrame(index=sub.index)
    for c in measure_cols:
        encoded, err = _binary_encode(sub[c], c)
        if err:
            return AnalysisResult(task="hypothesis_test", status="error", messages=[err])
        binary[c] = encoded
    col_sums = binary.sum(axis=0).values
    row_sums = binary.sum(axis=1).values
    Q = (k - 1) * (k * np.sum(col_sums**2) - np.sum(col_sums)**2)
    denom = k * np.sum(row_sums) - np.sum(row_sums**2)
    if denom < EPSILON:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=["Cochran Q 无法计算：所有样本在各条件下的响应完全一致（分母为零），"
                      "不满足检验前提。"])
    Q = Q / denom
    p = float(sp_stats.chi2.sf(max(Q, 0), k - 1))
    test_name = f"Cochran Q 检验 ({k} 条件)"
    alpha = req.params.get("alpha", 0.05)
    conclusion = "条件间存在显著差异" if p < alpha else "条件间未发现显著差异"
    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量(Q)": [f"{Q:.3f}"],
            "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
            "条件数": [str(k)], "样本量": [str(len(sub))],
            "结论": [conclusion],
        })},
        summary=f"Cochran Q: {conclusion} (Q={Q:.2f}, p={p:.4f}, k={k})",
        metadata={"test": test_name, "statistic": float(Q), "p_value": float(p),
                 "alpha": alpha, "k": k, "n": len(sub)},
    )


def _ht_ks(req: AnalysisRequest) -> AnalysisResult:
    """Kolmogorov-Smirnov 双样本检验。"""
    group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=["KS 检验需要恰好 2 个分组"])
    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()
    stat, p = sp_stats.ks_2samp(g1, g2)
    test_name = f"Kolmogorov-Smirnov 检验 ({groups[0]} vs {groups[1]})"
    alpha = req.params.get("alpha", 0.05)
    conclusion = "两样本分布存在显著差异" if p < alpha else "未发现分布差异"
    fig = Figure(figsize=(7, 4))
    ax = fig.add_subplot(111)
    ax.hist(g1, bins=20, alpha=0.6, color=PALETTE["data"]["secondary"], density=True, label=str(groups[0]))
    ax.hist(g2, bins=20, alpha=0.6, color=PALETTE["contrast"]["b"], density=True, label=str(groups[1]))
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_title(f"{test_name} (D={stat:.3f}, p={p:.4f})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量(D)": [f"{stat:.4f}"],
            "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
            "结论": [conclusion],
        })},
        figures=[fig],
        summary=f"KS 检验: {conclusion} (D={stat:.3f}, p={p:.4f})",
        metadata={"test": test_name, "statistic": float(stat),
                 "p_value": float(p), "alpha": alpha},
    )


def _ht_friedman(req: AnalysisRequest) -> AnalysisResult:
    """Friedman 检验 (非参数重复测量)。"""
    measure_cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(measure_cols) < 2:
        measure_cols = [req.target_col] + [c for c in req.feature_cols[:2] if c in req.data.columns]
    sub = req.data[measure_cols].dropna()
    if len(sub) < 3 or len(measure_cols) < 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=["Friedman 检验需要至少 2 个重复测量条件和 3 个完整观测"])
    stat, p = sp_stats.friedmanchisquare(*[sub[c].values for c in measure_cols])
    test_name = f"Friedman 检验 (非参数重复测量, {len(measure_cols)} 条件)"
    n = len(sub)
    k = len(measure_cols)
    kendall_w = float(stat / (n * (k - 1))) if n > 0 and k > 1 else 0.0
    if kendall_w > 0.5:
        effect_label = "强一致"
    elif kendall_w > 0.3:
        effect_label = "中等一致"
    elif kendall_w > 0.1:
        effect_label = "弱一致"
    else:
        effect_label = "可忽略"
    alpha = req.params.get("alpha", 0.05)
    conclusion = "条件间存在显著差异" if p < alpha else "条件间未发现显著差异"
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    means = [sub[c].median() for c in measure_cols]
    ax.bar(range(len(measure_cols)), means, color=PALETTE["data"]["secondary"], edgecolor="white")
    ax.set_xticks(range(len(measure_cols)))
    ax.set_xticklabels(measure_cols, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("中位数", fontsize=10)
    ax.set_title(f"{test_name} (χ²={stat:.2f}, p={p:.4f})", fontsize=11)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量(χ²)": [f"{stat:.3f}"],
            "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
            "效应量": [f"Kendall's W={kendall_w:.3f} ({effect_label})"],
            "结论": [conclusion],
        })},
        figures=[fig],
        summary=f"Friedman: {conclusion} (χ²={stat:.2f}, p={p:.4f}, W={kendall_w:.3f})",
        metadata={"test": test_name, "statistic": float(stat), "p_value": float(p),
                 "alpha": alpha, "effect_size": kendall_w, "n": n, "k": k},
    )


_HYPOTHESIS_DISPATCH = {
    "cochran_q": _ht_cochran_q,
    "ks": _ht_ks,
    "friedman": _ht_friedman,
}


def hypothesis_test(req: AnalysisRequest) -> AnalysisResult:
    """假设检验：独立样本、配对样本、单样本 t 检验 / Mann-Whitney U，含效应量。"""
    test_type = req.params.get("test", "ttest_ind")

    # 调度到独立分支函数（新增检验类型只需在 _HYPOTHESIS_DISPATCH 注册）
    if test_type in _HYPOTHESIS_DISPATCH:
        return _HYPOTHESIS_DISPATCH[test_type](req)

    # ── 单样本检验 ──
    if test_type == "ttest_1samp":
        data = req.data[req.target_col].dropna()
        popmean = req.params.get("popmean", 0)
        if len(data) < 3:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效数据不足(至少3个点)"])

        stat, p = sp_stats.ttest_1samp(data, popmean)
        test_name = f"单样本 t 检验 (H0: mu={popmean})"
        d = (float(data.mean()) - popmean) / (float(data.std(ddof=1)) + EPSILON)
        effect_size = float(d)
        effect_name = "Cohen's d (单样本)"
        effect_label = _effect_size_label(abs(d), "cohens_d")
        desc_df = pd.DataFrame({
            "统计量": ["样本量", "均值", "标准差", "标准误", "H0均值"],
            "值": [str(len(data)), f"{data.mean():.4f}", f"{data.std(ddof=1):.4f}",
                   f"{data.sem():.4f}", str(popmean)],
        })

        alpha = req.params.get("alpha", 0.05)
        conclusion = f"显著偏离 {popmean}" if p < alpha else f"未显著偏离 {popmean}"

        fig = Figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        ax.hist(data, bins=min(20, len(data)//2), color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.8)
        mean_val = float(data.mean())
        ax.axvline(mean_val, color=PALETTE["data"]["primary"], linewidth=2, label=f"μ={mean_val:.3f}")
        ax.axvline(popmean, color=PALETTE["target"]["primary"], linestyle="--", linewidth=2, label=f"H0={popmean}")
        # 95% CI
        ci = sp_stats.t.interval(0.95, len(data)-1, loc=mean_val, scale=data.sem())
        ax.axvspan(ci[0], ci[1], alpha=0.1, color=PALETTE["data"]["primary"], label="95%CI")
        ax.set_xlabel(req.target_col, fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame({
                    "检验方法": [test_name], "统计量": [f"{stat:.4f}"], "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)], "效应量": [f"{effect_name}={effect_size:.3f}"],
                    "效应量解读": [effect_label], "结论": [conclusion],
                }),
                "descriptive_stats": desc_df,
            },
            figures=[fig],
            summary=f"单样本检验: {conclusion} (p={p:.4f}, d={effect_size:.3f}, {effect_label})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "effect_size": effect_size, "popmean": popmean,
            },
        )

    # ── 配对检验 ──
    if test_type == "ttest_paired":
        # 配对检验：使用两个 feature_cols 作为配对的列
        if len(req.feature_cols) < 2:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["配对检验需要 2 个特征列（前后测量）"])
        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        if len(sub) < 3:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效配对数据不足(至少3对)"])

        stat, p = sp_stats.ttest_rel(sub[col1], sub[col2])
        test_name = f"配对 t 检验 ({col1} vs {col2})"
        diff = sub[col1].values - sub[col2].values
        # 配对 Cohen's d: mean(diff) / sd(diff)
        d_val = float(np.mean(diff) / (np.std(diff, ddof=1) + EPSILON))
        effect_size = d_val
        effect_name = "Cohen's d (配对)"
        effect_label = _effect_size_label(abs(d_val), "cohens_d")

        alpha = req.params.get("alpha", 0.05)
        conclusion = "前后存在显著差异" if p < alpha else "前后未发现显著差异"

        desc_df = pd.DataFrame({
            "统计量": ["配对对数", f"{col1}均值", f"{col2}均值",
                      "差值均值", "差值标准差", "差值标准误"],
            "值": [str(len(sub)), f"{sub[col1].mean():.4f}", f"{sub[col2].mean():.4f}",
                   f"{diff.mean():.4f}", f"{diff.std(ddof=1):.4f}",
                   f"{sp_stats.sem(diff):.4f}"],
        })

        # 配对图：前后连线
        fig = Figure(figsize=(6, 4.5))
        ax = fig.add_subplot(111)
        x_pos = np.arange(len(sub))
        ax.plot(x_pos, sub[col1].values, "o-", markersize=4, color=PALETTE["data"]["secondary"], label=col1)
        ax.plot(x_pos, sub[col2].values, "s-", markersize=4, color=PALETTE["contrast"]["b"], label=col2)
        for i in range(len(sub)):
            ax.plot([i, i], [sub[col1].iloc[i], sub[col2].iloc[i]],
                   "-", color=PALETTE["spec"]["tertiary"], alpha=0.4, linewidth=0.8)
        ax.set_xlabel("配对序号", fontsize=10)
        ax.set_ylabel("值", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, d={d_val:.3f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame({
                    "检验方法": [test_name], "统计量": [f"{stat:.4f}"], "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)], "效应量": [f"{effect_name}={effect_size:.3f}"],
                    "效应量解读": [effect_label], "结论": [conclusion],
                }),
                "descriptive_stats": desc_df,
            },
            figures=[fig],
            summary=f"配对检验: {conclusion} (p={p:.4f}, d={d_val:.3f}, {effect_label})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "effect_size": effect_size, "n_pairs": len(sub),
            },
        )

    def _wilcoxon_effect_size(p: float, n: int, diff_median: float) -> float:
        """Wilcoxon 效应量: 匹配对秩相关 r = Z / sqrt(N), 钳位到 [-1, 1]。

        单样本和配对 Wilcoxon 共享此实现，确保效应量公式一致。"""
        z_stat_abs = float(sp_stats.norm.ppf(1 - max(p, EPSILON) / 2))
        z_signed = z_stat_abs if diff_median >= 0 else -z_stat_abs
        r_effect = z_signed / np.sqrt(n)
        return float(max(min(r_effect, 1.0), -1.0))

    # ── 单样本 Wilcoxon 符号秩检验 ──
    if test_type == "wilcoxon_1samp":
        data = req.data[req.target_col].dropna()
        popmedian = req.params.get("popmedian", 0)
        if len(data) < 5:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效数据不足(至少5个点)"])

        # Wilcoxon 符号秩检验 (双边): 检验中位数是否等于 popmedian
        stat, p = sp_stats.wilcoxon(data.values - popmedian)
        test_name = f"单样本 Wilcoxon 检验 (H0: 中位数={popmedian})"
        n = len(data)
        r_effect = _wilcoxon_effect_size(p, n, np.median(data.values) - popmedian)
        effect_size = r_effect
        effect_name = "秩相关 r"
        effect_label = _effect_size_label(r_effect, "correlation")

        alpha = req.params.get("alpha", 0.05)
        conclusion = f"中位数显著偏离 {popmedian}" if p < alpha else f"中位数未显著偏离 {popmedian}"

        fig = Figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        ax.hist(data, bins=min(20, n//2), color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.8)
        ax.axvline(np.median(data), color=PALETTE["data"]["primary"], linewidth=2,
                   label=f"中位数={np.median(data):.3f}")
        ax.axvline(popmedian, color=PALETTE["target"]["primary"], linestyle="--", linewidth=2,
                   label=f"H0={popmedian}")
        ax.set_xlabel(req.target_col, fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame({
                    "检验方法": [test_name], "统计量": [f"{stat:.1f}"],
                    "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
                    "效应量": [f"{effect_name}={effect_size:.3f}"],
                    "效应量解读": [effect_label], "结论": [conclusion],
                }),
                "descriptive_stats": pd.DataFrame({
                    "统计量": ["样本量", "中位数", "IQR", "H0中位数",
                              "高于H0数", "低于H0数"],
                    "值": [str(n), f"{data.median():.4f}",
                           f"{data.quantile(0.75)-data.quantile(0.25):.4f}",
                           str(popmedian), str(int((data > popmedian).sum())),
                           str(int((data < popmedian).sum()))],
                }),
            },
            figures=[fig],
            summary=f"单样本Wilcoxon: {conclusion} (p={p:.4f}, r={r_effect:.3f})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "effect_size": effect_size, "popmedian": popmedian,
            },
        )

    # ── Kruskal-Wallis H 检验 (非参数 ANOVA) ──
    if test_type in ("kruskal_wallis", "kruskal"):
        group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
        sub = req.data[[req.target_col, group_col]].dropna()
        groups = sub[group_col].unique()
        if len(groups) < 2:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["至少需要 2 个分组"])

        group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
        stat, p = sp_stats.kruskal(*group_data)
        test_name = "Kruskal-Wallis H 检验 (非参数 ANOVA)"
        n_total = len(sub)
        # 效应量: η²_H = H / (N-1) 近似
        eta2_h = min(float(stat / (n_total - 1)), 1.0) if n_total > 1 else 0.0
        effect_size = eta2_h
        effect_name = "η²_H"
        effect_label = _effect_interpretation(eta2_h)

        alpha = req.params.get("alpha", 0.05)
        conclusion = "组间存在显著差异" if p < alpha else "未发现组间显著差异"

        fig = Figure(figsize=(max(len(groups)*1.5, 5), 4))
        ax = fig.add_subplot(111)
        bp = ax.boxplot(group_data, tick_labels=[str(g) for g in groups],
                       patch_artist=True, widths=0.5)
        if len(groups) > 6:
            for label in ax.get_xticklabels():
                label.set_rotation(30)
                label.set_ha("right")
        ax.tick_params(labelsize=9)
        for patch in bp["boxes"]:
            patch.set_facecolor(PALETTE["data"]["secondary"])
        ax.set_xlabel(group_col, fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        ax.set_title(f"{test_name} (H={stat:.2f}, p={p:.4f})", fontsize=11)
        fig.tight_layout()

        # ── Dunn 事后多重比较 ──
        tables = {
            "test_results": pd.DataFrame({
                "检验方法": [test_name], "统计量(H)": [f"{stat:.3f}"],
                "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
                "效应量": [f"{effect_name}={effect_size:.3f}"],
                "效应量解读": [effect_label], "结论": [conclusion],
            }),
        }
        if p < alpha and len(groups) >= 3:
            # Dunn 检验：基于秩和的成对比较
            from itertools import combinations
            all_vals = np.concatenate(group_data)
            ranks = sp_stats.rankdata(all_vals)
            _, tie_counts = np.unique(ranks, return_counts=True)
            rank_sums = {}
            start = 0
            for g, gd in zip(groups, group_data):
                rank_sums[g] = np.sum(ranks[start:start + len(gd)])
                start += len(gd)

            dunn_rows = []
            n_comparisons = len(groups) * (len(groups) - 1) // 2
            for g1, g2 in combinations(groups, 2):
                n1, n2 = len(group_data[list(groups).index(g1)]), len(group_data[list(groups).index(g2)])
                z_num = abs(rank_sums[g1] / n1 - rank_sums[g2] / n2)
                N = len(all_vals)
                tie_corr = np.sum(tie_counts**3 - tie_counts) / (12 * (N - 1)) if N > 1 else 0
                z_denom = np.sqrt(((N * (N + 1) / 12) - tie_corr) * (1/n1 + 1/n2))
                z_stat_dunn = z_num / (z_denom + EPSILON)
                p_dunn = float(2 * sp_stats.norm.sf(abs(z_stat_dunn)))
                # Bonferroni 校正
                p_adj = min(p_dunn * n_comparisons, 1.0)
                dunn_rows.append({
                    "对比": f"{g1} vs {g2}",
                    "Z值": round(float(z_stat_dunn), 3),
                    "原始p值": round(float(p_dunn), 4),
                    "校正p值": round(float(p_adj), 4),
                    "显著": "是" if p_adj < alpha else "否",
                })
            tables["posthoc_dunn"] = pd.DataFrame(dunn_rows)

        return AnalysisResult(
            task="hypothesis_test",
            tables=tables,
            figures=[fig],
            summary=f"Kruskal-Wallis: {conclusion} (H={stat:.2f}, p={p:.4f}, η²_H={eta2_h:.3f})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "effect_size": effect_size, "n_groups": len(groups),
            },
        )

    # ── McNemar 检验 (配对二分类数据) ──
    if test_type == "mcnemar":
        if len(req.feature_cols) < 2:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["McNemar 检验需要 2 个特征列 (前后二分类测量)"])

        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        if len(sub) < 5:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效配对数据不足(至少5对)"])

        # 构建 2×2 列联表
        vals1 = sub[col1].values
        vals2 = sub[col2].values
        # 自动二值化
        unique_vals = np.unique(np.concatenate([vals1, vals2]))
        if len(unique_vals) != 2:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=[f"McNemar 检验需要二分类数据 (每列恰好 2 个不同值)，当前有 {len(unique_vals)} 个"])

        # 保留原始类型进行比较，避免 str() 导致数值型二值数据 (0/1) 比较失败
        pos = unique_vals[1]
        neg = unique_vals[0]

        a = int(((vals1 == pos) & (vals2 == pos)).sum())  # 都为正
        b = int(((vals1 == pos) & (vals2 == neg)).sum())  # 前正后负
        c = int(((vals1 == neg) & (vals2 == pos)).sum())  # 前负后正
        d = int(((vals1 == neg) & (vals2 == neg)).sum())  # 都为负

        # McNemar 检验
        # 小样本 (b+c < 25) 使用 Yates 连续性校正，大样本不做校正
        bc_sum = b + c
        if bc_sum > 0:
            if bc_sum < 25:
                stat = (abs(b - c) - 1)**2 / bc_sum
                test_name_suffix = " (Yates校正)"
            else:
                stat = (b - c)**2 / bc_sum
                test_name_suffix = ""
        else:
            stat = 0
            test_name_suffix = ""
        p = float(sp_stats.chi2.sf(stat, 1))

        test_name = f"McNemar 检验 ({col1} → {col2}){test_name_suffix}"
        alpha = req.params.get("alpha", 0.05)
        conclusion = "前后存在显著变化" if p < alpha else "前后未发现显著变化"
        # Odds Ratio = b/c（保留原始值，不做截断）
        or_val = b / (c + EPSILON)

        # 可视化：前后对比堆叠柱状图
        fig = Figure(figsize=(5, 4))
        ax = fig.add_subplot(111)
        categories = [f"{neg}→{neg}", f"{neg}→{pos}", f"{pos}→{neg}", f"{pos}→{pos}"]
        counts = [d, c, b, a]
        ax.bar(categories, counts, color=[PALETTE["data"]["tertiary"], PALETTE["data"]["primary"], PALETTE["target"]["primary"], PALETTE["data"]["secondary"]],
               edgecolor="white")
        for i, (cat, cnt) in enumerate(zip(categories, counts)):
            ax.text(i, cnt + max(counts)*0.02, str(cnt), ha="center", fontsize=9)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, OR={or_val:.2f})", fontsize=10)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame({
                    "检验方法": [test_name], "统计量(χ²)": [f"{stat:.3f}"],
                    "p值": [f"{p:.4f}"], "显著性水平": [str(alpha)],
                    "效应量(OR)": [f"{or_val:.3f}"],
                    "结论": [conclusion],
                }),
                "contingency_2x2": pd.DataFrame({
                    f"{col2}={neg}": [d, b], f"{col2}={pos}": [c, a],
                }, index=[f"{col1}={neg}", f"{col1}={pos}"]),
            },
            figures=[fig],
            summary=f"McNemar: {conclusion} (χ²={stat:.2f}, p={p:.4f}, OR=b/c={or_val:.2f})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "odds_ratio": float(or_val) if not np.isinf(or_val) else None,
                "n_pairs": len(sub), "discordant_pairs": b + c,
            },
        )

    # ── Mann-Kendall 趋势检验 ──
    if test_type == "mann_kendall":
        data = req.data[req.target_col].dropna()
        n = len(data)
        if n < 4:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效数据不足(至少4个点)"])

        # MK 统计量: 使用 scipy kendalltau (τ-B) 计算 p 值（已正确处理结）
        vals = data.values
        tau_mk, p = sp_stats.kendalltau(np.arange(n), vals)
        # 从 τ-B 反推 S：τ-B = S / sqrt(n0*(n0-n2)) → 考虑 y 方向结校正
        n0 = n * (n - 1) / 2
        unique_vals, counts = np.unique(vals, return_counts=True)
        n2 = np.sum(counts * (counts - 1) / 2)  # y 方向结校正
        S = int(round(tau_mk * np.sqrt(max(n0 * (n0 - n2), 1.0))))
        effect_size = float(tau_mk)
        # 从 p 值反推近似 Z（用于展示）
        p_safe = max(p, EPSILON)  # protect against p=0 causing ppf(1.0)=inf (EPSILON keeps z≤6.47 finite)
        z_mk = float(sp_stats.norm.ppf(1 - p_safe / 2)) * np.sign(S) if p < 1.0 else 0.0

        test_name = "Mann-Kendall 趋势检验"
        alpha = req.params.get("alpha", 0.05)
        trend_dir = "上升趋势" if S > 0 else "下降趋势" if S < 0 else "无趋势"
        conclusion = f"存在显著{trend_dir}" if p < alpha else "未发现显著趋势"

        fig = Figure(figsize=(8, 4))
        ax = fig.add_subplot(111)
        ax.plot(range(n), vals, "o-", markersize=3, color=PALETTE["data"]["primary"], linewidth=1)
        # 简单趋势线
        z_poly = np.polyfit(range(n), vals, 1)
        ax.plot(range(n), np.polyval(z_poly, range(n)), "-", color=PALETTE["target"]["primary"],
               linewidth=2, alpha=0.7, label=f"线性趋势 (τ={tau_mk:.3f})")
        ax.set_xlabel("时间序号", fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        ax.set_title(f"{test_name} (S={S}, p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={"test_results": pd.DataFrame({
                "检验方法": [test_name], "S统计量": [str(S)],
                "Z值": [f"{z_mk:.3f}"], "p值": [f"{p:.4f}"],
                "显著性水平": [str(alpha)], "Kendall τ": [f"{tau_mk:.4f}"],
                "结论": [conclusion],
            })},
            figures=[fig],
            summary=f"Mann-Kendall: {conclusion} (τ={tau_mk:.3f}, p={p:.4f})",
            metadata={"test": test_name, "S": int(S), "z": float(z_mk),
                     "p_value": float(p), "tau": float(tau_mk), "alpha": alpha},
        )

    # ── Jonckheere-Terpstra 趋势检验 ──
    if test_type == "jonckheere":
        group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
        sub = req.data[[req.target_col, group_col]].dropna()
        groups = sub[group_col].unique()
        if len(groups) < 3:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["Jonckheere-Terpstra 需要至少 3 个有序分组"])
        # 转换分组为有序秩次
        group_order = {g: i for i, g in enumerate(groups)}
        sub_ordered = sub.copy()
        sub_ordered["_order"] = sub[group_col].map(group_order)
        sub_sorted = sub_ordered.sort_values("_order")
        group_data_ordered = [sub_sorted[sub_sorted["_order"] == i][req.target_col].values
                             for i in range(len(groups))]

        # JT 统计量: 标准 Jonckheere-Terpstra = Σ_{i<j} U_{ij}
        # U_{ij} = #{(x∈gi, y∈gj) | x < y}（Mann-Whitney 统计量）
        # 使用向量化 searchsorted（O(n log n)），与 _cliffs_delta 相同算法
        JT = 0
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                gi, gj = group_data_ordered[i], group_data_ordered[j]
                y_sorted = np.sort(gj)
                # le_count: gj 中小于等于各 gi 元素的数量
                le_count = int(np.sum(np.searchsorted(y_sorted, gi, side="right")))
                # U_{ij} = n_i * n_j - le_count = #(x < y)
                JT += len(gi) * len(gj) - le_count

        # 正态近似
        n_total = sum(len(g) for g in group_data_ordered)
        n_i = np.array([len(g) for g in group_data_ordered])
        E_JT = (n_total**2 - np.sum(n_i**2)) / 4
        V_JT = (n_total**2 * (2*n_total + 3) - np.sum(n_i**2 * (2*n_i + 3))) / 72
        # 结校正：对所有组的值合并后统一计算，每个结值的校正项按其总出现次数计算
        #（正确做法是按跨组总频数计算，而非按每个组内分别计算）
        all_vals_flat = np.concatenate(group_data_ordered)
        _, counts_all = np.unique(all_vals_flat, return_counts=True)
        ties_all = counts_all[counts_all >= 2]
        V_JT -= np.sum(ties_all * (ties_all - 1) * (2 * ties_all + 5)) / 72
        z_JT = (JT - E_JT) / np.sqrt(max(V_JT, EPSILON))
        p = float(2 * sp_stats.norm.sf(abs(z_JT)))

        test_name = "Jonckheere-Terpstra 趋势检验"
        alpha = req.params.get("alpha", 0.05)
        trend_dir = "递增趋势" if z_JT > 0 else "递减趋势"
        conclusion = f"存在显著{trend_dir}" if p < alpha else "未发现显著趋势"

        # Kendall's tau-b 效应量近似
        tau_b = 4 * JT / (n_total**2 - np.sum(n_i**2) + EPSILON) - 1
        effect_size = float(tau_b)
        effect_label = _effect_size_label(abs(tau_b), "correlation")

        return AnalysisResult(
            task="hypothesis_test",
            tables={"test_results": pd.DataFrame({
                "检验方法": [test_name], "统计量(JT)": [str(JT)],
                "Z值": [f"{z_JT:.3f}"], "p值": [f"{p:.4f}"],
                "显著性水平": [str(alpha)], "效应量(τ)": [f"{tau_b:.3f}"],
                "结论": [conclusion],
            })},
            summary=f"Jonckheere-Terpstra: {conclusion} (Z={z_JT:.2f}, p={p:.4f}, τ={tau_b:.3f})",
            metadata={"test": test_name, "statistic": float(JT), "p_value": float(p),
                     "alpha": alpha, "effect_size": effect_size, "z": float(z_JT)},
        )

    # ── 配对 Wilcoxon 符号秩检验 ──
    if test_type == "wilcoxon_paired":
        if len(req.feature_cols) < 2:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["配对检验需要 2 个特征列"])
        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        if len(sub) < 5:
            return AnalysisResult(task="hypothesis_test", status="error",
                messages=["有效配对数据不足(至少5对)"])

        # Wilcoxon 符号秩检验
        stat, p = sp_stats.wilcoxon(sub[col1], sub[col2])
        test_name = f"Wilcoxon 符号秩检验 ({col1} vs {col2})"
        diff = sub[col1].values - sub[col2].values
        n_pairs = len(sub)
        r_effect = _wilcoxon_effect_size(p, n_pairs, np.median(diff))
        effect_size = float(r_effect)
        effect_name = "匹配对秩相关 r"
        effect_label = _effect_size_label(r_effect, "correlation")

        alpha = req.params.get("alpha", 0.05)
        conclusion = "前后存在显著差异" if p < alpha else "前后未发现显著差异"

        # 配对差值分布图
        fig = Figure(figsize=(7, 4.5))
        ax = fig.add_subplot(111)
        ax.hist(diff, bins=min(15, n_pairs//2), color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.8)
        ax.axvline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5, label="零差异线")
        ax.axvline(np.median(diff), color=PALETTE["data"]["primary"], linewidth=2,
                   label=f"中位数差={np.median(diff):.3f}")
        ax.set_xlabel(f"{col1} - {col2}", fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, r={r_effect:.3f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame({
                    "检验方法": [test_name], "统计量": [f"{stat:.1f}"], "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)], "效应量": [f"{effect_name}={effect_size:.3f}"],
                    "效应量解读": [effect_label], "结论": [conclusion],
                }),
                "descriptive_stats": pd.DataFrame({
                    "统计量": ["配对对数", f"{col1}中位数", f"{col2}中位数",
                              "差值中位数", "正差值对数", "负差值对数"],
                    "值": [str(n_pairs), f"{sub[col1].median():.4f}", f"{sub[col2].median():.4f}",
                           f"{np.median(diff):.4f}", str(int((diff > 0).sum())),
                           str(int((diff < 0).sum()))],
                }),
            },
            figures=[fig],
            summary=f"Wilcoxon配对检验: {conclusion} (p={p:.4f}, r={r_effect:.3f}, {effect_label})",
            metadata={
                "test": test_name, "statistic": float(stat), "p_value": float(p),
                "alpha": alpha, "effect_size": effect_size, "n_pairs": n_pairs,
            },
        )

    # ── 独立双样本检验 ──
    group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=[f"分组列需要恰好 2 个水平，当前有 {len(groups)} 个"])

    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()

    # 最小样本量检查 — 与其他分支保持一致 (P2-3 fix)
    min_n = 3
    if len(g1) < min_n or len(g2) < min_n:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=[f"每组至少需要 {min_n} 个有效数据，当前 g1={len(g1)}, g2={len(g2)}"])

    # ── 自动选择参数/非参数检验 ──
    norm_warn: list[str] = []
    sw1 = sw2 = 1.0  # 初始化为正态（用于 auto 分支中条件不满足时的回退）
    norm_already_checked = False
    if test_type == "auto":
        normal = True
        if len(g1) >= 3 and len(g2) >= 3 and len(g1) <= 5000 and len(g2) <= 5000:
            _, sw1 = sp_stats.shapiro(g1)
            _, sw2 = sp_stats.shapiro(g2)
            normal = min(sw1, sw2) >= 0.05
            norm_already_checked = True
        if normal:
            test_type = "ttest_ind"
        else:
            test_type = "mannwhitney"
            norm_warn.append(
                f"自动选择 Mann-Whitney U (正态性p={min(sw1,sw2):.4f}<0.05)"
            )

    if not norm_already_checked and len(g1) >= 3 and len(g2) >= 3 and test_type != "mannwhitney":
        _, sw1 = sp_stats.shapiro(g1) if len(g1) <= 5000 else (None, 1.0)
        _, sw2 = sp_stats.shapiro(g2) if len(g2) <= 5000 else (None, 1.0)
        if min(sw1, sw2) < 0.05:
            norm_warn.append(
                f"正态性检验 p={min(sw1,sw2):.4f}<0.05，建议使用 Mann-Whitney U 检验"
            )

    if test_type == "mannwhitney":
        stat, p = sp_stats.mannwhitneyu(g1, g2)
        test_name = "Mann-Whitney U 检验"
        effect_size = _cliffs_delta(g1.values, g2.values)
        effect_name = "Cliff's δ"
        effect_label = _effect_size_label(effect_size, "cliffs_delta")
    else:
        stat, p = sp_stats.ttest_ind(g1, g2)
        test_name = "独立样本 t 检验"
        effect_size = _cohens_d(g1.values, g2.values, norm_warn)
        effect_name = "Cohen's d"
        effect_label = _effect_size_label(effect_size, "cohens_d")

    alpha = req.params.get("alpha", 0.05)
    conclusion = "存在显著差异" if p < alpha else "未发现显著差异"

    # ── 统计功效估计 ──
    n1, n2 = len(g1), len(g2)
    from math import sqrt
    # 非中心参数近似
    ncp = abs(effect_size) * sqrt(n1 * n2 / (n1 + n2)) if (n1 + n2) > 0 else 0
    dof = n1 + n2 - 2
    if test_type != "mannwhitney" and dof > 0:
        try:
            t_crit = sp_stats.t.ppf(1 - alpha / 2, dof)
            power = float(1 - sp_stats.nct.cdf(t_crit, dof, ncp) + sp_stats.nct.cdf(-t_crit, dof, ncp))
        except Exception:
            logger.debug("统计功效计算失败", exc_info=True)
            power = None
    else:
        power = None

    # 双样本箱线图 + 散点叠加
    fig = Figure(figsize=(6, 4.5))
    ax = fig.add_subplot(111)
    bp = ax.boxplot([g1, g2], tick_labels=[
        f"{groups[0]}\n(n={n1})", f"{groups[1]}\n(n={n2})"
    ], patch_artist=True, widths=0.5)
    for patch, color in zip(bp['boxes'], [PALETTE["data"]["secondary"], PALETTE["target"]["fill"]]):
        patch.set_facecolor(color)
    # 叠加散点
    for i, gdata in enumerate([g1, g2], 1):
        jitter = np.random.uniform(-0.12, 0.12, len(gdata))
        ax.scatter(np.full(len(gdata), i) + jitter, gdata.values,
                   alpha=0.35, s=12, color=PALETTE["misc"]["grid"], zorder=3)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"{test_name} — {req.target_col}\n"
        f"p={p:.4f} | {effect_name}={effect_size:.3f} ({effect_label})"
        + (f" | 功效={power:.1%}" if power else ""),
        fontsize=10
    )
    fig.tight_layout()

    # ── 描述统计表 ──
    desc_df = pd.DataFrame({
        "分组": [str(groups[0]), str(groups[1])],
        "样本量": [n1, n2],
        "均值": [float(g1.mean()), float(g2.mean())],
        "标准差": [float(g1.std(ddof=1)), float(g2.std(ddof=1))],
        "标准误": [float(g1.sem()), float(g2.sem())],
    })

    result_table = pd.DataFrame({
        "检验方法": [test_name],
        "统计量": [f"{stat:.4f}"],
        "p值": [f"{p:.4f}"],
        "显著性水平": [str(alpha)],
        "效应量": [f"{effect_name}={effect_size:.3f}"],
        "效应量解读": [effect_label],
        "统计功效": [f"{power:.1%}" if power is not None else "N/A"],
        "结论": [f"「{group_col}」: {groups[0]} vs {groups[1]} — {conclusion}"],
    })

    summary_parts = [
        f"「{group_col}」中 {groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})",
        f"效应量 {effect_name}={effect_size:.3f}（{effect_label}）",
    ]
    if power is not None:
        summary_parts.append(f"统计功效 {power:.1%}")
    else:
        summary_parts.append("统计功效 N/A")

    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": result_table,
            "descriptive_stats": desc_df,
        },
        figures=[fig],
        summary="；".join(summary_parts),
        metadata={
            "test": test_name, "statistic": float(stat), "p_value": float(p),
            "alpha": alpha, "effect_size": effect_size, "effect_name": effect_name,
            "effect_label": effect_label, "power": power,
        },
        messages=norm_warn,
    )


def decision_tree_analysis(req: AnalysisRequest) -> AnalysisResult:
    """决策树特征重要性分析，含排列重要性和交叉验证。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(task="decision_tree", status="error",
            messages=["需要至少 1 个因子列"])

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 5:
        return AnalysisResult(task="decision_tree", status="error",
            messages=[f"有效样本({len(df)})不足"])

    # 检查是否存在非数值列（DecisionTreeRegressor 不接受字符串/类别特征）
    non_num = [c for c in cols if not pd.api.types.is_numeric_dtype(df[c])]
    if non_num:
        return AnalysisResult(task="decision_tree", status="error",
            messages=[f"以下列包含非数值数据，请先进行 One-Hot 编码: {non_num}"])
    X = df[cols]
    y = df[req.target_col]
    max_depth = req.params.get("max_depth", 5)
    random_state = req.params.get("random_state", 42)

    tree = DecisionTreeRegressor(max_depth=max_depth, random_state=random_state)
    tree.fit(X, y)

    # ── 内置特征重要性 ──
    fi_builtin = pd.DataFrame({
        "因子": cols,
        "内置重要性": tree.feature_importances_,
    })

    # ── 排列重要性 (更可靠，不受树结构偏差影响) ──
    from sklearn.inspection import permutation_importance
    try:
        perm_result = permutation_importance(
            tree, X, y, n_repeats=10, random_state=random_state, scoring="r2"
        )
        fi_perm = pd.DataFrame({
            "因子": cols,
            "排列重要性": perm_result.importances_mean,
            "排列重要性_std": perm_result.importances_std,
        })
    except Exception:
        logger.warning(
            "排列重要性计算失败（样本量可能不足），回退为内置重要性。"
            "排列重要性标准差已置零，解读时请注意。",
            exc_info=True,
        )
        fi_perm = pd.DataFrame({
            "因子": cols,
            "排列重要性": tree.feature_importances_,
            "排列重要性_std": [0.0] * len(cols),
        })

    # 合并两种重要性
    fi = fi_builtin.merge(fi_perm, on="因子")
    fi["综合重要性"] = fi["排列重要性"].clip(lower=0)
    fi = fi.sort_values("综合重要性", ascending=False).reset_index(drop=True)
    top = fi.iloc[0] if len(fi) > 0 else None

    # ── 交叉验证评估过拟合 ──
    from sklearn.model_selection import cross_val_score
    warn_msgs: list[str] = []
    cv_scores = []
    if len(df) >= 10:
        try:
            cv_scores = cross_val_score(
                tree, X, y, cv=min(5, len(df) // 3), scoring="r2"
            )
            cv_r2 = float(np.mean(cv_scores))
            train_r2 = float(tree.score(X, y))
            if train_r2 - cv_r2 > 0.3:
                warn_msgs.append(
                    f"⚠ 过拟合警告: 训练R²={train_r2:.3f}, "
                    f"交叉验证R²={cv_r2:.3f} (差距={train_r2-cv_r2:.2f})"
                )
        except Exception:
            logger.debug("交叉验证失败", exc_info=True)
            cv_r2 = None
    else:
        cv_r2 = None

    # ── 图1: 特征重要性对比柱状图 ──
    n_factors = len(fi)
    fig_imp = Figure(figsize=(max(n_factors*0.8, 6), 4.5))
    # 只显示重要性>0的因子
    fi_plot = fi[fi["综合重要性"] > 0] if fi["综合重要性"].sum() > 0 else fi
    x = np.arange(len(fi_plot))
    width = 0.35
    ax = fig_imp.add_subplot(111)
    ax.barh(x + width/2, fi_plot["内置重要性"], width,
            label="内置重要性 (Gini)", color=PALETTE["data"]["secondary"], alpha=0.8)
    ax.barh(x - width/2, fi_plot["排列重要性"], width,
            label="排列重要性 (±1σ)", color=PALETTE["data"]["primary"], alpha=0.9,
            xerr=fi_plot["排列重要性_std"] if "排列重要性_std" in fi_plot.columns else None,
            capsize=2)
    ax.set_yticks(x)
    ax.set_yticklabels(fi_plot["因子"], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("重要性", fontsize=10)
    cv_note = f" | CV R²={cv_r2:.3f}" if cv_r2 is not None else ""
    ax.set_title(f"决策树特征重要性对比 — {req.target_col}{cv_note}", fontsize=11)
    ax.legend(fontsize=8, loc="lower right")
    fig_imp.tight_layout()

    # ── 图2: 决策树结构图 ──
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig_tree = Figure(figsize=(12, max(tree.get_depth() * 1.2, 4)))
    FigureCanvasAgg(fig_tree)  # plot_tree 需要 canvas renderer 初始化
    ax_tree = fig_tree.add_subplot(111)
    plot_tree(tree, ax=ax_tree, feature_names=cols, filled=True,
              rounded=True, fontsize=8, precision=2, max_depth=4)
    ax_tree.set_title(f"决策树结构 — {req.target_col} (深度={tree.get_depth()})", fontsize=12)
    fig_tree.tight_layout()

    # ── 汇总 ──
    cv_str = f"CV R²={cv_r2:.3f}" if cv_r2 is not None else "CV R²=N/A"
    summary = (
        f"关键影响因子: {top['因子']} "
        f"(排列重要性={top['排列重要性']:.3f}, "
        f"内置重要性={top['内置重要性']:.3f})。{cv_str}"
    ) if top is not None else f"分析完成。{cv_str}"

    return AnalysisResult(
        task="decision_tree",
        tables={"feature_importance": fi},
        figures=[fig_imp, fig_tree],
        summary=summary,
        metadata={
            "top_factor": top["因子"] if top is not None else None,
            "cv_r2": cv_r2,
            "train_r2": float(tree.score(X, y)),
            "max_depth": max_depth,
            "n_samples": len(df),
        },
        messages=warn_msgs,
    )


def vif_analysis(req: AnalysisRequest) -> AnalysisResult:
    """方差膨胀因子 — 多元共线性诊断。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(task="vif", status="error",
            messages=["VIF 分析需要至少 2 个因子列"])

    df = req.data[cols].dropna()
    if len(df) < len(cols) + 2:
        return AnalysisResult(task="vif", status="error",
            messages=[f"有效样本({len(df)})不足"])

    try:
        X = sm.add_constant(df)
        vif_vals = [variance_inflation_factor(X.values, i) for i in range(X.shape[1])]
        vif_full = pd.DataFrame({"变量": X.columns, "VIF": vif_vals})
        # 排除无意义的 const 列
        vif_data = vif_full[vif_full["变量"] != "const"].copy()
        high_vif = vif_data[vif_data["VIF"] > VIF_THRESHOLD]
        # VIF < 1 在数学上不可能（VIF = 1/(1-R²) ≥ 1），异常值提示常量列或数值问题
        invalid_vif = vif_data[vif_data["VIF"] < 0.99]  # 允许浮点舍入误差 (~0.999…)
        vif_warnings = []
        if len(high_vif) > 0:
            vif_warnings.append(f"{len(high_vif)} 个变量 VIF>{VIF_THRESHOLD}，存在共线性风险")
        if len(invalid_vif) > 0:
            bad_cols = invalid_vif["变量"].tolist()
            vif_warnings.append(f"⚠ {len(invalid_vif)} 个变量 VIF<1 异常（{bad_cols}），"
                               "可能为零方差常量列或数值计算误差，请检查数据")
        warning = "; ".join(vif_warnings) if vif_warnings else f"所有变量 VIF<={VIF_THRESHOLD}，无明显共线性"

        # VIF 柱状图
        vif_plot = vif_data
        fig = Figure(figsize=(max(len(vif_plot)*0.7, 5), 3.5))
        ax = fig.add_subplot(111)
        colors = [PALETTE["target"]["primary"] if v > VIF_THRESHOLD else PALETTE["data"]["primary"]
                  for v in vif_plot["VIF"]]
        ax.barh(vif_plot["变量"], vif_plot["VIF"], color=colors)
        ax.axvline(VIF_THRESHOLD, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1,
                  label=f"VIF={VIF_THRESHOLD} 阈值")
        ax.set_xlabel("VIF", fontsize=9)
        ax.set_title("共线性诊断 — VIF", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="vif", tables={"vif_table": vif_data}, figures=[fig], summary=warning,
            metadata={"high_vif_count": len(high_vif), "invalid_vif_count": len(invalid_vif)},
        )
    except Exception:
        logger.debug("VIF 计算失败", exc_info=True)
        return AnalysisResult(task="vif", status="error",
                              messages=["VIF 计算失败，请检查数据是否存在共线性或数值异常"])


def power_analysis(req: AnalysisRequest) -> AnalysisResult:
    """统计功效分析 — 估计所需样本量或已达功效。

    参数 (通过 params):
        effect_size: 预期效应量 (Cohen's d 或 η²)
        alpha: 显著性水平 (默认 0.05)
        target_power: 目标功效 (默认 0.80)
        mode: "required_n" (计算所需样本量) 或 "achieved" (计算已达功效)
        current_n: 当前样本量 (mode="achieved" 时必需)
        test_type: "ttest" (默认) | "anova" | "proportion"
        n_groups: ANOVA 分组数 (test_type="anova" 时使用)
    """
    from math import ceil

    effect_size = req.params.get("effect_size", 0.5)
    alpha = req.params.get("alpha", 0.05)
    target_power = req.params.get("target_power", 0.80)
    mode = req.params.get("mode", "required_n")  # "required_n" | "achieved"
    test_type = req.params.get("test_type", "ttest")
    current_n = req.params.get("current_n")

    if mode == "required_n":
        # 计算所需样本量
        if test_type == "ttest":
            from statsmodels.stats.power import TTestIndPower
            analysis = TTestIndPower()
            required = ceil(analysis.solve_power(
                effect_size=abs(effect_size), alpha=alpha,
                power=target_power, alternative="two-sided"
            ))
            label = f"独立样本 t 检验所需每组样本量: {required} (总计 {required*2})"
        elif test_type == "anova":
            n_groups = req.params.get("n_groups", 3)
            from statsmodels.stats.power import FTestAnovaPower
            analysis = FTestAnovaPower()
            total_n = ceil(float(analysis.solve_power(
                effect_size=abs(effect_size), alpha=alpha,
                power=target_power, k_groups=n_groups
            )))
            required = ceil(total_n / n_groups)
            label = f"ANOVA ({n_groups}组) 所需每组样本量: {required} (总计 {required*n_groups})"
        elif test_type == "proportion":
            p0 = req.params.get("p0", 0.5)
            p1 = req.params.get("p1", 0.6)
            z_alpha = abs(sp_stats.norm.ppf(alpha / 2))
            z_beta = abs(sp_stats.norm.ppf(1 - target_power))
            d = abs(p1 - p0)
            # 双比例检验: 总方差 = p0*(1-p0) + p1*(1-p1)
            required = ceil((z_alpha + z_beta)**2 * (p0 * (1 - p0) + p1 * (1 - p1)) / (d**2 + EPSILON))
            label = f"比例检验所需样本量: {required} (p0={p0}, p1={p1}, d={d:.3f})"
        else:
            return AnalysisResult(
                task="power_analysis", status="error",
                messages=[f"不支持的检验类型: {test_type}"],
            )

        power_df = pd.DataFrame({
            "参数": ["效应量", "显著性水平(α)", "目标功效", "检验类型", "所需每组样本量"],
            "值": [str(effect_size), str(alpha), str(target_power),
                  test_type, str(required)],
        })

        # 功效曲线图
        n_range = np.arange(max(2, required // 2), required * 3 + 1, max(1, required // 20))
        if test_type == "ttest":
            powers = [TTestIndPower().power(effect_size=abs(effect_size),
                     nobs1=n, alpha=alpha) for n in n_range]
        else:
            n_groups = req.params.get("n_groups", 3)
            powers = [FTestAnovaPower().power(effect_size=abs(effect_size),
                     nobs=n * n_groups, k_groups=n_groups, alpha=alpha)
                     for n in n_range]

        fig = Figure(figsize=(7, 4))
        ax = fig.add_subplot(111)
        ax.plot(n_range, powers, "-", color=PALETTE["data"]["primary"], linewidth=2)
        ax.axhline(target_power, color=PALETTE["target"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"目标功效={target_power}")
        ax.axvline(required, color=PALETTE["center"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"所需N={required}")
        ax.set_xlabel("每组样本量", fontsize=10)
        ax.set_ylabel("统计功效", fontsize=10)
        ax.set_title(f"功效曲线 — {test_type} (效应量={effect_size}, α={alpha})", fontsize=11)
        ax.legend(fontsize=8)
        ax.set_ylim(0, 1.05)
        fig.tight_layout()

        return AnalysisResult(
            task="power_analysis",
            tables={"power_result": power_df},
            figures=[fig],
            summary=label,
            metadata={
                "required_n": required, "effect_size": effect_size,
                "alpha": alpha, "target_power": target_power, "test_type": test_type,
                "mode": "required_n",
            },
        )

    elif mode in ("achieved", "achieved_power"):
        # 计算已达功效（"achieved_power" 为 Web UI 兼容别名）
        if current_n is None:
            return AnalysisResult(
                task="power_analysis", status="error",
                messages=["mode='achieved' 需要提供 current_n 参数"],
            )

        if test_type == "ttest":
            from statsmodels.stats.power import TTestIndPower
            power = float(TTestIndPower().power(
                effect_size=abs(effect_size), nobs1=current_n, alpha=alpha
            ))
        elif test_type == "anova":
            n_groups = req.params.get("n_groups", 3)
            from statsmodels.stats.power import FTestAnovaPower
            power = float(FTestAnovaPower().power(
                effect_size=abs(effect_size), nobs=current_n * n_groups,
                k_groups=n_groups, alpha=alpha
            ))
        else:
            return AnalysisResult(
                task="power_analysis", status="error",
                messages=[f"不支持的检验类型: {test_type}"],
            )

        judge = "充足 (≥0.80)" if power >= 0.80 else ("一般 (0.50-0.80)" if power >= 0.50 else "不足 (<0.50)")
        summary = f"当前功效={power:.1%} ({judge})，效应量={effect_size}, 每组N={current_n}"

        return AnalysisResult(
            task="power_analysis",
            tables={
                "power_result": pd.DataFrame({
                    "参数": ["效应量", "显著性水平(α)", "每组样本量", "检验类型", "已达功效", "判定"],
                    "值": [str(effect_size), str(alpha), str(current_n),
                          test_type, f"{power:.3f}", judge],
                }),
            },
            summary=summary,
            metadata={
                "achieved_power": power, "effect_size": effect_size,
                "alpha": alpha, "current_n": current_n, "test_type": test_type,
                "mode": "achieved",
            },
        )

    else:
        return AnalysisResult(
            task="power_analysis", status="error",
            messages=[f"未知模式: {mode}，支持 'required_n' 和 'achieved'"],
        )


def contingency_analysis(req: AnalysisRequest) -> AnalysisResult:
    """列联表分析 — 检验两个分类变量是否独立。

    自动选择：期望频数≥5 用 Chi-square，否则用 Fisher's exact test。
    效应量: Cramér's V (Chi-square) 或 Odds Ratio (2×2 Fisher)。
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(task="contingency", status="error",
            messages=["需要至少 1 个因子列"])

    col1 = req.target_col
    col2 = req.feature_cols[0]
    if col1 not in req.data.columns or col2 not in req.data.columns:
        return AnalysisResult(task="contingency", status="error",
            messages=["目标列或因子列不存在"])

    sub = req.data[[col1, col2]].dropna()
    if len(sub) < 4:
        return AnalysisResult(task="contingency", status="error",
            messages=["有效数据不足"])

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

    alpha = req.params.get("alpha", 0.05)
    conclusion = "两变量存在显著关联" if p_val < alpha else "两变量未发现显著关联"

    # 可视化：堆叠柱状图
    fig = Figure(figsize=(8, 4.5))
    ax = fig.add_subplot(111)
    ctab_pct = ctab.div(ctab.sum(axis=0), axis=1) * 100
    bar_colors = [PALETTE["data"]["primary"], PALETTE["data"]["secondary"],
                  PALETTE["target"]["primary"], PALETTE["anomaly"]["primary"],
                  PALETTE["contrast"]["b"], PALETTE["contrast"]["c"]]
    ctab_pct.plot(kind="bar", stacked=True, ax=ax, color=bar_colors[:len(ctab_pct)],
                  edgecolor="white", linewidth=0.5)
    ax.set_xlabel(col1, fontsize=10)
    ax.set_ylabel("比例 (%)", fontsize=10)
    ax.set_title(
        f"{test_name}: {col1} vs {col2} "
        f"({stat_label}={stat:.3f}, p={p_val:.4f}, {effect_name}={effect:.3f})",
        fontsize=10,
    )
    ax.legend(title=col2, fontsize=8, title_fontsize=8)
    ax.tick_params(axis="x", rotation=45, labelsize=9)
    fig.tight_layout()

    summary = (
        f"{test_name}: {conclusion} (p={p_val:.4f}), "
        f"{effect_name}={effect:.3f} ({effect_label})"
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
            "test": test_name, "statistic": float(stat),
            "p_value": float(p_val), "alpha": alpha,
            "effect_size": effect, "effect_name": effect_name,
            "effect_label": effect_label,
            "degrees_of_freedom": int(dof) if min_expected >= 5 else None,
            "min_expected": float(min_expected),
        },
    )


def proportion_ci(req: AnalysisRequest) -> AnalysisResult:
    """二项比例置信区间 — Wilson Score 和 Clopper-Pearson 精确方法。

    适用于合格率、不良率、通过率等二项数据的区间估计。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n == 0:
        return AnalysisResult(task="proportion_ci", status="error",
            messages=[f"列「{req.target_col}」有效数据为空"])
    # 将数据转为 0/1
    unique_vals = data.unique()
    if len(unique_vals) > 2:
        return AnalysisResult(task="proportion_ci", status="error",
            messages=[f"列「{req.target_col}」包含超过 2 个不同值，需要二值数据"])

    # 自动识别"成功"标签
    success_val = req.params.get("success_value")
    if success_val is not None:
        successes = int((data == success_val).sum())
    else:
        # 尝试常见标签
        for label in ["合格", "是", "pass", "ok", "yes", "true", "success", "通过", "正常", 1, "1"]:
            if label in unique_vals:
                successes = int((data == label).sum())
                break
        else:
            # 默认取出现最多的值
            successes = int(data.value_counts().iloc[0])

    p_hat = successes / n

    from math import sqrt

    # Wilson Score CI
    z = sp_stats.norm.ppf(0.975)
    denominator = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denominator
    margin = z * sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator
    wilson_lower = max(0, center - margin)
    wilson_upper = min(1, center + margin)

    # Clopper-Pearson 精确 CI
    cp_lower = sp_stats.beta.ppf(0.025, successes, n - successes + 1) if successes > 0 else 0
    cp_upper = sp_stats.beta.ppf(0.975, successes + 1, n - successes) if successes < n else 1

    # 可视化
    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)
    methods = ["Wilson Score", "Clopper-Pearson"]
    uppers = [wilson_upper - p_hat, cp_upper - p_hat]
    ax.barh(methods, uppers, left=[wilson_lower, cp_lower], height=0.3,
            color=[PALETTE["data"]["secondary"], PALETTE["data"]["primary"]], edgecolor="white")
    ax.axvline(p_hat, color=PALETTE["target"]["primary"], linewidth=2, label=f"p_hat={p_hat:.4f}")
    ax.set_xlabel("比例", fontsize=10)
    ax.set_title(f"二项比例 95% CI — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8)
    ax.set_xlim(0, 1)
    fig.tight_layout()

    summary = (
        f"比例估计: {successes}/{n} = {p_hat:.2%}。"
        f"Wilson 95%CI: [{wilson_lower:.2%}, {wilson_upper:.2%}]"
    )

    return AnalysisResult(
        task="proportion_ci",
        tables={
            "proportion_ci": pd.DataFrame({
                "方法": ["点估计", "Wilson Score (推荐)", "Clopper-Pearson (精确)"],
                "下限": [f"{p_hat:.4f}", f"{wilson_lower:.4f}", f"{cp_lower:.4f}"],
                "上限": [f"{p_hat:.4f}", f"{wilson_upper:.4f}", f"{cp_upper:.4f}"],
            }),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "successes": successes, "n": n, "p_hat": p_hat,
            "wilson_ci": (float(wilson_lower), float(wilson_upper)),
            "clopper_pearson_ci": (float(cp_lower), float(cp_upper)),
        },
    )


def variance_test(req: AnalysisRequest) -> AnalysisResult:
    """方差齐性检验 — Levene 和 Bartlett 检验。

    用于 ANOVA 前验证方差齐性假设，或比较不同组的离散程度。
    """
    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P2 fix)
    group_col = req.params.get("group_col")
    if group_col is None:
        group_col = req.feature_cols[0] if req.feature_cols else None
    if group_col is None or group_col not in req.data.columns:
        return AnalysisResult(task="variance_test", status="error",
            messages=["需要提供分组列 (group_col)"])

    sub = req.data[[req.target_col, group_col]].dropna()
    groups = sub[group_col].unique()
    if len(groups) < 2:
        return AnalysisResult(task="variance_test", status="error",
            messages=["至少需要 2 个分组"])

    group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
    valid_groups = [(str(g), d) for g, d in zip(groups, group_data) if len(d) >= 2]

    if len(valid_groups) < 2:
        return AnalysisResult(task="variance_test", status="error",
            messages=["有效分组不足"])

    data_list = [d for _, d in valid_groups]

    # Levene (对非正态更鲁棒，推荐)
    try:
        lev_stat, lev_p = sp_stats.levene(*data_list, center="median")
    except Exception:
        logger.debug("Levene 检验失败", exc_info=True)
        lev_stat, lev_p = None, None

    # Bartlett (要求正态，更敏感)
    try:
        bart_stat, bart_p = sp_stats.bartlett(*data_list)
    except Exception:
        logger.debug("Bartlett 检验失败", exc_info=True)
        bart_stat, bart_p = None, None

    alpha = req.params.get("alpha", 0.05)

    # 判定
    if lev_p is not None:
        levene_result = "方差齐性 ✓" if lev_p >= alpha else f"方差不齐 (p={lev_p:.4f})"
    else:
        levene_result = "N/A"
    if bart_p is not None:
        bartlett_result = "方差齐性 ✓" if bart_p >= alpha else f"方差不齐 (p={bart_p:.4f})"
    else:
        bartlett_result = "N/A"

    # 各组建模统计
    desc_rows = []
    for g, d in valid_groups:
        desc_rows.append({
            "分组": g, "样本量": len(d), "均值": f"{np.mean(d):.4f}",
            "标准差": f"{np.std(d, ddof=1):.4f}",
            "方差": f"{np.var(d, ddof=1):.4f}",
            "IQR": f"{np.percentile(d, 75) - np.percentile(d, 25):.4f}",
        })

    return AnalysisResult(
        task="variance_test",
        tables={
            "variance_tests": pd.DataFrame({
                "检验方法": ["Levene (中位数, 推荐)", "Bartlett (需正态)"],
                "统计量": [f"{lev_stat:.4f}" if lev_stat else "N/A",
                          f"{bart_stat:.4f}" if bart_stat else "N/A"],
                "p值": [f"{lev_p:.4f}" if lev_p else "N/A",
                       f"{bart_p:.4f}" if bart_p else "N/A"],
                "结论": [levene_result, bartlett_result],
            }),
            "group_statistics": pd.DataFrame(desc_rows),
        },
        summary=(
            f"方差齐性检验: Levene {levene_result}"
            + (f", Bartlett {bartlett_result}" if bart_p is not None else "")
        ),
        metadata={
            "levene_p": float(lev_p) if lev_p else None,
            "bartlett_p": float(bart_p) if bart_p else None,
            "n_groups": len(valid_groups),
        },
    )


def cohens_kappa(req: AnalysisRequest) -> AnalysisResult:
    """Cohen's Kappa — 两个评定者之间的一致性评估。

    feature_cols[0] 和 feature_cols[1] 分别对应两个评定者的评定结果。
    """
    if len(req.feature_cols) < 2:
        return AnalysisResult(task="cohens_kappa", status="error",
            messages=["需要 2 个评定者列"])

    c1, c2 = req.feature_cols[0], req.feature_cols[1]
    sub = req.data[[c1, c2]].dropna()
    if len(sub) < 3:
        return AnalysisResult(task="cohens_kappa", status="error",
            messages=["有效数据不足"])

    # 构建一致性矩阵
    ctab = pd.crosstab(sub[c1], sub[c2])
    n = ctab.sum().sum()
    # 观察一致率
    p_o = np.trace(ctab.values) / n
    # 期望一致率
    row_sums = ctab.sum(axis=1).values
    col_sums = ctab.sum(axis=0).values
    p_e = np.sum(row_sums * col_sums) / n**2
    # Kappa
    kappa = (p_o - p_e) / (1 - p_e + EPSILON)
    # 标准误 (Fleiss-Cohen-Everitt 公式，适用于大样本)
    # SE₀(κ) = √[p_o(1-p_o) / (n(1-p_e)²)]  是 H₀:κ=0 下的近似
    # 生产环境使用简化公式；如需精确 SE 可用 bootstrap 方法
    se_kappa = np.sqrt((p_o * (1 - p_o)) / (n * (1 - p_e)**2 + EPSILON))
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
            "kappa_result": pd.DataFrame({
                "指标": ["Kappa", "观察一致率", "期望一致率", "Z值", "p值", "样本量", "判读"],
                "值": [f"{kappa:.4f}", f"{p_o:.1%}", f"{p_e:.1%}",
                      f"{z_kappa:.3f}", f"{p_val:.4f}", str(n), level],
            }),
        },
        summary=f"Cohen's Kappa={kappa:.3f} ({level}), p_o={p_o:.1%}, n={n}",
        metadata={"kappa": float(kappa), "p_o": float(p_o), "p_e": float(p_e),
                  "z": float(z_kappa), "level": level},
    )


def cronbach_alpha(req: AnalysisRequest) -> AnalysisResult:
    """Cronbach's α — 内部一致性信度分析。

    feature_cols 中的列视为量表的各个题项，计算 Cronbach's α 系数。
    α ≥ 0.9: 优秀, ≥ 0.8: 良好, ≥ 0.7: 可接受, < 0.7: 需改进。
    """
    items = [c for c in req.feature_cols if c in req.data.columns]
    if len(items) < 2:
        return AnalysisResult(task="cronbach_alpha", status="error",
            messages=["至少需要 2 个题项列"])

    sub = req.data[items].dropna()
    k = len(items)
    n = len(sub)
    if n < 3:
        return AnalysisResult(task="cronbach_alpha", status="error",
            messages=["有效数据不足"])

    # 各项方差 + 总分方差
    item_vars = sub.var(ddof=1).values
    total_var = float(sub.sum(axis=1).var(ddof=1))
    if total_var < EPSILON:
        return AnalysisResult(task="cronbach_alpha", status="error",
            messages=["总分方差为零，无法计算 α"])

    alpha = (k / (k - 1)) * (1 - np.sum(item_vars) / total_var)

    # Cronbach's α 异常值诊断警告
    warn_msgs = []
    if alpha < 0:
        warn_msgs.append("⚠ Cronbach's α 为负值，可能原因: 项目编码方向不一致、"
                         "负协方差项目存在、或量表结构性失效。建议检查项目编码方向。")
    elif alpha > 1:
        warn_msgs.append(f"⚠ Cronbach's α 超过理论上限 1.0（当前 {alpha:.4f}），"
                         "可能原因: 总分方差被低估或存在计算精度问题，请检查数据完整性。")

    # 如果删除某项后的 α
    alpha_if_deleted = []
    for i, col in enumerate(items):
        sub_drop = sub.drop(columns=[col])
        kd = k - 1
        item_vars_drop = sub_drop.var(ddof=1).values
        total_var_drop = float(sub_drop.sum(axis=1).var(ddof=1))
        if total_var_drop > EPSILON and kd > 1:
            a_drop = (kd / (kd - 1)) * (1 - np.sum(item_vars_drop) / total_var_drop)
        else:
            a_drop = None
        # 项总相关：零方差列会导致 .corr() 返回 NaN，格式化时需防护
        item_total_corr = sub[col].corr(sub.drop(columns=[col]).sum(axis=1))
        if pd.isna(item_total_corr) or item_vars[i] < EPSILON:
            corr_str = "N/A (零方差)"
        else:
            corr_str = f"{float(item_total_corr):.3f}"
        alpha_if_deleted.append({
            "题项": col,
            "删除后α": f"{a_drop:.4f}" if a_drop is not None else "N/A",
            "变化": (
                f"+{a_drop-alpha:.4f}" if a_drop is not None and a_drop > alpha + 0.01
                else f"{a_drop-alpha:.4f}" if a_drop is not None else "—"
            ),
            "方差": f"{item_vars[i]:.4f}",
            "项总相关": corr_str,
        })

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
            "alpha_summary": pd.DataFrame({
                "指标": ["Cronbach's α", "题项数", "样本量", "判读"],
                "值": [f"{alpha:.4f}", str(k), str(n), level],
            }),
            "item_analysis": pd.DataFrame(alpha_if_deleted),
        },
        summary=f"Cronbach's α={alpha:.3f} ({level}), {k} 题项, n={n}",
        metadata={"alpha": float(alpha), "k": k, "n": n, "level": level},
        messages=warn_msgs,
    )


def distribution_summary(req: AnalysisRequest) -> AnalysisResult:
    """分布特征摘要 — 描述性统计 + 正态/对数正态/Weibull 拟合。

    提供全面的单变量分布描述和拟合诊断。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 3:
        return AnalysisResult(task="distribution_summary", status="error",
            messages=["有效数据不足(至少3个点)"])


    # 描述性统计
    desc = {
        "样本量": n, "均值": float(data.mean()), "中位数": float(data.median()),
        "标准差": float(data.std(ddof=1)), "方差": float(data.var(ddof=1)),
        "偏度": float(data.skew()), "峰度": float(data.kurtosis()),
        "最小值": float(data.min()), "最大值": float(data.max()),
        "极差": float(data.max() - data.min()),
        "P1": float(data.quantile(0.01)), "P5": float(data.quantile(0.05)),
        "P10": float(data.quantile(0.10)), "P25": float(data.quantile(0.25)),
        "P75": float(data.quantile(0.75)), "P90": float(data.quantile(0.90)),
        "P95": float(data.quantile(0.95)), "P99": float(data.quantile(0.99)),
        "IQR": float(data.quantile(0.75) - data.quantile(0.25)),
        "CV(%)": round(float(data.std(ddof=1) / (abs(data.mean()) + EPSILON) * 100), 2),
    }

    # 正态性
    sw_p = float(sp_stats.shapiro(data)[1]) if n <= 5000 else None
    desc["Shapiro-Wilk p"] = round(sw_p, 4) if sw_p else "N/A"

    # 分布拟合
    fits = {}
    # Normal
    mu, sigma = sp_stats.norm.fit(data)
    ks_norm = float(sp_stats.kstest(data, "norm", args=(mu, sigma))[1])
    fits["Normal"] = {"params": f"μ={mu:.3f}, σ={sigma:.3f}", "KS p": round(ks_norm, 4)}

    # Lognormal (only if all positive)
    if (data > 0).all():
        shape, loc, scale = sp_stats.lognorm.fit(data, floc=0)
        ks_ln = float(sp_stats.kstest(data, "lognorm", args=(shape, 0, scale))[1])
        fits["Lognormal"] = {"params": f"σ={shape:.3f}, μ={np.log(scale):.3f}", "KS p": round(ks_ln, 4)}

    # Weibull (only if all positive)
    if (data > 0).all():
        try:
            shape_w, loc_w, scale_w = sp_stats.weibull_min.fit(data, floc=0)
            ks_w = float(sp_stats.kstest(data, "weibull_min", args=(shape_w, 0, scale_w))[1])
            fits["Weibull"] = {"params": f"β={shape_w:.3f}, η={scale_w:.3f}", "KS p": round(ks_w, 4)}
        except Exception:
            logger.debug("Weibull 拟合失败", exc_info=True)
            pass

    # 直方图 + 拟合曲线
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.hist(data, bins=min(30, int(np.sqrt(n))*2), density=True,
            color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.7, label="数据")
    x_fit = np.linspace(data.min(), data.max(), 200)
    ax.plot(x_fit, sp_stats.norm.pdf(x_fit, mu, sigma), "-", color=PALETTE["data"]["primary"],
            linewidth=2, label=f"Normal (KS p={ks_norm:.3f})")
    if "Lognormal" in fits:
        ax.plot(x_fit, sp_stats.lognorm.pdf(x_fit, shape, 0, scale), "--",
                color=PALETTE["target"]["primary"], linewidth=1.5, label=f"Lognormal (KS p={ks_ln:.3f})")
    if "Weibull" in fits:
        ax.plot(x_fit, sp_stats.weibull_min.pdf(x_fit, shape_w, 0, scale_w), ":",
                color=PALETTE["center"]["primary"], linewidth=1.5, label=f"Weibull (KS p={ks_w:.3f})")
    ax.axvline(data.mean(), color=PALETTE["data"]["primary"], linestyle="--", linewidth=1, alpha=0.5)
    ax.axvline(data.median(), color=PALETTE["target"]["primary"], linestyle="--", linewidth=1, alpha=0.5)
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("密度", fontsize=10)
    ax.set_title(f"分布特征 — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()

    # 最佳拟合
    best_fit = max(fits, key=lambda k: fits[k]["KS p"]) if fits else "None"

    return AnalysisResult(
        task="distribution_summary",
        tables={
            "descriptive_stats": pd.DataFrame([desc]).T.rename(columns={0: "值"}),
            "distribution_fits": pd.DataFrame(fits).T,
        },
        figures=[fig],
        summary=(
            f"{req.target_col}: μ={desc['均值']:.3f}, M={desc['中位数']:.3f}, "
            f"σ={desc['标准差']:.3f}, CV={desc['CV(%)']:.1f}%。"
            f"最佳拟合: {best_fit} (KS p={fits[best_fit]['KS p']:.3f})"
        ),
        metadata={"descriptive": desc, "fits": fits, "best_fit": best_fit},
    )


def normality_check(req: AnalysisRequest) -> AnalysisResult:
    """正态性评估 — 对多个列执行 Shapiro-Wilk 检验，推荐变换方法。

    返回偏度/峰度统计量和变换建议 (log, sqrt, Box-Cox, Yeo-Johnson)。
    """
    cols = [c for c in ([req.target_col] + req.feature_cols) if c in req.data.columns]
    if not cols:
        return AnalysisResult(task="normality_check", status="error",
            messages=["没有可分析的列"])

    results = []
    for col in cols:
        d = req.data[col].dropna()
        n = len(d)
        if n < 3:
            results.append({
                "列名": col, "样本量": n, "Shapiro-Wilk p": None,
                "偏度": None, "峰度": None, "正态性": "样本不足",
                "建议变换": "—",
            })
            continue

        _, sw_p = sp_stats.shapiro(d) if n <= 5000 else (None, None)
        # Anderson-Darling (更稳健的大样本检验)
        try:
            ad_result = sp_stats.anderson(d, dist="norm", method="interpolate")
            ad_stat = float(ad_result.statistic)
            # 取 5% 显著性水平的临界值
            ad_crit = float(ad_result.critical_values[2]) if len(ad_result.critical_values) > 2 else 0
            ad_normal = ad_stat < ad_crit
        except Exception:
            logger.debug("Anderson-Darling 检验失败", exc_info=True)
            ad_stat, ad_crit, ad_normal = None, None, None

        skew = float(d.skew())
        kurt = float(d.kurtosis())

        # 判断和建议变换 (综合 S-W 和 A-D)
        sw_normal = sw_p is not None and sw_p > 0.05
        is_normal = sw_normal or (ad_normal if ad_normal is not None else False)

        if is_normal:
            normality = "正态 ✓"
            recommendation = "无需变换"
        else:
            normality = f"非正态 (S-W p={sw_p:.4f})" if sw_p else "—"
            if skew > 1.5:
                if (d > 0).all():
                    recommendation = "Box-Cox (右偏严重)"
                else:
                    recommendation = "Yeo-Johnson (右偏严重)"
            elif skew > 0.5:
                if (d > 0).all():
                    recommendation = "对数变换 log(x)"
                else:
                    recommendation = "平方根变换 √(x+const)"
            elif skew < -1.5:
                recommendation = "平方变换 x²"
            elif skew < -0.5:
                if (d > 0).all():
                    recommendation = "倒数变换 1/x"
                else:
                    recommendation = "反射+对数变换"
            else:
                recommendation = "Box-Cox / Yeo-Johnson"

        ad_info = f"A-D stat={ad_stat:.3f}" if ad_stat else "N/A"
        results.append({
            "列名": col, "样本量": n,
            "Shapiro-Wilk p": f"{sw_p:.4f}" if sw_p else "N/A",
            "Anderson-Darling": ad_info,
            "偏度": f"{skew:.3f}", "峰度": f"{kurt:.3f}",
            "正态性": normality, "建议变换": recommendation,
        })

    results_df = pd.DataFrame(results)

    # Q-Q 子图矩阵
    n_cols_plot = min(len(cols), 6)
    n_rows = (n_cols_plot + 2) // 3
    fig = Figure(figsize=(4 * min(3, n_cols_plot), 3.5 * n_rows))
    for i, col in enumerate(cols[:n_cols_plot]):
        ax = fig.add_subplot(n_rows, min(3, n_cols_plot), i + 1)
        d = req.data[col].dropna()
        sp_stats.probplot(d, dist="norm", plot=ax)
        ax.set_title(col, fontsize=9)
    fig.tight_layout()

    # 汇总
    normal_count = sum(1 for r in results if "正态" in str(r.get("正态性", "")))
    summary = (
        f"正态性评估: {normal_count}/{len(cols)} 列满足正态性。"
        + (f" 偏度最大列: {results_df.dropna(subset=['偏度']).sort_values('偏度', key=lambda x: x.str.replace('-','').astype(float)).iloc[-1]['列名']}"
           if len(results_df.dropna(subset=['偏度'])) > 0 else "")
    )

    return AnalysisResult(
        task="normality_check",
        tables={"normality_results": results_df},
        figures=[fig],
        summary=summary,
        metadata={
            "n_columns": len(cols),
            "normal_count": normal_count,
            "recommendations": {r["列名"]: r["建议变换"] for r in results},
        },
    )
