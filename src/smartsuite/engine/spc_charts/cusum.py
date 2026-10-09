"""CUSUM 累积和控制图（cusum_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Finite, Opt, Spec
from smartsuite.core.param_specs_common import GROUP_COL
from smartsuite.engine._guard import (
    BoundaryReport,
    check_magnitude,
    clean_series,
    explain_undefined_sigma,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine.spc_charts._shared import _resolve_groups

# ── 声明式参数契约（P4 步骤③，第二十三轮）──
# 契约：docs/governance/improvement-plan.md §六
PARAM_SPECS = {
    "spc_cusum": Spec(
        k=Opt(
            Finite(gt=0),
            default=0.5,
            label="K 值 (松弛因子)",
            hint="参考值（通常取 0.5σ）；须为正的有限数",
        ),
        h=Opt(
            Finite(gt=0),
            default=5.0,
            label="H 值 (决策区间)",
            hint="判定失控的累积偏差阈值；须为正的有限数，工程上常用 4~5",
        ),
        group_col=GROUP_COL,
        mu=Opt(Finite(), default=None, label="过程均值 μ", hint="留空则由数据估计"),
        sigma=Opt(Finite(), default=None, label="过程标准差 σ", hint="留空则由数据估计"),
    ),
}


def cusum_chart(req: AnalysisRequest) -> AnalysisResult:
    """CUSUM (累积和) 控制图 — 对小偏移 (±0.5σ~2σ) 比 X-bar 更敏感。

    参数:
        k: 参考值/松弛因子 (通常取 δ/2，其中 δ 是要检测的偏移量，以 σ 为单位)
        h: 决策区间 (通常取 4~5)
        mu: 过程均值 (如未提供，从数据估计；建议使用已知受控状态的 μ)
        sigma: 过程标准差 (如未提供，从数据估计；建议使用已知受控状态的 σ)
        group_col: 分组依据 (可选，不同值=不同颜色的线，共享坐标轴)
    """
    # ── 0. 列名存在性前置校验（审查 2026-10-09 P2-4）──
    # `_resolve_groups` 对不存在的分组列会**静默退化**为单系列（has_groups=False），
    # 用户以为已按分组分析却得到单条线 —— 与 process_capability/hypothesis_test/
    # correlation/anova 的显式报错不一致（同样的错误在不同任务下表现不同）。
    _group_col = req.params.get("group_col")
    if _group_col and _group_col not in req.data.columns:
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[
                f"分组列「{_group_col}」不存在于数据中。可用列: {list(req.data.columns)[:10]}"
            ],
        )

    # ── 1. 边界处置（B0/B1）──
    # 审查 2026-10-09 P0-6：入口原为 `dropna()`（不剔除 ±Inf）→ σ=NaN 落入
    # 「零方差」分支，把「数据含 Inf」误归因为「常量数据（标准差为零）」，
    # 用户按提示去查常量列永远查不到原因（违反 boundary-contract 硬性要求 2）。
    _boundary = BoundaryReport()
    y_col = req.target_col
    _series, _n_non_finite = clean_series(req.data[y_col], column=y_col, report=_boundary)
    data = req.data.loc[_series.index] if _n_non_finite else req.data
    # 量级上界（P1-4）：Σy² 在 |y| ≳ 1e154 时溢出为 Inf，σ 随之变 NaN —— 同一条
    # 「σ 不可算」路径，但原因完全不同（量级而非常量），必须单独归因。
    _mag = check_magnitude(_series, what=f"目标列「{y_col}」", report=_boundary)
    if _mag is not None:
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=_boundary.messages(),
            metadata={"boundary_codes": _boundary.codes()},
        )

    group_vals, group_names, has_groups, _same_y_col, _all_groups_meta = _resolve_groups(req)

    # 公共参数 (cusum)
    # 参数校验（P4 步骤③，第二十三轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 迁移前是 `float()` 转换 + 四段检查（约 40 行）；现由 PARAM_SPECS 一次表达。
    _p = PARAM_SPECS["spc_cusum"].validate_or_raise(req.params)
    k, h = _p.k, _p.h
    user_mu, user_sigma = _p.mu, _p.sigma
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
    # σ 不可估计的分组 —— 归因文案由 `_guard.explain_undefined_sigma` 产出，
    # **不再**与「零方差」共用同一个列表（那正是 P0-6 的错误归因）
    skipped_sigma: list[str] = []
    for gname in group_names:
        mask = group_vals == gname if has_groups else pd.Series(True, index=data.index)
        gdata = data.loc[mask, y_col].dropna()
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
        # 审查 2026-09-16 D-1：原 `sigma < EPSILON` 把微尺度分组误判零方差跳过。
        # 审查 2026-10-09 P0-6：原实现把「σ 非有限」与「σ ≤ 0」并入同一条
        # 「标准差为零（常量值）」—— 两者**原因完全不同**：
        #   σ == 0（精确）→ 真的是常量；
        #   σ 非有限     → 数据含 ±Inf / 量级溢出 / 有效观测不足，与"常量"无关。
        # 原文案把用户引向"去查常量列"，永远查不到原因（违反契约硬性要求 2）。
        if not np.isfinite(sigma):
            issue = explain_undefined_sigma(gdata, what=f"分组「{gname}」")
            skipped_sigma.append(issue.detail)
            continue
        if sigma <= 0:
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
    if skipped_sigma:
        warn_msgs.append(
            "⚠ 以下分组的标准差不可估计，已跳过 CUSUM 计算: " + "；".join(skipped_sigma)
        )
    if skipped_insufficient:
        warn_msgs.append(
            f"⚠ 以下分组有效数据不足（<5 个点），已跳过: {', '.join(skipped_insufficient)}"
        )
    if len(group_results) < 1:
        # 归因按**实际原因**组合复述 —— 原文案在「仅有 σ 不可估计」时也会说
        # 「所有分组标准差均为零（常量数据）」，那是错误归因（P0-6）。
        causes: list[str] = []
        if skipped_sigma:
            causes.append(f"标准差不可估计（{skipped_sigma[0]}）")
        if skipped_zero_var:
            causes.append("标准差为零（常量数据）")
        if skipped_insufficient:
            causes.append("有效数据不足（每组至少需要 5 个点）")
        detail = (
            "所有分组均无法计算 CUSUM：" + "；".join(causes)
            if causes
            else "无有效分组，无法计算 CUSUM"
        )
        return AnalysisResult(
            task="spc_cusum",
            status="error",
            messages=[detail] + warn_msgs + _boundary.messages(),
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
        messages=_boundary.messages() + warn_msgs,
        metadata={
            "k": k,
            "h": h,
            "total_alarms": total_alarms,
            "n_groups": len(group_results),
            "groups": [str(g) for g in _all_groups_meta if g != "_default"],
            "boundary_codes": _boundary.codes(),
        },
    )
