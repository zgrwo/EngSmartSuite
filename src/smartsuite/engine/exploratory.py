"""探索性分析模块：箱线图、散点图、中位数 CI、Bootstrap CI。"""

import logging
import re
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from sklearn.linear_model import LinearRegression

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Finite, Integer, Opt, Spec
from smartsuite.core.param_specs_common import (
    BOOL_SWITCH,
    CI_LEVEL,
    GROUP_COL,
    LSL,
    RANDOM_STATE,
    TARGET,
    USL,
)
from smartsuite.engine._guard import (
    BoundaryReport,
    clean_frame,
    clean_series,
    degenerate_column_reason,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    _adjust_xlabels,
    disp,
    round_for_display,
)

logger = logging.getLogger(__name__)


# ── 声明式参数契约（P4 步骤③，第二十轮：共享字段库驱动）──
PARAM_SPECS = {
    # 本模块含 4 个任务（box_chart/scatter_plot/bootstrap_ci/median_ci），
    # 故按任务登记
    "median_ci": Spec(ci_level=CI_LEVEL),
    # 第二十五轮：
    # `n_bootstrap` 声明为 [100, 10000] 闭区间 —— 这是引擎原夹紧逻辑的上下界；
    # 迁移前越界值被**静默夹紧**（50→100、20000→10000），非法值静默回落默认 2000。
    "bootstrap_ci": Spec(
        statistic=Opt(
            Choice(
                ("mean", "均值"),
                ("median", "中位数"),
                ("std", "标准差"),
                ("var", "方差"),
            ),
            default="mean",
            label="统计量",
            hint="要估计置信区间的统计量",
        ),
        n_bootstrap=Opt(
            Integer(min=100, max=10000),
            default=2000,
            label="重抽样次数",
            hint="Bootstrap 重抽样次数，范围 [100, 10000]；越多越稳定也越慢",
        ),
        ci_level=CI_LEVEL,
        random_state=RANDOM_STATE,
    ),
    # 第二十五轮：`fit` 此前**无白名单校验**（拼错静默变成「不拟合」）。
    # `show_ci` 的默认值是**字符串** "true"（不是布尔），故 Spec 只接受
    # "true"/"false" 字符串；「字符串 → 布尔」的转换留在引擎。
    "scatter_plot": Spec(
        fit=Opt(
            Choice(
                ("none", "不拟合"),
                ("linear", "线性趋势线"),
                ("lowess", "LOWESS 平滑线"),
            ),
            default="none",
            label="拟合方式",
            hint="线性=最小二乘直线；LOWESS=局部加权平滑（适合非线性趋势）",
        ),
        # 第三十轮：改用共享的 `BOOL_SWITCH`（**行为改进**）。
        # 迁移前是透传字段 + 引擎的宽容归一 `str.lower() not in ("false","0","no","")`，
        # 于是 `"maybe"`/`"yes"`/`123` 都**静默变成 True**（用户以为关掉了却还开着）。
        # 现由 `Choice` + 别名（`True`/`1` → "true"）收口：合法写法照旧，非法写法明确拒绝。
        show_ci=BOOL_SWITCH,
        group_col=GROUP_COL,
    ),
    # 第二十六轮：`mode` 此前**无白名单校验** —— 实测 mode='grid'/'FACET_' 都返回
    # ok 并静默按 facet 执行（用户以为切换了布局）。现由 Choice 明确拒绝。
    # 五个控制/规格限 + target 由**动态键循环**读取，与 spc_xbar 同构，全部来自共享库。
    "box_chart": Spec(
        mode=Opt(
            Choice(("facet", "分面（每水平一个子图）"), ("nested", "嵌套（同图分组）")),
            default="facet",
            label="布局模式",
            hint="分面=每个水平独立子图；嵌套=同一坐标轴内按组并列",
        ),
        # 第三十轮：与 `scatter_plot.show_ci` 同因同解 —— 改用共享 `BOOL_SWITCH`。
        # 注意默认值从布尔 `True` 变为字符串 `"true"`（对齐 `DEFAULT_PARAMS`）；二者等价。
        show_stats=BOOL_SWITCH,
        group_col=GROUP_COL,
        usl=USL,
        lsl=LSL,
        ucl=Opt(Finite(), default=None, label="控制上限 UCL", hint="可选参考线"),
        lcl=Opt(Finite(), default=None, label="控制下限 LCL", hint="可选参考线"),
        cl=Opt(Finite(), default=None, label="中心线 CL", hint="可选参考线"),
        target=TARGET,
    ),
}


