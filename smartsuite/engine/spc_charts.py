"""SPC 控制图模块：X-bar/R、属性控制图、CUSUM、EWMA、非参数 SPC。"""
import logging

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import EPSILON
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


def _xbar_s_constants(n: int) -> tuple[float, float, float, float]:
    """计算 x-bar/S 控制图常数 (c4, A3, B3, B4)，支持任意 n ≥ 2。

    用于 n > 25 时替代 R 图（S 图在大子组时比 R 图更高效）。
    使用 math.gamma 精确计算 c4 无偏常量。

    Returns:
        (c4, A3, B3, B4)
    """
    import math
    c4 = math.sqrt(2.0 / (n - 1)) * math.gamma(n / 2.0) / math.gamma((n - 1) / 2.0)
    c4 = max(c4, 1e-10)
    A3 = 3.0 / (c4 * math.sqrt(n))
    common = 3.0 * math.sqrt(max(0.0, 1.0 - c4 ** 2)) / c4
    B3 = max(0.0, 1.0 - common)
    B4 = 1.0 + common
    return c4, A3, B3, B4


def _we_rules_xbar(values, cl, sigma):
    """Western Electric 规则检测 X-bar 图。返回违规子组索引字典。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    sigma = max(sigma, EPSILON)
    n = len(vals)

    # Rule 1: 单点超出 ±3σ
    r1 = np.where((vals > cl + 3*sigma) | (vals < cl - 3*sigma))[0]
    if len(r1):
        violations["规则1: 超出±3σ"] = [int(i) for i in r1]

    # Rule 2: 连续3点中≥2点超出 ±2σ (同侧)
    r2: set[int] = set()
    for i in range(n - 2):
        above = np.sum(vals[i:i+3] > cl + 2*sigma)
        below = np.sum(vals[i:i+3] < cl - 2*sigma)
        if above >= 2:
            r2.update(j for j in range(i, i+3) if vals[j] > cl + 2*sigma)
        if below >= 2:
            r2.update(j for j in range(i, i+3) if vals[j] < cl - 2*sigma)
    if r2:
        violations["规则2: 3点中≥2点超出±2σ"] = sorted(r2)

    # Rule 3: 连续5点中≥4点超出 ±1σ (同侧)
    r3: set[int] = set()
    for i in range(n - 4):
        above = np.sum(vals[i:i+5] > cl + 1*sigma)
        below = np.sum(vals[i:i+5] < cl - 1*sigma)
        if above >= 4:
            r3.update(j for j in range(i, i+5) if vals[j] > cl + 1*sigma)
        if below >= 4:
            r3.update(j for j in range(i, i+5) if vals[j] < cl - 1*sigma)
    if r3:
        violations["规则3: 5点中≥4点超出±1σ"] = sorted(r3)

    # Rule 4: 连续8点在同一侧
    r4: set[int] = set()
    for i in range(n - 7):
        if all(vals[i:i+8] > cl) or all(vals[i:i+8] < cl):
            r4.update(range(i, i+8))
    if r4:
        violations["规则4: 连续8点同侧"] = sorted(r4)

    # Rule 5: 连续6点单调上升或下降
    r5: set[int] = set()
    for i in range(n - 5):
        if all(vals[i+k+1] > vals[i+k] for k in range(5)):
            r5.update(range(i, i+6))
        if all(vals[i+k+1] < vals[i+k] for k in range(5)):
            r5.update(range(i, i+6))
    if r5:
        violations["规则5: 连续6点趋势"] = sorted(r5)

    # Rule 6: 连续15点在 ±1σ 内（分层/虚假受控）
    r6: set[int] = set()
    for i in range(n - 14):
        if all(abs(vals[i:i+15] - cl) < 1*sigma):
            r6.update(range(i, i+15))
    if r6:
        violations["规则6: 连续15点在±1σ内"] = sorted(r6)

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


def _we_rules_s(values, cl, ucl, lcl=0):
    """S 控制图的模式检测规则（与 R 图规则一致，使用 S 命名）。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    n = len(vals)

    # Rule S1a: 超出 UCL
    r1 = np.where(vals > ucl)[0]
    if len(r1):
        violations["S1a: 超出UCL"] = [int(i) for i in r1]

    # Rule S1b: 低于 LCL (仅当 LCL>0 时)
    if lcl > 0:
        r1b = np.where(vals < lcl)[0]
        if len(r1b):
            violations["S1b: 低于LCL"] = [int(i) for i in r1b]

    # Rule S2: 连续 7 点在中心线同侧
    s2_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i:i+7] > cl):
            s2_seen.update(range(i, i+7))
        if all(vals[i:i+7] < cl):
            s2_seen.update(range(i, i+7))
    if s2_seen:
        violations["S2: 连续7点同侧"] = sorted(s2_seen)

    # Rule S3: 连续 7 点上升 (变异性恶化)
    s3_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i+k+1] > vals[i+k] for k in range(6)):
            s3_seen.update(range(i, i+7))
    if s3_seen:
        violations["S3: 连续7点上升 (变异增大)"] = sorted(s3_seen)

    # Rule S4: 连续 7 点下降 (变异性改善)
    s4_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i+k+1] < vals[i+k] for k in range(6)):
            s4_seen.update(range(i, i+7))
    if s4_seen:
        violations["S4: 连续7点下降 (变异减小)"] = sorted(s4_seen)

    return {k: sorted(set(v)) for k, v in violations.items()}


