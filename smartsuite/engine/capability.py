"""过程能力分析模块：Cp/Cpk、Sigma 水平、Box-Cox 变换。"""
import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    CPK_EXCELLENT,
    CPK_GOOD,
    CPK_MINIMUM,
)
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)

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
    # P2 fix: Bissell 近似在小样本/小 Cpk 时可能产生负下限，Cpk 物理下限为 0
    return (max(float(ci_lower), 0.0), float(ci_upper))


def _sigma_level(cpk_val):
    """Cpk → Sigma Level (短期) 和 DPMO 估算。

    注意: DPMO 公式使用短期 (unshifted) sigma，假设过程均值不发生偏移。
    实际生产中常考虑 1.5σ 偏移，此时 DPMO 会更高。该公式提供的是
    理论最优条件下的缺陷率估算，用于能力对比而非绝对预测。

    Cpk < 0 时（过程均值在规格限外），钳位为 0 以确保 DPMO ≤ 1,000,000
    和 Sigma Level ≥ 0 的物理合理性。
    """
    # Sigma Level ≈ 3 * Cpk（长期 Z 值）
    # DPMO = 2 * Φ(-3*Cpk) * 1e6（双边正态，无偏移假设）
    # 负 Cpk 钳位 — 避免 DPMO > 1,000,000 (P1 fix)
    cpk_val = max(cpk_val, 0)
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
    if len(data) < 3:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=[f"有效数据不足：过程能力分析至少需要 3 个观测值"
                      f"（当前 {len(data)} 个，无法可靠估计标准差）"],
        )

    usl = req.params.get("usl")
    lsl = req.params.get("lsl")
    target = req.params.get("target")  # Cpm 目标值
    transform = req.params.get("transform")  # None | "boxcox"

    # 统一转换为 float（Web UI 端发送数字，CLI/直接调用可能为字符串）
    if usl is not None:
        try:
            usl = float(usl)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="process_capability", status="error",
                messages=[f"规格上限 USL 值无效: {usl}，请输入数值"],
            )
    if lsl is not None:
        try:
            lsl = float(lsl)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="process_capability", status="error",
                messages=[f"规格下限 LSL 值无效: {lsl}，请输入数值"],
            )
    if target is not None:
        try:
            target = float(target)
        except (ValueError, TypeError):
            target = None  # 目标值无效时静默忽略

    # ── 规格限有效性校验 (P2 fix: 防止 USL ≤ LSL 导致负 Cp) ──
    if usl is not None and lsl is not None and usl <= lsl:
        return AnalysisResult(
            task="process_capability", status="error",
            messages=[f"规格限无效: USL ({usl}) ≤ LSL ({lsl})，"
                      f"请确保 USL > LSL。"],
        )
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
                    "⚠ Box-Cox 变换要求规格限均为正值，规格限无法变换，"
                    "已跳过过程能力指数计算，请使用原始数据分析"
                )
                usl, lsl, target = None, None, None  # 阻止混合尺度计算
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
    cp = float((usl - lsl) / (6 * within_sigma)) if has_both and np.isfinite(within_sigma) and within_sigma > 0 else None
    if has_upper and has_lower:
        cpk_val = float(min((usl - mu) / (3 * within_sigma),
                            (mu - lsl) / (3 * within_sigma))) if np.isfinite(within_sigma) and within_sigma > 0 else None
    elif has_upper:
        cpk_val = float((usl - mu) / (3 * within_sigma)) if np.isfinite(within_sigma) and within_sigma > 0 else None
    elif has_lower:
        cpk_val = float((mu - lsl) / (3 * within_sigma)) if np.isfinite(within_sigma) and within_sigma > 0 else None
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
        if cpk_val >= CPK_EXCELLENT:
            judge = f"优秀 (≥{CPK_EXCELLENT})"
        elif cpk_val >= CPK_GOOD:
            judge = f"合格 (≥{CPK_GOOD})"
        elif cpk_val >= CPK_MINIMUM:
            judge = f"勉强 (≥{CPK_MINIMUM}，需改进)"
        else:
            judge = f"不合格 (<{CPK_MINIMUM})"
    else:
        judge = "未提供规格限"

    # ── 能力汇总表 ──
    capability_rows = [
        {"指标": "Cp (短期能力)", "值": f"{cp:.3f}" if cp is not None else "N/A",
         "95%CI下限": f"{cp_ci[0]:.3f}" if cp_ci[0] is not None else "N/A",
         "95%CI上限": f"{cp_ci[1]:.3f}" if cp_ci[1] is not None else "N/A"},
        {"指标": "Cpk (短期+偏倚)", "值": f"{cpk_val:.3f}" if cpk_val is not None else "N/A",
         "95%CI下限": f"{cpk_ci[0]:.3f}" if cpk_ci[0] is not None else "N/A",
         "95%CI上限": f"{cpk_ci[1]:.3f}" if cpk_ci[1] is not None else "N/A"},
        {"指标": "Pp (长期能力)", "值": f"{pp:.3f}" if pp is not None else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Ppk (长期+偏倚)", "值": f"{ppk_val:.3f}" if ppk_val is not None else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Cpm (田口能力)", "值": f"{cpm:.3f}" if cpm is not None else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "Sigma Level (无偏移理论值)", "值": f"{sigma_lvl:.2f}" if sigma_lvl is not None else "N/A",
         "95%CI下限": "N/A", "95%CI上限": "N/A"},
        {"指标": "DPMO (无偏移假设)", "值": f"{dpmo:,}" if dpmo is not None else "N/A",
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
            str(usl) if usl is not None else "未指定", str(lsl) if lsl is not None else "未指定",
            str(target) if target is not None else "未指定",
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
        ax.axvline(lsl, color=PALETTE["anomaly"]["primary"], linestyle="-", linewidth=2,
                   label=f"LSL={lsl}")
    if usl is not None:
        ax.axvline(usl, color=PALETTE["anomaly"]["primary"], linestyle="-", linewidth=2,
                   label=f"USL={usl}")
    if target is not None:
        ax.axvline(target, color=PALETTE["direction"]["zero"], linestyle=":", linewidth=1.5,
                   label=f"目标={target}")

    # 规格限区域着色
    if lsl is not None and usl is not None:
        ax.axvspan(lsl, usl, alpha=0.08, color=PALETTE["center"]["primary"], label="规格范围")

    # 构建标题：主标题显示判定结论，副标题显示关键指数
    ax.set_title(f"过程能力分析 — {req.target_col}", fontsize=11, fontweight="bold")
    sub_parts = []
    if boxcox_lambda is not None:
        sub_parts.append(f"Box-Cox λ={boxcox_lambda:.3f}")
    if cpk_val is not None:
        sub_parts.append(f"Cpk={cpk_val:.3f}")
    if ppk_val is not None:
        sub_parts.append(f"Ppk={ppk_val:.3f}")
    sub_parts.append(judge)
    ax.set_xlabel(f"{req.target_col}  |  {'  |  '.join(sub_parts)}", fontsize=9)
    ax.set_ylabel("密度", fontsize=10)
    ax.legend(fontsize=8, loc="upper right", ncol=2)
    fig.tight_layout()

    # ── 汇总 ──
    summary_parts = []
    if boxcox_lambda is not None:
        summary_parts.append(f"Box-Cox λ={boxcox_lambda:.3f}")
    if cpk_val is not None:
        cpk_ci_str = f"[{cpk_ci[0]:.3f}, {cpk_ci[1]:.3f}]" if cpk_ci[0] is not None else "N/A"
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
