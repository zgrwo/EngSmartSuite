"""相关分析。"""

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from statsmodels.nonparametric.smoothers_lowess import lowess

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Opt, Spec
from smartsuite.engine._constants import (
    EPSILON,
    SIG_EXTREME,
    SIG_HIGH,
    SIG_MODERATE,
)
from smartsuite.engine._guard import (
    BoundaryReport,
    clean_frame,
    degenerate_column_code,
    degenerate_column_reason,
    first_degenerate_reason,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display
from smartsuite.engine.root_cause._shared import _correlation_ci, _effect_size_label

logger = logging.getLogger(__name__)

# ── 声明式参数契约（P4 步骤③，第二十三轮）──
# 契约：docs/governance/improvement-plan.md §六
PARAM_SPECS = {
    "correlation": Spec(
        method=Opt(
            Choice(
                ("pearson", "Pearson（线性相关）"),
                ("spearman", "Spearman（秩相关，抗离群）"),
                ("kendall", "Kendall（秩相关，小样本更稳）"),
            ),
            default="pearson",
            label="相关方法",
            hint="Pearson 测线性；Spearman/Kendall 测单调关系且抗离群值",
        ),
        control_vars=Opt(
            # 默认值与 `DEFAULT_PARAMS` 一致是 `[]`（而非 `None`）——
            # 由 `Spec.defaults()` 的对拍用例抓出。引擎侧把 `None` 与 `[]`
            # 都当作"无控制变量"，故两者语义等价，但声明必须与默认值表一致。
            default=[],
            label="控制变量(逗号分隔)",
            hint="偏相关：控制这些变量后再计算目标与其余列的净相关",
        ),
    ),
}


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


def correlation_analysis(req: AnalysisRequest) -> AnalysisResult:
    """相关性矩阵分析（Pearson/Spearman），含多重比较校正和显著性标记。"""
    frame = req.data
    if req.target_col not in frame.columns:
        return AnalysisResult(
            task="correlation",
            status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中"],
        )
    # 去重：防止 target_col 同时出现在 feature_cols 中导致重复列
    cols = list(dict.fromkeys(req.feature_cols + [req.target_col]))
    cols = [c for c in cols if c in frame.columns]

    # 校验所有列为数值型，避免非数值列静默失败
    non_numeric = [c for c in cols if not pd.api.types.is_numeric_dtype(frame[c])]
    if non_numeric:
        return AnalysisResult(
            task="correlation",
            status="error",
            messages=[
                f"以下列非数值型，无法计算相关性: {non_numeric}。"
                "请使用数据预处理将类别列转换为数值型。"
            ],
        )

    if len(cols) < 2:
        return AnalysisResult(
            task="correlation",
            status="error",
            messages=["至少需要 1 个因子列与目标列进行相关性分析，当前无有效因子列"],
        )

    # ── 边界处置（B1）：±Inf 必须清洗并**披露**（审查 2026-10-09 P0-8 / P1-6）──
    # 原实现只在 p 值循环里手写成对 `np.isfinite` 掩码，**没有任何披露** ——
    # 用户看到 n=60 而实际参与计算的样本已变（实测 summary 与「NaN 对照」逐字相同）。
    # `drop_nan=False`：NaN 保留给 pandas `.corr()` 的**成对完整观测**口径，
    # 否则一个因子的缺失会压垮整表样本（见 `_guard.clean_frame` 的说明）。
    _boundary = BoundaryReport()
    frame, _n_non_finite = clean_frame(frame, cols, report=_boundary, drop_nan=False)

    # 最小样本守卫：n<3 时任意两列 |r|=1 的“伪完美相关”会误导结论（允许部分列缺失）
    if frame[cols].dropna(how="all").shape[0] < 3:
        return AnalysisResult(
            task="correlation",
            status="error",
            messages=["有效样本不足(至少3行含数据)，相关分析在极小样本下无意义"]
            + _boundary.messages(),
        )

    # 参数校验（P4 步骤③，第二十三轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 原白名单检查已由 `Choice` 表达并**给出可选值的中文文案**（供下拉框显示）。
    method = PARAM_SPECS["correlation"].validate_or_raise(req.params).method
    if method == "spearman":
        corr = frame[cols].corr(method="spearman")
        corr_label = "Spearman ρ"
    elif method == "kendall":
        corr = frame[cols].corr(method="kendall")
        corr_label = "Kendall τ"
    else:
        corr = frame[cols].corr(method="pearson")
        corr_label = "Pearson r"

    # p 值矩阵
    pmat = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for c1 in cols:
        for c2 in cols:
            # 常量列防护：nunique<=1 时相关性/检验无定义，直接 NaN（与其他函数一致，
            # 避免 pearsonr/spearmanr/kendalltau 返回 NaN 后混入校正矩阵）
            # 收尾轮（契约 #5）：判据改走 `_guard` 单一实现（等价改写，不改变矩阵结果）
            if (
                degenerate_column_code(frame[c1]) is not None
                or degenerate_column_code(frame[c2]) is not None
            ):
                pmat.loc[c1, c2] = np.nan
                continue
            # 审查 2026-09-22 发现 4：pandas `.corr()` 对 ±Inf 按缺失成对剔除，
            # 原 mask 只查 notna → r 有限而 p 为 NaN（同一表内自相矛盾）。
            # 审查 2026-10-09 P1-6：±Inf 已在**入口**由 `_guard.clean_frame(drop_nan=False)`
            # 按行剔除并披露，故此处只需处理 **NaN 的成对缺失**（与 `.corr()` 的
            # 「成对完整观测」口径一致）—— 不再手写非有限值清洗。
            _v1 = frame[c1].to_numpy(dtype=float, na_value=np.nan)
            _v2 = frame[c2].to_numpy(dtype=float, na_value=np.nan)
            mask = ~np.isnan(_v1) & ~np.isnan(_v2)
            if mask.sum() >= 3:
                if method == "spearman":
                    _, p = sp_stats.spearmanr(frame.loc[mask, c1], frame.loc[mask, c2])
                elif method == "kendall":
                    _, p = sp_stats.kendalltau(frame.loc[mask, c1], frame.loc[mask, c2])
                else:
                    _, p = sp_stats.pearsonr(frame.loc[mask, c1], frame.loc[mask, c2])
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
    for i, _c1 in enumerate(cols):
        for j, _c2 in enumerate(cols):
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
    sig_after = int(
        (pmat_corrected.values[np.triu_indices_from(pmat_corrected.values, k=1)] < 0.05).sum()
    )
    correction_note = (
        f"Bonferroni校正前 {sig_before} 对显著，校正后 {sig_after} 对显著（{n_comparisons} 对比较）"
    )

    # ── 零方差提前检查：避免浪费图表生成计算 (P2 fix: 移到图表生成之前) ──
    if pd.isna(top_value):
        # 审查 2026-08-19 #2.6/#3.4：原消息一律指向目标列，但常量特征列
        # （或有效样本不足）同样会导致 top_value=NaN，消息须指向真实原因
        # Round-2 #A2m：目标列本身为常量时消息应指向目标列而非误称"特征列"
        # 收尾轮（契约 #5）：特征列与目标列的**原因**一律取自 `_guard` 三级归因 ——
        # 原先手写 `nunique(dropna=True) <= 1` 会把「整列为空」也说成"常量列"。
        _feat_reason = first_degenerate_reason(
            frame, [c for c in cols if c != req.target_col], label="特征列"
        )
        _target_code = degenerate_column_code(frame[req.target_col])
        if _feat_reason is not None and _target_code is None:
            msg = f"{_feat_reason}，无法计算相关性分析。请移除该列或检查数据。"
        elif _target_code in ("E_DATA_EMPTY_COLUMN", "E_DATA_INSUFFICIENT_N"):
            # 空列 / 单观测此前被误报为"方差为零（常量列）"——按真实原因说明
            msg = (
                f"{degenerate_column_reason(frame[req.target_col], what=f'目标列「{req.target_col}」')}"
                f"，无法计算相关性分析。"
            )
        else:
            msg = (
                f"目标列「{req.target_col}」方差为零（常量列）或有效样本不足，无法计算相关性分析。"
            )
        return AnalysisResult(task="correlation", status="error", messages=[msg])

    # ── 热力图增强：只标注显著单元格，添加星号 ──
    n = len(cols)
    fig = Figure(figsize=(max(n * 0.95, 6), max(n * 0.85, 4.5)))
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
                ax.text(
                    j,
                    i,
                    f"{v:+.2f}{stars}",
                    ha="center",
                    va="center",
                    fontsize=8 if n <= 15 else 6,
                    fontweight="bold" if is_sig else "normal",
                    color="white" if abs(v) > 0.65 else "black",
                )
    fig.colorbar(im, ax=ax, shrink=0.8, label=corr_label)
    ax.set_title(
        f"相关性热力图 — {req.target_col}\n({corr_label} | {correction_note})",
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
                        if ri == ci:
                            # 对角线：单列直方图。注意 df[[cv1, cv2]] 在 cv1==cv2 时
                            # 会选中两个同名列 → sub[cv1] 返回 2D → matplotlib≥3.9
                            # hist 严格校验 color 报错（此前被 try 吞掉致图缺失）
                            vals = frame[cv1].dropna().values
                            if len(vals) < 2:
                                continue
                            ax.hist(
                                vals,
                                bins=min(15, len(vals) // 2),
                                color=PALETTE["data"]["secondary"],
                                edgecolor="white",
                                alpha=0.8,
                            )
                            ax.set_title(cv1, fontsize=9)
                            continue
                        sub = frame[[cv1, cv2]].dropna()
                        if len(sub) < 2:
                            continue
                        ax.scatter(
                            sub[cv1].values,
                            sub[cv2].values,
                            s=8,
                            alpha=0.5,
                            color=PALETTE["data"]["primary"],
                        )
                        # LOWESS 平滑趋势线
                        if len(sub) >= 20:
                            try:
                                # 常量/近常量序列的平滑除零告警：结果由后续哨兵判定
                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore", RuntimeWarning)
                                    smoothed = lowess(
                                        sub[cv2].values,
                                        sub[cv1].values,
                                        frac=0.3,
                                        return_sorted=True,
                                    )
                                ax.plot(
                                    smoothed[:, 0],
                                    smoothed[:, 1],
                                    "-",
                                    color=PALETTE["target"]["primary"],
                                    linewidth=1.5,
                                    alpha=0.7,
                                )
                            except (ValueError, RuntimeError):
                                logger.debug("LOWESS 平滑失败", exc_info=True)
                                pass
                            r_val = (
                                corr.loc[cv1, cv2]
                                if cv1 in corr.index and cv2 in corr.columns
                                else 0
                            )
                            ax.annotate(
                                f"r={r_val:.2f}",
                                xy=(0.95, 0.05),
                                xycoords="axes fraction",
                                ha="right",
                                fontsize=7.5,
                                color=PALETTE["target"]["primary"],
                                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7),
                            )
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
                logger.debug("散点矩阵生成失败", exc_info=True)  # 散点矩阵失败不影响主分析

    # ── 偏相关分析（控制混淆变量）──
    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P3 fix)
    control_vars = req.params.get("control_vars")
    if control_vars is None:
        control_vars = []
    # Round-2 P3：字符串 control_vars 此前被逐字符过滤静默变 []
    if isinstance(control_vars, str):
        control_vars = [c.strip() for c in control_vars.split(",") if c.strip()]
    if not isinstance(control_vars, list):
        return AnalysisResult(
            task="correlation",
            status="error",
            messages=["control_vars 必须是列名列表或逗号分隔字符串"],
        )
    control_vars = [
        c
        for c in control_vars
        if c in frame.columns and c != req.target_col and pd.api.types.is_numeric_dtype(frame[c])
    ]
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
            sub = frame[all_vars].dropna()
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
            r_zero = (
                corr.loc[req.target_col, fc]
                if req.target_col in corr.index and fc in corr.columns
                else np.nan
            )
            partial_results.append(
                {
                    "因子": fc,
                    "零阶相关(r)": round_for_display(float(r_zero), 4)
                    if not np.isnan(r_zero)
                    else None,
                    "偏相关(r_partial)": round_for_display(float(r_partial), 4),
                    "p值": round_for_display(float(p_partial), 4),
                    "变化": (
                        "抑制"
                        if not np.isnan(r_zero) and abs(r_partial) > abs(r_zero) + 0.05
                        else "削弱"
                        if not np.isnan(r_zero) and abs(r_partial) < abs(r_zero) - 0.05
                        else "稳定"
                    ),
                }
            )
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
            fig_partial = Figure(figsize=(max(len(partial_df) * 0.9, 6), 4))
            ax_p = fig_partial.add_subplot(111)
            x = np.arange(len(partial_df))
            width = 0.35
            zero_vals = [v if v is not None else 0 for v in partial_df["零阶相关(r)"]]
            partial_vals = partial_df["偏相关(r_partial)"].values
            ax_p.bar(
                x - width / 2,
                zero_vals,
                width,
                label="零阶相关",
                color=PALETTE["data"]["secondary"],
                alpha=0.8,
            )
            ax_p.bar(
                x + width / 2,
                partial_vals,
                width,
                label="偏相关(控制混淆)",
                color=PALETTE["data"]["primary"],
                alpha=0.9,
            )
            ax_p.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
            ax_p.set_xticks(x)
            ax_p.set_xticklabels(partial_df["因子"], rotation=45, ha="right", fontsize=9)
            ax_p.set_ylabel("相关系数", fontsize=10)
            ax_p.set_title(
                f"偏相关分析 — {req.target_col} | 控制变量: {', '.join(control_vars)}",
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
                if top_partial["变化"] != "稳定"
                else ""
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
        messages=_boundary.messages(),
        metadata={
            "target_correlations": target_corr.to_dict(),
            "method": method,
            "n_comparisons": n_comparisons,
            "sig_before_correction": sig_before,
            "sig_after_correction": sig_after,
            "target_p_adjusted": target_p_adj,
            "partial_correlations": partial_corr_meta,
            "control_vars": control_vars,
            "effect_size": float(top_value),
            "effect_name": corr_label,
            "effect_label": _effect_size_label(float(top_value), "correlation"),
            "effect_size_ci": _correlation_ci(float(top_value), int(frame[cols].dropna().shape[0])),
            "boundary_codes": _boundary.codes(),
        },
    )
