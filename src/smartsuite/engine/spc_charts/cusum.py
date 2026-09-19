"""CUSUM 累积和控制图（cusum_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine.spc_charts._shared import _resolve_groups


def cusum_chart(req: AnalysisRequest) -> AnalysisResult:
    """CUSUM (累积和) 控制图 — 对小偏移 (±0.5σ~2σ) 比 X-bar 更敏感。

    参数:
        k: 参考值/松弛因子 (通常取 δ/2，其中 δ 是要检测的偏移量，以 σ 为单位)
        h: 决策区间 (通常取 4~5)
        mu: 过程均值 (如未提供，从数据估计；建议使用已知受控状态的 μ)
        sigma: 过程标准差 (如未提供，从数据估计；建议使用已知受控状态的 σ)
        group_col: 分组依据 (可选，不同值=不同颜色的线，共享坐标轴)
    """
    group_vals, group_names, has_groups, y_col, _all_groups_meta = _resolve_groups(req)

    # 公共参数 (cusum)
    k = req.params.get("k", 0.5)
    h = req.params.get("h", 5.0)
    try:
        k, h = float(k), float(h)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[f"参数 k/h 值无效: k={k}, h={h}，请输入数值"],
        )
    if k <= 0:
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[f"参数 k ({k}) 无效：参考值必须为正数，建议 k=0.5"],
        )
    if h <= 0:
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[f"参数 h ({h}) 无效：决策区间必须为正数，建议 h=4~5"],
        )

    user_mu = req.params.get("mu")
    user_sigma = req.params.get("sigma")
    if user_mu is not None and user_sigma is not None:
        try:
            user_mu, user_sigma = float(user_mu), float(user_sigma)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="spc_cusum",
                status="error",
                messages=[f"参数 mu/sigma 值无效: mu={user_mu}, sigma={user_sigma}，请输入数值"],
            )
        if not (np.isfinite(user_mu) and np.isfinite(user_sigma)):
            return AnalysisResult(
                task="spc_cusum",
                status="error",
                messages=["参数 mu/sigma 必须为有限数值（不允许 NaN/Inf）"],
            )
    # Round-2 #A2j：与 EWMA 一致——只传一个时此前静默忽略两个
    if (user_mu is None) != (user_sigma is None):
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=["mu/sigma 必须同时提供或同时省略（当前只提供了一个）"],
        )

    # 分组处理
    group_results = []
    all_group_names = []
    warn_msgs: list[str] = []
    max_n = 0
    skipped_zero_var: list[str] = []
    skipped_insufficient: list[str] = []
    for gname in group_names:
        mask = group_vals == gname if has_groups else pd.Series(True, index=req.data.index)
        gdata = req.data.loc[mask, y_col].dropna()
        if len(gdata) < 5:
            skipped_insufficient.append(str(gname))
            continue
        all_group_names.append(gname)
        max_n = max(max_n, len(gdata))

        if user_mu is not None and user_sigma is not None:
            mu, sigma = user_mu, user_sigma
        else:
            mu = float(gdata.mean())
            sigma = float(gdata.std(ddof=1))
        # 审查 2026-09-16 D-1：原 `sigma < EPSILON` 把微尺度分组误判零方差跳过；
        # 仅当 σ 精确为 0/非有限/非正（用户给定）时才跳过
        if not np.isfinite(sigma) or sigma <= 0:
            skipped_zero_var.append(str(gname))
            continue

        z = (gdata.values - mu) / sigma
        c_plus = np.zeros(len(z))
        c_minus = np.zeros(len(z))
        alarm_plus: list[int] = []
        alarm_minus: list[int] = []
        for i in range(len(z)):
            if i == 0:
                c_plus[i] = max(0, z[i] - k)
                c_minus[i] = max(0, -z[i] - k)
            else:
                c_plus[i] = max(0, c_plus[i - 1] + z[i] - k)
                c_minus[i] = max(0, c_minus[i - 1] - z[i] - k)
            if c_plus[i] > h:
                alarm_plus.append(i)
            if c_minus[i] > h:
                alarm_minus.append(i)

        group_results.append(
            {
                "name": gname,
                "data": gdata.values,
                "mu": mu,
                "sigma": sigma,
                "c_plus": c_plus,
                "c_minus": c_minus,
                "alarm_plus": alarm_plus,
                "alarm_minus": alarm_minus,
            }
        )

    # 汇总跳过警告（P1 fix: 区分零方差和数据不足）
    if skipped_zero_var:
        warn_msgs.append(
            f"⚠ 以下分组标准差为零（常量值），已跳过 CUSUM 计算: {', '.join(skipped_zero_var)}"
        )
    if skipped_insufficient:
        warn_msgs.append(
            f"⚠ 以下分组有效数据不足（<5 个点），已跳过: {', '.join(skipped_insufficient)}"
        )
    if len(group_results) < 1:
        if skipped_zero_var and not skipped_insufficient:
            detail = "所有分组标准差均为零（常量数据），无法计算 CUSUM"
        elif not skipped_zero_var and skipped_insufficient:
            detail = "所有分组有效数据不足（每组至少需要 5 个点）"
        else:
            detail = "无有效分组：部分分组标准差为零，部分数据不足"
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[detail] + warn_msgs,
        )

    # 图表
    fig = Figure(figsize=(12, 8 if has_groups else 6))
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212)

    group_colors = {}
    for gi, gname in enumerate(all_group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    total_alarms = 0
    if user_mu is None:
        warn_msgs.append("⚠ μ/σ 从各组数据独立估计。建议通过参数 mu/sigma 指定已知受控状态的参数。")

    for gr in group_results:
        gname = gr["name"]
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        pos = np.arange(len(gr["data"]))
        total_alarms += len(gr["alarm_plus"]) + len(gr["alarm_minus"])

        # 数据子图（大样本时去掉点标记，避免"毛刷"噪声）
        if len(pos) > 300:
            ax1.plot(pos, gr["data"], "-", color=color, linewidth=0.7, alpha=0.7, label=label)
        else:
            ax1.plot(
                pos,
                gr["data"],
                "o-",
                markersize=2,
                color=color,
                linewidth=0.8,
                alpha=0.7,
                label=label,
            )
        ax1.axhline(gr["mu"], color=color, linestyle="--", linewidth=0.8, alpha=0.4)

        # CUSUM 子图
        ax2.plot(
            pos,
            gr["c_plus"],
            "-",
            color=color,
            linewidth=1.2,
            alpha=0.8,
            label=f"{label} C+" if has_groups else "C+ (上偏移)",
        )
        ax2.plot(
            pos,
            gr["c_minus"],
            "--",
            color=color,
            linewidth=1.2,
            alpha=0.8,
            label=f"{label} C-" if has_groups else "C- (下偏移)",
        )
        if gr["alarm_plus"]:
            ax2.scatter(
                gr["alarm_plus"],
                gr["c_plus"][gr["alarm_plus"]],
                s=50,
                color=color,
                marker="x",
                linewidths=2,
                zorder=5,
            )
        if gr["alarm_minus"]:
            ax2.scatter(
                gr["alarm_minus"],
                gr["c_minus"][gr["alarm_minus"]],
                s=50,
                color=color,
                marker="x",
                linewidths=2,
                zorder=5,
            )

    ax2.axhline(
        h,
        color=PALETTE["control"]["primary"],
        linestyle="--",
        linewidth=1.2,
        label=f"决策区间 h={h}",
    )
    ax2.fill_between(np.arange(max_n), 0, h, alpha=0.05, color=PALETTE["center"]["primary"])

    ax1.set_ylabel(y_col, fontsize=10)
    ax1.set_title(f"CUSUM 控制图 — {y_col} (k={k}, h={h})", fontsize=11)
    if has_groups:
        ax1.legend(fontsize=7, ncol=max(1, len(all_group_names) // 3 + 1))

    ax2.set_xlabel("序号", fontsize=10)
    ax2.set_ylabel("CUSUM", fontsize=10)
    # 图例固定在右上空白区，避免 matplotlib 自动放置遮挡曲线
    ax2.legend(fontsize=7, ncol=2, loc="upper right")

    fig.tight_layout()

    # 汇总
    summary_parts = [f"CUSUM 检测到 {total_alarms} 次偏移报警 (k={k}σ, h={h})。"]
    for gr in group_results:
        gname = gr["name"]
        ap, am = len(gr["alarm_plus"]), len(gr["alarm_minus"])
        label = f"{gname}: " if has_groups else ""
        summary_parts.append(f"{label}上偏移 {ap} 次，下偏移 {am} 次；")

    # 控制限表
    stats_rows = []
    for gr in group_results:
        gname = gr["name"]
        label = str(gname) if has_groups else "全部"
        stats_rows.append(
            {
                "分组": label,
                "均值(μ)": f"{gr['mu']:.4f}",
                "标准差(σ)": f"{gr['sigma']:.4f}",
                "上偏移报警": str(len(gr["alarm_plus"])),
                "下偏移报警": str(len(gr["alarm_minus"])),
            }
        )

    return AnalysisResult(
        task="spc_cusum",
        tables={
            "cusum_stats": pd.DataFrame(stats_rows),
        },
        figures=[fig],
        summary="".join(summary_parts),
        messages=warn_msgs,
        metadata={
            "k": k,
            "h": h,
            "total_alarms": total_alarms,
            "n_groups": len(group_results),
            "groups": [str(g) for g in _all_groups_meta if g != "_default"],
        },
    )
