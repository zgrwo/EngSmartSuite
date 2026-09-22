"""假设检验：t/Friedman/Cochran Q/KS/效应量族。"""

import logging
from math import sqrt

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    EPSILON,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    drop_non_finite,
    drop_non_finite_rows,
    non_finite_note,
    round_for_display,
    shapiro_p,
)
from smartsuite.engine._utils import safe_float as _safe_float
from smartsuite.engine.root_cause._shared import (
    _correlation_ci,
    _effect_interpretation,
    _effect_size_label,
)

logger = logging.getLogger(__name__)


def _resolve_group_col(req, task_name: str) -> tuple[str | None, AnalysisResult | None]:
    """解析分组列参数：None 回退 feature_cols[0]，无效时返回 (None, 中文错误结果)。

    审查 2026-08-19 #1.1/#2.10：DEFAULT_PARAMS 恒注入 group_col=None，
    双参 .get(key, default) 会返回 None 而非默认值，导致 req.data[[target, None]]
    KeyError；且 group_col 指向不存在列时同样 KeyError。统一在此处兜底。
    """
    group_col = req.params.get("group_col")
    if group_col is None:
        group_col = req.feature_cols[0] if req.feature_cols else None
    if group_col is None or group_col not in req.data.columns:
        return None, AnalysisResult(
            task=task_name,
            status="error",
            messages=[f"分组列(group_col)无效或不存在: {group_col!r}，请检查参数或数据列名"],
        )
    return group_col, None


def _binary_encode(series, col_name: str = ""):
    """验证二分类列并编码为 0/1。

    返回 (binary_array, error_msg)。
    成功时 error_msg 为 None，binary_array 为 int 型 numpy 数组。
    失败时 binary_array 为 None，error_msg 为中文错误描述。

    编码规则: 排序后的较大值 (sorted[-1]) 映射为 1，较小值映射为 0。
    注意: NaN 值会被编码为 0（因为 NaN != uv[1] 返回 False），调用方
    如需区分 NaN 和真实值，应先自行处理缺失值。
    """
    vals = series.dropna()
    unique_vals = vals.unique()
    if len(unique_vals) != 2:
        label = f"「{col_name}」" if col_name else "该列"
        return None, f"{label}不是二分类数据（唯一值数={len(unique_vals)}，需要恰好2个）"
    uv = sorted(unique_vals)
    n_nan = int(series.isna().sum())
    if n_nan > 0:
        logger.warning(
            "列「%s」存在 %d 个缺失值，将被编码为 0（与「%s」归为一类）。"
            "如需区分缺失值，请先填充后再分析。",
            col_name or "未知",
            n_nan,
            str(uv[0]),
        )
    return (series == uv[1]).astype(int).values, None


def _cohens_d(x, y, warn_list: list[str] | None = None):
    """Cohen's d 效应量 (Hedges' g 校正小样本偏差)。

    当样本量不足时返回 0.0 并向 warn_list 追加警告消息。
    """
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        if warn_list is not None:
            warn_list.append(
                f"⚠ 效应量计算: 样本量不足 (n1={n1}, n2={n2})，Hedges g 无法可靠估计，已返回 0"
            )
        return 0.0
    s1, s2 = np.std(x, ddof=1), np.std(y, ddof=1)
    # 合并标准差
    sp = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    # 审查 2026-09-16 B-3：sp 带数据量纲，原 `sp < EPSILON`（绝对 1e-10）把微尺度
    # 真实效应静默归 0；仅当两组均零方差（sp 精确为 0）或非有限时才无法估计，
    # 返回 0 的同时给出警告（不静默）
    if not np.isfinite(sp) or sp == 0:
        if warn_list is not None:
            warn_list.append(
                "⚠ 效应量计算: 两组数据均无变异（合并标准差为 0），Hedges g 无法估计，已返回 0"
            )
        return 0.0
    d = (np.mean(x) - np.mean(y)) / sp
    # Hedges' g 小样本校正因子
    correction = 1 - 3 / (4 * (n1 + n2) - 9)
    return float(d * correction)