def median_ci(req: AnalysisRequest) -> AnalysisResult:
    """中位数置信区间 — 基于二项分布符号检验的非参数方法。

    不依赖任何分布假设，适用于偏态或未知分布数据。
    """
    data = req.data[req.target_col].dropna()
    # 审查 2026-09-22 发现 3：±Inf 穿透 dropna 使 hist/set_xlim 抛 ValueError
    # 第三十七轮：手抄清洗 → `_guard.clean_series`（披露与错误码在一处产出）
    _report = BoundaryReport()
    data, _n_inf = clean_series(data, column=req.target_col, report=_report)
    n = len(data)
    if n < 5:
        return AnalysisResult(
            task="median_ci", status="error", messages=["有效数据不足(至少5个点)"]
        )

    # 参数校验（P4 步骤③）：失败时抛 ParamValidationError
    ci_level = PARAM_SPECS["median_ci"].validate_or_raise(req.params).ci_level
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
    ax.hist(
        data,
        bins=min(30, int(np.sqrt(n)) * 2),
        color=PALETTE["data"]["secondary"],
        edgecolor="white",
        alpha=0.7,
    )
    # 中位数/CI 端点带**数据量纲** → 共享展示格式化器 `disp`
    # （审查 2026-10-09 C-1/R2BD-06：×1e-9 时图例、表、摘要三处全为 `0.0000`）
    ax.axvline(
        median, color=PALETTE["center"]["primary"], linewidth=2, label=f"中位数={disp(median)}"
    )
    ax.axvline(lower, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5)
    ax.axvline(
        upper,
        color=PALETTE["anomaly"]["primary"],
        linestyle="--",
        linewidth=1.5,
        label=f"{ci_level * 100:.0f}% CI: [{disp(lower)}, {disp(upper)}]",
    )
    ax.axvspan(lower, upper, alpha=0.1, color=PALETTE["anomaly"]["primary"])
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("频数", fontsize=10)
    ax.set_title(f"中位数 {ci_level * 100:.0f}% CI — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    return AnalysisResult(
        task="median_ci",
        tables={
            "median_ci": pd.DataFrame(
                {
                    "指标": ["中位数", "CI下限", "CI上限", "置信水平", "样本量", "方法"],
                    "值": [
                        disp(median),
                        disp(lower),
                        disp(upper),
                        f"{ci_level:.0%}",
                        str(n),
                        "二项分布符号检验",
                    ],
                }
            )
        },
        figures=[fig],
        summary=(
            f"中位数={disp(median)}, {ci_level * 100:.0f}% CI: [{disp(lower)}, {disp(upper)}]"
        ),
        metadata={
            "median": median,
            "ci_lower": lower,
            "ci_upper": upper,
            "ci_level": ci_level,
            "n": n,
        },
        messages=_report.messages(),
    )


