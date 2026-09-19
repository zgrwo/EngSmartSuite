"""分类分析（ROC / 逻辑回归）。"""

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display

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
                    "阈值": round_for_display(thresholds_clean),
                    "FPR": round_for_display(fpr),
                    "TPR": round_for_display(tpr),
                    "Youden_J": round_for_display(tpr - fpr),
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
            "系数": round_for_display(params),
            "标准误": round_for_display(np.asarray(model.bse)),
            "z值": round_for_display(np.asarray(model.tvalues), 3),
            "p值": round_for_display(np.asarray(model.pvalues)),
            "OR (Odds Ratio)": round_for_display(or_vals, 3),
            "OR 95%CI下限": round_for_display(or_ci_lower, 3),
            "OR 95%CI上限": round_for_display(or_ci_upper, 3),
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
