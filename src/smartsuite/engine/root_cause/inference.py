"""区间估计与方差检验：比例 CI、方差齐性检验。"""

import contextlib
import logging
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Opt, Spec
from smartsuite.core.param_specs_common import ALPHA, CI_LEVEL, GROUP_COL
from smartsuite.engine._guard import BoundaryIssue, BoundaryReport, check_magnitude, clean_frame
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float

logger = logging.getLogger(__name__)


# ── 声明式参数契约（P4 步骤③，第二十轮起：共享字段库驱动）──
# 按**任务**登记（本模块含 proportion_ci / variance_test 等多个任务）。
PARAM_SPECS = {
    "variance_test": Spec(group_col=GROUP_COL, alpha=ALPHA),
    # 第二十二轮：`ci_level` 引用共享常量；`success_value` 故意**不校验** ——
    # 它是"成功标签的匹配值"，用户可能用 1 / "1" / "合格" 等任意类型，
    # 故只声明标签与提示、`validator=None` 原样透传。
    "proportion_ci": Spec(
        ci_level=CI_LEVEL,
        success_value=Opt(
            default=None,
            label="成功值",
            hint="指定哪个取值算作「成功」（如 1 / 合格）；留空则自动识别常见标签",
        ),
    ),
}


def proportion_ci(req: AnalysisRequest) -> AnalysisResult:
    """二项比例置信区间 — Wilson Score 和 Clopper-Pearson 精确方法。

    适用于合格率、不良率、通过率等二项数据的区间估计。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n == 0:
        return AnalysisResult(
            task="proportion_ci", status="error", messages=[f"列「{req.target_col}」有效数据为空"]
        )
    # 将数据转为 0/1
    unique_vals = data.unique()
    if len(unique_vals) > 2:
        return AnalysisResult(
            task="proportion_ci",
            status="error",
            messages=[f"列「{req.target_col}」包含超过 2 个不同值，需要二值数据"],
        )

    # 自动识别"成功"标签
    # 审查 2026-10-09 P2-6：显式传入的 `success_value` 若**不在列的实际取值中**，
    # 原实现 `int((data == success_val).sum())` 恒得 0 → 点估计 0.0000、
    # status=ok、messages 为空 —— 合格率/不良率这类质量 KPI 会直出「0%」的错误结论。
    # 同时修类型敏感：面板（`<select>`/文本框）只能给出字符串，故 `'1'` 必须能命中数值 1。
    success_val = req.params.get("success_value")
    if isinstance(success_val, str) and success_val.strip() == "":
        success_val = None  # 空串 = 未提供（与前端"留空"语义一致）
    if success_val is not None:
        candidates: list[Any] = [success_val]
        s = str(success_val)
        candidates.append(s)
        with contextlib.suppress(TypeError, ValueError):
            f = float(s)
            candidates.append(f)
            if f.is_integer():
                candidates.append(int(f))
        mask = data.isin(candidates)
        if not mask.any():
            _vals = [str(v) for v in unique_vals[:8]]
            return AnalysisResult(
                task="proportion_ci",
                status="error",
                messages=[
                    f"参数「成功值」={success_val!r} 未出现在列「{req.target_col}」的实际取值中："
                    f"{_vals}。请指定一个实际存在的取值，或留空以自动识别。"
                ],
            )
        successes = int(mask.sum())
    else:
        # 尝试常见标签
        for label in ["合格", "是", "pass", "ok", "yes", "true", "success", "通过", "正常", 1, "1"]:
            if label in unique_vals:
                successes = int((data == label).sum())
                break
        else:
            # 默认取出现最多的值
            successes = int(data.value_counts().iloc[0])

    p_hat = successes / n

    # 参数校验（P4 步骤③，第二十二轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 迁移前是 `_safe_float` 安全转换 + 一段 (0,1) 区间检查。
    ci_level = PARAM_SPECS["proportion_ci"].validate_or_raise(req.params).ci_level
    alpha_tail = (1 - ci_level) / 2

    # Wilson Score CI
    z = sp_stats.norm.ppf(1 - alpha_tail)
    denominator = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denominator
    margin = z * sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator
    wilson_lower = max(0, center - margin)
    wilson_upper = min(1, center + margin)

    # Clopper-Pearson 精确 CI
    cp_lower = sp_stats.beta.ppf(alpha_tail, successes, n - successes + 1) if successes > 0 else 0
    cp_upper = (
        sp_stats.beta.ppf(1 - alpha_tail, successes + 1, n - successes) if successes < n else 1
    )

    # 可视化
    fig = Figure(figsize=(6, 3))
    ax = fig.add_subplot(111)
    methods = ["Wilson Score", "Clopper-Pearson"]
    # Round-2 #A2i：宽度必须为 upper-lower（此前 width=upper-p_hat → 条右端错位）
    widths = [wilson_upper - wilson_lower, cp_upper - cp_lower]
    ax.barh(
        methods,
        widths,
        left=[wilson_lower, cp_lower],
        height=0.3,
        color=[PALETTE["data"]["secondary"], PALETTE["data"]["primary"]],
        edgecolor="white",
    )
    ax.axvline(p_hat, color=PALETTE["target"]["primary"], linewidth=2, label=f"p_hat={p_hat:.4f}")
    # 端点数值标注（区间很窄时文字才是可读信息）
    for yi, (lo_v, hi_v) in enumerate([(wilson_lower, wilson_upper), (cp_lower, cp_upper)]):
        ax.annotate(
            f"[{lo_v:.4f}, {hi_v:.4f}]",
            xy=(hi_v, yi),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
        )
    # 自适应放大 x 轴：数据集中在某一段时不再画满 0~1 造成大片空白
    lo = min(wilson_lower, cp_lower, p_hat)
    hi = max(wilson_upper, cp_upper, p_hat)
    pad = max((hi - lo) * 0.35, 0.005)
    ax.set_xlim(max(0.0, lo - pad), min(1.0, hi + pad))
    ax.set_xlabel("比例", fontsize=10)
    ax.set_title(f"二项比例 {ci_level:.0%} CI — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()

    summary = (
        f"比例估计: {successes}/{n} = {p_hat:.2%}。"
        f"Wilson {ci_level:.0%}CI: [{wilson_lower:.2%}, {wilson_upper:.2%}]"
    )

    return AnalysisResult(
        task="proportion_ci",
        tables={
            "proportion_ci": pd.DataFrame(
                {
                    "方法": ["点估计", "Wilson Score (推荐)", "Clopper-Pearson (精确)"],
                    "下限": [f"{p_hat:.4f}", f"{wilson_lower:.4f}", f"{cp_lower:.4f}"],
                    "上限": [f"{p_hat:.4f}", f"{wilson_upper:.4f}", f"{cp_upper:.4f}"],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "successes": successes,
            "n": n,
            "p_hat": p_hat,
            "wilson_ci": (float(wilson_lower), float(wilson_upper)),
            "clopper_pearson_ci": (float(cp_lower), float(cp_upper)),
        },
    )


def variance_test(req: AnalysisRequest) -> AnalysisResult:
    """方差齐性检验 — Levene 和 Bartlett 检验。

    用于 ANOVA 前验证方差齐性假设，或比较不同组的离散程度。
    """
    # 参数校验（P4 步骤③）：失败时抛 ParamValidationError。
    # `group_col` 的缺省由共享常量 `GROUP_COL` 给 `None`，与下面的回落判断
    # （`if group_col is None: group_col = feature_cols[0]`）直接兼容。
    # 仍保留 `or None` 归一：显式传空串时也走回落，与迁移前行为一致。
    _params = PARAM_SPECS["variance_test"].validate_or_raise(req.params)
    group_col = _params.group_col or None
    if group_col is None:
        group_col = req.feature_cols[0] if req.feature_cols else None
    if group_col is None or group_col not in req.data.columns:
        return AnalysisResult(
            task="variance_test", status="error", messages=["需要提供分组列 (group_col)"]
        )

    # ── 边界处置（B1）：±Inf 必须清洗并披露 ──
    # 审查 2026-10-09 P0-4：`dropna()` **不剔除 ±Inf**（Inf 不是 NaN），故 ±Inf 穿透后
    # 使 `scipy.levene/bartlett` 返回 NaN。旧实现把 NaN 判决写成确定结论
    # 「方差不齐 (p=nan)」（`NaN >= alpha` 恒为 False 落进 else 分支），
    # 且 status=ok、messages 为空。
    _report = BoundaryReport()
    sub, _n_dropped = clean_frame(
        req.data[[req.target_col, group_col]], [req.target_col], report=_report
    )
    sub = sub.dropna()
    # 审查 2026-10-09 P1-4：量级上界守卫（B0）。×1e300 时 Levene/Bartlett 的平方和
    # 溢出 → 统计量非有限。此前只做披露（结论标「无法判定」）但不拒绝；
    # 现与其余任务口径一致地明确拒绝 —— 用户得到可执行的修复建议，
    # 而不是一张没有结论的表。
    if (
        issue := check_magnitude(sub[req.target_col], what=f"「{req.target_col}」", report=_report)
    ) is not None:
        return AnalysisResult(task="variance_test", status="error", messages=[issue.detail])
    groups = sub[group_col].unique()
    if len(groups) < 2:
        return AnalysisResult(task="variance_test", status="error", messages=["至少需要 2 个分组"])

    group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
    valid_groups = [(str(g), d) for g, d in zip(groups, group_data, strict=True) if len(d) >= 2]

    if len(valid_groups) < 2:
        return AnalysisResult(task="variance_test", status="error", messages=["有效分组不足"])

    data_list = [d for _, d in valid_groups]

    # Levene (对非正态更鲁棒，推荐)
    try:
        lev_stat, lev_p = sp_stats.levene(*data_list, center="median")
    except Exception:
        logger.debug("Levene 检验失败", exc_info=True)
        lev_stat, lev_p = None, None

    # Bartlett (要求正态，更敏感)
    try:
        bart_stat, bart_p = sp_stats.bartlett(*data_list)
    except Exception:
        logger.debug("Bartlett 检验失败", exc_info=True)
        bart_stat, bart_p = None, None

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="variance_test",
            status="error",
            messages=[f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}"],
        )

    # 判定
    # 审查 2026-10-09 P0-4：统计量非有限（量级溢出等）时 `p >= alpha` 恒为 False，
    # 旧实现会落进 else 分支把「无法判定」写成确定结论「方差不齐 (p=nan)」。
    # 不可判定必须显式标注（陷阱 9 规则 2：不得伪造结论）。
    def _verdict(p) -> str:
        if p is None:
            return "N/A"
        if not np.isfinite(p):
            return "无法判定（检验统计量非有限）"
        return "方差齐性 ✓" if p >= alpha else f"方差不齐 (p={p:.4f})"

    levene_result = _verdict(lev_p)
    bartlett_result = _verdict(bart_p)
    if (lev_p is not None and not np.isfinite(lev_p)) or (
        bart_p is not None and not np.isfinite(bart_p)
    ):
        _report.add(
            BoundaryIssue(
                level="B3",
                code="E_NUMERIC_TEST_STAT_UNDEFINED",
                detail=(
                    "⚠ 方差齐性检验统计量非有限（数据量级过大导致平方和溢出），"
                    "结论标注为「无法判定」—— 请先做单位换算或中心化"
                ),
            )
        )

    # 各组建模统计（D5 输出保洁：非有限值不得渗漏进结果表）
    desc_rows = []
    for g, d in valid_groups:
        desc_rows.append(
            {
                "分组": g,
                "样本量": len(d),
                "均值": f"{np.mean(d):.4f}",
                "标准差": f"{np.std(d, ddof=1):.4f}",
                "方差": f"{np.var(d, ddof=1):.4f}",
                "IQR": f"{np.percentile(d, 75) - np.percentile(d, 25):.4f}",
            }
        )

    return AnalysisResult(
        task="variance_test",
        tables={
            "variance_tests": pd.DataFrame(
                {
                    "检验方法": ["Levene (中位数, 推荐)", "Bartlett (需正态)"],
                    "统计量": [
                        f"{lev_stat:.4f}" if lev_stat is not None else "N/A",
                        f"{bart_stat:.4f}" if bart_stat is not None else "N/A",
                    ],
                    "p值": [
                        f"{lev_p:.4f}" if lev_p is not None else "N/A",
                        f"{bart_p:.4f}" if bart_p is not None else "N/A",
                    ],
                    "结论": [levene_result, bartlett_result],
                }
            ),
            "group_statistics": pd.DataFrame(desc_rows),
        },
        summary=(
            f"方差齐性检验: Levene {levene_result}"
            + (f", Bartlett {bartlett_result}" if bart_p is not None else "")
        ),
        messages=_report.messages(),
        metadata={
            "levene_p": float(lev_p) if lev_p is not None else None,
            "bartlett_p": float(bart_p) if bart_p is not None else None,
            "n_groups": len(valid_groups),
            "boundary_codes": _report.codes(),
        },
    )
