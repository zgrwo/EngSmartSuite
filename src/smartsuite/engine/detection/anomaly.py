"""异常点检测（原 detection.py 的 anomaly_detect，2026-09-21 拆分）。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from sklearn.preprocessing import StandardScaler

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.core.param_spec import Choice, Integer, Opt, Spec
from smartsuite.core.param_specs_common import ALPHA
from smartsuite.engine._constants import (
    IQR_OUTLIER_MULTIPLIER,
    ZSCORE_OUTLIER_THRESHOLD,
)
from smartsuite.engine._guard import BoundaryReport, check_magnitude, clean_series
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display
from smartsuite.engine.detection._shared import iqr_outlier_mask

logger = logging.getLogger(__name__)

# ── 声明式参数契约（P4 步骤③，第二十四轮）──
# 契约：docs/governance/improvement-plan.md §六
# 只声明 `DEFAULT_PARAMS` 里的三个参数。`contamination` 不在默认值表里且
# 支持 `(0,0.5]` 数值**或字符串 "auto"** 双形态，故有意不声明 → 原样透传。
PARAM_SPECS = {
    "anomaly_detect": Spec(
        method=Opt(
            Choice(
                ("iqr", "IQR（四分位距，单变量）"),
                ("zscore", "Z-score（标准差，单变量）"),
                ("grubbs", "Grubbs（单变量，逐点剔除）"),
                ("isolation_forest", "孤立森林（多变量）"),
            ),
            default="iqr",
            label="异常检测方法",
            hint="IQR/Z-score/Grubbs 为单变量；孤立森林可同时利用多个特征",
        ),
        alpha=ALPHA,
        max_outliers=Opt(
            Integer(min=1),
            default=5,
            label="最多异常点数",
            hint="Grubbs 检验逐点剔除的上限；至少 1",
        ),
    ),
}


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """异常检测：IQR / Z-score (单变量) 或 Isolation Forest (多变量)。"""

    # 参数校验（P4 步骤③，第二十四轮）：失败时抛 ParamValidationError，
    # 由 orchestrator 统一转成 status="error" + 中文文案。
    # 原 Round-2 #A2p 的"未知 method 静默按 Z-score 执行"守卫（白名单检查）
    # 已由 `Choice` 前置表达并给出中文文案，故不再重复。
    _ap = PARAM_SPECS["anomaly_detect"].validate_or_raise(req.params)
    method = _ap.method
    alpha = _ap.alpha
    max_outliers = _ap.max_outliers

    # ── 多变量异常检测 (Isolation Forest) ──
    if method == "isolation_forest":
        feature_cols = [c for c in req.feature_cols if c in req.data.columns]
        if not feature_cols:
            feature_cols = [req.target_col]
        sub = req.data[feature_cols].dropna()
        if len(sub) < 5:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["有效样本不足(至少需要5个完整观测)"],
            )
        from sklearn.ensemble import IsolationForest

        contamination = req.params.get("contamination", 0.05)
        # 审查 2026-09-01 N-3：CLI/YAML 字符串参数需转换——numeric 字符串转 float，
        # "auto"（sklearn 合法）保留原值；非法字符串返回中文错误而非 sklearn 原始异常
        if isinstance(contamination, str):
            if contamination.strip().lower() == "auto":
                contamination = "auto"
            else:
                try:
                    contamination = float(contamination)
                except (ValueError, TypeError, OverflowError):
                    return AnalysisResult(
                        task="anomaly_detect",
                        status="error",
                        messages=[
                            f"参数 contamination 无效: {contamination!r}，"
                            f"请输入 (0, 0.5] 区间数值或 'auto'"
                        ],
                    )
        if not isinstance(contamination, str) and not np.isfinite(contamination):
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=[f"参数 contamination 必须为有限数值或 'auto'，当前: {contamination!r}"],
            )
        contamination_disp = "auto" if contamination == "auto" else f"{contamination:.1%}"
        try:
            # 审查 2026-09-21 D-4（P1）：IsolationForest 直接吃原始特征值时对量纲敏感——
            # 实测同一数据 ×1e-9/×1e-12 时检出数由 6 静默降为 0（status 仍为 ok）。
            # 入模型前标准化，使检出结果与单位选择无关。
            iso = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100,
            )
            scaled = StandardScaler().fit_transform(sub.values)
            preds = iso.fit_predict(scaled)
            scores = iso.decision_function(scaled)
            # preds: 1=正常, -1=异常
            mask = preds == -1
        except Exception as e:
            logger.warning("Isolation Forest 拟合失败: %s", e, exc_info=True)
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["Isolation Forest 模型拟合失败，请检查数据质量或调整 contamination 参数"],
            )

        anomalies = req.data.loc[sub.index[mask]] if mask.sum() > 0 else pd.DataFrame()

        # 多变量可视化：取前两个特征做散点图 + 异常高亮
        fig = Figure(figsize=(10, 5))
        if len(feature_cols) >= 2:
            ax1 = fig.add_subplot(1, 2, 1)
            c1, c2 = feature_cols[0], feature_cols[1]
            normal_mask = ~mask
            ax1.scatter(
                sub.loc[normal_mask, c1],
                sub.loc[normal_mask, c2],
                s=20,
                alpha=0.5,
                color=PALETTE["data"]["secondary"],
                label=f"正常 ({normal_mask.sum()})",
            )
            if mask.sum() > 0:
                ax1.scatter(
                    sub.loc[mask, c1],
                    sub.loc[mask, c2],
                    s=60,
                    alpha=0.9,
                    color=PALETTE["anomaly"]["primary"],
                    marker="x",
                    linewidths=2,
                    label=f"异常 ({mask.sum()})",
                )
            ax1.set_xlabel(c1, fontsize=9)
            ax1.set_ylabel(c2, fontsize=9)
            ax1.set_title("多变量异常检测 (Isolation Forest)", fontsize=10)
            ax1.legend(fontsize=8)

            # 异常分数分布
            ax2 = fig.add_subplot(1, 2, 2)
        else:
            ax2 = fig.add_subplot(111)
        ax2.hist(
            scores[~mask],
            bins=20,
            alpha=0.7,
            color=PALETTE["data"]["secondary"],
            label=f"正常 (n={(~mask).sum()})",
        )
        if mask.sum() > 0:
            ax2.hist(
                scores[mask],
                bins=10,
                alpha=0.8,
                color=PALETTE["target"]["primary"],
                label=f"异常 (n={mask.sum()})",
            )
        ax2.axvline(
            0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, label="决策边界"
        )
        ax2.set_xlabel("异常分数 (越低越异常)", fontsize=9)
        ax2.set_ylabel("频数", fontsize=9)
        ax2.set_title("异常分数分布", fontsize=10)
        ax2.legend(fontsize=8, ncol=2)
        fig.tight_layout()

        # 异常详情表（含异常分数）
        anomaly_rows = []
        if mask.sum() > 0:
            for i, idx in enumerate(sub.index[mask]):
                row_data = {"异常分数": round_for_display(float(scores[mask][i]))}
                for c in feature_cols:
                    row_data[c] = req.data.loc[idx, c]
                anomaly_rows.append(row_data)

        return AnalysisResult(
            task="anomaly_detect",
            tables={
                "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows else pd.DataFrame(),
            },
            figures=[fig],
            summary=(
                f"Isolation Forest 检测到 {mask.sum()} 个多变量异常点 "
                f"(污染率={contamination_disp}, 维度={len(feature_cols)})"
            ),
            metadata={
                "anomaly_count": int(mask.sum()),
                "method": "isolation_forest",
                "contamination": contamination,
                "feature_dim": len(feature_cols),
            },
        )

    # ── 单变量异常检测 (IQR / Z-score) ──
    # 边界处置（B1）：`dropna()` **不剔除 ±Inf**（Inf 不是 NaN）。
    # 审查 2026-10-09 P0-7：+Inf 使 `np.std` 变成 NaN，Grubbs 的
    # `if not np.isfinite(sigma) ... break` 在**首次迭代前**就退出 →
    # 静默返回「检测到 0 个异常点」（status=ok、messages 为空）。
    _report = BoundaryReport()
    data, _n_dropped = clean_series(req.data[req.target_col], column=req.target_col, report=_report)
    data = data.dropna()
    # 审查 2026-10-09 P1-4：量级上界守卫。×1e300 时 σ 溢出为 inf → 旧实现静默返回
    # 「检测到 0 个异常点」（status=ok、messages 为空）—— 一个看不出问题的假结论。
    if (issue := check_magnitude(data, what=f"「{req.target_col}」", report=_report)) is not None:
        return AnalysisResult(task="anomaly_detect", status="error", messages=[issue.detail])
    data_std = data.std(ddof=1)  # 统一计算，供所有方法和可视化使用
    if len(data) < 5:
        return AnalysisResult(
            task="anomaly_detect",
            status="error",
            messages=["有效数据不足(至少5个点)", *_report.messages()],
        )

    if method == "grubbs":
        # Grubbs 检验：每次检测最大偏差，迭代最多 5 个异常点
        # `alpha` / `max_outliers` 已在函数开头由 `PARAM_SPECS["anomaly_detect"]`
        # 一次校验并取用（含 `int(inf)` 这类 OverflowError 场景 —— `Integer`
        # 会先判 `isfinite`，故不存在溢出穿透）。此处只做别名，不再重复校验。
        alpha_g = alpha
        # 审查 2026-09-16 B-2：原 `sigma < EPSILON`（绝对 1e-10）在首次迭代对微尺度
        # 数据直接 break → 静默返回 0 异常。常量列改为显式中文错误；迭代中 sigma 归零
        # （剔除后剩余值全同）才 break（此时已返回已检出异常，语义正确）。
        if data.nunique(dropna=True) <= 1:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["目标列为常量列（标准差为 0），无法进行 Grubbs 检验"],
            )
        vals = data.values.copy()
        mask = np.zeros(len(data), dtype=bool)
        keep_idx = np.arange(len(data))
        for _ in range(max_outliers):
            mu = np.mean(vals)
            sigma = np.std(vals, ddof=1)
            # 审查 2026-10-09 P0-7：原先把「σ 非有限」与「σ ≤ 0」并入同一个 `break`
            # → 量级溢出时迭代尚未开始就退出，静默返回 0 个异常。
            # 二者语义不同，必须分开：
            #   · σ 精确为 0（剔除后剩余值全同）→ 无可检出的异常，break 正确；
            #   · σ 非有限（平方和溢出）→ **无法判定**，B0 拒绝并说明量级问题。
            if not np.isfinite(sigma):
                return AnalysisResult(
                    task="anomaly_detect",
                    status="error",
                    messages=[
                        "Grubbs 检验无法判定：数据量级过大导致标准差溢出（非有限），"
                        "请先做单位换算或中心化后重试",
                        *_report.messages(),
                    ],
                )
            if sigma <= 0:
                break
            g_scores = np.abs(vals - mu) / sigma
            max_idx = np.argmax(g_scores)
            G = g_scores[max_idx]
            n_remain = len(vals)
            if n_remain < 3:
                break
            t_crit = sp_stats.t.ppf(1 - alpha_g / (2 * n_remain), n_remain - 2)
            G_crit = (
                (n_remain - 1) / np.sqrt(n_remain) * np.sqrt(t_crit**2 / (n_remain - 2 + t_crit**2))
            )
            if G > G_crit:
                mask[keep_idx[max_idx]] = True
                vals = np.delete(vals, max_idx)
                keep_idx = np.delete(keep_idx, max_idx)
            else:
                break
    elif method == "iqr":
        # 审查 2026-09-21 A-1：IQR 判据与 outlier_consensus 共用 _shared 单一实现
        # （含 IQR==0 拒绝政策与倍率常量来源）；边界一次算出，供掩码与下方可视化共用。
        _iqr = iqr_outlier_mask(data, IQR_OUTLIER_MULTIPLIER)
        if _iqr is None:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据无变化(IQR=0)，无法检测异常"],
            )
        mask, iqr_lower, iqr_upper = _iqr
    else:
        # 审查 2026-09-16 D-1：原 `data_std < EPSILON`（绝对 1e-10）显式拒绝微尺度
        # 数据；改精确零判据——只有真常量列才无法做 z 分数（z 本身量纲无关）
        if data.nunique(dropna=True) <= 1:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["目标列为常量列（标准差为 0），无法进行 Z-score 异常检测"],
            )
        z = np.abs((data - data.mean()) / data_std)
        mask = z > ZSCORE_OUTLIER_THRESHOLD

    idx = data.index[mask]
    anomalies = req.data.loc[idx] if mask.sum() > 0 else pd.DataFrame()

    # 异常检测散点图（大样本时减细线与点标记）
    fig = Figure(figsize=(9, 4))
    ax = fig.add_subplot(111)
    pos = np.arange(len(data))
    if len(data) > 300:
        ax.plot(
            pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=0.7, label="数据"
        )
        ax.scatter(pos, data.values, s=3, color=PALETTE["data"]["primary"], alpha=0.6)
    else:
        ax.plot(
            pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, label="数据"
        )
        ax.scatter(pos, data.values, s=10, color=PALETTE["data"]["primary"])
    if mask.sum() > 0:
        anomaly_pos = np.where(mask)[0]
        ax.scatter(
            anomaly_pos,
            data.values[mask],
            s=80,
            color=PALETTE["anomaly"]["primary"],
            marker="x",
            linewidths=2.5,
            zorder=5,
            label=f"异常({mask.sum()}个)",
        )
        if method == "iqr":
            # 与判定掩码同源（_shared.iqr_outlier_mask 返回的边界），不另行重算
            lower_bound = iqr_lower
            upper_bound = iqr_upper
            ax.axhline(
                lower_bound,
                color=PALETTE["spec"]["secondary"],
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"下界={lower_bound:.3f}",
            )
            ax.axhline(
                upper_bound,
                color=PALETTE["spec"]["secondary"],
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"上界={upper_bound:.3f}",
            )
        elif method == "grubbs":
            # Grubbs 使用迭代临界值 (t 分布)，不画 ±3σ 线避免误导
            ax.axhline(
                data.mean(),
                color=PALETTE["spec"]["secondary"],
                linestyle=":",
                linewidth=1,
                alpha=0.4,
                label=f"均值={data.mean():.3f}",
            )
        else:
            ax.axhline(
                data.mean() + 3 * data_std,
                color=PALETTE["spec"]["secondary"],
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"上界={data.mean() + 3 * data_std:.3f}",
            )
            ax.axhline(
                data.mean() - 3 * data_std,
                color=PALETTE["spec"]["secondary"],
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"下界={data.mean() - 3 * data_std:.3f}",
            )
    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(f"异常检测 — {req.target_col} (方法: {method})", fontsize=11)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    return AnalysisResult(
        task="anomaly_detect",
        tables={"anomalies": anomalies},
        figures=[fig],
        summary=f"检测到 {mask.sum()} 个异常点 (方法: {method})",
        messages=_report.messages(),
        metadata={
            "anomaly_count": int(mask.sum()),
            "method": method,
            "boundary_codes": _report.codes(),
        },
    )
