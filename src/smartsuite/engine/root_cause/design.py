"""试验设计类：功效与样本量分析。"""

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine.root_cause._shared import _safe_int


def _proportion_power(n: int, p0: float, p1: float, z_alpha: float) -> float:
    """双比例 z 检验的统计功效（每组 n 样本，双侧近似）。

    审查 2026-08-19 #2.10：power_analysis 的 proportion 模式此前误用
    FTestAnovaPower 画 ANOVA 功效曲线；此处为比例检验自身的功效公式。
    """
    se = np.sqrt((p0 * (1 - p0) + p1 * (1 - p1)) / max(n, 1))
    d = abs(p1 - p0)
    if se <= 0:
        return 0.0
    return float(sp_stats.norm.cdf(d / se - z_alpha))


def power_analysis(req: AnalysisRequest) -> AnalysisResult:
    """统计功效分析 — 估计所需样本量或已达功效。

    参数 (通过 params):
        effect_size: 预期效应量 (Cohen's d 或 η²)
        alpha: 显著性水平 (默认 0.05)
        target_power: 目标功效 (默认 0.80)
        mode: "required_n" (计算所需样本量) 或 "achieved" (计算已达功效)
        current_n: 当前样本量 (mode="achieved" 时必需)
        test_type: "ttest" (默认) | "anova" | "proportion"
        n_groups: ANOVA 分组数 (test_type="anova" 时使用)
    """
    from math import ceil

    effect_size = req.params.get("effect_size", 0.5)
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=[f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}"],
        )
    target_power = req.params.get("target_power", 0.80)
    mode = req.params.get("mode", "required_n")  # "required_n" | "achieved"
    test_type = req.params.get("test_type", "ttest")
    current_n = req.params.get("current_n")

    # 参数 float() 防护 (CLI/YAML 传入字符串时安全转换)
    for name, val, _default in [
        ("effect_size", effect_size, 0.5),
        ("alpha", alpha, 0.05),
        ("target_power", target_power, 0.80),
    ]:
        try:
            _ = float(val)
        except (ValueError, TypeError):
            return AnalysisResult(
                task="power_analysis",
                status="error",
                messages=[f"参数 {name} 值无效: {val}，请输入数值"],
            )
    effect_size = float(effect_size)
    alpha = float(alpha)
    target_power = float(target_power)
    # Round-2 #A2f：NaN/Inf 与区间校验（此前 "nan" 穿透 float() 顶层校验）
    if not all(np.isfinite(x) for x in (effect_size, alpha, target_power)):
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=["effect_size/alpha/target_power 必须为有限数值"],
        )
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=[f"alpha 必须在 (0, 1) 区间内，当前: {alpha!r}"],
        )
    if not 0 < target_power < 1:
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=[f"target_power 必须在 (0, 1) 区间内，当前: {target_power!r}"],
        )
    # 审查 2026-08-19 #1.4：effect_size=0 时 statsmodels solve_power 抛 ValueError
    if effect_size == 0:
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=["effect_size 不能为 0（无法检测零效应量），请输入非零值"],
        )
    if current_n is not None:
        try:
            current_n = int(current_n)
        except (ValueError, TypeError, OverflowError):
            # OverflowError（审查 2026-09-22 发现 5 同族）：int(float('inf')) 穿透守卫
            return AnalysisResult(
                task="power_analysis",
                status="error",
                messages=[f"参数 current_n 值无效: {current_n}，请输入整数"],
            )

    if mode == "required_n":
        # 计算所需样本量
        if test_type == "ttest":
            from statsmodels.stats.power import TTestIndPower

            analysis = TTestIndPower()
            required = ceil(
                analysis.solve_power(
                    effect_size=abs(effect_size),
                    alpha=alpha,
                    power=target_power,
                    alternative="two-sided",
                )
            )
            label = f"独立样本 t 检验所需每组样本量: {required} (总计 {required * 2})"
        elif test_type == "anova":
            n_groups = _safe_int(req.params.get("n_groups", 3))
            if n_groups is None or n_groups < 2:
                return AnalysisResult(
                    task="power_analysis",
                    status="error",
                    messages=["n_groups 必须为 ≥2 的整数"],
                )
            from statsmodels.stats.power import FTestAnovaPower

            analysis = FTestAnovaPower()
            total_n = ceil(
                float(
                    analysis.solve_power(
                        effect_size=abs(effect_size),
                        alpha=alpha,
                        power=target_power,
                        k_groups=n_groups,
                    )
                )
            )
            required = ceil(total_n / n_groups)
            label = f"ANOVA ({n_groups}组) 所需每组样本量: {required} (总计 {required * n_groups})"
        elif test_type == "proportion":
            # 审查 2026-08-19 #1.4：p0/p1 需 float 防护（CLI/YAML 字符串 → TypeError）
            try:
                p0 = float(req.params.get("p0", 0.5))
                p1 = float(req.params.get("p1", 0.6))
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="power_analysis",
                    status="error",
                    messages=["参数 p0/p1 值无效，请输入 (0,1) 区间内的数值"],
                )
            if not (0 < p0 < 1 and 0 < p1 < 1):
                return AnalysisResult(
                    task="power_analysis",
                    status="error",
                    messages=[f"p0/p1 必须在 (0, 1) 区间内，当前: p0={p0}, p1={p1}"],
                )
            # 审查 2026-09-19 C-1：守卫已拒绝 d<1e-9（d>0 恒成立），分母必须用精确 d²。
            # 旧 `d**2 + EPSILON`（1e-10）在 1e-9<d<1e-4 时静默低估样本量（陷阱 9 同族）。
            if abs(p1 - p0) < 1e-9:
                return AnalysisResult(
                    task="power_analysis",
                    status="error",
                    messages=["p0 与 p1 不能相等（无法检测零比例差），请调整假设比例"],
                )
            z_alpha = abs(sp_stats.norm.ppf(alpha / 2))
            z_beta = abs(sp_stats.norm.ppf(1 - target_power))
            d = abs(p1 - p0)
            # 双比例检验: 总方差 = p0*(1-p0) + p1*(1-p1)
            required = ceil((z_alpha + z_beta) ** 2 * (p0 * (1 - p0) + p1 * (1 - p1)) / d**2)
            label = f"比例检验所需样本量: {required} (p0={p0}, p1={p1}, d={d:.3g})"
        else:
            return AnalysisResult(
                task="power_analysis",
                status="error",
                messages=[f"不支持的检验类型: {test_type}"],
            )

        power_df = pd.DataFrame(
            {
                "参数": ["效应量", "显著性水平(α)", "目标功效", "检验类型", "所需每组样本量"],
                "值": [str(effect_size), str(alpha), str(target_power), test_type, str(required)],
            }
        )

        # 功效曲线图
        n_range = np.arange(max(2, required // 2), required * 3 + 1, max(1, required // 20))
        if test_type == "ttest":
            powers = [
                TTestIndPower().power(effect_size=abs(effect_size), nobs1=n, alpha=alpha)
                for n in n_range
            ]
        else:
            # 审查 2026-08-19 #2.10：proportion 模式此前误用 ANOVA 功效曲线
            if test_type == "proportion":
                p0 = float(req.params.get("p0", 0.5))
                p1 = float(req.params.get("p1", 0.6))
                z_alpha = abs(sp_stats.norm.ppf(alpha / 2))
                powers = [_proportion_power(n, p0, p1, z_alpha) for n in n_range]
            else:
                n_groups = _safe_int(req.params.get("n_groups", 3))
                if n_groups is None or n_groups < 2:
                    return AnalysisResult(
                        task="power_analysis",
                        status="error",
                        messages=["n_groups 必须为 ≥2 的整数"],
                    )
                powers = [
                    FTestAnovaPower().power(
                        effect_size=abs(effect_size),
                        nobs=n * n_groups,
                        k_groups=n_groups,
                        alpha=alpha,
                    )
                    for n in n_range
                ]

        fig = Figure(figsize=(7, 4))
        ax = fig.add_subplot(111)
        ax.plot(n_range, powers, "-", color=PALETTE["data"]["primary"], linewidth=2)
        ax.axhline(
            target_power,
            color=PALETTE["target"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"目标功效={target_power}",
        )
        ax.axvline(
            required,
            color=PALETTE["center"]["primary"],
            linestyle="--",
            linewidth=1.2,
            label=f"所需N={required}",
        )
        ax.set_xlabel("每组样本量", fontsize=10)
        ax.set_ylabel("统计功效", fontsize=10)
        ax.set_title(f"功效曲线 — {test_type} (效应量={effect_size}, α={alpha})", fontsize=11)
        ax.legend(fontsize=8)
        ax.set_ylim(0, 1.05)
        fig.tight_layout()

        return AnalysisResult(
            task="power_analysis",
            tables={"power_result": power_df},
            figures=[fig],
            summary=label,
            metadata={
                "required_n": required,
                "effect_size": effect_size,
                "alpha": alpha,
                "target_power": target_power,
                "test_type": test_type,
                "mode": "required_n",
            },
        )

    elif mode in ("achieved", "achieved_power"):
        # 计算已达功效（"achieved_power" 为 Web UI 兼容别名）
        if current_n is None:
            return AnalysisResult(
                task="power_analysis",
                status="error",
                messages=["mode='achieved' 需要提供 current_n 参数"],
            )

        if test_type == "ttest":
            from statsmodels.stats.power import TTestIndPower

            power = float(
                TTestIndPower().power(effect_size=abs(effect_size), nobs1=current_n, alpha=alpha)
            )
        elif test_type == "anova":
            n_groups = _safe_int(req.params.get("n_groups", 3))
            if n_groups is None or n_groups < 2:
                return AnalysisResult(
                    task="power_analysis",
                    status="error",
                    messages=["n_groups 必须为 ≥2 的整数"],
                )
            from statsmodels.stats.power import FTestAnovaPower

            power = float(
                FTestAnovaPower().power(
                    effect_size=abs(effect_size),
                    nobs=current_n * n_groups,
                    k_groups=n_groups,
                    alpha=alpha,
                )
            )
        else:
            return AnalysisResult(
                task="power_analysis",
                status="error",
                messages=[f"不支持的检验类型: {test_type}"],
            )

        judge = (
            "充足 (≥0.80)"
            if power >= 0.80
            else ("一般 (0.50-0.80)" if power >= 0.50 else "不足 (<0.50)")
        )
        summary = f"当前功效={power:.1%} ({judge})，效应量={effect_size}, 每组N={current_n}"

        return AnalysisResult(
            task="power_analysis",
            tables={
                "power_result": pd.DataFrame(
                    {
                        "参数": [
                            "效应量",
                            "显著性水平(α)",
                            "每组样本量",
                            "检验类型",
                            "已达功效",
                            "判定",
                        ],
                        "值": [
                            str(effect_size),
                            str(alpha),
                            str(current_n),
                            test_type,
                            f"{power:.3f}",
                            judge,
                        ],
                    }
                ),
            },
            summary=summary,
            metadata={
                "achieved_power": power,
                "effect_size": effect_size,
                "alpha": alpha,
                "current_n": current_n,
                "test_type": test_type,
                "mode": "achieved",
            },
        )

    else:
        return AnalysisResult(
            task="power_analysis",
            status="error",
            messages=[f"未知模式: {mode}，支持 'required_n' 和 'achieved'"],
        )
