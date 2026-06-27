import numpy as np
import pandas as pd
from scipy import stats
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
