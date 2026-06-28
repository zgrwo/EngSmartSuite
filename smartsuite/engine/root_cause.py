import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats
from sklearn.tree import DecisionTreeRegressor, plot_tree
from statsmodels.formula.api import ols
from statsmodels.stats.outliers_influence import variance_inflation_factor

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def correlation_analysis(req: AnalysisRequest) -> AnalysisResult:
    """Pearson 相关性矩阵分析，含 p 值。"""
    # 去重：防止 target_col 同时出现在 feature_cols 中导致重复列
    cols = list(dict.fromkeys(req.feature_cols + [req.target_col]))
    cols = [c for c in cols if c in req.data.columns]
    corr = req.data[cols].corr()

    # p 值矩阵
    pmat = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for c1 in cols:
        for c2 in cols:
            mask = req.data[c1].notna() & req.data[c2].notna()
            if mask.sum() >= 3:
                _, p = stats.pearsonr(req.data.loc[mask, c1], req.data.loc[mask, c2])
                pmat.loc[c1, c2] = p
            else:
                pmat.loc[c1, c2] = np.nan

    target_corr = corr[req.target_col].drop(req.target_col).sort_values(ascending=False)
    top_factor = target_corr.index[0] if len(target_corr) > 0 else "N/A"
    top_value = target_corr.iloc[0] if len(target_corr) > 0 else 0

    # 全矩阵热力图
    n = len(cols)
    fig = Figure(figsize=(max(n*0.85, 5), max(n*0.75, 4)))
    ax = fig.add_subplot(111)
    im = ax.imshow(corr.values, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
    ax.set_xticks(range(n)); ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(n)); ax.set_yticklabels(cols, fontsize=8)
    for i in range(n):
        for j in range(n):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center",
                    fontsize=7, fontweight="bold",
                    color="white" if abs(v) > 0.5 else "black")
    fig.colorbar(im, ax=ax, shrink=0.8, label="r")
    ax.set_title(f"相关性热力图 — {req.target_col}", fontsize=11)
    fig.tight_layout()

    return AnalysisResult(
        task="correlation",
        tables={"correlation_matrix": corr, "p_values": pmat.astype(float)},
        figures=[fig],
        summary=f"与「{req.target_col}」相关性最强的因子是「{top_factor}」(r={top_value:.3f})",
        metadata={"target_correlations": target_corr.to_dict()},
    )


