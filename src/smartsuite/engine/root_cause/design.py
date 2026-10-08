"""试验设计类：功效与样本量分析。"""

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Custom, Finite, Integer, Opt, Spec, Violation
from smartsuite.engine._palette import PALETTE


def _nonzero_effect(raw) -> tuple[float | None, Violation | None]:
    """效应量：先按有限数值校验，再拒绝 0。

    审查 2026-09-24（P4 步骤③）：`effect_size=0` 无意义（无法检测零效应），
    且 `statsmodels` 的 `solve_power` 会抛 `ValueError`。原实现用单独一段
    `if effect_size == 0` 表达；现作为校验器的一部分，归因更准。
    """
    val, bad = Finite().check(raw)
    if bad is not None:
        return None, bad
    if val == 0:
        return None, Violation("不能为 0（无法检测零效应量），请输入非零值", "ZERO_EFFECT")
    return val, None


def _open_unit(raw) -> tuple[float | None, Violation | None]:
    """比例/概率：必须是 **(0,1) 开区间**内的有限数值。

    开区间与既有实现一致（原代码 `if not (0 < p0 < 1 and 0 < p1 < 1)`）。
    迁移时我一度写成闭区间 `[0,1]`，被"与既有行为对拍"的用例抓出：
    比例检验的功效公式在 p 为 0 或 1 时分母退化（`p(1-p)=0`）。
    """
    return Finite(gt=0, lt=1).check(raw)


# ── 声明式参数契约（阶段 P4 步骤③，2026-09-24）──
# 契约：docs/governance/improvement-plan.md §六
#
# 迁移前这里有约 70 行分散的手写校验，含明显冗余：
#   - `alpha` 的区间检查**写了两遍**（`_safe_float` 之后又查一次）；
#   - `_safe_float` / `float()` / `np.isfinite` 三段式对三个参数各来一遍；
#   - `n_groups` 的同一检查**写了三处**（三条模式分支各一份）；
#   - 参数在多个分支里反复重读（`p0`/`p1`/`n_groups` 各 3 次）。
# 现在统一为下方一次声明 + 一次校验。
PARAM_SPEC = Spec(
    mode=Opt(
        # `achieved_power` 是 Web UI 的兼容别名（原实现 `mode in ("achieved",
        # "achieved_power")`）；用 aliases 归一化，两种写法都落到 "achieved"。
        Choice(
            ("required_n", "所需样本量"),
            ("achieved", "已达功效"),
            aliases={"achieved_power": "achieved"},
        ),
        default="required_n",
        label="模式",
        hint="required_n=算所需样本量；achieved=算当前样本量下的已达功效",
    ),
    test_type=Opt(
        Choice(
            ("ttest", "独立/配对样本 t 检验"),
            ("anova", "单因素方差分析 (ANOVA)"),
            ("proportion", "两比例检验"),
        ),
        default="ttest",
        label="检验类型",
        hint="ttest=两组均值；anova=多组；proportion=两比例",
    ),
    effect_size=Opt(
        Custom(_nonzero_effect),
        default=0.5,
        label="效应量",
        hint="Cohen's d 或 η²；可取负值（方向由符号表示），但不得为 0",
    ),
    alpha=Opt(Finite(gt=0, lt=1), default=0.05, label="显著性水平 α", hint="必须在 (0,1) 开区间内"),
    target_power=Opt(
        Finite(gt=0, lt=1),
        default=0.80,
        label="目标功效",
        hint="必须在 (0,1) 开区间内；工程上常用 0.80 或 0.90",
    ),
    current_n=Opt(
        Integer(min=1),
        # 默认 30 对齐 `DEFAULT_PARAMS`（前端面板初值亦然）。迁移时我一度写
        # None，被"Spec 默认值 == DEFAULT_PARAMS"的对拍抓出。
        default=30,
        label="当前样本量",
        hint="mode=achieved 时使用；必须是正整数",
    ),
    n_groups=Opt(
        Integer(min=2),
        default=3,
        label="组数 k",
        hint="test_type=anova 时使用；至少 2 组",
    ),
    p0=Opt(Custom(_open_unit), default=0.5, label="基准比例", hint="proportion 模式；(0,1) 内"),
    p1=Opt(Custom(_open_unit), default=0.6, label="目标比例", hint="proportion 模式；(0,1) 内"),
)


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

    # ── 参数校验（阶段 P4 步骤③：已迁移到声明式 Spec）──
    # 迁移前这里有约 70 行分散校验，含明显冗余：`alpha` 区间检查写两遍、
    # 三个参数各走一遍 `_safe_float`/`float()`/`np.isfinite` 三段式。
    # 现统一为 PARAM_SPEC 一次校验；参数也从"多个分支反复重读"变为一次取用。
    #
    # **抛异常而非 return status="error"**：由 orchestrator 的
    # `except SmartSuiteError → build_error_result()` 统一转结果
    # （见 core/param_spec.py::validate_or_raise 的说明）。Web/CLI 侧看到的
    # 仍是 status="error" + 精确中文文案。
    _p = PARAM_SPEC.validate_or_raise(req.params)
    effect_size = _p.effect_size
    alpha = _p.alpha
    target_power = _p.target_power
    mode = _p.mode
    test_type = _p.test_type
    current_n = _p.current_n
    n_groups = _p.n_groups
    p0 = _p.p0
    p1 = _p.p1

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
            # `n_groups` 已由 PARAM_SPEC 的 `Integer(min=2)` 保证 ≥2 且为整数，
            # 原三处重复的检查（三条模式分支各一份）已删除。
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
            # `p0`/`p1` 的类型与 (0,1) 区间已由 PARAM_SPEC 的 `Custom(_open_unit)`
            # 保证，原先的 try/float 与区间检查（两段共 16 行）已删除。
            #
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
                z_alpha = abs(sp_stats.norm.ppf(alpha / 2))
                powers = [_proportion_power(n, p0, p1, z_alpha) for n in n_range]
            else:
                # `n_groups` 已由 PARAM_SPEC 的 `Integer(min=2)` 保证 ≥2 且为整数
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
            # `n_groups` 已由 PARAM_SPEC 的 `Integer(min=2)` 保证 ≥2 且为整数，
            # 原三处重复的检查（三条模式分支各一份）已删除。
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
