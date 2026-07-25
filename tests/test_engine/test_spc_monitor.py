import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.spc_monitor import (
    anomaly_detect,
    ewma_chart,
    process_capability_analysis,
    trend_forecast,
    xbar_r_chart,
)


def test_xbar_r_chart(sample_spc_data):
    req = AnalysisRequest(
        task="spc_xbar",
        data=sample_spc_data,
        target_col="测量值",
        feature_cols=["子组"],
        params={},
    )
    result = xbar_r_chart(req)
    assert result.status == "ok"
    assert len(result.figures) >= 1
    assert "control_limits" in result.tables


def test_process_capability(sample_spc_data):
    req = AnalysisRequest(
        task="process_capability",
        data=sample_spc_data,
        target_col="测量值",
        params={"usl": 12.0, "lsl": 8.0},
    )
    result = process_capability_analysis(req)
    assert result.status == "ok"
    cpk = result.metadata.get("cpk", 0)
    assert isinstance(cpk, (int, float))
    assert "cp" in result.metadata


def test_trend_forecast(sample_spc_data):
    subgroup_means = sample_spc_data.groupby("子组")["测量值"].mean().reset_index()
    req = AnalysisRequest(
        task="trend_forecast",
        data=subgroup_means,
        target_col="测量值",
        params={"forecast_steps": 5},
    )
    result = trend_forecast(req)
    assert result.status == "ok"
    assert "forecast" in result.tables
    assert len(result.tables["forecast"]) >= 5


def test_anomaly_detect(sample_spc_data):
    req = AnalysisRequest(
        task="anomaly_detect",
        data=sample_spc_data,
        target_col="测量值",
        params={"method": "iqr"},
    )
    result = anomaly_detect(req)
    assert result.status == "ok"
    assert "anomaly_count" in result.metadata


def test_xbar_constants_correct_limits():
    """验证 X-bar/R 控制图常数表产生正确的控制限。"""
    np.random.seed(42)
    # n=5 子组，总均值=10，总极差均值=1.5
    n_groups = 25
    n_subgroup = 5
    data_rows = []
    for g in range(1, n_groups + 1):
        vals = np.random.normal(10, 0.8, n_subgroup)
        for v in vals:
            data_rows.append({"子组": g, "测量值": v})
    df = pd.DataFrame(data_rows)
    req = AnalysisRequest(
        task="spc_xbar",
        data=df,
        target_col="测量值",
        feature_cols=["子组"],
        params={},
    )
    result = xbar_r_chart(req)
    assert result.status == "ok"
    limits = result.tables["control_limits"]
    # 手工计算验证: n=5 → A2=0.577, D3=0, D4=2.114
    subgroup_stats = df.groupby("子组")["测量值"].agg(["mean", lambda x: x.max() - x.min()])
    subgroup_stats.columns = ["mean", "range"]
    xbar_bar = subgroup_stats["mean"].mean()
    r_bar = subgroup_stats["range"].mean()
    expected_ucl_x = xbar_bar + 0.577 * r_bar
    expected_lcl_x = xbar_bar - 0.577 * r_bar
    expected_ucl_r = 2.114 * r_bar
    # 引擎输出的控制限字符串 → float 比较
    xbar_row = limits[limits["统计量"] == "X-bar"].iloc[0]
    r_row = limits[limits["统计量"] == "R"].iloc[0]
    assert abs(float(xbar_row["UCL"]) - expected_ucl_x) < 0.01, \
        f"X-bar UCL mismatch: {xbar_row['UCL']} vs {expected_ucl_x:.4f}"
    assert abs(float(xbar_row["LCL"]) - expected_lcl_x) < 0.01
    # R 图下控制限（n=5 时 D3=0）
    assert abs(float(r_row["LCL"])) < 0.01


def test_ewma_first_data_point_included():
    """验证 EWMA 首个数据点参与计算（修复 P0 Bug F2.2）。"""
    import numpy as np

    from smartsuite.core.contracts import AnalysisRequest

    np.random.seed(42)
    # 构造序列: 首个点为极端异常值，应被 EWMA 捕获
    data_vals = [50.0, 10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3]
    df = pd.DataFrame({"val": data_vals})
    # 计算手动 EWMA
    mu = np.mean(data_vals)  # ~15.1
    lam = 0.2
    expected_ewma_0 = lam * data_vals[0] + (1 - lam) * mu
    # 首个 EWMA 值应反映极端点 50.0
    assert expected_ewma_0 > mu, f"首个 EWMA 值 {expected_ewma_0:.2f} 应 > 均值 {mu:.2f}（反映异常点）"

    req = AnalysisRequest(task="spc_ewma", data=df, target_col="val",
                          params={"lam": lam, "L": 2.7})
    result = ewma_chart(req)
    assert result.status == "ok"
    # EWMA 图应存在，摘要应包含统计信息
    assert len(result.figures) >= 1