def anova_analysis(req: AnalysisRequest) -> AnalysisResult:
    """多因子 ANOVA 方差分析。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if req.target_col not in req.data.columns:
        return AnalysisResult(task="anova", status="error",
            messages=[f"目标列「{req.target_col}」不存在于数据中"])

    if len(cols) < 1:
        return AnalysisResult(task="anova", status="error",
            messages=["没有可用于 ANOVA 分析的特征列"])

    # 构建公式：可选两两交互项
    terms = [f"Q('{c}')" for c in cols]
    if req.params.get("interactions") and len(cols) >= 2:
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                terms.append(f"Q('{cols[i]}'):Q('{cols[j]}')")
    formula = f"Q('{req.target_col}') ~ " + " + ".join(terms)

    warn_msgs: list[str] = []
    try:
        model = ols(formula, data=req.data).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
    except Exception:
        return AnalysisResult(task="anova", status="error",
            messages=["ANOVA 模型拟合失败，请检查数据是否包含缺失值或非数值列"])

    alpha = req.params.get("alpha", 0.05)
    sig_factors = []
    for col in cols:
        try:
            p_val = anova_table.loc[f"Q('{col}')", "PR(>F)"]
            if p_val < alpha:
                sig_factors.append(f"{col}(p={p_val:.4f})")
        except KeyError:
            warn_msgs.append(f"因子「{col}」在 ANOVA 结果表中未找到")

    summary = f"显著影响「{req.target_col}」的因子: {', '.join(sig_factors)}" if sig_factors \
        else f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})"

    coef_df = pd.DataFrame({
        "变量": model.params.index, "系数": model.params.values,
        "标准误": model.bse.values, "t值": model.tvalues.values, "p值": model.pvalues.values,
    })

    # 箱线图：按第一个显著因子（或第一个因子）分组展示目标变量分布
    fig_box = Figure(figsize=(max(len(cols)*1.6, 5), 4))
    ax_box = fig_box.add_subplot(111)
    group_col = sig_factors[0].split("(")[0] if sig_factors else cols[0]
    groups = req.data[[req.target_col, group_col]].dropna()
    group_names = sorted(groups[group_col].unique())
    group_data = [groups[groups[group_col] == g][req.target_col].values for g in group_names]
    bp = ax_box.boxplot(group_data, tick_labels=[str(g) for g in group_names], patch_artist=True)
    for patch in bp['boxes']:
        patch.set_facecolor("#6baed6")
    ax_box.set_xlabel(group_col, fontsize=9)
    ax_box.set_ylabel(req.target_col, fontsize=9)
    ax_box.set_title(f"箱线图 — {req.target_col} by {group_col}", fontsize=11)
    fig_box.tight_layout()

    return AnalysisResult(
        task="anova",
        tables={"anova_table": anova_table, "coefficients": coef_df},
        figures=[fig_box],
        summary=summary,
        metadata={"r_squared": model.rsquared, "r_squared_adj": model.rsquared_adj},
        messages=warn_msgs,
    )


def hypothesis_test(req: AnalysisRequest) -> AnalysisResult:
    """两样本假设检验 (t-test / Mann-Whitney U)。"""
    group_col = req.params.get("group_col", req.feature_cols[0] if req.feature_cols else "group")
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(task="hypothesis_test", status="error",
            messages=[f"分组列需要恰好 2 个水平，当前有 {len(groups)} 个"])

    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()
    test_type = req.params.get("test", "ttest_ind")

    if test_type == "mannwhitney":
        stat, p = stats.mannwhitneyu(g1, g2)
        test_name = "Mann-Whitney U 检验"
    else:
        stat, p = stats.ttest_ind(g1, g2)
        test_name = "独立样本 t 检验"

    alpha = req.params.get("alpha", 0.05)
    conclusion = "存在显著差异" if p < alpha else "未发现显著差异"

    # 双样本箱线图
    fig = Figure(figsize=(5, 4))
    ax = fig.add_subplot(111)
    bp = ax.boxplot([g1, g2], tick_labels=[str(groups[0]), str(groups[1])], patch_artist=True)
    for patch, color in zip(bp['boxes'], ["#6baed6", "#fd8d3c"]):
        patch.set_facecolor(color)
    ax.set_ylabel(req.target_col, fontsize=9)
    ax.set_title(f"{test_name} — {req.target_col} (p={p:.4f})", fontsize=11)
    fig.tight_layout()

    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量": [stat], "p值": [p],
            "显著性水平": [alpha],
            "结论": [f"{groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})"],
        })},
        figures=[fig],
        summary=f"{groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})",
        metadata={"test": test_name, "statistic": stat, "p_value": p, "alpha": alpha},
    )


def decision_tree_analysis(req: AnalysisRequest) -> AnalysisResult:
    """决策树特征重要性分析。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(task="decision_tree", status="error",
            messages=["需要至少 1 个因子列"])

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 5:
        return AnalysisResult(task="decision_tree", status="error",
            messages=[f"有效样本({len(df)})不足"])

    X = df[cols]
    y = df[req.target_col]
    max_depth = req.params.get("max_depth", 5)

    tree = DecisionTreeRegressor(max_depth=max_depth, random_state=42)
    tree.fit(X, y)

    fi = pd.DataFrame({"因子": cols, "重要性": tree.feature_importances_})
    fi = fi.sort_values("重要性", ascending=False).reset_index(drop=True)
    top = fi.iloc[0] if len(fi) > 0 else None

    # 图1: 特征重要性柱状图
    fig_imp = Figure(figsize=(max(len(fi)*0.7, 5), 3.5))
    ax = fig_imp.add_subplot(111)
    colors = ["#2171b5" if v > 0.1 else "#6baed6" for v in fi["重要性"]]
    ax.barh(fi["因子"], fi["重要性"], color=colors)
    ax.set_xlabel("重要性", fontsize=9)
    ax.set_title(f"决策树特征重要性 — {req.target_col}", fontsize=11)
    ax.invert_yaxis()
    fig_imp.tight_layout()

    # 图2: 决策树分层结构图 (需 Canvas 支持 plot_tree)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig_tree = Figure(figsize=(12, max(tree.get_depth() * 1.2, 4)))
    FigureCanvasAgg(fig_tree)  # plot_tree 需要 renderer
    ax_tree = fig_tree.add_subplot(111)
    plot_tree(tree, ax=ax_tree, feature_names=cols, filled=True,
              rounded=True, fontsize=8, precision=2, max_depth=4)
    ax_tree.set_title(f"决策树结构 — {req.target_col}", fontsize=12)
    fig_tree.tight_layout()

    return AnalysisResult(
        task="decision_tree",
        tables={"feature_importance": fi},
        figures=[fig_imp, fig_tree],
        summary=f"关键影响因子: {top['因子']} (重要性={top['重要性']:.3f})" if top is not None
            else "分析完成",
        metadata={"top_factor": top["因子"] if top is not None else None},
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
        high_vif = vif_data[vif_data["VIF"] > 5]
        warning = f"注意: {len(high_vif)} 个变量 VIF>5，存在共线性风险" if len(high_vif) > 0 \
            else "所有变量 VIF<=5，无明显共线性"

        # VIF 柱状图
        vif_plot = vif_data
        fig = Figure(figsize=(max(len(vif_plot)*0.7, 5), 3.5))
        ax = fig.add_subplot(111)
        colors = ["#d94801" if v > 5 else "#2171b5" for v in vif_plot["VIF"]]
        ax.barh(vif_plot["变量"], vif_plot["VIF"], color=colors)
        ax.axvline(5, color="red", linestyle="--", linewidth=1, label="VIF=5 阈值")
        ax.set_xlabel("VIF", fontsize=9)
        ax.set_title("共线性诊断 — VIF", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="vif", tables={"vif_table": vif_data}, figures=[fig], summary=warning,
            metadata={"high_vif_count": len(high_vif)},
        )
    except Exception:
        return AnalysisResult(task="vif", status="error",
                              messages=["VIF 计算失败，请检查数据是否存在共线性或数值异常"])
