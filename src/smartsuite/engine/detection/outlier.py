"""多方法离群点共识（原 detection.py 的 outlier_consensus，2026-09-21 拆分）。"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    IQR_OUTLIER_MULTIPLIER,
    ZSCORE_OUTLIER_THRESHOLD,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display
from smartsuite.engine.detection._shared import iqr_outlier_mask

logger = logging.getLogger(__name__)


def outlier_consensus(req: AnalysisRequest) -> AnalysisResult:
    """多方法异常检测共识 — 组合 IQR、Z-score、Isolation Forest 投票判定。

    只有当 ≥2 种方法都判定为异常时，才标记为"高置信异常"。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 10:
        return AnalysisResult(
            task="outlier_consensus",
            status="error",
            messages=["有效数据不足(至少10个点)"],
        )

    # ── 方法 1: IQR ──
    # 审查 2026-09-21 A-1：与 anomaly_detect 共用 _shared 单一实现
    _iqr = iqr_outlier_mask(data, IQR_OUTLIER_MULTIPLIER)
    if _iqr is None:
        return AnalysisResult(
            task="outlier_consensus",
            status="error",
            messages=["数据无变化(IQR=0)，无法检测异常"],
        )
    iqr_mask, _, _ = _iqr

    # ── 方法 2: Z-score ──
    # 审查 2026-09-16 D-1：原分母 `std+EPSILON` 在微尺度下把 z 整体压低 ~1000×
    # → 静默漏检；此处 std=0 已在 IQR==0 分支提前返回，直接相除（z 量纲无关）
    # 审查 2026-09-21 A-1：Z 分数判据与 anomaly_detect 的 z 分支重复（同为 ddof=1、
    # 同一 ZSCORE_OUTLIER_THRESHOLD）。未合并的原因：本处需把 Z 值写入结果表，
    # 而 anomaly_detect 只用掩码——两处改动请同步（本题不引入绝对阈值，见陷阱 9）。
    z_scores = np.abs((data - data.mean()) / data.std(ddof=1))
    z_mask = z_scores > ZSCORE_OUTLIER_THRESHOLD

    # ── 方法 3: Isolation Forest ──
    try:
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler

        iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
        # 审查 2026-09-21 D-4：同 anomaly_detect——不标准化的 IsolationForest
        # 在微尺度（×1e-9）下静默退化为零检出，使本方法投票缺失、共识条数变化。
        _scale = StandardScaler().fit_transform
        if len(req.feature_cols) > 0:
            feature_cols = [c for c in req.feature_cols if c in req.data.columns]
            sub = req.data[feature_cols + [req.target_col]].dropna()
            common_idx = data.index.intersection(sub.index)
            X = _scale(sub.loc[common_idx, feature_cols + [req.target_col]].values)
            iso_preds = iso.fit_predict(X)
            iso_mask = pd.Series(False, index=data.index)
            for i, idx in enumerate(common_idx):
                iso_mask[idx] = iso_preds[i] == -1
        else:
            X = _scale(data.values.reshape(-1, 1))
            iso_preds = iso.fit_predict(X)
            iso_mask = pd.Series(iso_preds == -1, index=data.index)
    except (ValueError, RuntimeError, ImportError):
        logger.debug("IsolationForest failed in outlier_consensus", exc_info=True)
        iso_mask = pd.Series(False, index=data.index)

    # ── 投票: ≥2 票 → 高置信异常 ──
    votes = iqr_mask.astype(int) + z_mask.astype(int) + iso_mask.astype(int)
    high_conf = votes >= 2
    any_flag = votes >= 1

    # ── 结果表 ──
    anomaly_rows = []
    for i, idx in enumerate(data.index):
        if any_flag.iloc[i]:
            anomaly_rows.append(
                {
                    "序号": idx,
                    req.target_col: round_for_display(float(data.iloc[i])),
                    "IQR": "是" if iqr_mask.iloc[i] else "否",
                    "Z-Score": "是" if z_mask.iloc[i] else "否",
                    "IsoForest": "是" if iso_mask.iloc[i] else "否",
                    "投票数": int(votes.iloc[i]),
                    "置信度": "高 (≥2票)" if high_conf.iloc[i] else "低 (1票)",
                }
            )

    # ── 可视化 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    # 大样本时减细线与点，突出高/低置信标记
    if n > 300:
        ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=0.7, alpha=0.5)
        ax.scatter(pos, data.values, s=4, color=PALETTE["data"]["primary"], alpha=0.5)
    else:
        ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.6)
        ax.scatter(pos, data.values, s=12, color=PALETTE["data"]["primary"], alpha=0.6)

    # 低置信 (1票)
    low_conf_pos = np.where(any_flag & ~high_conf)[0]
    if len(low_conf_pos) > 0:
        ax.scatter(
            low_conf_pos,
            data.values[low_conf_pos],
            s=60,
            color=PALETTE["spec"]["secondary"],
            marker="s",
            facecolors="none",
            linewidths=1.5,
            zorder=4,
            label=f"低置信 (1票, {len(low_conf_pos)}个)",
        )

    # 高置信 (≥2票)
    high_conf_pos = np.where(high_conf)[0]
    if len(high_conf_pos) > 0:
        ax.scatter(
            high_conf_pos,
            data.values[high_conf_pos],
            s=100,
            color=PALETTE["anomaly"]["primary"],
            marker="x",
            linewidths=3,
            zorder=5,
            label=f"高置信 (≥2票, {len(high_conf_pos)}个)",
        )

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"多方法异常共识 — {req.target_col} | "
        f"高置信={int(high_conf.sum())}, 总标记={int(any_flag.sum())}",
        fontsize=11,
    )
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()

    summary = (
        f"异常共识: {int(any_flag.sum())} 个标记, "
        f"{int(high_conf.sum())} 个高置信(≥2票)。"
        f"方法: IQR({int(iqr_mask.sum())}), Z-score({int(z_mask.sum())}), "
        f"IsoForest({int(iso_mask.sum())})"
    )

    return AnalysisResult(
        task="outlier_consensus",
        tables={
            "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows else pd.DataFrame(),
            "method_counts": pd.DataFrame(
                {
                    "方法": ["IQR", "Z-Score", "Isolation Forest", "高置信(≥2票)", "任意标记"],
                    "检测数": [
                        int(iqr_mask.sum()),
                        int(z_mask.sum()),
                        int(iso_mask.sum()),
                        int(high_conf.sum()),
                        int(any_flag.sum()),
                    ],
                }
            ),
        },
        figures=[fig],
        summary=summary,
        metadata={
            "iqr_count": int(iqr_mask.sum()),
            "zscore_count": int(z_mask.sum()),
            "isoforest_count": int(iso_mask.sum()),
            "high_confidence_count": int(high_conf.sum()),
            "total_flagged": int(any_flag.sum()),
        },
    )
