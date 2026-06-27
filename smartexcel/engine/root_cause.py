import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.formula.api import ols
from smartexcel.core.contracts import AnalysisRequest, AnalysisResult


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
            messages=[f"ANOVA 模型拟合失败: {e}"])

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
        messages=warnings if warnings else None,
    )
