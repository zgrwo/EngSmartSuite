"""趋势预测（原 detection.py 的 trend_forecast，2026-09-21 拆分）。"""

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
)
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import durbin_watson, round_for_display

logger = logging.getLogger(__name__)


def _acf_values(residuals, max_lag):
    """标准自相关序列 r_0..r_max_lag（全样本均值定义）。

    Round-2 #A3a：np.corrcoef 对两段残差分别减各自均值 → 自相关系统性偏大
    （白噪声 p≈0.04 可翻转 0.05 阈值）；此处统一采用全样本均值的标准自相关定义，
    与 Ljung-Box 检验、statsmodels acf 一致。r_0 恒为 1.0；零方差残差除 r_0 外返回 0。
    """
    x = np.asarray(residuals, dtype=float)
    mean = float(x.mean())
    denom = float(np.sum((x - mean) ** 2))
    # 审查 2026-09-06 B3：绝对阈值 1e-12 误判微尺度残差（~1e-13，纳米/微应变数据），
    # 真实自相关 [1,0.45,...] 被静默吞为 [1,0,0]。改相对判据（与 exploratory.py ssx 同族）：
    # 真常量残差 denom/Σx² ~ eps² 仍命中退化分支；微尺度真实波动比值 ~O(1) 不再误判。
    if denom <= 1e-12 * max(float(np.sum(x**2)), 1e-300):
        return [1.0] + [0.0] * max_lag  # 零方差残差：除 lag0 外自相关无定义
    return [1.0] + [
        float(np.sum((x[:-k] - mean) * (x[k:] - mean)) / denom) for k in range(1, max_lag + 1)
    ]


