import logging
from itertools import combinations, product

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import DW_NEGATIVE_AUTOCORR, DW_POSITIVE_AUTOCORR, EPSILON
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    durbin_watson,
    safe_float as _safe_float,
    threshold_label,
)  # 共享工具函数

logger = logging.getLogger(__name__)


# 阳性标签候选列表 — roc_analysis 和 logistic_regression 共享 (P2-12 fix)
_POSITIVE_LABELS = ["不合格", "是", "1", 1, True, "fail", "异常"]


def _detect_positive_label(unique_values: list) -> object:
    """从候选列表中自动识别二分类的阳性标签。

    按 _POSITIVE_LABELS 顺序匹配，若都不存在则取排序后的最后一个值。
    """
    for pos_label in _POSITIVE_LABELS:
        if pos_label in unique_values:
            return pos_label
    return sorted(unique_values)[-1]


def _std_beta(model, X):
    """计算标准化回归系数 (Beta 权重)，用于比较不同量纲变量的重要性。"""
    y_std = np.std(model.model.endog)
    if y_std < EPSILON:
        return [0.0] * len(X.columns)
    beta = []
    for i, col in enumerate(X.columns):
        if col == "const":
            beta.append(0.0)
        else:
            param_val = model.params[col]
            x_std = np.std(X[col])
            if np.isnan(param_val) or x_std < EPSILON:
                beta.append(0.0)
            else:
                beta.append(float(param_val * x_std / y_std))
    return beta


def _breusch_pagan(model, X):
    """Breusch-Pagan 异方差检验。返回 (LM统计量, p值)。"""
    residuals = model.resid
    resid_sq = residuals**2
    resid_sq_mean = np.mean(resid_sq)
    n = len(residuals)
    # 回归残差平方对自变量
    try:
        aux_model = sm.OLS(resid_sq, X).fit()
        ess = np.sum((aux_model.fittedvalues - resid_sq_mean) ** 2)
        rss = np.sum((resid_sq - aux_model.fittedvalues) ** 2)
        # 审查 2026-08-19：#完美拟合时 ess=rss=0 → LM=0/0=NaN，返回 None 由调用方显示 N/A
        if ess + rss <= 1e-12:
            return None, None
        lm = n * ess / (ess + rss)
        k = X.shape[1] - 1
        p_val = float(sp_stats.chi2.sf(lm, max(k, 1)))
        return float(lm), p_val
    except (ValueError, np.linalg.LinAlgError):
        logger.debug("Breusch-Pagan 异方差检验失败（数据异常或矩阵奇异）", exc_info=True)
        return None, None


