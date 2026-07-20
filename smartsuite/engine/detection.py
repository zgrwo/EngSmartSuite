"""异常检测模块：趋势预测、变化点检测、异常检测、离群点共识。"""
import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats
from sklearn.linear_model import LinearRegression

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import (
    DW_NEGATIVE_AUTOCORR,
    DW_POSITIVE_AUTOCORR,
    DW_SAFE_LOWER,
    DW_SAFE_UPPER,
    EPSILON,
    IQR_OUTLIER_MULTIPLIER,
    ZSCORE_OUTLIER_THRESHOLD,
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import durbin_watson

logger = logging.getLogger(__name__)

def _ljung_box(residuals, lags=None):
    """Ljung-Box 检验 — 残差自相关的整体显著性检验。"""
    n = len(residuals)
    if lags is None:
        lags = min(10, n // 5)
    lags = max(1, min(lags, n // 2))
    # 简化计算：对每个滞后计算自相关，然后 Q = n*(n+2)*sum(r_k^2/(n-k))
    acf_sum = 0.0
    for k in range(1, lags + 1):
        r_k = np.corrcoef(residuals[k:], residuals[:-k])[0, 1]
        if np.isnan(r_k):  # P1 fix: 零方差子段导致 np.corrcoef 返回 NaN
            r_k = 0.0
        acf_sum += r_k**2 / (n - k)
    q_stat = n * (n + 2) * acf_sum
    p_val = float(sp_stats.chi2.sf(q_stat, lags))
    return float(q_stat), p_val, lags


def _dw_interpretation(dw, n, k=1):
    """Durbin-Watson 判读（近似阈值）。

    注意: 阈值为近似经验值，精确的 DW 临界值取决于样本量 n 和自变量数 k。
    对于小样本 (n<30) 或多变量回归，建议查阅 DW 临界值表进行精确判读。
    本函数提供快速近似判读。
    """
    if dw < DW_POSITIVE_AUTOCORR:
        return f"正自相关 (DW={dw:.3f}<{DW_POSITIVE_AUTOCORR})"
    elif dw > DW_NEGATIVE_AUTOCORR:
        return f"负自相关 (DW={dw:.3f}>{DW_NEGATIVE_AUTOCORR})"
    elif DW_SAFE_LOWER <= dw <= DW_SAFE_UPPER:
        return f"无显著自相关 (DW={dw:.3f})"
    else:
        return f"不确定 (DW={dw:.3f})"


def trend_forecast(req: AnalysisRequest) -> AnalysisResult:
    """线性趋势预测，含精度指标 (MAPE/RMSE/MAE)、残差诊断和 Durbin-Watson 检验。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 3:
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=["有效数据不足(至少3个点)"],
        )

    steps = req.params.get("forecast_steps", 5)
    try:
        n = len(data)
        X = np.arange(n).reshape(-1, 1)
        y = data.values
        model = LinearRegression().fit(X, y)

        # ── 样本内拟合 ──
        y_pred_in = model.predict(X)
        residuals = y - y_pred_in

        # ── 精度指标 ──
        # MAPE (处理零值)
        mape_mask = np.abs(y) > EPSILON
        mape = float(np.mean(np.abs(residuals[mape_mask] / y[mape_mask])) * 100) if mape_mask.sum() > 0 else None
        rmse = float(np.sqrt(np.mean(residuals**2)))
        mae = float(np.mean(np.abs(residuals)))
        r2 = float(model.score(X, y))
        adj_r2 = float(1 - (1 - r2) * (n - 1) / max(n - 2, 1))

        # ── Durbin-Watson + Ljung-Box ──
        dw = durbin_watson(residuals)
        dw_label = _dw_interpretation(dw, n)
        lb_q, lb_p, lb_lags = _ljung_box(residuals)

        # ── 预测 ──
        future_X = np.arange(n, n + steps).reshape(-1, 1)
        predictions = model.predict(future_X)

        # 使用 t 分布（小样本更准确）
        dof = max(1, n - 2)
        t_crit = sp_stats.t.ppf(0.975, dof)
        resid_std_se = float(np.std(residuals, ddof=2))
        # 预测区间随预测步数增大而加宽（外推不确定性）
        x_mean = float(np.mean(np.arange(n)))
        ssx = float(np.sum((np.arange(n) - x_mean) ** 2))
        future_conf = []
        for step in range(1, steps + 1):
            x_future = n + step - 1  # 0-indexed future position
            se_future = resid_std_se * np.sqrt(1 + 1/n + (x_future - x_mean)**2 / ssx)
            future_conf.append(float(t_crit * se_future))
        conf_array = np.array(future_conf)

        forecast_df = pd.DataFrame({
            "步数": range(1, steps + 1),
            "预测值": predictions.round(4),
            "下限": (predictions - conf_array).round(4),
            "上限": (predictions + conf_array).round(4),
        })

        # ── 精度指标表 ──
        lb_label = f"显著自相关 (p={lb_p:.4f})" if lb_p < 0.05 else f"无显著自相关 (p={lb_p:.4f})"
        metrics_df = pd.DataFrame({
            "指标": ["R²", "调整R²", "RMSE", "MAE", "MAPE (%)",
                    "Durbin-Watson", "Ljung-Box Q", "Ljung-Box p",
                    "残差诊断", "样本量", "预测步数", "斜率 (每步)", "截距"],
            "值": [
                f"{r2:.4f}", f"{adj_r2:.4f}", f"{rmse:.4f}", f"{mae:.4f}",
                f"{mape:.2f}%" if mape else "N/A",
                f"{dw:.4f}", f"{lb_q:.3f}", f"{lb_p:.4f}",
                f"{dw_label}; {lb_label}",
                str(n), str(steps),
                f"{float(model.coef_[0]):.6f}", f"{float(model.intercept_):.4f}",
            ],
        })

        trend_dir = "上升" if model.coef_[0] > 0 else "下降"

        # ── ACF 计算 ──
        max_lag = min(20, n // 4)
        acf_vals = []
        acf_conf = float(sp_stats.norm.ppf(0.975)) / np.sqrt(n)  # 95% 置信限
        for lag in range(max_lag + 1):
            if lag == 0:
                acf_vals.append(1.0)
            else:
                r = np.corrcoef(residuals[lag:], residuals[:-lag])[0, 1]
                acf_vals.append(float(r))

        # ── 增强图表：2×2 布局 ──
        fig = Figure(figsize=(13, 9))

        # 左上：趋势 + 预测 + 置信带
        ax1 = fig.add_subplot(2, 2, 1)
        hist_idx = np.arange(n)
        ax1.plot(hist_idx, y, "o-", markersize=3, label="历史数据", color=PALETTE["data"]["primary"], linewidth=1.2)
        ax1.plot(hist_idx, y_pred_in, "-", color=PALETTE["data"]["secondary"], linewidth=2, alpha=0.6,
                label=f"趋势线 (R²={r2:.3f})")
        fut_idx = np.arange(n, n + steps)
        ax1.plot(fut_idx, predictions, "o-", markersize=4, label="预测", color=PALETTE["target"]["primary"])
        ax1.fill_between(fut_idx, predictions - conf_array, predictions + conf_array,
                        alpha=0.2, color=PALETTE["target"]["primary"], label="95% 预测区间")
        ax1.set_xlabel("时间点", fontsize=9)
        ax1.set_ylabel(req.target_col, fontsize=9)
        ax1.set_title(f"趋势预测 — {req.target_col} ({trend_dir})", fontsize=10)
        ax1.legend(fontsize=8, ncol=2)

        # 右上：残差图
        ax2 = fig.add_subplot(2, 2, 2)
        ax2.scatter(hist_idx, residuals, s=12, color=PALETTE["data"]["secondary"], alpha=0.7)
        ax2.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
        ax2.plot(hist_idx, residuals, "-", color=PALETTE["data"]["secondary"], alpha=0.3, linewidth=0.5)
        ax2.set_xlabel("时间点", fontsize=9)
        ax2.set_ylabel("残差", fontsize=9)
        ax2.set_title(f"残差 — {dw_label}", fontsize=10)

        # 左下：ACF 自相关图
        ax3 = fig.add_subplot(2, 2, 3)
        lags = range(max_lag + 1)
        ax3.bar(lags, acf_vals, color=PALETTE["data"]["secondary"], width=0.4, edgecolor="white")
        ax3.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
        ax3.axhline(acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6)
        ax3.axhline(-acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6)
        ax3.set_xlabel("滞后阶数", fontsize=9)
        ax3.set_ylabel("自相关 (ACF)", fontsize=9)
        ax3.set_title("残差自相关 (ACF)", fontsize=10)

        # 右下：Actual vs Predicted
        ax4 = fig.add_subplot(2, 2, 4)
        ax4.scatter(y_pred_in, y, s=12, alpha=0.6, color=PALETTE["data"]["primary"])
        ax4.plot([y.min(), y.max()], [y.min(), y.max()],
                 color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
        ax4.set_xlabel("预测值", fontsize=9)
        ax4.set_ylabel("实际值", fontsize=9)
        ax4.set_title(f"Actual vs Predicted (R²={r2:.3f})", fontsize=10)
        fig.tight_layout()

        # ── 汇总 ──
        mape_str = f"{mape:.1f}%" if mape else "N/A"
        summary = (
            f"趋势{trend_dir} (斜率={float(model.coef_[0]):.4f}/步)，"
            f"预测{steps}步。R²={r2:.3f}, RMSE={rmse:.4f}, MAPE={mape_str}。"
            f"残差自相关: {dw_label}"
        )

        return AnalysisResult(
            task="trend_forecast",
            tables={
                "forecast": forecast_df,
                "accuracy_metrics": metrics_df,
            },
            figures=[fig],
            summary=summary,
            metadata={
                "slope": float(model.coef_[0]),
                "intercept": float(model.intercept_),
                "r_squared": r2, "r_squared_adj": adj_r2,
                "rmse": rmse, "mae": mae, "mape": mape,
                "durbin_watson": dw, "dw_interpretation": dw_label,
                "ljung_box_q": lb_q, "ljung_box_p": lb_p, "ljung_box_lags": lb_lags,
                "forecast_steps": steps, "n": n,
            },
        )
    except (ValueError, np.linalg.LinAlgError) as e:
        logger.warning("趋势预测模型拟合失败: %s", e)
        return AnalysisResult(
            task="trend_forecast", status="error",
            messages=["趋势预测模型拟合失败，数据可能不足或存在共线性问题，"
                      "请检查数据中是否包含足够的有效观测值。"])


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
            task="change_point", status="error",
            messages=["有效数据不足(至少20个点)"],
        )

    min_segment = req.params.get("min_segment", max(10, n // 20))
    max_cp = req.params.get("n_changepoints", 5)
    min_peak_ratio = req.params.get("min_peak_ratio", 0.1)

    # 参数类型安全转换 (CLI/YAML 传入字符串时防护)
    try:
        min_segment = int(min_segment)
        max_cp = int(max_cp)
        min_peak_ratio = float(min_peak_ratio)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="change_point", status="error",
            messages=["变点检测参数格式错误：min_segment 和 n_changepoints 需为整数，"
                      "min_peak_ratio 需为数值"],
        )

    values = data.values
    changepoints: list[int] = []
    segments_for_split = [(0, n)]

    # 二元分割：每次在段内找最大 CUSUM 位置
    while len(changepoints) < max_cp and segments_for_split:
        best_cp = None
        best_stat = 0
        best_seg_idx = -1

        for seg_i, (start, end) in enumerate(segments_for_split):
            seg_len = end - start
            if seg_len < 2 * min_segment:
                continue
            seg_vals = values[start:end]
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

            if peak_val > best_stat:
                best_stat = peak_val
                best_cp = start + peak_idx
                best_seg_idx = seg_i

        if best_cp is not None and best_cp not in changepoints:
            # 检查峰值是否超过数据变化范围的最小比例
            seg_start, seg_end = segments_for_split[best_seg_idx]
            segment_vals = values[seg_start:seg_end]
            data_range = float(np.max(segment_vals) - np.min(segment_vals))
            if data_range > 0 and best_stat < min_peak_ratio * data_range:
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
        segment_stats = [{
            "段": 1, "起始": 0, "结束": n - 1, "样本数": n,
            "均值": f"{float(np.mean(values)):.4f}",
            "标准差": f"{float(np.std(values, ddof=1)):.4f}",
        }]
        summary = f"未检测到显著变点，过程整体平稳 (n={n})"
    else:
        segment_stats = []
        boundaries = [0] + changepoints + [n]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_vals = values[start:end]
            if len(seg_vals) > 0:
                segment_stats.append({
                    "段": seg_i + 1,
                    "起始": start,
                    "结束": end - 1,
                    "样本数": end - start,
                    "均值": f"{float(np.mean(seg_vals)):.4f}",
                    "标准差": f"{float(np.std(seg_vals, ddof=1)):.4f}",
                    "变化方向": (
                        "↑ 上升" if seg_i > 0 and float(np.mean(seg_vals)) >
                        float(np.mean(values[boundaries[seg_i-1]:boundaries[seg_i]]))
                        else "↓ 下降" if seg_i > 0 else "—"
                    ),
                })
        cp_positions = ", ".join(str(cp) for cp in changepoints)
        summary = (
            f"检测到 {len(changepoints)} 个变点 (位置: {cp_positions})，"
            f"过程分为 {len(segment_stats)} 段"
        )

    # ── 可视化 ──
    fig = Figure(figsize=(12, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    ax.plot(pos, values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.7, label="数据")

    # 分段均值线
    if changepoints:
        boundaries = [0] + changepoints + [n]
        colors = [PALETTE["data"]["primary"], PALETTE["target"]["primary"], PALETTE["center"]["primary"], PALETTE["contrast"]["d"], PALETTE["contrast"]["b"]]
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_mean = float(np.mean(values[start:end]))
            ax.plot([start, end - 1], [seg_mean, seg_mean], "-",
                   color=colors[seg_i % len(colors)], linewidth=2.5,
                   label=f"段{seg_i+1} μ={seg_mean:.3f}")

    # 标记变点
    for cp in changepoints:
        ax.axvline(cp, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1.5, alpha=0.8)
        ax.annotate(f"变点{cp}", xy=(cp, values[cp]),
                   xytext=(cp + 5, values[cp] + 0.5 * np.std(values)),
                   fontsize=8, color=PALETTE["anomaly"]["primary"],
                   arrowprops=dict(arrowstyle="->", color=PALETTE["anomaly"]["primary"], lw=0.8))

    ax.set_xlabel("序号", fontsize=10)
    ax.set_ylabel(req.target_col, fontsize=10)
    ax.set_title(
        f"变点检测 — {req.target_col} | "
        f"{len(changepoints)} 个变点, {len(segment_stats)} 段",
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


def outlier_consensus(req: AnalysisRequest) -> AnalysisResult:
    """多方法异常检测共识 — 组合 IQR、Z-score、Isolation Forest 投票判定。

    只有当 ≥2 种方法都判定为异常时，才标记为"高置信异常"。
    """
    data = req.data[req.target_col].dropna()
    n = len(data)
    if n < 10:
        return AnalysisResult(
            task="outlier_consensus", status="error",
            messages=["有效数据不足(至少10个点)"],
        )

    # ── 方法 1: IQR ──
    Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
    IQR = Q3 - Q1
    if IQR == 0:
        return AnalysisResult(
            task="outlier_consensus",
            status="error",
            messages=["数据无变化(IQR=0)，无法检测异常"],
        )
    iqr_mask = (data < Q1 - IQR_OUTLIER_MULTIPLIER * IQR) | (data > Q3 + IQR_OUTLIER_MULTIPLIER * IQR)

    # ── 方法 2: Z-score ──
    z_scores = np.abs((data - data.mean()) / (data.std(ddof=1) + EPSILON))
    z_mask = z_scores > ZSCORE_OUTLIER_THRESHOLD

    # ── 方法 3: Isolation Forest ──
    try:
        from sklearn.ensemble import IsolationForest
        iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
        if len(req.feature_cols) > 0:
            feature_cols = [c for c in req.feature_cols if c in req.data.columns]
            sub = req.data[feature_cols + [req.target_col]].dropna()
            common_idx = data.index.intersection(sub.index)
            iso_preds = iso.fit_predict(sub.loc[common_idx, feature_cols + [req.target_col]].values)
            iso_mask = pd.Series(False, index=data.index)
            for i, idx in enumerate(common_idx):
                iso_mask[idx] = iso_preds[i] == -1
        else:
            X = data.values.reshape(-1, 1)
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
            anomaly_rows.append({
                "序号": idx,
                req.target_col: round(float(data.iloc[i]), 4),
                "IQR": "是" if iqr_mask.iloc[i] else "否",
                "Z-Score": "是" if z_mask.iloc[i] else "否",
                "IsoForest": "是" if iso_mask.iloc[i] else "否",
                "投票数": int(votes.iloc[i]),
                "置信度": "高 (≥2票)" if high_conf.iloc[i] else "低 (1票)",
            })

    # ── 可视化 ──
    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)
    pos = np.arange(n)
    ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, alpha=0.6)
    ax.scatter(pos, data.values, s=12, color=PALETTE["data"]["primary"], alpha=0.6)

    # 低置信 (1票)
    low_conf_pos = np.where(any_flag & ~high_conf)[0]
    if len(low_conf_pos) > 0:
        ax.scatter(low_conf_pos, data.values[low_conf_pos], s=60,
                  color=PALETTE["spec"]["secondary"], marker="s", facecolors="none", linewidths=1.5,
                  zorder=4, label=f"低置信 (1票, {len(low_conf_pos)}个)")

    # 高置信 (≥2票)
    high_conf_pos = np.where(high_conf)[0]
    if len(high_conf_pos) > 0:
        ax.scatter(high_conf_pos, data.values[high_conf_pos], s=100,
                  color=PALETTE["anomaly"]["primary"], marker="x", linewidths=3, zorder=5,
                  label=f"高置信 (≥2票, {len(high_conf_pos)}个)")

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
            "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows
            else pd.DataFrame(),
            "method_counts": pd.DataFrame({
                "方法": ["IQR", "Z-Score", "Isolation Forest", "高置信(≥2票)", "任意标记"],
                "检测数": [int(iqr_mask.sum()), int(z_mask.sum()),
                         int(iso_mask.sum()), int(high_conf.sum()),
                         int(any_flag.sum())],
            }),
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


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """异常检测：IQR / Z-score (单变量) 或 Isolation Forest (多变量)。"""
    method = req.params.get("method", "iqr")

    # ── 多变量异常检测 (Isolation Forest) ──
    if method == "isolation_forest":
        feature_cols = [c for c in req.feature_cols if c in req.data.columns]
        if not feature_cols:
            feature_cols = [req.target_col]
        sub = req.data[feature_cols].dropna()
        if len(sub) < 5:
            return AnalysisResult(
                task="anomaly_detect", status="error",
                messages=["有效样本不足(至少需要5个完整观测)"],
            )
        from sklearn.ensemble import IsolationForest
        contamination = req.params.get("contamination", 0.05)
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
                task="anomaly_detect", status="error",
                messages=[f"Isolation Forest 模型拟合失败: {e}"],
            )

        anomalies = req.data.loc[sub.index[mask]] if mask.sum() > 0 else pd.DataFrame()

        # 多变量可视化：取前两个特征做散点图 + 异常高亮
        fig = Figure(figsize=(10, 5))
        if len(feature_cols) >= 2:
            ax1 = fig.add_subplot(1, 2, 1)
            c1, c2 = feature_cols[0], feature_cols[1]
            normal_mask = ~mask
            ax1.scatter(sub.loc[normal_mask, c1], sub.loc[normal_mask, c2],
                       s=20, alpha=0.5, color=PALETTE["data"]["secondary"], label=f"正常 ({normal_mask.sum()})")
            if mask.sum() > 0:
                ax1.scatter(sub.loc[mask, c1], sub.loc[mask, c2],
                           s=60, alpha=0.9, color=PALETTE["anomaly"]["primary"], marker="x",
                           linewidths=2, label=f"异常 ({mask.sum()})")
            ax1.set_xlabel(c1, fontsize=9)
            ax1.set_ylabel(c2, fontsize=9)
            ax1.set_title("多变量异常检测 (Isolation Forest)", fontsize=10)
            ax1.legend(fontsize=8)

            # 异常分数分布
            ax2 = fig.add_subplot(1, 2, 2)
        else:
            ax2 = fig.add_subplot(111)
        ax2.hist(scores[~mask], bins=20, alpha=0.7, color=PALETTE["data"]["secondary"],
                label=f"正常 (n={(~mask).sum()})")
        if mask.sum() > 0:
            ax2.hist(scores[mask], bins=10, alpha=0.8, color=PALETTE["target"]["primary"],
                    label=f"异常 (n={mask.sum()})")
        ax2.axvline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, label="决策边界")
        ax2.set_xlabel("异常分数 (越低越异常)", fontsize=9)
        ax2.set_ylabel("频数", fontsize=9)
        ax2.set_title("异常分数分布", fontsize=10)
        ax2.legend(fontsize=8, ncol=2)
        fig.tight_layout()

        # 异常详情表（含异常分数）
        anomaly_rows = []
        if mask.sum() > 0:
            for i, idx in enumerate(sub.index[mask]):
                row_data = {"异常分数": round(float(scores[mask][i]), 4)}
                for c in feature_cols:
                    row_data[c] = req.data.loc[idx, c]
                anomaly_rows.append(row_data)

        return AnalysisResult(
            task="anomaly_detect",
            tables={
                "anomalies": pd.DataFrame(anomaly_rows) if anomaly_rows
                else pd.DataFrame(),
            },
            figures=[fig],
            summary=(
                f"Isolation Forest 检测到 {mask.sum()} 个多变量异常点 "
                f"(污染率={contamination:.1%}, 维度={len(feature_cols)})"
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
        alpha_g = req.params.get("alpha", 0.05)
        max_outliers = req.params.get("max_outliers", 5)
        vals = data.values.copy()
        mask = np.zeros(len(data), dtype=bool)
        keep_idx = np.arange(len(data))
        for _ in range(max_outliers):
            mu = np.mean(vals)
            sigma = np.std(vals, ddof=1)
            if sigma < EPSILON:
                break
            g_scores = np.abs(vals - mu) / sigma
            max_idx = np.argmax(g_scores)
            G = g_scores[max_idx]
            n_remain = len(vals)
            if n_remain < 3:
                break
            t_crit = sp_stats.t.ppf(1 - alpha_g / (2 * n_remain), n_remain - 2)
            G_crit = (n_remain - 1) / np.sqrt(n_remain) * np.sqrt(
                t_crit**2 / (n_remain - 2 + t_crit**2)
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
        mask = (data < Q1 - IQR_OUTLIER_MULTIPLIER * IQR) | (data > Q3 + IQR_OUTLIER_MULTIPLIER * IQR)
    else:
        if data_std < EPSILON:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据标准差接近零，无法进行 Z-score 异常检测"],
            )
        z = np.abs((data - data.mean()) / data_std)
        mask = z > ZSCORE_OUTLIER_THRESHOLD

    idx = data.index[mask]
    anomalies = req.data.loc[idx] if mask.sum() > 0 else pd.DataFrame()

    # 异常检测散点图
    fig = Figure(figsize=(9, 4))
    ax = fig.add_subplot(111)
    pos = np.arange(len(data))
    ax.plot(pos, data.values, "-", color=PALETTE["data"]["secondary"], linewidth=1, label="数据")
    ax.scatter(pos, data.values, s=10, color=PALETTE["data"]["primary"])
    if mask.sum() > 0:
        anomaly_pos = np.where(mask)[0]
        ax.scatter(anomaly_pos, data.values[mask], s=80, color=PALETTE["anomaly"]["primary"],
                   marker="x", linewidths=2.5, zorder=5, label=f"异常({mask.sum()}个)")
        if method == "iqr":
            lower_bound = Q1 - IQR_OUTLIER_MULTIPLIER * IQR
            upper_bound = Q3 + IQR_OUTLIER_MULTIPLIER * IQR
            ax.axhline(lower_bound, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"下界={lower_bound:.3f}")
            ax.axhline(upper_bound, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"上界={upper_bound:.3f}")
        elif method == "grubbs":
            # Grubbs 使用迭代临界值 (t 分布)，不画 ±3σ 线避免误导
            ax.axhline(data.mean(), color=PALETTE["spec"]["secondary"], linestyle=":",
                      linewidth=1, alpha=0.4, label=f"均值={data.mean():.3f}")
        else:
            ax.axhline(data.mean() + 3*data_std, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"上界={data.mean()+3*data_std:.3f}")
            ax.axhline(data.mean() - 3*data_std, color=PALETTE["spec"]["secondary"], linestyle="--",
                      linewidth=1, alpha=0.6, label=f"下界={data.mean()-3*data_std:.3f}")
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