def _ljung_box(residuals, lags=None):
    """Ljung-Box 检验 — 残差自相关的整体显著性检验。"""
    n = len(residuals)
    if lags is None:
        lags = min(10, n // 5)
    lags = max(1, min(lags, n // 2))
    # Round-2 #A3a：使用全样本均值的标准自相关定义（见 _acf_values）
    acfs = _acf_values(residuals, lags)
    acf_sum = sum(acfs[k] ** 2 / (n - k) for k in range(1, lags + 1))
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

    # Round-2 #A3b：常量序列 → sklearn R²=1.0 假完美拟合
    # 审查 2026-09-05 B1：绝对阈值 1e-12 误判微尺度数据（std~1e-13，如单位换算后的
    # 纳米/微应变数据）→ 相对阈值，复用 spc_xbar 同族修法（spc_charts 相对判据）
    # 审查 2026-09-16 B-4：去掉 `_scale=1.0` 兜底（pico 级真实波动不再误报常量），
    # 阈值相对数据自身幅值 |x|max
    _abs_scale = float(np.max(np.abs(data.values)))
    if _abs_scale == 0 or float(np.std(data.values, ddof=1)) <= 1e-12 * _abs_scale:
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=["目标列为常量列（无变异），趋势预测无意义。"],
        )

    # Round-2 #A3b：forecast_steps 类型/范围校验（字符串/浮点此前 TypeError）
    steps = req.params.get("forecast_steps", 5)
    try:
        steps = int(steps)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=[f"forecast_steps 必须是正整数，当前: {steps!r}"],
        )
    if steps < 1 or steps > 1000:
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=[f"forecast_steps 必须在 1~1000 之间，当前: {steps}"],
        )
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
        # 审查 2026-09-16 D-2：原 |y|>EPSILON 绝对掩码会把微尺度序列（~1e-11）
        # 整体排除 → MAPE 恒 N/A；改精确零判据（MAPE 为比值，量纲无关）
        mape_mask = np.abs(y) > 0
        mape = (
            float(np.mean(np.abs(residuals[mape_mask] / y[mape_mask])) * 100)
            if mape_mask.sum() > 0
            else None
        )
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
            se_future = resid_std_se * np.sqrt(1 + 1 / n + (x_future - x_mean) ** 2 / ssx)
            future_conf.append(float(t_crit * se_future))
        conf_array = np.array(future_conf)

        forecast_df = pd.DataFrame(
            {
                "步数": range(1, steps + 1),
                # 审查 2026-09-05 新观察 O-1：固定 4 位小数把微尺度预测（~1e-10）
                # 整列显示为 0.0000 → 尺度感知舍入（常规量级行为不变）
                "预测值": round_for_display(predictions),
                "下限": round_for_display(predictions - conf_array),
                "上限": round_for_display(predictions + conf_array),
            }
        )

        # ── 精度指标表 ──
        lb_label = f"显著自相关 (p={lb_p:.4f})" if lb_p < 0.05 else f"无显著自相关 (p={lb_p:.4f})"
        metrics_df = pd.DataFrame(
            {
                "指标": [
                    "R²",
                    "调整R²",
                    "RMSE",
                    "MAE",
                    "MAPE (%)",
                    "Durbin-Watson",
                    "Ljung-Box Q",
                    "Ljung-Box p",
                    "残差诊断",
                    "样本量",
                    "预测步数",
                    "斜率 (每步)",
                    "截距",
                ],
                "值": [
                    f"{r2:.4f}",
                    f"{adj_r2:.4f}",
                    f"{rmse:.4f}",
                    f"{mae:.4f}",
                    f"{mape:.2f}%" if mape is not None else "N/A",
                    f"{dw:.4f}",
                    f"{lb_q:.3f}",
                    f"{lb_p:.4f}",
                    f"{dw_label}; {lb_label}",
                    str(n),
                    str(steps),
                    f"{float(model.coef_[0]):.6f}",
                    f"{float(model.intercept_):.4f}",
                ],
            }
        )

        trend_dir = "上升" if model.coef_[0] > 0 else "下降"

        # ── ACF 计算（Round-2 #A3a：全样本均值标准自相关，与 Ljung-Box 一致）──
        max_lag = min(20, n // 4)
        acf_vals = _acf_values(residuals, max_lag)
        acf_conf = float(sp_stats.norm.ppf(0.975)) / np.sqrt(n)  # 95% 置信限

        # ── 增强图表：2×2 布局 ──
        fig = Figure(figsize=(13, 9))

        # 左上：趋势 + 预测 + 置信带（大样本时去掉点标记）
        ax1 = fig.add_subplot(2, 2, 1)
        hist_idx = np.arange(n)
        if n > 300:
            ax1.plot(
                hist_idx,
                y,
                "-",
                linewidth=0.8,
                label="历史数据",
                color=PALETTE["data"]["primary"],
            )
        else:
            ax1.plot(
                hist_idx,
                y,
                "o-",
                markersize=3,
                label="历史数据",
                color=PALETTE["data"]["primary"],
                linewidth=1.2,
            )
        ax1.plot(
            hist_idx,
            y_pred_in,
            "-",
            color=PALETTE["data"]["secondary"],
            linewidth=2,
            alpha=0.6,
            label=f"趋势线 (R²={r2:.3f})",
        )
        fut_idx = np.arange(n, n + steps)
        ax1.plot(
            fut_idx,
            predictions,
            "o-",
            markersize=4,
            label="预测",
            color=PALETTE["target"]["primary"],
        )
        ax1.fill_between(
            fut_idx,
            predictions - conf_array,
            predictions + conf_array,
            alpha=0.2,
            color=PALETTE["target"]["primary"],
            label="95% 预测区间",
        )
        # 预测区高亮 + 标注，避免预测点被上千个历史点淹没
        ax1.axvspan(n + 0.5, n + steps + 0.5, color=PALETTE["misc"]["grid"], alpha=0.12, zorder=0)
        _last_pred = float(predictions[-1])
        _last_conf = float(conf_array[-1])
        ax1.annotate(
            f"预测 {_last_pred:.2f}\n95%区间 [{_last_pred - _last_conf:.2f}, {_last_pred + _last_conf:.2f}]",
            xy=(n + steps, _last_pred),
            xytext=(-36, 26),
            textcoords="offset points",
            ha="right",
            fontsize=8,
            color=PALETTE["target"]["primary"],
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", alpha=0.85, edgecolor="none"),
            arrowprops=dict(arrowstyle="->", color=PALETTE["target"]["primary"], lw=0.8),
        )
        ax1.set_xlabel("时间点", fontsize=9)
        ax1.set_ylabel(req.target_col, fontsize=9)
        ax1.set_title(f"趋势预测 — {req.target_col} ({trend_dir})", fontsize=10)
        ax1.legend(fontsize=8, ncol=2)

        # 右上：残差图
        ax2 = fig.add_subplot(2, 2, 2)
        ax2.scatter(hist_idx, residuals, s=12, color=PALETTE["data"]["secondary"], alpha=0.7)
        ax2.axhline(0, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1)
        ax2.plot(
            hist_idx, residuals, "-", color=PALETTE["data"]["secondary"], alpha=0.3, linewidth=0.5
        )
        ax2.set_xlabel("时间点", fontsize=9)
        ax2.set_ylabel("残差", fontsize=9)
        ax2.set_title(f"残差 — {dw_label}", fontsize=10)

        # 左下：ACF 自相关图
        ax3 = fig.add_subplot(2, 2, 3)
        lags = range(max_lag + 1)
        ax3.bar(lags, acf_vals, color=PALETTE["data"]["secondary"], width=0.4, edgecolor="white")
        ax3.axhline(0, color=PALETTE["direction"]["zero"], linewidth=0.5)
        ax3.axhline(
            acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6
        )
        ax3.axhline(
            -acf_conf, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=0.8, alpha=0.6
        )
        ax3.set_xlabel("滞后阶数", fontsize=9)
        ax3.set_ylabel("自相关 (ACF)", fontsize=9)
        if max_lag >= 5:
            ax3.set_xticks(range(0, max_lag + 1, 5))
        ax3.set_title("残差自相关 (ACF)", fontsize=10)

        # 右下：实际值 vs 预测值
        ax4 = fig.add_subplot(2, 2, 4)
        ax4.scatter(y_pred_in, y, s=12, alpha=0.6, color=PALETTE["data"]["primary"])
        ax4.plot(
            [y.min(), y.max()],
            [y.min(), y.max()],
            color=PALETTE["anomaly"]["primary"],
            linestyle="--",
            linewidth=1,
        )
        ax4.set_xlabel("预测值", fontsize=9)
        ax4.set_ylabel("实际值", fontsize=9)
        ax4.set_title(f"实际值 vs 预测值 (R²={r2:.3f})", fontsize=10)
        fig.tight_layout()

        # ── 汇总 ──
        mape_str = f"{mape:.1f}%" if mape is not None else "N/A"
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
                "r_squared": r2,
                "r_squared_adj": adj_r2,
                "rmse": rmse,
                "mae": mae,
                "mape": mape,
                "durbin_watson": dw,
                "dw_interpretation": dw_label,
                "ljung_box_q": lb_q,
                "ljung_box_p": lb_p,
                "ljung_box_lags": lb_lags,
                "forecast_steps": steps,
                "n": n,
            },
        )
    except (ValueError, np.linalg.LinAlgError) as e:
        logger.warning("趋势预测模型拟合失败: %s", e)
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=[
                "趋势预测模型拟合失败，数据可能不足或存在共线性问题，"
                "请检查数据中是否包含足够的有效观测值。"
            ],
        )
