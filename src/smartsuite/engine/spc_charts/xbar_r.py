"""X-bar/R 控制图（xbar_r_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import XBR_CONSTANTS
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import _adjust_xlabels
from smartsuite.engine.spc_charts._shared import _natural_sort_key
from smartsuite.engine.spc_charts.we_rules import (
    _we_rules_r,
    _we_rules_s,
    _we_rules_xbar,
    _xbar_s_constants,
)


def xbar_r_chart(req: AnalysisRequest) -> AnalysisResult:
    """X-bar 控制图，含 Western Electric 规则和区域着色。

    参数模型:
        X 列 (feature_cols[0]): 横坐标 — 类别/日期/数字。空→顺序索引
        group_col (params): 分组依据 — 空→单系列。不同值=不同线，共享坐标轴
        usl/lsl/target (params): 规格限/目标值（可选）

    子组: 同一 (X值, 分组值) 下的多行自然形成。n = 该组合的行数。
    """
    data = req.data.copy()
    y_col = req.target_col

    # ── 1. 提取 X 列（横坐标）──
    x_col = req.feature_cols[0] if req.feature_cols else None
    if x_col and x_col in data.columns:
        x_vals = data[x_col]
    else:
        x_vals = pd.Series(range(len(data)), index=data.index, name="_seq")

    # ── 2. 提取分组依据 ──
    group_col = req.params.get("group_col")
    # 审查 2026-09-05 C2：无效分组列此前被静默忽略退化为单系列，
    # 用户误以为已按分组分析——显式报错（哨兵契约：集合内无效元素显式提示）
    if group_col and group_col not in data.columns:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"分组列「{group_col}」不存在于数据中。可用列: {list(data.columns)[:10]}"],
        )
    has_groups = bool(group_col)
    if has_groups:
        group_vals = data[group_col]
        group_names = sorted(group_vals.dropna().unique())
        all_group_names = list(group_names)  # 2026-08-21 #F2：全量分组（metadata 供筛选栏常驻）
        # 支持前端筛选：仅显示指定分组
        filter_groups = req.params.get("filter_groups")
        if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
            filter_set = set(str(f) for f in filter_groups)
            group_names = [g for g in group_names if str(g) in filter_set]
            if not group_names:
                group_names = sorted(group_vals.dropna().unique())  # 全空则回退
    else:
        group_vals = pd.Series("_default", index=data.index)
        group_names = ["_default"]

    # ── 3. 构建子组统计 ──
    data["_x"] = x_vals.values
    data["_group"] = group_vals.values
    data["_y"] = data[y_col].values

    # 过滤有效数据
    valid = data["_y"].notna()
    data_valid = data[valid].copy()
    if len(data_valid) < 2:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"目标列「{y_col}」有效数据不足（至少需要2个数据点）"],
        )

    # 按 (X值, 分组值) 聚合
    agg = (
        data_valid.groupby(["_x", "_group"], dropna=False)["_y"]
        .agg(xbar="mean", r=lambda x: x.max() - x.min(), s="std", n="count")
        .reset_index()
    )
    agg = agg.rename(columns={"_x": "x_val", "_group": "group_val"})

    # ── 4. 分类子组: n≥2 参与控制限估计, n=1 仅显示 ──
    agg["multi"] = agg["n"] >= 2
    multi_data = agg[agg["multi"]].copy()
    single_data = agg[~agg["multi"]].copy()

    if len(multi_data) < 1 and len(single_data) < 2:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=["X 列有效分组数不足（至少需要2个点）"],
        )

    # ── 5. 确定统一 n（用于图表标题）──
    if len(multi_data) > 0:
        n_sizes = multi_data["n"]
        if n_sizes.nunique() == 1:
            n_common = int(n_sizes.iloc[0])
            warn_unequal = ""
        else:
            n_common = int(n_sizes.min())
            warn_unequal = f" (子组大小不一致，最小n={n_common})"
    else:
        n_common = 1
        warn_unequal = " (无多点子组，仅显示单值)"

    # ── 6. 控制限计算 ──
    use_s_chart = False
    xbar_bar = None
    sigma_xbar = None
    ucl_x = lcl_x = None
    lower_cl = lower_ucl = lower_lcl = None
    lower_label = lower_title = ""
    chart_subtype = ""
    _r_bar = None
    _s_bar = None
    _disp_key = "r"  # 散度统计量的列名

    # 分组独立控制限（has_groups 时每组独立计算）
    group_limits: dict = {}  # group_name → {xbar_bar, sigma, ucl_x, lcl_x, ...}
    per_group_violations: dict = {}  # group_name → {"xbar": ..., "disp": ...}

    if len(multi_data) > 0:
        # ── 全局控制限（pooled，用于图表背景参考线）──
        if n_common in XBR_CONSTANTS:
            A2, D3, D4 = XBR_CONSTANTS[n_common]
            _r_bar = float(multi_data["r"].mean())
            xbar_bar = float(multi_data["xbar"].mean())
            sigma_xbar = A2 * _r_bar / 3.0
            ucl_x = xbar_bar + 3.0 * sigma_xbar
            lcl_x = xbar_bar - 3.0 * sigma_xbar
            lower_cl = _r_bar
            lower_ucl = D4 * _r_bar
            lower_lcl = D3 * _r_bar
            lower_label = "R (极差)"
            lower_title = "R 控制图"
            chart_subtype = "xbar_r"
            _disp_key = "r"
        else:
            use_s_chart = True
            c4, A3, B3, B4 = _xbar_s_constants(n_common)
            _s_bar = float(multi_data["s"].mean())
            xbar_bar = float(multi_data["xbar"].mean())
            sigma_xbar = A3 * _s_bar / 3.0
            ucl_x = xbar_bar + 3.0 * sigma_xbar
            lcl_x = xbar_bar - 3.0 * sigma_xbar
            lower_cl = _s_bar
            lower_ucl = B4 * _s_bar
            lower_lcl = B3 * _s_bar
            lower_label = "S (标准差)"
            lower_title = "S 控制图"
            chart_subtype = "xbar_s"
            _disp_key = "s"

        # ── 分组独立违规检测 ──
        if has_groups:
            for gname in group_names:
                g_multi = multi_data[multi_data["group_val"] == gname]
                if len(g_multi) < 2:
                    continue
                if n_common in XBR_CONSTANTS:
                    A2g, D3g, D4g = XBR_CONSTANTS[n_common]
                    _rg = float(g_multi["r"].mean())
                    _xbg = float(g_multi["xbar"].mean())
                    _sg = A2g * _rg / 3.0
                    group_limits[gname] = {
                        "xbar_bar": _xbg,
                        "sigma_xbar": _sg,
                        "ucl_x": _xbg + 3.0 * _sg,
                        "lcl_x": _xbg - 3.0 * _sg,
                        "lower_cl": _rg,
                        "lower_ucl": D4g * _rg,
                        "lower_lcl": D3g * _rg,
                    }
                else:
                    _sg_bar = float(g_multi["s"].mean())
                    _xbg = float(g_multi["xbar"].mean())
                    _sg2 = A3 * _sg_bar / 3.0
                    group_limits[gname] = {
                        "xbar_bar": _xbg,
                        "sigma_xbar": _sg2,
                        "ucl_x": _xbg + 3.0 * _sg2,
                        "lcl_x": _xbg - 3.0 * _sg2,
                        "lower_cl": _sg_bar,
                        "lower_ucl": B4 * _sg_bar,
                        "lower_lcl": B3 * _sg_bar,
                    }

        # ── 全局违规检测（无分组时直接用 pooled 限）──
        if n_common in XBR_CONSTANTS:
            xbar_violations = _we_rules_xbar(multi_data["xbar"].values, xbar_bar, sigma_xbar)
            r_violations = _we_rules_r(multi_data["r"].values, _r_bar, lower_ucl, lower_lcl)
        else:
            xbar_violations = _we_rules_xbar(multi_data["xbar"].values, xbar_bar, sigma_xbar)
            r_violations = _we_rules_s(multi_data["s"].values, _s_bar, lower_ucl, lower_lcl)

        # ── 分组违规检测 ──
        if has_groups:
            for gname, glim in group_limits.items():
                g_multi = multi_data[multi_data["group_val"] == gname]
                gv_x = _we_rules_xbar(g_multi["xbar"].values, glim["xbar_bar"], glim["sigma_xbar"])
                if n_common in XBR_CONSTANTS:
                    gv_disp = _we_rules_r(
                        g_multi["r"].values, glim["lower_cl"], glim["lower_ucl"], glim["lower_lcl"]
                    )
                else:
                    gv_disp = _we_rules_s(
                        g_multi["s"].values, glim["lower_cl"], glim["lower_ucl"], glim["lower_lcl"]
                    )
                per_group_violations[gname] = {"xbar": gv_x, "disp": gv_disp}
    else:
        # 全部 n=1: I 图风格
        xbar_bar = float(agg["xbar"].mean())
        if has_groups:
            # 分组 + 全 n=1：σ 用组内 MR 池化（避免跨组差分污染，审查 #2.4），
            # 规则检测用全局 σ（每组单点自身的 σ=0 会致全组误报）
            _group_mr_parts: list[np.ndarray] = []
            _group_series: dict[str, np.ndarray] = {}
            for gname, gdata_i in agg.groupby("group_val"):
                g_xbar = gdata_i["xbar"].values
                g_mr = np.abs(np.diff(g_xbar))
                if len(g_mr) > 0:
                    _group_mr_parts.append(g_mr)
                _group_series[gname] = g_xbar
            if _group_mr_parts:
                sigma_xbar = float(np.mean(np.concatenate(_group_mr_parts))) / 1.128
            else:
                sigma_xbar = float(agg["xbar"].std(ddof=1)) if len(agg) > 1 else 0.0
            for gname, g_xbar in _group_series.items():
                per_group_violations[gname] = {
                    "xbar": _we_rules_xbar(g_xbar, xbar_bar, sigma_xbar),
                    "disp": {},
                }
        else:
            mr_vals = np.abs(np.diff(agg["xbar"].values))
            if len(mr_vals) > 0:
                sigma_xbar = float(np.mean(mr_vals)) / 1.128
            else:
                # 单点回退：与 has_groups 分支同款守卫（审查 #R2），
                # 单值样本标准差 ddof=1 为 NaN，会落入下方错误消息而非误导性报缺
                sigma_xbar = float(agg["xbar"].std(ddof=1)) if len(agg) > 1 else 0.0
        ucl_x = xbar_bar + 3.0 * sigma_xbar
        lcl_x = xbar_bar - 3.0 * sigma_xbar
        lower_label = "—"
        lower_title = "—"
        chart_subtype = "i_chart"
        if has_groups:
            xbar_violations = {}
        else:
            xbar_violations = _we_rules_xbar(agg["xbar"].values, xbar_bar, sigma_xbar)
        r_violations = {}

    # NaN 校验
    if np.isnan(xbar_bar) or np.isnan(sigma_xbar):
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"目标列「{y_col}」的所有值均为缺失值或不可计算，无法估计控制限。"],
        )
    # 常量列：σ=0 → 控制图无意义（审查 #2.8）
    # Round-2 #A2l：绝对阈值 1e-12 误报微尺度数据 → 相对阈值
    # 审查 2026-09-16 B-4：原 `_scale=1.0` 兜底使阈值退回绝对值 → pico 级真实波动
    # 误报常量；改为相对数据自身幅值（|x|max），全零列才判常量
    _abs_scale = float(np.max(np.abs(agg["xbar"].values)))
    if _abs_scale == 0 or sigma_xbar <= 1e-12 * _abs_scale:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"目标列「{y_col}」为常量列（标准差为 0），控制图无意义。"],
        )

    # ── 7. 图表渲染 ──
    n_series = len(group_names) if has_groups else 1
    fig_height = 9 if (lower_title != "—") else 6
    fig = Figure(figsize=(12, fig_height))
    n_subplots = 2 if lower_title != "—" else 1

    # X-bar 控制图
    ax1 = fig.add_subplot(n_subplots * 100 + 11) if n_subplots == 2 else fig.add_subplot(111)

    # 构建统一索引 — 按 X 值排序，同一 X 值下按分组排
    # 审查 2026-08-19 #2.2：数值 X 按字符串字典序排序（1,10,11,2,...）导致图表顺序错乱
    # Round-2 #A5：np.int64 非 int 子类，key 用 _natural_sort_key 覆盖全部数值类型
    x_unique = sorted(agg["x_val"].unique(), key=_natural_sort_key)
    x_to_idx = {v: i for i, v in enumerate(x_unique)}
    agg["_idx"] = agg["x_val"].map(x_to_idx)

    # 分组颜色
    group_colors = {}
    for gi, gname in enumerate(group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    # 区域着色（基于整体控制限）
    all_idx = np.arange(len(x_unique))
    ax1.fill_between(all_idx, lcl_x, ucl_x, alpha=0.06, color=PALETTE["center"]["primary"])
    ax1.fill_between(
        all_idx,
        xbar_bar - 2 * sigma_xbar,
        xbar_bar + 2 * sigma_xbar,
        alpha=0.06,
        color=PALETTE["judge"]["warn"],
    )
    ax1.fill_between(
        all_idx,
        xbar_bar - 1 * sigma_xbar,
        xbar_bar + 1 * sigma_xbar,
        alpha=0.06,
        color=PALETTE["center"]["primary"],
    )
    ax1.axhline(
        xbar_bar,
        color=PALETTE["control"]["primary"],
        linestyle="--",
        linewidth=1.5,
        label=f"CL={xbar_bar:.4f}",
    )
    ax1.axhline(
        ucl_x,
        color=PALETTE["control"]["primary"],
        linestyle="--",
        linewidth=1.2,
        label=f"UCL={ucl_x:.4f}",
    )
    ax1.axhline(
        lcl_x,
        color=PALETTE["control"]["primary"],
        linestyle="--",
        linewidth=1.2,
        label=f"LCL={lcl_x:.4f}",
    )
    ax1.axhline(
        xbar_bar + 2 * sigma_xbar,
        color=PALETTE["spec"]["secondary"],
        linestyle=":",
        linewidth=0.7,
        alpha=0.6,
    )
    ax1.axhline(
        xbar_bar - 2 * sigma_xbar,
        color=PALETTE["spec"]["secondary"],
        linestyle=":",
        linewidth=0.7,
        alpha=0.6,
    )
    ax1.axhline(
        xbar_bar + 1 * sigma_xbar,
        color=PALETTE["spec"]["tertiary"],
        linestyle=":",
        linewidth=0.5,
        alpha=0.4,
    )
    ax1.axhline(
        xbar_bar - 1 * sigma_xbar,
        color=PALETTE["spec"]["tertiary"],
        linestyle=":",
        linewidth=0.5,
        alpha=0.4,
    )

    # 规格限
    # 审查 2026-09-19 D-1：float() 不拦 inf/nan（capability C1 同族），必须 isfinite
    # 显式拒绝，不再静默忽略非法参数（哨兵 L1）
    for spec_key, spec_label in [("usl", "USL"), ("lsl", "LSL")]:
        spec_val = req.params.get(spec_key)
        if spec_val is not None:
            try:
                sv = float(spec_val)
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="spc_xbar",
                    status="error",
                    messages=[f"规格限 {spec_label} 值无效: {spec_val}，请输入数值"],
                )
            if not np.isfinite(sv):
                return AnalysisResult(
                    task="spc_xbar",
                    status="error",
                    messages=[f"规格限 {spec_label} 必须为有限数值，当前: {spec_val!r}"],
                )
            ax1.axhline(
                sv,
                color=PALETTE["anomaly"]["primary"],
                linestyle="-",
                linewidth=1.2,
                alpha=0.9,
                label=f"{spec_label}={sv}",
            )
    target_spec = req.params.get("target")
    if target_spec is not None:
        try:
            tv = float(target_spec)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="spc_xbar",
                status="error",
                messages=[f"目标值 Target 值无效: {target_spec}，请输入数值"],
            )
        if not np.isfinite(tv):
            return AnalysisResult(
                task="spc_xbar",
                status="error",
                messages=[f"目标值 Target 必须为有限数值，当前: {target_spec!r}"],
            )
        ax1.axhline(
            tv,
            color=PALETTE["direction"]["zero"],
            linestyle=":",
            linewidth=1.0,
            alpha=0.6,
            label=f"Target={tv}",
        )

    # ── 分组独立控制限线（有分组时每组画自己的限）──
    if has_groups and group_limits:
        for gname, glim in group_limits.items():
            color = group_colors[gname]
            ax1.axhline(glim["ucl_x"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)
            ax1.axhline(glim["lcl_x"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)

    # 按分组绘制系列线
    all_xbar_violated: set[int] = set()
    for _rule_name, idxs in xbar_violations.items():
        for idx in idxs:
            all_xbar_violated.add(idx)

    for _gi, gname in enumerate(group_names):
        gdata = agg[agg["group_val"] == gname].sort_values("_idx")
        if len(gdata) == 0:
            continue
        g_idx = gdata["_idx"].values
        g_xbar = gdata["xbar"].values
        color = group_colors[gname]
        label = str(gname) if has_groups else None

        # 线
        ax1.plot(g_idx, g_xbar, "-", color=color, linewidth=1.2, alpha=0.6, label=label, zorder=2)
        # 点多点 / 单点 标记区分
        g_multi = gdata[gdata["multi"]]
        g_single = gdata[~gdata["multi"]]
        if len(g_multi) > 0:
            ax1.scatter(
                g_multi["_idx"],
                g_multi["xbar"],
                s=30,
                color=color,
                marker="o",
                edgecolors="white",
                linewidth=0.5,
                zorder=4,
            )
        if len(g_single) > 0:
            ax1.scatter(
                g_single["_idx"],
                g_single["xbar"],
                s=25,
                color=color,
                marker="s",
                edgecolors="white",
                linewidth=0.5,
                zorder=4,
                label=f"{label} (n=1)" if has_groups else "n=1",
            )

        # ── 分组独立违规点 ──
        if has_groups and gname in per_group_violations:
            gv = per_group_violations[gname]["xbar"]
            g_vio_set: set[int] = set()
            for idxs in gv.values():
                for idx in idxs:
                    g_vio_set.add(idx)
            if g_vio_set:
                g_vio_idx = sorted(g_vio_set)
                # 审查 #2.3：I 图（全 n=1）gdata["multi"] 恒 False → 标记全丢；
                # 此时违规索引直接对应组内行
                g_multi_sorted = gdata if chart_subtype == "i_chart" else gdata[gdata["multi"]]
                viol_data = g_multi_sorted.iloc[[i for i in g_vio_idx if i < len(g_multi_sorted)]]
                if len(viol_data) > 0:
                    ax1.scatter(
                        viol_data["_idx"],
                        viol_data["xbar"],
                        s=60,
                        color=color,
                        marker="o",
                        facecolors="none",
                        linewidths=1.5,
                        zorder=5,
                    )

    # 违规点标记（无分组时用全局检测）
    if not has_groups and all_xbar_violated:
        # 审查 2026-08-19 #2.3：I 图路径（全 n=1）agg["multi"] 恒 False，
        # 违规索引基于 agg 全表，此前过滤 multi 后标记全部丢失
        viol_frame = agg if chart_subtype == "i_chart" else agg[agg["multi"]]
        vio_idx_list = [i for i in all_xbar_violated if i < len(viol_frame)]
        if vio_idx_list:
            vio_subset = viol_frame.iloc[vio_idx_list]
            ax1.scatter(
                vio_subset["_idx"],
                vio_subset["xbar"],
                s=80,
                color=PALETTE["anomaly"]["primary"],
                marker="o",
                facecolors="none",
                linewidths=2,
                zorder=5,
                label=f"违规点 ({len(vio_idx_list)}个)",
            )

    # X 轴标签
    def _fmt_labels(vals):
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

    x_labels = _fmt_labels(x_unique)
    ax1.set_xticks(all_idx)
    ax1.set_xticklabels(x_labels)
    _adjust_xlabels(ax1, len(x_labels), fig)
    ax1.set_ylabel(y_col, fontsize=10)
    title_n = n_common if n_common > 1 else 1
    title_info = f"{chart_subtype.upper()}控制图 — {y_col} ({len(agg)}点{'×' + str(title_n) + '样本' if title_n > 1 else ''}{warn_unequal})"
    ax1.set_title(title_info, fontsize=12)
    if has_groups:
        ax1.legend(fontsize=7, loc="upper right", ncol=max(1, n_series // 3 + 1))
    else:
        ax1.legend(fontsize=8, loc="upper right", ncol=2)

    # ── R/S 控制图 (下方子图) ──
    ax2 = None
    disp_key = _disp_key
    if lower_title != "—":
        assert lower_cl is not None and lower_ucl is not None and lower_lcl is not None
        ax2 = fig.add_subplot(212)
        ax2.axhline(
            lower_cl,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.5,
            label=f"CL={lower_cl:.4f}",
        )
        ax2.axhline(
            lower_ucl,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"UCL={lower_ucl:.4f}",
        )
        ax2.axhline(
            lower_lcl,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"LCL={lower_lcl:.4f}",
        )

        # ── 分组独立散度控制限 ──
        if has_groups and group_limits:
            for gname, glim in group_limits.items():
                color = group_colors[gname]
                ax2.axhline(
                    glim["lower_ucl"], color=color, linestyle="--", linewidth=0.6, alpha=0.35
                )
                ax2.axhline(
                    glim["lower_lcl"], color=color, linestyle="--", linewidth=0.6, alpha=0.35
                )

        # 系列线
        for _gi, gname in enumerate(group_names):
            gdata = agg[agg["group_val"] == gname].sort_values("_idx")
            g_multi = gdata[gdata["multi"]]
            if len(g_multi) == 0:
                continue
            g_idx = g_multi["_idx"].values
            g_disp = g_multi[disp_key].values
            color = group_colors[gname]
            ax2.plot(g_idx, g_disp, "-", color=color, linewidth=1.2, alpha=0.6)
            ax2.scatter(
                g_idx,
                g_disp,
                s=20,
                color=color,
                marker="o",
                edgecolors="white",
                linewidth=0.5,
                zorder=4,
            )

            # ── 分组独立散度违规点 ──
            if has_groups and gname in per_group_violations:
                gv_disp = per_group_violations[gname]["disp"]
                g_disp_vio: set[int] = set()
                for idxs in gv_disp.values():
                    for idx in idxs:
                        g_disp_vio.add(idx)
                if g_disp_vio:
                    g_disp_vio_idx = sorted(g_disp_vio)
                    g_multi_sorted = gdata[gdata["multi"]]
                    viol_disp = g_multi_sorted.iloc[
                        [i for i in g_disp_vio_idx if i < len(g_multi_sorted)]
                    ]
                    if len(viol_disp) > 0:
                        ax2.scatter(
                            viol_disp["_idx"],
                            viol_disp[disp_key],
                            s=50,
                            color=color,
                            marker="o",
                            facecolors="none",
                            linewidths=1.5,
                            zorder=5,
                        )

        # R/S 违规点（无分组时用全局检测）
        if not has_groups:
            all_lower_violated: set[int] = set()
            for idxs in r_violations.values():
                for idx in idxs:
                    all_lower_violated.add(idx)
            if all_lower_violated:
                multi_only = agg[agg["multi"]]
                lvio_idx_list = [i for i in all_lower_violated if i < len(multi_only)]
                if lvio_idx_list:
                    lvio_subset = multi_only.iloc[lvio_idx_list]
                    ax2.scatter(
                        lvio_subset["_idx"],
                        lvio_subset[disp_key],
                        s=80,
                        color=PALETTE["anomaly"]["primary"],
                        marker="o",
                        facecolors="none",
                        linewidths=2,
                        zorder=5,
                        label=f"违规点 ({len(lvio_idx_list)}个)",
                    )

        ax2.set_xlabel("X", fontsize=10)
        ax2.set_ylabel(lower_label, fontsize=10)
        ax2.set_title(lower_title, fontsize=12)
        ax2.legend(fontsize=8, loc="upper right")
        ax2.set_xticks(all_idx)
        ax2.set_xticklabels(x_labels)
        _adjust_xlabels(ax2, len(x_labels), fig)

    fig.tight_layout()

    # ── 8. 违规汇总表 ──
    violation_rows: list[dict] = []
    if has_groups and per_group_violations:
        for gname, gv in per_group_violations.items():
            # 审查 #2.3：I 图分组模式下 multi 帧为空，取组内行帧
            # Round-2 M1：multi 分组模式此前用全局 agg[agg["multi"]] 取组内索引 →
            # 标签错行（B 组违规显示为 A 组首行）；组内违规索引对应组内 multi 帧
            if chart_subtype == "i_chart":
                _gframe = agg[agg["group_val"] == gname]
            else:
                _gframe = agg[(agg["group_val"] == gname) & agg["multi"]]
            for rule_name, idxs in gv["xbar"].items():
                v_labels = [str(_gframe.iloc[i]["x_val"]) for i in idxs if i < len(_gframe)]
                violation_rows.append(
                    {
                        "分组": str(gname),
                        "图表": "X-bar",
                        "规则": rule_name,
                        "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                        "违规点数": len(idxs),
                    }
                )
            lower_chart_label = "S" if use_s_chart else "R"
            for rule_name, idxs in gv["disp"].items():
                v_labels = [str(_gframe.iloc[i]["x_val"]) for i in idxs if i < len(_gframe)]
                violation_rows.append(
                    {
                        "分组": str(gname),
                        "图表": lower_chart_label,
                        "规则": rule_name,
                        "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                        "违规点数": len(idxs),
                    }
                )
        total_violations = sum(
            len(gv["xbar"]) + len(gv["disp"]) for gv in per_group_violations.values()
        )
    else:
        _vio_frame = agg if chart_subtype == "i_chart" else agg[agg["multi"]]
        for rule_name, idxs in xbar_violations.items():
            v_labels = [str(_vio_frame.iloc[i]["x_val"]) for i in idxs if i < len(_vio_frame)]
            violation_rows.append(
                {
                    "图表": "X-bar",
                    "规则": rule_name,
                    "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                    "违规点数": len(idxs),
                }
            )
        if r_violations:
            lower_chart_label = "S" if use_s_chart else "R"
            for rule_name, idxs in r_violations.items():
                v_labels = [
                    str(agg[agg["multi"]].iloc[i]["x_val"])
                    for i in idxs
                    if i < len(agg[agg["multi"]])
                ]
                violation_rows.append(
                    {
                        "图表": lower_chart_label,
                        "规则": rule_name,
                        "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                        "违规点数": len(idxs),
                    }
                )
        total_violations = len(xbar_violations) + len(r_violations)
    is_stable = total_violations == 0

    # ── 9. 控制限表 ──
    lower_stats_name = "—"
    if use_s_chart:
        lower_stats_name = "S"
    elif len(multi_data) > 0:
        lower_stats_name = "R"

    limits_rows = [
        {
            "统计量": "X-bar",
            "CL": f"{xbar_bar:.4f}",
            "UCL": f"{ucl_x:.4f}",
            "LCL": f"{lcl_x:.4f}",
            "1σ上限": f"{xbar_bar + sigma_xbar:.4f}",
            "1σ下限": f"{xbar_bar - sigma_xbar:.4f}",
        }
    ]
    if lower_stats_name != "—":
        limits_rows.append(
            {
                "统计量": lower_stats_name,
                "CL": f"{lower_cl:.4f}",
                "UCL": f"{lower_ucl:.4f}",
                "LCL": f"{lower_lcl:.4f}",
                "1σ上限": "—",
                "1σ下限": "—",
            }
        )
    limits = pd.DataFrame(limits_rows)

    # ── 10. 摘要 ──
    stability_summary = (
        "过程稳定 ✓" if is_stable else f"过程存在异常，共触发 {total_violations} 条规则"
    )

    messages: list[str] = []
    if use_s_chart:
        messages.append(
            f"⚠ 子组大小 n={n_common} > 25，已自动切换为 X-bar/S 控制图。"
            "S 图（标准差）在大子组时比 R 图（极差）更高效。"
        )
    if warn_unequal and n_common > 1:
        messages.append(
            f"⚠ 子组大小不一致: {warn_unequal.strip(' ()')}。控制限基于最小子组大小估计。"
        )
    single_count = len(single_data)
    if single_count > 0:
        messages.append(
            f"ℹ 检测到 {single_count} 个单值点（n=1），已在 X-bar 图中显示为方块标记，不参与极差/标准差计算。"
        )

    # ── 11. 元数据 ──
    metadata: dict = {
        "xbar_mean": xbar_bar,
        "sigma_xbar": sigma_xbar,
        "ucl_x": ucl_x,
        "lcl_x": lcl_x,
        "subgroup_size": n_common,
        "chart_type": chart_subtype,
        "n_series": n_series,
        "n_points": len(agg),
        "multi_points": len(multi_data),
        "single_points": single_count,
        "xbar_violations": {k: v for k, v in xbar_violations.items()},
        "is_stable": is_stable,
    }
    if use_s_chart:
        assert _s_bar is not None and lower_ucl is not None and lower_lcl is not None
        metadata["s_bar"] = float(_s_bar)
        metadata["ucl_s"] = float(lower_ucl)
        metadata["lcl_s"] = float(lower_lcl)
        metadata["r_violations"] = {}
        metadata["s_violations"] = {k: v for k, v in r_violations.items()}
    else:
        if _r_bar is not None:
            metadata["r_mean"] = float(_r_bar)
            metadata["ucl_r"] = float(lower_ucl) if lower_ucl is not None else 0.0
            metadata["lcl_r"] = float(lower_lcl) if lower_lcl is not None else 0.0
            metadata["r_violations"] = {k: v for k, v in r_violations.items()}
        else:
            metadata["r_violations"] = {}

    # 分组信息（用于前端筛选按钮）
    if has_groups:
        metadata["groups"] = [str(g) for g in all_group_names if g != "_default"]

    return AnalysisResult(
        task="spc_xbar",
        tables={
            "control_limits": limits,
            "violations": pd.DataFrame(violation_rows)
            if violation_rows
            else pd.DataFrame({"状态": ["未检测到违规"]}),
        },
        figures=[fig],
        summary=f"{stability_summary}。X-bar CL={xbar_bar:.4f}, UCL={ucl_x:.4f}, LCL={lcl_x:.4f}",
        messages=messages,
        metadata=metadata,
    )
