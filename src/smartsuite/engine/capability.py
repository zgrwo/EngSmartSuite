"""过程能力分析模块：Cp/Cpk、Sigma 水平、Box-Cox 变换。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, CrossRule, Finite, Integer, Opt, Spec
from smartsuite.engine._constants import (
    CPK_EXCELLENT,
    CPK_GOOD,
    CPK_MINIMUM,
)
from smartsuite.engine._guard import BoundaryIssue, BoundaryReport, check_non_constant, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import shapiro_p

logger = logging.getLogger(__name__)

# ── 声明式参数契约（阶段 P4 步骤②，2026-09-24）──
# 契约：docs/governance/improvement-plan.md §六
#
# 本常量是 `process_capability` 参数的**唯一声明处**：校验、默认值、
# 中文标签/提示均由此派生（将来前端 `TASK_PARAMS`/`PARAM_META` 与
# api-reference 的参数段也从这里生成）。
#
# ⚠️ 范围界定：`Spec` 只承载**与数据无关**的参数校验。
# 依赖数据的检查（样本量 ≥3、非恒定列、子组结构）**留在引擎**，
# 因为那属 `_guard.py` 的 B0–B3 职责（boundary-contract）。
PARAM_SPEC = Spec(
    usl=Opt(
        Finite(),
        label="规格上限 (USL)",
        hint="客户/设计要求的上限；与 LSL 同时给出时用于计算 Cp",
    ),
    lsl=Opt(Finite(), label="规格下限 (LSL)", hint="通常为 0 或设计下限"),
    target=Opt(Finite(), label="Cpm 目标值", hint="给出后额外计算 Taguchi 能力指数 Cpm"),
    # 审查 2026-10-09 P2-8：原先只有 `Choice("boxcox")` 一个选项，而
    # `params.js::buildParamInput` 把 Choice 渲染成**无空选项**的 `<select>` ——
    # 一旦把 `transform` 补进面板（default_params），默认 None 匹配不上任何
    # `selected`，浏览器自动选第一个 → 回读 `{"transform":"boxcox"}`，
    # **Web 用户被强制开启 Box-Cox 且关不掉**。故必须显式提供「不做变换」选项，
    # 默认值取该空值（与引擎 `if transform == "boxcox"` 的判定一致）。
    transform=Opt(
        Choice(("", "不做变换"), ("boxcox", "Box-Cox 正态化")),
        default="",
        label="正态化变换",
        hint="仅对全为正值的数据可用；规格限会同步变换",
    ),
    subgroup_col=Opt(
        label="子组列",
        hint="按该列分组池化求组内 σ，不受数据行序影响（推荐）；与「子组大小」二选一",
    ),
    subgroup_size=Opt(
        Integer(min=2),
        label="子组大小",
        hint="按行序切连续等长子组；与「子组列」二选一",
    ),
).cross(
    CrossRule(
        field_name="lsl",
        check=lambda p: p["usl"] is None or p["lsl"] is None or p["usl"] > p["lsl"],
        code="E_SPEC_INVERTED",
        message="规格限无效: USL 必须大于 LSL，请检查规格上下限。",
    )
)

# ── 移动极差法组内 σ 的有效自由度系数 ──
# 契约：docs/governance/boundary-contract.md（B3 近似）
#
# σ̂_within = mean(MR)/d2（d2=1.128，n=2）不是样本方差的缩放：
# 它由 n−1 个**高度相关**的移动极差构成（相邻 MR 共享一个观测），
# 故有效自由度远小于 n−1。
#
# 实测（logs/reports/verify-round3/a1a3a7_sigma_eta.py，20000 次蒙特卡洛 n=100）：
#     Var(σ̂)/E(σ̂)² = 1/(2·df_eff)  →  df_eff = 60.0 = 0.606·(n−1)
# 该比值与 n 无关（n=20/50/100/200 实测波动 < 0.01），故按系数实现。
#
# 审查 2026-09-24（第三轮复核 P0-3）：原 `_cp_confidence_interval` 用 dof=n−1，
# 使 Cp/Cpk 的 χ²/Bissell 区间过窄约 1.28 倍 → **Cpk 下限虚高**，
# 而"Cpk 下限 ≥1.33"正是工艺放行判据。
# 依据：移动极差估计量的方差见 Montgomery《Introduction to Statistical Quality
# Control》关于 I-MR 图 σ̂ 的讨论（d3/d2 的相对标准差）。R 的 qcc 包对
# "基于 MR 的 σ" 亦使用约 0.62(n−1) 量级的有效自由度。
_MR_DOF_RATIO = 0.606


def _mr_dof_eff(n: int) -> float:
    """移动极差法 σ̂ 的有效自由度 df_eff ≈ 0.606·(n−1)。

    Returns:
        n ≥ 2 时返回正的浮点数；n < 2 时返回 0.0（调用方据此跳过 CI，
        而不是产出虚假区间——见 sentinel-contract「不可估计不伪造」）。
    """
    if n < 2:
        return 0.0
    return _MR_DOF_RATIO * (n - 1)


def _cp_confidence_interval(cp, n, alpha=0.05, dof: float | None = None):
    """Cp 的 95% 置信区间（χ² 分布）。

    审查 2026-09-24 P0-3：自由度由 `n−1` 改为 `df_eff = 0.606(n−1)`
    （移动极差估计量的有效自由度）。覆盖率检验见
    `tests/engine/test_capability_ci_coverage.py`（改前实测约 0.78，改后回到名义 0.95）。

    审查 2026-09-24 P2-5：新增 `dof` 参数以便**同一函数**服务 Pp——
    Pp 用样本标准差（自由度恰为 `n−1`），Cp 用组内 σ（自由度按估计量收缩）。
    两者区间**形式完全相同**，只有自由度不同，故复用而非复制（避免两份公式漂移）。
    显式传入 `dof` 时以传入值为准。
    """
    if cp is None:
        return (None, None)
    effective_dof = _mr_dof_eff(n) if dof is None else float(dof)
    if effective_dof <= 0:
        return (None, None)
    chi2_lower = sp_stats.chi2.ppf(alpha / 2, effective_dof)
    chi2_upper = sp_stats.chi2.ppf(1 - alpha / 2, effective_dof)
    ci_lower = cp * np.sqrt(chi2_lower / effective_dof)
    ci_upper = cp * np.sqrt(chi2_upper / effective_dof)
    return (float(ci_lower), float(ci_upper))


def _cpk_confidence_interval(cpk, n, alpha=0.05, dof: float | None = None):
    """Cpk 95% 置信区间近似（Bissell 方法）。

    Bissell 的 `se = sqrt(1/(9n) + Cpk²/(2·dof))` 假定 σ̂ 是样本标准差
    （`dof = n−1`）。本模块的 Cpk 用组内 σ，故第二项的分母用该估计量的
    有效自由度；第一项 `1/(9n)` 刻画均值偏移项，与 σ 估计量无关，保持不变。

    审查 2026-09-24 P2-5：新增 `dof` 参数以复用于 Ppk（Ppk 的 σ 是样本标准差，
    `dof = n−1`）。显式传入时以传入值为准。
    """
    if cpk is None:
        return (None, None)
    effective_dof = _mr_dof_eff(n) if dof is None else float(dof)
    if effective_dof <= 0:
        return (None, None)
    se = np.sqrt(1 / (9 * n) + cpk**2 / (2 * effective_dof))
    z = sp_stats.norm.ppf(1 - alpha / 2)
    ci_lower = cpk - z * se
    ci_upper = cpk + z * se
    # 审查 2026-09-24 P2-5：钳位必须**保留点估计在区间内**。
    #
    # 原实现只把下限钳到 0，这在 Cpk < 0（过程均值落在规格限之外）时给出
    # **下限 0 高于点估计**的荒谬区间 —— 实测 Cpk=−6.19 时得 CI=(0.0, −5.25)，
    # 上下限还是反的。而 Cpk<0 恰恰是最需要预警的情形。
    #
    # 正确做法：按点估计符号决定钳位方向。点估计 ≥0 时把负下限抬到 0；
    # 点估计 <0 时把正上限压到 0（"上限 0"意为"最好也不过零能力"）。
    lo, hi = float(ci_lower), float(ci_upper)
    if cpk >= 0:
        lo = max(lo, 0.0)
        hi = max(hi, lo)
    else:
        hi = min(hi, 0.0)
        lo = min(lo, hi)
    return (lo, hi)


def _pooled_within_sigma(
    values: np.ndarray, labels: np.ndarray | None, subgroup_size: int | None
) -> tuple[float | None, str, list[str]]:
    """池化组内 σ —— 不依赖"数据行序 = 时间顺序"假设。

    契约：docs/governance/boundary-contract.md（B0 拒绝 / B3 近似）

    审查 2026-09-24（第三轮复核 P2-5）：引擎原先只有**移动极差法**
    （`mean(|diff|)/1.128`），它隐含"相邻行在时间上相邻"。从 Excel 筛选或排序
    一次就会破坏该假设；而按批次成组采集的数据里，移动极差会把**批间跳变**
    算进"组内变异"，使 Cp 偏小。

    本函数提供两条显式子组路径：

    - `labels`（来自 `subgroup_col`）：按列分组，各组内去该组均值后池化
      —— **完全不受行序影响**；
    - `subgroup_size`：按行序切成连续等长子组（经典 X-bar/R 的合理子组）。

    池化定义（Montgomery 式 6.17 的样本标准差形式）：

        σ_pooled = sqrt( Σ_g Σ_i (x_gi − x̄_g)² / (N − k) )

    即"合并在组内自由度上的组内平方和"，k 为子组数。

    Returns:
        `(sigma, method, problems)`。`problems` 非空时调用方应**拒绝**该输入
        （B0），而不是回落到移动极差法 —— 静默回落会让用户以为用了子组口径。

    > ⚠️ **已知局限**：本函数用无偏合并**标准差**，而经典 X-bar/R 的
    > `σ̂ = R̄/d2` 是极差口径。n=5 时两者期望相同，小样本（n=2/3）下
    > 极差口径的方差更大；本实现选标准差口径（自由度明确、可精确验证）。
    """
    problems: list[str] = []
    if subgroup_size is not None:
        if not isinstance(subgroup_size, (int, float)) or isinstance(subgroup_size, bool):
            return (
                None,
                "pooled_subgroup_size",
                [f"参数 subgroup_size 值无效: {subgroup_size!r}，请输入 ≥2 的整数"],
            )
        if float(subgroup_size) != int(subgroup_size):
            return (
                None,
                "pooled_subgroup_size",
                [f"参数 subgroup_size 必须为整数，当前: {subgroup_size!r}"],
            )
        size = int(subgroup_size)
        if size < 2:
            return (
                None,
                "pooled_subgroup_size",
                [
                    f"参数 subgroup_size 必须 ≥2（子组内至少 2 个观测才能估计组内变异），当前: {size}"
                ],
            )
        n_total = len(values)
        if size >= n_total:
            return (
                None,
                "pooled_subgroup_size",
                [
                    f"子组大小 ({size}) 不小于样本量 ({n_total})，无法分组。"
                    "请减小 subgroup_size 或改用 subgroup_col 指定分组列。"
                ],
            )
        n_groups = n_total // size
        if n_groups < 2:
            return (
                None,
                "pooled_subgroup_size",
                [f"按子组大小 {size} 只能分出 {n_groups} 个子组，至少需要 2 个。"],
            )
        groups = [values[i * size : (i + 1) * size] for i in range(n_groups)]
        remainder = n_total - n_groups * size
        if remainder:
            # 显式披露而非静默丢弃（B2：降级必须可见）
            problems.append(
                f"注意：样本量 {n_total} 不是子组大小 {size} 的整数倍，"
                f"末尾 {remainder} 个观测未参与组内 σ 估计（池化使用前 "
                f"{n_groups * size} 个观测）。"
            )
        return _pool_groups(groups, problems), "pooled_subgroup_size", problems

    # labels 路径
    assert labels is not None  # 调用方保证二者之一非空
    uniq, counts = np.unique(labels, return_counts=True)
    if len(uniq) < 2:
        return (
            None,
            "pooled_subgroup_col",
            [
                f"分组列只有 {len(uniq)} 个不同取值（{uniq.tolist() if len(uniq) else '空'}）。"
                "池化组内 σ 需要至少 2 个子组；若数据整体为一组，请改用移动极差法（不传该参数）。"
            ],
        )
    thin = [(str(u), int(c)) for u, c in zip(uniq, counts, strict=True) if c < 2]
    if thin:
        shown = ", ".join(f"{u}({c} 个)" for u, c in thin[:5])
        return (
            None,
            "pooled_subgroup_col",
            [
                f"分组列存在仅含 1 个观测的子组：{shown}"
                + ("…" if len(thin) > 5 else "")
                + "。这类子组对组内变异无贡献，保留会**静默低估**组内 σ，故拒绝。"
            ],
        )
    groups = [values[labels == u] for u in uniq]
    return _pool_groups(groups, problems), "pooled_subgroup_col", problems


def _pool_groups(groups: list[np.ndarray], problems: list[str]) -> float | None:
    """合并组内平方和 → 池化 σ；`N−k ≤ 0` 时返回 None（调用方跳过）。"""
    total = sum(len(g) for g in groups)
    k = len(groups)
    if total - k <= 0:
        return None
    ss = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
    return float(np.sqrt(ss / (total - k)))


def _sigma_level(cpk_val):
    """Cpk → Sigma Level 和 DPMO 估算。

    注意: DPMO 公式使用无偏移 (unshifted) sigma，假设过程均值不发生偏移。
    实际生产中常考虑 1.5σ 偏移，此时 DPMO 会更高。该公式提供的是
    理论最优条件下的缺陷率估算，用于能力对比而非绝对预测。

    Cpk < 0 时（过程均值在规格限外），钳位为 0 以确保 DPMO ≤ 1,000,000
    和 Sigma Level ≥ 0 的物理合理性。
    """
    # Sigma Level ≈ 3 * Cpk（无偏移理论 Z 值；注意与“短期/长期能力”口径无关，
    # 短期/长期由组内 (within) / 整体 (overall) σ 区分，见 Cp/Cpk vs Pp/Ppk）
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
    sw_p = shapiro_p(data)
    # 审查 2026-10-09 P0-3：`shapiro_p` 现在对"不可计算"返回 NaN（原先归一为 1.0，
    # 会把强非正态数据判成"正态 ✓"）。NaN 时不得静默 —— 明确告知无法判定。
    if not np.isfinite(sw_p):
        return "⚠ 正态性检验 (Shapiro-Wilk) 无法计算（数据含非有限值或量级溢出），无法判定正态性"
    if sw_p < 0.01:
        return (
            f"⚠ 正态性检验 (Shapiro-Wilk) p={sw_p:.4f}<0.01，"
            f"数据显著偏离正态分布，建议使用 Box-Cox 变换或非正态能力分析"
        )
    return None


def process_capability_analysis(req: AnalysisRequest) -> AnalysisResult:
    """过程能力分析：Cp/Cpk/Pp/Ppk/Cpm，含置信区间、DPMO 和 Sigma Level。"""
    data = req.data[req.target_col].dropna()
    # ── 边界处置（B0/B1）：**一处声明、一处执行**，走 `engine/_guard.py` ──
    # 审查 2026-09-22 发现 3：±Inf 穿透 dropna 后使 matplotlib hist/set_xlim 抛
    # ValueError（被 orchestrator 泛化翻译为「数据格式不符合要求」）；入口按缺失剔除。
    #
    # 第三十五轮：由手抄（`drop_non_finite` + `non_finite_note` + `warn_msgs`）
    # 改为 `_guard` —— 清算的**披露与错误码**在 `_guard` 一处产出，
    # 本模块只负责把 `report.messages()` 接进结果。
    report = BoundaryReport()
    data, _n_inf = clean_series(data, column=req.target_col, report=report)
    if len(data) < 3:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=[
                f"有效数据不足：过程能力分析至少需要 3 个观测值"
                f"（当前 {len(data)} 个，无法可靠估计标准差）"
            ],
        )

    # Round-2 #A2n：常量数据 → Cp/Cpk/Pp 全 None 且 status=ok，误导
    # 第三十五轮：改由 `_guard.check_non_constant` 判定（B0），
    # 使"常量列"这一拒绝与其它模块**同源**（此前各模块手写各自的判据与文案）。
    _const_issue = check_non_constant(data, what="目标列")
    if _const_issue is not None:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=["目标列为常量列（标准差为 0），过程能力无法估计。"],
        )

    # ── 参数校验（阶段 P4 步骤②③：声明式 Spec + 抛异常式传播）──
    # 原先这里有约 55 行手写的 try/float/isfinite 重复块（usl/lsl/target 各一遍，
    # 每遍两个错误分支）。现由 PARAM_SPEC 一处完成强转、NaN/Inf 拒绝、
    # 取值域与交叉规则校验。
    #
    # **抛异常而非 return status="error"**：参数校验失败是预期内的可复用失败，
    # 由 orchestrator 的 `except SmartSuiteError → build_error_result()` 统一转结果。
    # 若在此处早退，每迁移一个任务反而 +1 处早退（见 core/param_spec.py 的说明）。
    #
    # 行为兼容性由 tests/engine/test_capability_param_migration.py 锁定；
    # Web/CLI 侧看到的仍是 status="error" + 精确中文文案（由编排层组装）。
    _params = PARAM_SPEC.validate_or_raise(req.params)
    usl = _params.usl
    lsl = _params.lsl
    target = _params.target
    transform = _params.transform

    # 注：原 `USL ≤ LSL` 的手写校验已删除 —— 它现在是 `PARAM_SPEC` 的交叉规则
    # （`E_SPEC_INVERTED`）。保留两份会让规则漂移，而 Spec 已是唯一声明处。
    n = len(data)

    # `n_inf` 的披露已由上面的 `clean_series(report=...)` 记录 → 不再手写
    boxcox_lambda: float | None = None

    # ── Box-Cox 变换（非正态数据处理）──
    if transform == "boxcox":
        # MED-3 修复 2026-08-29：变换前备份原始数据与规格限，
        # 规格限变换后非正时回退原始尺度（此前整体丢弃双侧能力指数）
        _orig_data = data
        _orig_usl, _orig_lsl, _orig_target = usl, lsl, target
        transformed, lam = _box_cox_transform(data.values)
        if transformed is not None:
            data = pd.Series(transformed, name=data.name)
            boxcox_lambda = lam
            # 对规格限和目标值同样做 Box-Cox 变换（逐个独立判断，单侧规格也有效）
            # Round-2 P3：此前要求 USL/LSL 同时为正才变换，单侧正规格被整体丢弃
            if usl is not None and usl > 0:
                usl = sp_stats.boxcox(np.array([usl]), lmbda=lam)[0]
            if lsl is not None and lsl > 0:
                lsl = sp_stats.boxcox(np.array([lsl]), lmbda=lam)[0]
            if target is not None and target > 0:
                target = sp_stats.boxcox(np.array([target]), lmbda=lam)[0]
            if (usl is not None and usl <= 0) or (lsl is not None and lsl <= 0):
                report.add(
                    BoundaryIssue(
                        level="B2",
                        code="E_CAPABILITY_BOXCOX_TRANSFORMED_SPEC_NONPOSITIVE",
                        detail=(
                            "⚠ Box-Cox 变换后规格限非正（λ<0 时小值规格限可变换为负），"
                            "无法在变换域计算能力指数，已回退使用原始数据"
                        ),
                    )
                )
                data = _orig_data
                usl, lsl, target = _orig_usl, _orig_lsl, _orig_target
                boxcox_lambda = None
        else:
            report.add(
                BoundaryIssue(
                    level="B2",
                    code="E_CAPABILITY_BOXCOX_FAILED",
                    detail="⚠ Box-Cox 变换失败（数据必须全部为正值），使用原始数据分析",
                )
            )

    norm_warn = _normality_warning(data)
    if norm_warn and transform != "boxcox":
        # 正态性提示属 B3（近似：用正态口径算能力指数，但数据不满足正态假设）
        report.add(
            BoundaryIssue(
                level="B3",
                code="E_CAPABILITY_DATA_NOT_NORMAL",
                detail=norm_warn,
            )
        )

    mu = float(data.mean())
    sigma_overall = float(data.std(ddof=1))  # 整体 σ (用于 Pp/Ppk)

    # ── 组内 σ：三选一（审查 2026-09-24 P2-5）──
    # 默认仍是移动极差法（向后兼容），但显式披露其"行序 = 时间顺序"假设；
    # 提供两条子组路径以摆脱该假设。
    subgroup_col = req.params.get("subgroup_col")
    subgroup_size = req.params.get("subgroup_size")
    if subgroup_col and subgroup_size:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=[
                "参数 subgroup_col 与 subgroup_size 只能二选一（同时给出属歧义输入）。"
                "按列分组请用 subgroup_col，按行序切子组请用 subgroup_size。"
            ],
        )

    # 三个分支统一产出 `_pooled_sigma`（float | None）与 `within_method`，
    # 由下方守卫统一判定 None；`within_sigma` 只在守卫之后绑定为 float，
    # 使类型检查器与运行时校验看到同一件事（避免 12 处 `Optional` 报错）。
    within_method: str
    _sub_problems: list[str]
    _pooled_sigma: float | None
    if subgroup_col:
        if subgroup_col not in req.data.columns:
            return AnalysisResult(
                task="process_capability",
                status="error",
                messages=[
                    f"分组列「{subgroup_col}」不存在于数据中。"
                    f"可用列：{', '.join(map(str, req.data.columns[:12]))}"
                    + ("…" if len(req.data.columns) > 12 else "")
                ],
            )
        _labels = req.data.loc[data.index, subgroup_col].to_numpy()
        _pooled_sigma, within_method, _sub_problems = _pooled_within_sigma(
            data.to_numpy(), _labels, None
        )
    elif subgroup_size is not None:
        _pooled_sigma, within_method, _sub_problems = _pooled_within_sigma(
            data.to_numpy(), None, subgroup_size
        )
    else:
        # ⚠ 移动极差法隐含"数据按行序 = 时间顺序"假设（相邻行差分）；
        # 若数据未按采样时间排序，组内 σ 估计将失真。
        mr = np.abs(np.diff(data.values))
        _pooled_sigma = float(np.mean(mr) / 1.128) if len(mr) > 0 else sigma_overall
        within_method = "moving_range"
        _sub_problems = [
            "组内 σ 使用**移动极差法**（相邻行差分的均值 / 1.128），"
            "隐含「数据行序 = 采样时间顺序」假设。若数据经过筛选/排序，或按批次成组采集，"
            "该估计会失真 —— 请用 subgroup_col 指定分组列，或用 subgroup_size 指定子组大小。"
        ]

    # 子组路径的显式错误（B0 拒绝，不回落）+ 披露（B2 降级可见）
    if _pooled_sigma is None:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=_sub_problems or ["子组口径无法估计组内标准差，请检查分组设置。"],
        )
    within_sigma: float = _pooled_sigma
    for _msg in _sub_problems:
        report.add(
            BoundaryIssue(
                level="B3",
                code="E_CAPABILITY_SUBGROUP_SIGMA_CAVEAT",
                # 文案拼装规则与迁移前**逐字一致**（以「注意」开头的不加 ⚠ 前缀）——
                # 改写文案会改变用户可见内容，那不属于"消除手抄"的范围。
                detail=_msg if _msg.startswith("注意") else f"⚠ {_msg}",
            )
        )
    within_sigma_dof = _mr_dof_eff(n) if within_method == "moving_range" else None

    # ── 计算各项能力指数 ──

    # Cp/Cpk (短期/组内) — 单侧公差仅计算 Cpk
    cp = (
        float((usl - lsl) / (6 * within_sigma))
        if usl is not None and lsl is not None and np.isfinite(within_sigma) and within_sigma > 0
        else None
    )
    if usl is not None and lsl is not None:
        cpk_val = (
            float(min((usl - mu) / (3 * within_sigma), (mu - lsl) / (3 * within_sigma)))
            if np.isfinite(within_sigma) and within_sigma > 0
            else None
        )
    elif usl is not None:
        cpk_val = (
            float((usl - mu) / (3 * within_sigma))
            if np.isfinite(within_sigma) and within_sigma > 0
            else None
        )
    elif lsl is not None:
        cpk_val = (
            float((mu - lsl) / (3 * within_sigma))
            if np.isfinite(within_sigma) and within_sigma > 0
            else None
        )
    else:
        cpk_val = None

    # Pp/Ppk (长期/整体) — 单侧公差仅计算 Ppk
    pp = (
        float((usl - lsl) / (6 * sigma_overall))
        if usl is not None and lsl is not None and sigma_overall > 0
        else None
    )
    if usl is not None and lsl is not None:
        ppk_val = (
            float(min((usl - mu) / (3 * sigma_overall), (mu - lsl) / (3 * sigma_overall)))
            if sigma_overall > 0
            else None
        )
    elif usl is not None:
        ppk_val = float((usl - mu) / (3 * sigma_overall)) if sigma_overall > 0 else None
    elif lsl is not None:
        ppk_val = float((mu - lsl) / (3 * sigma_overall)) if sigma_overall > 0 else None
    else:
        ppk_val = None

    # Cpm (Taguchi 能力指数, 需双侧公差)
    cpm = None
    if usl is not None and lsl is not None and target is not None and sigma_overall > 0:
        tau = np.sqrt(sigma_overall**2 + (mu - target) ** 2)
        cpm = float((usl - lsl) / (6 * tau)) if tau > 0 else None

    # 置信区间
    cp_ci = _cp_confidence_interval(cp, n, dof=within_sigma_dof) if cp is not None else (None, None)
    cpk_ci = (
        _cpk_confidence_interval(cpk_val, n, dof=within_sigma_dof)
        if cpk_val is not None
        else (None, None)
    )
    # Pp/Ppk 的 CI（审查 2026-09-24 P2-5）：整体 σ 是样本标准差，自由度恰为 n−1，
    # 无需像组内 σ 那样收缩。此前 Ppk 无区间，而它常被直接当放行判据用。
    _overall_dof = float(n - 1) if n > 1 else 0.0
    pp_ci = _cp_confidence_interval(pp, n, dof=_overall_dof) if pp is not None else (None, None)
    ppk_ci = (
        _cpk_confidence_interval(ppk_val, n, dof=_overall_dof)
        if ppk_val is not None
        else (None, None)
    )

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
        {
            "指标": "Cp (短期能力)",
            "值": f"{cp:.3f}" if cp is not None else "N/A",
            "95%CI下限": f"{cp_ci[0]:.3f}" if cp_ci[0] is not None else "N/A",
            "95%CI上限": f"{cp_ci[1]:.3f}" if cp_ci[1] is not None else "N/A",
        },
        {
            "指标": "Cpk (短期+偏倚)",
            "值": f"{cpk_val:.3f}" if cpk_val is not None else "N/A",
            "95%CI下限": f"{cpk_ci[0]:.3f}" if cpk_ci[0] is not None else "N/A",
            "95%CI上限": f"{cpk_ci[1]:.3f}" if cpk_ci[1] is not None else "N/A",
        },
        {
            "指标": "Pp (长期能力)",
            "值": f"{pp:.3f}" if pp is not None else "N/A",
            "95%CI下限": "N/A",
            "95%CI上限": "N/A",
        },
        {
            "指标": "Ppk (长期+偏倚)",
            "值": f"{ppk_val:.3f}" if ppk_val is not None else "N/A",
            "95%CI下限": "N/A",
            "95%CI上限": "N/A",
        },
        {
            "指标": "Cpm (田口能力)",
            "值": f"{cpm:.3f}" if cpm is not None else "N/A",
            "95%CI下限": "N/A",
            "95%CI上限": "N/A",
        },
        {
            "指标": "Sigma Level (无偏移理论值)",
            "值": f"{sigma_lvl:.2f}" if sigma_lvl is not None else "N/A",
            "95%CI下限": "N/A",
            "95%CI上限": "N/A",
        },
        {
            "指标": "DPMO (无偏移假设)",
            "值": f"{dpmo:,}" if dpmo is not None else "N/A",
            "95%CI下限": "N/A",
            "95%CI上限": "N/A",
        },
    ]
    capability_df = pd.DataFrame(capability_rows)

    # ── 描述统计表 ──
    desc_df = pd.DataFrame(
        {
            "统计量": ["样本量", "均值", "整体σ", "组内σ", "偏度", "峰度", "USL", "LSL", "目标值"],
            "值": [
                str(n),
                f"{mu:.4f}",
                f"{sigma_overall:.4f}",
                f"{within_sigma:.4f}",
                f"{float(data.skew()):.4f}",
                f"{float(data.kurtosis()):.4f}",
                str(usl) if usl is not None else "未指定",
                str(lsl) if lsl is not None else "未指定",
                str(target) if target is not None else "未指定",
            ],
        }
    )

    # ── 增强直方图 + 正态拟合曲线 + 规格限区域 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    # 直方图
    n_bins = min(30, max(10, int(np.sqrt(n))))
    counts, bins, patches = ax.hist(
        data,
        bins=n_bins,
        color=PALETTE["data"]["secondary"],
        edgecolor="white",
        alpha=0.7,
        density=True,
        label="数据分布",
    )

    # 正态拟合曲线
    x_fit = np.linspace(data.min(), data.max(), 200)
    pdf_fit = sp_stats.norm.pdf(x_fit, mu, sigma_overall)
    ax.plot(
        x_fit,
        pdf_fit,
        color=PALETTE["data"]["primary"],
        linewidth=2,
        label=f"正态拟合 (μ={mu:.3f}, σ={sigma_overall:.3f})",
    )

    # 规格限
    ax.axvline(
        mu, color=PALETTE["center"]["primary"], linestyle="-", linewidth=2, label=f"均值={mu:.4f}"
    )
    if lsl is not None:
        ax.axvline(
            lsl, color=PALETTE["anomaly"]["primary"], linestyle="-", linewidth=2, label=f"LSL={lsl}"
        )
    if usl is not None:
        ax.axvline(
            usl, color=PALETTE["anomaly"]["primary"], linestyle="-", linewidth=2, label=f"USL={usl}"
        )
    if target is not None:
        ax.axvline(
            target,
            color=PALETTE["direction"]["zero"],
            linestyle=":",
            linewidth=1.5,
            label=f"目标={target}",
        )

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
            "cp": cp,
            "cpk": cpk_val,
            "pp": pp,
            "ppk": ppk_val,
            "cpm": cpm,
            "cp_ci": cp_ci,
            "cpk_ci": cpk_ci,
            # Pp/Ppk 的 CI（P2-5）
            "pp_ci": pp_ci,
            "ppk_ci": ppk_ci,
            "sigma_level": sigma_lvl,
            "dpmo": dpmo,
            "mean": mu,
            "sigma_overall": sigma_overall,
            "sigma_within": within_sigma,
            # 组内 σ 的口径（P2-5）：moving_range / pooled_subgroup_col /
            # pooled_subgroup_size。三种口径的数值不可直接比较，必须随数值披露。
            "within_sigma_method": within_method,
            "n": n,
            "judge": judge,
            "boxcox_lambda": boxcox_lambda,
            # ── 边界处置的**机器可读错误码**（第三十五轮随 `_guard` 迁移兑现）──
            # 迁移前是手抄的 `warn_msgs: list[str]`，只有文案、没有码 ——
            # 上游（API 消费者、日志聚合）无法可靠地按"处置类型"分流，
            # 只能对中文文案做子串匹配（脆弱且随文案改动失效）。
            # 现由 `BoundaryIssue.code` 一处产出，`report.codes()` 去重导出。
            # 详情（含列名与数量）仍在 `messages` 里，供用户阅读。
            "boundary_codes": report.codes(),
        },
        messages=report.messages(),
    )
