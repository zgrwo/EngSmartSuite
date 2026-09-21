"""属性控制图（attribute_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import _adjust_xlabels, round_for_display
from smartsuite.engine.spc_charts._shared import _natural_sort_key


def attribute_chart(req: AnalysisRequest) -> AnalysisResult:
    """计数型/属性控制图：p (不良率)、np (不良数)、c (缺陷数)、u (单位缺陷率)。

    参数:
        chart_type: "p" | "np" | "c" | "u"
        X 列 (feature_cols[0]): 横坐标 — 类别/日期/数字。空→顺序索引
        group_col: 分组依据 (可选，不同值=不同颜色的线)
        n_col: 样本量列名 (p/u 图需要，变样本量时使用)
    """
    chart_type = req.params.get("chart_type", "p")
    data = req.data.copy()
    y_col = req.target_col
    _text_mapped = False  # 文本二值列被映射为 0/1 时置 True（用于下游语义提示）

    # 审查 2026-08-19 #2.8：常见中文二值串（合格/不合格、是/否）映射为 0/1，
    # 使 p/np 图可直接用于质量记录列（此前只能吃数值列）
    if y_col in data.columns and not pd.api.types.is_numeric_dtype(data[y_col]):
        _bin_map = {
            "合格": 1,
            "不合格": 0,
            "是": 1,
            "否": 0,
            "TRUE": 1,
            "FALSE": 0,
            "True": 1,
            "False": 0,
            "true": 1,
            "false": 0,
        }
        _mapped = data[y_col].map(_bin_map)
        if _mapped.notna().sum() == data[y_col].notna().sum() and _mapped.notna().sum() > 0:
            data[y_col] = _mapped.astype(float)
            _text_mapped = True
        else:
            # Round-2 #A2k：部分值无法映射（如"待检"）→ 明确报错而非下游深层异常
            _unmapped = sorted(
                {
                    str(v)
                    for v in data[y_col].dropna().unique()
                    if _bin_map.get(v) is None and v not in _bin_map
                }
            )[:5]
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=[
                    "目标列为文本但包含无法识别的类别值: "
                    + ", ".join(_unmapped)
                    + "。计数型控制图需要数值列或 合格/不合格、是/否 二值列。"
                ],
            )

    # X 列
    x_col = req.feature_cols[0] if req.feature_cols else None
    if x_col and x_col in data.columns:
        data["_x"] = data[x_col].values
    else:
        data["_x"] = range(len(data))

    # 分组依据
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in data.columns)
    if has_groups:
        data["_g"] = data[group_col].values
        group_names = sorted(data["_g"].dropna().unique())
        all_group_names = list(group_names)  # 2026-08-21 #F2：全量分组（metadata 供筛选栏常驻）
    else:
        data["_g"] = "_default"
        group_names = ["_default"]
        all_group_names = []

    # ── 前端分组筛选支持 ──
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        group_names = [g for g in group_names if str(g) in filter_set]
        if not group_names:
            group_names = sorted(data["_g"].dropna().unique()) if has_groups else ["_default"]

    # 按 (X, group) 聚合
    valid = data[y_col].notna()
    dv = data[valid]
    # 分组列含 NaN 的行无法归属任何序列：剔除其参与池化统计/绘图，避免“看不见的点在算控制限”
    _nan_dropped = 0
    if has_groups:
        _nan_dropped = int(dv["_g"].isna().sum())
        if _nan_dropped:
            dv = dv[dv["_g"].notna()]
    agg = dv.groupby(["_x", "_g"], dropna=False)[y_col].agg(count="sum", size="count").reset_index()
    agg = agg.rename(columns={"_x": "x_val", "_g": "group_val"})

    m = len(agg)
    if m < 5:
        return AnalysisResult(
            task="spc_attribute", status="error", messages=["分组数量不足(至少5个)"]
        )

    # 计数型/属性图的缺陷计数不允许为负：负值会使 sqrt 内为负 → NaN 控制限静默污染
    if (agg["count"] < 0).any():
        return AnalysisResult(
            task="spc_attribute",
            status="error",
            messages=["目标列含负计数值：p/np/c/u 图要求缺陷计数 ≥ 0，请检查目标列选择"],
        )

    # 按图表类型计算
    n_col = req.params.get("n_col")
    if n_col and n_col in data.columns:
        # P1 fix: 始终用 ["_x", "_g"] 分组（非分组模式下 _g="_default"），
        # 确保 n_map 键与 agg 行结构一致；同时 NaN 值回退到平均样本量
        n_map_raw = data.groupby(["_x", "_g"], dropna=False)[n_col].first()
        mean_size = float(agg["size"].mean())
        n_map = {}
        for idx, val in n_map_raw.items():
            n_map[idx] = float(val) if (not pd.isna(val)) else None
        agg["n_vals"] = agg.apply(
            lambda r: float(
                v if (v := n_map.get((r["x_val"], r["group_val"]))) is not None else mean_size
            ),
            axis=1,
        )
    else:
        agg["n_vals"] = agg["size"].astype(float)

    if chart_type == "p":
        if (agg["n_vals"] == 0).any():
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"],
            )
        agg["stat"] = agg["count"] / agg["n_vals"]
        stat_name = "不良率(p)"
        p_bar = float(agg["count"].sum() / agg["n_vals"].sum())
        # 审查 2026-08-19 #2.8：p 图要求 0/1 比例数据；若数据为百分比/任意数值
        # （如 0-100 的不良率列），p_bar>1 → sqrt(负) → UCL/LCL=NaN 静默污染
        if not 0 <= p_bar <= 1:
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=[
                    "p 图要求目标列为 0/1 不良比例数据；"
                    f"当前总体不良率={p_bar:.4f} 超出 [0,1]，"
                    "请检查数据是否为 0/1 编码（百分比需除以 100）"
                ],
            )
        cl = p_bar
        ucl_const = None

    elif chart_type == "np":
        if (agg["n_vals"] == 0).any():
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=["np 图要求各子组样本量 n>0（n_col 指定样本量时不得含 0）"],
            )
        agg["stat"] = agg["count"].astype(float)
        stat_name = "不良数(np)"
        np_bar = float(agg["count"].mean())
        # 与 p 图一致：用 n_vals（子组实际样本量）而非 size（聚合行数），
        # 否则分组聚合下 p_bar=count/行数 恒 >1 → sqrt(负) → NaN 控制限静默污染
        p_bar = float(agg["count"].sum() / agg["n_vals"].sum())
        if not 0 <= p_bar <= 1:
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=[
                    "np 图要求缺陷计数值不超过对应样本量；"
                    f"当前总体不良比例={p_bar:.4f} 超出 [0,1]，"
                    "请检查目标列是否为缺陷计数（且 count ≤ 样本量 n 列）"
                ],
            )
        cl = np_bar
        ucl_const = float(np_bar + 3 * np.sqrt(np_bar * (1 - p_bar)))

    elif chart_type == "c":
        agg["stat"] = agg["count"].astype(float)
        stat_name = "缺陷数(c)"
        c_bar = float(agg["count"].mean())
        cl = c_bar
        ucl_const = float(c_bar + 3 * np.sqrt(c_bar))

    elif chart_type == "u":
        if (agg["n_vals"] == 0).any():
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"],
            )
        agg["stat"] = agg["count"] / agg["n_vals"]
        stat_name = "单位缺陷率(u)"
        u_bar = float(agg["count"].sum() / agg["n_vals"].sum())
        cl = u_bar
        ucl_const = None
    else:
        return AnalysisResult(
            task="spc_attribute",
            status="error",
            messages=[f"不支持的图表类型: {chart_type}，支持 p/np/c/u"],
        )

    # 控制限
    if ucl_const is not None:
        lcl_const = max(0, 2 * cl - ucl_const)
        agg["ucl"] = ucl_const
        agg["lcl"] = lcl_const
    elif chart_type == "p":
        agg["ucl"] = cl + 3 * np.sqrt(cl * (1 - cl) / agg["n_vals"].values)
        agg["lcl"] = np.maximum(0, cl - 3 * np.sqrt(cl * (1 - cl) / agg["n_vals"].values))
    else:
        agg["ucl"] = cl + 3 * np.sqrt(cl / agg["n_vals"].values)
        agg["lcl"] = np.maximum(0, cl - 3 * np.sqrt(cl / agg["n_vals"].values))

    # 违规检测
    agg_viol = agg[agg["stat"].notna()]
    above = agg_viol["stat"].values > agg_viol["ucl"].values
    below = agg_viol["stat"].values < agg_viol["lcl"].values
    violations = int((above | below).sum())

    # 图表（Round-2 #A5：与 xbar 同款 _natural_sort_key）
    x_unique = sorted(agg["x_val"].unique(), key=_natural_sort_key)
    x_to_idx = {v: i for i, v in enumerate(x_unique)}
    agg["_idx"] = agg["x_val"].map(x_to_idx)

    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    group_colors = {}
    for gi, gname in enumerate(group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    for _gi, gname in enumerate(group_names):
        gdata = agg[agg["group_val"] == gname].sort_values("_idx")
        if len(gdata) == 0:
            continue
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        g_idx = gdata["_idx"].values
        g_stat = gdata["stat"].values

        # 大样本时点+连线会形成"毛刷"噪声，退化为细线
        if len(g_idx) > 300:
            ax.plot(g_idx, g_stat, "-", color=color, linewidth=0.7, label=label, alpha=0.7)
        else:
            ax.plot(
                g_idx,
                g_stat,
                "o-",
                markersize=5,
                color=color,
                linewidth=1.2,
                label=label,
                alpha=0.8,
            )

    # 控制限
    ax.axhline(
        cl, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.5, label=f"CL={cl:.4f}"
    )
    if ucl_const is not None:
        ax.axhline(
            ucl_const,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"UCL={ucl_const:.4f}",
        )
        ax.axhline(
            lcl_const,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"LCL={lcl_const:.4f}",
        )
    else:
        all_idx = np.arange(len(x_unique))
        ax.plot(
            all_idx,
            agg.groupby("_idx")["ucl"].first().values,
            "--",
            color=PALETTE["control"]["primary"],
            linewidth=1,
            alpha=0.5,
            label="UCL",
        )
        ax.plot(
            all_idx,
            agg.groupby("_idx")["lcl"].first().values,
            "--",
            color=PALETTE["control"]["primary"],
            linewidth=1,
            alpha=0.5,
            label="LCL",
        )

    # 违规标记
    viol_mask = agg["stat"].notna()
    viol_idx = agg.loc[viol_mask, "_idx"].values
    viol_stat = agg.loc[viol_mask, "stat"].values
    viol_ucl = agg.loc[viol_mask, "ucl"].values
    viol_lcl = agg.loc[viol_mask, "lcl"].values
    viol_pts = np.where((viol_stat > viol_ucl) | (viol_stat < viol_lcl))[0]
    if len(viol_pts) > 0:
        ax.scatter(
            viol_idx[viol_pts],
            viol_stat[viol_pts],
            s=80,
            color=PALETTE["anomaly"]["primary"],
            marker="x",
            linewidths=2.5,
            zorder=5,
            label=f"超出控制限 ({len(viol_pts)}个)",
        )

    # 标签
    def _fmt_attr_labels(vals):
        labels = []
        for v in vals:
            s = v.strftime("%m-%d") if hasattr(v, "strftime") else str(v)
            if len(s) > 15:
                s = s[:14] + "…"
            labels.append(s)
        n_lbl = len(labels)
        if n_lbl > 20:
            step = max(1, n_lbl // 20)
            for i in range(n_lbl):
                if i % step != 0 and i != n_lbl - 1:
                    labels[i] = ""
        return labels

    x_labels = _fmt_attr_labels(x_unique)
    ax.set_xticks(np.arange(len(x_unique)))
    ax.set_xticklabels(x_labels)
    _adjust_xlabels(ax, len(x_labels), fig)
    ax.set_xlabel("X", fontsize=10)
    ax.set_ylabel(stat_name, fontsize=10)
    ax.set_title(f"{chart_type.upper()}-控制图 — {y_col} (m={m}点)", fontsize=11)
    if has_groups:
        ax.legend(fontsize=7, ncol=max(1, len(group_names) // 3 + 1))
    else:
        ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    summary = f"{chart_type.upper()} 控制图: CL={cl:.4f}, 超出控制限 {violations}/{m} 个点"

    _notes = []
    if _text_mapped:
        _notes.append(
            "文本质量列已映射（合格→1、不合格→0），图统计的是“1 事件”占比/计数，"
            "请按列语义解读（若列以 1=合格 编码则为合格率图，而非不良率）"
        )
    if _nan_dropped:
        _notes.append(f"已剔除 {_nan_dropped} 行分组(group_col)为空的记录，避免其参与控制限统计")
    if _notes:
        summary += "；" + "；".join(_notes)

    # 控制限表
    table_rows = []
    for _, row in agg.iterrows():
        table_rows.append(
            {
                "X": row["x_val"],
                "分组": row["group_val"] if has_groups else "—",
                stat_name: round_for_display(float(row["stat"]), 4),
                "UCL": round_for_display(float(row["ucl"]), 4),
                "LCL": round_for_display(float(row["lcl"]), 4),
            }
        )

    return AnalysisResult(
        task="spc_attribute",
        tables={"control_stats": pd.DataFrame(table_rows)},
        figures=[fig],
        summary=summary,
        metadata={
            "chart_type": chart_type,
            "cl": float(cl),
            "n_points": m,
            "n_violations": violations,
            "groups": [str(g) for g in all_group_names if g != "_default"],
            "text_binary_mapped": _text_mapped,
            "nan_group_rows_dropped": _nan_dropped,
        },
    )
