"""EWMA 指数加权移动平均控制图（ewma_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine.spc_charts._shared import _resolve_groups


def ewma_chart(req: AnalysisRequest) -> AnalysisResult:
    """EWMA (指数加权移动平均) 控制图 — 对近期观测赋予更高权重。

    参数:
        lam: 平滑参数 (0<λ≤1)。λ越小越平滑，λ=1 等同于原始数据。常用 λ=0.2
        L: 控制限宽度 (常用 2.7~3.0)
        mu: 过程均值 (如未提供，从数据估计)
        sigma: 过程标准差 (如未提供，从数据估计)
        group_col: 分组依据 (可选，不同值=不同颜色的线，共享坐标轴)
    """
    group_vals, group_names, has_groups, y_col, _all_groups_meta = _resolve_groups(req)

    # 公共参数 (ewma)
    lam = req.params.get("lam", 0.2)
    L = req.params.get("L", 2.7)
    try:
        lam, L = float(lam), float(L)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="spc_ewma",
            status="error",
            messages=[f"参数 lam/L 值无效: lam={lam}, L={L}，请输入数值"],
        )
    if not 0 < lam <= 1:
        return AnalysisResult(
            task="spc_ewma",
            status="error",
            messages=[f"λ (平滑参数) 必须在 (0, 1] 范围内，当前值: {lam}"],
        )
    # 审查 2026-08-19 #2.8：L≤0 时控制限退化/反转导致全部点误报警
    if L <= 0:
        return AnalysisResult(
            task="spc_ewma",
            status="error",
            messages=[f"L (控制限宽度) 必须大于 0，当前值: {L}"],
        )

    user_mu = req.params.get("mu")
    user_sigma = req.params.get("sigma")
    if user_mu is not None and user_sigma is not None:
        try:
            user_mu, user_sigma = float(user_mu), float(user_sigma)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="spc_ewma",
                status="error",
                messages=[f"参数 mu/sigma 值无效: mu={user_mu}, sigma={user_sigma}，请输入数值"],
            )
        if not (np.isfinite(user_mu) and np.isfinite(user_sigma)):
            return AnalysisResult(
                task="spc_ewma",
                status="error",
                messages=["参数 mu/sigma 必须为有限数值（不允许 NaN/Inf）"],
            )
    # 审查 2026-08-19 #2.8：只传一个时此前静默忽略两个；改为提示
    if (user_mu is None) != (user_sigma is None):
        return AnalysisResult(
            task="spc_ewma",
            status="error",
            messages=["mu/sigma 必须同时提供或同时省略（当前只提供了一个）"],
        )

    # 分组处理
    group_results = []
    all_group_names = []
    skipped_insufficient: list[str] = []
    skipped_zero_var: list[str] = []
    for gname in group_names:
        mask = group_vals == gname if has_groups else pd.Series(True, index=req.data.index)
        gdata = req.data.loc[mask, y_col].dropna()
        if len(gdata) < 3:
            skipped_insufficient.append(str(gname))
            continue
        all_group_names.append(gname)

        if user_mu is not None and user_sigma is not None:
            mu, sigma = user_mu, user_sigma
        else:
            mu = float(gdata.mean())
            sigma = float(gdata.std(ddof=1))
        # 审查 2026-09-16 D-1：同 CUSUM——微尺度分组不再误判零方差跳过
        if not np.isfinite(sigma) or sigma <= 0:
            skipped_zero_var.append(str(gname))
            continue

        n = len(gdata)
        ewma_vals = np.zeros(n)
        ewma_vals[0] = lam * gdata.values[0] + (1 - lam) * mu
        for i in range(1, n):
            ewma_vals[i] = lam * gdata.values[i] + (1 - lam) * ewma_vals[i - 1]

        sigma_ewma_asym = sigma * np.sqrt(lam / (2 - lam))
        t = np.arange(1, n + 1)
        corr = 1 - (1 - lam) ** (2 * t)
        sigma_ewma_t = sigma * np.sqrt(lam / (2 - lam) * corr)

        ucl_t = mu + L * sigma_ewma_t
        lcl_t = mu - L * sigma_ewma_t
        above = ewma_vals > ucl_t
        below = ewma_vals < lcl_t
        violations = above | below

        group_results.append(
            {
                "name": gname,
                "data": gdata.values,
                "mu": mu,
                "sigma": sigma,
                "ewma": ewma_vals,
                "ucl_t": ucl_t,
                "lcl_t": lcl_t,
                "ucl_asym": float(mu + L * sigma_ewma_asym),
                "lcl_asym": float(mu - L * sigma_ewma_asym),
                "violations": violations,
                "n": n,
            }
        )

    if len(group_results) < 1:
        return AnalysisResult(
            task="spc_ewma",
            status="error",
            messages=["有效数据不足(每组至少3个点)"],
        )

    # 图表
    fig = Figure(figsize=(10, 6))
    ax = fig.add_subplot(111)
    group_colors = {}
    for gi, gname in enumerate(all_group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    total_violations = 0
    warn_msgs: list[str] = []
    if skipped_zero_var:
        warn_msgs.append(
            f"⚠ 以下分组标准差为零（常量值），已跳过 EWMA 计算: {', '.join(skipped_zero_var)}"
        )
    if skipped_insufficient:
        warn_msgs.append(
            f"⚠ 以下分组有效数据不足（<3 个点），已跳过 EWMA 计算: {', '.join(skipped_insufficient)}"
        )
    if user_mu is None:
        warn_msgs.append("⚠ μ/σ 从各组数据独立估计。建议通过参数 mu/sigma 指定已知受控状态的参数。")

    for gr in group_results:
        gname = gr["name"]
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        pos = np.arange(gr["n"])
        total_violations += int(gr["violations"].sum())

        # 原始数据（大样本时去掉点标记，避免"毛刷"噪声）
        if gr["n"] > 300:
            ax.plot(
                pos,
                gr["data"],
                "-",
                alpha=0.25,
                color=color,
                linewidth=0.8,
                label=f"{label} 原始" if has_groups else "原始数据",
            )
        else:
            ax.plot(
                pos,
                gr["data"],
                "o-",
                markersize=2,
                alpha=0.3,
                color=color,
                linewidth=0.6,
                label=f"{label} 原始" if has_groups else "原始数据",
            )
        ax.plot(
            pos,
            gr["ewma"],
            "-",
            color=color,
            linewidth=2,
            label=label if has_groups else f"EWMA (λ={lam})",
        )
        ax.axhline(gr["mu"], color=color, linestyle="--", linewidth=0.8, alpha=0.4)
        ax.plot(pos, gr["ucl_t"], "--", color=color, linewidth=0.8, alpha=0.5)
        ax.plot(pos, gr["lcl_t"], "--", color=color, linewidth=0.8, alpha=0.5)

        if gr["violations"].sum() > 0:
            vpos = np.where(gr["violations"])[0]
            ax.scatter(
                vpos, gr["ewma"][vpos], s=60, color=color, marker="x", linewidths=2, zorder=5
            )

    # 全局参考线
    ax.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5, alpha=0.3)

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(y_col, fontsize=10)
    # 单组时图例移到坐标区上方，标题需上移让位（pad 见下）
    if has_groups:
        ax.set_title(f"EWMA 控制图 — {y_col} (λ={lam}, L={L})", fontsize=11)
    else:
        ax.set_title(f"EWMA 控制图 — {y_col} (λ={lam}, L={L})", fontsize=11, pad=26)
    if has_groups:
        ax.legend(fontsize=7, ncol=max(1, len(all_group_names) // 3 + 1))
        fig.tight_layout()
    else:
        # 图例移到坐标区上方，避免遮挡左上角的数据与违规点
        ax.legend(
            fontsize=7.5,
            ncol=3,
            loc="lower center",
            bbox_to_anchor=(0.5, 1.0),
            frameon=False,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.92))

    # 汇总
    summary_parts = [f"EWMA (λ={lam}, L={L}) 检测到 {total_violations} 个违规点。"]
    for gr in group_results:
        gname = gr["name"]
        label = f"{gname}: " if has_groups else ""
        summary_parts.append(f"{label}渐近UCL={gr['ucl_asym']:.4f}, LCL={gr['lcl_asym']:.4f}；")

    # 统计表
    stats_rows = []
    for gr in group_results:
        gname = gr["name"]
        label = str(gname) if has_groups else "全部"
        stats_rows.append(
            {
                "分组": label,
                "均值(μ)": f"{gr['mu']:.4f}",
                "标准差(σ)": f"{gr['sigma']:.4f}",
                "渐近UCL": f"{gr['ucl_asym']:.4f}",
                "渐近LCL": f"{gr['lcl_asym']:.4f}",
                "违规点数": str(int(gr["violations"].sum())),
            }
        )

    meta: dict = {
        "lam": lam,
        "L": L,
        "total_violations": total_violations,
        "n_groups": len(group_results),
        "groups": [str(g) for g in _all_groups_meta if g != "_default"],
    }
    if len(group_results) == 1:
        meta["mu"] = group_results[0]["mu"]
        meta["sigma"] = group_results[0]["sigma"]
        meta["ucl_asym"] = group_results[0]["ucl_asym"]
        meta["lcl_asym"] = group_results[0]["lcl_asym"]
        meta["violations"] = int(group_results[0]["violations"].sum())

    return AnalysisResult(
        task="spc_ewma",
        tables={"ewma_stats": pd.DataFrame(stats_rows)},
        figures=[fig],
        summary="".join(summary_parts),
        messages=warn_msgs,
        metadata=meta,
    )