def _cliffs_delta(x, y):
    """Cliff's delta — 非参数效应量，适用于 Mann-Whitney。值域 [-1, 1]。

    使用基于排序的 O(n log n) 向量化实现，避免 O(n²) Python 循环。
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    n1, n2 = len(x_arr), len(y_arr)
    if n1 == 0 or n2 == 0:
        return 0.0

    # 对 y 排序后，用 searchsorted 批量统计
    y_sorted = np.sort(y_arr)
    # lt_count: y 中严格小于各 xi 的元素总数
    lt_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="left")))
    # le_count: y 中小于等于各 xi 的元素总数
    le_count = int(np.sum(np.searchsorted(y_sorted, x_arr, side="right")))
    # dominance = #(xi > yj) - #(xi < yj) = 2*lt_count + eq_count - n1*n2
    dominance = lt_count + le_count - n1 * n2
    return float(dominance / (n1 * n2))


def _cohens_d_ci(
    d: float, n1: int, n2: int, alpha: float = 0.05, *, paired: bool = False
) -> tuple[float, float]:
    """Cohen's d 的 95% CI（正态近似法）。

    双样本: SE(d) ≈ sqrt((n1+n2)/(n1*n2) + d²/(2*(n1+n2)))  [Hedges & Olkin 1985]
    单样本/配对: SE(d) ≈ sqrt(1/n + d²/(2n))  [Cohen 1988]
    """
    if n1 < 2 or n2 < 2:
        return (float("nan"), float("nan"))
    if paired:
        # 单样本/配对设计: n 为观测对数
        n = n1
        se = np.sqrt(1.0 / n + d**2 / (2.0 * n))
    else:
        se = np.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
    z = sp_stats.norm.ppf(1 - alpha / 2)
    return (float(d - z * se), float(d + z * se))


# ── 假设检验分支调度 ── 新增检验类型只需在此注册 + 实现私有函数
def _ht_cochran_q(req: AnalysisRequest) -> AnalysisResult:
    """Cochran Q 检验 (3+ 配对二分类条件)。"""
    measure_cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(measure_cols) < 2:
        return AnalysisResult(
            task="hypothesis_test", status="error", messages=["Cochran Q 需要至少 2 个二分类条件列"]
        )
    sub = req.data[measure_cols].dropna()
    if len(sub) < 3:
        return AnalysisResult(
            task="hypothesis_test", status="error", messages=["有效数据不足(至少3行)"]
        )
    k = len(measure_cols)
    binary = pd.DataFrame(index=sub.index)
    for c in measure_cols:
        encoded, err = _binary_encode(sub[c], c)
        if err:
            return AnalysisResult(task="hypothesis_test", status="error", messages=[err])
        binary[c] = encoded
    col_sums = binary.sum(axis=0).values
    row_sums = binary.sum(axis=1).values
    Q = (k - 1) * (k * np.sum(col_sums**2) - np.sum(col_sums) ** 2)
    denom = k * np.sum(row_sums) - np.sum(row_sums**2)
    if denom < EPSILON:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[
                "Cochran Q 无法计算：所有样本在各条件下的响应完全一致（分母为零），不满足检验前提。"
            ],
        )
    Q = Q / denom
    p = float(sp_stats.chi2.sf(max(Q, 0), k - 1))
    test_name = f"Cochran Q 检验 ({k} 条件)"
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    conclusion = "条件间存在显著差异" if p < alpha else "条件间未发现显著差异"
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "统计量(Q)": [f"{Q:.3f}"],
                    "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)],
                    "条件数": [str(k)],
                    "样本量": [str(len(sub))],
                    "结论": [conclusion],
                }
            )
        },
        summary=f"Cochran Q: {conclusion} (Q={Q:.2f}, p={p:.4f}, k={k})",
        metadata={
            "test": test_name,
            "statistic": float(Q),
            "p_value": float(p),
            "alpha": alpha,
            "k": k,
            "n": len(sub),
        },
    )


def _ht_ks(req: AnalysisRequest) -> AnalysisResult:
    """Kolmogorov-Smirnov 双样本检验。"""
    # 显式检查 None + 列存在性：避免 DEFAULT_PARAMS 注入 None 阻断 fallback (P3 fix)
    group_col, group_err = _resolve_group_col(req, "hypothesis_test")
    if group_err is not None:
        return group_err
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(
            task="hypothesis_test", status="error", messages=["KS 检验需要恰好 2 个分组"]
        )
    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()
    g1, n_inf1 = drop_non_finite(g1)
    g2, n_inf2 = drop_non_finite(g2)
    inf_msgs = [non_finite_note(n, req.target_col) for n in (n_inf1, n_inf2) if n]
    if len(g1) < 3 or len(g2) < 3:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=["KS 检验每组至少需要 3 个有效观测（某组目标列可能全为 NaN/Inf）"],
        )
    stat, p = sp_stats.ks_2samp(g1, g2)
    test_name = f"Kolmogorov-Smirnov 检验 ({groups[0]} vs {groups[1]})"
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    conclusion = "两样本分布存在显著差异" if p < alpha else "未发现分布差异"
    fig = Figure(figsize=(7, 4))
    ax = fig.add_subplot(111)
    ax.hist(
        g1,
        bins=20,
        alpha=0.6,
        color=PALETTE["data"]["secondary"],
        density=True,
        label=str(groups[0]),
    )
    ax.hist(
        g2, bins=20, alpha=0.6, color=PALETTE["contrast"]["b"], density=True, label=str(groups[1])
    )
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_title(f"{test_name} (D={stat:.3f}, p={p:.4f})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "统计量(D)": [f"{stat:.4f}"],
                    "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)],
                    "结论": [conclusion],
                }
            )
        },
        figures=[fig],
        summary=f"KS 检验: {conclusion} (D={stat:.3f}, p={p:.4f})",
        metadata={"test": test_name, "statistic": float(stat), "p_value": float(p), "alpha": alpha},
        messages=inf_msgs,
    )


def _ht_friedman(req: AnalysisRequest) -> AnalysisResult:
    """Friedman 检验 (非参数重复测量)。"""
    measure_cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(measure_cols) < 2:
        measure_cols = [req.target_col] + [c for c in req.feature_cols[:2] if c in req.data.columns]
    sub = req.data[measure_cols].dropna()
    sub, n_inf = drop_non_finite_rows(sub, measure_cols)
    inf_msgs = [non_finite_note(n_inf)] if n_inf else []
    if len(sub) < 3 or len(measure_cols) < 2:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=["Friedman 检验需要至少 2 个重复测量条件和 3 个完整观测"],
        )
    stat, p = sp_stats.friedmanchisquare(*[sub[c].values for c in measure_cols])
    test_name = f"Friedman 检验 (非参数重复测量, {len(measure_cols)} 条件)"
    n = len(sub)
    k = len(measure_cols)
    kendall_w = float(stat / (n * (k - 1))) if n > 0 and k > 1 else 0.0
    if kendall_w > 0.5:
        effect_label = "强一致"
    elif kendall_w > 0.3:
        effect_label = "中等一致"
    elif kendall_w > 0.1:
        effect_label = "弱一致"
    else:
        effect_label = "可忽略"
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    conclusion = "条件间存在显著差异" if p < alpha else "条件间未发现显著差异"
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    means = [sub[c].median() for c in measure_cols]
    ax.bar(range(len(measure_cols)), means, color=PALETTE["data"]["secondary"], edgecolor="white")
    ax.set_xticks(range(len(measure_cols)))
    ax.set_xticklabels(measure_cols, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("中位数", fontsize=10)
    ax.set_title(f"{test_name} (χ²={stat:.2f}, p={p:.4f})", fontsize=11)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "统计量(χ²)": [f"{stat:.3f}"],
                    "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)],
                    "效应量": [f"Kendall's W={kendall_w:.3f} ({effect_label})"],
                    "结论": [conclusion],
                }
            )
        },
        figures=[fig],
        summary=f"Friedman: {conclusion} (χ²={stat:.2f}, p={p:.4f}, W={kendall_w:.3f})",
        metadata={
            "test": test_name,
            "statistic": float(stat),
            "p_value": float(p),
            "alpha": alpha,
            "effect_size": kendall_w,
            "n": n,
            "k": k,
        },
        messages=inf_msgs,
    )


def _ht_cohens_d(req: AnalysisRequest) -> AnalysisResult:
    """效应量 Hedges g（不检验）— 两组标准化均值差异（Cohen's d 的小样本无偏校正）。"""
    group_col, group_err = _resolve_group_col(req, "hypothesis_test")
    if group_err is not None:
        return group_err
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=["Hedges g 需要恰好 2 个分组"],
        )
    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()
    g1, n_inf1 = drop_non_finite(g1)
    g2, n_inf2 = drop_non_finite(g2)
    if len(g1) < 3 or len(g2) < 3:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[f"每组至少需要 3 个有效数据，当前 g1={len(g1)}, g2={len(g2)}"],
        )
    warn_list: list[str] = []
    warn_list.extend(non_finite_note(n, req.target_col) for n in (n_inf1, n_inf2) if n)
    d = _cohens_d(g1.values, g2.values, warn_list)
    ci = _cohens_d_ci(d, len(g1), len(g2))
    label = _effect_size_label(abs(d), "cohens_d")
    test_name = f"效应量 Hedges g ({groups[0]} vs {groups[1]})"
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    ax.hist(
        g1,
        bins=20,
        alpha=0.6,
        color=PALETTE["data"]["secondary"],
        density=True,
        label=str(groups[0]),
    )
    ax.hist(
        g2, bins=20, alpha=0.6, color=PALETTE["contrast"]["b"], density=True, label=str(groups[1])
    )
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_title(f"{test_name} (d={d:.3f}, {label})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "效应量(d)": [f"{d:.4f}"],
                    "95%CI": [f"[{ci[0]:.4f}, {ci[1]:.4f}]"],
                    "效应量解读": [label],
                    "样本量": [f"g1={len(g1)}, g2={len(g2)}"],
                }
            )
        },
        figures=[fig],
        summary=f"Hedges g={d:.3f} ({label})，95%CI=[{ci[0]:.3f}, {ci[1]:.3f}]",
        metadata={
            "test": test_name,
            "statistic": float(d),
            "p_value": None,  # 纯效应量，不检验
            "effect_size": float(d),
            "effect_name": "Hedges g",
            "effect_label": label,
            "effect_size_ci": (float(ci[0]), float(ci[1])),
            "n1": len(g1),
            "n2": len(g2),
        },
        messages=warn_list,
    )