def _adjust_xlabels(ax, n_labels: int, fig=None):
    """自适应调整 X 轴刻度标签：根据标签数量选择旋转角度和字号。

    统一所有控制图、箱线图的 X 轴标签显示策略，消除硬编码 fontsize/rotation。
    与 _fmt_labels / _fmt_attr_labels 配合使用（后者负责文字截断和稀疏化）。

    Args:
        ax: matplotlib Axes 对象
        n_labels: 标签总数（含可能被 _fmt_labels 置空的标签）
        fig: 可选，用于多标签时自动调整子图边距
    """
    if n_labels <= 4:
        ax.tick_params(axis="x", labelsize=9)
    elif n_labels <= 8:
        ax.tick_params(axis="x", labelsize=9, rotation=30)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    elif n_labels <= 15:
        ax.tick_params(axis="x", labelsize=8, rotation=45)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    else:
        ax.tick_params(axis="x", labelsize=7.5, rotation=60)
        for label in ax.get_xticklabels():
            label.set_ha("right")
        if fig:
            fig.subplots_adjust(bottom=0.25)


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
    has_groups = bool(group_col and group_col in data.columns)
    if has_groups:
        group_vals = data[group_col]
        group_names = sorted(group_vals.dropna().unique())
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
            task="spc_xbar", status="error",
            messages=[f"目标列「{y_col}」有效数据不足（至少需要2个数据点）"],
        )

    # 按 (X值, 分组值) 聚合
    agg = data_valid.groupby(["_x", "_group"], dropna=False)["_y"].agg(
        xbar="mean", r=lambda x: x.max() - x.min(), s="std", n="count"
    ).reset_index()
    agg = agg.rename(columns={"_x": "x_val", "_group": "group_val"})

    # ── 4. 分类子组: n≥2 参与控制限估计, n=1 仅显示 ──
    agg["multi"] = agg["n"] >= 2
    multi_data = agg[agg["multi"]].copy()
    single_data = agg[~agg["multi"]].copy()

    if len(multi_data) < 1 and len(single_data) < 2:
        return AnalysisResult(
            task="spc_xbar", status="error",
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

    if len(multi_data) > 0:
        # ── 全局控制限（pooled，用于图表背景参考线）──
        if n_common in _XBR_CONSTANTS:
            A2, D3, D4 = _XBR_CONSTANTS[n_common]
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
                if n_common in _XBR_CONSTANTS:
                    A2g, D3g, D4g = _XBR_CONSTANTS[n_common]
                    _rg = float(g_multi["r"].mean())
                    _xbg = float(g_multi["xbar"].mean())
                    _sg = A2g * _rg / 3.0
                    group_limits[gname] = {
                        "xbar_bar": _xbg, "sigma_xbar": _sg,
                        "ucl_x": _xbg + 3.0 * _sg, "lcl_x": _xbg - 3.0 * _sg,
                        "lower_cl": _rg, "lower_ucl": D4g * _rg, "lower_lcl": D3g * _rg,
                    }
                else:
                    _sg_bar = float(g_multi["s"].mean())
                    _xbg = float(g_multi["xbar"].mean())
                    _sg2 = A3 * _sg_bar / 3.0
                    group_limits[gname] = {
                        "xbar_bar": _xbg, "sigma_xbar": _sg2,
                        "ucl_x": _xbg + 3.0 * _sg2, "lcl_x": _xbg - 3.0 * _sg2,
                        "lower_cl": _sg_bar, "lower_ucl": B4 * _sg_bar, "lower_lcl": B3 * _sg_bar,
                    }

        # ── 全局违规检测（无分组时直接用 pooled 限）──
        if n_common in _XBR_CONSTANTS:
            xbar_violations = _we_rules_xbar(
                multi_data["xbar"].values, xbar_bar, sigma_xbar)
            r_violations = _we_rules_r(
                multi_data["r"].values, _r_bar, lower_ucl, lower_lcl)
        else:
            xbar_violations = _we_rules_xbar(
                multi_data["xbar"].values, xbar_bar, sigma_xbar)
            r_violations = _we_rules_s(
                multi_data["s"].values, _s_bar, lower_ucl, lower_lcl)

        # ── 分组违规检测 ──
        per_group_violations: dict = {}
        if has_groups:
            for gname, glim in group_limits.items():
                g_multi = multi_data[multi_data["group_val"] == gname]
                gv_x = _we_rules_xbar(
                    g_multi["xbar"].values, glim["xbar_bar"], glim["sigma_xbar"])
                if n_common in _XBR_CONSTANTS:
                    gv_disp = _we_rules_r(
                        g_multi["r"].values, glim["lower_cl"], glim["lower_ucl"], glim["lower_lcl"])
                else:
                    gv_disp = _we_rules_s(
                        g_multi["s"].values, glim["lower_cl"], glim["lower_ucl"], glim["lower_lcl"])
                per_group_violations[gname] = {"xbar": gv_x, "disp": gv_disp}
    else:
        # 全部 n=1: I 图风格
        xbar_bar = float(agg["xbar"].mean())
        mr_vals = np.abs(np.diff(agg["xbar"].values))
        if len(mr_vals) > 0:
            sigma_xbar = float(np.mean(mr_vals)) / 1.128
        else:
            sigma_xbar = float(agg["xbar"].std())
        ucl_x = xbar_bar + 3.0 * sigma_xbar
        lcl_x = xbar_bar - 3.0 * sigma_xbar
        lower_label = "—"
        lower_title = "—"
        chart_subtype = "i_chart"
        xbar_violations = _we_rules_xbar(agg["xbar"].values, xbar_bar, sigma_xbar)
        r_violations = {}

    # NaN 校验
    if np.isnan(xbar_bar) or np.isnan(sigma_xbar):
        return AnalysisResult(
            task="spc_xbar", status="error",
            messages=[f"目标列「{y_col}」的所有值均为缺失值或不可计算，无法估计控制限。"],
        )

    # ── 7. 图表渲染 ──
    n_series = len(group_names) if has_groups else 1
    fig_height = 9 if (lower_title != "—") else 6
    fig = Figure(figsize=(12, fig_height))
    n_subplots = 2 if lower_title != "—" else 1

    # X-bar 控制图
    ax1 = fig.add_subplot(n_subplots * 100 + 11) if n_subplots == 2 else fig.add_subplot(111)

    # 构建统一索引 — 按 X 值排序，同一 X 值下按分组排
    x_unique = sorted(agg["x_val"].unique(), key=lambda v: (isinstance(v, (int, float)), str(v)))
    x_to_idx = {v: i for i, v in enumerate(x_unique)}
    agg["_idx"] = agg["x_val"].map(x_to_idx)

    # 分组颜色
    group_colors = {}
    for gi, gname in enumerate(group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    # 区域着色（基于整体控制限）
    all_idx = np.arange(len(x_unique))
    ax1.fill_between(all_idx, lcl_x, ucl_x, alpha=0.06, color=PALETTE["center"]["primary"])
    ax1.fill_between(all_idx, xbar_bar - 2*sigma_xbar, xbar_bar + 2*sigma_xbar,
                     alpha=0.06, color=PALETTE["judge"]["warn"])
    ax1.fill_between(all_idx, xbar_bar - 1*sigma_xbar, xbar_bar + 1*sigma_xbar,
                     alpha=0.06, color=PALETTE["center"]["primary"])
    ax1.axhline(xbar_bar, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.5,
                label=f"CL={xbar_bar:.4f}")
    ax1.axhline(ucl_x, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.2,
                label=f"UCL={ucl_x:.4f}")
    ax1.axhline(lcl_x, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.2,
                label=f"LCL={lcl_x:.4f}")
    ax1.axhline(xbar_bar + 2*sigma_xbar, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.7, alpha=0.6)
    ax1.axhline(xbar_bar - 2*sigma_xbar, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.7, alpha=0.6)
    ax1.axhline(xbar_bar + 1*sigma_xbar, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)
    ax1.axhline(xbar_bar - 1*sigma_xbar, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)

    # 规格限
    for spec_key, spec_label in [("usl", "USL"), ("lsl", "LSL")]:
        spec_val = req.params.get(spec_key)
        if spec_val is not None:
            try:
                sv = float(spec_val)
            except (ValueError, TypeError):
                sv = None
            if sv is not None:
                ax1.axhline(sv, color=PALETTE["anomaly"]["primary"], linestyle="-",
                           linewidth=1.2, alpha=0.9, label=f"{spec_label}={sv}")
    target_spec = req.params.get("target")
    if target_spec is not None:
        try:
            tv = float(target_spec)
        except (ValueError, TypeError):
            tv = None
        if tv is not None:
            ax1.axhline(tv, color=PALETTE["direction"]["zero"], linestyle=":",
                       linewidth=1.0, alpha=0.6, label=f"Target={tv}")

    # ── 分组独立控制限线（有分组时每组画自己的限）──
    if has_groups and group_limits:
        for gname, glim in group_limits.items():
            color = group_colors[gname]
            ax1.axhline(glim["ucl_x"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)
            ax1.axhline(glim["lcl_x"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)

    # 按分组绘制系列线
    all_xbar_violated: set[int] = set()
    for rule_name, idxs in xbar_violations.items():
        for idx in idxs:
            all_xbar_violated.add(idx)

    for gi, gname in enumerate(group_names):
        gdata = agg[agg["group_val"] == gname].sort_values("_idx")
        if len(gdata) == 0:
            continue
        g_idx = gdata["_idx"].values
        g_xbar = gdata["xbar"].values
        color = group_colors[gname]
        label = str(gname) if has_groups else None

        # 线
        ax1.plot(g_idx, g_xbar, "-", color=color, linewidth=1.2, alpha=0.6,
                label=label, zorder=2)
        # 点多点 / 单点 标记区分
        g_multi = gdata[gdata["multi"]]
        g_single = gdata[~gdata["multi"]]
        if len(g_multi) > 0:
            ax1.scatter(g_multi["_idx"], g_multi["xbar"], s=30, color=color,
                       marker="o", edgecolors="white", linewidth=0.5, zorder=4)
        if len(g_single) > 0:
            ax1.scatter(g_single["_idx"], g_single["xbar"], s=25, color=color,
                       marker="s", edgecolors="white", linewidth=0.5, zorder=4,
                       label=f"{label} (n=1)" if has_groups else "n=1")

        # ── 分组独立违规点 ──
        if has_groups and gname in per_group_violations:
            gv = per_group_violations[gname]["xbar"]
            g_vio_set: set[int] = set()
            for idxs in gv.values():
                for idx in idxs:
                    g_vio_set.add(idx)
            if g_vio_set:
                g_vio_idx = sorted(g_vio_set)
                g_multi_sorted = gdata[gdata["multi"]]
                viol_data = g_multi_sorted.iloc[
                    [i for i in g_vio_idx if i < len(g_multi_sorted)]]
                if len(viol_data) > 0:
                    ax1.scatter(viol_data["_idx"], viol_data["xbar"], s=60,
                               color=color, marker="o", facecolors="none",
                               linewidths=1.5, zorder=5)

    # 违规点标记（无分组时用全局检测）
    if not has_groups and all_xbar_violated:
        multi_only = agg[agg["multi"]]
        vio_idx_list = [i for i in all_xbar_violated if i < len(multi_only)]
        if vio_idx_list:
            vio_subset = multi_only.iloc[vio_idx_list]
            ax1.scatter(vio_subset["_idx"], vio_subset["xbar"], s=80,
                       color=PALETTE["anomaly"]["primary"], marker="o",
                       facecolors="none", linewidths=2, zorder=5,
                       label=f"违规点 ({len(vio_idx_list)}个)")

    # X 轴标签
    def _fmt_labels(vals):
        labels = []
        for v in vals:
            if hasattr(v, "strftime"):
                s = v.strftime("%m-%d")
            else:
                s = str(v)
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
    title_info = f"{chart_subtype.upper()}控制图 — {y_col} ({len(agg)}点{'×'+str(title_n)+'样本' if title_n>1 else ''}{warn_unequal})"
    ax1.set_title(title_info, fontsize=12)
    if has_groups:
        ax1.legend(fontsize=7, loc="upper right", ncol=max(1, n_series // 3 + 1))
    else:
        ax1.legend(fontsize=8, loc="upper right", ncol=2)

    # ── R/S 控制图 (下方子图) ──
    ax2 = None
    disp_key = _disp_key
    if lower_title != "—":
        ax2 = fig.add_subplot(212)
        ax2.axhline(lower_cl, color=PALETTE["control"]["primary"], linestyle="--",
                    linewidth=1.5, label=f"CL={lower_cl:.4f}")
        ax2.axhline(lower_ucl, color=PALETTE["control"]["primary"], linestyle="--",
                    linewidth=1.2, label=f"UCL={lower_ucl:.4f}")
        ax2.axhline(lower_lcl, color=PALETTE["control"]["primary"], linestyle="--",
                    linewidth=1.2, label=f"LCL={lower_lcl:.4f}")

        # ── 分组独立散度控制限 ──
        if has_groups and group_limits:
            for gname, glim in group_limits.items():
                color = group_colors[gname]
                ax2.axhline(glim["lower_ucl"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)
                ax2.axhline(glim["lower_lcl"], color=color, linestyle="--", linewidth=0.6, alpha=0.35)

        # 系列线
        for gi, gname in enumerate(group_names):
            gdata = agg[agg["group_val"] == gname].sort_values("_idx")
            g_multi = gdata[gdata["multi"]]
            if len(g_multi) == 0:
                continue
            g_idx = g_multi["_idx"].values
            g_disp = g_multi[disp_key].values
            color = group_colors[gname]
            ax2.plot(g_idx, g_disp, "-", color=color, linewidth=1.2, alpha=0.6)
            ax2.scatter(g_idx, g_disp, s=20, color=color, marker="o",
                       edgecolors="white", linewidth=0.5, zorder=4)

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
                        [i for i in g_disp_vio_idx if i < len(g_multi_sorted)]]
                    if len(viol_disp) > 0:
                        ax2.scatter(viol_disp["_idx"], viol_disp[disp_key], s=50,
                                   color=color, marker="o", facecolors="none",
                                   linewidths=1.5, zorder=5)

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
                    ax2.scatter(lvio_subset["_idx"], lvio_subset[disp_key], s=80,
                               color=PALETTE["anomaly"]["primary"], marker="o",
                               facecolors="none", linewidths=2, zorder=5,
                               label=f"违规点 ({len(lvio_idx_list)}个)")

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
            for rule_name, idxs in gv["xbar"].items():
                v_labels = [str(agg[agg["multi"]].iloc[i]["x_val"]) for i in idxs
                            if i < len(agg[agg["multi"]])]
                violation_rows.append({
                    "分组": str(gname),
                    "图表": "X-bar",
                    "规则": rule_name,
                    "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                    "违规点数": len(idxs),
                })
            lower_chart_label = "S" if use_s_chart else "R"
            for rule_name, idxs in gv["disp"].items():
                v_labels = [str(agg[agg["multi"]].iloc[i]["x_val"]) for i in idxs
                            if i < len(agg[agg["multi"]])]
                violation_rows.append({
                    "分组": str(gname),
                    "图表": lower_chart_label,
                    "规则": rule_name,
                    "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                    "违规点数": len(idxs),
                })
        total_violations = sum(
            len(gv["xbar"]) + len(gv["disp"]) for gv in per_group_violations.values())
    else:
        for rule_name, idxs in xbar_violations.items():
            v_labels = [str(agg[agg["multi"]].iloc[i]["x_val"]) for i in idxs
                        if i < len(agg[agg["multi"]])]
            violation_rows.append({
                "图表": "X-bar",
                "规则": rule_name,
                "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                "违规点数": len(idxs),
            })
        if r_violations:
            lower_chart_label = "S" if use_s_chart else "R"
            for rule_name, idxs in r_violations.items():
                v_labels = [str(agg[agg["multi"]].iloc[i]["x_val"]) for i in idxs
                            if i < len(agg[agg["multi"]])]
                violation_rows.append({
                    "图表": lower_chart_label,
                    "规则": rule_name,
                    "违规子组": ", ".join(v_labels[:10]) + ("…" if len(v_labels) > 10 else ""),
                    "违规点数": len(idxs),
                })
        total_violations = len(xbar_violations) + len(r_violations)
    is_stable = total_violations == 0

    # ── 9. 控制限表 ──
    lower_stats_name = "—"
    if use_s_chart:
        lower_stats_name = "S"
    elif len(multi_data) > 0:
        lower_stats_name = "R"

    limits_rows = [{
        "统计量": "X-bar",
        "CL": f"{xbar_bar:.4f}",
        "UCL": f"{ucl_x:.4f}",
        "LCL": f"{lcl_x:.4f}",
        "1σ上限": f"{xbar_bar + sigma_xbar:.4f}",
        "1σ下限": f"{xbar_bar - sigma_xbar:.4f}",
    }]
    if lower_stats_name != "—":
        limits_rows.append({
            "统计量": lower_stats_name,
            "CL": f"{lower_cl:.4f}",
            "UCL": f"{lower_ucl:.4f}",
            "LCL": f"{lower_lcl:.4f}",
            "1σ上限": "—",
            "1σ下限": "—",
        })
    limits = pd.DataFrame(limits_rows)

    # ── 10. 摘要 ──
    stability_summary = (
        "过程稳定 ✓" if is_stable
        else f"过程存在异常，共触发 {total_violations} 条规则"
    )

    messages: list[str] = []
    if use_s_chart:
        messages.append(
            f"⚠ 子组大小 n={n_common} > 25，已自动切换为 X-bar/S 控制图。"
            "S 图（标准差）在大子组时比 R 图（极差）更高效。"
        )
    if warn_unequal and n_common > 1:
        messages.append(
            f"⚠ 子组大小不一致: {warn_unequal.strip(' ()')}。"
            "控制限基于最小子组大小估计。"
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
        "ucl_x": ucl_x, "lcl_x": lcl_x,
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
        metadata["groups"] = [str(g) for g in group_names if g != "_default"]

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
        metadata=metadata,
    )


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
    else:
        data["_g"] = "_default"
        group_names = ["_default"]

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
    agg = dv.groupby(["_x", "_g"], dropna=False)[y_col].agg(
        count="sum", size="count"
    ).reset_index()
    agg = agg.rename(columns={"_x": "x_val", "_g": "group_val"})

    m = len(agg)
    if m < 5:
        return AnalysisResult(task="spc_attribute", status="error",
            messages=["分组数量不足(至少5个)"])

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
                v if (v := n_map.get((r["x_val"], r["group_val"]))) is not None
                else mean_size
            ),
            axis=1)
    else:
        agg["n_vals"] = agg["size"].astype(float)

    if chart_type == "p":
        if (agg["n_vals"] == 0).any():
            return AnalysisResult(task="spc_attribute", status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"])
        agg["stat"] = agg["count"] / agg["n_vals"]
        stat_name = "不良率(p)"
        p_bar = float(agg["count"].sum() / agg["n_vals"].sum())
        cl = p_bar
        ucl_const = None

    elif chart_type == "np":
        agg["stat"] = agg["count"].astype(float)
        stat_name = "不良数(np)"
        np_bar = float(agg["count"].mean())
        n_bar = float(agg["size"].mean())
        p_bar = np_bar / max(n_bar, 1)
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
            return AnalysisResult(task="spc_attribute", status="error",
                messages=["子组样本量包含0值，无法计算比率控制图"])
        agg["stat"] = agg["count"] / agg["n_vals"]
        stat_name = "单位缺陷率(u)"
        u_bar = float(agg["count"].sum() / agg["n_vals"].sum())
        cl = u_bar
        ucl_const = None
    else:
        return AnalysisResult(task="spc_attribute", status="error",
            messages=[f"不支持的图表类型: {chart_type}，支持 p/np/c/u"])

    # 控制限
    if ucl_const is not None:
        lcl_const = max(0, 2*cl - ucl_const)
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

    # 图表
    x_unique = sorted(agg["x_val"].unique(), key=lambda v: (isinstance(v, (int, float)), str(v)))
    x_to_idx = {v: i for i, v in enumerate(x_unique)}
    agg["_idx"] = agg["x_val"].map(x_to_idx)

    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    group_colors = {}
    for gi, gname in enumerate(group_names):
        group_colors[gname] = cm.tab10(gi % 10)

    for gi, gname in enumerate(group_names):
        gdata = agg[agg["group_val"] == gname].sort_values("_idx")
        if len(gdata) == 0:
            continue
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        g_idx = gdata["_idx"].values
        g_stat = gdata["stat"].values

        ax.plot(g_idx, g_stat, "o-", markersize=5, color=color, linewidth=1.2,
                label=label, alpha=0.8)

    # 控制限
    ax.axhline(cl, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.5,
               label=f"CL={cl:.4f}")
    if ucl_const is not None:
        ax.axhline(ucl_const, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"UCL={ucl_const:.4f}")
        ax.axhline(lcl_const, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.2,
                   label=f"LCL={lcl_const:.4f}")
    else:
        all_idx = np.arange(len(x_unique))
        ax.plot(all_idx, agg.groupby("_idx")["ucl"].first().values, "--",
                color=PALETTE["control"]["primary"], linewidth=1, alpha=0.5, label="UCL")
        ax.plot(all_idx, agg.groupby("_idx")["lcl"].first().values, "--",
                color=PALETTE["control"]["primary"], linewidth=1, alpha=0.5, label="LCL")

    # 违规标记
    viol_mask = agg["stat"].notna()
    viol_idx = agg.loc[viol_mask, "_idx"].values
    viol_stat = agg.loc[viol_mask, "stat"].values
    viol_ucl = agg.loc[viol_mask, "ucl"].values
    viol_lcl = agg.loc[viol_mask, "lcl"].values
    viol_pts = np.where((viol_stat > viol_ucl) | (viol_stat < viol_lcl))[0]
    if len(viol_pts) > 0:
        ax.scatter(viol_idx[viol_pts], viol_stat[viol_pts], s=80,
                   color=PALETTE["anomaly"]["primary"], marker="x", linewidths=2.5,
                   zorder=5, label=f"超出控制限 ({len(viol_pts)}个)")

    # 标签
    def _fmt_attr_labels(vals):
        labels = []
        for v in vals:
            if hasattr(v, "strftime"):
                s = v.strftime("%m-%d")
            else:
                s = str(v)
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

    summary = (
        f"{chart_type.upper()} 控制图: CL={cl:.4f}, "
        f"超出控制限 {violations}/{m} 个点"
    )

    # 控制限表
    table_rows = []
    for _, row in agg.iterrows():
        table_rows.append({
            "X": row["x_val"],
            "分组": row["group_val"] if has_groups else "—",
            stat_name: round(float(row["stat"]), 4),
            "UCL": round(float(row["ucl"]), 4),
            "LCL": round(float(row["lcl"]), 4),
        })

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
            "groups": [str(g) for g in group_names if g != "_default"],
        },
    )


def cusum_chart(req: AnalysisRequest) -> AnalysisResult:
    """CUSUM (累积和) 控制图 — 对小偏移 (±0.5σ~2σ) 比 X-bar 更敏感。

    参数:
        k: 参考值/松弛因子 (通常取 δ/2，其中 δ 是要检测的偏移量，以 σ 为单位)
        h: 决策区间 (通常取 4~5)
        mu: 过程均值 (如未提供，从数据估计；建议使用已知受控状态的 μ)
        sigma: 过程标准差 (如未提供，从数据估计；建议使用已知受控状态的 σ)
        group_col: 分组依据 (可选，不同值=不同颜色的线，共享坐标轴)
    """
    y_col = req.target_col
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in req.data.columns)

    if has_groups:
        group_vals = req.data[group_col]
        group_names = sorted(group_vals.dropna().unique())
    else:
        group_vals = pd.Series("_default", index=req.data.index)
        group_names = ["_default"]

    # ── 前端分组筛选支持 ──
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        group_names = [g for g in group_names if str(g) in filter_set]
        if not group_names:
            group_names = sorted(group_vals.dropna().unique())

    # 公共参数 (cusum)
    k = req.params.get("k", 0.5)
    h = req.params.get("h", 5.0)
    try:
        k, h = float(k), float(h)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="spc_cusum", status="error",
            messages=[f"参数 k/h 值无效: k={k}, h={h}，请输入数值"],
        )
    if k <= 0:
        return AnalysisResult(task="spc_cusum", status="error",
            messages=[f"参数 k ({k}) 无效：参考值必须为正数，建议 k=0.5"])
    if h <= 0:
        return AnalysisResult(task="spc_cusum", status="error",
            messages=[f"参数 h ({h}) 无效：决策区间必须为正数，建议 h=4~5"])

    user_mu = req.params.get("mu")
    user_sigma = req.params.get("sigma")
    if user_mu is not None and user_sigma is not None:
        try:
            user_mu, user_sigma = float(user_mu), float(user_sigma)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="spc_cusum", status="error",
                messages=[f"参数 mu/sigma 值无效: mu={user_mu}, sigma={user_sigma}，请输入数值"],
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
        if sigma < EPSILON:
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
                c_plus[i] = max(0, c_plus[i-1] + z[i] - k)
                c_minus[i] = max(0, c_minus[i-1] - z[i] - k)
            if c_plus[i] > h:
                alarm_plus.append(i)
            if c_minus[i] > h:
                alarm_minus.append(i)

        group_results.append({
            "name": gname, "data": gdata.values, "mu": mu, "sigma": sigma,
            "c_plus": c_plus, "c_minus": c_minus,
            "alarm_plus": alarm_plus, "alarm_minus": alarm_minus,
        })

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
            task="spc_cusum", status="error",
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
        warn_msgs.append(
            "⚠ μ/σ 从各组数据独立估计。"
            "建议通过参数 mu/sigma 指定已知受控状态的参数。"
        )

    for gr in group_results:
        gname = gr["name"]
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        pos = np.arange(len(gr["data"]))
        total_alarms += len(gr["alarm_plus"]) + len(gr["alarm_minus"])

        # 数据子图
        ax1.plot(pos, gr["data"], "o-", markersize=2, color=color, linewidth=0.8,
                alpha=0.7, label=label)
        ax1.axhline(gr["mu"], color=color, linestyle="--", linewidth=0.8, alpha=0.4)

        # CUSUM 子图
        ax2.plot(pos, gr["c_plus"], "-", color=color, linewidth=1.2,
                alpha=0.8, label=f"{label} C+" if has_groups else "C+ (上偏移)")
        ax2.plot(pos, gr["c_minus"], "--", color=color, linewidth=1.2,
                alpha=0.8, label=f"{label} C-" if has_groups else "C- (下偏移)")
        if gr["alarm_plus"]:
            ax2.scatter(gr["alarm_plus"], gr["c_plus"][gr["alarm_plus"]], s=50,
                       color=color, marker="x", linewidths=2, zorder=5)
        if gr["alarm_minus"]:
            ax2.scatter(gr["alarm_minus"], gr["c_minus"][gr["alarm_minus"]], s=50,
                       color=color, marker="x", linewidths=2, zorder=5)

    ax2.axhline(h, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.2,
                label=f"决策区间 h={h}")
    ax2.fill_between(np.arange(max_n), 0, h, alpha=0.05, color=PALETTE["center"]["primary"])

    ax1.set_ylabel(y_col, fontsize=10)
    ax1.set_title(f"CUSUM 控制图 — {y_col} (k={k}, h={h})", fontsize=11)
    if has_groups:
        ax1.legend(fontsize=7, ncol=max(1, len(all_group_names) // 3 + 1))

    ax2.set_xlabel("序号", fontsize=10)
    ax2.set_ylabel("CUSUM", fontsize=10)
    ax2.legend(fontsize=7, ncol=2)

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
        stats_rows.append({
            "分组": label,
            "均值(μ)": f"{gr['mu']:.4f}",
            "标准差(σ)": f"{gr['sigma']:.4f}",
            "上偏移报警": str(len(gr["alarm_plus"])),
            "下偏移报警": str(len(gr["alarm_minus"])),
        })

    return AnalysisResult(
        task="spc_cusum",
        tables={
            "cusum_stats": pd.DataFrame(stats_rows),
        },
        figures=[fig],
        summary="".join(summary_parts),
        messages=warn_msgs,
        metadata={
            "k": k, "h": h,
            "total_alarms": total_alarms,
            "n_groups": len(group_results),
            "groups": [str(g) for g in all_group_names if g != "_default"],
        },
    )


def ewma_chart(req: AnalysisRequest) -> AnalysisResult:
    """EWMA (指数加权移动平均) 控制图 — 对近期观测赋予更高权重。

    参数:
        lam: 平滑参数 (0<λ≤1)。λ越小越平滑，λ=1 等同于原始数据。常用 λ=0.2
        L: 控制限宽度 (常用 2.7~3.0)
        mu: 过程均值 (如未提供，从数据估计)
        sigma: 过程标准差 (如未提供，从数据估计)
        group_col: 分组依据 (可选，不同值=不同颜色的线，共享坐标轴)
    """
    y_col = req.target_col
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in req.data.columns)

    if has_groups:
        group_vals = req.data[group_col]
        group_names = sorted(group_vals.dropna().unique())
    else:
        group_vals = pd.Series("_default", index=req.data.index)
        group_names = ["_default"]

    # ── 前端分组筛选支持 ──
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        group_names = [g for g in group_names if str(g) in filter_set]
        if not group_names:
            group_names = sorted(group_vals.dropna().unique())

    # 公共参数 (ewma)
    lam = req.params.get("lam", 0.2)
    L = req.params.get("L", 2.7)
    try:
        lam, L = float(lam), float(L)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="spc_ewma", status="error",
            messages=[f"参数 lam/L 值无效: lam={lam}, L={L}，请输入数值"],
        )
    if not 0 < lam <= 1:
        return AnalysisResult(
            task="spc_ewma", status="error",
            messages=[f"λ (平滑参数) 必须在 (0, 1] 范围内，当前值: {lam}"])

    user_mu = req.params.get("mu")
    user_sigma = req.params.get("sigma")
    if user_mu is not None and user_sigma is not None:
        try:
            user_mu, user_sigma = float(user_mu), float(user_sigma)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="spc_ewma", status="error",
                messages=[f"参数 mu/sigma 值无效: mu={user_mu}, sigma={user_sigma}，请输入数值"],
            )

    # 分组处理
    group_results = []
    all_group_names = []
    for gname in group_names:
        mask = group_vals == gname if has_groups else pd.Series(True, index=req.data.index)
        gdata = req.data.loc[mask, y_col].dropna()
        if len(gdata) < 3:
            continue
        all_group_names.append(gname)

        if user_mu is not None and user_sigma is not None:
            mu, sigma = user_mu, user_sigma
        else:
            mu = float(gdata.mean())
            sigma = float(gdata.std(ddof=1))
        if sigma < EPSILON:
            continue

        n = len(gdata)
        ewma_vals = np.zeros(n)
        ewma_vals[0] = lam * gdata.values[0] + (1 - lam) * mu
        for i in range(1, n):
            ewma_vals[i] = lam * gdata.values[i] + (1 - lam) * ewma_vals[i-1]

        sigma_ewma_asym = sigma * np.sqrt(lam / (2 - lam))
        t = np.arange(1, n + 1)
        corr = 1 - (1 - lam) ** (2 * t)
        sigma_ewma_t = sigma * np.sqrt(lam / (2 - lam) * corr)

        ucl_t = mu + L * sigma_ewma_t
        lcl_t = mu - L * sigma_ewma_t
        above = ewma_vals > ucl_t
        below = ewma_vals < lcl_t
        violations = above | below

        group_results.append({
            "name": gname, "data": gdata.values, "mu": mu, "sigma": sigma,
            "ewma": ewma_vals, "ucl_t": ucl_t, "lcl_t": lcl_t,
            "ucl_asym": float(mu + L * sigma_ewma_asym),
            "lcl_asym": float(mu - L * sigma_ewma_asym),
            "violations": violations, "n": n,
        })

    if len(group_results) < 1:
        return AnalysisResult(
            task="spc_ewma", status="error",
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
    if user_mu is None:
        warn_msgs.append(
            "⚠ μ/σ 从各组数据独立估计。"
            "建议通过参数 mu/sigma 指定已知受控状态的参数。"
        )

    for gr in group_results:
        gname = gr["name"]
        color = group_colors[gname]
        label = str(gname) if has_groups else None
        pos = np.arange(gr["n"])
        total_violations += int(gr["violations"].sum())

        ax.plot(pos, gr["data"], "o-", markersize=2, alpha=0.3,
                color=color, linewidth=0.6, label=f"{label} 原始" if has_groups else "原始数据")
        ax.plot(pos, gr["ewma"], "-", color=color, linewidth=2,
                label=label if has_groups else f"EWMA (λ={lam})")
        ax.axhline(gr["mu"], color=color, linestyle="--", linewidth=0.8, alpha=0.4)
        ax.plot(pos, gr["ucl_t"], "--", color=color, linewidth=0.8, alpha=0.5)
        ax.plot(pos, gr["lcl_t"], "--", color=color, linewidth=0.8, alpha=0.5)

        if gr["violations"].sum() > 0:
            vpos = np.where(gr["violations"])[0]
            ax.scatter(vpos, gr["ewma"][vpos], s=60, color=color, marker="x",
                      linewidths=2, zorder=5)

    # 全局参考线
    ax.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5, alpha=0.3)

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(y_col, fontsize=10)
    ax.set_title(f"EWMA 控制图 — {y_col} (λ={lam}, L={L})", fontsize=11)
    if has_groups:
        ax.legend(fontsize=7, ncol=max(1, len(all_group_names) // 3 + 1))
    else:
        ax.legend(fontsize=7.5, loc="upper left", ncol=2)
    fig.tight_layout()

    # 汇总
    summary_parts = [f"EWMA (λ={lam}, L={L}) 检测到 {total_violations} 个违规点。"]
    for gr in group_results:
        gname = gr["name"]
        label = f"{gname}: " if has_groups else ""
        summary_parts.append(
            f"{label}渐近UCL={gr['ucl_asym']:.4f}, LCL={gr['lcl_asym']:.4f}；"
        )

    # 统计表
    stats_rows = []
    for gr in group_results:
        gname = gr["name"]
        label = str(gname) if has_groups else "全部"
        stats_rows.append({
            "分组": label,
            "均值(μ)": f"{gr['mu']:.4f}",
            "标准差(σ)": f"{gr['sigma']:.4f}",
            "渐近UCL": f"{gr['ucl_asym']:.4f}",
            "渐近LCL": f"{gr['lcl_asym']:.4f}",
            "违规点数": str(int(gr["violations"].sum())),
        })

    meta: dict = {
        "lam": lam, "L": L,
        "total_violations": total_violations,
        "n_groups": len(group_results),
        "groups": [str(g) for g in all_group_names if g != "_default"],
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
    ks_n = sp_stats.kstest(values, sp_stats.norm(loc=mu, scale=sigma).cdf)
    fits["Normal"] = {"dist": sp_stats.norm, "args": (mu, sigma), "ks_p": ks_n.pvalue}

    # Lognormal
    if (values > 0).all():
        shape_ln, loc_ln, scale_ln = sp_stats.lognorm.fit(values, floc=0)
        ks_ln = sp_stats.kstest(values, sp_stats.lognorm(shape_ln, loc=0, scale=scale_ln).cdf)
        fits["Lognormal"] = {"dist": sp_stats.lognorm, "args": (shape_ln, 0, scale_ln),
                            "ks_p": ks_ln.pvalue}

    # Weibull
    if (values > 0).all():
        try:
            shape_w, loc_w, scale_w = sp_stats.weibull_min.fit(values, floc=0)
            ks_w = sp_stats.kstest(values, sp_stats.weibull_min(shape_w, loc=0, scale=scale_w).cdf)
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
    ax.axhline(cl, color=PALETTE["control"]["primary"], linestyle="--", linewidth=2, label=f"CL (中位数)={cl:.4f}")

    if ucl is not None:
        ax.axhline(ucl, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.5,
                   label=f"UCL (P99.865)={ucl:.4f}")
        if ucl_2s:
            ax.axhline(ucl_2s, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.8, alpha=0.6)
        if ucl_1s:
            ax.axhline(ucl_1s, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4)
        ax.fill_between(pos, cl, ucl, alpha=0.04, color=PALETTE["center"]["primary"])

    if lcl is not None:
        ax.axhline(lcl, color=PALETTE["control"]["primary"], linestyle="--", linewidth=1.5,
                   label=f"LCL (P0.135)={lcl:.4f}")
        if lcl_2s:
            ax.axhline(lcl_2s, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.8, alpha=0.6)
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
    ax.legend(fontsize=7.5, loc="upper right", ncol=2)
    fig.tight_layout()

    # ── 汇总 ──
    n_violations = len(violations)
    is_stable = n_violations == 0
    ucl_str = f"{ucl:.4f}" if ucl is not None else "N/A"
    lcl_str = f"{lcl:.4f}" if lcl is not None else "N/A"
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
