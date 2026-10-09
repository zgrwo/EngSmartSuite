"""属性控制图（attribute_chart）。"""

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Opt, Spec
from smartsuite.engine._guard import BoundaryReport, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import _adjust_xlabels, round_for_display
from smartsuite.engine.spc_charts._shared import _natural_sort_key

# ── 声明式参数契约（阶段 P4 步骤③，2026-09-24）──
# 契约：docs/governance/improvement-plan.md §六
#
# 只有 `chart_type` 是**纯参数校验**（枚举 + 默认值），故进 Spec；
# `group_col` / `n_col` / `subgroup_col` / `filter_groups` 需引用实际列，
# 属**依赖数据**的检查，留在引擎（`n_col` 的存在性检查见下方实现）。
#
# `Choice` 自带大小写与首尾空白归一：`"P"` / `"p "` 都会被接受为 p 图
# —— Web 表单与 YAML 模板里写 `"P"` 很自然，不该因大小写报错。
PARAM_SPEC = Spec(
    chart_type=Opt(
        Choice("p", "np", "c", "u"),
        default="p",
        label="控制图类型",
        hint="p=不良率（需 0/1 数据）、np=不良数、c=缺陷数、u=单位缺陷数",
    ),
    group_col=Opt(label="分组列", hint="按该列分出多条序列（多机台/多产线）"),
    n_col=Opt(label="样本量列", hint="每组的检验数；不给时按行数计"),
    subgroup_col=Opt(label="子组列", hint="长格式子组标识"),
    filter_groups=Opt(label="分组筛选", hint="仅保留指定分组的序列"),
)


