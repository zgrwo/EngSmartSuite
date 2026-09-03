"""化工批次数据集集成测试 — 端到端工作流验证。"""

import os

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import missing_pattern_analysis, recommend_analysis
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture(scope="module")
def chemical_df():
    """加载化工批次数据集。"""
    path = os.path.join(os.path.dirname(__file__), "test_chemical_data.xlsx")
    if not os.path.exists(path):
        pytest.skip("test_chemical_data.xlsx not found")
    return pd.read_excel(path)


def test_chemical_data_loaded(chemical_df):
    """验证化工数据集加载正确。"""
    assert len(chemical_df) == 300
    assert "收率" in chemical_df.columns
    assert "纯度" in chemical_df.columns


def test_chemical_correlation(chemical_df):
    """收率与工艺参数的相关性分析。"""
    feats = ["实际温度", "温度偏差", "压力", "搅拌速度", "反应时间", "pH值"]
    req = AnalysisRequest(
        task="correlation",
        data=chemical_df,
        target_col="收率",
        feature_cols=feats,
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # 引擎 r 与测试内逐对 dropna 独立重算对照；r/p 有界；最强因子双方一致
    tc = result.metadata["target_correlations"]
    tp = result.metadata["target_p_adjusted"]
    assert set(tc) == set(feats)
    manual = {}
    for f in feats:
        pair = chemical_df[["收率", f]].dropna()
        manual[f] = float(np.corrcoef(pair["收率"], pair[f])[0, 1])
        assert tc[f] == pytest.approx(manual[f], abs=1e-9)
        assert abs(tc[f]) <= 1 and 0 <= tp[f] <= 1
    assert max(manual, key=lambda k: abs(manual[k])) == max(tc, key=lambda k: abs(tc[k]))


def test_chemical_regression(chemical_df):
    """收率回归分析。"""
    req = AnalysisRequest(
        task="regression",
        data=chemical_df,
        target_col="收率",
        feature_cols=["实际温度", "压力", "搅拌速度", "反应时间", "pH值", "终点纯度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "r_squared" in result.metadata


def test_chemical_anova(chemical_df):
    """催化剂类型对收率的 ANOVA。"""
    req = AnalysisRequest(
        task="anova",
        data=chemical_df,
        target_col="收率",
        feature_cols=["催化剂类型"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。单因子 ANOVA F/p 与 scipy
    # f_oneway 独立重算对照（分组按数据实际类别动态构建）
    cats = [c for c in chemical_df["催化剂类型"].dropna().unique() if pd.notna(c)]
    grp = [chemical_df.loc[chemical_df["催化剂类型"] == c, "收率"].dropna() for c in cats]
    F, pF = stats.f_oneway(*grp)
    tbl = result.tables["anova_enhanced"]
    anova_row = tbl[tbl["来源"] == "Q('催化剂类型')"].iloc[0]
    assert float(anova_row["F值"]) == pytest.approx(F, abs=1e-9)
    assert float(anova_row["p值"]) == pytest.approx(pF, abs=1e-9)
    assert float(anova_row["η²"]) == pytest.approx(
        result.metadata["effect_sizes"]["Q('催化剂类型')"]["η²"], abs=1e-9
    )


def test_chemical_hypothesis_auto(chemical_df):
    """自动选择检验类型的工作流（二分类变量）。"""
    req = AnalysisRequest(
        task="hypothesis_test",
        data=chemical_df,
        target_col="收率",
        feature_cols=["外观检查"],
        params={"test": "auto", "group_col": "外观检查"},
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "p_value" in result.metadata


def test_chemical_capability(chemical_df):
    """过程能力分析。"""
    req = AnalysisRequest(
        task="process_capability",
        data=chemical_df,
        target_col="纯度",
        params={"usl": 99.5, "lsl": 95.0, "target": 97.5},
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① Pp=(USL−LSL)/(6·s) 用原始数据 ddof=1 标准差独立重算；② Cp≥Cpk、Pp≥Ppk
    raw = chemical_df["纯度"].dropna()
    md = result.metadata
    assert md["n"] == len(raw) == 300
    assert md["pp"] == pytest.approx((99.5 - 95.0) / (6 * raw.std(ddof=1)), abs=1e-9)
    assert md["cp"] >= md["cpk"] > 0
    assert md["pp"] >= md["ppk"] > 0


def test_chemical_trend(chemical_df):
    """收率趋势预测。"""
    req = AnalysisRequest(
        task="trend_forecast",
        data=chemical_df,
        target_col="收率",
        params={"forecast_steps": 5},
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。预测步数兑现 + RMSE 有限非负
    assert len(result.tables["forecast"]) == 5
    assert result.metadata["rmse"] > 0
    assert np.isfinite(result.metadata["rmse"])


def test_chemical_normality(chemical_df):
    """正态性评估。"""
    req = AnalysisRequest(
        task="normality_check",
        data=chemical_df,
        target_col="收率",
        feature_cols=["实际温度", "压力", "反应时间", "pH值", "纯度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status——引擎返回非数（如全零 p）也不拦。
    # ① 表行数 = 1 目标 + 5 特征；② 每列 Shapiro-Wilk p ∈ [0,1]；
    # ③ 目标列 p 与 scipy 独立重算对照（引擎表格 4 位舍入 → 容差 1e-3）
    tab = result.tables["normality_results"]
    expected_cols = ["收率"] + ["实际温度", "压力", "反应时间", "pH值", "纯度"]
    assert list(tab["列名"]) == expected_cols
    # 引擎表格中 p 值为格式化字符串 → 转数值后判界
    p_num = pd.to_numeric(tab["Shapiro-Wilk p"], errors="coerce")
    assert p_num.notna().all() and (p_num.between(0, 1)).all()
    raw = chemical_df["收率"].dropna()
    row_yield = tab[tab["列名"] == "收率"].iloc[0]
    assert row_yield["样本量"] == len(raw) == 300
    assert float(row_yield["Shapiro-Wilk p"]) == pytest.approx(stats.shapiro(raw).pvalue, abs=1e-3)


def test_chemical_outlier_consensus(chemical_df):
    """多方法异常共识。"""
    req = AnalysisRequest(
        task="outlier_consensus",
        data=chemical_df,
        target_col="收率",
        feature_cols=["实际温度", "压力"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status——若引擎恒报 0 异常也绿。
    # ① IQR 检出数与测试内独立重算（Q1/Q3 ± 1.5·IQR，目标列）一致；
    # ② 异常明细表行数 == 声明总数；③ 各方法计数有界 [0, n]
    raw = chemical_df["收率"].dropna()
    q1, q3 = raw.quantile([0.25, 0.75])
    iqr = q3 - q1
    manual_iqr = int(((raw < q1 - 1.5 * iqr) | (raw > q3 + 1.5 * iqr)).sum())
    assert result.metadata["iqr_count"] == manual_iqr
    assert len(result.tables["anomalies"]) == result.metadata["total_flagged"]
    for k in ("iqr_count", "zscore_count", "isoforest_count", "total_flagged"):
        assert 0 <= result.metadata[k] <= len(chemical_df)


def test_chemical_bootstrap(chemical_df):
    """Bootstrap 置信区间。"""
    req = AnalysisRequest(
        task="bootstrap_ci",
        data=chemical_df,
        target_col="收率",
        params={"statistic": "mean", "n_bootstrap": 500},
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① 样本量与原始数据一致；② 点估计 ≈ 样本均值（bootstrap 均值无偏）；
    # ③ 样本均值落在 CI 内（均值抽样分布核心性质）；④ CI 下界 < 上界
    raw = chemical_df["收率"].dropna()
    md = result.metadata
    assert md["n"] == len(raw) == 300
    assert md["point_estimate"] == pytest.approx(raw.mean(), abs=1e-9)
    assert md["ci_lower"] < md["ci_upper"]
    assert md["ci_lower"] <= raw.mean() <= md["ci_upper"]


def test_chemical_recommendation(chemical_df):
    """智能分析推荐。"""
    result = recommend_analysis(chemical_df, target_col="收率")
    assert "recommendations" in result
    assert len(result["recommendations"]) >= 3


def test_chemical_missing_analysis(chemical_df):
    """缺失模式分析。"""
    result = missing_pattern_analysis(chemical_df)
    assert result["total_rows"] == 300
    assert "summary" in result
