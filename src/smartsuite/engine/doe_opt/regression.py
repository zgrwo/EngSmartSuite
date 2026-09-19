"""回归建模族（OLS / Lasso / 稳健 / 分位数）。"""

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import DW_NEGATIVE_AUTOCORR, DW_POSITIVE_AUTOCORR
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    durbin_watson,
    round_for_display,
)
from smartsuite.engine._utils import (
    safe_float as _safe_float,
)

logger = logging.getLogger(__name__)


def _std_beta(model, X):
    """计算标准化回归系数 (Beta 权重)，用于比较不同量纲变量的重要性。

    审查 2026-09-16 C-3：y_std/x_std 带数据量纲，绝对 EPSILON 会把微尺度数据
    整表归零 → 改精确零/非有限判据（β·σx/σy 为量纲无关比值，可正常计算）。
    """
    y_std = float(np.std(model.model.endog))
    if not np.isfinite(y_std) or y_std == 0:
        return [0.0] * len(X.columns)
    beta = []
    for col in X.columns:
        if col == "const":
            beta.append(0.0)
        else:
            param_val = model.params[col]
            x_std = float(np.std(X[col]))
            if not np.isfinite(param_val) or x_std == 0:
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
        # 秩亏（常量残差/共线 X）告警由下方相对判据统一处理，此处仅静默 statsmodels 英文告警
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SingularMatrixWarning)
            aux_model = sm.OLS(resid_sq, X).fit()
        ess = np.sum((aux_model.fittedvalues - resid_sq_mean) ** 2)
        rss = np.sum((resid_sq - aux_model.fittedvalues) ** 2)
        # 审查 2026-08-19：#完美拟合时 ess=rss=0 → LM=0/0=NaN，返回 None 由调用方显示 N/A
        # 审查 2026-09-05 B3：原绝对阈值 1e-12 误判微尺度真实数据（y~1e-10、残差~1e-13）
        # → 改双相对判据，任一成立则检验无意义：
        #   a) 残差仅为浮点舍入水平（rms ≤ 16·eps·y_rms，完美拟合属此类）；
        #   b) resid_sq 相对变异可忽略（ess+rss ≤ 1e-12·n·mean(resid_sq)²）
        # 微尺度真实数据的 LM 为量纲无关比值，可正常计算
        _resid_rms = float(np.sqrt(np.mean(resid_sq)))
        _y_rms = float(np.sqrt(np.mean(np.asarray(model.model.endog, dtype=float) ** 2)))
        if _y_rms > 0 and _resid_rms <= 16 * float(np.finfo(float).eps) * _y_rms:
            return None, None
        if ess + rss <= 1e-12 * n * float(np.mean(resid_sq)) ** 2:
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
        # 共线设计矩阵的秩亏告警：退化处理走下方 R²/系数守卫，静默第三方英文告警
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SingularMatrixWarning)
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
        ax1.set_title("残差 vs 拟合值", fontsize=10)

        # 2. Q-Q Plot
        ax2 = fig_res.add_subplot(2, 3, 2)
        sp_stats.probplot(residuals, dist="norm", plot=ax2)
        ax2.set_xlabel("理论分位数", fontsize=9)
        ax2.set_ylabel("样本分位数", fontsize=9)
        ax2.set_title("Q-Q 图（残差正态性）", fontsize=10)

        # 3. Scale-Location (sqrt|resid| vs fitted)
        ax3 = fig_res.add_subplot(2, 3, 3)
        sqrt_abs_resid = np.sqrt(np.abs(residuals))
        ax3.scatter(fitted, sqrt_abs_resid, alpha=0.6, s=20, color=PALETTE["data"]["primary"])
        ax3.set_xlabel("拟合值", fontsize=9)
        ax3.set_ylabel("√|残差|", fontsize=9)
        ax3.set_title("尺度-位置图", fontsize=10)

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
            ax4.set_title("Cook 距离（影响点诊断）", fontsize=10)
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
            ax4.set_title("Cook 距离（不可用）", fontsize=10)

        # 5. Residual vs Leverage
        ax5 = fig_res.add_subplot(2, 3, 5)
        if influence is not None:
            leverage = influence.hat_matrix_diag
            ax5.scatter(leverage, residuals, alpha=0.6, s=20, color=PALETTE["data"]["primary"])
            ax5.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
            ax5.set_xlabel("杠杆值", fontsize=9)
            ax5.set_ylabel("残差", fontsize=9)
            ax5.set_title("残差 vs 杠杆值", fontsize=10)
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
            ax5.set_title("残差 vs 杠杆值（不可用）", fontsize=10)

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
        ax6.set_title(f"实际值 vs 预测值 (R²={model.rsquared:.3f})", fontsize=10)
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
                "std_betas": {col: beta for col, beta in zip(X.columns, std_betas, strict=True)},
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
    if np.unique(y).size <= 1:
        return AnalysisResult(
            task="lasso_regression",
            status="error",
            messages=["目标列为常量列，无法进行 Lasso/ElasticNet 回归"],
        )
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
    # 审查 2026-09-06 R4-1：绝对阈值 1e-6 误判微尺度数据（y~1e-10 → 系数~1e-9 整表
    # 误标「否」，与 R²=0.99 矛盾）。系数带 y 量纲（模型拟合于 X_scaled、y 未标准化），
    # 与 2026-09-05 B1/B3 同族改为相对判据：相对最大系数幅值取 1e-6；
    # 全零模型（Lasso 全压缩）时 max=0 → 阈值 0，全「否」保持本义。
    _coef_scale = float(np.max(np.abs(coefs)))
    nonzero = np.abs(coefs) > 1e-6 * _coef_scale
    n_selected = int(np.count_nonzero(nonzero))
    r2 = float(model.score(X_scaled, y))

    # 收敛性检查：max_iter 用尽且未收敛时警告用户
    convergence_warning = ""
    if hasattr(model, "n_iter_"):
        n_iter_actual = int(np.max(np.asarray(model.n_iter_)))
        if n_iter_actual >= _lasso_max_iter:
            convergence_warning = (
                "⚠ Lasso 模型在最大迭代次数内未收敛，系数可能不准确，建议增大 max_iter 或调整 alpha"
            )

    coef_df = pd.DataFrame(
        {
            "变量": cols + ["(截距)"],
            "标准化系数": list(coefs) + [float(model.intercept_)],
            "选中": ["是" if m else "否" for m in nonzero] + ["—"],
        }
    ).sort_values("标准化系数", key=abs, ascending=False)

    # 可视化
    fig = Figure(figsize=(7, 4))
    ax = fig.add_subplot(111)
    ax.set_axisbelow(True)
    nonzero_coefs = coef_df[coef_df["选中"] == "是"].copy()
    if len(nonzero_coefs) > 0:
        colors = [
            PALETTE["target"]["primary"] if v < 0 else PALETTE["data"]["primary"]
            for v in nonzero_coefs["标准化系数"]
        ]
        ax.barh(nonzero_coefs["变量"], nonzero_coefs["标准化系数"], color=colors, height=0.5)
        # 数值标注：负值柱的标签放在柱体内部，避免与 Y 轴刻度文字重叠
        for y_i, v in enumerate(nonzero_coefs["标准化系数"]):
            ax.annotate(
                f"{v:+.4f}",
                xy=(v, y_i),
                xytext=(5 if v < 0 else 4, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=8,
                color="white" if v < 0 else "black",
                fontweight="bold" if v < 0 else "normal",
            )
        vmin = float(nonzero_coefs["标准化系数"].min())
        vmax = float(nonzero_coefs["标准化系数"].max())
        pad = max((vmax - vmin) * 0.2, 1e-12)
        ax.set_xlim(min(vmin, 0.0) - pad, max(vmax, 0.0) + pad)
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
        if np.unique(y).size <= 1:
            return AnalysisResult(
                task="robust_regression",
                status="error",
                messages=["目标列为常量列，无法进行 Huber 稳健回归"],
            )
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
                + [h - o for h, o in zip(huber.coef_, ols_model.params[1:], strict=True)],
            }
        )

        # 识别差异大的变量（OLS 受异常值影响严重）
        max_diff_idx = np.argmax(np.abs(coef_df["差异"].values[1:])) + 1
        outlier_sensitive = coef_df.iloc[max_diff_idx]["变量"] if len(coef_df) > 1 else None

        # 截距与斜率量级悬殊时同轴柱状图会退化为"只有一侧有柱"，拆成两个面板
        huber_vals = coef_df["Huber系数"].values
        ols_vals = coef_df["OLS系数"].values
        inter_mag = abs(float(huber_vals[0]))
        slope_mag = float(np.max(np.abs(huber_vals[1:]))) if len(cols) > 0 else 0.0
        split_panels = len(cols) >= 1 and slope_mag > 0 and inter_mag > 10 * slope_mag

        fig = Figure(figsize=(9.5, 4.2) if split_panels else (8, 4.5))
        if split_panels:
            # 左：截距项
            ax_i = fig.add_subplot(1, 2, 1)
            ax_i.bar(
                [0, 1],
                [huber_vals[0], ols_vals[0]],
                width=0.6,
                color=[PALETTE["data"]["primary"], PALETTE["data"]["secondary"]],
            )
            ax_i.set_xticks([0, 1])
            ax_i.set_xticklabels(["Huber 稳健", "OLS"], fontsize=9)
            ax_i.set_title("截距项", fontsize=10)
            ax_i.set_ylabel("系数", fontsize=10)
            ax_i.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
            for xi, v in enumerate([huber_vals[0], ols_vals[0]]):
                ax_i.annotate(
                    f"{v:.4f}",
                    xy=(xi, v),
                    xytext=(0, 4 if v >= 0 else -12),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
            # 右：斜率项（独立量纲，同轴内对比 Huber/OLS）
            ax = fig.add_subplot(1, 2, 2)
            slope_df = coef_df.iloc[1:]
            x_pos = np.arange(len(slope_df))
            width = 0.35
            ax.bar(
                x_pos - width / 2,
                slope_df["Huber系数"],
                width,
                color=PALETTE["data"]["primary"],
            )
            ax.bar(
                x_pos + width / 2,
                slope_df["OLS系数"],
                width,
                color=PALETTE["data"]["secondary"],
                alpha=0.7,
            )
            ax.set_xticks(x_pos)
            ax.set_xticklabels(slope_df["变量"], rotation=20, ha="right", fontsize=8)
            ax.set_title("斜率项", fontsize=10)
            ax.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
            ax.margins(y=0.35)
            # 单类别时图例会盖住柱体，直接在基线上方标注系列名与数值
            # 审查 2026-09-19 C-2：循环变量不得复用上方面板的 `xi`（int/numpy 整数
            # 类型冲突使 mypy 门禁红），改名 xpos_i
            for xpos_i, hv, ov in zip(
                x_pos, slope_df["Huber系数"], slope_df["OLS系数"], strict=True
            ):
                ax.annotate(
                    f"Huber {hv:.4f}",
                    xy=(xpos_i - width / 2, 0.0),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=PALETTE["data"]["primary"],
                )
                ax.annotate(
                    f"OLS {ov:.4f}",
                    xy=(xpos_i + width / 2, 0.0),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=PALETTE["data"]["secondary"],
                )
        else:
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
            ax.legend(fontsize=8)
        if split_panels:
            fig.suptitle("Huber 稳健回归 vs OLS（截距/斜率分栏）", fontsize=11)
        else:
            ax.set_title("Huber 稳健回归 vs OLS", fontsize=11)
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
        if y.nunique() <= 1:
            return AnalysisResult(
                task="quantile_regression",
                status="error",
                messages=["目标列为常量列，无法进行分位数回归"],
            )
        Xc = sm.add_constant(X_df)
        model = sm.QuantReg(y, Xc).fit(q=quantile)

        coef_df = pd.DataFrame(
            {
                "变量": Xc.columns,
                "系数": round_for_display(np.asarray(model.params)),
                "标准误": round_for_display(np.asarray(model.bse)),
                "t值": round_for_display(np.asarray(model.tvalues), 3),
                "p值": round_for_display(np.asarray(model.pvalues)),
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
