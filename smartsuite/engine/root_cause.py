import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from sklearn.tree import DecisionTreeRegressor
from statsmodels.formula.api import ols
from statsmodels.stats.outliers_influence import variance_inflation_factor

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def correlation_analysis(req: AnalysisRequest) -> AnalysisResult:
    """Pearson 相关性矩阵分析，含 p 值。"""
    cols = req.feature_cols + [req.target_col]
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

    return AnalysisResult(
        task="correlation",
        tables={"correlation_matrix": corr, "p_values": pmat.astype(float)},
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

    formula = f"Q('{req.target_col}') ~ " + " + ".join(f"Q('{c}')" for c in cols)

    warnings: list[str] = []
    try:
        model = ols(formula, data=req.data).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
    except Exception as e:
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
            warnings.append(f"因子「{col}」在 ANOVA 结果表中未找到")

    summary = f"显著影响「{req.target_col}」的因子: {', '.join(sig_factors)}" if sig_factors \
        else f"未发现对「{req.target_col}」显著影响的因子 (α={alpha})"

    coef_df = pd.DataFrame({
        "变量": model.params.index, "系数": model.params.values,
        "标准误": model.bse.values, "t值": model.tvalues.values, "p值": model.pvalues.values,
    })

    return AnalysisResult(
        task="anova",
        tables={"anova_table": anova_table, "coefficients": coef_df},
        summary=summary,
        metadata={"r_squared": model.rsquared, "r_squared_adj": model.rsquared_adj},
        messages=warnings if warnings else [],
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

    return AnalysisResult(
        task="hypothesis_test",
        tables={"test_results": pd.DataFrame({
            "检验方法": [test_name], "统计量": [stat], "p值": [p],
            "显著性水平": [alpha],
            "结论": [f"{groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})"],
        })},
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

    return AnalysisResult(
        task="decision_tree",
        tables={"feature_importance": fi},
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
        vif_data = pd.DataFrame({
            "变量": X.columns,
            "VIF": [variance_inflation_factor(X.values, i) for i in range(X.shape[1])],
        })
        high_vif = vif_data[vif_data["VIF"] > 5]
        warning = f"注意: {len(high_vif)} 个变量 VIF>5，存在共线性风险" if len(high_vif) > 0 \
            else "所有变量 VIF<=5，无明显共线性"

        return AnalysisResult(
            task="vif", tables={"vif_table": vif_data}, summary=warning,
            metadata={"high_vif_count": len(high_vif)},
        )
    except Exception as e:
        return AnalysisResult(task="vif", status="error",
                              messages=["VIF 计算失败，请检查数据是否存在共线性或数值异常"])
