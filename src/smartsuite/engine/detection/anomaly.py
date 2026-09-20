"""异常点检测（原 detection.py 的 anomaly_detect，2026-09-21 拆分）。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    IQR_OUTLIER_MULTIPLIER,
    ZSCORE_OUTLIER_THRESHOLD,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display

logger = logging.getLogger(__name__)


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """异常检测：IQR / Z-score (单变量) 或 Isolation Forest (多变量)。"""
    method = req.params.get("method", "iqr")
    # Round-2 #A2p：未知 method 此前静默按 Z-score 执行
    if method not in ("isolation_forest", "grubbs", "iqr", "zscore"):
        return AnalysisResult(
            task="anomaly_detect",
            status="error",
            messages=[f"不支持的检测方法: {method!r}，可选 isolation_forest/grubbs/iqr/zscore"],
        )

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
                except (ValueError, TypeError):
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
            iso = IsolationForest(
                contamination=contamination,
                random_state=42,
                n_estimators=100,
            )
            preds = iso.fit_predict(sub.values)
            scores = iso.decision_function(sub.values)
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
    data = req.data[req.target_col].dropna()
    data_std = data.std(ddof=1)  # 统一计算，供所有方法和可视化使用
    if len(data) < 5:
        return AnalysisResult(
            task="anomaly_detect",
            status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    if method == "grubbs":
        # Grubbs 检验：每次检测最大偏差，迭代最多 5 个异常点
        # 类型安全转换（审查 2026-08-19 #1.4：CLI/YAML 字符串参数会 TypeError）
        # 审查 2026-09-16 C-1：int(inf) 抛 OverflowError 且不在捕获元组内 → 补齐
        try:
            alpha_g = float(req.params.get("alpha", 0.05))
            max_outliers = int(req.params.get("max_outliers", 5))
        except (ValueError, TypeError, OverflowError):
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["Grubbs 检验参数格式错误：alpha 需为数值，max_outliers 需为整数"],
            )
        if not 0 < alpha_g < 1:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=[f"alpha 必须在 (0, 1) 区间内，当前: {alpha_g!r}"],
            )
        if max_outliers < 1:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=[f"max_outliers 必须 ≥ 1，当前: {max_outliers}"],
            )
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
            if not np.isfinite(sigma) or sigma <= 0:
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
        Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
        IQR = Q3 - Q1
        if IQR == 0:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据无变化(IQR=0)，无法检测异常"],
            )
        mask = (data < Q1 - IQR_OUTLIER_MULTIPLIER * IQR) | (
            data > Q3 + IQR_OUTLIER_MULTIPLIER * IQR
        )
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
            lower_bound = Q1 - IQR_OUTLIER_MULTIPLIER * IQR
            upper_bound = Q3 + IQR_OUTLIER_MULTIPLIER * IQR
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
        metadata={"anomaly_count": int(mask.sum()), "method": method},
    )
