import logging

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from sklearn.linear_model import LinearRegression

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)

# ── X-bar/R 控制图常数表 (子组大小 n → A2, D3, D4) ──
# 标准 ASTM/ISO Shewhart 控制图常数 (Montgomery, 9th ed.)
_XBR_CONSTANTS: dict[int, tuple[float, float, float]] = {
    2: (1.880, 0, 3.267),   3: (1.023, 0, 2.574),
    4: (0.729, 0, 2.282),   5: (0.577, 0, 2.114),
    6: (0.483, 0, 2.004),   7: (0.419, 0.076, 1.924),
    8: (0.373, 0.136, 1.864),   9: (0.337, 0.184, 1.816),
    10: (0.308, 0.223, 1.777),  11: (0.285, 0.256, 1.744),
    12: (0.266, 0.283, 1.717),  13: (0.249, 0.307, 1.693),
    14: (0.235, 0.328, 1.672),  15: (0.223, 0.347, 1.653),
    16: (0.212, 0.363, 1.637),  17: (0.203, 0.378, 1.622),
    18: (0.194, 0.391, 1.609),  19: (0.187, 0.404, 1.596),
    20: (0.180, 0.415, 1.585),  21: (0.173, 0.425, 1.575),
    22: (0.167, 0.435, 1.565),  23: (0.162, 0.443, 1.557),
    24: (0.157, 0.452, 1.548),  25: (0.153, 0.459, 1.541),
}


def _we_rules_xbar(values, cl, sigma):
    """Western Electric 规则检测 X-bar 图。返回违规子组索引字典。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    sigma = max(sigma, 1e-10)
    n = len(vals)

    # Rule 1: 单点超出 ±3σ
    r1 = np.where((vals > cl + 3*sigma) | (vals < cl - 3*sigma))[0]
    if len(r1):
        violations["规则1: 超出±3σ"] = [int(i) for i in r1]

    # Rule 2: 连续3点中≥2点超出 ±2σ (同侧)
    r2 = []
    for i in range(n - 2):
        above = np.sum(vals[i:i+3] > cl + 2*sigma)
        below = np.sum(vals[i:i+3] < cl - 2*sigma)
        if above >= 2:
            for j in range(i, i+3):
                if vals[j] > cl + 2*sigma and j not in r2:
                    r2.append(j)
        if below >= 2:
            for j in range(i, i+3):
                if vals[j] < cl - 2*sigma and j not in r2:
                    r2.append(j)
    if r2:
        violations["规则2: 3点中≥2点超出±2σ"] = sorted(set(r2))

    # Rule 3: 连续5点中≥4点超出 ±1σ (同侧)
    r3 = []
    for i in range(n - 4):
        above = np.sum(vals[i:i+5] > cl + 1*sigma)
        below = np.sum(vals[i:i+5] < cl - 1*sigma)
        if above >= 4:
            for j in range(i, i+5):
                if vals[j] > cl + 1*sigma and j not in r3:
                    r3.append(j)
        if below >= 4:
            for j in range(i, i+5):
                if vals[j] < cl - 1*sigma and j not in r3:
                    r3.append(j)
    if r3:
        violations["规则3: 5点中≥4点超出±1σ"] = sorted(set(r3))

    # Rule 4: 连续8点在同一侧
    r4 = []
    for i in range(n - 7):
        if all(vals[i:i+8] > cl) or all(vals[i:i+8] < cl):
            for j in range(i, i+8):
                if j not in r4:
                    r4.append(j)
    if r4:
        violations["规则4: 连续8点同侧"] = sorted(set(r4))

    # Rule 5: 连续6点单调上升或下降
    r5 = []
    for i in range(n - 5):
        if all(vals[i+k+1] > vals[i+k] for k in range(5)):
            for j in range(i, i+6):
                if j not in r5:
                    r5.append(j)
        if all(vals[i+k+1] < vals[i+k] for k in range(5)):
            for j in range(i, i+6):
                if j not in r5:
                    r5.append(j)
    if r5:
        violations["规则5: 连续6点趋势"] = sorted(set(r5))

    # Rule 6: 连续15点在 ±1σ 内（分层/虚假受控）
    r6 = []
    for i in range(n - 14):
        if all(abs(vals[i:i+15] - cl) < 1*sigma):
            for j in range(i, i+15):
                if j not in r6:
                    r6.append(j)
    if r6:
        violations["规则6: 连续15点在±1σ内"] = sorted(set(r6))

    return violations


def _we_rules_r(values, cl, ucl, lcl=0):
    """R 控制图的模式检测规则（右偏分布，不同于 X-bar 的对称规则）。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    n = len(vals)

    # Rule R1a: 超出 UCL
    r1 = np.where(vals > ucl)[0]
    if len(r1):
        violations["R1a: 超出UCL"] = [int(i) for i in r1]

    # Rule R1b: 低于 LCL (仅当 LCL>0 时)
    if lcl > 0:
        r1b = np.where(vals < lcl)[0]
        if len(r1b):
            violations["R1b: 低于LCL"] = [int(i) for i in r1b]

    # Rule R2: 连续 7 点在中心线同侧
    r2_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i:i+7] > cl):
            r2_seen.update(range(i, i+7))
        if all(vals[i:i+7] < cl):
            r2_seen.update(range(i, i+7))
    if r2_seen:
        violations["R2: 连续7点同侧"] = sorted(r2_seen)

    # Rule R3: 连续 7 点上升 (变异性恶化) — 严格单调，与 X-bar Rule 5 一致
    r3_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i+k+1] > vals[i+k] for k in range(6)):
            r3_seen.update(range(i, i+7))
    if r3_seen:
        violations["R3: 连续7点上升 (变异增大)"] = sorted(r3_seen)

    # Rule R4: 连续 7 点下降 (变异性改善)
    r4_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i+k+1] < vals[i+k] for k in range(6)):
            r4_seen.update(range(i, i+7))
    if r4_seen:
        violations["R4: 连续7点下降 (变异减小)"] = sorted(r4_seen)

    # 去重每个规则内的索引
    return {k: sorted(set(v)) for k, v in violations.items()}


def xbar_r_chart(req: AnalysisRequest) -> AnalysisResult:
    """X-bar 和 R 控制图，含 Western Electric 规则和区域着色。"""
    subgroup_col = req.params.get("subgroup_col", "子组")
    if subgroup_col not in req.data.columns:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"子组列「{subgroup_col}」不存在"],
        )

    subgroups = req.data.groupby(subgroup_col)[req.target_col]
    xbar = subgroups.mean()
    r = subgroups.max() - subgroups.min()

    if len(xbar) < 2:
        return AnalysisResult(
            task="spc_xbar", status="error", messages=["子组数量不足"]
        )

    # 校验子组大小一致性 — 不等时自动修剪到最小子组大小
    subgroup_sizes = subgroups.count()
    warn_unequal = ""
    if subgroup_sizes.nunique() > 1:
        min_n = int(subgroup_sizes.min())
        # 修剪每组到 min_n
        trimmed_data = []
        for name, group in subgroups:
            group_vals = group.dropna().values[:min_n]
            if len(group_vals) == min_n:
                trimmed_data.append({"subgroup": name, "values": group_vals})
        if len(trimmed_data) < 2:
            return AnalysisResult(task="spc_xbar", status="error",
                messages=["修剪后子组数量不足"])
        xbar = pd.Series([np.mean(d["values"]) for d in trimmed_data],
                         index=[d["subgroup"] for d in trimmed_data])
        r = pd.Series([np.max(d["values"]) - np.min(d["values"]) for d in trimmed_data],
                      index=[d["subgroup"] for d in trimmed_data])
        n = min_n
        warn_unequal = f" (子组大小不一致，已取每组前{min_n}个值修剪为n={min_n})"
    else:
        n = int(subgroup_sizes.iloc[0]) if len(subgroups) > 0 else 5

    # 在修剪后计算 xbar_bar 和 r_bar，确保控制限与图表数据一致
    xbar_bar = float(xbar.mean())
    r_bar = float(r.mean())

    if n not in _XBR_CONSTANTS:
        return AnalysisResult(
            task="spc_xbar", status="error",
            messages=[f"子组大小 n={n} 不在支持范围 (2-25)"],
        )
    A2, D3, D4 = _XBR_CONSTANTS[n]

    sigma_xbar = A2 * r_bar / 3  # X-bar σ 估计
    ucl_x = xbar_bar + 3 * sigma_xbar
    lcl_x = xbar_bar - 3 * sigma_xbar
    ucl_r = D4 * r_bar
    lcl_r = D3 * r_bar

    # ── Western Electric 规则检测 ──
    xbar_violations = _we_rules_xbar(xbar.values, xbar_bar, sigma_xbar)

    # R 图规则检测
    r_violations = _we_rules_r(r.values, r_bar, ucl_r, lcl_r)

    # ── 增强控制图 ──
    fig = Figure(figsize=(12, 9))
    indices = np.arange(len(xbar))

    # X-bar 控制图
    ax1 = fig.add_subplot(211)
    # 区域着色
    ax1.fill_between(indices, lcl_x, ucl_x, alpha=0.06, color=PALETTE["center"]["primary"], label="±3σ 区域")
    ax1.fill_between(indices, xbar_bar - 2*sigma_xbar, xbar_bar + 2*sigma_xbar,
                     alpha=0.06, color=PALETTE["judge"]["warn"])
    ax1.fill_between(indices, xbar_bar - 1*sigma_xbar, xbar_bar + 1*sigma_xbar,
                     alpha=0.06, color=PALETTE["center"]["primary"])
    ax1.axhline(xbar_bar, color=PALETTE["center"]["primary"], linestyle="-", linewidth=1.5,
                label=f"CL={xbar_bar:.4f}")
    ax1.axhline(ucl_x, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                label=f"UCL={ucl_x:.4f}")
    ax1.axhline(lcl_x, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                label=f"LCL={lcl_x:.4f}")
    ax1.axhline(xbar_bar + 2*sigma_xbar, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.7, alpha=0.6)
    ax1.axhline(xbar_bar - 2*sigma_xbar, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.7, alpha=0.6)
    ax1.axhline(xbar_bar + 1*sigma_xbar, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)
    ax1.axhline(xbar_bar - 1*sigma_xbar, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)

    ax1.plot(indices, xbar.values, "o-", markersize=5, color=PALETTE["data"]["primary"], linewidth=1.2)

    # 标记所有违规点
    all_xbar_violated = set()
    for rule_name, idxs in xbar_violations.items():
        for idx in idxs:
            if idx < len(xbar):
                all_xbar_violated.add(idx)
    if all_xbar_violated:
        vio_idx = sorted(all_xbar_violated)
        ax1.scatter(vio_idx, xbar.values[list(vio_idx)], s=80, color=PALETTE["anomaly"]["primary"],
                   marker="o", facecolors="none", linewidths=2, zorder=5,
                   label=f"违规点 ({len(vio_idx)}个)")

    ax1.set_ylabel(req.target_col, fontsize=10)
    ax1.set_title(f"X-bar 控制图 — {req.target_col} ({len(xbar)}子组×{n}样本{warn_unequal})",
                  fontsize=12)
    ax1.legend(fontsize=7, loc="upper right")
    ax1.set_xticks(indices)
    ax1.set_xticklabels([str(i) for i in xbar.index], fontsize=7, rotation=45)

    # R 控制图
    ax2 = fig.add_subplot(212)
    ax2.axhline(r_bar, color=PALETTE["center"]["primary"], linestyle="-", linewidth=1.5,
                label=f"CL={r_bar:.4f}")
    ax2.axhline(ucl_r, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                label=f"UCL={ucl_r:.4f}")
    ax2.axhline(lcl_r, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                label=f"LCL={lcl_r:.4f}")
    ax2.plot(indices, r.values, "o-", markersize=5, color=PALETTE["target"]["primary"], linewidth=1.2)

    # 标记 R 图违规（所有规则）
    all_r_violated: set[int] = set()
    for idxs in r_violations.values():
        for idx in idxs:
            if idx < len(r):
                all_r_violated.add(idx)
    if all_r_violated:
        r_vio_idx = sorted(all_r_violated)
        ax2.scatter(r_vio_idx, r.values[list(r_vio_idx)], s=80, color=PALETTE["anomaly"]["primary"],
                   marker="o", facecolors="none", linewidths=2, zorder=5,
                   label=f"违规点 ({len(r_vio_idx)}个)")

    ax2.set_xlabel("子组", fontsize=10)
    ax2.set_ylabel("R (极差)", fontsize=10)
    ax2.set_title("R 控制图", fontsize=12)
    ax2.legend(fontsize=7, loc="upper right")
    ax2.set_xticks(indices)
    ax2.set_xticklabels([str(i) for i in r.index], fontsize=7, rotation=45)
    fig.tight_layout()

    # ── 违规汇总表 ──
    violation_rows: list[dict] = []
    for rule_name, idxs in xbar_violations.items():
        violation_rows.append({
            "图表": "X-bar",
            "规则": rule_name,
            "违规子组": ", ".join(str(xbar.index[i]) for i in idxs if i < len(xbar.index)),
            "违规点数": len(idxs),
        })
    for rule_name, idxs in r_violations.items():
        violation_rows.append({
            "图表": "R",
            "规则": rule_name,
            "违规子组": ", ".join(str(r.index[i]) for i in idxs if i < len(r.index)),
            "违规点数": len(idxs),
        })

    is_stable = len(xbar_violations) == 0 and len(r_violations) == 0

    # ── 控制限表 ──
    limits = pd.DataFrame({
        "统计量": ["X-bar", "R"],
        "CL": [f"{xbar_bar:.4f}", f"{r_bar:.4f}"],
        "UCL": [f"{ucl_x:.4f}", f"{ucl_r:.4f}"],
        "LCL": [f"{lcl_x:.4f}", f"{lcl_r:.4f}"],
        "1σ上限": [f"{xbar_bar + sigma_xbar:.4f}", "—"],
        "1σ下限": [f"{xbar_bar - sigma_xbar:.4f}", "—"],
    })

    stability_summary = (
        "过程稳定 ✓" if is_stable
        else f"过程存在异常，共触发 {len(xbar_violations) + len(r_violations)} 条规则"
    )

    messages: list[str] = []
    if warn_unequal:
        messages.append(
            f"⚠ 子组大小不一致: {warn_unequal.strip(' ()')}。"
            "注：取每组前N个值，后续值被丢弃。如需完整分析，建议使用等大子组。"
        )

    return AnalysisResult(
        task="spc_xbar",
        tables={
            "control_limits": limits,
            "violations": pd.DataFrame(violation_rows) if violation_rows
            else pd.DataFrame({"状态": ["未检测到违规"]}),
        },
        figures=[fig],
        summary=f"{stability_summary}。X-bar CL={xbar_bar:.4f}, UCL={ucl_x:.4f}, LCL={lcl_x:.4f}",
        messages=messages,
        metadata={
            "xbar_mean": xbar_bar,
            "r_mean": r_bar,
            "ucl_x": ucl_x, "lcl_x": lcl_x,
            "ucl_r": ucl_r, "lcl_r": lcl_r,
            "sigma_xbar": sigma_xbar,
            "subgroup_size": n,
            "xbar_violations": {k: v for k, v in xbar_violations.items()},
            "r_violations": {k: v for k, v in r_violations.items()},
            "is_stable": is_stable,
        },
    )


