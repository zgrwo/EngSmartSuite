"""变化点检测（原 detection.py 的 change_point_detect，2026-09-21 拆分）。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE

logger = logging.getLogger(__name__)


def change_point_detect(req: AnalysisRequest) -> AnalysisResult:
    """变点检测 — 基于 CUSUM 的二元分割法，识别过程结构性变化。

    返回变点位置列表和分段统计。
    参数:
        min_segment: 最小段长度 (默认 10)
        n_changepoints: 最多检测的变点数 (默认 5)
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 20:
        return AnalysisResult(
            task="change_point",
            status="error",
            messages=["有效数据不足(至少20个点)"],
        )

    _def_ms = min(max(10, n // 20), (n - 1) // 2)  # 保证 2*min_segment < n（n=20 时默认 9 而非 10）
    min_segment = req.params.get("min_segment", _def_ms)
    max_cp = req.params.get("n_changepoints", 5)
    # 标准化峰值阈值（审查 2026-08-19 #2.6）：CUSUM 统计量量纲为 σ√L，
    # 与单点量纲的 data_range 比较是量纲错误；改为与 σ√L 比较。
    # 噪声下 max|W(t)|（布朗桥最大值）期望 ≈1.2，默认 2.0 对应每段约 5% 误报率。
    min_peak_ratio = req.params.get("min_peak_ratio", 2.0)

    # 参数类型安全转换 (CLI/YAML 传入字符串时防护)
    try:
        min_segment = int(min_segment)
        max_cp = int(max_cp)
        min_peak_ratio = float(min_peak_ratio)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="change_point",
            status="error",
            messages=[
                "变点检测参数格式错误：min_segment 和 n_changepoints 需为整数，"
                "min_peak_ratio 需为数值"
            ],
        )

    # 参数范围校验（审查 2026-08-19 #1.3）
    if min_segment < 1:
        return AnalysisResult(
            task="change_point",
            status="error",
            messages=[f"min_segment 必须 ≥ 1，当前: {min_segment}"],
        )
    # Round-2 #A2q：2*min_segment >= n 时搜索区间为空（[ms, n-ms] 无位置）
    # → 静默无变点；边界用 >=
    if min_segment * 2 >= n:
        return AnalysisResult(
            task="change_point",
            status="error",
            messages=[
                f"min_segment({min_segment}) 过大（2×min_segment > n={n}），无法在段内搜索变点"
            ],
        )

    values = data.values
    changepoints: list[int] = []
    segments_for_split = [(0, n)]

    # 二元分割：每次在段内找标准化 CUSUM 峰值最大的位置
    while len(changepoints) < max_cp and segments_for_split:
        best_cp = None
        best_stat_norm = 0.0
        best_seg_idx = -1

        for seg_i, (start, end) in enumerate(segments_for_split):
            seg_len = end - start
            if seg_len < 2 * min_segment:
                continue
            seg_vals = values[start:end]
            # 常量段无变点可检测，跳过（避免 σ=0 除零）
            seg_std = float(np.std(seg_vals, ddof=1)) if len(seg_vals) >= 2 else 0.0
            if seg_std <= 0:
                continue
            seg_mean = np.mean(seg_vals)
            # CUSUM 统计量
            cumsum = np.cumsum(seg_vals - seg_mean)
            cusum_abs = np.abs(cumsum)
            # 限制搜索范围在 min_segment ~ seg_len-min_segment 之间
            search_start = min_segment
            search_end = seg_len - min_segment
            if search_end <= search_start:
                continue
            peak_idx = np.argmax(cusum_abs[search_start:search_end]) + search_start
            peak_val = cusum_abs[peak_idx]
            # 标准化：除以 σ√L，消除段长/方差对跨段比较的影响（审查 #2.6 量纲修复）
            peak_norm = peak_val / (seg_std * np.sqrt(seg_len))

            if peak_norm > best_stat_norm:
                best_stat_norm = peak_norm
                best_cp = int(start + peak_idx)
                best_seg_idx = seg_i

        if best_cp is not None and best_cp not in changepoints:
            # 标准化峰值阈值判定（噪声下 max|W| ≈ 1.2，默认 2.0）
            if best_stat_norm < min_peak_ratio:
                break
            changepoints.append(best_cp)
            old_start, old_end = segments_for_split[best_seg_idx]
            segments_for_split.pop(best_seg_idx)
            segments_for_split.append((old_start, best_cp + 1))
            segments_for_split.append((best_cp + 1, old_end))
        else:
            break

    changepoints.sort()

    # ── 分段统计 ──
    if not changepoints:
        # 无变点：只有一个段
        segment_stats = [
            {
                "段": 1,
                "起始": 0,
                "结束": n - 1,
                "样本数": n,
                "均值": f"{float(np.mean(values)):.4f}",
                "标准差": f"{float(np.std(values, ddof=1)):.4f}",
            }
        ]
        summary = f"未检测到显著变点，过程整体平稳 (n={n})"
    else:
        segment_stats = []
        boundaries = [0] + changepoints + [n]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_vals = values[start:end]
            if len(seg_vals) > 0:
                segment_stats.append(
                    {
                        "段": seg_i + 1,
                        "起始": start,
                        "结束": end - 1,
                        "样本数": end - start,
                        "均值": f"{float(np.mean(seg_vals)):.4f}",
                        "标准差": f"{float(np.std(seg_vals, ddof=1)):.4f}"
                        if len(seg_vals) >= 2
                        else "—",
                        "变化方向": (
                            "↑ 上升"
                            if seg_i > 0
                            and float(np.mean(seg_vals))
                            > float(np.mean(values[boundaries[seg_i - 1] : boundaries[seg_i]]))
                            else "↓ 下降"
                            if seg_i > 0
                            else "—"
                        ),
                    }
                )
        cp_positions = ", ".join(str(cp) for cp in changepoints)
        summary = (
            f"检测到 {len(changepoints)} 个变点 (位置: {cp_positions})，"
            f"过程分为 {len(segment_stats)} 段"
        )

    # ── 可视化 ──
    fig = Figure(figsize=(12, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    ax.plot(
        pos, values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.7, label="数据"
    )

    # 分段均值线
    if changepoints:
        boundaries = [0] + changepoints + [n]
        colors = [
            PALETTE["data"]["primary"],
            PALETTE["target"]["primary"],
            PALETTE["center"]["primary"],
            PALETTE["contrast"]["d"],
            PALETTE["contrast"]["b"],
        ]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_mean = float(np.mean(values[start:end]))
            ax.plot(
                [start, end - 1],
                [seg_mean, seg_mean],
                "-",
                color=colors[seg_i % len(colors)],
                linewidth=2.5,
                label=f"段{seg_i + 1} μ={seg_mean:.3f}",
            )

    # 标记变点
    for cp in changepoints:
        ax.axvline(
            cp, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5, alpha=0.8
        )
        ax.annotate(
            f"变点{cp}",
            xy=(cp, values[cp]),
            xytext=(cp + 5, values[cp] + 0.5 * np.std(values)),
            fontsize=8,
            color=PALETTE["anomaly"]["primary"],
            arrowprops=dict(arrowstyle="->", color=PALETTE["anomaly"]["primary"], lw=0.8),
        )

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"变点检测 — {req.target_col} | {len(changepoints)} 个变点, {len(segment_stats)} 段",
        fontsize=11,
    )
    ax.legend(fontsize=7.5, loc="upper left", ncol=2)
    fig.tight_layout()

    return AnalysisResult(
        task="change_point",
        tables={"segment_statistics": pd.DataFrame(segment_stats)},
        figures=[fig],
        summary=summary,
        metadata={
            "changepoints": changepoints,
            "n_changepoints": len(changepoints),
            "n_segments": len(segment_stats),
            "n": n,
        },
    )