def _ht_correlation(req: AnalysisRequest) -> AnalysisResult:
    """相关显著性检验 — 检验 target_col 与 feature_cols[0] 的 Pearson 相关。"""
    feat_cols = [c for c in req.feature_cols if c in req.data.columns]
    if not feat_cols:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=["相关显著性检验需要 1 个因子列（与目标列配对计算 Pearson 相关）"],
        )
    x_col = feat_cols[0]
    sub = req.data[[req.target_col, x_col]].dropna()
    sub, n_inf = drop_non_finite_rows(sub, [req.target_col, x_col])
    inf_msgs = [non_finite_note(n_inf)] if n_inf else []
    if len(sub) < 3:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[f"有效数据不足(至少3对完整观测)，当前 {len(sub)} 对"],
        )
    x = sub[x_col].values
    y = sub[req.target_col].values
    # 审查 2026-09-16 D-2：原绝对 EPSILON 把微尺度变量误判常量列；改精确零判据
    if np.std(x, ddof=1) == 0 or np.std(y, ddof=1) == 0:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=["相关显著性检验需要两个变量均有变异（常量列无法计算相关系数）"],
        )
    r_val, p_val = sp_stats.pearsonr(x, y)
    ci = _correlation_ci(r_val, len(sub))
    label = _effect_size_label(abs(r_val), "correlation")
    test_name = f"相关显著性检验 ({req.target_col} vs {x_col})"
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    conclusion = "存在显著相关" if p_val < alpha else "未发现显著相关"
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    ax.scatter(x, y, s=20, alpha=0.7, color=PALETTE["data"]["primary"])
    ax.set_xlabel(x_col, fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(f"{test_name} (r={r_val:.3f}, p={p_val:.4f})", fontsize=11)
    fig.tight_layout()
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "相关系数(r)": [f"{r_val:.4f}"],
                    "p值": [f"{p_val:.4f}"],
                    "显著性水平": [str(alpha)],
                    "95%CI": [f"[{ci[0]:.4f}, {ci[1]:.4f}]"],
                    "效应量解读": [label],
                    "样本量": [str(len(sub))],
                    "结论": [conclusion],
                }
            )
        },
        figures=[fig],
        summary=f"相关显著性: {conclusion} (r={r_val:.3f}, p={p_val:.4f}, n={len(sub)})",
        metadata={
            "test": test_name,
            "statistic": float(r_val),
            "p_value": float(p_val),
            "alpha": alpha,
            "effect_size": float(r_val),
            "effect_name": "Pearson r",
            "effect_label": label,
            "effect_size_ci": (float(ci[0]), float(ci[1])),
            "n": len(sub),
        },
        messages=inf_msgs,
    )


_HYPOTHESIS_DISPATCH = {
    "cochran_q": _ht_cochran_q,
    "ks": _ht_ks,
    "friedman": _ht_friedman,
    "cohens_d": _ht_cohens_d,
    "correlation": _ht_correlation,
}


# Round-2 #A2d：合法 test_type 白名单（此前未知类型静默落入独立双样本分支）
_HYPOTHESIS_TEST_TYPES = {
    "ttest_ind",
    "ttest_1samp",
    "ttest_paired",
    "wilcoxon_1samp",
    "wilcoxon_paired",
    "mannwhitney",
    "kruskal_wallis",
    "kruskal",
    "jonckheere",
    "mcnemar",
    "mann_kendall",
    "auto",
    "cochran_q",
    "ks",
    "friedman",
    "cohens_d",
    "correlation",
}


def _wilcoxon_rank_r(diff, direction: float) -> float:
    """Wilcoxon 符号秩检验的秩相关效应量 r = |Z| / √n_eff（符号取差值中位数方向）。

    审查 2026-09-21 B-3（P2）：原实现由 p 反推 Z
    （`z = norm.ppf(1 - max(p, EPSILON)/2)`），两处失真：
    ① `EPSILON = 1e-10` 下限把 Z 钳在 6.467，强效应被系统性压小；
    ② 分母用全样本量 n（含被丢弃的零差）而非有效对数 n_eff，进一步低估。
    实测「全部正差、互不相同」（最大效应）下原实现给出
    n=100 → 0.457、n=1000 → 0.145 —— 随 n 增大而**衰减**，
    而渐近真值为 √3/2 ≈ 0.866（与 n 无关）。

    改用 scipy 的渐近 Z（`method="approx"` 是 `"asymptotic"` 的向后兼容别名，
    跨 scipy 1.10 可用）。已验证：无并列无零差时该 Z 与教科书正态近似公式
    逐位一致（实测 n=100/400/1000 → 8.6818/17.3313/27.3930）。
    """
    diff_arr = np.asarray(diff, dtype=float)
    diff_arr = diff_arr[np.isfinite(diff_arr)]
    n_eff = int(np.count_nonzero(diff_arr))  # 默认 zero_method="wilcox" 丢弃零差
    if n_eff < 5:
        return float("nan")
    z = abs(float(sp_stats.wilcoxon(diff_arr, method="approx").zstatistic))
    if not np.isfinite(z):
        return float("nan")
    r = min(z / np.sqrt(n_eff), 1.0)
    return float(r if direction >= 0 else -r)


