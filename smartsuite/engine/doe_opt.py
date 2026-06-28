import matplotlib
import numpy as np
import pandas as pd
import statsmodels.api as sm

matplotlib.use("Agg")
from matplotlib.figure import Figure
from sklearn.linear_model import Ridge

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def regression_analysis(req: AnalysisRequest) -> AnalysisResult:
    """线性回归建模 (OLS)。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="regression", status="error",
            messages=["需要至少 1 个因子列"],
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < len(cols) + 2:
        return AnalysisResult(
            task="regression", status="error",
            messages=[f"有效样本量({len(df)})不足，需要至少{len(cols)+2}条"],
        )

    try:
        X = sm.add_constant(df[cols])
        y = df[req.target_col]
        model = sm.OLS(y, X).fit()

        coef_df = pd.DataFrame({
            "变量": X.columns,
            "系数": model.params.values,
            "标准误": model.bse.values,
            "t值": model.tvalues.values,
            "p值": model.pvalues.values,
        })

        sig_vars = coef_df[(coef_df["p值"] < 0.05) & (coef_df["变量"] != "const")]

        return AnalysisResult(
            task="regression",
            tables={"coefficients": coef_df},
            summary=f"R²={model.rsquared:.4f}, 调整R²={model.rsquared_adj:.4f}, "
                    f"显著变量: {len(sig_vars)}/{len(cols)}",
            metadata={
                "r_squared": model.rsquared,
                "r_squared_adj": model.rsquared_adj,
                "f_statistic": model.fvalue,
                "f_pvalue": model.f_pvalue,
                "significant_vars": sig_vars["变量"].tolist(),
            },
        )
    except Exception as e:
        return AnalysisResult(task="regression", status="error",
                              messages=["回归模型拟合失败，请检查数据是否存在缺失值或共线性"])


def response_surface_analysis(req: AnalysisRequest) -> AnalysisResult:
    """响应面分析 — 二次模型 + 3D 曲面图。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(
            task="response_surface", status="error",
            messages=["响应面分析需要至少 2 个因子"],
        )

    c1, c2 = cols[0], cols[1]
    df = req.data[[req.target_col, c1, c2]].dropna()
    if len(df) < 6:
        return AnalysisResult(
            task="response_surface", status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    try:
        X1, X2 = df[c1].values, df[c2].values
        y = df[req.target_col].values
        X = np.column_stack([np.ones(len(df)), X1, X2, X1**2, X2**2, X1*X2])

        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return AnalysisResult(
            task="response_surface", status="error",
            messages=["响应面模型未能求解"],
        )

    xi = np.linspace(X1.min(), X1.max(), 30)
    yi = np.linspace(X2.min(), X2.max(), 30)
    XI, YI = np.meshgrid(xi, yi)
    ZI = (
        beta[0]
        + beta[1] * XI
        + beta[2] * YI
        + beta[3] * XI**2
        + beta[4] * YI**2
        + beta[5] * XI * YI
    )

    fig = Figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot_surface(XI, YI, ZI, cmap="viridis", alpha=0.8)
    ax.scatter(X1, X2, y, color="red", s=30)
    ax.set_xlabel(c1)
    ax.set_ylabel(c2)
    ax.set_zlabel(req.target_col)

    direction = req.params.get("direction", "maximize")
    opt_idx = np.unravel_index(
        np.argmax(ZI) if "min" not in direction else np.argmin(ZI), ZI.shape
    )

    return AnalysisResult(
        task="response_surface",
        tables={
            "coefficients": pd.DataFrame({
                "项": ["截距", c1, c2, f"{c1}²", f"{c2}²", f"{c1}×{c2}"],
                "系数": beta,
            })
        },
        figures=[fig],
        summary=f"响应面分析完成，最优区域: {c1}={XI[opt_idx]:.1f}, {c2}={YI[opt_idx]:.1f}",
        metadata={
            "optimal_x1": float(XI[opt_idx]),
            "optimal_x2": float(YI[opt_idx]),
            "optimal_z": float(ZI[opt_idx]),
        },
    )


def grid_search(req: AnalysisRequest) -> AnalysisResult:
    """网格搜索最优参数。"""
    ranges = req.params.get("ranges", {})
    if not ranges:
        return AnalysisResult(
            task="grid_search", status="error",
            messages=["需要提供参数搜索范围 (ranges)"],
        )

    n_points = req.params.get("n_points", 10)
    direction = req.params.get("direction", "maximize")

    grids = {col: np.linspace(lo, hi, n_points) for col, (lo, hi) in ranges.items()}
    mesh = np.meshgrid(*grids.values(), indexing="ij")
    points = np.column_stack([g.ravel() for g in mesh])
    col_names = list(ranges.keys())

    df = req.data[col_names + [req.target_col]].dropna()
    if len(df) < 5:
        return AnalysisResult(
            task="grid_search", status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    try:
        model = Ridge(alpha=1.0).fit(df[col_names].values, df[req.target_col].values)
        predictions = model.predict(points)

        best_idx = (
            np.argmax(predictions)
            if direction == "maximize"
            else np.argmin(predictions)
        )
        best = {
            col_names[i]: round(float(points[best_idx, i]), 3)
            for i in range(len(col_names))
        }

        return AnalysisResult(
            task="grid_search",
            summary=f"最优参数: {best}, 预测值: {predictions[best_idx]:.4f}",
            metadata={
                "optimal_params": best,
                "optimal_value": float(predictions[best_idx]),
            },
        )
    except Exception as e:
        return AnalysisResult(task="grid_search", status="error",
                              messages=["网格搜索失败，请检查参数范围和样本量是否合理"])


def multi_objective_opt(req: AnalysisRequest) -> AnalysisResult:
    """多目标优化 — 加权期望函数法。"""
    objectives = req.params.get("objectives", [])
    if not objectives:
        return AnalysisResult(
            task="multi_objective", status="error",
            messages=["需要提供优化目标 (objectives)"],
        )

    weights = req.params.get("weights", [1.0] * len(objectives))
    weights = np.array(weights) / np.sum(weights)


    # 构建所有优化目标列的共同有效数据掩码
    obj_cols = [obj["col"] for obj in objectives]
    valid_mask = req.data[obj_cols].notna().all(axis=1)
    if valid_mask.sum() == 0:
        return AnalysisResult(
            task="multi_objective", status="error",
            messages=["所有目标列均包含缺失值"],
        )

    scores = np.zeros(len(req.data))
    valid_rows = valid_mask  # 布尔索引
    for obj, w in zip(objectives, weights):
        col = obj["col"]
        vals = req.data.loc[valid_rows, col].values
        if len(vals) < 2:
            return AnalysisResult(
                task="multi_objective", status="error",
                messages=[f"列「{col}」有效数据不足"],
            )
        direction = obj.get("direction", "maximize")
        if direction == "maximize":
            desirability = (vals - vals.min()) / (vals.max() - vals.min() + 1e-10)
        else:
            desirability = (vals.max() - vals) / (vals.max() - vals.min() + 1e-10)
        scores[valid_rows] += w * desirability

    valid_idx = req.data.index[valid_rows]
    best_pos = np.argmax(scores[valid_rows])
    best_idx = valid_idx[best_pos]
    best_params = {
        c: req.data.loc[best_idx, c]
        for c in req.feature_cols
        if c in req.data.columns
    }

    return AnalysisResult(
        task="multi_objective",
        summary=f"综合评分最优: {best_params}, 得分: {scores[best_idx]:.4f}",
        metadata={
            "optimal_params": best_params,
            "composite_score": float(scores[best_idx]),
        },
    )


def doe_analysis(req: AnalysisRequest) -> AnalysisResult:
    """DOE 主效应分析。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="doe_analysis", status="error",
            messages=["需要至少 1 个因子"],
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 3:
        return AnalysisResult(
            task="doe_analysis", status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    effects = []
    grand_mean = df[req.target_col].mean()
    for col in cols:
        median = df[col].median()
        hi = df[df[col] > median][req.target_col].mean()
        lo = df[df[col] <= median][req.target_col].mean()
        effect = hi - lo
        effects.append({
            "因子": col,
            "主效应": effect,
            "效应占比": abs(effect) / (abs(grand_mean) + 1e-10),
        })

    effects_df = pd.DataFrame(effects).sort_values("主效应", key=abs, ascending=False)
    top_name = effects_df["因子"].iloc[0] if len(effects_df) > 0 else "N/A"
    top_val = effects_df["主效应"].iloc[0] if len(effects_df) > 0 else 0

    return AnalysisResult(
        task="doe_analysis",
        tables={"effect_estimates": effects_df},
        summary=f"最强主效应: {top_name} (效应={top_val:.3f})",
        metadata={"grand_mean": grand_mean, "top_effect_factor": top_name},
    )
