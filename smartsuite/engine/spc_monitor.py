import numpy as np
import pandas as pd

from matplotlib.figure import Figure
from sklearn.linear_model import LinearRegression

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult


def xbar_r_chart(req: AnalysisRequest) -> AnalysisResult:
    """X-bar 和 R 控制图。"""
    subgroup_col = req.params.get("subgroup_col", "子组")
    if subgroup_col not in req.data.columns:
        return AnalysisResult(
            task="spc_xbar",
            status="error",
            messages=[f"子组列「{subgroup_col}」不存在"],
        )

    subgroups = req.data.groupby(subgroup_col)[req.target_col]
    xbar = subgroups.mean()
    r = subgroups.max() - subgroups.min()

    if len(xbar) < 2:
        return AnalysisResult(
            task="spc_xbar", status="error", messages=["子组数量不足"]
        )

    xbar_bar = xbar.mean()
    r_bar = r.mean()
    n = int(subgroups.count().iloc[0]) if len(subgroups) > 0 else 5
    # X-bar/R 控制图常数表 (子组大小 n → A2, D3, D4)
    _XBR_CONSTANTS = {
        2: (1.880, 0, 3.267), 3: (1.023, 0, 2.574),
        4: (0.729, 0, 2.282), 5: (0.577, 0, 2.114),
        6: (0.483, 0, 2.004), 7: (0.419, 0.076, 1.924),
        8: (0.373, 0.136, 1.864), 9: (0.337, 0.184, 1.816),
        10: (0.308, 0.223, 1.777),
    }
    A2, D3, D4 = _XBR_CONSTANTS.get(n, _XBR_CONSTANTS[5])

    fig = Figure(figsize=(10, 8))
    ax1 = fig.add_subplot(211)
    ax1.plot(xbar.index, xbar.values, "o-", markersize=4)
    ax1.axhline(xbar_bar, color="green", linestyle="-", label=f"CL={xbar_bar:.3f}")
    ax1.axhline(xbar_bar + A2 * r_bar, color="red", linestyle="--")
    ax1.axhline(xbar_bar - A2 * r_bar, color="red", linestyle="--")
    ax1.set_title("X-bar 控制图")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(212)
    ax2.plot(r.index, r.values, "o-", markersize=4, color="orange")
    ax2.axhline(r_bar, color="green", linestyle="-", label=f"CL={r_bar:.3f}")
    ax2.axhline(D4 * r_bar, color="red", linestyle="--")
    ax2.axhline(D3 * r_bar, color="red", linestyle="--")
    ax2.set_title("R 控制图")
    ax2.legend(fontsize=8)

    xbar_ooc = (xbar > xbar_bar + A2 * r_bar) | (xbar < xbar_bar - A2 * r_bar)

    limits = pd.DataFrame(
        {
            "统计量": ["X-bar", "R"],
            "CL": [xbar_bar, r_bar],
            "UCL": [xbar_bar + A2 * r_bar, D4 * r_bar],
            "LCL": [xbar_bar - A2 * r_bar, D3 * r_bar],
        }
    )

    return AnalysisResult(
        task="spc_xbar",
        tables={"control_limits": limits},
        figures=[fig],
        summary=f"X-bar 控制图: 失控点 {xbar_ooc.sum()} 个",
        metadata={
            "xbar_mean": float(xbar_bar),
            "r_mean": float(r_bar),
            "xbar_ooc_count": int(xbar_ooc.sum()),
        },
    )


