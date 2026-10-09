"""非参数 SPC（spc_nonparametric）。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Opt, Spec
from smartsuite.engine._guard import BoundaryReport, check_magnitude, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import disp, round_for_display

logger = logging.getLogger(__name__)

# ── 声明式参数契约（P4 步骤③，第二十三轮）──
# 契约：docs/governance/improvement-plan.md §六
# 枚举**逐任务**声明（不进共享库）。注意值集是 two-sided/upper/lower，
# **不是** two-sided/one-sided —— 共享库的判据表记录了这处踩坑。
PARAM_SPECS = {
    "spc_nonparametric": Spec(
        side=Opt(
            Choice(
                ("two-sided", "双侧"),
                ("upper", "单侧上限（越小越好）"),
                ("lower", "单侧下限（越大越好）"),
            ),
            default="two-sided",
            label="控制限方向",
            hint="双侧=同时关注上下偏移；单侧用于只关心一个方向的特性",
        )
    ),
}


def spc_nonparametric(req: AnalysisRequest) -> AnalysisResult:
    """非参数控制图 — 基于最佳拟合分布的 CDF 逆推控制限，不假设正态。

    方法与标准 SPC (±3σ) 不同：
    1. 自动拟合 Normal / Lognormal / Weibull 三种分布，选 KS 检验最优者
    2. 用拟合分布的 CDF 逆函数 (PPF) 精确计算控制限
    3. 适用于偏态/非对称数据，且不受样本量限制

    参数:
        side: "two-sided"(默认) | "upper"(越小越好,只设上限) | "lower"(越大越好,只设下限)
    """
    # 审查 2026-08-19 #1.5：dropna 不过滤 ±Inf，norm.fit 对 Inf 直接抛异常
    # 审查 2026-10-09 P1-6：原实现是手写 `replace([np.inf,-np.inf], np.nan).dropna()`
    # —— 绕过 `_guard` 且**无任何披露**（用户看到 n 变小却不知为何）。
    # 第三十六轮/本轮的收口要求：输入清洗只有 `_guard` 一个执行点。
    _boundary = BoundaryReport()
    data, _n_non_finite = clean_series(
        req.data[req.target_col], column=req.target_col, report=_boundary
    )
    n = len(data)

    if n < 10:
        return AnalysisResult(
            task="spc_nonparametric",
            status="error",
            messages=[f"有效数据不足(至少10个点, 当前{n}个)"] + _boundary.messages(),
        )

    # 量级上界（审查 2026-10-09 P1-4）：×1e300 时 `Σy²` 溢出为 Inf，
    # 拟合分布的控制限随之变成天文数字，summary 反而写「过程稳定 ✓」——
    # 判决与量纲不符，必须 B0 拒绝而不是给结论。
    _mag = check_magnitude(data, what=f"目标列「{req.target_col}」", report=_boundary)
    if _mag is not None:
        return AnalysisResult(
            task="spc_nonparametric",
            status="error",
            messages=_boundary.messages(),
            metadata={"boundary_codes": _boundary.codes()},
        )

    # 参数校验（P4 步骤③，第二十三轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 原 Round-2 #A2p 的"未知 side 静默按双侧执行"守卫（白名单检查）已由
    # `Choice` 前置表达并**给出可选值的中文文案**，故此处不再重复 ——
    # 死代码会让后来者以为"还要在这里改值集"。
    side = PARAM_SPECS["spc_nonparametric"].validate_or_raise(req.params).side
    values = data.values

    # 审查 2026-08-19 #2.5：常量列 → 所有 KS p 为 nan → 假"过程稳定 ✓ CL=nan"
    # 审查 2026-09-05 B1：绝对阈值误判微尺度数据 → 相对阈值（同 xbar_r_chart #A2l）
    # 审查 2026-09-16 B-4：去掉 `_scale=1.0` 兜底（pico 级真实波动不再误报常量）
    _abs_scale = float(np.max(np.abs(values)))
    if _abs_scale == 0 or float(np.std(values, ddof=1)) <= 1e-12 * _abs_scale:
        return AnalysisResult(
            task="spc_nonparametric",
            status="error",
            messages=["目标列为常量列（方差为 0），无法进行分布拟合与控制限计算"],
        )

    # 审查 2026-09-21 A-1：与 `root_cause/distribution.py` 的分布拟合段重复，未合并原因
    # 见该处注释（产出结构不同：此处保留 dist/args 供算控制限）。
    # 已知不对称：此处 lognorm/Weibull 均有 try/except 降级，彼处 lognorm 无。**两处请同步改**。
    # ── 1. 分布拟合 (Normal / Lognormal / Weibull) ──
    fits = {}
    # Normal
    mu, sigma = sp_stats.norm.fit(values)
    ks_n = sp_stats.kstest(values, sp_stats.norm(loc=mu, scale=sigma).cdf)
    fits["Normal"] = {"dist": sp_stats.norm, "args": (mu, sigma), "ks_p": ks_n.pvalue}

    # Lognormal（审查 2026-08-19 #2.8：lognorm.fit 与 Weibull 对称加保护）
    if (values > 0).all():
        try:
            shape_ln, loc_ln, scale_ln = sp_stats.lognorm.fit(values, floc=0)
            ks_ln = sp_stats.kstest(values, sp_stats.lognorm(shape_ln, loc=0, scale=scale_ln).cdf)
            fits["Lognormal"] = {
                "dist": sp_stats.lognorm,
                "args": (shape_ln, 0, scale_ln),
                "ks_p": ks_ln.pvalue,
            }
        except Exception:
            logger.debug("Lognormal fit failed in spc_nonparametric", exc_info=True)

    # Weibull
    if (values > 0).all():
        try:
            shape_w, loc_w, scale_w = sp_stats.weibull_min.fit(values, floc=0)
            ks_w = sp_stats.kstest(values, sp_stats.weibull_min(shape_w, loc=0, scale=scale_w).cdf)
            fits["Weibull"] = {
                "dist": sp_stats.weibull_min,
                "args": (shape_w, 0, scale_w),
                "ks_p": ks_w.pvalue,
            }
        except Exception:
            logger.debug("Weibull fit failed in spc_nonparametric", exc_info=True)

    # 选 KS p 值最大的（拟合最优）
    best_name = max(fits, key=lambda k: fits[k]["ks_p"])
    best = fits[best_name]
    dist = best["dist"]
    args = best["args"]

    # ── 2. 用拟合分布 PPF (CDF 逆函数) 计算控制限 ──
    cl = float(dist.median(*args))

    # 契约 #16（审查 2026-10-09）：PPF 失败 → 回退经验分位数属 **B2 降级**，
    # 必须用户可见。原实现只写 `logger.debug`，而图表标题仍写「拟合=Weibull」——
    # 用户以为看到的是**理论分布**控制限，实际是经验分位数（两者在尾部差异最大，
    # 而尾部正是控制限所在）。契约硬性要求 1 明文禁止"只在 debug 日志里说明的降级"。
    _ppf_fallbacks: list[str] = []

    def _ppf(p):
        """安全 PPF，防止极端值溢出；失败时回退经验分位数并**登记降级**。"""
        try:
            return float(dist.ppf(p, *args))
        except Exception as e:
            if not _ppf_fallbacks:
                _ppf_fallbacks.append(
                    f"⚠ 拟合分布 PPF 在尾部不可用（{type(e).__name__}: {e}），"
                    "已回退为**经验分位数**——控制限不再是理论分布限（尾部差异最大），"
                    "请结合直方图/样本量判断其稳定性"
                )
            logger.warning(
                "PPF 计算失败，回退经验分位数（B2 降级，已向用户披露）: %s", e, exc_info=True
            )
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
        violations = sorted(set(list(np.where(values > ucl)[0]) + list(np.where(values < lcl)[0])))
        side_note = f"双侧控制限 (拟合={best_name})"

    # 控制限与"距中位数"都带**数据量纲** → 共享展示格式化器 `disp`
    # （审查 2026-10-09 C-1：×1e-9 时本段写成 `UCL=0.0000 / LCL=0.0000`，
    # 而同一结果的 `control_limits` 表是 `1.004000e-08` —— 两套口径自相矛盾）
    limit_parts = []
    if ucl is not None:
        limit_parts.append(f"UCL={disp(ucl)}")
    if lcl is not None:
        limit_parts.append(f"LCL={disp(lcl)}")
    limit_label = " / ".join(limit_parts) if limit_parts else "N/A"

    # 偏度评估（偏度无量纲 → 保留 `:.2f`；两个"距中位数"带量纲 → `disp`）
    skew_val = float(data.skew())
    if abs(skew_val) > 0.5:
        asym_parts = [f"数据偏度={skew_val:.2f}({'右偏' if skew_val > 0 else '左偏'})"]
        if ucl is not None:
            asym_parts.append(f"上限距中位数={disp(ucl - cl, 3)}")
        if lcl is not None:
            asym_parts.append(f"下限距中位数={disp(cl - lcl, 3)}")
        asym_note = "，".join(asym_parts)
    else:
        asym_note = f"数据近似对称(偏度={skew_val:.2f})"

    # ── 图表 ──
    fig = Figure(figsize=(12, 7))
    pos = np.arange(n)
    ax = fig.add_subplot(111)

    # 大样本时去掉点标记并减细线宽，避免"毛刷"噪声淹没控制限与违规点
    if n > 300:
        ax.plot(
            pos,
            values,
            "-",
            color=PALETTE["data"]["primary"],
            linewidth=0.7,
            alpha=0.6,
            label="数据",
        )
    else:
        ax.plot(
            pos,
            values,
            "o-",
            markersize=3,
            color=PALETTE["data"]["primary"],
            linewidth=1,
            alpha=0.6,
            label="数据",
        )
    ax.axhline(
        cl,
        color=PALETTE["control"]["primary"],
        linestyle="--",
        linewidth=2,
        label=f"CL (中位数)={disp(cl)}",
    )

    if ucl is not None:
        ax.axhline(
            ucl,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.5,
            label=f"UCL (P99.865)={disp(ucl)}",
        )
        if ucl_2s is not None:
            ax.axhline(
                ucl_2s,
                color=PALETTE["spec"]["secondary"],
                linestyle=":",
                linewidth=0.8,
                alpha=0.6,
                label="±2σ 警戒线",
            )
        if ucl_1s is not None:
            ax.axhline(
                ucl_1s,
                color=PALETTE["spec"]["tertiary"],
                linestyle=":",
                linewidth=0.5,
                alpha=0.4,
                label="±1σ 参考线",
            )
        ax.fill_between(pos, cl, ucl, alpha=0.04, color=PALETTE["center"]["primary"])

    if lcl is not None:
        ax.axhline(
            lcl,
            color=PALETTE["control"]["primary"],
            linestyle="--",
            linewidth=1.5,
            label=f"LCL (P0.135)={disp(lcl)}",
        )
        if lcl_2s is not None:
            ax.axhline(
                lcl_2s, color=PALETTE["spec"]["secondary"], linestyle=":", linewidth=0.8, alpha=0.6
            )
        if lcl_1s is not None:
            ax.axhline(
                lcl_1s, color=PALETTE["spec"]["tertiary"], linestyle=":", linewidth=0.5, alpha=0.4
            )
        ax.fill_between(pos, lcl, cl, alpha=0.04, color=PALETTE["center"]["primary"])

    if violations:
        ax.scatter(
            violations,
            values[violations],
            s=80,
            color=PALETTE["anomaly"]["primary"],
            marker="x",
            linewidths=2.5,
            zorder=5,
            label=f"违规 ({len(violations)}个)",
        )

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    # 契约 #16：回退发生时**图表标题也必须标注**（用户看的是图，不看 messages）
    _title_mark = "  ⚠ 控制限=经验分位数（PPF 不可用）" if _ppf_fallbacks else ""
    ax.set_title(
        f"非参数控制图 — {req.target_col} ({side_note}){_title_mark}\n"
        f"CL={disp(cl)} | {limit_label}",
        fontsize=10,
    )
    ax.legend(fontsize=7.5, loc="upper right", ncol=2)
    fig.tight_layout()

    # ── 汇总 ──
    n_violations = len(violations)
    is_stable = n_violations == 0
    ucl_str = disp(ucl) if ucl is not None else "N/A"
    lcl_str = disp(lcl) if lcl is not None else "N/A"
    summary = (
        f"非参数控制图({side_note}): {'过程稳定 ✓' if is_stable else f'{n_violations} 个点违规'}。"
        f"CL(P50)={disp(cl)}, UCL={ucl_str}, LCL={lcl_str}。{asym_note}。"
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
            "control_limits": pd.DataFrame(
                {
                    "统计量": [k for k, _ in present_pairs],
                    "值": round_for_display([v for _, v in present_pairs]),
                }
            ),
            "violations": pd.DataFrame(
                {
                    "序号": violations,
                    "值": round_for_display(values[violations]),
                }
            )
            if violations
            else pd.DataFrame({"状态": ["未检测到违规"]}),
        },
        figures=[fig],
        summary=summary,
        messages=_boundary.messages() + _ppf_fallbacks,
        metadata={
            # 契约 #16：机器可读的回退标记（上游不必做中文字串匹配）
            "ppf_fallback": bool(_ppf_fallbacks),
            "cl": cl,
            "ucl": ucl,
            "lcl": lcl,
            "side": side,
            "ucl_2s": ucl_2s,
            "lcl_2s": lcl_2s,
            "n": n,
            "n_violations": n_violations,
            "is_stable": is_stable,
            "boundary_codes": _boundary.codes(),
        },
    )
