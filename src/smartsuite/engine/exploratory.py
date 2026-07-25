"""探索性分析模块：箱线图、散点图、中位数 CI、Bootstrap CI。"""
import logging
import re

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from sklearn.linear_model import LinearRegression

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import _adjust_xlabels

logger = logging.getLogger(__name__)

def median_ci(req: AnalysisRequest) -> AnalysisResult:
    """中位数置信区间 — 基于二项分布符号检验的非参数方法。

    不依赖任何分布假设，适用于偏态或未知分布数据。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 5:
        return AnalysisResult(task="median_ci", status="error",
            messages=["有效数据不足(至少5个点)"])

    ci_level = req.params.get("ci_level", 0.95)
    alpha = 1 - ci_level


    sorted_data = np.sort(data.values)
    # 二项分布法：找到最小的 k 使得 P(k ≤ B ≤ n-k) ≥ ci_level
    k = 0
    for i in range(n // 2 + 1):
        prob = sp_stats.binom.cdf(i, n, 0.5)
        if prob <= alpha / 2:
            k = i
    lower = float(sorted_data[k]) if k < n else float(sorted_data[0])
    upper = float(sorted_data[n - k - 1]) if n - k - 1 >= 0 else float(sorted_data[-1])
    median = float(np.median(data))

    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    ax.hist(data, bins=min(30, int(np.sqrt(n))*2), color=PALETTE["data"]["secondary"],
            edgecolor="white", alpha=0.7)
    ax.axvline(median, color=PALETTE["center"]["primary"], linewidth=2, label=f"中位数={median:.4f}")
    ax.axvline(lower, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5)
    ax.axvline(upper, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5,
               label=f"{ci_level*100:.0f}% CI: [{lower:.4f}, {upper:.4f}]")
    ax.axvspan(lower, upper, alpha=0.1, color=PALETTE["anomaly"]["primary"])
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("频数", fontsize=10)
    ax.set_title(f"中位数 {ci_level*100:.0f}% CI — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    return AnalysisResult(
        task="median_ci",
        tables={"median_ci": pd.DataFrame({
            "指标": ["中位数", "CI下限", "CI上限", "置信水平", "样本量", "方法"],
            "值": [f"{median:.4f}", f"{lower:.4f}", f"{upper:.4f}",
                  f"{ci_level:.0%}", str(n), "二项分布符号检验"],
        })},
        figures=[fig],
        summary=f"中位数={median:.4f}, {ci_level*100:.0f}% CI: [{lower:.4f}, {upper:.4f}]",
        metadata={"median": median, "ci_lower": lower, "ci_upper": upper,
                  "ci_level": ci_level, "n": n},
    )


def bootstrap_ci(req: AnalysisRequest) -> AnalysisResult:
    """Bootstrap 置信区间 — 不依赖正态假设的稳健区间估计。

    参数:
        statistic: "mean" (默认) | "median" | "std"
        n_bootstrap: 重抽样次数 (默认 2000)
        ci_level: 置信水平 (默认 0.95)

    返回百分位法（Percentile）Bootstrap 置信区间。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 5:
        return AnalysisResult(
            task="bootstrap_ci", status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    statistic = req.params.get("statistic", "mean")
    n_boot_raw = req.params.get("n_bootstrap", 2000)
    try:
        n_boot = max(100, min(int(n_boot_raw), 10000))
    except (ValueError, TypeError):
        n_boot = 2000
    ci_level = req.params.get("ci_level", 0.95)
    alpha = 1 - ci_level
    random_state = req.params.get("random_state", 42)

    rng = np.random.RandomState(random_state)
    values = data.values

    # 原始估计
    if statistic == "median":
        orig_stat = float(np.median(values))
        def stat_fn(x):
            return np.median(x)
    elif statistic == "std":
        orig_stat = float(np.std(values, ddof=1))
        def stat_fn(x):
            return np.std(x, ddof=1)
    else:  # mean
        orig_stat = float(np.mean(values))
        def stat_fn(x):
            return np.mean(x)

    # Bootstrap
    boot_stats = np.zeros(n_boot)
    for i in range(n_boot):
        sample = rng.choice(values, size=n, replace=True)
        boot_stats[i] = stat_fn(sample)

    # 百分位法 CI
    ci_lower_pct = float(np.percentile(boot_stats, alpha / 2 * 100))
    ci_upper_pct = float(np.percentile(boot_stats, (1 - alpha / 2) * 100))

    # 百分位法 CI（最常用的 Bootstrap CI 方法）
    # 可视化：Bootstrap 分布 + CI
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot(111)
    ax.hist(boot_stats, bins=40, color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.8, density=True)
    ax.axvline(orig_stat, color=PALETTE["center"]["primary"], linewidth=2, label=f"点估计={orig_stat:.4f}")
    ax.axvline(ci_lower_pct, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5,
               label=f"{ci_level*100:.0f}% CI下限={ci_lower_pct:.4f}")
    ax.axvline(ci_upper_pct, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5,
               label=f"{ci_level*100:.0f}% CI上限={ci_upper_pct:.4f}")
    ax.axvspan(ci_lower_pct, ci_upper_pct, alpha=0.1, color=PALETTE["anomaly"]["primary"])
    ax.set_xlabel(f"{statistic} ({req.target_col})", fontsize=10)
    ax.set_ylabel("Bootstrap 密度", fontsize=10)
    ax.set_title(
        f"Bootstrap {statistic.upper()} CI — {req.target_col} "
        f"({ci_level*100:.0f}%, {n_boot}次重抽样, n={n})",
        fontsize=10,
    )
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    ci_width = ci_upper_pct - ci_lower_pct
    summary = (
        f"{statistic} = {orig_stat:.4f}, "
        f"{ci_level*100:.0f}% Bootstrap CI: "
        f"[{ci_lower_pct:.4f}, {ci_upper_pct:.4f}] (宽度={ci_width:.4f})"
    )

    return AnalysisResult(
        task="bootstrap_ci",
        tables={
            "bootstrap_ci": pd.DataFrame({
                "统计量": [statistic, "点估计", f"CI下限 ({ci_level*100:.0f}%)",
                        f"CI上限 ({ci_level*100:.0f}%)", "CI宽度",
                        "重抽样次数", "样本量"],
                "值": [statistic, f"{orig_stat:.4f}", f"{ci_lower_pct:.4f}",
                      f"{ci_upper_pct:.4f}", f"{ci_width:.4f}",
                      str(n_boot), str(n)],
            }),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "statistic": statistic, "point_estimate": orig_stat,
            "ci_lower": ci_lower_pct, "ci_upper": ci_upper_pct,
            "ci_level": ci_level, "n_bootstrap": n_boot,
            "n": n,
        },
    )


def box_chart(req: AnalysisRequest) -> AnalysisResult:
    """分组箱线图 — 按类别因子分组展示分布，支持嵌套和分面两种次分类模式。

    target_col: 数值型 Y 列
    feature_cols[0]: 主分类列
    feature_cols[1] (可选): 次分类列
    params:
        mode: "facet"(默认,分面) | "nested"(嵌套,组合标签如 ABS/否)
        usl/lsl: 规格上限/下限 (红色实线)
        ucl/lcl/cl: 控制上限/下限/中心线 (黄色虚线)
        target: 目标值 (灰色点线)
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(task="box_chart", status="error",
            messages=["需要至少 1 个分类列作为分组依据"])

    group_col = req.feature_cols[0]
    sub_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None
    mode = req.params.get("mode", "facet")  # "facet" | "nested"

    # ── 规格限与控制限（可选参考线）──
    def _draw_ref_lines(ax):
        """在箱线图上叠加规格限/控制限参考线。"""
        for val, color, style, label in _ref_lines:
            ax.axhline(val, color=color, linestyle=style, linewidth=1.0,
                      alpha=0.8, label=label)
        if _ref_lines:
            ax.legend(fontsize=7.5, loc="upper right")

    _ref_lines: list[tuple[float, str, str, str]] = []
    for key, color, style in [
        ("usl", PALETTE["anomaly"]["primary"], "-"),
        ("lsl", PALETTE["anomaly"]["primary"], "-"),
        ("ucl", PALETTE["control"]["primary"], "--"),
        ("lcl", PALETTE["control"]["primary"], "--"),
        ("cl",  PALETTE["control"]["primary"], "--"),
    ]:
        val = req.params.get(key)
        if val is not None:
            try:
                _ref_lines.append((float(val), color, style, key.upper()))
            except (ValueError, TypeError):
                pass
    target_val = req.params.get("target")
    if target_val is not None:
        try:
            _ref_lines.append((float(target_val), PALETTE["direction"]["zero"],
                              ":", "Target"))
        except (ValueError, TypeError):
            pass

    sub = req.data[[req.target_col, group_col] + ([sub_col] if sub_col else [])].dropna()
    if len(sub) < 5:
        return AnalysisResult(task="box_chart", status="error",
            messages=["有效数据不足(至少5个点)"])

    # ── 嵌套模式: 创建组合分组列 ──
    nested_label = None
    if mode == "nested" and sub_col:
        sub = sub.copy()
        nested_label = f"{group_col} × {sub_col}"
        sub[nested_label] = sub[group_col].astype(str) + "/" + sub[sub_col].astype(str)
        group_col = nested_label
        sub_col = None  # 嵌套模式不用分面

    groups = sorted(sub[group_col].unique(), key=str)
    if len(groups) < 2:
        return AnalysisResult(task="box_chart", status="error",
            messages=["分组列需要至少 2 个不同值"])
    if len(groups) > 30:
        return AnalysisResult(task="box_chart", status="error",
            messages=[f"分组过多({len(groups)}个)，最多支持 30 个分组"])

    # ── 前端筛选支持 ──
    all_groups = list(groups)  # 保存完整列表用于 metadata
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        groups = [g for g in groups if str(g) in filter_set]
        if not groups:
            groups = all_groups  # 全空则回退

    # ── 描述统计 ──
    stat_rows = []
    for g in groups:
        gdata = sub[sub[group_col] == g][req.target_col]
        stat_rows.append({
            "分组": str(g),
            "样本量": len(gdata),
            "均值": round(float(gdata.mean()), 3),
            "中位数": round(float(gdata.median()), 3),
            "标准差": round(float(gdata.std(ddof=1)), 3),
            "IQR": round(float(gdata.quantile(0.75) - gdata.quantile(0.25)), 3),
            "最小值": round(float(gdata.min()), 3),
            "最大值": round(float(gdata.max()), 3),
        })

    # ── ANOVA + Kruskal-Wallis (3+组) / t检验 + MWU (2组) ──
    group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
    test_note = ""
    if len(groups) >= 3:
        try:
            _, anova_p = sp_stats.f_oneway(*group_data)
            _, kw_p = sp_stats.kruskal(*group_data)
            test_note = f"ANOVA p={anova_p:.4f}, Kruskal-Wallis p={kw_p:.4f}"
        except (ValueError, RuntimeError):
            logger.debug("ANOVA/Kruskal-Wallis test failed in box_chart", exc_info=True)
    else:
        try:
            _, t_p = sp_stats.ttest_ind(*group_data)
            _, mw_p = sp_stats.mannwhitneyu(*group_data)
            test_note = f"t检验 p={t_p:.4f}, MWU p={mw_p:.4f}"
        except (ValueError, RuntimeError):
            logger.debug("t-test/Mann-Whitney test failed in box_chart", exc_info=True)

    # ── 箱线图 ──
    has_sub = sub_col and sub[sub_col].nunique() >= 2 and sub[sub_col].nunique() <= 8
    if has_sub:
        sub_groups = sorted(sub[sub_col].unique(), key=str)
        n_cols = min(len(sub_groups), 4)
        n_rows = (len(sub_groups) + n_cols - 1) // n_cols
        fig = Figure(figsize=(n_cols * 4, n_rows * 4))
        for si, sg in enumerate(sub_groups):
            ax = fig.add_subplot(n_rows, n_cols, si + 1)
            sg_data = sub[sub[sub_col] == sg]
            sg_groups = [sg_data[sg_data[group_col] == g][req.target_col].values
                        for g in groups
                        if len(sg_data[sg_data[group_col] == g]) > 0]
            valid_groups = [g for g in groups
                          if len(sg_data[sg_data[group_col] == g]) > 0]
            if len(valid_groups) >= 2:
                bp = ax.boxplot(sg_groups, tick_labels=valid_groups,
                               patch_artist=True, widths=0.5)
                cmap = cm.tab10
                for pi, patch in enumerate(bp['boxes']):
                    patch.set_facecolor(cmap(pi % 10))
                for i, gdata in enumerate(sg_groups, 1):
                    jitter = np.random.uniform(-0.12, 0.12, len(gdata))
                    ax.scatter(np.full(len(gdata), i)+jitter, gdata,
                             alpha=0.3, s=8, color=PALETTE["misc"]["grid"], zorder=3)
            ax.set_title(f"{sub_col}={sg} (n={len(sg_data)})", fontsize=9)
            ax.set_xlabel(group_col, fontsize=8)
            ax.set_ylabel(req.target_col, fontsize=8)
            n_valid = len(valid_groups)
            _adjust_xlabels(ax, n_valid, fig)
            _draw_ref_lines(ax)
    else:
        fig = Figure(figsize=(max(len(groups)*1.2, 6), 5))
        ax = fig.add_subplot(111)
        bp = ax.boxplot(group_data,
                       tick_labels=[f"{g}\n(n={len(d)})"
                                   for g, d in zip(groups, group_data, strict=False)],
                       patch_artist=True, widths=0.5)
        cmap = cm.tab10
        for pi, patch in enumerate(bp['boxes']):
            patch.set_facecolor(cmap(pi % 10))
        for i, gdata in enumerate(group_data, 1):
            jitter = np.random.uniform(-0.12, 0.12, len(gdata))
            ax.scatter(np.full(len(gdata), i)+jitter, gdata,
                     alpha=0.3, s=10, color=PALETTE["misc"]["grid"], zorder=3)
        ax.set_xlabel(group_col, fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        title = f"分组箱线图 — {req.target_col} by {group_col}"
        if sub_col and not has_sub:
            title += f" (次分类「{sub_col}」水平过多，未分面)"
        ax.set_title(title, fontsize=11)
        _adjust_xlabels(ax, len(groups), fig)
        _draw_ref_lines(ax)
    fig.tight_layout()

    n_total = sum(s["样本量"] for s in stat_rows)  # 按实际显示的分组汇总
    # 统计检验结论 — 明确告知组间是否存在显著差异
    conclusion = ""
    if test_note:
        # 从 test_note 中提取 p 值判断显著性 (α=0.05)
        p_vals = [float(m) for m in re.findall(r"p=([\d.eE+-]+)", test_note)]
        any_sig = any(p < 0.05 for p in p_vals)
        if any_sig:
            conclusion = "各组之间存在显著差异（p<0.05），建议进一步做多重比较确认差异来源。"
        else:
            conclusion = "各组之间未发现显著差异（p≥0.05），但建议结合效应量和业务经验综合判断。"
    summary = (
        f"{req.target_col} 按 {group_col} 分组 (共 {len(groups)} 组, n={n_total})。"
        + (f" {test_note}。" if test_note else "")
        + (f" {conclusion}" if conclusion else "")
    )

    return AnalysisResult(
        task="box_chart",
        tables={"group_statistics": pd.DataFrame(stat_rows)},
        figures=[fig],
        summary=summary,
        metadata={
            "n_groups": len(groups), "n_total": n_total,
            "group_col": group_col, "sub_col": sub_col, "has_sub": has_sub,
            "mode": mode, "nested_label": nested_label,
            "groups": [str(g) for g in all_groups],
        },
    )


def scatter_plot(req: AnalysisRequest) -> AnalysisResult:
    """散点图 — X-Y 散点图，可选线性/LOWESS 拟合线与置信带，支持分组着色。

    参数 (params):
        fit: 拟合类型 — "none"(默认) | "linear"(OLS回归) | "lowess"(局部加权)
        show_ci: 是否显示 95% 置信带 (默认 true)
        group_col: 分组着色依据 (可选，不同值=不同颜色)

    数据要求:
        target_col: Y 轴数值列
        feature_cols[0]: X 轴数值列
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(
            task="scatter_plot", status="error",
            messages=["需要至少 1 个 X 轴数值列"],
        )

    x_col = req.feature_cols[0]
    y_col = req.target_col

    # ── 提取有效数据 ──
    cols_needed = [y_col, x_col]
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in req.data.columns)
    if has_groups:
        cols_needed.append(group_col)

    sub = req.data[cols_needed].dropna()
    if len(sub) < 3:
        return AnalysisResult(
            task="scatter_plot", status="error",
            messages=[f"有效数据不足(至少3个点, 当前{len(sub)}个)"],
        )

    # ── 参数提取 ──
    fit_type = req.params.get("fit", "none")
    show_ci = req.params.get("show_ci", True)
    if isinstance(show_ci, str):
        show_ci = show_ci.lower() not in ("false", "0", "no", "")

    # ── 分组信息 ──
    if has_groups:
        group_vals = sub[group_col]
        group_names = sorted(group_vals.dropna().unique())
        # 支持前端筛选
        filter_groups = req.params.get("filter_groups")
        if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
            filter_set = set(str(f) for f in filter_groups)
            group_names = [g for g in group_names if str(g) in filter_set]
            if not group_names:
                group_names = sorted(group_vals.dropna().unique())
    else:
        group_vals = pd.Series("_default", index=sub.index)
        group_names = ["_default"]

    # ── 图表渲染 ──
    fig = Figure(figsize=(10, 7))
    ax = fig.add_subplot(111)

    group_colors = {}
    # 使用 tab20 支持最多 20 个分组（超过后循环），比 tab10 提供更好的区分度
    for gi, gname in enumerate(group_names):
        group_colors[gname] = cm.tab20(gi % 20)

    # ── 按分组绘制散点 ──
    all_x_for_fit = []
    all_y_for_fit = []
    for gname in group_names:
        mask = group_vals == gname if has_groups else pd.Series(True, index=sub.index)
        gx = sub.loc[mask, x_col].values
        gy = sub.loc[mask, y_col].values
        if len(gx) == 0:
            continue
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        ax.scatter(gx, gy, s=25, color=color, alpha=0.65, edgecolors="white",
                   linewidth=0.3, label=label, zorder=3)
        all_x_for_fit.extend(gx.tolist())
        all_y_for_fit.extend(gy.tolist())

    x_all = np.array(all_x_for_fit)
    y_all = np.array(all_y_for_fit)

    # ── 拟合线 ──
    r_squared = None
    eq_text = ""
    if fit_type == "linear" and len(x_all) >= 3:
        # OLS 线性回归
        X_mat = x_all.reshape(-1, 1)
        model = LinearRegression().fit(X_mat, y_all)
        y_pred_all = model.predict(X_mat)
        slope = float(model.coef_[0])
        intercept = float(model.intercept_)
        r_squared = float(model.score(X_mat, y_all))

        # 排序后的 x 用于绘制平滑拟合线
        x_sorted = np.linspace(x_all.min(), x_all.max(), 200)
        y_fit = model.predict(x_sorted.reshape(-1, 1))

        ax.plot(x_sorted, y_fit, "-", color=PALETTE["anomaly"]["primary"],
                linewidth=2, alpha=0.85, zorder=5,
                label=f"OLS (R²={r_squared:.3f})")

        # 置信带
        if show_ci and len(x_all) > 2:
            n = len(x_all)
            x_mean = float(np.mean(x_all))
            ssx = float(np.sum((x_all - x_mean) ** 2))
            if ssx < 1e-15:
                # X 列为常量，拟合线为水平线，置信带退化（无意义）
                pass
            else:
                resid_se = float(np.sqrt(np.sum((y_all - y_pred_all) ** 2) / max(n - 2, 1)))
                t_crit = float(sp_stats.t.ppf(0.975, max(n - 2, 1)))
                se_fit = resid_se * np.sqrt(1 / n + (x_sorted - x_mean) ** 2 / ssx)
                ci_upper = y_fit + t_crit * se_fit
                ci_lower = y_fit - t_crit * se_fit
                ax.fill_between(x_sorted, ci_lower, ci_upper,
                               color=PALETTE["anomaly"]["primary"], alpha=0.08, zorder=1,
                               label="95% 置信带")

        slope_sign = "+" if slope >= 0 else ""
        eq_text = f"y = {intercept:.4f} {slope_sign} {slope:.4f}x"

    elif fit_type == "lowess" and len(x_all) >= 5:
        # LOWESS (局部加权散点平滑)
        try:
            from statsmodels.nonparametric.smoothers_lowess import lowess
        except ImportError:
            logger.info("statsmodels 未安装，LOWESS 拟合不可用。"
                        "安装: pip install statsmodels")
        else:
            try:
                lowess_result = lowess(y_all, x_all, frac=0.5, return_sorted=True)
                ax.plot(lowess_result[:, 0], lowess_result[:, 1], "-",
                        color=PALETTE["anomaly"]["primary"], linewidth=2, alpha=0.85, zorder=5,
                        label="LOWESS (frac=0.5)")
                # 计算伪 R²
                y_lowess_interp = np.interp(x_all, lowess_result[:, 0], lowess_result[:, 1])
                ss_res = np.sum((y_all - y_lowess_interp) ** 2)
                ss_tot = np.sum((y_all - np.mean(y_all)) ** 2)
                r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
            except (ValueError, np.linalg.LinAlgError, RuntimeError):
                logger.debug("LOWESS fit failed in scatter_plot", exc_info=True)

    # ── 标签与标题 ──
    ax.set_xlabel(x_col, fontsize=10)
    ax.set_ylabel(y_col, fontsize=10)
    title = f"散点图 — {y_col} vs {x_col}"
    if eq_text:
        title += f"\n{eq_text}"
    ax.set_title(title, fontsize=11)
    if has_groups or fit_type != "none":
        ax.legend(fontsize=8, loc="best")

    fig.tight_layout()

    # ── 汇总 ──
    n_points = len(x_all)  # 仅统计实际绘制的点（含筛选后分组）
    parts = [f"{y_col} vs {x_col} (n={n_points})"]
    if has_groups:
        parts.append(f"，{len(group_names)} 个分组")
    if r_squared is not None:
        parts.append(f"，R²={r_squared:.4f}")
    if fit_type == "linear":
        parts.append(f"，线性拟合: {eq_text}")
    elif fit_type == "lowess":
        parts.append("，LOWESS 平滑")

    return AnalysisResult(
        task="scatter_plot",
        figures=[fig],
        summary="".join(parts) + "。",
        metadata={
            "n_points": n_points, "x_col": x_col,
            "fit_type": fit_type, "r_squared": r_squared,
            "groups": [str(g) for g in group_names if g != "_default"],
        },
    )