def attribute_chart(req: AnalysisRequest) -> AnalysisResult:
    """计数型/属性控制图：p (不良率)、np (不良数)、c (缺陷数)、u (单位缺陷率)。

    参数:
        chart_type: "p" | "np" | "c" | "u"
        subgroup_col: 分组列 (p/np 的检验批次, c/u 的样本单元)
        n_col: 样本量列名 (p/u 图需要，变样本量时使用)
    """
    chart_type = req.params.get("chart_type", "p")
    subgroup_col = req.params.get("subgroup_col")

    if subgroup_col and subgroup_col in req.data.columns:
        subgroups = req.data.groupby(subgroup_col)[req.target_col]
        counts = subgroups.sum()
        sizes = subgroups.count()
    else:
        counts = req.data[req.target_col].dropna()
        sizes = pd.Series(1, index=counts.index)

    m = len(counts)
    if m < 5:
        return AnalysisResult(
            task="spc_attribute", status="error",
            messages=["子组数量不足(至少5个)"],
        )

    # ── 按图表类型计算统计量 ──
    if chart_type == "p":
        # p-chart: 不良率 = 不良数 / 检验数
        n_col = req.params.get("n_col")
        if n_col and n_col in req.data.columns:
            n_vals = req.data.groupby(subgroup_col)[n_col].first() if subgroup_col else req.data[n_col]
        else:
            n_vals = sizes
        if (n_vals == 0).any():
            return AnalysisResult(task="spc_attribute", status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"])
        stat = counts / n_vals
        stat_name = "不良率(p)"
        p_bar = float(counts.sum() / n_vals.sum())
        cl = p_bar
        # 控制限随样本量变化
        ucl = p_bar + 3 * np.sqrt(p_bar * (1 - p_bar) / n_vals.values)
        lcl = np.maximum(0, p_bar - 3 * np.sqrt(p_bar * (1 - p_bar) / n_vals.values))
        ucl_const = None  # 非恒定

    elif chart_type == "np":
        # np-chart: 不良数（要求等样本量）
        stat = counts
        stat_name = "不良数(np)"
        if sizes.nunique() > 1:
            logger.warning(
                "np-chart 要求等样本量，当前子组大小范围为 %.0f-%.0f，将使用均值 %.1f 近似计算控制限",
                sizes.min(), sizes.max(), sizes.mean()
            )
        n_bar = float(sizes.mean())
        np_bar = float(counts.mean())
        p_bar = np_bar / n_bar
        cl = np_bar
        ucl = np_bar + 3 * np.sqrt(np_bar * (1 - p_bar))
        lcl = np.maximum(0, np_bar - 3 * np.sqrt(np_bar * (1 - p_bar)))
        ucl_const = float(ucl)

    elif chart_type == "c":
        # c-chart: 缺陷数 (Poisson, 固定检验单位)
        stat = counts
        stat_name = "缺陷数(c)"
        c_bar = float(counts.mean())
        cl = c_bar
        ucl = c_bar + 3 * np.sqrt(c_bar)
        lcl = np.maximum(0, c_bar - 3 * np.sqrt(c_bar))
        ucl_const = float(ucl)

    elif chart_type == "u":
        # u-chart: 单位缺陷率 (变检验单位)
        n_col = req.params.get("n_col")
        if n_col and n_col in req.data.columns:
            n_vals = req.data.groupby(subgroup_col)[n_col].first() if subgroup_col else req.data[n_col]
        else:
            n_vals = sizes
        if (n_vals == 0).any():
            return AnalysisResult(task="spc_attribute", status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"])
        stat = counts / n_vals
        stat_name = "单位缺陷率(u)"
        u_bar = float(counts.sum() / n_vals.sum())
        cl = u_bar
        ucl = u_bar + 3 * np.sqrt(u_bar / n_vals.values)
        lcl = np.maximum(0, u_bar - 3 * np.sqrt(u_bar / n_vals.values))
        ucl_const = None

    else:
        return AnalysisResult(
            task="spc_attribute", status="error",
            messages=[f"不支持的图表类型: {chart_type}，支持 p/np/c/u"],
        )

    # ── 违规检测 ──
    if ucl_const is not None:
        above = stat > ucl_const
        below = stat < float(lcl)
    else:
        above = stat.values > ucl
        below = stat.values < lcl
    violations = np.where(above | below)[0]

    # ── 控制图 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(m)
    ax.plot(pos, stat.values, "o-", markersize=5, color=PALETTE["data"]["primary"], linewidth=1.2)
    ax.axhline(cl, color=PALETTE["center"]["primary"], linestyle="-", linewidth=1.5,
               label=f"CL={cl:.4f}")

    if ucl_const is not None:
        ax.axhline(ucl_const, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"UCL={ucl_const:.4f}")
        lcl_val = float(lcl)
        ax.axhline(lcl_val, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"LCL={lcl_val:.4f}")
    else:
        ax.plot(pos, ucl, "--", color=PALETTE["anomaly"]["primary"], linewidth=1, alpha=0.6, label="UCL")
        ax.plot(pos, lcl, "--", color=PALETTE["anomaly"]["primary"], linewidth=1, alpha=0.6, label="LCL")

    if len(violations) > 0:
        ax.scatter(violations, stat.values[violations], s=80, color=PALETTE["anomaly"]["primary"],
                   marker="x", linewidths=2.5, zorder=5,
                   label=f"超出控制限 ({len(violations)}个)")

    ax.set_xlabel("子组序号", fontsize=10)
    ax.set_ylabel(stat_name, fontsize=10)
    ax.set_title(
        f"{chart_type.upper()}-控制图 — {req.target_col} (m={m}子组)",
        fontsize=11,
    )
    ax.legend(fontsize=8)
    fig.tight_layout()

    # ── 汇总 ──
    summary = (
        f"{chart_type.upper()} 控制图: CL={cl:.4f}, "
        f"超出控制限 {len(violations)}/{m} 个子组"
    )

    return AnalysisResult(
        task="spc_attribute",
        tables={
            "control_stats": pd.DataFrame({
                "子组": range(1, m + 1),
                stat_name: stat.values.round(4),
                "UCL": ucl.round(4) if ucl_const is None else [f"{ucl_const:.4f}"] * m,
                "LCL": lcl.round(4) if ucl_const is None else [f"{lcl_val:.4f}"] * m,
            }),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "chart_type": chart_type,
            "cl": float(cl),
            "n_subgroups": m,
            "n_violations": len(violations),
        },
    )


def _cp_confidence_interval(cp, n, alpha=0.05):
    """Cp/Cpk 95% 置信区间 (基于 χ² 分布)。"""
    dof = n - 1
    if dof <= 0 or cp is None:
        return (None, None)
    chi2_lower = sp_stats.chi2.ppf(alpha / 2, dof)
    chi2_upper = sp_stats.chi2.ppf(1 - alpha / 2, dof)
    ci_lower = cp * np.sqrt(chi2_lower / dof)
    ci_upper = cp * np.sqrt(chi2_upper / dof)
    return (float(ci_lower), float(ci_upper))


def _cpk_confidence_interval(cpk, n, alpha=0.05):
    """Cpk 95% 置信区间近似 (Bissell 方法)。"""
    if cpk is None or n < 2:
        return (None, None)
    se = np.sqrt(1 / (9 * n) + cpk**2 / (2 * (n - 1)))
    z = sp_stats.norm.ppf(1 - alpha / 2)
    ci_lower = cpk - z * se
    ci_upper = cpk + z * se
    return (float(ci_lower), float(ci_upper))


def _sigma_level(cpk_val):
    """Cpk → Sigma Level (短期) 和 DPMO 估算。

    注意: DPMO 公式使用短期 (unshifted) sigma，假设过程均值不发生偏移。
    实际生产中常考虑 1.5σ 偏移，此时 DPMO 会更高。该公式提供的是
    理论最优条件下的缺陷率估算，用于能力对比而非绝对预测。
    """
    # Sigma Level ≈ 3 * Cpk（长期 Z 值）
    # DPMO = 2 * Φ(-3*Cpk) * 1e6（双边正态，无偏移假设）
    sigma = 3 * cpk_val
    dpmo = int(2 * sp_stats.norm.cdf(-3 * cpk_val) * 1_000_000)
    return float(sigma), dpmo


def _box_cox_transform(data):
    """Box-Cox 幂变换，返回 (变换后数据, lambda)。仅用于正值数据。"""
    if (data <= 0).any():
        return None, None
    try:
        transformed, lam = sp_stats.boxcox(data)
        return transformed, float(lam)
    except Exception:
        logger.warning("Box-Cox 变换失败 (数据可能非正值或数值异常)", exc_info=True)
        return None, None


def _normality_warning(data):
    """检测非正态性并给出警告。"""
    n = len(data)
    if n < 3 or n > 5000:
        return None
    _, sw_p = sp_stats.shapiro(data)
    if sw_p < 0.01:
        return (
            f"⚠ 正态性检验 (Shapiro-Wilk) p={sw_p:.4f}<0.01，"
            f"数据显著偏离正态分布，建议使用 Box-Cox 变换或非正态能力分析"
        )
    return None


def process_capability_analysis(req: AnalysisRequest) -> AnalysisResult:
    """过程能力分析：Cp/Cpk/Pp/Ppk/Cpm，含置信区间、DPMO 和 Sigma Level。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 2:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=["有效数据不足"],
        )

    usl = req.params.get("usl")
    lsl = req.params.get("lsl")
    target = req.params.get("target")  # Cpm 目标值
    transform = req.params.get("transform")  # None | "boxcox"
    n = len(data)

    warn_msgs: list[str] = []
    boxcox_lambda: float | None = None

    # ── Box-Cox 变换（非正态数据处理）──
    if transform == "boxcox":
        transformed, lam = _box_cox_transform(data.values)
        if transformed is not None:
            data = pd.Series(transformed, name=data.name)
            boxcox_lambda = lam
            # 对规格限和目标值同样做 Box-Cox 变换（全量或全不：避免混合尺度）
            spec_positive = (usl is not None and usl > 0) and (lsl is not None and lsl > 0)
            if spec_positive:
                usl = sp_stats.boxcox(np.array([usl]), lmbda=lam)[0]
                lsl = sp_stats.boxcox(np.array([lsl]), lmbda=lam)[0]
                if target is not None and target > 0:
                    target = sp_stats.boxcox(np.array([target]), lmbda=lam)[0]
            elif usl is not None or lsl is not None:
                warn_msgs.append(
                    "⚠ Box-Cox 变换要求规格限均为正值，规格限保持在原始尺度，"
                    "Cp/Cpk 可能不准确，建议使用原始数据分析"
                )
        else:
            warn_msgs.append("⚠ Box-Cox 变换失败（数据必须全部为正值），使用原始数据分析")

    norm_warn = _normality_warning(data)
    if norm_warn and transform != "boxcox":
        warn_msgs.append(norm_warn)

    mu = float(data.mean())
    sigma_overall = float(data.std(ddof=1))  # 整体 σ (用于 Pp/Ppk)
    mr = np.abs(np.diff(data.values))
    within_sigma = float(np.mean(mr) / 1.128) if len(mr) > 0 else sigma_overall

    # ── 计算各项能力指数 ──
    has_upper = usl is not None
    has_lower = lsl is not None
    has_both = has_upper and has_lower

    # Cp/Cpk (短期/组内) — 单侧公差仅计算 Cpk
    cp = float((usl - lsl) / (6 * within_sigma)) if has_both and within_sigma > 0 else None
    if has_upper and has_lower:
        cpk_val = float(min((usl - mu) / (3 * within_sigma),
                            (mu - lsl) / (3 * within_sigma))) if within_sigma > 0 else None
    elif has_upper:
        cpk_val = float((usl - mu) / (3 * within_sigma)) if within_sigma > 0 else None
    elif has_lower:
        cpk_val = float((mu - lsl) / (3 * within_sigma)) if within_sigma > 0 else None
    else:
        cpk_val = None

    # Pp/Ppk (长期/整体) — 单侧公差仅计算 Ppk
    pp = float((usl - lsl) / (6 * sigma_overall)) if has_both and sigma_overall > 0 else None
    if has_upper and has_lower:
        ppk_val = float(min((usl - mu) / (3 * sigma_overall),
                            (mu - lsl) / (3 * sigma_overall))) if sigma_overall > 0 else None
    elif has_upper:
        ppk_val = float((usl - mu) / (3 * sigma_overall)) if sigma_overall > 0 else None
    elif has_lower:
        ppk_val = float((mu - lsl) / (3 * sigma_overall)) if sigma_overall > 0 else None
    else:
        ppk_val = None

    # Cpm (Taguchi 能力指数, 需双侧公差)
    cpm = None
    if has_both and target is not None and sigma_overall > 0:
        tau = np.sqrt(sigma_overall**2 + (mu - target)**2)
        cpm = float((usl - lsl) / (6 * tau)) if tau > 0 else None

    # 置信区间
    cp_ci = _cp_confidence_interval(cp, n) if cp is not None else (None, None)
    cpk_ci = _cpk_confidence_interval(cpk_val, n) if cpk_val is not None else (None, None)

    # Sigma Level + DPMO
    sigma_lvl, dpmo = _sigma_level(cpk_val) if cpk_val is not None else (None, None)

    # ── 判定 ──
    if cpk_val is not None:
        if cpk_val >= 1.67:
            judge = "优秀 (≥1.67)"
        elif cpk_val >= 1.33:
            judge = "合格 (≥1.33)"
        elif cpk_val >= 1.0:
            judge = "勉强 (≥1.0，需改进)"
        else:
            judge = "不合格 (<1.0)"
    else:
        judge = "未提供规格限"

    # ── 能力汇总表 ──
    capability_rows = [
        {"指标": "Cp (短期能力)", "值": f"{cp:.3f}" if cp else "N/A",
         "95%CI下限": f"{cp_ci[0]:.3f}" if cp_ci[0] else "N/A",
         "95%CI上限": f"{cp_ci[1]:.3f}" if cp_ci[1] else "N/A"},
        {"指标": "Cpk (短期+偏倚)", "值": f"{cpk_val:.3f}" if cpk_val else "N/A",
         "95%CI下限": f"{cpk_ci[0]:.3f}" if cpk_ci[0] else "N/A",
         "95%CI上限": f"{cpk_ci[1]:.3f}" if cpk_ci[1] else "N/A"},
        {"指标": "Pp (长期能力)", "值": f"{pp:.3f}" if pp else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Ppk (长期+偏倚)", "值": f"{ppk_val:.3f}" if ppk_val else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Cpm (田口能力)", "值": f"{cpm:.3f}" if cpm else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Sigma Level (无偏移理论值)", "值": f"{sigma_lvl:.2f}" if sigma_lvl else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "DPMO (无偏移假设)", "值": f"{dpmo:,}" if dpmo else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
    ]
    capability_df = pd.DataFrame(capability_rows)

    # ── 描述统计表 ──
    desc_df = pd.DataFrame({
        "统计量": ["样本量", "均值", "整体σ", "组内σ", "偏度", "峰度",
                  "USL", "LSL", "目标值"],
        "值": [
            str(n), f"{mu:.4f}", f"{sigma_overall:.4f}", f"{within_sigma:.4f}",
            f"{float(data.skew()):.4f}", f"{float(data.kurtosis()):.4f}",
            str(usl) if usl else "未指定", str(lsl) if lsl else "未指定",
            str(target) if target else "未指定",
        ],
    })

    # ── 增强直方图 + 正态拟合曲线 + 规格限区域 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    # 直方图
    n_bins = min(30, max(10, int(np.sqrt(n))))
    counts, bins, patches = ax.hist(
        data, bins=n_bins, color=PALETTE["data"]["secondary"], edgecolor="white",
        alpha=0.7, density=True, label="数据分布"
    )

    # 正态拟合曲线
    x_fit = np.linspace(data.min(), data.max(), 200)
    pdf_fit = sp_stats.norm.pdf(x_fit, mu, sigma_overall)
    ax.plot(x_fit, pdf_fit, color=PALETTE["data"]["primary"], linewidth=2,
            label=f"正态拟合 (μ={mu:.3f}, σ={sigma_overall:.3f})")

    # 规格限
    ax.axvline(mu, color=PALETTE["center"]["primary"], linestyle="-", linewidth=2,
               label=f"均值={mu:.4f}")
    if lsl is not None:
        ax.axvline(lsl, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=2,
                   label=f"LSL={lsl}")
    if usl is not None:
        ax.axvline(usl, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=2,
                   label=f"USL={usl}")
    if target is not None:
        ax.axvline(target, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=1.5,
                   label=f"目标={target}")

    # 规格限区域着色
    if lsl is not None and usl is not None:
        ax.axvspan(lsl, usl, alpha=0.08, color=PALETTE["center"]["primary"], label="规格范围")

    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("密度", fontsize=10)

    # 构建标题
    title_parts = [f"过程能力分析 — {req.target_col}"]
    if boxcox_lambda is not None:
        title_parts.append(f"(Box-Cox λ={boxcox_lambda:.3f})")
    if cpk_val is not None:
        title_parts.append(f"Cpk={cpk_val:.3f}")
    if ppk_val is not None:
        title_parts.append(f"Ppk={ppk_val:.3f}")
    title_parts.append(f"判定: {judge}")
    ax.set_title(" | ".join(title_parts), fontsize=11)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()

    # ── 汇总 ──
    summary_parts = []
    if boxcox_lambda is not None:
        summary_parts.append(f"Box-Cox λ={boxcox_lambda:.3f}")
    if cpk_val is not None:
        cpk_ci_str = f"[{cpk_ci[0]:.3f}, {cpk_ci[1]:.3f}]" if cpk_ci[0] else "N/A"
        summary_parts.append(f"Cpk={cpk_val:.3f} (95%CI: {cpk_ci_str})")
    if ppk_val is not None:
        summary_parts.append(f"Ppk={ppk_val:.3f}")
    if cpm is not None:
        summary_parts.append(f"Cpm={cpm:.3f}")
    if sigma_lvl is not None:
        summary_parts.append(f"Sigma={sigma_lvl:.2f} σ")
    if dpmo is not None:
        summary_parts.append(f"DPMO={dpmo:,}")
    summary_parts.append(f"判定: {judge}")
    summary = "；".join(summary_parts)

    return AnalysisResult(
        task="process_capability",
        tables={
            "capability_indices": capability_df,
            "descriptive_stats": desc_df,
        },
        figures=[fig],
        summary=summary,
        metadata={
            "cp": cp, "cpk": cpk_val, "pp": pp, "ppk": ppk_val, "cpm": cpm,
            "cp_ci": cp_ci, "cpk_ci": cpk_ci,
            "sigma_level": sigma_lvl, "dpmo": dpmo,
            "mean": mu, "sigma_overall": sigma_overall,
            "sigma_within": within_sigma, "n": n,
            "judge": judge,
            "boxcox_lambda": boxcox_lambda,
        },
        messages=warn_msgs,
    )


def durbin_watson(residuals):
    """Durbin-Watson 统计量 — 检测残差一阶自相关。

    跨模块共享工具：被 regression_analysis (doe_opt.py) 和 trend_forecast 调用。
    """
    diff = np.diff(residuals)
    dw = np.sum(diff**2) / (np.sum(residuals**2) + 1e-10)
    return float(dw)


# 向后兼容别名
_durbin_watson = durbin_watson


def _ljung_box(residuals, lags=None):
    """Ljung-Box 检验 — 残差自相关的整体显著性检验。"""
    n = len(residuals)
    if lags is None:
        lags = min(10, n // 5)
    lags = max(1, min(lags, n // 2))
    # 简化计算：对每个滞后计算自相关，然后 Q = n*(n+2)*sum(r_k^2/(n-k))
    acf_sum = 0.0
    for k in range(1, lags + 1):
        r_k = np.corrcoef(residuals[k:], residuals[:-k])[0, 1]
        acf_sum += r_k**2 / (n - k)
    q_stat = n * (n + 2) * acf_sum
    p_val = float(1 - sp_stats.chi2.cdf(q_stat, lags))
    return float(q_stat), p_val, lags


def _dw_interpretation(dw, n, k=1):
    """Durbin-Watson 判读（近似阈值）。

    注意: 阈值 1.0/1.5/2.5/3.0 为近似经验值，精确的 DW 临界值
    取决于样本量 n 和自变量数 k。对于小样本 (n<30) 或多变量回归，
    建议查阅 DW 临界值表进行精确判读。本函数提供快速近似判读。
    """
    if dw < 1.0:
        return f"正自相关 (DW={dw:.3f}<1.0)"
    elif dw > 3.0:
        return f"负自相关 (DW={dw:.3f}>3.0)"
    elif 1.5 <= dw <= 2.5:
        return f"无显著自相关 (DW={dw:.3f})"
    else:
        return f"不确定 (DW={dw:.3f})"


def trend_forecast(req: AnalysisRequest) -> AnalysisResult:
    """线性趋势预测，含精度指标 (MAPE/RMSE/MAE)、残差诊断和 Durbin-Watson 检验。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 3:
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=["有效数据不足(至少3个点)"],
        )

    steps = req.params.get("forecast_steps", 5)
    try:
        n = len(data)
        X = np.arange(n).reshape(-1, 1)
        y = data.values
        model = LinearRegression().fit(X, y)

        # ── 样本内拟合 ──
        y_pred_in = model.predict(X)
        residuals = y - y_pred_in

        # ── 精度指标 ──
        # MAPE (处理零值)
        mape_mask = np.abs(y) > 1e-10
        mape = float(np.mean(np.abs(residuals[mape_mask] / y[mape_mask])) * 100) if mape_mask.sum() > 0 else None
        rmse = float(np.sqrt(np.mean(residuals**2)))
        mae = float(np.mean(np.abs(residuals)))
        r2 = float(model.score(X, y))
        adj_r2 = float(1 - (1 - r2) * (n - 1) / max(n - 2, 1))

        # ── Durbin-Watson + Ljung-Box ──
        dw = _durbin_watson(residuals)
        dw_label = _dw_interpretation(dw, n)
        lb_q, lb_p, lb_lags = _ljung_box(residuals)

        # ── 预测 ──
        future_X = np.arange(n, n + steps).reshape(-1, 1)
        predictions = model.predict(future_X)

        # 使用 t 分布（小样本更准确）
        dof = max(1, n - 2)
        t_crit = sp_stats.t.ppf(0.975, dof)
        resid_std_se = float(np.std(residuals, ddof=2))
        # 预测区间随预测步数增大而加宽（外推不确定性）
        x_mean = float(np.mean(np.arange(n)))
        ssx = float(np.sum((np.arange(n) - x_mean) ** 2))
        future_conf = []
        for step in range(1, steps + 1):
            x_future = n + step - 1  # 0-indexed future position
            se_future = resid_std_se * np.sqrt(1 + 1/n + (x_future - x_mean)**2 / ssx)
            future_conf.append(float(t_crit * se_future))
        conf_array = np.array(future_conf)

        forecast_df = pd.DataFrame({
            "步数": range(1, steps + 1),
            "预测值": predictions.round(4),
            "下限": (predictions - conf_array).round(4),
            "上限": (predictions + conf_array).round(4),
        })

        # ── 精度指标表 ──
        lb_label = f"显著自相关 (p={lb_p:.4f})" if lb_p < 0.05 else f"无显著自相关 (p={lb_p:.4f})"
        metrics_df = pd.DataFrame({
            "指标": ["R²", "调整R²", "RMSE", "MAE", "MAPE (%)",
                    "Durbin-Watson", "Ljung-Box Q", "Ljung-Box p",
                    "残差诊断", "样本量", "预测步数", "斜率 (每步)", "截距"],
            "值": [
                f"{r2:.4f}", f"{adj_r2:.4f}", f"{rmse:.4f}", f"{mae:.4f}",
                f"{mape:.2f}%" if mape else "N/A",
                f"{dw:.4f}", f"{lb_q:.3f}", f"{lb_p:.4f}",
                f"{dw_label}; {lb_label}",
                str(n), str(steps),
                f"{float(model.coef_[0]):.6f}", f"{float(model.intercept_):.4f}",
            ],
        })

        trend_dir = "上升" if model.coef_[0] > 0 else "下降"

        # ── ACF 计算 ──
        max_lag = min(20, n // 4)
        acf_vals = []
        acf_conf = float(sp_stats.norm.ppf(0.975)) / np.sqrt(n)  # 95% 置信限
        for lag in range(max_lag + 1):
            if lag == 0:
                acf_vals.append(1.0)
            else:
                r = np.corrcoef(residuals[lag:], residuals[:-lag])[0, 1]
                acf_vals.append(float(r))

        # ── 增强图表：2×2 布局 ──
        fig = Figure(figsize=(13, 9))

        # 左上：趋势 + 预测 + 置信带
        ax1 = fig.add_subplot(2, 2, 1)
        hist_idx = np.arange(n)
        ax1.plot(hist_idx, y, "o-", markersize=3, label="历史数据", color=PALETTE["data"]["primary"], linewidth=1.2)
        ax1.plot(hist_idx, y_pred_in, "-", color=PALETTE["data"]["secondary"], linewidth=2, alpha=0.6,
                label=f"趋势线 (R²={r2:.3f})")
        fut_idx = np.arange(n, n + steps)
        ax1.plot(fut_idx, predictions, "o-", markersize=4, label="预测", color=PALETTE["target"]["primary"])
        ax1.fill_between(fut_idx, predictions - conf_array, predictions + conf_array,
                        alpha=0.2, color=PALETTE["target"]["primary"], label="95% 预测区间")
        ax1.set_xlabel("时间点", fontsize=9)
        ax1.set_ylabel(req.target_col, fontsize=9)
        ax1.set_title(f"趋势预测 — {req.target_col} ({trend_dir})", fontsize=10)
        ax1.legend(fontsize=7)

        # 右上：残差图
        ax2 = fig.add_subplot(2, 2, 2)
        ax2.scatter(hist_idx, residuals, s=12, color=PALETTE["data"]["secondary"], alpha=0.7)
        ax2.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
        ax2.plot(hist_idx, residuals, "-", color=PALETTE["data"]["secondary"], alpha=0.3, linewidth=0.5)
        ax2.set_xlabel("时间点", fontsize=9)
        ax2.set_ylabel("残差", fontsize=9)
        ax2.set_title(f"残差 — {dw_label}", fontsize=10)

        # 左下：ACF 自相关图
        ax3 = fig.add_subplot(2, 2, 3)
        lags = range(max_lag + 1)
        ax3.bar(lags, acf_vals, color=PALETTE["data"]["secondary"], width=0.4, edgecolor="white")
        ax3.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
        ax3.axhline(acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6)
        ax3.axhline(-acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6)
        ax3.set_xlabel("滞后阶数", fontsize=9)
        ax3.set_ylabel("自相关 (ACF)", fontsize=9)
        ax3.set_title("残差自相关 (ACF)", fontsize=10)

        # 右下：Actual vs Predicted
        ax4 = fig.add_subplot(2, 2, 4)
        ax4.scatter(y_pred_in, y, s=12, alpha=0.6, color=PALETTE["data"]["primary"])
        ax4.plot([y.min(), y.max()], [y.min(), y.max()], "r--", linewidth=1)
        ax4.set_xlabel("预测值", fontsize=9)
        ax4.set_ylabel("实际值", fontsize=9)
        ax4.set_title(f"Actual vs Predicted (R²={r2:.3f})", fontsize=10)
        fig.tight_layout()

        # ── 汇总 ──
        mape_str = f"{mape:.1f}%" if mape else "N/A"
        summary = (
            f"趋势{trend_dir} (斜率={float(model.coef_[0]):.4f}/步)，"
            f"预测{steps}步。R²={r2:.3f}, RMSE={rmse:.4f}, MAPE={mape_str}。"
            f"残差自相关: {dw_label}"
        )

        return AnalysisResult(
            task="trend_forecast",
            tables={
                "forecast": forecast_df,
                "accuracy_metrics": metrics_df,
            },
            figures=[fig],
            summary=summary,
            metadata={
                "slope": float(model.coef_[0]),
                "intercept": float(model.intercept_),
                "r_squared": r2, "r_squared_adj": adj_r2,
                "rmse": rmse, "mae": mae, "mape": mape,
                "durbin_watson": dw, "dw_interpretation": dw_label,
                "ljung_box_q": lb_q, "ljung_box_p": lb_p, "ljung_box_lags": lb_lags,
                "forecast_steps": steps, "n": n,
            },
        )
    except (ValueError, np.linalg.LinAlgError) as e:
        logger.warning("趋势预测模型拟合失败: %s", e)
        return AnalysisResult(
            task="trend_forecast", status="error",
            messages=[f"趋势预测模型拟合失败: {e}"])


def cusum_chart(req: AnalysisRequest) -> AnalysisResult:
    """CUSUM (累积和) 控制图 — 对小偏移 (±0.5σ~2σ) 比 X-bar 更敏感。

    参数:
        k: 参考值/松弛因子 (通常取 δ/2，其中 δ 是要检测的偏移量，以 σ 为单位)
        h: 决策区间 (通常取 4~5)
        mu: 过程均值 (如未提供，从数据估计；建议使用已知受控状态的 μ)
        sigma: 过程标准差 (如未提供，从数据估计；建议使用已知受控状态的 σ)
    """
    data = req.data[req.target_col].dropna()
    if len(data) < 5:
        return AnalysisResult(
            task="spc_cusum", status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    mu = req.params.get("mu")
    sigma = req.params.get("sigma")
    warn_msgs: list[str] = []
    if mu is not None and sigma is not None:
        mu, sigma = float(mu), float(sigma)
    else:
        mu = float(data.mean())
        sigma = float(data.std(ddof=1))
        warn_msgs.append(
            "⚠ μ/σ 从全部数据估计，若数据包含过程偏移会导致 CUSUM 灵敏度下降。"
            "建议通过参数 mu/sigma 指定已知受控状态的参数。"
        )
    if sigma < 1e-10:
        return AnalysisResult(
            task="spc_cusum", status="error",
            messages=["数据标准差接近零，无法计算 CUSUM"],
        )

    # 标准化
    z = (data.values - mu) / sigma
    k = req.params.get("k", 0.5)   # 默认检测 1σ 偏移
    h = req.params.get("h", 5.0)   # 默认决策区间

    # 双侧 CUSUM
    c_plus = np.zeros(len(z))
    c_minus = np.zeros(len(z))
    alarm_plus: list[int] = []
    alarm_minus: list[int] = []

    for i in range(len(z)):
        if i == 0:
            c_plus[i] = max(0, z[i] - k)
            c_minus[i] = max(0, -z[i] - k)
        else:
            c_plus[i] = max(0, c_plus[i-1] + z[i] - k)
            c_minus[i] = max(0, c_minus[i-1] - z[i] - k)
        if c_plus[i] > h:
            alarm_plus.append(i)
        if c_minus[i] > h:
            alarm_minus.append(i)

    # 图表
    fig = Figure(figsize=(10, 6))
    pos = np.arange(len(data))

    ax1 = fig.add_subplot(211)
    ax1.plot(pos, data.values, "o-", markersize=3, color=PALETTE["data"]["secondary"], linewidth=1, label="数据")
    ax1.axhline(mu, color=PALETTE["center"]["primary"], linestyle="-", linewidth=1, label=f"均值={mu:.3f}")
    ax1.set_ylabel(req.target_col, fontsize=10)
    ax1.set_title(f"CUSUM 控制图 — {req.target_col} (k={k}, h={h})", fontsize=11)
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(212)
    ax2.plot(pos, c_plus, "-", color=PALETTE["target"]["primary"], linewidth=1.5, label="C+ (上偏移)")
    ax2.plot(pos, c_minus, "-", color=PALETTE["data"]["primary"], linewidth=1.5, label="C- (下偏移)")
    ax2.axhline(h, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.2, label=f"决策区间 h={h}")
    ax2.fill_between(pos, 0, h, alpha=0.05, color=PALETTE["center"]["primary"])
    if alarm_plus:
        ax2.scatter(alarm_plus, c_plus[alarm_plus], s=60, color=PALETTE["anomaly"]["primary"],
                   marker="x", linewidths=2, zorder=5, label=f"上偏移报警({len(alarm_plus)})")
    if alarm_minus:
        ax2.scatter(alarm_minus, c_minus[alarm_minus], s=60, color=PALETTE["anomaly"]["primary"],
                   marker="x", linewidths=2, zorder=5, label=f"下偏移报警({len(alarm_minus)})")
    ax2.set_xlabel("序号", fontsize=10)
    ax2.set_ylabel("CUSUM", fontsize=10)
    ax2.legend(fontsize=8)
    fig.tight_layout()

    total_alarms = len(alarm_plus) + len(alarm_minus)
    summary = (
        f"CUSUM 检测到 {total_alarms} 次偏移报警 "
        f"(k={k}σ, h={h})。"
        f"上偏移: {len(alarm_plus)} 次，下偏移: {len(alarm_minus)} 次。"
    )

    return AnalysisResult(
        task="spc_cusum",
        tables={
            "cusum_stats": pd.DataFrame({
                "指标": ["均值(μ)", "标准差(σ)", "k (松弛因子)", "h (决策区间)",
                       "上偏移报警", "下偏移报警", "总报警"],
                "值": [f"{mu:.4f}", f"{sigma:.4f}", str(k), str(h),
                      str(len(alarm_plus)), str(len(alarm_minus)), str(total_alarms)],
            }),
        },
        figures=[fig],
        summary=summary,
        messages=warn_msgs,
        metadata={
            "mu": mu, "sigma": sigma, "k": k, "h": h,
            "alarm_plus": alarm_plus, "alarm_minus": alarm_minus,
            "total_alarms": total_alarms,
        },
    )


def ewma_chart(req: AnalysisRequest) -> AnalysisResult:
    """EWMA (指数加权移动平均) 控制图 — 对近期观测赋予更高权重。

    参数:
        lam: 平滑参数 (0<λ≤1)。λ越小越平滑，λ=1 等同于原始数据。常用 λ=0.2
        L: 控制限宽度 (常用 2.7~3.0)
        mu: 过程均值 (如未提供，从数据估计)
        sigma: 过程标准差 (如未提供，从数据估计)
    """
    data = req.data[req.target_col].dropna()
    if len(data) < 3:
        return AnalysisResult(
            task="spc_ewma", status="error",
            messages=["有效数据不足(至少3个点)"],
        )

    warn_msgs: list[str] = []
    mu = req.params.get("mu")
    sigma = req.params.get("sigma")
    if mu is not None and sigma is not None:
        mu, sigma = float(mu), float(sigma)
    else:
        mu = float(data.mean())
        sigma = float(data.std(ddof=1))
        warn_msgs.append(
            "⚠ μ/σ 从全部数据估计，若数据包含过程偏移会导致 EWMA 控制限偏大。"
            "建议通过参数 mu/sigma 指定已知受控状态的参数。"
        )
    if sigma < 1e-10:
        return AnalysisResult(
            task="spc_ewma", status="error",
            messages=["数据标准差接近零，无法计算 EWMA"],
        )

    lam = req.params.get("lam", 0.2)
    L = req.params.get("L", 2.7)
    if not 0 < lam <= 1:
        return AnalysisResult(
            task="spc_ewma", status="error",
            messages=[f"λ (平滑参数) 必须在 (0, 1] 范围内，当前值: {lam}"])

    n = len(data)
    ewma = np.zeros(n)
    # Montgomery 标准: z₁ = λ·x₁ + (1-λ)·μ, z₀ = μ 为初始值
    ewma[0] = lam * data.values[0] + (1 - lam) * mu

    for i in range(1, n):
        ewma[i] = lam * data.values[i] + (1 - lam) * ewma[i-1]

    # 控制限（随时间变化，但渐近稳定）
    # 渐近 σ_ewma = σ * sqrt(λ/(2-λ))
    sigma_ewma_asym = sigma * np.sqrt(lam / (2 - lam))
    # 时变 σ_ewma = σ * sqrt(λ/(2-λ) * [1 - (1-λ)^(2i)])
    t = np.arange(1, n + 1)
    corr = 1 - (1 - lam) ** (2 * t)
    sigma_ewma_t = sigma * np.sqrt(lam / (2 - lam) * corr)

    ucl_t = mu + L * sigma_ewma_t
    lcl_t = mu - L * sigma_ewma_t
    ucl_asym = mu + L * sigma_ewma_asym
    lcl_asym = mu - L * sigma_ewma_asym

    # 违规检测
    above = ewma > ucl_t
    below = ewma < lcl_t
    violations = above | below

    # 图表
    fig = Figure(figsize=(10, 6))
    ax = fig.add_subplot(111)
    pos = np.arange(n)

    ax.plot(pos, data.values, "o-", markersize=3, alpha=0.35,
            color=PALETTE["data"]["tertiary"], linewidth=0.8, label="原始数据")
    ax.plot(pos, ewma, "-", color=PALETTE["data"]["primary"], linewidth=2, label=f"EWMA (λ={lam})")
    ax.axhline(mu, color=PALETTE["center"]["primary"], linestyle="-", linewidth=1, label=f"CL={mu:.3f}")
    ax.plot(pos, ucl_t, "--", color=PALETTE["anomaly"]["primary"], linewidth=1, alpha=0.7, label="UCL(t)")
    ax.plot(pos, lcl_t, "--", color=PALETTE["anomaly"]["primary"], linewidth=1, alpha=0.7, label="LCL(t)")
    ax.axhline(ucl_asym, color=PALETTE["anomaly"]["primary"], linestyle=":", linewidth=1, alpha=0.4)
    ax.axhline(lcl_asym, color=PALETTE["anomaly"]["primary"], linestyle=":", linewidth=1, alpha=0.4)

    if violations.sum() > 0:
        vpos = np.where(violations)[0]
        ax.scatter(vpos, ewma[vpos], s=80, color=PALETTE["anomaly"]["primary"], marker="x",
                  linewidths=2, zorder=5, label=f"违规({violations.sum()}个)")

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"EWMA 控制图 — {req.target_col} (λ={lam}, L={L})",
        fontsize=11,
    )
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    fig.tight_layout()

    summary = (
        f"EWMA (λ={lam}, L={L}) 检测到 {int(violations.sum())} 个违规点。"
        f"渐近控制限: UCL={ucl_asym:.4f}, LCL={lcl_asym:.4f}"
    )

    return AnalysisResult(
        task="spc_ewma",
        tables={
            "ewma_stats": pd.DataFrame({
                "指标": ["均值(μ)", "标准差(σ)", "λ (平滑参数)", "L (控制限宽度)",
                       "渐近UCL", "渐近LCL", "违规点数"],
                "值": [f"{mu:.4f}", f"{sigma:.4f}", str(lam), str(L),
                      f"{ucl_asym:.4f}", f"{lcl_asym:.4f}",
                      str(int(violations.sum()))],
            }),
        },
        figures=[fig],
        summary=summary,
        messages=warn_msgs,
        metadata={
            "mu": mu, "sigma": sigma, "lam": lam, "L": L,
            "ucl_asym": float(ucl_asym), "lcl_asym": float(lcl_asym),
            "violations": int(violations.sum()),
        },
    )


def gage_rr(req: AnalysisRequest) -> AnalysisResult:
    """测量系统分析 (Gage R&R) — 评估量具的重复性和再现性。

    数据要求: target_col=测量值, feature_cols 中需含 "部件" 和 "操作员" 列。

    参数:
        part_col: 部件列名 (默认 feature_cols[0])
        operator_col: 操作员列名 (默认 feature_cols[1])
        tolerance: 公差范围 (用于 %P/T 计算，可选)
        sigma_multiplier: 研究变异乘数 (默认 5.15 = 99% 研究变异)
    """
    part_col = req.params.get("part_col", req.feature_cols[0] if len(req.feature_cols) > 0 else None)
    operator_col = req.params.get("operator_col", req.feature_cols[1] if len(req.feature_cols) > 1 else None)
    if not part_col or not operator_col:
        return AnalysisResult(task="gage_rr", status="error",
            messages=["需要提供部件列和操作员列"])

    sub = req.data[[req.target_col, part_col, operator_col]].dropna()
    if len(sub) < 10:
        return AnalysisResult(task="gage_rr", status="error",
            messages=["有效数据不足"])

    parts = sub[part_col].unique()
    operators = sub[operator_col].unique()
    k = len(operators)
    n_parts = len(parts)

    # 每部件每操作员的重复次数
    rep_counts = sub.groupby([part_col, operator_col]).size()
    r = int(rep_counts.mode().iloc[0]) if len(rep_counts) > 0 else 1

    # X-bar and R method
    # 每个操作员的 R-bar 和 X-bar
    op_stats = []
    for op in operators:
        op_data = sub[sub[operator_col] == op]
        ranges = op_data.groupby(part_col)[req.target_col].apply(lambda x: x.max() - x.min())
        r_bar_op = float(ranges.mean())
        x_bar_op = float(op_data[req.target_col].mean())
        op_stats.append({"操作员": op, "R-bar": r_bar_op, "X-bar": x_bar_op})

    # R-double-bar (average of operator R-bars)
    r_double_bar = float(np.mean([s["R-bar"] for s in op_stats]))
    x_bar_diff = float(np.max([s["X-bar"] for s in op_stats]) -
                       np.min([s["X-bar"] for s in op_stats]))

    # d2 constants for subgroup size r (ASTM E2282 / AIAG MSA standard table)
    d2_table = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534,
                7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078,
                11: 3.173, 12: 3.258, 13: 3.336, 14: 3.407, 15: 3.472,
                16: 3.532, 17: 3.588, 18: 3.640, 19: 3.689, 20: 3.735,
                21: 3.778, 22: 3.819, 23: 3.858, 24: 3.895, 25: 3.931,
                26: 3.964, 27: 3.997, 28: 4.027, 29: 4.056, 30: 4.084}
    d2_r = d2_table.get(r)
    if d2_r is None:
        # r=1 时无法估计重复性（极差未定义），回退到 r=2 的 d2=1.128
        # 并给出明确警告
        if r < 2:
            d2_r = 1.128
            logger.warning(
                "Gage R&R 重复次数 r=%d < 2，d2 使用回退值 %.3f (按 r=2 处理)。"
                "建议至少重复测量 2 次以获得可靠的重复性估计。",
                r, d2_r
            )
        else:
            # r > 30: 使用 Blom 近似公式 d2 ≈ 2 · Φ⁻¹((n-0.375)/(n+0.25))
            # 参考: Harter (1960), ASTM E2282。该公式在 n>30 时比 chi 分布均值
            # 近似（√2·Γ((n+1)/2)/Γ(n/2)）更准确（误差 <0.5% vs ~35%）
            _blom_arg = (r - 0.375) / (r + 0.25)
            d2_r = float(2.0 * sp_stats.norm.ppf(_blom_arg))
            logger.info(
                "Gage R&R 重复次数 r=%d > 30，d2 使用 Blom 近似 %.3f（标准表仅覆盖 2-30）",
                r, d2_r
            )

    sigma_mult = req.params.get("sigma_multiplier", 5.15)

    # Repeatability (EV)
    ev = r_double_bar / d2_r
    ev_pct = ev * sigma_mult

    # Reproducibility (AV)
    n_obs = n_parts * r
    d2_o = d2_table.get(k, 1.128)
    av = np.sqrt(max(0, (x_bar_diff / d2_o)**2 - ev**2 / n_obs))
    av_pct = av * sigma_mult

    # GRR
    grr = np.sqrt(ev**2 + av**2)
    grr_pct = grr * sigma_mult

    # Part Variation (PV)
    part_means = sub.groupby(part_col)[req.target_col].mean()
    rp = float(part_means.max() - part_means.min())
    d2_p = d2_table.get(n_parts)
    if d2_p is None:
        # 使用 Blom 近似公式（与 d2_r 一致）
        _blom_arg = (n_parts - 0.375) / (n_parts + 0.25)
        d2_p = float(2.0 * sp_stats.norm.ppf(_blom_arg))
    pv = rp / d2_p
    pv_pct = pv * sigma_mult

    # Total Variation
    tv = np.sqrt(grr**2 + pv**2)
    tv_pct = tv * sigma_mult

    # % contribution
    ev_contrib = (ev**2 / tv**2) * 100
    av_contrib = (av**2 / tv**2) * 100
    grr_contrib = (grr**2 / tv**2) * 100
    pv_contrib = (pv**2 / tv**2) * 100

    # % Study Variation (%SV)
    grr_sv = (grr / tv) * 100
    ev_sv = (ev / tv) * 100
    av_sv = (av / tv) * 100

    # ndc
    ndc = int(1.41 * pv / grr) if grr > 0 else 99

    # 判定
    if grr_sv < 10:
        judge = "优秀 (可接受)"
    elif grr_sv < 30:
        judge = "临界 (可能需要改进)"
    else:
        judge = "不合格 (需改进)"

    # 可视化
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    components = ["重复性(EV)", "再现性(AV)", "GRR", "部件间(PV)"]
    values_pct = [ev_pct, av_pct, grr_pct, pv_pct]
    ax.barh(components, values_pct, color=[PALETTE["data"]["secondary"], PALETTE["data"]["tertiary"], PALETTE["data"]["primary"], PALETTE["contrast"]["b"]])
    ax.axvline(tv_pct, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, label=f"TV={tv_pct:.3f}")
    ax.set_xlabel(f"{sigma_mult:.1f}σ 研究变异", fontsize=10)
    ax.set_title(
        f"Gage R&R — {req.target_col} | %GRR={grr_sv:.1f}%, ndc={ndc} | {judge}",
        fontsize=10,
    )
    ax.legend(fontsize=8)
    fig.tight_layout()

    summary = (
        f"Gage R&R: %GRR={grr_sv:.1f}% ({judge}), ndc={ndc}。"
        f"EV={ev:.4f}, AV={av:.4f}, PV={pv:.4f}"
    )

    return AnalysisResult(
        task="gage_rr",
        tables={
            "gage_rr_results": pd.DataFrame({
                "变异源": ["重复性 (EV)", "再现性 (AV)", "GRR (量具)", "部件间 (PV)", "总计 (TV)"],
                "标准差": [f"{ev:.4f}", f"{av:.4f}", f"{grr:.4f}", f"{pv:.4f}", f"{tv:.4f}"],
                f"{sigma_mult:.1f}σ变异": [f"{ev_pct:.4f}", f"{av_pct:.4f}",
                                       f"{grr_pct:.4f}", f"{pv_pct:.4f}", f"{tv_pct:.4f}"],
                "贡献率(%)": [f"{ev_contrib:.1f}", f"{av_contrib:.1f}",
                            f"{grr_contrib:.1f}", f"{pv_contrib:.1f}", "100"],
                "%SV": [f"{ev_sv:.1f}", f"{av_sv:.1f}", f"{grr_sv:.1f}", "—", "—"],
            }),
            "ndc": pd.DataFrame({"指标": ["ndc (可区分类别数)", "判定"],
                                "值": [str(ndc), judge]}),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "ev": ev, "av": av, "grr": grr, "pv": pv, "tv": tv,
            "grr_sv": grr_sv, "ndc": ndc, "judge": judge,
            "n_parts": n_parts, "n_operators": k, "n_replicates": r,
        },
    )


def tolerance_interval(req: AnalysisRequest) -> AnalysisResult:
    """统计容许区间 — 以指定置信度覆盖总体指定比例的区间。

    参数:
        coverage: 覆盖比例 (默认 0.99，即 99% 总体)
        confidence: 置信水平 (默认 0.95)
        side: "two-sided" | "upper" | "lower"

    用于设定合理规格限，不同于置信区间（均值的不确定性）。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 5:
        return AnalysisResult(
            task="tolerance_interval", status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    coverage = req.params.get("coverage", 0.99)
    confidence = req.params.get("confidence", 0.95)
    side = req.params.get("side", "two-sided")
    mu = float(data.mean())
    sigma = float(data.std(ddof=1))

    from math import sqrt

    if side == "two-sided":
        # 双侧容许区间的 k 因子 (Howe 近似)
        z_p = sp_stats.norm.ppf((1 + coverage) / 2)
        chi_sq = sp_stats.chi2.ppf(1 - confidence, n - 1)
        k = sqrt((n - 1) * (1 + 1/n) * z_p**2 / chi_sq)
        lower = mu - k * sigma
        upper = mu + k * sigma
        label = (f"{coverage*100:.0f}% 总体以 {confidence*100:.0f}% 置信度落在 "
                 f"[{lower:.4f}, {upper:.4f}]")
    elif side == "upper":
        # 单侧上限
        delta = sp_stats.norm.ppf(coverage) * sqrt(n)
        t_val = sp_stats.nct.ppf(confidence, n - 1, delta) / sqrt(n)
        k_upper = t_val
        upper = mu + k_upper * sigma
        lower = float("-inf")
        label = f"{coverage*100:.0f}% 总体 ≤ {upper:.4f} ({confidence*100:.0f}% 置信)"
    else:
        # 单侧下限
        delta = sp_stats.norm.ppf(coverage) * sqrt(n)
        t_val = sp_stats.nct.ppf(confidence, n - 1, delta) / sqrt(n)
        k_lower = t_val
        lower = mu - k_lower * sigma
        upper = float("inf")
        label = f"{coverage*100:.0f}% 总体 ≥ {lower:.4f} ({confidence*100:.0f}% 置信)"

    # 可视化
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot(111)
    ax.hist(data, bins=min(30, int(sqrt(n))*2), density=True,
            color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.7)
    x_fit = np.linspace(data.min() - 2*sigma, data.max() + 2*sigma, 200)
    ax.plot(x_fit, sp_stats.norm.pdf(x_fit, mu, sigma), "-", color=PALETTE["data"]["primary"], linewidth=2)
    if side != "upper":
        ax.axvline(lower, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=2)
    if side != "lower":
        ax.axvline(upper, color=PALETTE["center"]["primary"], linestyle="--", linewidth=2)
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_title(f"容许区间 — {label}", fontsize=10)
    fig.tight_layout()

    return AnalysisResult(
        task="tolerance_interval",
        tables={
            "tolerance_limits": pd.DataFrame({
                "参数": ["样本量", "均值", "标准差", "覆盖比例", "置信水平",
                        "下限", "上限", "区间类型"],
                "值": [str(n), f"{mu:.4f}", f"{sigma:.4f}",
                      f"{coverage:.1%}", f"{confidence:.1%}",
                      f"{lower:.4f}" if lower > float("-inf") else "-∞",
                      f"{upper:.4f}" if upper < float("inf") else "+∞",
                      side],
            }),
        },
        figures=[fig],
        summary=label,
        metadata={
            "mu": mu, "sigma": sigma, "n": n,
            "lower": lower, "upper": upper,
            "coverage": coverage, "confidence": confidence, "side": side,
        },
    )


def survival_analysis(req: AnalysisRequest) -> AnalysisResult:
    """Kaplan-Meier 生存分析 + Weibull 拟合 — 适用于右删失寿命数据。

    target_col: 时间/寿命列
    feature_cols[0]: 事件指示列 (1=失效, 0=删失)
    feature_cols[1] (可选): 分组列 (用于 Log-rank 检验)
    """
    time_col = req.target_col
    event_col = req.feature_cols[0] if len(req.feature_cols) > 0 else None
    group_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None

    if not event_col or event_col not in req.data.columns:
        return AnalysisResult(task="survival_analysis", status="error",
            messages=["需要提供事件指示列 (1=失效, 0=删失)"])

    sub = req.data[[time_col, event_col] + ([group_col] if group_col else [])].dropna()
    times = sub[time_col].values
    # 自动二值化事件列：支持 0/1 数值和 "是"/"否" 等文本
    try:
        events = sub[event_col].values.astype(int)
    except (ValueError, TypeError):
        unique_vals = sub[event_col].unique()
        if len(unique_vals) == 2:
            events = (sub[event_col] == sorted(unique_vals)[-1]).astype(int).values
        else:
            return AnalysisResult(task="survival_analysis", status="error",
                messages=[f"事件列「{event_col}」需要恰好2个不同值(0/1 或 是/否)，当前有{len(unique_vals)}个"])

    # KM 估计 (全样本)
    unique_times = np.sort(np.unique(times[events == 1]))
    n_total = len(times)
    km_times = [0.0]
    km_survival_val = [1.0]

    for t in unique_times:
        n_events = int(np.sum((times == t) & (events == 1)))
        at_risk = int(np.sum(times >= t))  # 直接计算风险集，正确计入事件间删失
        if at_risk > 0 and n_events > 0:
            km_survival_val.append(km_survival_val[-1] * (1 - n_events / at_risk))
            km_times.append(float(t))

    # 中位生存时间
    median_idx = np.where(np.array(km_survival_val) <= 0.5)[0]
    median_survival = float(km_times[median_idx[0]]) if len(median_idx) > 0 else None

    # Weibull 拟合 (仅失效数据；注：scipy 不支持删失数据 MLE，结果有偏)
    fail_times = times[events == 1]
    weibull_shape, weibull_scale = None, None
    if len(fail_times) >= 5:
        try:
            shape, loc, scale = sp_stats.weibull_min.fit(fail_times, floc=0)
            weibull_shape = float(shape)
            weibull_scale = float(scale)
        except Exception:
            logger.debug("Weibull fit failed in survival_analysis", exc_info=True)

    # Log-rank 检验 (分组比较)
    logrank_result = None
    if group_col and group_col in sub.columns:
        groups = sub[group_col].unique()
        if len(groups) == 2:
            g1 = sub[sub[group_col] == groups[0]]
            g2 = sub[sub[group_col] == groups[1]]
            # 简化 Log-rank
            all_event_times = np.sort(np.unique(
                np.concatenate([g1[time_col][g1[event_col]==1],
                               g2[time_col][g2[event_col]==1]])
            ))
            # Log-rank: 单次遍历计算 O/E 和方差
            O1_sum, E1_sum, v1 = 0.0, 0.0, 0.0
            for t in all_event_times:
                o1 = int(((g1[time_col] == t) & (g1[event_col] == 1)).sum())
                o2 = int(((g2[time_col] == t) & (g2[event_col] == 1)).sum())
                r1_t = int((g1[time_col] >= t).sum())
                r2_t = int((g2[time_col] >= t).sum())
                total_o = o1 + o2
                total_r = r1_t + r2_t
                if total_r > 0:
                    e1 = total_o * r1_t / total_r
                    O1_sum += o1
                    E1_sum += e1
                if total_r > 1:
                    v1 += total_o * (total_r - total_o) * r1_t * r2_t / (total_r**2 * (total_r - 1) + 1e-10)
            z_lr = (O1_sum - E1_sum) / np.sqrt(v1 + 1e-10)
            lr_p = float(2 * sp_stats.norm.sf(abs(z_lr)))
            logrank_result = {
                "分组": f"{groups[0]} vs {groups[1]}",
                "Log-rank Z": round(float(z_lr), 3),
                "p值": round(lr_p, 4),
                "显著": "是" if lr_p < 0.05 else "否",
            }

    # 可视化
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.step(km_times, km_survival_val, where="post", color=PALETTE["data"]["primary"], linewidth=2.5,
            label=f"KM (n={n_total})")
    ax.axhline(0.5, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.8, alpha=0.5)
    if median_survival:
        ax.axvline(median_survival, color=PALETTE["target"]["primary"], linestyle="--", linewidth=1,
                   label=f"中位寿命={median_survival:.0f}")
    # Weibull 拟合曲线
    if weibull_shape and weibull_scale:
        x_w = np.linspace(0, max(times) * 1.2, 200)
        s_w = 1 - sp_stats.weibull_min.cdf(x_w, weibull_shape, 0, weibull_scale)
        ax.plot(x_w, s_w, "--", color=PALETTE["data"]["secondary"], linewidth=1.5, alpha=0.7,
                label=f"Weibull (β={weibull_shape:.2f}, η={weibull_scale:.0f})")

    # 删失标记
    cens_times = times[events == 0]
    ax.scatter(cens_times, np.ones(len(cens_times)), marker="|", s=30, color=PALETTE["spec"]["tertiary"],
              alpha=0.5, label=f"删失 ({len(cens_times)})")

    ax.set_xlabel("时间", fontsize=10)
    ax.set_ylabel("生存概率", fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.set_title(
        f"Kaplan-Meier 生存曲线 — {req.target_col}"
        + (f" | {logrank_result['分组']} p={logrank_result['p值']}" if logrank_result else ""),
        fontsize=10,
    )
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()

    summary_parts = [f"KM: 中位寿命={median_survival:.0f}" if median_survival else "KM: 中位寿命未达到"]
    if weibull_shape:
        summary_parts.append(f"Weibull β={weibull_shape:.2f}, η={weibull_scale:.0f}")
    if logrank_result:
        summary_parts.append(f"Log-rank: {logrank_result['分组']} p={logrank_result['p值']}")
    summary = "；".join(summary_parts)

    tables = {
        "km_survival": pd.DataFrame({
            "时间": km_times,
            "生存概率": [f"{s:.4f}" for s in km_survival_val],
        }),
    }
    if logrank_result:
        tables["logrank_test"] = pd.DataFrame([logrank_result])

    return AnalysisResult(
        task="survival_analysis",
        tables=tables,
        figures=[fig],
        summary=summary,
        metadata={
            "median_survival": median_survival,
            "n_total": n_total, "n_events": int(events.sum()),
            "n_censored": int((events == 0).sum()),
            "weibull_shape": weibull_shape,
            "weibull_scale": weibull_scale,
            "logrank_p": logrank_result["p值"] if logrank_result else None,
        },
    )


def change_point_detect(req: AnalysisRequest) -> AnalysisResult:
    """变点检测 — 基于 CUSUM 的二元分割法，识别过程结构性变化。

    返回变点位置列表和分段统计。
    参数:
        min_segment: 最小段长度 (默认 10)
        n_changepoints: 最多检测的变点数 (默认 5)
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 20:
        return AnalysisResult(
            task="change_point", status="error",
            messages=["有效数据不足(至少20个点)"],
        )

    min_segment = req.params.get("min_segment", max(10, n // 20))
    max_cp = req.params.get("n_changepoints", 5)
    min_peak_ratio = req.params.get("min_peak_ratio", 0.1)

    values = data.values
    changepoints: list[int] = []
    segments_for_split = [(0, n)]

    # 二元分割：每次在段内找最大 CUSUM 位置
    while len(changepoints) < max_cp and segments_for_split:
        best_cp = None
        best_stat = 0
        best_seg_idx = -1

        for seg_i, (start, end) in enumerate(segments_for_split):
            seg_len = end - start
            if seg_len < 2 * min_segment:
                continue
            seg_vals = values[start:end]
            seg_mean = np.mean(seg_vals)
            # CUSUM 统计量
            cumsum = np.cumsum(seg_vals - seg_mean)
            cusum_abs = np.abs(cumsum)
            # 限制搜索范围在 min_segment ~ seg_len-min_segment 之间
            search_start = min_segment
            search_end = seg_len - min_segment
            if search_end <= search_start:
                continue
            peak_idx = np.argmax(cusum_abs[search_start:search_end]) + search_start
            peak_val = cusum_abs[peak_idx]

            if peak_val > best_stat:
                best_stat = peak_val
                best_cp = start + peak_idx
                best_seg_idx = seg_i

        if best_cp is not None and best_cp not in changepoints:
            # 检查峰值是否超过数据变化范围的最小比例
            seg_start, seg_end = segments_for_split[best_seg_idx]
            segment_vals = values[seg_start:seg_end]
            data_range = float(np.max(segment_vals) - np.min(segment_vals))
            if data_range > 0 and best_stat < min_peak_ratio * data_range:
                break
            changepoints.append(best_cp)
            old_start, old_end = segments_for_split[best_seg_idx]
            segments_for_split.pop(best_seg_idx)
            segments_for_split.append((old_start, best_cp))
            segments_for_split.append((best_cp, old_end))
        else:
            break

    changepoints.sort()

    # ── 分段统计 ──
    if not changepoints:
        # 无变点：只有一个段
        segment_stats = [{
            "段": 1, "起始": 0, "结束": n - 1, "样本数": n,
            "均值": f"{float(np.mean(values)):.4f}",
            "标准差": f"{float(np.std(values, ddof=1)):.4f}",
        }]
        summary = f"未检测到显著变点，过程整体平稳 (n={n})"
    else:
        segment_stats = []
        boundaries = [0] + changepoints + [n]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_vals = values[start:end]
            if len(seg_vals) > 0:
                segment_stats.append({
                    "段": seg_i + 1,
                    "起始": start,
                    "结束": end - 1,
                    "样本数": end - start,
                    "均值": f"{float(np.mean(seg_vals)):.4f}",
                    "标准差": f"{float(np.std(seg_vals, ddof=1)):.4f}",
                    "变化方向": (
                        "↑ 上升" if seg_i > 0 and float(np.mean(seg_vals)) >
                        float(np.mean(values[boundaries[seg_i-1]:boundaries[seg_i]]))
                        else "↓ 下降" if seg_i > 0 else "—"
                    ),
                })
        cp_positions = ", ".join(str(cp) for cp in changepoints)
        summary = (
            f"检测到 {len(changepoints)} 个变点 (位置: {cp_positions})，"
            f"过程分为 {len(segment_stats)} 段"
        )

    # ── 可视化 ──
    fig = Figure(figsize=(12, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    ax.plot(pos, values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.7, label="数据")

    # 分段均值线
    if changepoints:
        boundaries = [0] + changepoints + [n]
        colors = [PALETTE["data"]["primary"], PALETTE["target"]["primary"], PALETTE["center"]["primary"], PALETTE["contrast"]["d"], PALETTE["contrast"]["b"]]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_mean = float(np.mean(values[start:end]))
            ax.plot([start, end - 1], [seg_mean, seg_mean], "-",
                   color=colors[seg_i % len(colors)], linewidth=2.5,
                   label=f"段{seg_i+1} μ={seg_mean:.3f}")

    # 标记变点
    for cp in changepoints:
        ax.axvline(cp, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5, alpha=0.8)
        ax.annotate(f"变点{cp}", xy=(cp, values[cp]),
                   xytext=(cp + 5, values[cp] + 0.5 * np.std(values)),
                   fontsize=8, color=PALETTE["anomaly"]["primary"],
                   arrowprops=dict(arrowstyle="->", color=PALETTE["anomaly"]["primary"], lw=0.8))

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"变点检测 — {req.target_col} | "
        f"{len(changepoints)} 个变点, {len(segment_stats)} 段",
        fontsize=11,
    )
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    fig.tight_layout()

    return AnalysisResult(
        task="change_point",
        tables={"segment_statistics": pd.DataFrame(segment_stats)},
        figures=[fig],
        summary=summary,
        metadata={
            "changepoints": changepoints,
            "n_changepoints": len(changepoints),
            "n_segments": len(segment_stats),
            "n": n,
        },
    )


def outlier_consensus(req: AnalysisRequest) -> AnalysisResult:
    """多方法异常检测共识 — 组合 IQR、Z-score、Isolation Forest 投票判定。

    只有当 ≥2 种方法都判定为异常时，才标记为"高置信异常"。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 10:
        return AnalysisResult(
            task="outlier_consensus", status="error",
            messages=["有效数据不足(至少10个点)"],
        )

    # ── 方法 1: IQR ──
    Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
    IQR = Q3 - Q1
    iqr_mask = (data < Q1 - 1.5 * IQR) | (data > Q3 + 1.5 * IQR)

    # ── 方法 2: Z-score ──
    z_scores = np.abs((data - data.mean()) / (data.std(ddof=1) + 1e-10))
    z_mask = z_scores > 3

    # ── 方法 3: Isolation Forest ──
    try:
        from sklearn.ensemble import IsolationForest
        iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
        if len(req.feature_cols) > 0:
            feature_cols = [c for c in req.feature_cols if c in req.data.columns]
            sub = req.data[feature_cols + [req.target_col]].dropna()
            common_idx = data.index.intersection(sub.index)
            iso_preds = iso.fit_predict(sub.loc[common_idx, feature_cols + [req.target_col]].values)
            iso_mask = pd.Series(False, index=data.index)
            for i, idx in enumerate(common_idx):
                iso_mask[idx] = iso_preds[i] == -1
        else:
            X = data.values.reshape(-1, 1)
            iso_preds = iso.fit_predict(X)
            iso_mask = pd.Series(iso_preds == -1, index=data.index)
    except (ValueError, RuntimeError, ImportError):
        logger.debug("IsolationForest failed in outlier_consensus", exc_info=True)
        iso_mask = pd.Series(False, index=data.index)

    # ── 投票: ≥2 票 → 高置信异常 ──
    votes = iqr_mask.astype(int) + z_mask.astype(int) + iso_mask.astype(int)
    high_conf = votes >= 2
    any_flag = votes >= 1

    # ── 结果表 ──
    anomaly_rows = []
    for i, idx in enumerate(data.index):
        if any_flag.iloc[i]:
            anomaly_rows.append({
                "序号": idx,
                req.target_col: round(float(data.iloc[i]), 4),
                "IQR": "是" if iqr_mask.iloc[i] else "否",
                "Z-Score": "是" if z_mask.iloc[i] else "否",
                "IsoForest": "是" if iso_mask.iloc[i] else "否",
                "投票数": int(votes.iloc[i]),
                "置信度": "高 (≥2票)" if high_conf.iloc[i] else "低 (1票)",
            })

    # ── 可视化 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.6)
    ax.scatter(pos, data.values, s=12, color=PALETTE["data"]["primary"], alpha=0.6)

    # 低置信 (1票)
    low_conf_pos = np.where(any_flag & ~high_conf)[0]
    if len(low_conf_pos) > 0:
        ax.scatter(low_conf_pos, data.values[low_conf_pos], s=60,
                  color=PALETTE["spec"]["secondary"], marker="s", facecolors="none", linewidths=1.5,
                  zorder=4, label=f"低置信 (1票, {len(low_conf_pos)}个)")

    # 高置信 (≥2票)
    high_conf_pos = np.where(high_conf)[0]
    if len(high_conf_pos) > 0:
        ax.scatter(high_conf_pos, data.values[high_conf_pos], s=100,
                  color=PALETTE["anomaly"]["primary"], marker="x", linewidths=3, zorder=5,
                  label=f"高置信 (≥2票, {len(high_conf_pos)}个)")

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"多方法异常共识 — {req.target_col} | "
        f"高置信={int(high_conf.sum())}, 总标记={int(any_flag.sum())}",
        fontsize=11,
    )
    ax.legend(fontsize=8)
    fig.tight_layout()

    summary = (
        f"异常共识: {int(any_flag.sum())} 个标记, "
        f"{int(high_conf.sum())} 个高置信(≥2票)。"
        f"方法: IQR({int(iqr_mask.sum())}), Z-score({int(z_mask.sum())}), "
        f"IsoForest({int(iso_mask.sum())})"
    )

    return AnalysisResult(
        task="outlier_consensus",
        tables={
            "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows
            else pd.DataFrame(),
            "method_counts": pd.DataFrame({
                "方法": ["IQR", "Z-Score", "Isolation Forest", "高置信(≥2票)", "任意标记"],
                "检测数": [int(iqr_mask.sum()), int(z_mask.sum()),
                         int(iso_mask.sum()), int(high_conf.sum()),
                         int(any_flag.sum())],
            }),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "iqr_count": int(iqr_mask.sum()),
            "zscore_count": int(z_mask.sum()),
            "isoforest_count": int(iso_mask.sum()),
            "high_confidence_count": int(high_conf.sum()),
            "total_flagged": int(any_flag.sum()),
        },
    )


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """异常检测：IQR / Z-score (单变量) 或 Isolation Forest (多变量)。"""
    method = req.params.get("method", "iqr")

    # ── 多变量异常检测 (Isolation Forest) ──
    if method == "isolation_forest":
        feature_cols = [c for c in req.feature_cols if c in req.data.columns]
        if not feature_cols:
            feature_cols = [req.target_col]
        sub = req.data[feature_cols].dropna()
        if len(sub) < 5:
            return AnalysisResult(
                task="anomaly_detect", status="error",
                messages=["有效样本不足(至少需要5个完整观测)"],
            )
        from sklearn.ensemble import IsolationForest
        contamination = req.params.get("contamination", 0.05)
        try:
            iso = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100,
            )
            preds = iso.fit_predict(sub.values)
            scores = iso.decision_function(sub.values)
            # preds: 1=正常, -1=异常
            mask = preds == -1
        except Exception:
            return AnalysisResult(
                task="anomaly_detect", status="error",
                messages=["Isolation Forest 模型拟合失败"],
            )

        anomalies = req.data.loc[sub.index[mask]] if mask.sum() > 0 else pd.DataFrame()

        # 多变量可视化：取前两个特征做散点图 + 异常高亮
        fig = Figure(figsize=(10, 5))
        if len(feature_cols) >= 2:
            ax1 = fig.add_subplot(1, 2, 1)
            c1, c2 = feature_cols[0], feature_cols[1]
            normal_mask = ~mask
            ax1.scatter(sub.loc[normal_mask, c1], sub.loc[normal_mask, c2],
                       s=20, alpha=0.5, color=PALETTE["data"]["secondary"], label=f"正常 ({normal_mask.sum()})")
            if mask.sum() > 0:
                ax1.scatter(sub.loc[mask, c1], sub.loc[mask, c2],
                           s=60, alpha=0.9, color=PALETTE["anomaly"]["primary"], marker="x",
                           linewidths=2, label=f"异常 ({mask.sum()})")
            ax1.set_xlabel(c1, fontsize=9)
            ax1.set_ylabel(c2, fontsize=9)
            ax1.set_title("多变量异常检测 (Isolation Forest)", fontsize=10)
            ax1.legend(fontsize=8)

            # 异常分数分布
            ax2 = fig.add_subplot(1, 2, 2)
        else:
            ax2 = fig.add_subplot(111)
        ax2.hist(scores[~mask], bins=20, alpha=0.7, color=PALETTE["data"]["secondary"],
                label=f"正常 (n={(~mask).sum()})")
        if mask.sum() > 0:
            ax2.hist(scores[mask], bins=10, alpha=0.8, color=PALETTE["target"]["primary"],
                    label=f"异常 (n={mask.sum()})")
        ax2.axvline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, label="决策边界")
        ax2.set_xlabel("异常分数 (越低越异常)", fontsize=9)
        ax2.set_ylabel("频数", fontsize=9)
        ax2.set_title("异常分数分布", fontsize=10)
        ax2.legend(fontsize=8)
        fig.tight_layout()

        # 异常详情表（含异常分数）
        anomaly_rows = []
        if mask.sum() > 0:
            for i, idx in enumerate(sub.index[mask]):
                row_data = {"异常分数": round(float(scores[mask][i]), 4)}
                for c in feature_cols:
                    row_data[c] = req.data.loc[idx, c]
                anomaly_rows.append(row_data)

        return AnalysisResult(
            task="anomaly_detect",
            tables={
                "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows
                else pd.DataFrame(),
            },
            figures=[fig],
            summary=(
                f"Isolation Forest 检测到 {mask.sum()} 个多变量异常点 "
                f"(污染率={contamination:.1%}, 维度={len(feature_cols)})"
            ),
            metadata={
                "anomaly_count": int(mask.sum()),
                "method": "isolation_forest",
                "contamination": contamination,
                "feature_dim": len(feature_cols),
            },
        )

    # ── 单变量异常检测 (IQR / Z-score) ──
    data = req.data[req.target_col].dropna()
    data_std = data.std(ddof=1)  # 统一计算，供所有方法和可视化使用
    if len(data) < 5:
        return AnalysisResult(
            task="anomaly_detect",
            status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    if method == "grubbs":
        # Grubbs 检验：每次检测最大偏差，迭代最多 5 个异常点
        alpha_g = req.params.get("alpha", 0.05)
        max_outliers = req.params.get("max_outliers", 5)
        vals = data.values.copy()
        mask = np.zeros(len(data), dtype=bool)
        keep_idx = np.arange(len(data))
        for _ in range(max_outliers):
            mu = np.mean(vals)
            sigma = np.std(vals, ddof=1)
            if sigma < 1e-10:
                break
            g_scores = np.abs(vals - mu) / sigma
            max_idx = np.argmax(g_scores)
            G = g_scores[max_idx]
            n_remain = len(vals)
            if n_remain < 3:
                break
            t_crit = sp_stats.t.ppf(1 - alpha_g / (2 * n_remain), n_remain - 2)
            G_crit = (n_remain - 1) / np.sqrt(n_remain) * np.sqrt(
                t_crit**2 / (n_remain - 2 + t_crit**2)
            )
            if G > G_crit:
                mask[keep_idx[max_idx]] = True
                vals = np.delete(vals, max_idx)
                keep_idx = np.delete(keep_idx, max_idx)
            else:
                break
    elif method == "iqr":
        Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
        IQR = Q3 - Q1
        if IQR == 0:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据无变化(IQR=0)，无法检测异常"],
            )
        mask = (data < Q1 - 1.5 * IQR) | (data > Q3 + 1.5 * IQR)
    else:
        if data_std < 1e-10:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据标准差接近零，无法进行 Z-score 异常检测"],
            )
        z = np.abs((data - data.mean()) / data_std)
        mask = z > 3

    idx = data.index[mask]
    anomalies = req.data.loc[idx] if mask.sum() > 0 else pd.DataFrame()

    # 异常检测散点图
    fig = Figure(figsize=(9, 4))
    ax = fig.add_subplot(111)
    pos = np.arange(len(data))
    ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, label="数据")
    ax.scatter(pos, data.values, s=10, color=PALETTE["data"]["primary"])
    if mask.sum() > 0:
        anomaly_pos = np.where(mask)[0]
        ax.scatter(anomaly_pos, data.values[mask], s=80, color=PALETTE["anomaly"]["primary"],
                   marker="x", linewidths=2.5, zorder=5, label=f"异常({mask.sum()}个)")
        if method == "iqr":
            ax.axhline(Q1 - 1.5 * IQR, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"下界={Q1-1.5*IQR:.3f}")
            ax.axhline(Q3 + 1.5 * IQR, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"上界={Q3+1.5*IQR:.3f}")
        else:
            ax.axhline(data.mean() + 3*data_std, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"上界={data.mean()+3*data_std:.3f}")
            ax.axhline(data.mean() - 3*data_std, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"下界={data.mean()-3*data_std:.3f}")
    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(f"异常检测 — {req.target_col} (方法: {method})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()

    return AnalysisResult(
        task="anomaly_detect",
        tables={"anomalies": anomalies},
        figures=[fig],
        summary=f"检测到 {mask.sum()} 个异常点 (方法: {method})",
        metadata={"anomaly_count": int(mask.sum()), "method": method},
    )


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
    ax.legend(fontsize=8)
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
    n_boot = min(req.params.get("n_bootstrap", 2000), 10000)
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
    ax.legend(fontsize=8)
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
    """
    if len(req.feature_cols) < 1:
        return AnalysisResult(task="box_chart", status="error",
            messages=["需要至少 1 个分类列作为分组依据"])

    group_col = req.feature_cols[0]
    sub_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None
    mode = req.params.get("mode", "facet")  # "facet" | "nested"

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
            ax.tick_params(labelsize=7)
    else:
        fig = Figure(figsize=(max(len(groups)*1.2, 6), 5))
        ax = fig.add_subplot(111)
        bp = ax.boxplot(group_data,
                       tick_labels=[f"{g}\n(n={len(d)})"
                                   for g, d in zip(groups, group_data)],
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
    fig.tight_layout()

    n_total = len(sub)
    summary = (
        f"{req.target_col} 按 {group_col} 分组 (共 {len(groups)} 组, n={n_total})。"
        + (f" {test_note}。" if test_note else "")
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
        },
    )


# ── 注册非参数控制图 ──
# (函数在文件末尾定义, 此处确保被导出)

def spc_nonparametric(req: AnalysisRequest) -> AnalysisResult:
    """非参数控制图 — 基于最佳拟合分布的 CDF 逆推控制限，不假设正态。

    方法与标准 SPC (±3σ) 不同：
    1. 自动拟合 Normal / Lognormal / Weibull 三种分布，选 KS 检验最优者
    2. 用拟合分布的 CDF 逆函数 (PPF) 精确计算控制限
    3. 适用于偏态/非对称数据，且不受样本量限制

    参数:
        side: "two-sided"(默认) | "upper"(越小越好,只设上限) | "lower"(越大越好,只设下限)
    """
    data = req.data[req.target_col].dropna()
    n = len(data)

    if n < 10:
        return AnalysisResult(task="spc_nonparametric", status="error",
            messages=[f"有效数据不足(至少10个点, 当前{n}个)"])

    side = req.params.get("side", "two-sided")
    values = data.values

    # ── 1. 分布拟合 (Normal / Lognormal / Weibull) ──
    fits = {}
    # Normal
    mu, sigma = sp_stats.norm.fit(values)
    ks_n = sp_stats.kstest(values, "norm", args=(mu, sigma))
    fits["Normal"] = {"dist": sp_stats.norm, "args": (mu, sigma), "ks_p": ks_n.pvalue}

    # Lognormal
    if (values > 0).all():
        shape_ln, loc_ln, scale_ln = sp_stats.lognorm.fit(values, floc=0)
        ks_ln = sp_stats.kstest(values, "lognorm", args=(shape_ln, 0, scale_ln))
        fits["Lognormal"] = {"dist": sp_stats.lognorm, "args": (shape_ln, 0, scale_ln),
                            "ks_p": ks_ln.pvalue}

    # Weibull
    if (values > 0).all():
        try:
            shape_w, loc_w, scale_w = sp_stats.weibull_min.fit(values, floc=0)
            ks_w = sp_stats.kstest(values, "weibull_min", args=(shape_w, 0, scale_w))
            fits["Weibull"] = {"dist": sp_stats.weibull_min, "args": (shape_w, 0, scale_w),
                              "ks_p": ks_w.pvalue}
        except Exception:
            logger.debug("Weibull fit failed in spc_nonparametric", exc_info=True)

    # 选 KS p 值最大的（拟合最优）
    best_name = max(fits, key=lambda k: fits[k]["ks_p"])
    best = fits[best_name]
    dist = best["dist"]
    args = best["args"]

    # ── 2. 用拟合分布 PPF (CDF 逆函数) 计算控制限 ──
    cl = float(dist.median(*args))

    def _ppf(p):
        """安全 PPF，防止极端值溢出"""
        try:
            return float(dist.ppf(p, *args))
        except Exception:
            return float(np.percentile(values, p * 100))

    if side == "upper":
        ucl = _ppf(0.99865)
        ucl_2s = _ppf(0.97725)
        ucl_1s = _ppf(0.8413)
        lcl = lcl_2s = lcl_1s = None
        violations = list(np.where(values > ucl)[0])
        side_note = f"单侧上限 (越小越好, 拟合={best_name})"
    elif side == "lower":
        lcl = _ppf(0.00135)
        lcl_2s = _ppf(0.02275)
        lcl_1s = _ppf(0.1587)
        ucl = ucl_2s = ucl_1s = None
        violations = list(np.where(values < lcl)[0])
        side_note = f"单侧下限 (越大越好, 拟合={best_name})"
    else:
        ucl = _ppf(0.99865)
        lcl = _ppf(0.00135)
        ucl_2s = _ppf(0.97725)
        lcl_2s = _ppf(0.02275)
        ucl_1s = _ppf(0.8413)
        lcl_1s = _ppf(0.1587)
        violations = sorted(set(
            list(np.where(values > ucl)[0]) + list(np.where(values < lcl)[0])
        ))
        side_note = f"双侧控制限 (拟合={best_name})"

    limit_label = []
    if ucl is not None:
        limit_label.append(f"UCL={ucl:.4f}")
    if lcl is not None:
        limit_label.append(f"LCL={lcl:.4f}")
    limit_label = " / ".join(limit_label) if limit_label else "N/A"

    # 偏度评估
    skew_val = float(data.skew())
    if abs(skew_val) > 0.5:
        asym_parts = [f"数据偏度={skew_val:.2f}({'右偏' if skew_val > 0 else '左偏'})"]
        if ucl is not None:
            asym_parts.append(f"上限距中位数={ucl-cl:.3f}")
        if lcl is not None:
            asym_parts.append(f"下限距中位数={cl-lcl:.3f}")
        asym_note = "，".join(asym_parts)
    else:
        asym_note = f"数据近似对称(偏度={skew_val:.2f})"

    # ── 图表 ──
    fig = Figure(figsize=(12, 7))
    pos = np.arange(n)
    ax = fig.add_subplot(111)

    ax.plot(pos, values, "o-", markersize=3, color=PALETTE["data"]["primary"], linewidth=1, alpha=0.6, label="数据")
    ax.axhline(cl, color=PALETTE["center"]["primary"], linestyle="-", linewidth=2, label=f"CL (中位数)={cl:.4f}")

    if ucl is not None:
        ax.axhline(ucl, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5,
                   label=f"UCL (P99.865)={ucl:.4f}")
        if ucl_2s:
            ax.axhline(ucl_2s, color=PALETTE["target"]["primary"], linestyle=":", linewidth=0.8, alpha=0.6)
        if ucl_1s:
            ax.axhline(ucl_1s, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)
        ax.fill_between(pos, cl, ucl, alpha=0.04, color=PALETTE["center"]["primary"])

    if lcl is not None:
        ax.axhline(lcl, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5,
                   label=f"LCL (P0.135)={lcl:.4f}")
        if lcl_2s:
            ax.axhline(lcl_2s, color=PALETTE["target"]["primary"], linestyle=":", linewidth=0.8, alpha=0.6)
        if lcl_1s:
            ax.axhline(lcl_1s, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)
        ax.fill_between(pos, lcl, cl, alpha=0.04, color=PALETTE["center"]["primary"])

    if violations:
        ax.scatter(violations, values[violations], s=80, color=PALETTE["anomaly"]["primary"],
                  marker="x", linewidths=2.5, zorder=5,
                  label=f"违规 ({len(violations)}个)")

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"非参数控制图 — {req.target_col} ({side_note})\n"
        f"CL={cl:.4f} | {limit_label}",
        fontsize=10,
    )
    ax.legend(fontsize=7, loc="upper right", ncol=2)
    fig.tight_layout()

    # ── 汇总 ──
    n_violations = len(violations)
    is_stable = n_violations == 0
    ucl_str = f"{ucl:.4f}" if ucl else "N/A"
    lcl_str = f"{lcl:.4f}" if lcl else "N/A"
    summary = (
        f"非参数控制图({side_note}): {'过程稳定 ✓' if is_stable else f'{n_violations} 个点违规'}。"
        f"CL(P50)={cl:.4f}, UCL={ucl_str}, LCL={lcl_str}。{asym_note}。"
    )

    # ── 控制限表（去重列表确保统计量与值始终同步）──
    limit_pairs = [
        ("CL (中位数/P50)", cl),
        ("UCL (P99.865)", ucl),
        ("LCL (P0.135)", lcl),
        ("UCL (P97.725, ~2σ)", ucl_2s),
        ("LCL (P2.275, ~2σ)", lcl_2s),
        ("UCL (P84.13, ~1σ)", ucl_1s),
        ("LCL (P15.87, ~1σ)", lcl_1s),
    ]
    present_pairs = [(k, v) for k, v in limit_pairs if v is not None]

    return AnalysisResult(
        task="spc_nonparametric",
        tables={
            "control_limits": pd.DataFrame({
                "统计量": [k for k, _ in present_pairs],
                "值": [f"{v:.4f}" for _, v in present_pairs],
            }),
            "violations": pd.DataFrame({
                "序号": violations,
                "值": values[violations].round(4),
            }) if violations else pd.DataFrame({"状态": ["未检测到违规"]}),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "cl": cl, "ucl": ucl, "lcl": lcl, "side": side,
            "ucl_2s": ucl_2s, "lcl_2s": lcl_2s,
            "n": n, "n_violations": n_violations, "is_stable": is_stable,
        },
    )