def bootstrap_ci(req: AnalysisRequest) -> AnalysisResult:
    """Bootstrap 置信区间 — 不依赖正态假设的稳健区间估计。

    参数:
        statistic: "mean" (默认) | "median" | "std" | "var"
        n_bootstrap: 重抽样次数 (默认 2000)
        ci_level: 置信水平 (默认 0.95)

    返回百分位法（Percentile）Bootstrap 置信区间。
    """
    data = req.data[req.target_col].dropna()
    # 第三十七轮：手抄清洗 → `_guard.clean_series`（披露与错误码在一处产出）
    _report = BoundaryReport()
    data, _n_inf = clean_series(data, column=req.target_col, report=_report)
    n = len(data)
    if n < 5:
        return AnalysisResult(
            task="bootstrap_ci",
            status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    # 参数校验（P4 步骤③，第二十五轮）：失败时抛 ParamValidationError。
    # 迁移前 `n_bootstrap` 被静默夹紧（50->100、20000->10000）、非法值静默回落 2000。
    _bp = PARAM_SPECS["bootstrap_ci"].validate_or_raise(req.params)
    statistic = _bp.statistic
    if statistic not in ("mean", "median", "std", "var"):
        return AnalysisResult(
            task="bootstrap_ci",
            status="error",
            messages=[f"不支持的 statistic: {statistic!r}，可选 mean/median/std/var"],
        )
    # `n_bootstrap` / `ci_level` 已由 Spec 一次校验并取用（见上方注释）
    n_boot = _bp.n_bootstrap
    ci_level = _bp.ci_level
    alpha = 1 - ci_level
    random_state = _bp.random_state

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
    elif statistic == "var":
        orig_stat = float(np.var(values, ddof=1))

        def stat_fn(x):
            return np.var(x, ddof=1)
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
    ax.hist(
        boot_stats,
        bins=40,
        color=PALETTE["data"]["secondary"],
        edgecolor="white",
        alpha=0.8,
        density=True,
    )
    ax.axvline(
        orig_stat,
        color=PALETTE["center"]["primary"],
        linewidth=2,
        label=f"点估计={disp(orig_stat)}",
    )
    ax.axvline(
        ci_lower_pct,
        color=PALETTE["anomaly"]["primary"],
        linestyle="--",
        linewidth=1.5,
        label=f"{ci_level * 100:.0f}% CI下限={disp(ci_lower_pct)}",
    )
    ax.axvline(
        ci_upper_pct,
        color=PALETTE["anomaly"]["primary"],
        linestyle="--",
        linewidth=1.5,
        label=f"{ci_level * 100:.0f}% CI上限={disp(ci_upper_pct)}",
    )
    ax.axvspan(ci_lower_pct, ci_upper_pct, alpha=0.1, color=PALETTE["anomaly"]["primary"])
    ax.set_xlabel(f"{statistic} ({req.target_col})", fontsize=10)
    ax.set_ylabel("Bootstrap 密度", fontsize=10)
    ax.set_title(
        f"Bootstrap {statistic.upper()} CI — {req.target_col} "
        f"({ci_level * 100:.0f}%, {n_boot}次重抽样, n={n})",
        fontsize=10,
    )
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    ci_width = ci_upper_pct - ci_lower_pct
    # 点估计/CI 端点/宽度都带**数据量纲** → `disp`（审查 2026-10-09 C-1/R2BD-06）
    summary = (
        f"{statistic} = {disp(orig_stat)}, "
        f"{ci_level * 100:.0f}% Bootstrap CI: "
        f"[{disp(ci_lower_pct)}, {disp(ci_upper_pct)}] (宽度={disp(ci_width)})"
    )

    return AnalysisResult(
        task="bootstrap_ci",
        tables={
            "bootstrap_ci": pd.DataFrame(
                {
                    "统计量": [
                        statistic,
                        "点估计",
                        f"CI下限 ({ci_level * 100:.0f}%)",
                        f"CI上限 ({ci_level * 100:.0f}%)",
                        "CI宽度",
                        "重抽样次数",
                        "样本量",
                    ],
                    "值": [
                        statistic,
                        disp(orig_stat),
                        disp(ci_lower_pct),
                        disp(ci_upper_pct),
                        disp(ci_width),
                        str(n_boot),
                        str(n),
                    ],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "statistic": statistic,
            "point_estimate": orig_stat,
            "ci_lower": ci_lower_pct,
            "ci_upper": ci_upper_pct,
            "ci_level": ci_level,
            "n_bootstrap": n_boot,
            "n": n,
        },
        messages=_report.messages(),
    )


def _draw_group_stats_table(
    ax,
    groups: list,
    group_data: list,
    stat_rows: list[dict[str, Any]],
    ref_lines: list[tuple[float, str, str, str]],
) -> None:
    """在坐标区下沿预留带内绘制单张统计表（列=分组、行=统计量）。

    2026-09-22 用户复核：逐箱重复 5 行标注信息冗余，改为**一张表**；表格数据列
    与箱体共用同一套 x 位置（行标签列占左侧固定宽，其余数据列与坐标轴等宽），
    坐标区下界按表格高度下压、箱体压缩到上部，**图形整体尺寸不变**。
    """
    n_groups = len(groups)
    fig = ax.get_figure()
    # 行标签列按英寸折算轴宽比例：组数变化导致图宽变化时，标签列物理宽度稳定
    fig_width = fig.get_figwidth() if fig is not None else 6.0
    axes_width_in = max(ax.get_position().width * fig_width, 1e-6)
    label_w = min(max(0.62 / axes_width_in, 0.04), 0.14)
    data_w = (1.0 - label_w) / n_groups
    # 数据列中心必须与箱体 x 位置（1..n）一一对应：联立解得 xlim 左界
    ax.set_xlim(0.5 - label_w / data_w, 0.5 - label_w / data_w + 1.0 / data_w)

    d_lo = min(float(np.min(d)) for d in group_data if len(d))
    d_hi = max(float(np.max(d)) for d in group_data if len(d))
    # 跨度取「数据 ∪ 参考线」——保证表格带始终占据坐标区下沿固定比例
    lo = min([d_lo] + [val for val, _c, _s, _lab in ref_lines])
    hi = max([d_hi] + [val for val, _c, _s, _lab in ref_lines])
    span = hi - lo
    if not np.isfinite(span) or span <= 0:  # 常量数据：给一个可用的相对跨度
        span = max(abs(hi), 1.0)
    band_bottom, band_height = 0.02, 0.24
    # 让数据最小值落在表格顶边下方 gap 处，反解下界外扩量 L：
    # f = L / (span + L + 0.06·span)，取 f = band_top + gap
    f = min(band_bottom + band_height + 0.02, 0.9)
    lower_pad = f * 1.06 * span / (1.0 - f)
    ax.set_ylim(lo - lower_pad, hi + 0.06 * span)

    def _fmt_ann(v) -> str:
        """标注数值格式：与 group_statistics 表逐位一致。

        round_for_display 对常规量级取 3 位小数、对微尺度改按有效数字；此处反过来
        判别：能整除到 3 位小数的（常规量级）用定点输出（避开 :g 对大数值的 6 位
        有效数字二次舍入），否则（微尺度）用 :g 保持紧凑可读。
        """
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return str(v)
        if not np.isfinite(fv):
            return str(fv)
        if np.round(fv, 3) == fv:
            return f"{fv:.3f}".rstrip("0").rstrip(".") or "0"
        return f"{fv:g}"

    cell_text = [
        ["n"] + [str(row["样本量"]) for row in stat_rows],
        ["均值"] + [_fmt_ann(row["均值"]) for row in stat_rows],
        ["标准差"] + [_fmt_ann(row["标准差"]) for row in stat_rows],
        ["最大值"] + [_fmt_ann(row["最大值"]) for row in stat_rows],
        ["最小值"] + [_fmt_ann(row["最小值"]) for row in stat_rows],
    ]
    fontsize = 8.0 if n_groups <= 8 else 7.0 if n_groups <= 15 else 6.0
    table = ax.table(
        cellText=cell_text,
        colWidths=[label_w] + [data_w] * n_groups,
        bbox=[0.0, band_bottom, 1.0, band_height],
        cellLoc="center",
        zorder=6,
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)
    for cell in table.get_celld().values():
        cell.set_edgecolor(PALETTE["misc"]["grid"])
        cell.set_linewidth(0.6)


def _build_stat_row(group_label: str, gdata) -> dict[str, Any]:
    """单组描述统计行（group_statistics 表与箱体标注共用同一构造，保证逐位一致）。

    审查 2026-09-21 R1-3：原为固定位 round(x, 3)，微尺度（×1e-9）下整表归零；
    改走共享 round_for_display（低于 0.5×10^-decimals 时自动改按有效数字），
    与 detection/capability 展示口径一致。
    """
    return {
        "分组": group_label,
        "样本量": len(gdata),
        "均值": round_for_display(float(gdata.mean()), 3),
        "中位数": round_for_display(float(gdata.median()), 3),
        "标准差": round_for_display(float(gdata.std(ddof=1)), 3),
        "IQR": round_for_display(float(gdata.quantile(0.75) - gdata.quantile(0.25)), 3),
        "最小值": round_for_display(float(gdata.min()), 3),
        "最大值": round_for_display(float(gdata.max()), 3),
    }


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
        return AnalysisResult(
            task="box_chart", status="error", messages=["需要至少 1 个分类列作为分组依据"]
        )

    # 分组列优先 params.group_col（Web 面板选择），回退 feature_cols[0]
    # （审查 2026-08-19 #2.17：此前引擎忽略 params.group_col，UI 选择无效）
    # 审查 2026-09-06 F-D5：falsy 回退改 is not None——空串显式报错，不静默替换
    group_col = req.params.get("group_col")
    if group_col is None:
        group_col = req.feature_cols[0]
    if group_col not in req.data.columns:
        return AnalysisResult(
            task="box_chart",
            status="error",
            messages=[
                f"分组列「{group_col}」不存在于数据中。可用列: {list(req.data.columns)[:10]}"
            ],
        )
    sub_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None
    # Round-2 #A3：group_col 可能与 target/sub_col 同列（UI 可触发），
    # 去重列名避免 sub[col] 返回 DataFrame → .unique() AttributeError
    _cols_needed = list(dict.fromkeys([req.target_col, group_col] + ([sub_col] if sub_col else [])))
    # 参数校验（P4 步骤③，第二十六轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # `mode` 此前**无白名单校验**（实测 'grid'/'FACET_' 静默按 facet 执行）。
    _bc = PARAM_SPECS["box_chart"].validate_or_raise(req.params)
    mode = _bc.mode

    # ── 规格限与控制限（可选参考线）──
    def _draw_ref_lines(ax):
        """在箱线图上叠加规格限/控制限参考线。"""
        for val, color, style, label in _ref_lines:
            ax.axhline(val, color=color, linestyle=style, linewidth=1.0, alpha=0.8, label=label)
        if _ref_lines:
            ax.legend(fontsize=7.5, loc="upper right")

    _ref_lines: list[tuple[float, str, str, str]] = []
    # 审查 2026-09-19 D-1：float() 不拦 inf/nan（capability C1 同族），显式拒绝
    _ref_labels = {
        "usl": "规格上限 USL",
        "lsl": "规格下限 LSL",
        "ucl": "控制上限 UCL",
        "lcl": "控制下限 LCL",
        "cl": "中心线 CL",
    }
    for key, color, style in [
        ("usl", PALETTE["anomaly"]["primary"], "-"),
        ("lsl", PALETTE["anomaly"]["primary"], "-"),
        ("ucl", PALETTE["control"]["primary"], "--"),
        ("lcl", PALETTE["control"]["primary"], "--"),
        ("cl", PALETTE["control"]["primary"], "--"),
    ]:
        # 参考线已由 Spec 校验（`Finite()`，含 isfinite）→ 此处只需取值
        val_f = _bc.get(key)
        if val_f is not None:
            _ref_lines.append((float(val_f), color, style, key.upper()))
    # `target` 同样已由 Spec 校验
    target_f = _bc.target
    if target_f is not None:
        _ref_lines.append((float(target_f), PALETTE["direction"]["zero"], ":", "Target"))

    # show_stats：把 n/均值/标准差/最大值/最小值标注到每个箱体正下方
    # （标注带占用坐标区下沿，箱体自动压缩，图形整体尺寸不变；分面模式逐面板标注）
    # `show_stats` 现由 `BOOL_SWITCH` 校验（合法值是 "true"/"false"，
    # 且 `True`/`1` 经别名归一到 "true"）→ 这里只需一次比较。
    # 原先的宽容白名单（"0"/"no"/""）已随非法值被明确拒绝而不再需要。
    show_stats = _bc.show_stats == "true"

    sub = req.data[_cols_needed].dropna()
    # 审查 2026-09-22 发现 3：目标列 ±Inf 使 boxplot/set_ylim 抛 ValueError
    # 第三十七轮：同上，改走 `_guard.clean_frame`（多列按行清洗）
    _report = BoundaryReport()
    sub, _n_inf = clean_frame(sub, [req.target_col], report=_report)
    if len(sub) < 5:
        return AnalysisResult(
            task="box_chart", status="error", messages=["有效数据不足(至少5个点)"]
        )

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
        return AnalysisResult(
            task="box_chart", status="error", messages=["分组列需要至少 2 个不同值"]
        )
    if len(groups) > 30:
        return AnalysisResult(
            task="box_chart",
            status="error",
            messages=[f"分组过多({len(groups)}个)，最多支持 30 个分组"],
        )

    # ── 前端筛选支持 ──
    all_groups = list(groups)  # 保存完整列表用于 metadata
    filter_groups = req.params.get("filter_groups")
    if filter_groups and isinstance(filter_groups, list) and len(filter_groups) > 0:
        filter_set = set(str(f) for f in filter_groups)
        groups = [g for g in groups if str(g) in filter_set]
        if not groups:
            groups = all_groups  # 全空则回退

    # ── 描述统计 ──
    stat_rows: list[dict[str, Any]] = [
        _build_stat_row(str(g), sub[sub[group_col] == g][req.target_col]) for g in groups
    ]

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
        if len(groups) >= 2:
            try:
                _, t_p = sp_stats.ttest_ind(*group_data)
                _, mw_p = sp_stats.mannwhitneyu(*group_data)
                test_note = f"t检验 p={t_p:.4f}, MWU p={mw_p:.4f}"
            except (ValueError, RuntimeError):
                logger.debug("t-test/Mann-Whitney test failed in box_chart", exc_info=True)
        else:
            # 2026-08-21 #F1：filter_groups 筛选后仅剩 1 组时，跳过组间检验
            test_note = "仅 1 组，未做组间差异检验"

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
            sg_groups = [
                sg_data[sg_data[group_col] == g][req.target_col].values
                for g in groups
                if len(sg_data[sg_data[group_col] == g]) > 0
            ]
            valid_groups = [g for g in groups if len(sg_data[sg_data[group_col] == g]) > 0]
            if len(valid_groups) >= 2:
                bp = ax.boxplot(sg_groups, tick_labels=valid_groups, patch_artist=True, widths=0.5)
                cmap = cm.tab10
                for pi, patch in enumerate(bp["boxes"]):
                    patch.set_facecolor(cmap(pi % 10))
                for i, gdata in enumerate(sg_groups, 1):
                    # 可复现 jitter（种子基于组序号）
                    jitter = np.random.default_rng(20260819 + i).uniform(-0.12, 0.12, len(gdata))
                    ax.scatter(
                        np.full(len(gdata), i) + jitter,
                        gdata,
                        alpha=0.3,
                        s=8,
                        color=PALETTE["misc"]["grid"],
                        zorder=3,
                    )
            ax.set_title(f"{sub_col}={sg} (n={len(sg_data)})", fontsize=9)
            ax.set_xlabel(group_col, fontsize=8)
            ax.set_ylabel(req.target_col, fontsize=8)
            n_valid = len(valid_groups)
            # 分面同样逐面板标注（2026-09-22 视觉复核：面板尺寸足够，统一体验；
            # 每面板的统计值按该面板内各组重算，与箱体一一对应）
            if show_stats and len(valid_groups) >= 2:
                facet_rows = [
                    _build_stat_row(str(g), sg_data[sg_data[group_col] == g][req.target_col])
                    for g in valid_groups
                ]
                _draw_group_stats_table(ax, valid_groups, sg_groups, facet_rows, _ref_lines)
            _adjust_xlabels(ax, n_valid, fig)
            _draw_ref_lines(ax)
    else:
        fig = Figure(figsize=(max(len(groups) * 1.2, 6), 5))
        ax = fig.add_subplot(111)
        # show_stats 开启时 n 移入标注块，刻度标签只留类别名（避免重复展示）
        tick_labels = [
            str(g) if show_stats else f"{g}\n(n={len(d)})"
            for g, d in zip(groups, group_data, strict=False)
        ]
        bp = ax.boxplot(
            group_data,
            tick_labels=tick_labels,
            patch_artist=True,
            widths=0.5,
        )
        cmap = cm.tab10
        for pi, patch in enumerate(bp["boxes"]):
            patch.set_facecolor(cmap(pi % 10))
        for i, gdata in enumerate(group_data, 1):
            # 可复现 jitter（种子基于组序号）
            jitter = np.random.default_rng(20260819 + i).uniform(-0.12, 0.12, len(gdata))
            ax.scatter(
                np.full(len(gdata), i) + jitter,
                gdata,
                alpha=0.3,
                s=10,
                color=PALETTE["misc"]["grid"],
                zorder=3,
            )
        ax.set_xlabel(group_col, fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        title = f"分组箱线图 — {req.target_col} by {group_col}"
        if sub_col and not has_sub:
            title += f" (次分类「{sub_col}」水平过多，未分面)"
        ax.set_title(title, fontsize=11)
        _adjust_xlabels(ax, len(groups), fig)
        _draw_ref_lines(ax)
        if show_stats:
            _draw_group_stats_table(ax, groups, group_data, stat_rows, _ref_lines)
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
            "n_groups": len(groups),
            "n_total": n_total,
            "group_col": group_col,
            "sub_col": sub_col,
            "has_sub": has_sub,
            "mode": mode,
            "nested_label": nested_label,
            "groups": [str(g) for g in all_groups],
        },
        messages=_report.messages(),
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
            task="scatter_plot",
            status="error",
            messages=["需要至少 1 个 X 轴数值列"],
        )

    x_col = req.feature_cols[0]
    y_col = req.target_col

    # ── 提取有效数据 ──
    group_col = req.params.get("group_col")
    has_groups = bool(group_col and group_col in req.data.columns)
    # 去重列名：group_col 与 X/Y 相同时避免重复列导致 sub[col] 返回 DataFrame
    # （审查 2026-08-19 #1.2：'DataFrame' has no attribute 'unique' 崩溃）
    cols_needed = list(dict.fromkeys([y_col, x_col] + ([group_col] if has_groups else [])))

    # ── 边界处置（B1）：±Inf 清洗 + 披露（审查 2026-10-09 R2BD-11）──
    # 原实现只 `.dropna()` —— **±Inf 不是 NaN**，会原样进入散点与拟合：
    # 实测 `n_points` 仍为 60（NaN 情形为 57，即"与干净数据逐字相同"），
    # 且 `fit="linear"` 时 `LinearRegression().fit` 抛
    # `ValueError: Input y/X contains infinity` **未捕获逃出引擎**（红线）。
    # `clean_frame` 的清洗列**只取数值列**（y/x）：混入字符串分组列会让
    # `to_numpy(dtype=float)` 抛错 → `_guard` 静默返回原帧（清洗失效）；
    # 分组列的 NaN 仍由随后的 `.dropna()` 按既有的全列缺失语义处理。
    _boundary = BoundaryReport()
    sub, _n_non_finite = clean_frame(
        req.data[cols_needed], list(dict.fromkeys([y_col, x_col])), report=_boundary
    )
    sub = sub.dropna()
    if len(sub) < 3:
        return AnalysisResult(
            task="scatter_plot",
            status="error",
            messages=[f"有效数据不足(至少3个点, 当前{len(sub)}个)"] + _boundary.messages(),
            metadata={"boundary_codes": _boundary.codes()},
        )

    # ── 参数提取 ──
    # 参数校验（P4 步骤③，第二十五/三十轮）：失败时抛 ParamValidationError。
    # `fit` 此前**无白名单校验**（拼错静默变成「不拟合」）；
    # `show_ci` 现由共享的 `BOOL_SWITCH` 校验（合法值 "true"/"false"，
    # `True`/`1` 经别名归一到 "true"）。
    _sp = PARAM_SPECS["scatter_plot"].validate_or_raise(req.params)
    fit_type = _sp.fit
    # 归一简化为直比。原写法是
    #     `show_ci = show_ci.lower() not in ("false", "0", "no", "")`
    # —— 我一度以为它对字符串 `"false"` 会误判为真（"非空字符串恒真"），
    # 但**实测证伪**：`"false".lower() not in (...)` 就是 `False`，旧逻辑是对的。
    # 它现在的唯一问题是**冗余**：`Choice` 已把取值限定为 "true"/"false"，
    # 那串多写法白名单（"0"/"no"/""）再也不会命中。故简化为与
    # `box_chart.show_stats` 一致的直比，行为等价。
    show_ci = _sp.show_ci == "true"

    # ── 分组信息 ──
    if has_groups:
        group_vals = sub[group_col]
        group_names = sorted(group_vals.dropna().unique())
        all_group_names = list(group_names)  # 2026-08-21 #F2：全量分组（metadata 供筛选栏常驻）
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
        all_group_names = []

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
        ax.scatter(
            gx,
            gy,
            s=25,
            color=color,
            alpha=0.65,
            edgecolors="white",
            linewidth=0.3,
            label=label,
            zorder=3,
        )
        all_x_for_fit.extend(gx.tolist())
        all_y_for_fit.extend(gy.tolist())

    x_all = np.array(all_x_for_fit)
    y_all = np.array(all_y_for_fit)

    # ── 拟合线 ──
    r_squared = None
    eq_text = ""
    if fit_type == "linear" and len(x_all) >= 3:
        # 收尾轮（契约 #5）：判据与文案统一走 `_guard` 三级归因
        # （原先手写 `np.unique(y_all).size <= 1`，只报"常量"）
        _degenerate = (
            degenerate_column_reason(pd.Series(y_all), what="目标列") if y_all.size else None
        )
        if _degenerate is not None:
            return AnalysisResult(
                task="scatter_plot",
                status="error",
                messages=[f"{_degenerate}，无法拟合线性趋势（R² 无意义，避免 0/0 假 R²=1）"],
            )
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

        ax.plot(
            x_sorted,
            y_fit,
            "-",
            color=PALETTE["anomaly"]["primary"],
            linewidth=2,
            alpha=0.85,
            zorder=5,
            label=f"OLS (R²={r_squared:.3f})",
        )

        # 置信带
        if show_ci and len(x_all) > 2:
            n = len(x_all)
            x_mean = float(np.mean(x_all))
            ssx = float(np.sum((x_all - x_mean) ** 2))
            # 审查 2026-09-05 B3：绝对阈值 1e-15 误判微尺度 X（ssx~1e-25）→ 相对化，
            # 以 Σx² 量级的 1e-12 倍为常量 X 判据（真常量时 ssx 恒为 0，行为不变）
            if ssx <= 1e-12 * max(float(np.sum(x_all**2)), 1e-300):
                # X 列为常量，拟合线为水平线，置信带退化（无意义）
                pass
            else:
                resid_se = float(np.sqrt(np.sum((y_all - y_pred_all) ** 2) / max(n - 2, 1)))
                t_crit = float(sp_stats.t.ppf(0.975, max(n - 2, 1)))
                se_fit = resid_se * np.sqrt(1 / n + (x_sorted - x_mean) ** 2 / ssx)
                ci_upper = y_fit + t_crit * se_fit
                ci_lower = y_fit - t_crit * se_fit
                ax.fill_between(
                    x_sorted,
                    ci_lower,
                    ci_upper,
                    color=PALETTE["anomaly"]["primary"],
                    alpha=0.08,
                    zorder=1,
                    label="95% 置信带",
                )

        slope_sign = "+" if slope >= 0 else ""
        eq_text = f"y = {intercept:.4f} {slope_sign} {slope:.4f}x"

    elif fit_type == "lowess" and len(x_all) >= 5:
        # LOWESS (局部加权散点平滑)
        try:
            from statsmodels.nonparametric.smoothers_lowess import lowess
        except ImportError:
            logger.info("statsmodels 未安装，LOWESS 拟合不可用。安装: pip install statsmodels")
        else:
            try:
                lowess_result = lowess(y_all, x_all, frac=0.5, return_sorted=True)
                ax.plot(
                    lowess_result[:, 0],
                    lowess_result[:, 1],
                    "-",
                    color=PALETTE["anomaly"]["primary"],
                    linewidth=2,
                    alpha=0.85,
                    zorder=5,
                    label="LOWESS (frac=0.5)",
                )
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
            "n_points": n_points,
            "x_col": x_col,
            "fit_type": fit_type,
            "r_squared": r_squared,
            "groups": [str(g) for g in all_group_names if g != "_default"],
            # 审查 2026-10-09 R2BD-11：±Inf 的处置必须到达机器可读出口
            "boundary_codes": _boundary.codes(),
        },
        messages=_boundary.messages(),
    )
