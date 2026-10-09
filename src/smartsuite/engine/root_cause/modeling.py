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
from smartsuite.core.param_spec import Finite, Integer, Opt, Spec
from smartsuite.core.param_specs_common import RANDOM_STATE
from smartsuite.engine._constants import (
    VIF_THRESHOLD,
)
from smartsuite.engine._guard import (
    BoundaryIssue,
    BoundaryReport,
    clean_frame,
    degenerate_column_reason,
    first_degenerate_reason,
)
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)

# ── 声明式参数契约（P4 步骤③，第二十一轮起：共享字段库驱动）──
# 契约：docs/governance/improvement-plan.md §六
# 按**任务**登记（本模块含 decision_tree / vif / logistic_regression 等）。
PARAM_SPECS = {
    # 第二十二轮：`max_depth` ≥1（sklearn 对 ≤0 抛 ValueError，原先只做类型转换
    # 而无区间检查 —— 实际有检查，见迁移注释）；`random_state` 引用共享常量。
    "decision_tree": Spec(
        max_depth=Opt(
            Integer(min=1),
            default=5,
            label="最大深度",
            hint="决策树最大深度；至少 1（越大越容易过拟合）",
        ),
        random_state=RANDOM_STATE,
    ),
    # `threshold` 此前**完全没有校验**（实测：`'abc'` 静默回落默认值；
    # `inf` 使判定表全空且阈值参考线不显示；`-1` 把全部变量判为高 VIF）。
    # 三者都是"静默降级"，故 `gt=0` + 有限数值。
    "vif": Spec(
        threshold=Opt(
            Finite(gt=0),
            default=VIF_THRESHOLD,
            label="VIF 阈值",
            hint=f"VIF 超过该值判为存在共线性；默认 {VIF_THRESHOLD}",
        )
    ),
}


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
    # 审查 2026-09-22 发现 3：sklearn `tree.fit` 对 ±Inf 抛
    # ValueError('Input y contains infinity...')；入口按缺失剔除
    _numeric_cols = [c for c in [req.target_col] + cols if pd.api.types.is_numeric_dtype(df[c])]
    # 第三十六轮：手抄清洗改为 `_guard.clean_frame`（一处声明、一处执行）。
    # `n_inf` 仍取出 —— 下面的"不足"错误文案需要它（告知用户**为什么**样本变少了）。
    report = BoundaryReport()
    df, n_inf = clean_frame(df, _numeric_cols, report=report)
    if len(df) < 5:
        return AnalysisResult(
            task="decision_tree",
            status="error",
            messages=[f"剔除 {n_inf} 个非有限值后有效样本({len(df)})不足"],
        )
    X = df[cols]
    y = df[req.target_col]
    # 收尾轮（契约 #5）：判据与文案统一走 `_guard` 三级归因（原先手写 nunique 判据）
    _degenerate = degenerate_column_reason(y, what="目标列")
    if _degenerate is not None:
        return AnalysisResult(
            task="decision_tree",
            status="error",
            messages=[f"{_degenerate}，决策树特征重要性无意义（避免假 R²=1）"],
        )
    # 参数校验（P4 步骤③，第二十二轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 迁移前是 `_safe_int` 安全转换 + 一段 max_depth≥1 检查、random_state 无区间；
    # 现由 `Integer(min=1)` / `Integer(min=0)` 一次表达（并**拒绝小数**）。
    _dt = PARAM_SPECS["decision_tree"].validate_or_raise(req.params)
    max_depth = _dt.max_depth
    random_state = _dt.random_state

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

    # `n_inf` 的披露已由上面的 `clean_frame(report=...)` 记录 → 不再手写
    cv_scores = []
    if len(df) >= 10:
        try:
            cv_scores = cross_val_score(tree, X, y, cv=min(5, len(df) // 3), scoring="r2")
            cv_r2 = float(np.mean(cv_scores))
            train_r2 = float(tree.score(X, y))
            if train_r2 - cv_r2 > 0.3:
                report.add(
                    BoundaryIssue(
                        level="B3",
                        code="E_DECISION_TREE_OVERFIT_WARNING",
                        detail=(
                            f"⚠ 过拟合警告: 训练R²={train_r2:.3f}, "
                            f"交叉验证R²={cv_r2:.3f} (差距={train_r2 - cv_r2:.2f})"
                        ),
                    )
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
            "boundary_codes": report.codes(),
        },
        messages=report.messages(),
    )


def vif_analysis(req: AnalysisRequest) -> AnalysisResult:
    """方差膨胀因子 — 多元共线性诊断。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 2:
        return AnalysisResult(task="vif", status="error", messages=["VIF 分析需要至少 2 个因子列"])

    df = req.data[cols].dropna()
    # 审查 2026-10-09 R2BD-03（P1）：`dropna()` **不剔除 ±Inf**（Inf 不是 NaN），而
    # `variance_inflation_factor` 拿到含 Inf 的设计矩阵后发散/抛错 → 落进本函数末尾的
    # `except Exception`，用户看到「VIF 计算失败，请检查共线性」（**错误归因**）、
    # 数值表全丢、且 `messages` 里没有任何 ±Inf 披露。
    # 同文件 `decision_tree_analysis` 早已走 `_guard.clean_frame`（本条的修复范式）；
    # 本函数此前因"同文件已接 `_guard`"被文件级源码守卫整文件放行。
    report = BoundaryReport()
    df, n_inf = clean_frame(df, cols, report=report)
    if len(df) < len(cols) + 2:
        # 样本不足的**真实原因**可能就是刚被剔除的那批 ±Inf —— 必须点名，
        # 否则用户按"样本不足"去加数据，问题依旧（禁止错误归因）。
        reason = f"剔除 {n_inf} 行 ±Inf（非有限值）后" if n_inf else ""
        return AnalysisResult(
            task="vif", status="error", messages=[f"{reason}有效样本({len(df)})不足"]
        )

    # Round-2 #A2b：常量特征列使 add_constant 静默跳过截距 → VIF 算出有限伪值
    # 收尾轮（契约 #5）：判据与文案统一走 `_guard` 三级归因（原先手写 nunique 判据）
    _degenerate_feat = first_degenerate_reason(df, cols, label="特征列")
    if _degenerate_feat is not None:
        return AnalysisResult(
            task="vif",
            status="error",
            messages=[f"{_degenerate_feat}，VIF 无法定义。请移除该列或检查数据。"],
        )

    # 用户可通过 params 自定义阈值，fallback 到全局常量
    # 参数校验（P4 步骤③，第二十一轮）：失败时抛 ParamValidationError。
    # 迁移前此参数无校验（见 PARAM_SPECS 的说明）。
    threshold = PARAM_SPECS["vif"].validate_or_raise(req.params).threshold

    try:
        X = sm.add_constant(df)
        # 共线性由本函数的中文 summary（VIF>阈值 / 无穷大 VIF）统一表达，此处窄静默
        # statsmodels 的英文告警——跨版本两种形态，均需静默：
        #   ① statsmodels ≥0.15：variance_inflation_factor 自身对 cond(X)>1e4 发
        #      UserWarning("The design matrix is poorly conditioned ...")；
        #   ② statsmodels 0.14：内部 `1/(1-R²)` 在完全共线（R²==1）时除零，发 numpy
        #      RuntimeWarning。
        # 两者在项目 pytest 配置 `filterwarnings = error` 下都会升为异常，被外层
        # except 吞成「VIF 计算失败」，已算出的数值表全部丢失（2026-09-21 复审）。
        # 按消息窄静默、errstate 只管除零/无效，不吞掉其他告警。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SingularMatrixWarning)
            warnings.filterwarnings(
                "ignore",
                message="The design matrix is poorly conditioned",
                category=UserWarning,
            )
            with np.errstate(divide="ignore", invalid="ignore"):
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
        # 审查 2026-09-21 R1-4：inf 意味着**完全共线**（非仅仅「风险」），显式告知
        if not np.all(np.isfinite(vif_data["VIF"].to_numpy(dtype=float))):
            vif_warnings.append("⚠ 存在无穷大 VIF（变量完全共线），不可同时入模，请删除冗余变量")
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
        # 自适应轴范围：VIF 远低于阈值时不把阈值线画进来（否则柱子被压缩成一条）
        # 审查 2026-09-21 R1-4：statsmodels 在完全共线时可返回 inf（pyproject 允许
        # >=0.14）。两个陷阱：① inf*1.08 → set_xlim(0, inf) 让 matplotlib 抛错；
        # ② 直接把 inf 送入 barh，其内部变换发 RuntimeWarning（warnings-as-errors
        # 下同样中断）→ 两者都被外层 except Exception 吞成「VIF 计算失败」，
        # 已算出的 VIF 表全部丢失。处理：轴范围只按有限值定；inf 柱在**图上**
        # 截断绘制（数值表仍如实给出 inf）。
        values = vif_plot["VIF"].to_numpy(dtype=float)
        finite_vals = values[np.isfinite(values)]
        vif_max = float(finite_vals.max()) if finite_vals.size else 1.0
        if bool(np.any(~np.isfinite(values))):
            vif_max = max(vif_max, threshold)
        xmax = vif_max * 1.08 if vif_max >= threshold else max(vif_max * 1.25, 1.05)
        plot_values = np.where(np.isfinite(values), values, xmax)
        ax.barh(vif_plot["变量"], plot_values, color=colors)
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
            metadata={
                "high_vif_count": len(high_vif),
                "invalid_vif_count": len(invalid_vif),
                # 审查 2026-10-09 R2BD-03：入口清洗的处置必须机器可读（原为 `{}`）
                "boundary_codes": report.codes(),
            },
            messages=report.messages(),
        )
    except Exception:
        logger.debug("VIF 计算失败", exc_info=True)
        return AnalysisResult(
            task="vif",
            status="error",
            # 真失败也要先披露入口处置（否则"剔除了多少行 ±Inf"这条信息随异常一起丢失）
            messages=report.messages() + ["VIF 计算失败，请检查数据是否存在共线性或数值异常"],
        )