def process_capability_analysis(req: AnalysisRequest) -> AnalysisResult:
    """过程能力分析 Cp/Cpk。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 2:
        return AnalysisResult(
            task="process_capability",
            status="error",
            messages=["有效数据不足"],
        )

    usl = req.params.get("usl")
    lsl = req.params.get("lsl")

    mu = data.mean()
    sigma = data.std(ddof=1)
    mr = np.abs(np.diff(data.values))
    within_sigma = np.mean(mr) / 1.128 if len(mr) > 0 else sigma

    cp = (usl - lsl) / (6 * within_sigma) if usl and lsl else None
    cpk_val = (
        min((usl - mu) / (3 * within_sigma), (mu - lsl) / (3 * within_sigma))
        if usl and lsl and within_sigma > 0
        else None
    )

    judge = (
        "合格"
        if cpk_val and cpk_val >= 1.33
        else ("需改进" if cpk_val else "未提供规格限")
    )

    # 过程能力直方图 + 规格限
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot(111)
    ax.hist(data, bins=20, color="#6baed6", edgecolor="white", alpha=0.8)
    mean_val = float(mu)
    ax.axvline(mean_val, color="green", linestyle="-", linewidth=2, label=f"Mean={mean_val:.2f}")
    if lsl: ax.axvline(lsl, color="red", linestyle="--", linewidth=2, label=f"LSL={lsl}")
    if usl: ax.axvline(usl, color="red", linestyle="--", linewidth=2, label=f"USL={usl}")
    ax.set_xlabel(req.target_col, fontsize=9)
    ax.set_ylabel("频数", fontsize=9)
    ax.set_title(f"过程能力 — {req.target_col} (Cp={cp:.2f}, Cpk={cpk_val:.2f})" if cp else f"过程能力 — {req.target_col}")
    ax.legend(fontsize=8)
    fig.tight_layout()

    return AnalysisResult(
        task="process_capability",
        tables={
            "capability": pd.DataFrame({"指标": ["Cp", "Cpk"], "值": [cp, cpk_val]})
        },
        figures=[fig],
        summary=f"Cpk={cpk_val:.3f}, {judge}" if cpk_val is not None else judge,
        metadata={"cp": cp, "cpk": cpk_val, "mean": mean_val, "std": float(sigma)},
    )


def trend_forecast(req: AnalysisRequest) -> AnalysisResult:
    """简单线性趋势预测。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 3:
        return AnalysisResult(
            task="trend_forecast",
            status="error",
            messages=["有效数据不足(至少3个点)"],
        )

    steps = req.params.get("forecast_steps", 5)
    try:
        X = np.arange(len(data)).reshape(-1, 1)
        y = data.values
        model = LinearRegression().fit(X, y)
        future_X = np.arange(len(data), len(data) + steps).reshape(-1, 1)
        predictions = model.predict(future_X)
        conf = 1.96 * np.std(y - model.predict(X))

        forecast_df = pd.DataFrame(
            {
                "步数": range(1, steps + 1),
                "预测值": predictions,
                "下限": predictions - conf,
                "上限": predictions + conf,
            }
        )

        trend_dir = "上升" if model.coef_[0] > 0 else "下降"

        # 趋势预测图：历史数据 + 预测 + 置信带
        fig = Figure(figsize=(8, 4))
        ax = fig.add_subplot(111)
        hist_idx = np.arange(len(data))
        ax.plot(hist_idx, y, "o-", markersize=3, label="历史数据", color="#2171b5")
        fut_idx = np.arange(len(data), len(data) + steps)
        ax.plot(fut_idx, predictions, "o-", markersize=3, label="预测", color="#d94801")
        ax.fill_between(fut_idx, predictions - conf, predictions + conf,
                        alpha=0.2, color="#d94801", label=f"95% 置信带")
        ax.set_xlabel("时间点", fontsize=9)
        ax.set_ylabel(req.target_col, fontsize=9)
        ax.set_title(f"趋势预测 — {req.target_col} ({trend_dir})", fontsize=11)
        ax.legend(fontsize=8)
        fig.tight_layout()

        return AnalysisResult(
            task="trend_forecast",
            tables={"forecast": forecast_df},
            figures=[fig],
            summary=f"趋势{trend_dir}(斜率={model.coef_[0]:.4f}/步), 预测{steps}步",
            metadata={"slope": float(model.coef_[0]), "forecast_steps": steps},
        )
    except Exception as e:
        return AnalysisResult(
            task="trend_forecast", status="error",
            messages=["趋势预测模型拟合失败，请检查数据是否包含缺失值"])


def anomaly_detect(req: AnalysisRequest) -> AnalysisResult:
    """IQR / Z-score 异常检测。"""
    data = req.data[req.target_col].dropna()
    if len(data) < 5:
        return AnalysisResult(
            task="anomaly_detect",
            status="error",
            messages=["有效数据不足(至少5个点)"],
        )

    method = req.params.get("method", "iqr")

    if method == "iqr":
        Q1, Q3 = data.quantile(0.25), data.quantile(0.75)
        IQR = Q3 - Q1
        if IQR == 0:
            return AnalysisResult(
                task="anomaly_detect",
                status="error",
                messages=["数据无变化(IQR=0)，无法检测异常"],
            )
        mask = (data < Q1 - 1.5 * IQR) | (data > Q3 + 1.5 * IQR)
    else:
        z = np.abs((data - data.mean()) / (data.std() + 1e-10))
        mask = z > 3

    idx = data.index[mask]
    anomalies = req.data.loc[idx] if mask.sum() > 0 else pd.DataFrame()

    # 异常检测散点图
    fig = Figure(figsize=(8, 4))
    ax = fig.add_subplot(111)
    pos = np.arange(len(data))
    ax.plot(pos, data.values, "-", color="#6baed6", linewidth=1, label="数据")
    ax.scatter(pos, data.values, s=10, color="#2171b5")
    if mask.sum() > 0:
        anomaly_pos = [list(pos).index(i) for i in idx if i in pos]
        ax.scatter(anomaly_pos, data.values[mask], s=60, color="red",
                   marker="x", linewidths=2, zorder=5, label=f"异常({mask.sum()}个)")
    threshold = Q1 - 1.5 * IQR if method == "iqr" else data.mean() - 3 * data.std()
    ax.axhline(threshold, color="orange", linestyle="--", linewidth=1, alpha=0.5)
    ax.set_xlabel("序号", fontsize=9)
    ax.set_ylabel(req.target_col, fontsize=9)
    ax.set_title(f"异常检测 — {req.target_col} (方法: {method})", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()

    return AnalysisResult(
        task="anomaly_detect",
        tables={"anomalies": anomalies},
        figures=[fig],
        summary=f"检测到 {mask.sum()} 个异常点 (方法: {method})",
        metadata={"anomaly_count": int(mask.sum()), "method": method},
    )
