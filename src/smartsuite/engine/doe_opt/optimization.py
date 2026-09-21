"""网格搜索与多目标优化。"""

import logging
import numbers

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import is_positive_finite

logger = logging.getLogger(__name__)


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
        elif not all(isinstance(v, numbers.Real) and not isinstance(v, bool) for v in _r):
            # numbers.Real（审查 2026-09-19 E12）：numpy 数值上下限不得被误拒；
            # bool 排除，否则 (True, False) 会被当作合法区间
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
            # 按预测值排序（最优在前），否则候选差异被 0 起点柱高掩盖
            order = np.argsort(predictions)
            if direction == "maximize":
                order = order[::-1]
            pred_sorted = predictions[order]
            x = np.arange(len(pred_sorted))
            bar_colors = [
                PALETTE["anomaly"]["primary"] if i == 0 else PALETTE["data"]["secondary"]
                for i in range(len(pred_sorted))
            ]
            ax.bar(x, pred_sorted, color=bar_colors)
            ax.set_xticks(x)
            ax.set_xticklabels([str(int(i)) for i in order], fontsize=8)
            span = float(pred_sorted.max() - pred_sorted.min())
            if span > 0:
                pad = span * 0.25
                ax.set_ylim(float(pred_sorted.min()) - pad, float(pred_sorted.max()) + pad)
            ax.annotate(
                f"最优 {pred_sorted[0]:.4f}",
                xy=(0, pred_sorted[0]),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color=PALETTE["anomaly"]["primary"],
            )
            ax.set_xlabel("参数组合索引（纵轴已放大显示候选间差异）", fontsize=10)
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
    """计算期望值（0-1 min-max 归一化，multi_objective 聚合口径见其 docstring）。

    审查 2026-09-16 C-3：极差带数据量纲，原 `vmax-vmin+EPSILON` 会把微尺度目标
    压到 ~0.001 甚至全 0 → 改精确零判据；无变异目标保持全 0（不影响加权排序）。
    """
    vmin, vmax = vals.min(), vals.max()
    span = float(vmax - vmin)
    if not np.isfinite(span) or span == 0:
        return np.zeros_like(np.asarray(vals, dtype=float))
    if direction == "maximize":
        return (vals - vmin) / span
    elif direction == "minimize":
        return (vmax - vals) / span
    else:
        raise ValueError(f"不支持的优化方向「{direction}」，请使用 'maximize' 或 'minimize'")


def multi_objective_opt(req: AnalysisRequest) -> AnalysisResult:
    """多目标优化 — 加权期望函数法。

    聚合口径（逐公式审计 2026-09-05 约定#5）：综合期望 D = Σ wᵢ·dᵢ（加权算术平均），
    其中 dᵢ 为各目标 min-max 归一化期望值（_desirability）。注意这与
    Derringer-Suich 经典加权几何平均 D = (∏ dᵢ^wᵢ)^(1/Σw) 不同——算术平均
    对单目标极值更宽容，权衡取舍可能与几何平均口径的排序不一致。
    """
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
    # 审查 2026-09-21 D-1（同族）：float("nan")/float("inf") 不抛异常，而
    # `weight_sum <= 0` 对 NaN 恒 False、对 +Inf 亦为 False → 权重和静默通过守卫，
    # 随后归一化除零 → 实测 status=ok 且 summary 输出「得分: nan」。
    if not all(np.isfinite(w) for w in weights) or not is_positive_finite(float(weight_sum)):
        return AnalysisResult(
            task="multi_objective",
            status="error",
            messages=[f"权重必须为有限数值且总和大于零，当前: {weights}"],
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
    for obj, w in zip(objectives, weights, strict=True):
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
    pareto_idx: np.ndarray = np.array([], dtype=int)

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
    # 最优在前（排名 1 在顶部）
    top_idx = np.argsort(score_valid)[::-1][:top_n]
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
    ax_score.set_yticks(range(top_n))
    ax_score.set_yticklabels([str(i) for i in range(1, top_n + 1)], fontsize=8)
    ax_score.set_xlabel("加权期望值", fontsize=9)
    ax_score.set_ylabel("排名", fontsize=9)
    ax_score.set_title(f"多目标优化 — Top{top_n} 方案分解", fontsize=10)
    # 图例移出坐标系，避免遮挡柱条
    ax_score.legend(
        fontsize=7.5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=min(len(objectives), 3),
        frameon=False,
    )

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
