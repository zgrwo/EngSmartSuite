"""建模类：决策树特征重要性、VIF 共线性诊断。"""

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.figure import Figure
from sklearn.tree import DecisionTreeRegressor, plot_tree
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.sm_exceptions import SingularMatrixWarning

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    VIF_THRESHOLD,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine.root_cause._shared import _safe_int

logger = logging.getLogger(__name__)


def decision_tree_analysis(req: AnalysisRequest) -> AnalysisResult:
    """决策树特征重要性分析，含排列重要性和交叉验证。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="decision_tree", status="error", messages=["需要至少 1 个因子列"]
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 5:
        return AnalysisResult(
            task="decision_tree", status="error", messages=[f"有效样本({len(df)})不足"]
        )

    # 检查是否存在非数值列（DecisionTreeRegressor 不接受字符串/类别特征）
    non_num = [c for c in cols if not pd.api.types.is_numeric_dtype(df[c])]
    if non_num:
        return AnalysisResult(
            task="decision_tree",
            status="error",
            messages=[f"以下列包含非数值数据，请先进行 One-Hot 编码: {non_num}"],
        )
    X = df[cols]
    y = df[req.target_col]
    if y.nunique() <= 1:
        return AnalysisResult(
            task="decision_tree",
            status="error",
            messages=["目标列为常量列，决策树特征重要性无意义（避免假 R²=1）"],
        )
    # 审查 2026-08-19 #1.4：字符串 max_depth/random_state 会触发 sklearn
    # InvalidParameterError，此处安全转换
    max_depth = _safe_int(req.params.get("max_depth", 5), 5)
    random_state = _safe_int(req.params.get("random_state", 42), 42)
    # Round-2 #A2g：max_depth<=0 → sklearn ValueError → 通用错误
    if max_depth is not None and max_depth < 1:
        return AnalysisResult(
            task="decision_tree",
            status="error",
            messages=[f"max_depth 必须 ≥ 1，当前: {max_depth}"],
        )

    tree = DecisionTreeRegressor(max_depth=max_depth, random_state=random_state)
    tree.fit(X, y)

    # ── 内置特征重要性 ──
    fi_builtin = pd.DataFrame(
        {
            "因子": cols,
            "内置重要性": tree.feature_importances_,
        }
    )

    # ── 排列重要性 (更可靠，不受树结构偏差影响) ──
    from sklearn.inspection import permutation_importance

    try:
        perm_result = permutation_importance(
            tree, X, y, n_repeats=10, random_state=random_state, scoring="r2"
        )
        fi_perm = pd.DataFrame(
            {
                "因子": cols,
                "排列重要性": perm_result.importances_mean,
                "排列重要性_std": perm_result.importances_std,
            }
        )
    except Exception:
        logger.warning(
            "排列重要性计算失败（样本量可能不足），回退为内置重要性。"
            "排列重要性标准差已置零，解读时请注意。",
            exc_info=True,
        )
        fi_perm = pd.DataFrame(
            {
                "因子": cols,
                "排列重要性": tree.feature_importances_,
                "排列重要性_std": [0.0] * len(cols),
            }
        )

    # 合并两种重要性
    fi = fi_builtin.merge(fi_perm, on="因子")
    fi["综合重要性"] = fi["排列重要性"].clip(lower=0)
    fi = fi.sort_values("综合重要性", ascending=False).reset_index(drop=True)
    top = fi.iloc[0] if len(fi) > 0 else None

    # ── 交叉验证评估过拟合 ──
    from sklearn.model_selection import cross_val_score

    warn_msgs: list[str] = []
    cv_scores = []
    if len(df) >= 10:
        try:
            cv_scores = cross_val_score(tree, X, y, cv=min(5, len(df) // 3), scoring="r2")
            cv_r2 = float(np.mean(cv_scores))
            train_r2 = float(tree.score(X, y))
            if train_r2 - cv_r2 > 0.3:
                warn_msgs.append(
                    f"⚠ 过拟合警告: 训练R²={train_r2:.3f}, "
                    f"交叉验证R²={cv_r2:.3f} (差距={train_r2 - cv_r2:.2f})"
                )
        except Exception:
            logger.debug("交叉验证失败", exc_info=True)
            cv_r2 = None
    else:
        cv_r2 = None

    # ── 图1: 特征重要性对比柱状图 ──
    n_factors = len(fi)
    fig_imp = Figure(figsize=(max(n_factors * 0.8, 6), 4.5))
    # 只显示重要性>0的因子
    fi_plot = fi[fi["综合重要性"] > 0] if fi["综合重要性"].sum() > 0 else fi
    x = np.arange(len(fi_plot))
    width = 0.35
    ax = fig_imp.add_subplot(111)
    ax.barh(
        x + width / 2,
        fi_plot["内置重要性"],
        width,
        label="内置重要性 (Gini)",
        color=PALETTE["data"]["secondary"],
        alpha=0.8,
    )
    ax.barh(
        x - width / 2,
        fi_plot["排列重要性"],
        width,
        label="排列重要性 (±1σ)",
        color=PALETTE["data"]["primary"],
        alpha=0.9,
        xerr=fi_plot["排列重要性_std"] if "排列重要性_std" in fi_plot.columns else None,
        capsize=2,
    )
    ax.set_yticks(x)
    ax.set_yticklabels(fi_plot["因子"], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("重要性", fontsize=10)
    cv_note = f" | CV R²={cv_r2:.3f}" if cv_r2 is not None else ""
    ax.set_title(f"决策树特征重要性对比 — {req.target_col}{cv_note}", fontsize=11)
    ax.legend(fontsize=8, loc="lower right")
    fig_imp.tight_layout()

    # ── 图2: 决策树结构图 ──
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    # 只显示前 3 层：更深层节点框会相互重叠、文字截断（宽度随叶子数 2^d 增长）
    display_depth = min(3, tree.get_depth())
    n_leaves = 2**display_depth
    fig_tree = Figure(figsize=(max(14, n_leaves * 1.9), max(display_depth * 2.2, 4)))
    FigureCanvasAgg(fig_tree)  # plot_tree 需要 canvas renderer 初始化
    ax_tree = fig_tree.add_subplot(111)
    plot_tree(
        tree,
        ax=ax_tree,
        feature_names=cols,
        filled=True,
        rounded=True,
        fontsize=9,
        precision=2,
        impurity=False,
        max_depth=display_depth,
    )
    depth_note = (
        f"深度={tree.get_depth()}, 显示前 {display_depth} 层"
        if tree.get_depth() > display_depth
        else f"深度={tree.get_depth()}"
    )
    ax_tree.set_title(f"决策树结构 — {req.target_col} ({depth_note})", fontsize=12)
    fig_tree.tight_layout()

    # ── 汇总 ──
    cv_str = f"CV R²={cv_r2:.3f}" if cv_r2 is not None else "CV R²=N/A"
    summary = (
        (
            f"关键影响因子: {top['因子']} "
            f"(排列重要性={top['排列重要性']:.3f}, "
            f"内置重要性={top['内置重要性']:.3f})。{cv_str}"
        )
        if top is not None
        else f"分析完成。{cv_str}"
    )

    return AnalysisResult(
        task="decision_tree",
        tables={"feature_importance": fi},
        figures=[fig_imp, fig_tree],
        summary=summary,
        metadata={
            "top_factor": top["因子"] if top is not None else None,
            "cv_r2": cv_r2,
            "train_r2": float(tree.score(X, y)),
            "max_depth": max_depth,
            "n_samples": len(df),
        },
        messages=warn_msgs,
    )


def vif_analysis(req: AnalysisRequest) -> AnalysisResult:
    """方差膨胀因子 — 多元共线性诊断。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(task="vif", status="error", messages=["VIF 分析需要至少 2 个因子列"])

    df = req.data[cols].dropna()
    if len(df) < len(cols) + 2:
        return AnalysisResult(task="vif", status="error", messages=[f"有效样本({len(df)})不足"])

    # Round-2 #A2b：常量特征列使 add_constant 静默跳过截距 → VIF 算出有限伪值
    _const_feats = [c for c in cols if df[c].nunique(dropna=True) <= 1]
    if _const_feats:
        return AnalysisResult(
            task="vif",
            status="error",
            messages=[
                f"特征列「{_const_feats[0]}」为常量列（无变异），VIF 无法定义。"
                "请移除该列或检查数据。"
            ],
        )

    # 用户可通过 params 自定义阈值，fallback 到全局常量
    threshold = _safe_float(req.params.get("threshold", VIF_THRESHOLD), VIF_THRESHOLD)

    try:
        X = sm.add_constant(df)
        # 秩亏由本函数后续条件数告警（poorly conditioned）统一表达，此处静默 statsmodels 英文告警
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SingularMatrixWarning)
            vif_vals = [variance_inflation_factor(X.values, i) for i in range(X.shape[1])]
        vif_full = pd.DataFrame({"变量": X.columns, "VIF": vif_vals})
        # 排除无意义的 const 列
        vif_data = vif_full[vif_full["变量"] != "const"].copy()
        high_vif = vif_data[vif_data["VIF"] > threshold]
        # VIF < 1 在数学上不可能（VIF = 1/(1-R²) ≥ 1），异常值提示常量列或数值问题
        invalid_vif = vif_data[vif_data["VIF"] < 0.99]  # 允许浮点舍入误差 (~0.999…)
        vif_warnings = []
        if len(high_vif) > 0:
            vif_warnings.append(f"{len(high_vif)} 个变量 VIF>{threshold:g}，存在共线性风险")
        if len(invalid_vif) > 0:
            bad_cols = invalid_vif["变量"].tolist()
            vif_warnings.append(
                f"⚠ {len(invalid_vif)} 个变量 VIF<1 异常（{bad_cols}），"
                "可能为零方差常量列或数值计算误差，请检查数据"
            )
        warning = (
            "; ".join(vif_warnings)
            if vif_warnings
            else f"所有变量 VIF<={threshold:g}，无明显共线性"
        )

        # VIF 柱状图
        vif_plot = vif_data
        fig = Figure(figsize=(max(len(vif_plot) * 0.7, 5), 3.5))
        ax = fig.add_subplot(111)
        colors = [
            PALETTE["target"]["primary"] if v > threshold else PALETTE["data"]["primary"]
            for v in vif_plot["VIF"]
        ]
        ax.barh(vif_plot["变量"], vif_plot["VIF"], color=colors)
        # 自适应轴范围：VIF 远低于阈值时不把阈值线画进来（否则柱子被压缩成一条）
        vif_max = float(vif_plot["VIF"].max()) if len(vif_plot) else 1.0
        xmax = vif_max * 1.08 if vif_max >= threshold else max(vif_max * 1.25, 1.05)
        ax.set_xlim(0, xmax)
        if threshold <= xmax:
            ax.axvline(
                threshold,
                color=PALETTE["anomaly"]["primary"],
                linestyle="--",
                linewidth=1,
                label=f"VIF={threshold:g} 阈值",
            )
            ax.legend(fontsize=8, loc="lower right")
        else:
            ax.annotate(
                f"VIF={threshold:g} 阈值（当前全部未触及）",
                xy=(xmax, 0.5),
                xycoords=("data", "axes fraction"),
                xytext=(-4, 0),
                textcoords="offset points",
                ha="right",
                va="center",
                fontsize=8,
                color=PALETTE["anomaly"]["primary"],
            )
        ax.set_xlabel("VIF", fontsize=9)
        ax.set_title("共线性诊断 — VIF", fontsize=11)
        fig.tight_layout()

        return AnalysisResult(
            task="vif",
            tables={"vif_table": vif_data},
            figures=[fig],
            summary=warning,
            metadata={"high_vif_count": len(high_vif), "invalid_vif_count": len(invalid_vif)},
        )
    except Exception:
        logger.debug("VIF 计算失败", exc_info=True)
        return AnalysisResult(
            task="vif",
            status="error",
            messages=["VIF 计算失败，请检查数据是否存在共线性或数值异常"],
        )