def regression_analysis(req: AnalysisRequest) -> AnalysisResult:
    """线性回归建模 (OLS)，含标准化系数、Durbin-Watson、Breusch-Pagan 和 Cook's D。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="regression",
            status="error",
            messages=["需要至少 1 个因子列"],
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < len(cols) + 2:
        return AnalysisResult(
            task="regression",
            status="error",
            messages=[f"有效样本量({len(df)})不足，需要至少{len(cols) + 2}条"],
        )

    # Round-2 #A2a：常量特征列 → 系数 t=inf/NaN 且 inf 进入 Web JSON 链
    _const_feats = [c for c in cols if df[c].nunique(dropna=True) <= 1]
    if _const_feats:
        return AnalysisResult(
            task="regression",
            status="error",
            messages=[
                f"特征列「{_const_feats[0]}」为常量列（无变异），无法估计回归系数。"
                "请移除该列或检查数据。"
            ],
        )

    # 审查 2026-08-19 #1.4：常量目标列 → R²=0/0=-inf 且误报异方差/自相关诊断
    # Round-2 #A2l：用 nunique 替代绝对阈值（微尺度数据不误报）
    if df[req.target_col].nunique(dropna=True) <= 1:
        return AnalysisResult(
            task="regression",
            status="error",
            messages=[f"目标列「{req.target_col}」为常量列（方差为 0），回归模型无意义"],
        )

    try:
        X = sm.add_constant(df[cols])
        y = df[req.target_col]
        model = sm.OLS(y, X).fit()
        # 审查 2026-08-19 #1.4：输出守卫——R² 非有限时替换为哨兵 N/A
        if not np.isfinite(model.rsquared):
            return AnalysisResult(
                task="regression",
                status="error",
                messages=["R² 计算为非有限值（数据可能为常量或退化），回归结果不可用"],
            )
        residuals = model.resid
        fitted = model.fittedvalues
        n = len(y)
        k = len(cols)

        # 标准化系数
        std_betas = _std_beta(model, X)

        coef_df = pd.DataFrame(
            {
                "变量": X.columns,
                "系数": np.asarray(model.params),
                "标准误": np.asarray(model.bse),
                "t值": np.asarray(model.tvalues),
                "p值": np.asarray(model.pvalues),
                "标准化系数(β)": std_betas,
            }
        )

        # 警告消息列表（在整个诊断段之前初始化，供后续各节追加）
        warn_msgs: list[str] = []

        # ── 模型诊断 ──
        # Durbin-Watson
        dw = durbin_watson(residuals)

        # Breusch-Pagan 异方差检验
        bp_lm, bp_p = _breusch_pagan(model, X)

        # Cook's Distance — 隔离 try/except: 即使 Cook's D 失败也不丢弃已算出的系数和诊断
        cooks_d = None
        influence = None
        try:
            influence = model.get_influence()
            cooks_d = influence.cooks_distance[0]
        except Exception as e:
            # 审查 2026-09-01 C-9：记录完整堆栈便于定位（Cook's D 隔离 try）
            logger.warning("Cook's D 计算失败 (矩阵可能接近奇异): %s", e, exc_info=True)
            warn_msgs.append(
                "⚠ Cook's Distance 无法计算（数据可能存在严重共线性），"
                "回归系数仍然有效但影响点诊断已跳过"
            )

        # ── 诊断表 ──
        diagnostics_rows = [
            {"指标": "R²", "值": f"{model.rsquared:.4f}", "说明": "模型解释的变异比例"},
            {"指标": "调整R²", "值": f"{model.rsquared_adj:.4f}", "说明": "惩罚变量数后的拟合优度"},
            {
                "指标": "F 统计量",
                "值": f"{model.fvalue:.4f}" if np.isfinite(model.fvalue) else "N/A (退化模型)",
                "说明": f"p={model.f_pvalue:.4f}" if np.isfinite(model.f_pvalue) else "N/A",
            },
            {
                "指标": "Durbin-Watson",
                "值": f"{dw:.4f}",
                "说明": "接近2=无自相关, <1=正自相关, >3=负自相关",
            },
            {
                "指标": "Breusch-Pagan",
                "值": f"LM={bp_lm:.4f}, p={bp_p:.4f}"
                if (bp_lm is not None and bp_p is not None)
                else "N/A",
                "说明": "p<0.05=存在异方差",
            },
            {"指标": "AIC", "值": f"{model.aic:.1f}", "说明": "越小越好(模型比较用)"},
            {"指标": "BIC", "值": f"{model.bic:.1f}", "说明": "越小越好(惩罚更重)"},
        ]
        diagnostics_df = pd.DataFrame(diagnostics_rows)

        sig_vars = coef_df[(coef_df["p值"] < 0.05) & (coef_df["变量"] != "const")]

        # 异方差警告（p<0.05 表示拒绝同方差，即存在异方差 == 有问题）
        if bp_p is not None and bp_p < 0.05:
            warn_msgs.append(
                f"⚠ Breusch-Pagan 检验 p={bp_p:.4f}<0.05，残差存在异方差，系数标准误可能不准确"
            )
        if dw < DW_POSITIVE_AUTOCORR:
            warn_msgs.append(f"⚠ Durbin-Watson={dw:.3f}<{DW_POSITIVE_AUTOCORR}，残差存在正自相关")
        elif dw > DW_NEGATIVE_AUTOCORR:
            warn_msgs.append(f"⚠ Durbin-Watson={dw:.3f}>{DW_NEGATIVE_AUTOCORR}，残差存在负自相关")

        # ── 增强诊断图 (3×2) ──
        fig_res = Figure(figsize=(12, 8))

        # 1. Residual vs Fitted
        ax1 = fig_res.add_subplot(2, 3, 1)
        ax1.scatter(fitted, residuals, alpha=0.6, s=20, color=PALETTE["data"]["primary"])
        ax1.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
        ax1.set_xlabel("拟合值", fontsize=9)
        ax1.set_ylabel("残差", fontsize=9)
        ax1.set_title("Residual vs Fitted", fontsize=10)

        # 2. Q-Q Plot
        ax2 = fig_res.add_subplot(2, 3, 2)
        sp_stats.probplot(residuals, dist="norm", plot=ax2)
        ax2.set_title("Q-Q Plot", fontsize=10)

        # 3. Scale-Location (sqrt|resid| vs fitted)
        ax3 = fig_res.add_subplot(2, 3, 3)
        sqrt_abs_resid = np.sqrt(np.abs(residuals))
        ax3.scatter(fitted, sqrt_abs_resid, alpha=0.6, s=20, color=PALETTE["data"]["primary"])
        ax3.set_xlabel("拟合值", fontsize=9)
        ax3.set_ylabel("√|残差|", fontsize=9)
        ax3.set_title("Scale-Location", fontsize=10)

        # 4. Cook's Distance (若计算失败则显示提示文本)
        ax4 = fig_res.add_subplot(2, 3, 4)
        if cooks_d is not None and len(cooks_d) > 0:
            ax4.stem(
                range(n), cooks_d, linefmt=PALETTE["data"]["secondary"], markerfmt="o", basefmt=" "
            )
            threshold = 4 / n
            ax4.axhline(
                threshold,
                color=PALETTE["anomaly"]["primary"],
                linestyle="--",
                linewidth=1,
                label=f"4/n={threshold:.4f}",
            )
            ax4.set_xlabel("观测序号", fontsize=9)
            ax4.set_ylabel("Cook's D", fontsize=9)
            ax4.set_title("Cook's Distance (影响点诊断)", fontsize=10)
            ax4.legend(fontsize=7.5)
        else:
            ax4.text(
                0.5,
                0.5,
                "Cook's D 计算失败\n(数据可能共线性)",
                ha="center",
                va="center",
                transform=ax4.transAxes,
                fontsize=9,
                color=PALETTE["judge"]["warn"],
            )
            ax4.set_title("Cook's Distance (不可用)", fontsize=10)

        # 5. Residual vs Leverage
        ax5 = fig_res.add_subplot(2, 3, 5)
        if influence is not None:
            leverage = influence.hat_matrix_diag
            ax5.scatter(leverage, residuals, alpha=0.6, s=20, color=PALETTE["data"]["primary"])
            ax5.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
            ax5.set_xlabel("杠杆值", fontsize=9)
            ax5.set_ylabel("残差", fontsize=9)
            ax5.set_title("Residuals vs Leverage", fontsize=10)
        else:
            ax5.text(
                0.5,
                0.5,
                "杠杆值计算失败\n(数据可能共线性)",
                ha="center",
                va="center",
                transform=ax5.transAxes,
                fontsize=9,
                color=PALETTE["judge"]["warn"],
            )
            ax5.set_title("Residuals vs Leverage (不可用)", fontsize=10)

        # 6. Actual vs Predicted
        ax6 = fig_res.add_subplot(2, 3, 6)
        ax6.scatter(fitted, y, alpha=0.5, s=15, color=PALETTE["data"]["primary"])
        ax6.plot(
            [y.min(), y.max()],
            [y.min(), y.max()],
            color=PALETTE["anomaly"]["primary"],
            linestyle="--",
            linewidth=1,
            label="完美预测",
        )
        ax6.set_xlabel("预测值", fontsize=9)
        ax6.set_ylabel("实际值", fontsize=9)
        ax6.set_title(f"Actual vs Predicted (R²={model.rsquared:.3f})", fontsize=10)
        ax6.legend(fontsize=7.5)

        fig_res.tight_layout()

        # ── 汇总 ──
        summary_parts = [
            f"R²={model.rsquared:.4f}, 调整R²={model.rsquared_adj:.4f}",
            f"显著变量: {len(sig_vars)}/{k}",
        ]
        if len(sig_vars) > 0:
            top_beta_idx = np.argmax(
                np.abs([std_betas[list(X.columns).index(v)] for v in sig_vars["变量"]])
            )
            top_var = sig_vars.iloc[top_beta_idx]["变量"]
            summary_parts.append(f"最重要的变量: {top_var}")
        summary_parts.append(f"DW={dw:.3f}")
        if bp_p is not None and bp_p < 0.05:
            summary_parts.append("⚠ 存在异方差")
        summary = "；".join(summary_parts)

        return AnalysisResult(
            task="regression",
            tables={
                "coefficients": coef_df,
                "diagnostics": diagnostics_df,
            },
            figures=[fig_res],
            summary=summary,
            metadata={
                "r_squared": model.rsquared,
                "r_squared_adj": model.rsquared_adj,
                "f_statistic": float(model.fvalue) if np.isfinite(model.fvalue) else None,
                "f_pvalue": float(model.f_pvalue) if np.isfinite(model.f_pvalue) else None,
                "durbin_watson": dw,
                "breusch_pagan_lm": bp_lm,
                "breusch_pagan_p": bp_p,
                "aic": float(model.aic),
                "bic": float(model.bic),
                "significant_vars": sig_vars["变量"].tolist(),
                "std_betas": {col: beta for col, beta in zip(X.columns, std_betas)},
            },
            messages=warn_msgs,
        )
    except Exception:
        logger.debug("回归模型拟合失败", exc_info=True)
        return AnalysisResult(
            task="regression",
            status="error",
            messages=["回归模型拟合失败，请检查数据是否存在缺失值或共线性"],
        )


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
        surf = ax_3d.plot_surface(
            XI, YI, ZI, cmap=_rsm_cmap, alpha=0.85, linewidth=0, antialiased=True
        )
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
        fig.colorbar(surf, ax=ax_3d, shrink=0.5, label=req.target_col)

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


def grid_search(req: AnalysisRequest) -> AnalysisResult:
    """网格搜索最优参数。"""
    ranges = req.params.get("ranges", {})
    if not ranges:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=["需要提供参数搜索范围 (ranges)"],
        )

    # ── ranges 格式校验 (P2 fix: 防止非 tuple 输入导致解包失败) ──
    _invalid_ranges = []
    for _col, _r in ranges.items():
        if not isinstance(_r, (tuple, list)) or len(_r) != 2:
            _invalid_ranges.append(f"「{_col}」应为 (下限, 上限) 格式")
        elif not all(isinstance(v, (int, float)) for v in _r):
            _invalid_ranges.append(f"「{_col}」的上下限必须为数值")
        elif _r[0] >= _r[1]:
            _invalid_ranges.append(f"「{_col}」下限 ({_r[0]}) 必须小于上限 ({_r[1]})")
    if _invalid_ranges:
        return AnalysisResult(
            task="grid_search", status="error", messages=["参数搜索范围格式无效:"] + _invalid_ranges
        )

    n_points = req.params.get("n_points", 10)
    try:
        n_points = int(n_points)
    except (ValueError, TypeError):
        n_points = 10
    # 防止内存耗尽：限制搜索点数
    n_points = max(2, min(n_points, 30))
    if len(ranges) > 4:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[f"搜索参数维度({len(ranges)})过高，最多支持 4 个参数"],
        )
    total_points = n_points ** len(ranges)
    if total_points > 50000:
        n_points = max(2, int(50000 ** (1.0 / len(ranges))))
    direction = req.params.get("direction", "maximize")
    # 审查 2026-08-19 #2.6：direction 白名单校验
    if direction not in ("maximize", "minimize"):
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[f"方向参数 direction 无效: {direction!r}，请使用 'maximize' 或 'minimize'"],
        )
    _gs_cmap = "RdYlGn" if direction == "maximize" else "RdYlGn_r"

    # 审查 2026-08-19 #2.1：isinstance 校验对 NaN 恒真、NaN>=NaN 恒假，
    # [NaN, NaN] 能穿透校验并产生全 NaN 网格 → 显式 isfinite 兜底
    _nan_bounds = [c for c, (lo, hi) in ranges.items() if not (np.isfinite(lo) and np.isfinite(hi))]
    if _nan_bounds:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[
                f"搜索范围包含无效数值 (NaN/Inf): {_nan_bounds}，"
                "请检查 ranges 格式，正确格式如 料温:180,220"
            ],
        )

    grids = {col: np.linspace(lo, hi, n_points) for col, (lo, hi) in ranges.items()}
    mesh = np.meshgrid(*grids.values(), indexing="ij")
    points = np.column_stack([g.ravel() for g in mesh])
    col_names = list(ranges.keys())
    missing_cols = [c for c in col_names if c not in req.data.columns]
    if missing_cols:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[f"搜索参数列不存在于数据中: {missing_cols}"],
        )

    # Round-2 #A4：ranges 键可能 == 目标列 → 重复列名；去重后再取目标列
    df = req.data[list(dict.fromkeys(col_names + [req.target_col]))].dropna()
    if len(df) < 5:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    # 审查 2026-08-19 #2.6：常量目标列时 CV R² 恒为 1.000、最优参数无意义
    _target_series = df[req.target_col]
    if _target_series.nunique(dropna=True) <= 1:
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=[f"目标列「{req.target_col}」为常量列，网格搜索最优参数无意义"],
        )

    try:
        from sklearn.linear_model import RidgeCV
        from sklearn.model_selection import cross_val_score

        X_train = df[col_names].values
        y_train = df[req.target_col].values

        # 使用 RidgeCV 自动选择最优 alpha
        alphas = [0.01, 0.1, 1.0, 10.0, 100.0]
        ridge_cv = RidgeCV(alphas=alphas)
        ridge_cv.fit(X_train, y_train)
        best_alpha = float(ridge_cv.alpha_)

        # 交叉验证 R²
        cv_r2 = float(
            cross_val_score(
                ridge_cv, X_train, y_train, cv=max(2, min(5, len(df) // 3)), scoring="r2"
            ).mean()
        )

        predictions = ridge_cv.predict(points)

        best_idx = np.argmax(predictions) if direction == "maximize" else np.argmin(predictions)
        pred_best = float(predictions[best_idx])
        best = {col_names[i]: round(float(points[best_idx, i]), 3) for i in range(len(col_names))}

        # Top-N 候选
        top_n = min(5, len(predictions))
        if direction == "maximize":
            top_indices = np.argsort(predictions)[-top_n:][::-1]
        else:
            top_indices = np.argsort(predictions)[:top_n]
        top_candidates = [
            {col_names[i]: round(float(points[idx, i]), 3) for i in range(len(col_names))}
            | {"预测值": round(float(predictions[idx]), 4)}
            for idx in top_indices
        ]

        # 可视化：2D 等高线 / 1D 折线
        fig = Figure(figsize=(7, 4.5))
        if len(col_names) == 2:
            ax = fig.add_subplot(111)
            Z = predictions.reshape(n_points, n_points)
            X, Y = mesh
            cs = ax.contourf(X, Y, Z, levels=15, cmap=_gs_cmap)
            ax.scatter(
                X_train[:, 0],
                X_train[:, 1],
                alpha=0.4,
                s=12,
                color=PALETTE["data"]["primary"],
                label="训练数据",
            )
            ax.scatter(
                points[best_idx, 0],
                points[best_idx, 1],
                marker="*",
                color=PALETTE["target"]["primary"],
                s=180,
                edgecolors="white",
                linewidths=1.5,
                zorder=5,
                label=f"最优 ({best[col_names[0]]}, {best[col_names[1]]})",
            )
            ax.set_xlabel(col_names[0], fontsize=10)
            ax.set_ylabel(col_names[1], fontsize=10)
            ax.set_title(
                f"网格搜索 — {req.target_col} | CV R²={cv_r2:.3f}, α={best_alpha:.3f}",
                fontsize=10,
            )
            ax.legend(fontsize=8)
            fig.colorbar(cs, ax=ax, label="预测值", shrink=0.8)
        else:
            ax = fig.add_subplot(111)
            ax.bar(range(len(predictions)), predictions, color=PALETTE["data"]["secondary"])
            ax.set_xlabel("参数组合索引", fontsize=10)
            ax.set_ylabel("预测值", fontsize=10)
            ax.set_title(f"网格搜索 — {req.target_col}", fontsize=11)
        fig.tight_layout()

        return AnalysisResult(
            task="grid_search",
            tables={
                "top_candidates": pd.DataFrame(top_candidates),
            },
            figures=[fig],
            summary=(
                f"最优参数: {best}, 预测值: {pred_best:.4f}。"
                f"CV R²={cv_r2:.3f}, 最优 α={best_alpha:.3f}"
            ),
            metadata={
                "optimal_params": best,
                "optimal_value": pred_best,
                "cv_r2": cv_r2,
                "best_alpha": best_alpha,
                "top_candidates": top_candidates,
            },
        )
    except Exception:
        logger.debug("网格搜索失败", exc_info=True)
        return AnalysisResult(
            task="grid_search",
            status="error",
            messages=["网格搜索失败，请检查参数范围和样本量是否合理"],
        )


def _desirability(vals, direction):
    """计算期望值（0-1 归一化）。"""
    vmin, vmax = vals.min(), vals.max()
    rng = vmax - vmin + EPSILON
    if direction == "maximize":
        return (vals - vmin) / rng
    elif direction == "minimize":
        return (vmax - vals) / rng
    else:
        raise ValueError(f"不支持的优化方向「{direction}」，请使用 'maximize' 或 'minimize'")


def multi_objective_opt(req: AnalysisRequest) -> AnalysisResult:
    """多目标优化 — 加权期望函数法。"""
    objectives = req.params.get("objectives", [])
    if not objectives:
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=["需要提供优化目标 (objectives)"],
        )
    # 校验每个 objective 必须是包含 "col" 键的字典（审查 2026-08-19 #2.6）
    for i, obj in enumerate(objectives):
        if not isinstance(obj, dict) or "col" not in obj:
            return AnalysisResult(
                task="multi_objective",
                status="error",
                messages=[f"第 {i + 1} 个优化目标格式无效，需为含 'col' 字段的字典: {obj!r}"],
            )

    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P3 fix)
    weights = req.params.get("weights")
    if weights is None:
        weights = [1.0] * len(objectives)
    if len(weights) != len(objectives):
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=[f"权重数量({len(weights)})与目标数量({len(objectives)})不匹配"],
        )
    if len(weights) == 0:
        return AnalysisResult(task="multi_objective", status="error", messages=["权重列表不能为空"])
    # 审查 2026-08-19 #2.6：权重元素需数值化（字符串权重 → np.sum TypeError）
    try:
        weights = [float(w) for w in weights]
    except (ValueError, TypeError):
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=["权重列表必须全部为数值"],
        )
    weight_sum = np.sum(weights)
    if weight_sum <= 0:
        return AnalysisResult(
            task="multi_objective", status="error", messages=["权重之和必须大于零"]
        )
    weights = np.array(weights) / weight_sum

    # 构建所有优化目标列的共同有效数据掩码
    obj_cols = [obj["col"] for obj in objectives]
    # 校验列存在性
    missing_cols = [c for c in obj_cols if c not in req.data.columns]
    if missing_cols:
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=[f"优化目标列不存在于数据中: {', '.join(missing_cols)}"],
        )
    valid_mask = req.data[obj_cols].notna().all(axis=1)
    if valid_mask.sum() == 0:
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=["所有目标列均包含缺失值"],
        )

    scores = np.zeros(len(req.data))
    valid_rows = valid_mask  # 布尔索引
    for obj, w in zip(objectives, weights):
        col = obj["col"]
        vals = req.data.loc[valid_rows, col].values
        if len(vals) < 2:
            return AnalysisResult(
                task="multi_objective",
                status="error",
                messages=[f"列「{col}」有效数据不足"],
            )
        direction = obj.get("direction", "maximize")
        if direction not in ("maximize", "minimize"):
            return AnalysisResult(
                task="multi_objective",
                status="error",
                messages=[
                    f"目标列「{col}」的优化方向「{direction}」无效，请使用 'maximize' 或 'minimize'"
                ],
            )
        desirability = _desirability(vals, direction)
        scores[valid_rows] += w * desirability

    best_pos = np.argmax(scores[valid_rows])
    # Round-2 #A1：重复索引时经标签中转会取到'标签首现'位置——若首现行被 NaN
    # 排除（valid_mask=False），会静默返回被排除行。直接取有效行的位置索引。
    best_row_iloc = int(np.flatnonzero(valid_mask)[best_pos])
    best_params = {
        c: req.data.iloc[best_row_iloc][c] for c in req.feature_cols if c in req.data.columns
    }

    # ── 各目标单独期望值表 ──
    desirability_rows = []
    for obj in objectives:
        col = obj["col"]
        direction = obj.get("direction", "maximize")
        vals = req.data.loc[valid_rows, col].values
        d_i = _desirability(vals, direction)
        best_d = float(d_i[best_pos])
        desirability_rows.append(
            {
                "目标列": col,
                "方向": "最大化" if direction == "maximize" else "最小化",
                "权重": round(float(weights[objectives.index(obj)]), 3),
                "最优期望值": round(best_d, 4),
                "均值期望值": round(float(np.mean(d_i)), 4),
            }
        )
    desirability_df = pd.DataFrame(desirability_rows)

    # ── 增强图表 ──
    score_valid = scores[valid_rows]
    fig = Figure(figsize=(12, 5))
    pareto_idx: list = []

    # 左图: 如果恰好 2 个目标 → Pareto 前沿
    if len(objectives) == 2:
        ax_pareto = fig.add_subplot(1, 2, 1)
        vals0 = req.data.loc[valid_rows, objectives[0]["col"]].values
        vals1 = req.data.loc[valid_rows, objectives[1]["col"]].values
        # 转换为"越大越好"以展示 Pareto 前沿
        if objectives[0].get("direction", "maximize") == "minimize":
            vals0_plot = -vals0
            xlabel = f"{objectives[0]['col']} (反转)"
        else:
            vals0_plot = vals0
            xlabel = objectives[0]["col"]
        if objectives[1].get("direction", "maximize") == "minimize":
            vals1_plot = -vals1
            ylabel = f"{objectives[1]['col']} (反转)"
        else:
            vals1_plot = vals1
            ylabel = objectives[1]["col"]

        ax_pareto.scatter(
            vals0_plot,
            vals1_plot,
            c=score_valid,
            cmap="RdYlGn",
            alpha=0.6,
            s=30,
            edgecolors=PALETTE["spec"]["tertiary"],
            linewidths=0.3,
        )

        # Pareto 前沿：O(n log n) 排序法（按 x 降序，跟踪 y 最大值）
        points = np.column_stack([vals0_plot, vals1_plot])
        order = np.lexsort((-points[:, 0],))  # 按第0列降序
        sorted_pts = points[order]
        pareto_mask = np.ones(len(sorted_pts), dtype=bool)
        max_y = -np.inf
        for i in range(len(sorted_pts)):
            if sorted_pts[i, 1] <= max_y:
                pareto_mask[i] = False
            else:
                max_y = sorted_pts[i, 1]
        pareto_idx = order[pareto_mask]
        pareto_sorted = pareto_idx[np.argsort(points[pareto_idx, 0])]
        ax_pareto.plot(
            points[pareto_sorted, 0],
            points[pareto_sorted, 1],
            color=PALETTE["anomaly"]["primary"],
            linestyle="-",
            linewidth=2,
            alpha=0.7,
            label=f"Pareto 前沿 ({len(pareto_sorted)}点)",
        )
        # 标记最优
        best_pos_in_valid = best_pos
        ax_pareto.scatter(
            [vals0_plot[best_pos_in_valid]],
            [vals1_plot[best_pos_in_valid]],
            s=150,
            marker="*",
            color=PALETTE["anomaly"]["primary"],
            edgecolors="white",
            linewidths=1.5,
            zorder=5,
            label="加权最优",
        )
        ax_pareto.set_xlabel(xlabel, fontsize=9)
        ax_pareto.set_ylabel(ylabel, fontsize=9)
        ax_pareto.set_title("Pareto 前沿 — 双目标权衡", fontsize=10)
        ax_pareto.legend(fontsize=7.5)
        plt_label = "综合得分 (加权)"
        fig.colorbar(ax_pareto.collections[0], ax=ax_pareto, label=plt_label)

    # 右图: 得分分布 + 各目标期望值
    ax_score = fig.add_subplot(1, 2, 2) if len(objectives) == 2 else fig.add_subplot(111)
    top_n = min(20, len(score_valid))
    top_idx = np.argsort(score_valid)[-top_n:]
    # 显示各目标分解（PALETTE 对比色 + 数据色，支持 ≥5 目标）
    bar_colors = [
        PALETTE["data"]["primary"],  # 深蓝
        PALETTE["target"]["primary"],  # 深橙
        PALETTE["center"]["primary"],  # 绿色
        PALETTE["contrast"]["d"],  # 紫色
        PALETTE["contrast"]["a"],  # 浅蓝
        PALETTE["contrast"]["b"],  # 橙色
        PALETTE["data"]["secondary"],  # 浅蓝灰
        PALETTE["judge"]["warn"],  # 橙色警告
    ]
    bottom_vals = np.zeros(top_n)
    for oi, obj in enumerate(objectives):
        col = obj["col"]
        direction = obj.get("direction", "maximize")
        w = weights[oi]
        vals = req.data.loc[valid_rows, col].values
        d_i = _desirability(vals, direction)
        contrib = w * d_i[top_idx]
        ax_score.barh(
            range(top_n),
            contrib,
            left=bottom_vals,
            color=bar_colors[oi % len(bar_colors)],
            label=f"{col} (w={w:.3f})",
            height=0.7,
        )
        bottom_vals += contrib
    ax_score.invert_yaxis()
    ax_score.set_xlabel("加权期望值", fontsize=9)
    ax_score.set_ylabel("排名", fontsize=9)
    ax_score.set_title(f"多目标优化 — Top{top_n} 方案分解", fontsize=10)
    ax_score.legend(fontsize=7.5, loc="lower right")

    fig.tight_layout()

    return AnalysisResult(
        task="multi_objective",
        tables={
            "desirability_scores": desirability_df,
            "optimal_parameters": pd.DataFrame([best_params]),
        },
        figures=[fig],
        summary=(
            f"综合评分最优: {best_params}, 得分: {scores[best_row_iloc]:.4f}。"
            + (f"Pareto 前沿包含 {len(pareto_idx)} 个非支配解" if len(objectives) == 2 else "")
        ),
        metadata={
            "optimal_params": best_params,
            "composite_score": float(scores[best_row_iloc]),
            "pareto_count": int(len(pareto_idx)) if len(objectives) == 2 else None,
        },
    )


def _lenth_pse(effects):
    """Lenth 伪标准误 — 用于无重复 DOE 的效应显著性判断。"""
    abs_effects = np.sort(np.abs(effects))
    # 取中位数的一半作为初始 s0
    median_abs = np.median(abs_effects)
    s0 = 1.5 * median_abs
    # 剔除 > 2.5*s0 的效应后重新计算 PSE
    trimmed = abs_effects[abs_effects < 2.5 * s0]
    if len(trimmed) == 0:
        return max(s0, EPSILON)
    pse = 1.5 * np.median(trimmed)
    return max(pse, EPSILON)


# DOE 效应量阈值（η² 类逐步效应量, Richardson 2011）
_DOE_EFFECT_THRESHOLDS = [0.05, 0.15, 0.30]


def doe_analysis(req: AnalysisRequest) -> AnalysisResult:
    """DOE 主效应与交互效应分析，含显著性检验。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="doe_analysis",
            status="error",
            messages=["需要至少 1 个因子"],
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 3:
        return AnalysisResult(
            task="doe_analysis",
            status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    grand_mean = float(df[req.target_col].mean())
    grand_std = float(df[req.target_col].std(ddof=1))

    # ── 回归法估计效应（编码变量 -1/+1，比中位数分割更准确）──
    effects = []
    coded_map: dict[str, np.ndarray] = {}  # 编码列缓存（供交互效应复用）
    y = df[req.target_col].values
    for col in cols:
        col_vals = df[col]
        unique_vals = col_vals.unique()
        if len(unique_vals) <= 1:
            effects.append(
                {
                    "因子": col,
                    "主效应": 0.0,
                    "效应占比": 0.0,
                    "t值": 0.0,
                    "p值": 1.0,
                    "显著": "否",
                    "效应量": "可忽略",
                }
            )
            continue

        if len(unique_vals) == 2:
            # 二水平因子：直接编码 -1/+1（效应 = 全范围差异）
            s = sorted(unique_vals)
            _lo, hi = s[0], s[-1]
            coded = np.where(col_vals == hi, 1, -1)
        else:
            # Round-2 #A3c：多水平/连续因子需 z-score，字符串列无法运算
            if not pd.api.types.is_numeric_dtype(col_vals):
                return AnalysisResult(
                    task="doe_analysis",
                    status="error",
                    messages=[
                        f"因子列「{col}」含 {len(unique_vals)} 个非数值水平，"
                        "DOE 效应估计仅支持二水平类别或数值因子。"
                        "请先 One-Hot 编码或转为数值。"
                    ],
                )
            # 多水平/连续因子：标准化后作为线性效应
            coded = (col_vals - col_vals.mean()) / (col_vals.std(ddof=1) + EPSILON)
        coded_map[col] = coded

        X = np.column_stack([np.ones(len(coded)), coded])
        try:
            beta, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
            # 二水平因子: 效应 = 2*β (对应 -1→+1 的全部范围变化)
            # 连续因子: 效应 = 2*β (对应 ±1σ 的变化，约覆盖 68% 数据)
            # 注: 两种效应量的物理含义不同（全范围 vs 2σ），Pareto 图中并排展示时需注意解读差异
            effect = float(2 * beta[1])
            # t 检验
            resid_std = float(np.std(y - X @ beta, ddof=2)) if len(y) > 2 else 1.0
            Sxx = np.sum((coded - np.mean(coded)) ** 2)
            se = resid_std / np.sqrt(Sxx) if Sxx > EPSILON else 1.0
            t_val = float(beta[1] / se) if se > EPSILON else 0.0
            dof = len(y) - 2
            p_val = float(2 * sp_stats.t.sf(abs(t_val), dof)) if dof > 0 else 1.0
        except (ValueError, np.linalg.LinAlgError, TypeError) as e:
            logger.warning("DOE 效应估计失败 (因子: %s): %s", col, e)
            # 标记为计算失败而非静默赋零，避免伪造正常结果
            effects.append(
                {
                    "因子": col,
                    "主效应": None,
                    "效应占比": None,
                    "t值": None,
                    "p值": None,
                    "显著": "计算失败",
                    "效应量": "计算异常（详见日志）",
                }
            )
            continue

        effect_ratio = (
            abs(effect) / (abs(grand_mean) + EPSILON) if abs(grand_mean) > EPSILON else 0.0
        )
        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        # Round-2 P3：alpha 越界（如 2.0）→ 全因子"显著"
        if not 0 < alpha < 1:
            return AnalysisResult(
                task="doe_analysis",
                status="error",
                messages=[f"alpha 必须在 (0, 1) 区间内，当前: {alpha!r}"],
            )
        effects.append(
            {
                "因子": col,
                "主效应": round(effect, 4),
                "效应占比": round(effect_ratio, 4),
                "t值": round(t_val, 3),
                "p值": round(p_val, 4),
                "显著": "是" if p_val < alpha else "否",
                "效应量": threshold_label(
                    effect_ratio, _DOE_EFFECT_THRESHOLDS, ("可忽略", "小", "中", "大")
                ),
            }
        )

    # ── 两两交互效应（MED-2 修复 2026-08-29：docstring 承诺但此前缺失）──
    # 编码交互列 = coded_i × coded_j，同样单变量 lstsq 回归，效应 = 2β（口径与主效应一致）
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    coded_names = list(coded_map.keys())
    if len(coded_names) >= 2:
        for i in range(len(coded_names)):
            for j in range(i + 1, len(coded_names)):
                ci_name, cj_name = coded_names[i], coded_names[j]
                inter = coded_map[ci_name] * coded_map[cj_name]
                inter_name = f"{ci_name}×{cj_name}"
                X_i = np.column_stack([np.ones(len(inter)), inter])
                try:
                    beta_i, _, _, _ = np.linalg.lstsq(X_i, y, rcond=None)
                    effect_i = float(2 * beta_i[1])
                    resid_std_i = float(np.std(y - X_i @ beta_i, ddof=2)) if len(y) > 2 else 1.0
                    Sxx_i = np.sum((inter - np.mean(inter)) ** 2)
                    se_i = resid_std_i / np.sqrt(Sxx_i) if Sxx_i > EPSILON else 1.0
                    t_i = float(beta_i[1] / se_i) if se_i > EPSILON else 0.0
                    dof_i = len(y) - 2
                    p_i = float(2 * sp_stats.t.sf(abs(t_i), dof_i)) if dof_i > 0 else 1.0
                except (ValueError, np.linalg.LinAlgError, TypeError) as e:
                    logger.warning("DOE 交互效应估计失败 (%s): %s", inter_name, e)
                    effects.append(
                        {
                            "因子": inter_name,
                            "主效应": None,
                            "效应占比": None,
                            "t值": None,
                            "p值": None,
                            "显著": "计算失败",
                            "效应量": "计算异常（详见日志）",
                        }
                    )
                    continue
                ratio_i = (
                    abs(effect_i) / (abs(grand_mean) + EPSILON)
                    if abs(grand_mean) > EPSILON
                    else 0.0
                )
                effects.append(
                    {
                        "因子": inter_name,
                        "主效应": round(effect_i, 4),
                        "效应占比": round(ratio_i, 4),
                        "t值": round(t_i, 3),
                        "p值": round(p_i, 4),
                        "显著": "是" if p_i < alpha else "否",
                        "效应量": threshold_label(
                            ratio_i, _DOE_EFFECT_THRESHOLDS, ("可忽略", "小", "中", "大")
                        ),
                    }
                )

    effects_df = pd.DataFrame(effects)
    # 分离计算失败的因子（避免 None 值影响排序和统计）
    failed_effects = (
        effects_df[effects_df["主效应"].isna()] if "主效应" in effects_df else pd.DataFrame()
    )
    valid_effects = effects_df[effects_df["主效应"].notna()].sort_values(
        "主效应", key=abs, ascending=False
    )
    top_name = str(valid_effects["因子"].iloc[0]) if len(valid_effects) > 0 else "N/A"
    top_val = float(valid_effects["主效应"].iloc[0]) if len(valid_effects) > 0 else 0

    # ── Lenth PSE 参考线（无重复时替代 p 值作为显著性参考）──
    effect_array = valid_effects["主效应"].values
    pse = _lenth_pse(effect_array) if len(effect_array) >= 3 else 0
    # Lenth 临界值使用 t 分布近似（自由度 ≈ m/3，m = 效应数目）
    m = len(effect_array)
    lenth_df = max(1, int(m / 3))
    lenth_t_crit = float(sp_stats.t.ppf(1 - alpha / 2, lenth_df)) if m >= 3 else 2.0
    me = lenth_t_crit * pse  # 同步边际误差 (SME) 近似

    # ── Pareto 图含显著性阈值 ──
    n_plot = max(len(valid_effects), 1)
    fig = Figure(figsize=(max(n_plot * 0.9, 6), 4))
    ax = fig.add_subplot(111)
    ef = valid_effects.sort_values("主效应", key=abs)
    colors = [
        PALETTE["target"]["primary"] if v < 0 else PALETTE["data"]["primary"] for v in ef["主效应"]
    ]
    ax.barh(ef["因子"], ef["主效应"], color=colors, height=0.6)
    ax.axvline(0, color=PALETTE["direction"]["zero"], linewidth=0.8)
    if me > 0:
        ax.axvline(
            me,
            color=PALETTE["anomaly"]["primary"],
            linestyle="--",
            linewidth=1,
            alpha=0.6,
            label=f"Lenth ME={me:.3f} (α={alpha})",
        )
        ax.axvline(-me, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, alpha=0.6)
    # 标注效应值
    for i, (_, row) in enumerate(ef.iterrows()):
        v = row["主效应"]
        ha = "left" if v >= 0 else "right"
        ax.text(
            v,
            i,
            f" {v:+.3f}",
            va="center",
            ha=ha,
            fontsize=8,
            fontweight="bold" if abs(v) > me else "normal",
        )
    ax.set_xlabel("主效应", fontsize=10)
    ax.set_title(
        f"DOE主效应 — {req.target_col} | 均值={grand_mean:.3f}, σ={grand_std:.3f}", fontsize=11
    )
    if me > 0:
        ax.legend(fontsize=8)
    fig.tight_layout()

    # ── 汇总 ──
    sig_count = int((valid_effects["显著"] == "是").sum())
    fail_count = len(failed_effects)
    top_effect_label = str(valid_effects["效应量"].iloc[0]) if len(valid_effects) > 0 else "N/A"
    summary_parts = [
        f"最强主效应: {top_name} (效应={top_val:.4f}, {top_effect_label})",
        f"显著因子: {sig_count}/{len(valid_effects)}",
    ]
    if fail_count > 0:
        summary_parts.append(f"⚠ {fail_count} 个因子计算失败")
    summary = "。".join(summary_parts)

    # 合并有效结果和失败标记到输出表
    output_table = (
        pd.concat([valid_effects, failed_effects], ignore_index=True)
        if fail_count > 0
        else valid_effects
    )

    return AnalysisResult(
        task="doe_analysis",
        tables={"effect_estimates": output_table},
        figures=[fig],
        summary=summary,
        metadata={
            "grand_mean": grand_mean,
            "failed_factors": fail_count,
            "grand_std": grand_std,
            "top_effect_factor": top_name,
            "lenth_pse": pse,
            "lenth_me": me,
            "significant_count": sig_count,
        },
    )


def roc_analysis(req: AnalysisRequest) -> AnalysisResult:
    """ROC 曲线和 AUC 分析 — 评估连续预测变量对二分类结果的区分能力。

    target_col: 二分类结果列 (0/1 或 合格/不合格)
    feature_cols[0]: 连续预测变量 (分数/概率)
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(
            task="roc_analysis", status="error", messages=["需要至少 1 个预测变量列"]
        )

    score_col = req.feature_cols[0]
    label_col = req.target_col
    sub = req.data[[label_col, score_col]].dropna()

    # 二值化标签
    unique_labels = sub[label_col].unique()
    # 审查 2026-08-19 #1.4：目标/预测列全 NaN 时 sub 为空 → sorted([])[-1] IndexError
    if len(unique_labels) < 2:
        return AnalysisResult(
            task="roc_analysis",
            status="error",
            messages=["目标列需要至少 2 个类别（当前有效样本不足或类别数 <2）"],
        )
    if len(unique_labels) > 2:
        return AnalysisResult(
            task="roc_analysis", status="error", messages=["目标列需要恰好 2 个不同值"]
        )

    # 自动识别阳性标签
    pos_label = _detect_positive_label(unique_labels)

    y_true = (sub[label_col] == pos_label).astype(int).values
    scores = sub[score_col].values

    from sklearn.metrics import auc, roc_curve

    try:
        fpr, tpr, thresholds = roc_curve(y_true, scores)
        auc_val = float(auc(fpr, tpr))
    except Exception:
        logger.debug("ROC 曲线计算失败", exc_info=True)
        return AnalysisResult(task="roc_analysis", status="error", messages=["ROC 曲线计算失败"])

    # 最佳阈值 (Youden's J = TPR - FPR)
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    best_threshold = float(thresholds[best_idx]) if best_idx < len(thresholds) else 0.0

    # AUC 判读
    if auc_val >= 0.9:
        auc_label = "优秀"
    elif auc_val >= 0.8:
        auc_label = "良好"
    elif auc_val >= 0.7:
        auc_label = "可接受"
    elif auc_val >= 0.6:
        auc_label = "较差"
    else:
        auc_label = "无效"

    # ROC 曲线图
    fig = Figure(figsize=(6, 5.5))
    ax = fig.add_subplot(111)
    ax.plot(
        fpr,
        tpr,
        "-",
        color=PALETTE["data"]["primary"],
        linewidth=2.5,
        label=f"ROC (AUC={auc_val:.3f}, {auc_label})",
    )
    ax.plot(
        [0, 1],
        [0, 1],
        "--",
        color=PALETTE["spec"]["tertiary"],
        linewidth=1,
        alpha=0.6,
        label="随机猜测 (AUC=0.5)",
    )
    ax.fill_between(fpr, tpr, alpha=0.1, color=PALETTE["data"]["primary"])
    ax.scatter(
        [fpr[best_idx]],
        [tpr[best_idx]],
        s=100,
        color=PALETTE["target"]["primary"],
        marker="o",
        zorder=5,
        label=f"最佳阈值={best_threshold:.3f} (J={j_scores[best_idx]:.3f})",
    )
    ax.set_xlabel("假阳性率 (FPR)", fontsize=10)
    ax.set_ylabel("真阳性率 (TPR/召回率)", fontsize=10)
    ax.set_title(f"ROC 曲线 — {score_col} → {label_col} ({pos_label})", fontsize=11)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    summary = (
        f"AUC={auc_val:.3f} ({auc_label}), "
        f"最佳阈值={best_threshold:.3f} (TPR={tpr[best_idx]:.3f}, FPR={fpr[best_idx]:.3f})"
    )

    # 清洗阈值数组 — sklearn roc_curve 第一个元素为 np.inf, JSON 不支持
    thresholds_clean = np.where(np.isinf(thresholds), np.nan, thresholds)
    return AnalysisResult(
        task="roc_analysis",
        tables={
            "roc_points": pd.DataFrame(
                {
                    "阈值": thresholds_clean.round(4),
                    "FPR": fpr.round(4),
                    "TPR": tpr.round(4),
                    "Youden_J": (tpr - fpr).round(4),
                }
            ),
            "auc_summary": pd.DataFrame(
                {
                    "指标": ["AUC", "判读", "最佳阈值", "最佳TPR", "最佳FPR", "阳性标签", "样本量"],
                    "值": [
                        f"{auc_val:.4f}",
                        auc_label,
                        f"{best_threshold:.4f}",
                        f"{tpr[best_idx]:.4f}",
                        f"{fpr[best_idx]:.4f}",
                        str(pos_label),
                        str(len(sub)),
                    ],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "auc": auc_val,
            "auc_label": auc_label,
            "best_threshold": best_threshold,
            "best_tpr": float(tpr[best_idx]),
            "best_fpr": float(fpr[best_idx]),
            "positive_label": str(pos_label),
        },
    )


def logistic_regression(req: AnalysisRequest) -> AnalysisResult:
    """Logistic 回归 — 二分类结果建模，输出 Odds Ratio 和分类指标。

    target_col: 二分类结果列 (0/1 或 合格/不合格)
    feature_cols: 预测变量列
    """
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="logistic_regression", status="error", messages=["需要至少 1 个因子列"]
        )

    sub = req.data[[req.target_col] + cols].dropna()
    unique_y = sub[req.target_col].unique()
    if len(unique_y) != 2:
        return AnalysisResult(
            task="logistic_regression", status="error", messages=["目标列需要恰好 2 个不同值"]
        )

    # 二值化 — 使用与 roc_analysis 相同的阳性标签检测逻辑
    pos_label = _detect_positive_label(unique_y)
    y = (sub[req.target_col] == pos_label).astype(int).values

    # 分类阈值 — 提前提取+防护，避免被模型拟合异常误翻译
    threshold = req.params.get("threshold", 0.5)
    try:
        threshold = float(threshold)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="logistic_regression",
            status="error",
            messages=[f"参数 threshold 值无效: {threshold}，请输入数值 (0~1)"],
        )
    if not 0 < threshold < 1:
        return AnalysisResult(
            task="logistic_regression",
            status="error",
            messages=[f"阈值 threshold 必须在 (0, 1) 范围内，当前值: {threshold}"],
        )

    try:
        X = sm.add_constant(sub[cols])
        model = sm.Logit(y, X).fit(disp=0)
        if not getattr(model, "mle_retvals", {}).get("converged", True):
            logger.warning("Logistic 模型未收敛，结果可能不可靠")
    except Exception:
        logger.debug("Logistic 模型拟合失败", exc_info=True)
        return AnalysisResult(
            task="logistic_regression", status="error", messages=["Logistic 模型拟合失败"]
        )

    # Odds Ratios — clamp coefficients to prevent exp overflow (>700 → inf)
    _EXP_MAX = 700.0
    params = np.clip(np.asarray(model.params), -_EXP_MAX, _EXP_MAX)
    ci = model.conf_int()
    or_vals = np.exp(params)
    or_ci_lower = np.exp(np.clip(ci.iloc[:, 0].values, -_EXP_MAX, _EXP_MAX))
    or_ci_upper = np.exp(np.clip(ci.iloc[:, 1].values, -_EXP_MAX, _EXP_MAX))

    coef_df = pd.DataFrame(
        {
            "变量": X.columns,
            "系数": params.round(4),
            "标准误": np.asarray(model.bse).round(4),
            "z值": np.asarray(model.tvalues).round(3),
            "p值": np.asarray(model.pvalues).round(4),
            "OR (Odds Ratio)": or_vals.round(3),
            "OR 95%CI下限": or_ci_lower.round(3),
            "OR 95%CI上限": or_ci_upper.round(3),
        }
    )

    # 预测和分类表 — 使用前面已提取+校验的 threshold
    y_pred_prob = model.predict(X)
    y_pred = (y_pred_prob >= threshold).astype(int)
    accuracy = float(np.mean(y_pred == y))
    sensitivity = float(np.sum((y_pred == 1) & (y == 1)) / max(np.sum(y == 1), 1))
    specificity = float(np.sum((y_pred == 0) & (y == 0)) / max(np.sum(y == 0), 1))

    # Pseudo R²
    ll_null = model.llnull if hasattr(model, "llnull") else 0
    ll_model = model.llf
    mcfadden_r2 = float(1 - ll_model / ll_null) if ll_null != 0 else 0

    # 可视化：OR 森林图
    sig_vars = coef_df[coef_df["变量"] != "const"]
    fig = Figure(figsize=(7, max(len(sig_vars) * 0.6, 3.5)))
    ax = fig.add_subplot(111)
    sig_vars_plot = sig_vars.sort_values("OR (Odds Ratio)")
    y_pos = range(len(sig_vars_plot))
    ax.scatter(
        sig_vars_plot["OR (Odds Ratio)"].values,
        y_pos,
        s=60,
        color=PALETTE["data"]["primary"],
        zorder=3,
    )
    for i, (_, row) in enumerate(sig_vars_plot.iterrows()):
        ax.plot(
            [row["OR 95%CI下限"], row["OR 95%CI上限"]],
            [i, i],
            "-",
            color=PALETTE["data"]["secondary"],
            linewidth=2,
        )
    ax.axvline(
        1, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, alpha=0.6, label="OR=1"
    )
    ax.set_yticks(y_pos)
    ax.set_yticklabels(sig_vars_plot["变量"], fontsize=9)
    ax.set_xlabel("Odds Ratio (95% CI)", fontsize=10)
    ax.set_title(
        f"Logistic 回归 — {req.target_col} ({pos_label}) | "
        f"Acc={accuracy:.3f}, McFadden R²={mcfadden_r2:.3f}",
        fontsize=10,
    )
    ax.legend(fontsize=8)
    fig.tight_layout()

    summary = (
        f"Logistic: Acc={accuracy:.1%}, Sens={sensitivity:.1%}, Spec={specificity:.1%}, "
        f"McFadden R²={mcfadden_r2:.3f}" + (f" (阈值={threshold:.2f})" if threshold != 0.5 else "")
    )

    return AnalysisResult(
        task="logistic_regression",
        tables={
            "coefficients": coef_df,
            "classification_metrics": pd.DataFrame(
                {
                    "指标": ["准确率", "灵敏度 (召回)", "特异度", "McFadden R²", "AIC", "样本量"],
                    "值": [
                        f"{accuracy:.4f}",
                        f"{sensitivity:.4f}",
                        f"{specificity:.4f}",
                        f"{mcfadden_r2:.4f}",
                        f"{model.aic:.1f}",
                        str(len(sub)),
                    ],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        messages=[
            "⚠ Logistic 模型未收敛，系数和 OR 估计可能不可靠。请检查数据是否存在完美分离或共线性。"
        ]
        if not getattr(model, "mle_retvals", {}).get("converged", True)
        else [],
        metadata={
            "accuracy": accuracy,
            "sensitivity": sensitivity,
            "specificity": specificity,
            "mcfadden_r2": mcfadden_r2,
            "aic": float(model.aic),
            "model_converged": getattr(model, "mle_retvals", {}).get("converged", True),
        },
    )


def lasso_regression(req: AnalysisRequest) -> AnalysisResult:
    """Lasso/ElasticNet 正则化回归 — 自动变量选择 + 正则化路径。

    相比 OLS，Lasso 可将不重要的变量系数压缩到零，实现自动特征选择。
    """
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(
            task="lasso_regression", status="error", messages=["至少需要 2 个因子列"]
        )

    sub = req.data[[req.target_col] + cols].dropna()
    if len(sub) < len(cols) + 2:
        return AnalysisResult(task="lasso_regression", status="error", messages=["有效样本不足"])

    from sklearn.linear_model import ElasticNetCV, LassoCV
    from sklearn.preprocessing import StandardScaler

    X = sub[cols].values
    y = sub[req.target_col].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    alpha = req.params.get("alpha_lasso", None)
    if alpha is not None:
        alpha = _safe_float(alpha, 1.0)
    l1_ratio = _safe_float(
        req.params.get("l1_ratio", 1.0), 1.0
    )  # 1.0 = pure Lasso, <1 = ElasticNet
    # Round-2 P3：l1_ratio 越界此前静默按纯 Lasso/ElasticNet 执行
    if not 0 <= l1_ratio <= 1:
        return AnalysisResult(
            task="lasso_regression",
            status="error",
            messages=[f"l1_ratio 必须在 [0, 1] 区间内，当前: {l1_ratio!r}"],
        )

    _lasso_max_iter = 5000
    if alpha is not None:
        if l1_ratio < 1.0:
            # 用户既指定了 alpha 又指定了 l1_ratio → 使用 ElasticNet
            from sklearn.linear_model import ElasticNet

            model = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=_lasso_max_iter).fit(
                X_scaled, y
            )
        else:
            from sklearn.linear_model import Lasso

            model = Lasso(alpha=alpha, max_iter=_lasso_max_iter).fit(X_scaled, y)
        best_alpha = alpha
        train_r2 = None
    elif l1_ratio < 1.0:
        # cv 下限 2：len(sub)//3 可能为 1 → sklearn InvalidParameterError（审查 2026-08-19 #1.4）
        _cv = max(2, min(5, len(sub) // 3))
        model = ElasticNetCV(
            l1_ratio=[l1_ratio], cv=_cv, max_iter=_lasso_max_iter, random_state=42
        ).fit(X_scaled, y)
        best_alpha = float(model.alpha_)
        train_r2 = float(model.score(X_scaled, y))
    else:
        _cv = max(2, min(5, len(sub) // 3))
        model = LassoCV(cv=_cv, max_iter=_lasso_max_iter, random_state=42).fit(X_scaled, y)
        best_alpha = float(model.alpha_)
        train_r2 = float(model.score(X_scaled, y))

    # 系数
    coefs = model.coef_
    nonzero = np.abs(coefs) > 1e-6
    n_selected = int(np.sum(nonzero))
    r2 = float(model.score(X_scaled, y))

    # 收敛性检查：max_iter 用尽且未收敛时警告用户
    convergence_warning = ""
    if hasattr(model, "n_iter_"):
        n_iter_actual = (
            int(model.n_iter_) if np.isscalar(model.n_iter_) else int(np.max(model.n_iter_))
        )
        if n_iter_actual >= _lasso_max_iter:
            convergence_warning = (
                "⚠ Lasso 模型在最大迭代次数内未收敛，系数可能不准确，建议增大 max_iter 或调整 alpha"
            )

    coef_df = pd.DataFrame(
        {
            "变量": cols + ["(截距)"],
            "标准化系数": list(coefs) + [float(model.intercept_)],
            "选中": ["是" if abs(c) > 1e-6 else "否" for c in coefs] + ["—"],
        }
    ).sort_values("标准化系数", key=abs, ascending=False)

    # 可视化
    fig = Figure(figsize=(7, 4))
    ax = fig.add_subplot(111)
    nonzero_coefs = coef_df[coef_df["选中"] == "是"]
    if len(nonzero_coefs) > 0:
        colors = [
            PALETTE["target"]["primary"] if v < 0 else PALETTE["data"]["primary"]
            for v in nonzero_coefs["标准化系数"]
        ]
        ax.barh(nonzero_coefs["变量"], nonzero_coefs["标准化系数"], color=colors)
    ax.axvline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
    ax.set_xlabel("标准化系数", fontsize=10)
    ax.set_title(
        f"Lasso 回归 — {req.target_col} | "
        f"选中 {n_selected}/{len(cols)} 变量, α={best_alpha:.4f}, R²={r2:.3f}",
        fontsize=10,
    )
    fig.tight_layout()

    summary = f"Lasso: 选中 {n_selected}/{len(cols)} 变量, R²={r2:.3f}, α={best_alpha:.4f}" + (
        f", 训练 R²={train_r2:.3f}" if train_r2 else ""
    )

    messages = []
    if convergence_warning:
        messages.append(convergence_warning)

    return AnalysisResult(
        task="lasso_regression",
        tables={"coefficients": coef_df},
        figures=[fig],
        summary=summary,
        messages=messages,
        metadata={
            "r_squared": r2,
            "train_r2": train_r2,
            "best_alpha": best_alpha,
            "n_selected": n_selected,
            "n_features": len(cols),
            "converged": not bool(convergence_warning),
        },
    )


def robust_regression(req: AnalysisRequest) -> AnalysisResult:
    """Huber 稳健回归 — 对异常值不敏感的线性建模。

    使用 Huber 损失函数，自动降低异常值权重。返回与 OLS 的对比。
    """
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="robust_regression", status="error", messages=["需要至少 1 个因子列"]
        )

    sub = req.data[[req.target_col] + cols].dropna()
    if len(sub) < len(cols) + 2:
        return AnalysisResult(task="robust_regression", status="error", messages=["有效样本不足"])

    from sklearn.linear_model import HuberRegressor

    try:
        X = sub[cols].values
        y = sub[req.target_col].values
        huber = HuberRegressor(epsilon=1.35, max_iter=1000)
        huber.fit(X, y)

        # OLS 对比
        Xc = sm.add_constant(X)
        ols_model = sm.OLS(y, Xc).fit()

        # 对比表
        coef_df = pd.DataFrame(
            {
                "变量": ["(截距)"] + cols,
                "Huber系数": [huber.intercept_] + list(huber.coef_),
                "OLS系数": list(ols_model.params),
                "差异": [huber.intercept_ - ols_model.params[0]]
                + [h - o for h, o in zip(huber.coef_, ols_model.params[1:])],
            }
        )

        # 识别差异大的变量（OLS 受异常值影响严重）
        max_diff_idx = np.argmax(np.abs(coef_df["差异"].values[1:])) + 1
        outlier_sensitive = coef_df.iloc[max_diff_idx]["变量"] if len(coef_df) > 1 else None

        fig = Figure(figsize=(8, 4.5))
        ax = fig.add_subplot(111)
        x_pos = np.arange(len(coef_df))
        width = 0.35
        ax.bar(
            x_pos - width / 2,
            coef_df["Huber系数"],
            width,
            label="Huber 稳健",
            color=PALETTE["data"]["primary"],
        )
        ax.bar(
            x_pos + width / 2,
            coef_df["OLS系数"],
            width,
            label="OLS",
            color=PALETTE["data"]["secondary"],
            alpha=0.7,
        )
        ax.set_xticks(x_pos)
        ax.set_xticklabels(coef_df["变量"], rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("系数", fontsize=10)
        ax.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
        ax.set_title("Huber 稳健回归 vs OLS", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        summary = "稳健回归完成。" + (
            f"差异最大变量: {outlier_sensitive}" if outlier_sensitive else ""
        )

        return AnalysisResult(
            task="robust_regression",
            tables={"coefficient_comparison": coef_df},
            figures=[fig],
            summary=summary,
            metadata={"n_samples": len(sub), "n_features": len(cols)},
        )
    except Exception:
        logger.debug("稳健回归拟合失败", exc_info=True)
        return AnalysisResult(
            task="robust_regression", status="error", messages=["稳健回归拟合失败"]
        )


def quantile_regression(req: AnalysisRequest) -> AnalysisResult:
    """分位数回归 — 对非正态/异方差响应建模中位数或其他分位数。

    参数:
        quantile: 目标分位数 (默认 0.5 = 中位数回归)
    """
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="quantile_regression", status="error", messages=["需要至少 1 个因子列"]
        )

    sub = req.data[[req.target_col] + cols].dropna()
    if len(sub) < len(cols) + 2:
        return AnalysisResult(task="quantile_regression", status="error", messages=["有效样本不足"])

    quantile = req.params.get("quantile", 0.5)
    try:
        quantile = float(quantile)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="quantile_regression",
            status="error",
            messages=[f"参数 quantile 值无效: {quantile}，请输入数值 (0~1)"],
        )
    if not 0 < quantile < 1:
        return AnalysisResult(
            task="quantile_regression",
            status="error",
            messages=[f"分位数 τ 必须在 (0, 1) 范围内，当前值: {quantile}"],
        )
    try:
        X_df = sub[cols]
        y = sub[req.target_col]
        Xc = sm.add_constant(X_df)
        model = sm.QuantReg(y, Xc).fit(q=quantile)

        coef_df = pd.DataFrame(
            {
                "变量": Xc.columns,
                "系数": np.asarray(model.params).round(4),
                "标准误": np.asarray(model.bse).round(4),
                "t值": np.asarray(model.tvalues).round(3),
                "p值": np.asarray(model.pvalues).round(4),
            }
        )

        q_label = (
            f"Q{round(quantile * 100)} (中位数)" if quantile == 0.5 else f"Q{round(quantile * 100)}"
        )
        summary = f"{q_label} 回归完成，{len(coef_df) - 1} 个变量"

        return AnalysisResult(
            task="quantile_regression",
            tables={"coefficients": coef_df},
            summary=summary,
            metadata={"quantile": quantile, "n_samples": len(sub), "n_features": len(cols)},
        )
    except Exception:
        logger.debug("分位数回归拟合失败", exc_info=True)
        return AnalysisResult(
            task="quantile_regression", status="error", messages=["分位数回归拟合失败"]
        )


# ══════════════════════════════════════════════════════════════════════
# DOE 实验设计（doe_design）— 生成实验设计矩阵
# ══════════════════════════════════════════════════════════════════════

_VALID_DOE_METHODS = (
    "full_factorial",
    "fractional_factorial",
    "plackett_burman",
    "taguchi",
    "box_behnken",
    "ccd",
)

# Plackett-Burman 支持的运行数（N-1 必须为素数且 ≡ 3 mod 4，保证循环构造正交）。
# 注：28 不是标准 PB 规模（27=3³ 非素数，无循环差集，构造方式不同），故不列入。
_PB_SUPPORTED = (12, 20, 24)


def _legendre(a: int, p: int) -> int:
    """Legendre 符号：+1（二次剩余）/ -1（非剩余）/ 0（a ≡ 0 mod p）。"""
    a %= p
    if a == 0:
        return 0
    return 1 if pow(a, (p - 1) // 2, p) == 1 else -1


def _pb_generator(n_runs: int) -> list[int]:
    """Plackett-Burman 生成首行（+1 → 1，-1 → 0），基于二次剩余构造。

    N-1 = p 为素数时，g[j] = χ(j)（j=0..p-1），其中 χ(0) 约定为 +1。
    循环移位 + 末行全 0 后构成正交矩阵（由测试校验）。
    """
    if n_runs not in _PB_SUPPORTED:
        raise ValueError(f"plackett_burman 当前仅支持运行数 {list(_PB_SUPPORTED)}")
    p = n_runs - 1
    return [1 if (j == 0 or _legendre(j, p) == 1) else 0 for j in range(p)]


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_bool(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "是")
    return bool(v)


def _parse_factors(params):
    """解析并校验 factors 参数。返回 (parsed_list | None, [错误消息])。"""
    factors = params.get("factors")
    if not factors:
        return None, ["需要提供因子定义 (factors)，格式: [{'name': ..., 'levels': [...]}]"]
    parsed, seen = [], set()
    for i, f in enumerate(factors):
        name = f.get("name")
        levels = f.get("levels")
        if not name or not isinstance(name, str):
            return None, [f"第 {i + 1} 个因子缺少有效的 name"]
        if name in seen:
            return None, [f"因子名重复: {name}"]
        seen.add(name)
        if not isinstance(levels, (list, tuple)) or len(set(map(str, levels))) < 2:
            return None, [f"因子「{name}」的水平数必须 ≥ 2 且互异"]
        parsed.append({"name": name, "levels": list(levels)})
    return parsed, []


def _gen_full_factorial(factors) -> np.ndarray:
    """全因子：所有水平组合的笛卡尔积，返回水平索引矩阵。"""
    idx = [range(len(f["levels"])) for f in factors]
    return np.array(list(product(*idx)), dtype=int)


def _gen_fractional(factors, n_runs):
    """2^(k-p) 部分因子：GF(2) 饱和表取 k 个因子列（独立列优先）。返回 (矩阵, 错误列表)。"""
    from smartsuite.engine._doe_arrays import _two_level_factor_columns

    n = int(round(np.log2(n_runs)))
    if 2**n != n_runs:
        return None, [f"fractional_factorial 的运行数必须是 2 的幂，当前: {n_runs}"]
    k = len(factors)
    if k > n_runs - 1:
        return None, [f"因子数({k})超过 2^n-1({n_runs - 1})，正交表装不下"]
    return _two_level_factor_columns(n_runs, k), []


def _pb_matrix(n_runs) -> np.ndarray:
    """Plackett-Burman 矩阵：循环移位 + 末行全 0。"""
    g = np.array(_pb_generator(n_runs))
    rows = [np.roll(g, i) for i in range(n_runs - 1)]
    rows.append(np.zeros(n_runs - 1, dtype=int))
    return np.array(rows, dtype=int)


def _gen_plackett_burman(factors, n_runs):
    """Plackett-Burman 筛选设计。返回 (矩阵, 错误列表)。"""
    k = len(factors)
    try:
        m = _pb_matrix(n_runs)
    except ValueError as e:
        logger.warning("PB 设计生成失败 (n_runs=%s): %s", n_runs, e)
        return None, [f"plackett_burman 当前仅支持运行数: {sorted(_PB_SUPPORTED)}"]
    if k > n_runs - 1:
        return None, [f"因子数({k})超过 PB 运行数上限({n_runs - 1})"]
    return m[:, :k], []


def _two_level_base(name, runs) -> np.ndarray:
    """二水平正交表：L12 走 PB，其余走 GF(2)。"""
    from smartsuite.engine._doe_arrays import two_level_oa

    if name == "L12":
        return _pb_matrix(12)
    return two_level_oa(runs)


def _gen_taguchi(factors):
    """田口正交数组匹配器。返回 (编码矩阵, 表名, 列构成描述)。

    纯二水平 → L4/L8/L12/L16/L32；纯三水平 → L9/L27；
    混合 2/3 水平 → 以 L18 为基与 2^m 全因子做直积。
    失败时抛 ValueError（中文消息）。
    """
    from smartsuite.engine._doe_arrays import L18, three_level_oa, two_level_oa

    n2 = sum(1 for f in factors if len(f["levels"]) == 2)
    n3 = sum(1 for f in factors if len(f["levels"]) == 3)

    if n3 == 0:
        for name, runs, c2 in (
            ("L4", 4, 3),
            ("L8", 8, 7),
            ("L12", 12, 11),
            ("L16", 16, 15),
            ("L32", 32, 31),
        ):
            if n2 <= c2:
                two_cols = _two_level_base(name, runs)
                three_cols = None
                spec = f"2^{c2}"
                break
        else:
            raise ValueError(f"二水平因子数({n2})过多，无正交表可匹配")
    elif n2 == 0:
        for name, runs, c3 in (("L9", 9, 4), ("L27", 27, 13)):
            if n3 <= c3:
                three_cols = three_level_oa(runs)
                two_cols = None
                spec = f"3^{c3}"
                break
        else:
            raise ValueError(f"三水平因子数({n3})过多，无正交表可匹配")
    else:
        if n3 > 7:
            raise ValueError(
                "三水平因子数超过 7 且含二水平因子时无正交表可匹配；"
                "建议改用 full_factorial 或减少三水平因子数"
            )
        if n2 <= 1:
            two_cols = L18[:, 0:1]
            three_cols = L18[:, 1:8]
            name, spec = "L18", "2^1·3^7"
        else:
            m = 1
            while 2 ** (m + 1) - 1 < n2:
                m += 1
            ff = two_level_oa(2**m)  # (2^m) × (2^m-1)
            c1 = L18[:, 0]
            three = L18[:, 1:8]
            tiled_c1 = np.tile(c1, 2**m)
            two_list = [tiled_c1]
            for i in range(ff.shape[1]):
                a = np.repeat(ff[:, i], 18)
                two_list.append(a)
                two_list.append(tiled_c1 ^ a)
            two_cols = np.column_stack(two_list)  # (18·2^m) × (2^(m+1)-1)
            three_cols = np.tile(three, (2**m, 1))  # (18·2^m) × 7
            name = f"L{18 * 2**m}"
            spec = f"2^{2 ** (m + 1) - 1}·3^7"

    # 依因子顺序拼装列（二水平因子取二水平列，三水平因子取三水平列）
    cols, p2, p3 = [], 0, 0
    for f in factors:
        if len(f["levels"]) == 2:
            cols.append(two_cols[:, p2])
            p2 += 1
        else:
            cols.append(three_cols[:, p3])
            p3 += 1
    return np.column_stack(cols), name, spec


def _gen_box_behnken(k) -> np.ndarray:
    """Box-Behnken：每对因子的 2×2 方形角点（其余取中心），返回 -1/0/+1 编码。"""
    rows = []
    for i, j in combinations(range(k), 2):
        for a in (-1, 1):
            for b in (-1, 1):
                r = np.zeros(k)
                r[i], r[j] = a, b
                rows.append(r)
    return np.array(rows)


def _gen_ccd(k, alpha, center_points) -> np.ndarray:
    """中心复合设计：2^k（或 2^(k-1)）阶乘 + 2k 轴向点 + 中心点。"""
    if k <= 4:
        fact = np.array(list(product([-1.0, 1.0], repeat=k)))
    else:
        from smartsuite.engine._doe_arrays import _two_level_factor_columns

        n = int(round(np.log2(2 ** (k - 1))))
        fact = 2 * _two_level_factor_columns(2**n, k) - 1  # 0/1 → -1/+1
    axial = []
    for i in range(k):
        for s in (-alpha, alpha):
            r = np.zeros(k)
            r[i] = s
            axial.append(r)
    center = np.zeros((center_points, k))
    return np.vstack([fact, np.array(axial), center])


def _resolve_alpha(alpha, k, center_points):
    """解析 CCD 轴向距离 α。返回 float 或 None（非法）。"""
    # 阶乘点数量：k≤4 全因子 2^k，k≥5 半因子 2^(k-1)
    nf = 2**k if k <= 4 else 2 ** (k - 1)
    if alpha == "rotatable":
        # 旋转性：α = nf^(1/4)（k≤4 时即 2^(k/4)）
        return float(nf ** (1 / 4))
    if alpha == "face":
        return 1.0
    if alpha == "orthogonal":
        # 正交性：α = sqrt((sqrt(nf·N) − nf) / 2)，N = 总运行数
        ns = 2 * k
        n_total = nf + ns + center_points
        return float(np.sqrt((np.sqrt(nf * n_total) - nf) / 2))
    if _is_num(alpha) and alpha > 0:
        return float(alpha)
    return None


def _assemble_design(req, factors, coded, method, oa_name, oa_spec):
    """映射到实际水平 + 重复 + 随机化 + 运行顺序，组装 AnalysisResult。"""
    replicates = req.params.get("replicates", 1)
    try:
        replicates = int(replicates)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=[f"replicates 值无效: {replicates}，请输入整数"],
        )
    if replicates < 1:
        return AnalysisResult(task="doe_design", status="error", messages=["replicates 必须 ≥ 1"])

    cols = {}
    for ci, f in enumerate(factors):
        lv = f["levels"]
        col = coded[:, ci]
        if method in ("box_behnken", "ccd"):
            lo, mid, hi = float(lv[0]), float(lv[1]), float(lv[2])
            vals = np.where(col >= 0, mid + col * (hi - mid), mid + col * (mid - lo))
        else:
            vals = np.array([lv[int(i)] for i in col])
        cols[f["name"]] = vals

    df = pd.DataFrame(cols)
    if replicates > 1:
        df = pd.concat([df] * replicates, ignore_index=True)
        df.insert(0, "重复", np.repeat(np.arange(1, replicates + 1), len(coded)))

    randomize = _as_bool(req.params.get("randomize", True), True)
    seed = req.params.get("seed", 42)
    try:
        seed = int(seed)
    except (ValueError, TypeError):
        seed = 42
    if randomize:
        df = df.sample(frac=1.0, random_state=np.random.RandomState(seed)).reset_index(drop=True)
    df.insert(0, "运行顺序", np.arange(1, len(df) + 1))

    info = pd.DataFrame(
        {
            "指标": ["方法", "正交表", "列构成", "运行数", "因子数"],
            "值": [method, oa_name or "—", oa_spec or "—", str(len(df)), str(len(factors))],
        }
    )
    summary = f"{method} 设计：{len(factors)} 个因子，共 {len(df)} 次运行" + (
        f"（正交表 {oa_name}）" if oa_name else ""
    )
    return AnalysisResult(
        task="doe_design",
        tables={"design_matrix": df, "design_info": info},
        summary=summary,
        metadata={
            "method": method,
            "n_runs": len(df),
            "n_factors": len(factors),
            "oa_name": oa_name,
            "oa_spec": oa_spec,
            "randomized": randomize,
            "seed": seed,
            "replicates": replicates,
        },
    )


def doe_design(req: AnalysisRequest) -> AnalysisResult:
    """DOE 实验设计 — 输入因子（名称+水平）与设计方法，输出实验设计矩阵。

    参数 (params):
        factors: 必需，[{name, levels}]，levels 为水平值列表（数值或标签）
        method: full_factorial | fractional_factorial | plackett_burman
                | taguchi | box_behnken | ccd（默认 full_factorial）
        replicates: 重复次数（默认 1）
        randomize: 是否随机化运行顺序（默认 True）
        seed: 随机种子（默认 42）
        center_points: RSM 中心点重复数（BB/CCD，默认 3）
        alpha: CCD 轴向距离 rotatable|orthogonal|face|数值（默认 rotatable）
        n_runs: 指定运行数（fractional_factorial / plackett_burman）

    数据要求: 无（忽略 req.data，因子从 params 读取）
    """
    method = req.params.get("method", "full_factorial")
    if method not in _VALID_DOE_METHODS:
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=[f"method 无效: {method!r}，支持: {list(_VALID_DOE_METHODS)}"],
        )
    factors, errs = _parse_factors(req.params)
    if errs:
        return AnalysisResult(task="doe_design", status="error", messages=errs)

    oa_name, oa_spec = None, None
    try:
        if method == "full_factorial":
            total = int(np.prod([len(f["levels"]) for f in factors]))
            if total > 10000:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[f"全因子运行数({total})超过上限 10000，请改用 taguchi/ccd 降维"],
                )
            coded = _gen_full_factorial(factors)
        elif method == "fractional_factorial":
            if any(len(f["levels"]) != 2 for f in factors):
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=["fractional_factorial 要求所有因子为 2 水平"],
                )
            n_runs = req.params.get("n_runs") or 2 ** len(factors)
            try:
                n_runs = int(n_runs)
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="doe_design", status="error", messages=[f"n_runs 值无效: {n_runs}"]
                )
            coded, err = _gen_fractional(factors, n_runs)
            if err:
                return AnalysisResult(task="doe_design", status="error", messages=err)
            oa_name = f"2^{int(np.log2(n_runs))}"
            oa_spec = f"2^(k-p), 运行数={n_runs}"
        elif method == "plackett_burman":
            if any(len(f["levels"]) != 2 for f in factors):
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=["plackett_burman 要求所有因子为 2 水平"],
                )
            k = len(factors)
            n_runs = req.params.get("n_runs") or next(
                (n for n in _PB_SUPPORTED if n - 1 >= k), None
            )
            try:
                n_runs = int(n_runs)
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="doe_design", status="error", messages=[f"n_runs 值无效: {n_runs}"]
                )
            coded, err = _gen_plackett_burman(factors, n_runs)
            if err:
                return AnalysisResult(task="doe_design", status="error", messages=err)
            oa_name = f"PB{n_runs}"
            oa_spec = f"2^{n_runs - 1}"
        elif method == "taguchi":
            coded, oa_name, oa_spec = _gen_taguchi(factors)
        else:  # box_behnken / ccd
            bad = [
                f["name"]
                for f in factors
                if len(f["levels"]) != 3 or not all(_is_num(v) for v in f["levels"])
            ]
            if bad:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[
                        f"{method} 要求所有因子为 3 个数值水平（低/中/高），以下因子不符: {bad}"
                    ],
                )
            k = len(factors)
            if method == "box_behnken" and not (3 <= k <= 12):
                return AnalysisResult(
                    task="doe_design", status="error", messages=["box_behnken 支持 3-12 个因子"]
                )
            if method == "ccd" and not (2 <= k <= 10):
                return AnalysisResult(
                    task="doe_design", status="error", messages=["ccd 支持 2-10 个因子"]
                )
            center_points = req.params.get("center_points", 3)
            try:
                center_points = int(center_points)
            except (ValueError, TypeError):
                center_points = 3
            if center_points < 0:
                return AnalysisResult(
                    task="doe_design", status="error", messages=["center_points 必须 ≥ 0"]
                )
            if method == "box_behnken":
                coded = np.vstack(
                    [
                        _gen_box_behnken(k),
                        np.zeros((center_points, k)),
                    ]
                )
                oa_name, oa_spec = "Box-Behnken", f"k={k}"
            else:
                alpha = _resolve_alpha(req.params.get("alpha", "rotatable"), k, center_points)
                if alpha is None:
                    return AnalysisResult(
                        task="doe_design",
                        status="error",
                        messages=[
                            f"alpha 无效: {req.params.get('alpha')!r}，"
                            "支持 rotatable|orthogonal|face 或正数值"
                        ],
                    )
                coded = _gen_ccd(k, alpha, center_points)
                oa_name, oa_spec = "CCD", f"k={k}, α={alpha:.4f}"
    except ValueError as e:
        logger.warning("DOE 设计生成失败 (method=%s): %s", method, e)
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=["实验设计生成失败：请检查因子水平、alpha 与 center_points 参数配置"],
        )

    return _assemble_design(req, factors, coded, method, oa_name, oa_spec)