def _unequal_sample_sizes(n_vals) -> tuple[float, float] | None:
    """子组样本量是否不一致；一致返回 None，不一致返回 (最小, 最大)。

    契约：docs/governance/boundary-contract.md（B0 拒绝）

    用于 np/c 图的前置校验——这两类图的控制限是**常数**，只在样本量相等时成立。
    用相对容差比较（浮点 n_col 可能有微小表示误差），而非精确相等。
    """
    arr = np.asarray(n_vals, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    lo, hi = float(finite.min()), float(finite.max())
    if lo == hi:
        return None
    # 相对容差：1e-9 量级视为相等（n_col 浮点读取的表示误差）
    if (hi - lo) <= 1e-9 * max(abs(hi), 1.0):
        return None
    return lo, hi


def attribute_chart(req: AnalysisRequest) -> AnalysisResult:
    """计数型/属性控制图：p (不良率)、np (不良数)、c (缺陷数)、u (单位缺陷率)。

    参数:
        chart_type: "p" | "np" | "c" | "u"
        X 列 (feature_cols[0]): 横坐标 — 类别/日期/数字。空→顺序索引
        group_col: 分组依据 (可选，不同值=不同颜色的线)
        n_col: 样本量列名 (p/u 图需要，变样本量时使用)
    """
    # ── 参数校验（阶段 P4 步骤③：声明式 Spec + 抛异常式传播）──
    # 原先 `req.params.get("chart_type", "p")` 在键存在但值为 None 时
    # 默认值不生效 → 报"不支持的图表类型: None"（归因误导，且违反引擎
    # "None = 未提供"的既有约定）。Spec 统一处理该语义与大小写归一。
    #
    # **抛异常而非 return status="error"**：由 orchestrator 的
    # `except SmartSuiteError → build_error_result()` 统一转结果 ——
    # 若在此早退，每迁移一个任务反而 +1 处早退
    # （见 core/param_spec.py::validate_or_raise 的说明）。
    _params = PARAM_SPEC.validate_or_raise(req.params)
    chart_type = _params.chart_type
    data = req.data.copy()
    y_col = req.target_col
    _text_mapped = False  # 文本二值列被映射为 0/1 时置 True（用于下游语义提示）

    # ── 边界处置（B1）：目标列的 ±Inf 必须清洗并披露 ──
    # 审查 2026-10-09 P0-5：`dropna()` 不剔除 ±Inf，p/np/c/u 的均值被拉成 inf，
    # 使 CL/UCL 全为 inf、判据 `stat > ucl` 恒 False → 假阴性「超出控制限 0/100 个点」。
    _report = BoundaryReport()
    if y_col in data.columns and pd.api.types.is_numeric_dtype(data[y_col]):
        _cleaned, _n_non_finite = clean_series(data[y_col], column=y_col, report=_report)
        if _n_non_finite:
            data = data.loc[_cleaned.index]

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
    n_col = _params.n_col
    # 审查 2026-09-24（P4 步骤③ 迁移时发现）：原实现是
    # `if n_col and n_col in data.columns:` —— 用户显式给了 n_col 但列名打错时
    # 条件为假，引擎**静默回落到 size（行数）**，控制限随之算错且**无任何提示**。
    # 这违反 boundary-contract 的"禁止静默降级"：用户以为在按实际检验数计算。
    # 显式指定即必须生效；不存在则明确拒绝。
    if n_col and n_col not in data.columns:
        _avail = ", ".join(map(str, list(data.columns)[:12]))
        return AnalysisResult(
            task="spc_attribute",
            status="error",
            messages=[
                f"样本量列「{n_col}」不存在于数据中。可用列：{_avail}"
                + ("…" if len(data.columns) > 12 else "")
                + "。若不需按实际检验数计算，请不要指定 n_col（默认按行数计）。"
            ],
        )
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

    # 审查 2026-09-24（P4 步骤③ 迁移）：`p` 与 `u` 图原先各写一份**完全相同**的
    # 零样本量检查（消息逐字一致），合并到分派之前做一次。`np` 图的消息不同
    # （它明确指向 n_col 语义），保留在各自分支内。
    if chart_type in ("p", "u") and (agg["n_vals"] == 0).any():
        return AnalysisResult(
            task="spc_attribute",
            status="error",
            messages=["子组样本量包含0值，无法计算比率控制图"],
        )

    if chart_type == "p":
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
        # 审查 2026-09-24（第三轮复核 P2-6）：np 图的控制限公式
        #   UCL = np̄ + 3·sqrt(np̄(1−p̄))
        # 是**常数限**，仅在"各子组样本量相等"时成立。原实现对 n_vals 不等的情形
        # 无任何校验，直接套常数限 → 静默给出错误的控制限与违规判定。
        # 对照：p 图用逐点变限 cl ± 3·sqrt(cl(1−cl)/n_i)，不等 n 下仍然正确。
        _np_unequal = _unequal_sample_sizes(agg["n_vals"])
        if _np_unequal is not None:
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=[
                    f"np 图要求各子组样本量相等，但实际样本量不一致（最小 {_np_unequal[0]:g}、"
                    f"最大 {_np_unequal[1]:g}，共 {len(agg)} 个子组）。"
                    "np 图使用常数控制限，样本量不等时会给出错误的控制限与违规判定。"
                    "请改用 p 图（支持不等样本量，控制限逐点随 n 变化），"
                    "或将数据按等样本量重新划分批次。"
                ],
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
        # 审查 2026-09-24 P2-6：c 图同理——UCL = c̄ + 3·sqrt(c̄) 要求各子组
        # 的**检查单位数**相等。等样本量场景下 n_col 恒定或未提供（每子组行数相同），
        # 故这里用 n_vals 而非 size 判定（n_col 显式给出单位数时以其为准）。
        _c_unequal = _unequal_sample_sizes(agg["n_vals"])
        if _c_unequal is not None:
            return AnalysisResult(
                task="spc_attribute",
                status="error",
                messages=[
                    f"c 图要求各子组的检查单位数相等，但实际不一致（最小 {_c_unequal[0]:g}、"
                    f"最大 {_c_unequal[1]:g}，共 {len(agg)} 个子组）。"
                    "c 图使用常数控制限，单位数不等时会给出错误的控制限与违规判定。"
                    "请改用 u 图（支持不等单位数，控制限逐点随 n 变化），"
                    "或统一各子组的检查单位数。"
                ],
            )
        agg["stat"] = agg["count"].astype(float)
        stat_name = "缺陷数(c)"
        c_bar = float(agg["count"].mean())
        cl = c_bar
        ucl_const = float(c_bar + 3 * np.sqrt(c_bar))

    elif chart_type == "u":
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

    # 违规定位（**先做控制限有限性后置断言**）
    # 审查 2026-10-09 P0-5：±Inf 曾穿透 `dropna()` 把 c̄ 拉成 inf → CL/UCL 全 inf；
    # 判据 `stat > ucl` 在 ucl=inf 时恒为 False → 报「超出控制限 0/100 个点」
    # （假阴性），且 Inf 渗漏进 `control_stats` 表（101 个非有限值）。
    _limits = [
        float(cl),
        float(ucl_const) if ucl_const is not None else None,
        float(agg["ucl"].max()),
        float(agg["lcl"].min()),
    ]
    _bad_limits = [v for v in _limits if v is not None and not np.isfinite(v)]
    if _bad_limits:
        return AnalysisResult(
            task="spc_attribute",
            status="error",
            messages=[
                "控制限计算为非有限值（数据量级过大或含极端值），无法给出控制图结论；"
                "请先检查目标列是否存在异常量级后重试",
                *_report.messages(),
            ],
        )

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
        messages=_report.messages(),
        metadata={
            "chart_type": chart_type,
            "cl": float(cl),
            "n_points": m,
            "n_violations": violations,
            "groups": [str(g) for g in all_group_names if g != "_default"],
            "text_binary_mapped": _text_mapped,
            "nan_group_rows_dropped": _nan_dropped,
            "boundary_codes": _report.codes(),
        },
    )
