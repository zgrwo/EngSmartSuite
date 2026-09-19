"""区间估计与方差检验：比例 CI、方差齐性检验。"""

import logging
from math import sqrt

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float

logger = logging.getLogger(__name__)


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
    success_val = req.params.get("success_value")
    if success_val is not None:
        successes = int((data == success_val).sum())
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

    # 置信水平（用户可配置，默认 95%）
    ci_level = _safe_float(req.params.get("ci_level", 0.95), 0.95)
    if not 0 < ci_level < 1:
        return AnalysisResult(
            task="proportion_ci",
            status="error",
            messages=[f"置信水平 ci_level 必须在 (0, 1) 范围内，当前值: {ci_level}"],
        )
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
    ax.set_xlabel("比例", fontsize=10)
    ax.set_title(f"二项比例 {ci_level:.0%} CI — {req.target_col} (n={n})", fontsize=11)
    ax.legend(fontsize=8)
    ax.set_xlim(0, 1)
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
    # 显式检查 None：避免 DEFAULT_PARAMS 注入 None 阻断 fallback 逻辑 (P2 fix)
    group_col = req.params.get("group_col")
    if group_col is None:
        group_col = req.feature_cols[0] if req.feature_cols else None
    if group_col is None or group_col not in req.data.columns:
        return AnalysisResult(
            task="variance_test", status="error", messages=["需要提供分组列 (group_col)"]
        )

    sub = req.data[[req.target_col, group_col]].dropna()
    groups = sub[group_col].unique()
    if len(groups) < 2:
        return AnalysisResult(task="variance_test", status="error", messages=["至少需要 2 个分组"])

    group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
    valid_groups = [(str(g), d) for g, d in zip(groups, group_data) if len(d) >= 2]

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
    if lev_p is not None:
        levene_result = "方差齐性 ✓" if lev_p >= alpha else f"方差不齐 (p={lev_p:.4f})"
    else:
        levene_result = "N/A"
    if bart_p is not None:
        bartlett_result = "方差齐性 ✓" if bart_p >= alpha else f"方差不齐 (p={bart_p:.4f})"
    else:
        bartlett_result = "N/A"

    # 各组建模统计
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
        metadata={
            "levene_p": float(lev_p) if lev_p is not None else None,
            "bartlett_p": float(bart_p) if bart_p is not None else None,
            "n_groups": len(valid_groups),
        },
    )
