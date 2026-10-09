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
from smartsuite.engine._guard import (
    BoundaryIssue,
    BoundaryReport,
    check_magnitude,
    clean_series,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import round_for_display
from smartsuite.engine.detection._shared import iqr_outlier_mask

logger = logging.getLogger(__name__)


def outlier_consensus(req: AnalysisRequest) -> AnalysisResult:
    """多方法异常检测共识 — 组合 IQR、Z-score、Isolation Forest 投票判定。

    只有当 ≥2 种方法都判定为异常时，才标记为"高置信异常"。
    """
    # ── 边界处置（B0/B1）：±Inf 与量级上界（审查 2026-10-09 P0-8 / P1-4）──
    # `dropna()` 不剔除 ±Inf —— 实测注入 3 个 +Inf 后 `status=ok`、`messages=[]`；
    # ×1e300 时「3 个高置信」静默变成「0 个高置信」（结论级翻转）。
    _boundary = BoundaryReport()
    data, _n_non_finite = clean_series(
        req.data[req.target_col], column=req.target_col, report=_boundary
    )
    data = data.dropna()
    n = len(data)
    if n < 10:
        return AnalysisResult(
            task="outlier_consensus",
            status="error",
            messages=["有效数据不足(至少10个点)"] + _boundary.messages(),
        )
    if check_magnitude(data, what=f"目标列「{req.target_col}」", report=_boundary):
        return AnalysisResult(
            task="outlier_consensus",
            status="error",
            messages=_boundary.messages(),
            metadata={"boundary_codes": _boundary.codes()},
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
    # 降级可见性（审查 2026-10-09 R2BD-04，P1）：本方法不可用时原先只写
    # `logger.debug` 并把 `iso_mask` 整体置 False —— 该列照常渲染为「否」，
    # 与"IsoForest 跑了且认为都不是异常"**字面完全一致**，而投票成员数已由 3
    # 降为 2（≥2 票 = 高置信的语义随之变化），用户无法分辨「未运行」与「未发现」。
    # 违反 `boundary-contract.md` 硬性要求 1「禁止任何只在 logger.debug 里说明的降级」。
    # 现四处同步可见：① `BoundaryReport`（B2 + 错误码）② WARNING 日志
    # ③ 结果表该列写「未参与」（与「否」区分）④ summary 与 metadata 披露成员数。
    iso_available = True
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
        logger.warning("IsolationForest 方法不可用，本次投票已跳过该方法", exc_info=True)
        iso_mask = pd.Series(False, index=data.index)
        iso_available = False
        _boundary.add(
            BoundaryIssue(
                level="B2",
                code="E_NUMERIC_METHOD_UNAVAILABLE",
                detail=(
                    "⚠ IsolationForest 方法不可用（已跳过），本次投票仅基于 IQR 与 Z-Score "
                    "2 种方法；结果表该列显示「未参与」而非「否」。投票成员数由 3 降为 2，"
                    "高置信阈值仍为 ≥2 票 —— 同一票数在更少成员下含义更强，请结合方法列判读。"
                ),
            )
        )

    # ── 投票: ≥2 票 → 高置信异常 ──
    votes = iqr_mask.astype(int) + z_mask.astype(int) + iso_mask.astype(int)
    high_conf = votes >= 2
    any_flag = votes >= 1

    # 降级时该列写「未参与」而不是「否」（审查 2026-10-09 R2BD-04）：
    # 二者若同为「否」，用户无法分辨「方法未运行」与「方法运行了但认为不是异常」。
    _iso_cell_true, _iso_cell_false = ("是", "否") if iso_available else ("未参与", "未参与")

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
                    "IsoForest": _iso_cell_true if iso_mask.iloc[i] else _iso_cell_false,
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

    _iso_label = "IsoForest" if iso_available else "IsoForest(未参与)"
    summary = (
        f"异常共识: {int(any_flag.sum())} 个标记, "
        f"{int(high_conf.sum())} 个高置信(≥2票)。"
        f"方法: IQR({int(iqr_mask.sum())}), Z-score({int(z_mask.sum())}), "
        f"{_iso_label}({int(iso_mask.sum())})"
    )
    if not iso_available:
        summary += "。⚠ IsolationForest 方法不可用，本次仅 IQR 与 Z-Score 2 种方法参与投票"

    return AnalysisResult(
        task="outlier_consensus",
        tables={
            "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows else pd.DataFrame(),
            "method_counts": pd.DataFrame(
                {
                    "方法": [
                        "IQR",
                        "Z-Score",
                        "Isolation Forest" if iso_available else "Isolation Forest (未参与投票)",
                        "高置信(≥2票)",
                        "任意标记",
                    ],
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
        messages=_boundary.messages(),
        metadata={
            "iqr_count": int(iqr_mask.sum()),
            "zscore_count": int(z_mask.sum()),
            "isoforest_count": int(iso_mask.sum()),
            "high_confidence_count": int(high_conf.sum()),
            "total_flagged": int(any_flag.sum()),
            # 实际参与投票的方法清单（审查 2026-10-09 R2BD-04）：机器可读出口，
            # 上游不必解析中文文案即可判断本次投票的成员数。
            "voting_methods": ["IQR", "Z-Score", "Isolation Forest"]
            if iso_available
            else ["IQR", "Z-Score"],
            "boundary_codes": _boundary.codes(),
        },
    )