def hypothesis_test(req: AnalysisRequest) -> AnalysisResult:
    """假设检验：独立样本、配对样本、单样本 t 检验 / Mann-Whitney U，含效应量。"""
    test_type = req.params.get("test", "ttest_ind")
    if not isinstance(test_type, str) or test_type not in _HYPOTHESIS_TEST_TYPES:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[
                f"不支持的检验类型: {test_type!r}，可选: "
                + ", ".join(sorted(_HYPOTHESIS_TEST_TYPES))
            ],
        )

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    if not 0 < alpha < 1:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[
                f"alpha 必须在 (0,1) 区间内，当前: {alpha!r}（越界会使检验结论恒显著或恒不显著）"
            ],
        )

    # 调度到独立分支函数（新增检验类型只需在 _HYPOTHESIS_DISPATCH 注册）
    if test_type in _HYPOTHESIS_DISPATCH:
        return _HYPOTHESIS_DISPATCH[test_type](req)

    # ── 单样本检验 ──
    if test_type == "ttest_1samp":
        data = req.data[req.target_col].dropna()
        data, n_inf = drop_non_finite(data)
        inf_msgs = [non_finite_note(n_inf, req.target_col)] if n_inf else []
        popmean = _safe_float(req.params.get("popmean", 0), 0.0)
        if len(data) < 3:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效数据不足(至少3个点)"]
            )

        stat, p = sp_stats.ttest_1samp(data, popmean)
        test_name = f"单样本 t 检验 (H0: mu={popmean})"
        # 审查 2026-09-16 D-2：原分母 `std+EPSILON` 稀释微尺度 d（~1000×）；
        # d 为量纲无关比值，std 精确为 0 时不可估计 → NaN（标签走 N/A）
        _std_1s = float(data.std(ddof=1))
        d = (float(data.mean()) - popmean) / _std_1s if _std_1s > 0 else float("nan")
        effect_size = float(d)
        effect_name = "Cohen's d (单样本)"
        effect_label = _effect_size_label(abs(d), "cohens_d")
        desc_df = pd.DataFrame(
            {
                "统计量": ["样本量", "均值", "标准差", "标准误", "H0均值"],
                "值": [
                    str(len(data)),
                    f"{data.mean():.4f}",
                    f"{data.std(ddof=1):.4f}",
                    f"{data.sem():.4f}",
                    str(popmean),
                ],
            }
        )

        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = f"显著偏离 {popmean}" if p < alpha else f"未显著偏离 {popmean}"

        fig = Figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        ax.hist(
            data,
            bins=min(20, len(data) // 2),
            color=PALETTE["data"]["secondary"],
            edgecolor="white",
            alpha=0.8,
        )
        mean_val = float(data.mean())
        ax.axvline(
            mean_val, color=PALETTE["data"]["primary"], linewidth=2, label=f"μ={mean_val:.3f}"
        )
        ax.axvline(
            popmean,
            color=PALETTE["target"]["primary"],
            linestyle="--",
            linewidth=2,
            label=f"H0={popmean}",
        )
        # 95% CI
        ci = sp_stats.t.interval(0.95, len(data) - 1, loc=mean_val, scale=data.sem())
        ax.axvspan(ci[0], ci[1], alpha=0.1, color=PALETTE["data"]["primary"], label="95%CI")
        ax.set_xlabel(req.target_col, fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量": [f"{stat:.4f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量": [f"{effect_name}={effect_size:.3f}"],
                        "效应量解读": [effect_label],
                        "结论": [conclusion],
                    }
                ),
                "descriptive_stats": desc_df,
            },
            figures=[fig],
            summary=f"单样本检验: {conclusion} (p={p:.4f}, d={effect_size:.3f}, {effect_label})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "popmean": popmean,
                "effect_name": effect_name,
                "effect_label": effect_label,
                "effect_size_ci": _cohens_d_ci(effect_size, len(data), len(data), paired=True),
            },
            messages=inf_msgs,
        )

    # ── 配对检验 ──
    if test_type == "ttest_paired":
        # 配对检验：使用两个 feature_cols 作为配对的列
        if len(req.feature_cols) < 2:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=["配对检验需要 2 个特征列（前后测量）"],
            )
        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        sub, n_inf = drop_non_finite_rows(sub, [col1, col2])
        inf_msgs = [non_finite_note(n_inf)] if n_inf else []
        if len(sub) < 3:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效配对数据不足(至少3对)"]
            )

        stat, p = sp_stats.ttest_rel(sub[col1], sub[col2])
        test_name = f"配对 t 检验 ({col1} vs {col2})"
        diff = sub[col1].values - sub[col2].values
        # 配对 Cohen's d: mean(diff) / sd(diff)
        # 审查 2026-09-16 D-2：同单样本——去掉 +EPSILON 绝对稀释，精确零/非有限除外
        _sd_diff = float(np.std(diff, ddof=1))
        d_val = float(np.mean(diff)) / _sd_diff if _sd_diff > 0 else float("nan")
        effect_size = d_val
        effect_name = "Cohen's d (配对)"
        effect_label = _effect_size_label(abs(d_val), "cohens_d")

        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = "前后存在显著差异" if p < alpha else "前后未发现显著差异"

        desc_df = pd.DataFrame(
            {
                "统计量": [
                    "配对对数",
                    f"{col1}均值",
                    f"{col2}均值",
                    "差值均值",
                    "差值标准差",
                    "差值标准误",
                ],
                "值": [
                    str(len(sub)),
                    f"{sub[col1].mean():.4f}",
                    f"{sub[col2].mean():.4f}",
                    f"{diff.mean():.4f}",
                    f"{diff.std(ddof=1):.4f}",
                    f"{sp_stats.sem(diff):.4f}",
                ],
            }
        )

        # 配对图：前后连线
        fig = Figure(figsize=(6, 4.5))
        ax = fig.add_subplot(111)
        x_pos = np.arange(len(sub))
        ax.plot(
            x_pos,
            sub[col1].values,
            "o-",
            markersize=4,
            color=PALETTE["data"]["secondary"],
            label=col1,
        )
        ax.plot(
            x_pos, sub[col2].values, "s-", markersize=4, color=PALETTE["contrast"]["b"], label=col2
        )
        for i in range(len(sub)):
            ax.plot(
                [i, i],
                [sub[col1].iloc[i], sub[col2].iloc[i]],
                "-",
                color=PALETTE["spec"]["tertiary"],
                alpha=0.4,
                linewidth=0.8,
            )
        ax.set_xlabel("配对序号", fontsize=10)
        ax.set_ylabel("值", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, d={d_val:.3f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量": [f"{stat:.4f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量": [f"{effect_name}={effect_size:.3f}"],
                        "效应量解读": [effect_label],
                        "结论": [conclusion],
                    }
                ),
                "descriptive_stats": desc_df,
            },
            figures=[fig],
            summary=f"配对检验: {conclusion} (p={p:.4f}, d={d_val:.3f}, {effect_label})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "n_pairs": len(sub),
                "effect_name": effect_name,
                "effect_label": effect_label,
                "effect_size_ci": _cohens_d_ci(effect_size, len(sub), len(sub), paired=True),
            },
            messages=inf_msgs,
        )

    # ── 单样本 Wilcoxon 符号秩检验 ──
    if test_type == "wilcoxon_1samp":
        data = req.data[req.target_col].dropna()
        data, n_inf = drop_non_finite(data)
        inf_msgs = [non_finite_note(n_inf, req.target_col)] if n_inf else []
        popmedian = _safe_float(req.params.get("popmedian", 0), 0.0)
        if len(data) < 5:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效数据不足(至少5个点)"]
            )

        # Wilcoxon 符号秩检验 (双边): 检验中位数是否等于 popmedian
        stat, p = sp_stats.wilcoxon(data.values - popmedian)
        test_name = f"单样本 Wilcoxon 检验 (H0: 中位数={popmedian})"
        n = len(data)
        r_effect = _wilcoxon_rank_r(
            data.values - popmedian, float(np.median(data.values) - popmedian)
        )
        effect_size = r_effect
        effect_name = "秩相关 r"
        effect_label = _effect_size_label(r_effect, "correlation")

        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = f"中位数显著偏离 {popmedian}" if p < alpha else f"中位数未显著偏离 {popmedian}"

        fig = Figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        ax.hist(
            data,
            bins=min(20, n // 2),
            color=PALETTE["data"]["secondary"],
            edgecolor="white",
            alpha=0.8,
        )
        ax.axvline(
            np.median(data),
            color=PALETTE["data"]["primary"],
            linewidth=2,
            label=f"中位数={np.median(data):.3f}",
        )
        ax.axvline(
            popmedian,
            color=PALETTE["target"]["primary"],
            linestyle="--",
            linewidth=2,
            label=f"H0={popmedian}",
        )
        ax.set_xlabel(req.target_col, fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量": [f"{stat:.1f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量": [f"{effect_name}={effect_size:.3f}"],
                        "效应量解读": [effect_label],
                        "结论": [conclusion],
                    }
                ),
                "descriptive_stats": pd.DataFrame(
                    {
                        "统计量": ["样本量", "中位数", "IQR", "H0中位数", "高于H0数", "低于H0数"],
                        "值": [
                            str(n),
                            f"{data.median():.4f}",
                            f"{data.quantile(0.75) - data.quantile(0.25):.4f}",
                            str(popmedian),
                            str(int((data > popmedian).sum())),
                            str(int((data < popmedian).sum())),
                        ],
                    }
                ),
            },
            figures=[fig],
            summary=f"单样本Wilcoxon: {conclusion} (p={p:.4f}, r={r_effect:.3f})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "popmedian": popmedian,
            },
            messages=inf_msgs,
        )

    # ── Kruskal-Wallis H 检验 (非参数 ANOVA) ──
    if test_type in ("kruskal_wallis", "kruskal"):
        group_col, group_err = _resolve_group_col(req, "hypothesis_test")
        if group_err is not None:
            return group_err
        sub = req.data[[req.target_col, group_col]].dropna()
        sub, n_inf = drop_non_finite_rows(sub, [req.target_col])
        inf_msgs = [non_finite_note(n_inf, req.target_col)] if n_inf else []
        groups = sub[group_col].unique()
        # Round-2 #A2e：无分组列时回退到连续特征列 → 每观测一组、η²_H=1.000 误导
        if len(groups) > 20:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=[
                    f"分组列「{group_col}」水平数过多（{len(groups)} 个，上限 20），"
                    "可能是连续变量被当作分组。请指定有效的分组列。"
                ],
            )
        if any((sub[group_col] == g).sum() < 3 for g in groups):
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=[
                    "存在样本量小于 3 的分组，Kruskal-Wallis 结果不可靠。请检查分组列或增加数据量。"
                ],
            )
        if len(groups) < 2:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["至少需要 2 个分组"]
            )

        group_data = [sub[sub[group_col] == g][req.target_col].values for g in groups]
        stat, p = sp_stats.kruskal(*group_data)
        test_name = "Kruskal-Wallis H 检验 (非参数 ANOVA)"
        n_total = len(sub)
        # 效应量: η²_H = H / (N-1) 近似
        eta2_h = min(float(stat / (n_total - 1)), 1.0) if n_total > 1 else 0.0
        effect_size = eta2_h
        effect_name = "η²_H"
        effect_label = _effect_interpretation(eta2_h)

        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = "组间存在显著差异" if p < alpha else "未发现组间显著差异"

        fig = Figure(figsize=(max(len(groups) * 1.5, 5), 4))
        ax = fig.add_subplot(111)
        bp = ax.boxplot(
            group_data, tick_labels=[str(g) for g in groups], patch_artist=True, widths=0.5
        )
        if len(groups) > 6:
            for label in ax.get_xticklabels():
                label.set_rotation(30)
                label.set_horizontalalignment("right")
        ax.tick_params(labelsize=9)
        for patch in bp["boxes"]:
            patch.set_facecolor(PALETTE["data"]["secondary"])
        assert group_col is not None  # 分组检验路径必有分组列
        ax.set_xlabel(group_col, fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        ax.set_title(f"{test_name} (H={stat:.2f}, p={p:.4f})", fontsize=11)
        fig.tight_layout()

        # ── Dunn 事后多重比较 ──
        tables = {
            "test_results": pd.DataFrame(
                {
                    "检验方法": [test_name],
                    "统计量(H)": [f"{stat:.3f}"],
                    "p值": [f"{p:.4f}"],
                    "显著性水平": [str(alpha)],
                    "效应量": [f"{effect_name}={effect_size:.3f}"],
                    "效应量解读": [effect_label],
                    "结论": [conclusion],
                }
            ),
        }
        if p < alpha and len(groups) >= 3:
            # Dunn 检验：基于秩和的成对比较
            from itertools import combinations

            all_vals = np.concatenate(group_data)
            ranks = sp_stats.rankdata(all_vals)
            _, tie_counts = np.unique(ranks, return_counts=True)
            rank_sums = {}
            start = 0
            for g, gd in zip(groups, group_data, strict=True):
                rank_sums[g] = np.sum(ranks[start : start + len(gd)])
                start += len(gd)

            dunn_rows = []
            n_comparisons = len(groups) * (len(groups) - 1) // 2
            for g1, g2 in combinations(groups, 2):
                n1, n2 = (
                    len(group_data[list(groups).index(g1)]),
                    len(group_data[list(groups).index(g2)]),
                )
                z_num = abs(rank_sums[g1] / n1 - rank_sums[g2] / n2)
                N = len(all_vals)
                tie_corr = np.sum(tie_counts**3 - tie_counts) / (12 * (N - 1)) if N > 1 else 0
                # P2 fix: tie_corr 在大量结值时可能使方差估计变负，钳位到非负
                z_denom = np.sqrt(
                    max(0.0, (N * (N + 1) / 12) - tie_corr) * (1 / n1 + 1 / n2) + EPSILON
                )
                z_stat_dunn = z_num / (z_denom + EPSILON)
                p_dunn = float(2 * sp_stats.norm.sf(abs(z_stat_dunn)))
                # Bonferroni 校正
                p_adj = min(p_dunn * n_comparisons, 1.0)
                dunn_rows.append(
                    {
                        "对比": f"{g1} vs {g2}",
                        "Z值": round_for_display(float(z_stat_dunn), 3),
                        "原始p值": round_for_display(float(p_dunn), 4),
                        "校正p值": round_for_display(float(p_adj), 4),
                        "显著": "是" if p_adj < alpha else "否",
                    }
                )
            tables["posthoc_dunn"] = pd.DataFrame(dunn_rows)

        return AnalysisResult(
            task="hypothesis_test",
            tables=tables,
            figures=[fig],
            summary=f"Kruskal-Wallis: {conclusion} (H={stat:.2f}, p={p:.4f}, η²_H={eta2_h:.3f})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "n_groups": len(groups),
            },
            messages=inf_msgs,
        )

    # ── McNemar 检验 (配对二分类数据) ──
    if test_type == "mcnemar":
        if len(req.feature_cols) < 2:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=["McNemar 检验需要 2 个特征列 (前后二分类测量)"],
            )

        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        if len(sub) < 5:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效配对数据不足(至少5对)"]
            )

        # 构建 2×2 列联表
        vals1 = sub[col1].values
        vals2 = sub[col2].values
        # 自动二值化
        unique_vals = np.unique(np.concatenate([vals1, vals2]))
        if len(unique_vals) != 2:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=[
                    f"McNemar 检验需要二分类数据 (每列恰好 2 个不同值)，当前有 {len(unique_vals)} 个"
                ],
            )

        # 保留原始类型进行比较，避免 str() 导致数值型二值数据 (0/1) 比较失败
        pos = unique_vals[1]
        neg = unique_vals[0]

        a = int(((vals1 == pos) & (vals2 == pos)).sum())  # 都为正
        b = int(((vals1 == pos) & (vals2 == neg)).sum())  # 前正后负
        c = int(((vals1 == neg) & (vals2 == pos)).sum())  # 前负后正
        d = int(((vals1 == neg) & (vals2 == neg)).sum())  # 都为负

        # McNemar 检验
        # 小样本 (b+c < 25) 使用 Yates 连续性校正，大样本不做校正
        bc_sum = b + c
        mcnemar_warns: list[str] = []
        if bc_sum > 0:
            if bc_sum < 25:
                stat = (abs(b - c) - 1) ** 2 / bc_sum
                test_name_suffix = " (Yates校正)"
                # 逐公式审计 2026-09-05 约定#1：不一致对较少时 Yates χ² 仍近似偏激进
                mcnemar_warns.append(
                    f"⚠ 配对不一致数 (b+c={bc_sum}) 较小，Yates 校正 χ² 的 p 值可能欠准确，"
                    f"建议用精确二项检验复核：binomtest(min({b},{c}), {bc_sum}, 0.5)"
                )
            else:
                stat = (b - c) ** 2 / bc_sum
                test_name_suffix = ""
        else:
            stat = 0
            test_name_suffix = ""
        p = float(sp_stats.chi2.sf(stat, 1))

        test_name = f"McNemar 检验 ({col1} → {col2}){test_name_suffix}"
        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = "前后存在显著变化" if p < alpha else "前后未发现显著变化"
        # Odds Ratio = b/c（保留原始值，不做截断）
        # 审查 2026-09-21 B-5：原 `b / (c + EPSILON)` 有两处失真——
        # ① c=0 时给出**伪有限值**（b=30 → OR=3e11，还被写进 summary 与图表标题），
        #    使 metadata 里 `np.isinf(or_val)` 守卫成为死代码；
        # ② c>0 时引入 1e-10 级假精度（b=10,c=2 → 4.99999999975）。
        # 按定义处理：OR=b/c 在 c=0 时为∞、b=c=0 时未定义，两者一律给 None。
        or_val: float | None
        or_text: str
        if b == 0 and c == 0:
            or_val, or_text = None, "无法计算（无不一致对 b=c=0）"
        elif c == 0:
            or_val, or_text = None, "∞（c=0，无反向变化对）"
        else:
            or_val = b / c
            or_text = f"{or_val:.2f}"

        # 可视化：前后对比堆叠柱状图
        fig = Figure(figsize=(5, 4))
        ax = fig.add_subplot(111)
        categories = [f"{neg}→{neg}", f"{neg}→{pos}", f"{pos}→{neg}", f"{pos}→{pos}"]
        counts = [d, c, b, a]
        ax.bar(
            categories,
            counts,
            color=[
                PALETTE["data"]["tertiary"],
                PALETTE["data"]["primary"],
                PALETTE["target"]["primary"],
                PALETTE["data"]["secondary"],
            ],
            edgecolor="white",
        )
        for i, (_cat, cnt) in enumerate(zip(categories, counts, strict=True)):
            ax.text(i, cnt + max(counts) * 0.02, str(cnt), ha="center", fontsize=9)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, OR={or_text})", fontsize=10)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            messages=mcnemar_warns,
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量(χ²)": [f"{stat:.3f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量(OR)": [or_text],
                        "结论": [conclusion],
                    }
                ),
                "contingency_2x2": pd.DataFrame(
                    {
                        f"{col2}={neg}": [d, b],
                        f"{col2}={pos}": [c, a],
                    },
                    index=[f"{col1}={neg}", f"{col1}={pos}"],
                ),
            },
            figures=[fig],
            summary=f"McNemar: {conclusion} (χ²={stat:.2f}, p={p:.4f}, OR=b/c={or_text})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "odds_ratio": or_val,
                "n_pairs": len(sub),
                "discordant_pairs": b + c,
            },
        )

    # ── Mann-Kendall 趋势检验 ──
    if test_type == "mann_kendall":
        data = req.data[req.target_col].dropna()
        data, n_inf = drop_non_finite(data)
        inf_msgs = [non_finite_note(n_inf, req.target_col)] if n_inf else []
        n = len(data)
        if n < 4:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效数据不足(至少4个点)"]
            )

        # MK 统计量: 使用 scipy kendalltau (τ-B) 计算 p 值（已正确处理结）
        vals = data.values
        tau_mk, p = sp_stats.kendalltau(np.arange(n), vals)
        # 从 τ-B 反推 S：τ-B = S / sqrt(n0*(n0-n2)) → 考虑 y 方向结校正
        n0 = n * (n - 1) / 2
        _, tie_counts = np.unique(vals, return_counts=True)
        n_ties = np.sum(tie_counts * (tie_counts - 1) / 2)  # y 方向结校正
        S = int(round(tau_mk * np.sqrt(max(n0 * (n0 - n_ties), 1.0))))
        effect_size = float(tau_mk)
        # 从 p 值反推近似 Z（用于展示）
        p_safe = max(
            p, EPSILON
        )  # protect against p=0 causing ppf(1.0)=inf (EPSILON keeps z≤6.47 finite)
        z_mk = float(sp_stats.norm.ppf(1 - p_safe / 2)) * np.sign(S) if p < 1.0 else 0.0

        test_name = "Mann-Kendall 趋势检验"
        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        trend_dir = "上升趋势" if S > 0 else "下降趋势" if S < 0 else "无趋势"
        conclusion = f"存在显著{trend_dir}" if p < alpha else "未发现显著趋势"

        fig = Figure(figsize=(8, 4))
        ax = fig.add_subplot(111)
        ax.plot(range(n), vals, "o-", markersize=3, color=PALETTE["data"]["primary"], linewidth=1)
        # 简单趋势线
        z_poly = np.polyfit(range(n), vals, 1)
        ax.plot(
            range(n),
            np.polyval(z_poly, range(n)),
            "-",
            color=PALETTE["target"]["primary"],
            linewidth=2,
            alpha=0.7,
            label=f"线性趋势 (τ={tau_mk:.3f})",
        )
        ax.set_xlabel("时间序号", fontsize=10)
        ax.set_ylabel(req.target_col, fontsize=10)
        ax.set_title(f"{test_name} (S={S}, p={p:.4f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "S统计量": [str(S)],
                        "Z值": [f"{z_mk:.3f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "Kendall τ": [f"{tau_mk:.4f}"],
                        "结论": [conclusion],
                    }
                )
            },
            figures=[fig],
            summary=f"Mann-Kendall: {conclusion} (τ={tau_mk:.3f}, p={p:.4f})",
            metadata={
                "test": test_name,
                "S": int(S),
                "z": float(z_mk),
                "p_value": float(p),
                "tau": float(tau_mk),
                "alpha": alpha,
            },
            messages=inf_msgs,
        )

    # ── Jonckheere-Terpstra 趋势检验 ──
    if test_type == "jonckheere":
        group_col, group_err = _resolve_group_col(req, "hypothesis_test")
        if group_err is not None:
            return group_err
        sub = req.data[[req.target_col, group_col]].dropna()
        sub, n_inf = drop_non_finite_rows(sub, [req.target_col])
        inf_msgs = [non_finite_note(n_inf, req.target_col)] if n_inf else []
        groups = sub[group_col].unique()
        # Round-2 #A2e：同 kruskal——连续列回退产生伪分组
        if len(groups) > 20:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=[
                    f"分组列「{group_col}」水平数过多（{len(groups)} 个，上限 20），"
                    "可能是连续变量被当作分组。请指定有效的分组列。"
                ],
            )
        if len(groups) < 3:
            return AnalysisResult(
                task="hypothesis_test",
                status="error",
                messages=["Jonckheere-Terpstra 需要至少 3 个有序分组"],
            )
        # 转换分组为有序秩次
        group_order = {g: i for i, g in enumerate(groups)}
        sub_ordered = sub.copy()
        sub_ordered["_order"] = sub[group_col].map(group_order)
        sub_sorted = sub_ordered.sort_values("_order")
        group_data_ordered = [
            sub_sorted[sub_sorted["_order"] == i][req.target_col].values for i in range(len(groups))
        ]

        # JT 统计量: 标准 Jonckheere-Terpstra = Σ_{i<j} U_{ij}
        # U_{ij} = #{(x∈gi, y∈gj) | x < y}（Mann-Whitney 统计量）
        # 使用向量化 searchsorted（O(n log n)），与 _cliffs_delta 相同算法
        JT = 0
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                gi, gj = group_data_ordered[i], group_data_ordered[j]
                y_sorted = np.sort(gj)
                # le_count: gj 中小于等于各 gi 元素的数量
                le_count = int(np.sum(np.searchsorted(y_sorted, gi, side="right")))
                # U_{ij} = n_i * n_j - le_count = #(x < y)
                JT += len(gi) * len(gj) - le_count

        # 正态近似
        n_total = sum(len(g) for g in group_data_ordered)
        n_i = np.array([len(g) for g in group_data_ordered])
        E_JT = (n_total**2 - np.sum(n_i**2)) / 4
        V_JT = (n_total**2 * (2 * n_total + 3) - np.sum(n_i**2 * (2 * n_i + 3))) / 72
        # 结校正：对所有组的值合并后统一计算，每个结值的校正项按其总出现次数计算
        # （正确做法是按跨组总频数计算，而非按每个组内分别计算）
        all_vals_flat = np.concatenate(group_data_ordered)
        _, counts_all = np.unique(all_vals_flat, return_counts=True)
        ties_all = counts_all[counts_all >= 2]
        V_JT -= np.sum(ties_all * (ties_all - 1) * (2 * ties_all + 5)) / 72
        z_JT = (JT - E_JT) / np.sqrt(max(V_JT, EPSILON))
        p = float(2 * sp_stats.norm.sf(abs(z_JT)))

        test_name = "Jonckheere-Terpstra 趋势检验"
        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        trend_dir = "递增趋势" if z_JT > 0 else "递减趋势"
        conclusion = f"存在显著{trend_dir}" if p < alpha else "未发现显著趋势"

        # Kendall's tau-b 效应量近似
        tau_b = 4 * JT / (n_total**2 - np.sum(n_i**2) + EPSILON) - 1
        effect_size = float(tau_b)
        effect_label = _effect_size_label(abs(tau_b), "correlation")

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量(JT)": [str(JT)],
                        "Z值": [f"{z_JT:.3f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量(τ)": [f"{tau_b:.3f}"],
                        "结论": [conclusion],
                    }
                )
            },
            summary=f"Jonckheere-Terpstra: {conclusion} (Z={z_JT:.2f}, p={p:.4f}, τ={tau_b:.3f})",
            metadata={
                "test": test_name,
                "statistic": float(JT),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "z": float(z_JT),
            },
            messages=inf_msgs,
        )

    # ── 配对 Wilcoxon 符号秩检验 ──
    if test_type == "wilcoxon_paired":
        if len(req.feature_cols) < 2:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["配对检验需要 2 个特征列"]
            )
        col1, col2 = req.feature_cols[0], req.feature_cols[1]
        sub = req.data[[col1, col2]].dropna()
        sub, n_inf = drop_non_finite_rows(sub, [col1, col2])
        inf_msgs = [non_finite_note(n_inf)] if n_inf else []
        if len(sub) < 5:
            return AnalysisResult(
                task="hypothesis_test", status="error", messages=["有效配对数据不足(至少5对)"]
            )

        # Wilcoxon 符号秩检验
        stat, p = sp_stats.wilcoxon(sub[col1], sub[col2])
        test_name = f"Wilcoxon 符号秩检验 ({col1} vs {col2})"
        diff = sub[col1].values - sub[col2].values
        n_pairs = len(sub)
        r_effect = _wilcoxon_rank_r(diff, float(np.median(diff)))
        effect_size = float(r_effect)
        effect_name = "匹配对秩相关 r"
        effect_label = _effect_size_label(r_effect, "correlation")

        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        conclusion = "前后存在显著差异" if p < alpha else "前后未发现显著差异"

        # 配对差值分布图
        fig = Figure(figsize=(7, 4.5))
        ax = fig.add_subplot(111)
        ax.hist(
            diff,
            bins=min(15, n_pairs // 2),
            color=PALETTE["data"]["secondary"],
            edgecolor="white",
            alpha=0.8,
        )
        ax.axvline(
            0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5, label="零差异线"
        )
        ax.axvline(
            np.median(diff),
            color=PALETTE["data"]["primary"],
            linewidth=2,
            label=f"中位数差={np.median(diff):.3f}",
        )
        ax.set_xlabel(f"{col1} - {col2}", fontsize=10)
        ax.set_ylabel("频数", fontsize=10)
        ax.set_title(f"{test_name} (p={p:.4f}, r={r_effect:.3f})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="hypothesis_test",
            tables={
                "test_results": pd.DataFrame(
                    {
                        "检验方法": [test_name],
                        "统计量": [f"{stat:.1f}"],
                        "p值": [f"{p:.4f}"],
                        "显著性水平": [str(alpha)],
                        "效应量": [f"{effect_name}={effect_size:.3f}"],
                        "效应量解读": [effect_label],
                        "结论": [conclusion],
                    }
                ),
                "descriptive_stats": pd.DataFrame(
                    {
                        "统计量": [
                            "配对对数",
                            f"{col1}中位数",
                            f"{col2}中位数",
                            "差值中位数",
                            "正差值对数",
                            "负差值对数",
                        ],
                        "值": [
                            str(n_pairs),
                            f"{sub[col1].median():.4f}",
                            f"{sub[col2].median():.4f}",
                            f"{np.median(diff):.4f}",
                            str(int((diff > 0).sum())),
                            str(int((diff < 0).sum())),
                        ],
                    }
                ),
            },
            figures=[fig],
            summary=f"Wilcoxon配对检验: {conclusion} (p={p:.4f}, r={r_effect:.3f}, {effect_label})",
            metadata={
                "test": test_name,
                "statistic": float(stat),
                "p_value": float(p),
                "alpha": alpha,
                "effect_size": effect_size,
                "n_pairs": n_pairs,
            },
            messages=inf_msgs,
        )

    # ── 独立双样本检验 ──
    # 显式检查 None + 列存在性：避免 DEFAULT_PARAMS 注入 None 阻断 fallback (P3 fix)
    group_col, group_err = _resolve_group_col(req, "hypothesis_test")
    if group_err is not None:
        return group_err
    groups = req.data[group_col].unique()
    if len(groups) != 2:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[f"分组列需要恰好 2 个水平，当前有 {len(groups)} 个"],
        )

    g1 = req.data[req.data[group_col] == groups[0]][req.target_col].dropna()
    g2 = req.data[req.data[group_col] == groups[1]][req.target_col].dropna()

    # 审查 2026-09-22 发现 2：±Inf 既非 NaN 也未被 dropna 剔除，scipy 对含 Inf
    # 数组返回 NaN p 值，而 `p < alpha` 对 NaN 恒 False → 被表述为「未发现显著差异」。
    # 入口按缺失处理剔除并显式提示（同一缺陷族：paired/mannwhitney/wilcoxon 已同修）。
    g1, n_inf1 = drop_non_finite(g1)
    g2, n_inf2 = drop_non_finite(g2)

    # 最小样本量检查 — 与其他分支保持一致 (P2-3 fix)
    min_n = 3
    if len(g1) < min_n or len(g2) < min_n:
        return AnalysisResult(
            task="hypothesis_test",
            status="error",
            messages=[f"每组至少需要 {min_n} 个有效数据，当前 g1={len(g1)}, g2={len(g2)}"],
        )

    # ── 自动选择参数/非参数检验 ──
    norm_warn: list[str] = []
    norm_warn.extend(non_finite_note(n, req.target_col) for n in (n_inf1, n_inf2) if n)
    sw1 = sw2 = 1.0  # 初始化为正态（用于 auto 分支中条件不满足时的回退）
    norm_already_checked = False
    if test_type == "auto":
        normal = True
        if len(g1) >= 3 and len(g2) >= 3 and len(g1) <= 5000 and len(g2) <= 5000:
            sw1 = shapiro_p(g1)
            sw2 = shapiro_p(g2)
            normal = min(sw1, sw2) >= 0.05
            norm_already_checked = True
        if normal:
            test_type = "ttest_ind"
        else:
            test_type = "mannwhitney"
            norm_warn.append(f"自动选择 Mann-Whitney U (正态性p={min(sw1, sw2):.4f}<0.05)")

    if not norm_already_checked and len(g1) >= 3 and len(g2) >= 3 and test_type != "mannwhitney":
        sw1 = shapiro_p(g1) if len(g1) <= 5000 else 1.0
        sw2 = shapiro_p(g2) if len(g2) <= 5000 else 1.0
        if min(sw1, sw2) < 0.05:
            norm_warn.append(f"正态性检验 p={min(sw1, sw2):.4f}<0.05，建议使用 Mann-Whitney U 检验")

    if test_type == "mannwhitney":
        stat, p = sp_stats.mannwhitneyu(g1, g2)
        test_name = "Mann-Whitney U 检验"
        effect_size = _cliffs_delta(g1.values, g2.values)
        effect_name = "Cliff's δ"
        effect_label = _effect_size_label(effect_size, "cliffs_delta")
    else:
        stat, p = sp_stats.ttest_ind(g1, g2)
        test_name = "独立样本 t 检验"
        effect_size = _cohens_d(g1.values, g2.values, norm_warn)
        # 逐公式审计 2026-09-05 瑕疵#8：_cohens_d 实际返回含小样本校正的 Hedges g
        # （J=1-3/(4N-9)），标签同步更正，避免统计口径误读
        effect_name = "Hedges g"
        effect_label = _effect_size_label(effect_size, "cohens_d")

    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    conclusion = "存在显著差异" if p < alpha else "未发现显著差异"

    # ── 统计功效估计 ──
    n1, n2 = len(g1), len(g2)
    # 非中心参数近似
    ncp = abs(effect_size) * sqrt(n1 * n2 / (n1 + n2)) if (n1 + n2) > 0 else 0
    dof = n1 + n2 - 2
    if test_type != "mannwhitney" and dof > 0:
        try:
            t_crit = sp_stats.t.ppf(1 - alpha / 2, dof)
            power = float(
                1 - sp_stats.nct.cdf(t_crit, dof, ncp) + sp_stats.nct.cdf(-t_crit, dof, ncp)
            )
        except Exception:
            logger.debug("统计功效计算失败", exc_info=True)
            power = None
    else:
        power = None

    # 双样本箱线图 + 散点叠加
    fig = Figure(figsize=(6, 4.5))
    ax = fig.add_subplot(111)
    bp = ax.boxplot(
        [g1, g2],
        tick_labels=[f"{groups[0]}\n(n={n1})", f"{groups[1]}\n(n={n2})"],
        patch_artist=True,
        widths=0.5,
    )
    for patch, color in zip(
        bp["boxes"], [PALETTE["data"]["secondary"], PALETTE["target"]["fill"]], strict=True
    ):
        patch.set_facecolor(color)
    # 叠加散点
    for i, gdata in enumerate([g1, g2], 1):
        # 可复现 jitter（种子基于组序号）
        jitter = np.random.default_rng(20260819 + i).uniform(-0.12, 0.12, len(gdata))
        ax.scatter(
            np.full(len(gdata), i) + jitter,
            gdata.values,
            alpha=0.35,
            s=12,
            color=PALETTE["misc"]["grid"],
            zorder=3,
        )
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"{test_name} — {req.target_col}\n"
        f"p={p:.4f} | {effect_name}={effect_size:.3f} ({effect_label})"
        + (f" | 功效={power:.1%}" if power else ""),
        fontsize=10,
    )
    fig.tight_layout()

    # ── 描述统计表 ──
    desc_df = pd.DataFrame(
        {
            "分组": [str(groups[0]), str(groups[1])],
            "样本量": [n1, n2],
            "均值": [float(g1.mean()), float(g2.mean())],
            "标准差": [float(g1.std(ddof=1)), float(g2.std(ddof=1))],
            "标准误": [float(g1.sem()), float(g2.sem())],
        }
    )

    result_table = pd.DataFrame(
        {
            "检验方法": [test_name],
            "统计量": [f"{stat:.4f}"],
            "p值": [f"{p:.4f}"],
            "显著性水平": [str(alpha)],
            "效应量": [f"{effect_name}={effect_size:.3f}"],
            "效应量解读": [effect_label],
            "统计功效": [f"{power:.1%}" if power is not None else "N/A"],
            "结论": [f"「{group_col}」: {groups[0]} vs {groups[1]} — {conclusion}"],
        }
    )

    summary_parts = [
        f"「{group_col}」中 {groups[0]} vs {groups[1]}: {conclusion} (p={p:.4f})",
        f"效应量 {effect_name}={effect_size:.3f}（{effect_label}）",
    ]
    if power is not None:
        summary_parts.append(f"统计功效 {power:.1%}")
    else:
        summary_parts.append("统计功效 N/A")

    # 审查 2026-09-21 B-1：Cliff's δ 是有界统计量（∈[-1,1]），而原实现无条件套用
    # Cohen's d 的标准误公式（_cohens_d_ci）→ 实测 CI 越出定义域：
    #   n=8 → δ=-0.9062 CI=(-1.9353, +0.1228)；n=20 → (-1.3912, -0.1088)。
    # δ 的 CI 需要其自身（支配矩阵）的方差分量，本仓无可核验的闭式公式，故**不猜测**：
    # 仅对 d 族（Hedges g，定义域无界）输出 CI；δ 显式标注为不可用。
    if test_type == "mannwhitney":
        effect_ci: tuple[float, float] | None = None
        effect_ci_note = "Cliff's δ 的置信区间不适用 Cohen's d 的标准误公式，本工具不输出该区间"
    else:
        effect_ci = _cohens_d_ci(effect_size, n1, n2)
        effect_ci_note = ""

    metadata: dict[str, object] = {
        "test": test_name,
        "statistic": float(stat),
        "p_value": float(p),
        "alpha": alpha,
        "effect_size": effect_size,
        "effect_name": effect_name,
        "effect_label": effect_label,
        "power": power,
        "effect_size_ci": effect_ci,
    }
    if effect_ci_note:
        metadata["effect_ci_note"] = effect_ci_note
    return AnalysisResult(
        task="hypothesis_test",
        tables={
            "test_results": result_table,
            "descriptive_stats": desc_df,
        },
        figures=[fig],
        summary="；".join(summary_parts),
        metadata=metadata,
        messages=norm_warn,
    )
