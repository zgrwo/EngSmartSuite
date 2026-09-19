"""响应面分析（response_surface_analysis）。"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)


def response_surface_analysis(req: AnalysisRequest) -> AnalysisResult:
    """响应面分析 — 二次模型 + 3D 曲面 + 2D 等高线图，含模型评估。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(
            task="response_surface",
            status="error",
            messages=["响应面分析需要至少 2 个因子"],
        )

    c1, c2 = cols[0], cols[1]
    rsm_warn_msgs: list[str] = []
    if len(cols) > 2:
        rsm_warn_msgs.append(
            f"⚠ 响应面仅使用前 2 个因子 ({c1}, {c2})，"
            f"忽略其余 {len(cols) - 2} 个因子: {cols[2:]}。"
            "如需要，请手动选择 2 个关键因子。"
        )
    df = req.data[[req.target_col, c1, c2]].dropna()
    if len(df) < 7:
        return AnalysisResult(
            task="response_surface",
            status="error",
            messages=[
                f"有效样本不足：二次响应面模型含 6 个参数，至少需要 7 个数据点"
                f"（当前 {len(df)} 个，残差自由度为 0 会导致标准误为 NaN）"
            ],
        )

    # 审查 2026-08-19 #1.4：常量目标列 → R²=-inf 且误报诊断
    if df[req.target_col].nunique(dropna=True) <= 1:
        return AnalysisResult(
            task="response_surface",
            status="error",
            messages=[f"目标列「{req.target_col}」为常量列（方差为 0），响应面模型无意义"],
        )

    try:
        X1, X2 = df[c1].values, df[c2].values
        y = df[req.target_col].values

        # 构建设计矩阵 (使用 DataFrame 以便 OLS 输出含命名列)
        X_design_df = pd.DataFrame(
            {
                "const": np.ones(len(df)),
                c1: X1,
                c2: X2,
                f"{c1}²": X1**2,
                f"{c2}²": X2**2,
                f"{c1}×{c2}": X1 * X2,
            }
        )
        term_names = list(X_design_df.columns)

        # 使用 OLS 而非 lstsq，以获取 R²/p值/标准误
        model_rsm = sm.OLS(y, X_design_df).fit()
        beta = np.asarray(model_rsm.params)
        r2 = float(model_rsm.rsquared)
        r2_adj = float(model_rsm.rsquared_adj)
    except Exception:
        logger.debug("响应面模型未能求解", exc_info=True)
        return AnalysisResult(
            task="response_surface",
            status="error",
            messages=["响应面模型未能求解"],
        )

    # ── 生成响应面网格 ──
    n_grid = 40
    xi = np.linspace(X1.min(), X1.max(), n_grid)
    yi = np.linspace(X2.min(), X2.max(), n_grid)
    XI, YI = np.meshgrid(xi, yi)
    ZI = (
        beta[0]
        + beta[1] * XI
        + beta[2] * YI
        + beta[3] * XI**2
        + beta[4] * YI**2
        + beta[5] * XI * YI
    )

    # ── 最优点查找 ──
    direction = req.params.get("direction", "maximize")
    # 审查 2026-08-19 #2.6：direction 白名单校验（拼写错误静默反转方向）
    if direction not in ("maximize", "minimize"):
        return AnalysisResult(
            task="response_surface",
            status="error",
            messages=[f"方向参数 direction 无效: {direction!r}，请使用 'maximize' 或 'minimize'"],
        )
    # colormap 方向适配: maximize→绿高红低, minimize→红低绿高(RdYlGn反转)
    _rsm_cmap = "RdYlGn" if direction == "maximize" else "RdYlGn_r"
    if direction == "minimize":
        opt_idx = np.unravel_index(np.argmin(ZI), ZI.shape)
    else:  # default "maximize"
        opt_idx = np.unravel_index(np.argmax(ZI), ZI.shape)
    opt_x1 = float(XI[opt_idx])
    opt_x2 = float(YI[opt_idx])
    opt_z = float(ZI[opt_idx])

    # ── 系数表含显著性 ──
    coef_df = pd.DataFrame(
        {
            "项": term_names,
            "系数": beta,
            "标准误": np.asarray(model_rsm.bse),
            "t值": np.asarray(model_rsm.tvalues),
            "p值": np.asarray(model_rsm.pvalues),
        }
    )

    # ── 双图：3D 曲面 (左) + 2D 等高线 (右) ──
    # 检查 mplot3d 可用性（极简 matplotlib 安装可能不包含）
    try:
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

        _has_3d = True
    except ImportError:
        _has_3d = False

    fig = Figure(figsize=(14 if _has_3d else 7, 5.5))

    # 左: 3D 曲面
    if _has_3d:
        ax_3d = fig.add_subplot(1, 2, 1, projection="3d")
        ax_3d.plot_surface(XI, YI, ZI, cmap=_rsm_cmap, alpha=0.85, linewidth=0, antialiased=True)
        ax_3d.view_init(elev=22, azim=-62)
        ax_3d.scatter(
            X1, X2, y, color=PALETTE["data"]["primary"], s=25, alpha=0.7, label="观测数据"
        )
        # 标注最优点
        ax_3d.scatter(
            [opt_x1],
            [opt_x2],
            [opt_z],
            color=PALETTE["anomaly"]["primary"],
            s=120,
            marker="*",
            edgecolors="white",
            linewidths=1.5,
            label=f"最优 ({opt_x1:.2f}, {opt_x2:.2f})",
        )
        ax_3d.set_xlabel(c1, fontsize=9)
        ax_3d.set_ylabel(c2, fontsize=9)
        ax_3d.set_zlabel(req.target_col, fontsize=9)
        ax_3d.set_title(f"3D 响应面 — {req.target_col}\n(R²={r2:.3f})", fontsize=10)
        ax_3d.legend(fontsize=7.5, loc="upper left")
        # 色条只在 2D 面板保留一份，避免重复占位与 3D 面板拥挤

    # 右 (或全幅): 2D 填充等高线
    ax_contour = fig.add_subplot(1, 2 if _has_3d else 1, 2 if _has_3d else 1)
    levels = 20
    cf = ax_contour.contourf(XI, YI, ZI, levels=levels, cmap=_rsm_cmap, alpha=0.9)
    cs = ax_contour.contour(XI, YI, ZI, levels=8, colors="black", linewidths=0.5, alpha=0.3)
    ax_contour.clabel(cs, inline=True, fontsize=7.5, fmt="%.2f")
    ax_contour.scatter(X1, X2, color=PALETTE["data"]["primary"], s=20, alpha=0.6, label="观测数据")
    ax_contour.scatter(
        [opt_x1],
        [opt_x2],
        color=PALETTE["anomaly"]["primary"],
        s=150,
        marker="*",
        edgecolors="white",
        linewidths=2,
        label=f"最优 ({opt_x1:.2f}, {opt_x2:.2f}, z={opt_z:.3f})",
    )
    ax_contour.set_xlabel(c1, fontsize=10)
    ax_contour.set_ylabel(c2, fontsize=10)
    ax_contour.set_title(f"2D 等高线 — {req.target_col}", fontsize=10)
    ax_contour.legend(fontsize=8, loc="upper right")
    fig.colorbar(cf, ax=ax_contour, shrink=0.8, label=req.target_col)

    fig.tight_layout()

    # ── 汇总 ──
    summary = (
        f"响应面 R²={r2:.3f}, 调整R²={r2_adj:.3f}。"
        f"最优区域: {c1}={opt_x1:.2f}, {c2}={opt_x2:.2f}, "
        f"预测{req.target_col}={opt_z:.4f}"
    )

    return AnalysisResult(
        task="response_surface",
        messages=rsm_warn_msgs,
        tables={
            "coefficients": coef_df,
            "model_fit": pd.DataFrame(
                {
                    "指标": ["R²", "调整R²", "样本量", "最优X1", "最优X2", "最优预测值"],
                    "值": [
                        f"{r2:.4f}",
                        f"{r2_adj:.4f}",
                        str(len(df)),
                        f"{opt_x1:.4f}",
                        f"{opt_x2:.4f}",
                        f"{opt_z:.4f}",
                    ],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "r_squared": r2,
            "r_squared_adj": r2_adj,
            "optimal_x1": opt_x1,
            "optimal_x2": opt_x2,
            "optimal_z": opt_z,
            "direction": direction,
        },
    )
