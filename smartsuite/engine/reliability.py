"""可靠性与测量系统分析模块：Gage R&R、容差区间、生存分析。"""
import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import EPSILON
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)

def gage_rr(req: AnalysisRequest) -> AnalysisResult:
    """测量系统分析 (Gage R&R) — 评估量具的重复性和再现性。

    数据要求: target_col=测量值, feature_cols 中需含 "部件" 和 "操作员" 列。

    参数:
        part_col: 部件列名 (默认 feature_cols[0])
        operator_col: 操作员列名 (默认 feature_cols[1])
        tolerance: 公差范围 (用于 %P/T 计算，可选)
        sigma_multiplier: 研究变异乘数 (默认 5.15 = 99% 研究变异)
    """
    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P2 fix)
    part_col = req.params.get("part_col")
    if part_col is None:
        part_col = req.feature_cols[0] if len(req.feature_cols) > 0 else None
    operator_col = req.params.get("operator_col")
    if operator_col is None:
        operator_col = req.feature_cols[1] if len(req.feature_cols) > 1 else None
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

    try:
        sigma_mult = float(req.params.get("sigma_multiplier", 5.15))
    except (ValueError, TypeError):
        return AnalysisResult(
            task="gage_rr", status="error",
            messages=[f"参数 sigma_multiplier 值无效: "
                      f"{req.params.get('sigma_multiplier')}，请输入数值"],
        )

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
    if tv < EPSILON:
        return AnalysisResult(
            task="gage_rr", status="error",
            messages=["所有测量值完全一致（零变异），无法评估测量系统。"
                      "请检查数据：可能量具精度不足、数据录入错误或过程变异为零。"],
        )
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
    if sigma < EPSILON:
        return AnalysisResult(
            task="tolerance_interval", status="error",
            messages=["数据标准差为零，无法计算容许区间"],
        )

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
    if len(sub) == 0:
        return AnalysisResult(task="survival_analysis", status="error",
            messages=["有效数据为空：时间列与事件列无共同有效值，请检查数据完整性。"])
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

    # 零事件防护
    n_events_total = int(events.sum())
    if n_events_total == 0:
        return AnalysisResult(
            task="survival_analysis", status="error",
            messages=["所有观测均为删失数据（无失效事件），无法估计生存函数。"
                      "请检查事件列是否正确标记了失效事件 (1=失效)。"],
        )

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
    warn_msgs: list[str] = []
    if len(fail_times) >= 5:
        try:
            shape, loc, scale = sp_stats.weibull_min.fit(fail_times, floc=0)
            weibull_shape = float(shape)
            weibull_scale = float(scale)
        except Exception:
            logger.debug("Weibull fit failed in survival_analysis", exc_info=True)
    n_censored = int((events == 0).sum())
    if n_censored > 0 and weibull_shape is not None:
        warn_msgs.append(
            f"⚠ Weibull 参数基于 {len(fail_times)} 个失效数据拟合，"
            f"忽略了 {n_censored} 个删失观测，形状参数 β 可能被低估。"
            f"建议使用支持删失数据的专业可靠性软件（如 Minitab、JMP、R/survival）进行精确分析。"
        )

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
                    v1 += total_o * (total_r - total_o) * r1_t * r2_t / (total_r**2 * (total_r - 1) + EPSILON)
            z_lr = (O1_sum - E1_sum) / np.sqrt(v1 + EPSILON)
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
    ax.legend(fontsize=8, ncol=2)
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
        messages=warn_msgs,
        metadata={
            "median_survival": median_survival,
            "n_total": n_total, "n_events": int(events.sum()),
            "n_censored": int((events == 0).sum()),
            "weibull_shape": weibull_shape,
            "weibull_scale": weibull_scale,
            "logrank_p": logrank_result["p值"] if logrank_result else None,
        },
    )
