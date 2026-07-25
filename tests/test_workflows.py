"""端到端工作流集成测试 — 模拟真实分析场景。"""
import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.audit import process_audit
from smartsuite.services.data_io import missing_pattern_analysis, recommend_analysis
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture
def workflow_df():
    """模拟注塑工艺数据。"""
    np.random.seed(42)
    n = 150
    return pd.DataFrame({
        "temp": np.random.normal(200, 8, n),
        "mold_temp": np.random.normal(60, 8, n),
        "pressure": np.random.normal(80, 8, n),
        "speed": np.random.normal(50, 12, n),
        "cooling": np.random.normal(20, 4, n),
        "material": np.random.choice(["ABS", "PP", "PA6"], n),
        "maintenance": np.random.choice(["是", "否"], n, p=[0.15, 0.85]),
        "defect_rate": np.random.normal(4, 1.5, n),
    })


def test_workflow_root_cause_to_regression(workflow_df):
    """场景1: 要因筛选 → 回归建模。"""
    # Step 1: 相关性筛选
    r1 = orchestrate(AnalysisRequest(
        task="correlation", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
    ))
    assert r1.status == "ok"

    # Step 2: VIF 诊断
    r2 = orchestrate(AnalysisRequest(
        task="vif", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
    ))
    assert r2.status == "ok"

    # Step 3: 回归
    r3 = orchestrate(AnalysisRequest(
        task="regression", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
    ))
    assert r3.status == "ok"
    assert "r_squared" in r3.metadata


def test_workflow_hypothesis_to_anova(workflow_df):
    """场景2: 假设检验 → ANOVA → 事后比较。"""
    # Step 1: 两两对比
    r1 = orchestrate(AnalysisRequest(
        task="hypothesis_test", data=workflow_df, target_col="defect_rate",
        feature_cols=["maintenance"],
        params={"test": "auto", "group_col": "maintenance"},
    ))
    assert r1.status == "ok"

    # Step 2: 多组 ANOVA
    r2 = orchestrate(AnalysisRequest(
        task="anova", data=workflow_df, target_col="defect_rate",
        feature_cols=["material"],
    ))
    assert r2.status == "ok"

    # Step 3: 非参数验证
    r3 = orchestrate(AnalysisRequest(
        task="hypothesis_test", data=workflow_df, target_col="defect_rate",
        feature_cols=["material"],
        params={"test": "kruskal_wallis", "group_col": "material"},
    ))
    assert r3.status == "ok"


def test_workflow_spc_full(workflow_df):
    """场景3: SPC 全流程 — 控制图 → 能力 → 趋势 → 异常。"""
    # Step 1: 控制图
    r1 = orchestrate(AnalysisRequest(
        task="spc_cusum", data=workflow_df, target_col="defect_rate",
        params={"k": 0.5, "h": 5.0},
    ))
    assert r1.status == "ok"

    # Step 2: 过程能力
    r2 = orchestrate(AnalysisRequest(
        task="process_capability", data=workflow_df, target_col="defect_rate",
        params={"usl": 7.0, "lsl": 1.0, "target": 4.0},
    ))
    assert r2.status == "ok"

    # Step 3: 趋势预测
    r3 = orchestrate(AnalysisRequest(
        task="trend_forecast", data=workflow_df, target_col="defect_rate",
        params={"forecast_steps": 5},
    ))
    assert r3.status == "ok"

    # Step 4: 异常共识
    r4 = orchestrate(AnalysisRequest(
        task="outlier_consensus", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "pressure"],
    ))
    assert r4.status == "ok"


def test_workflow_data_quality(workflow_df):
    """场景4: 数据质量诊断 → 分析推荐。"""
    # Step 1: 缺失分析
    diag = missing_pattern_analysis(workflow_df)
    assert diag["total_rows"] == 150
    assert "summary" in diag

    # Step 2: 智能推荐
    rec = recommend_analysis(workflow_df, target_col="defect_rate")
    assert len(rec["recommendations"]) >= 3

    # Step 3: 正态性评估
    r3 = orchestrate(AnalysisRequest(
        task="normality_check", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "pressure", "speed"],
    ))
    assert r3.status == "ok"


def test_workflow_comprehensive_audit(workflow_df):
    """场景5: 综合过程审计。"""
    result = process_audit(
        workflow_df, target_col="defect_rate",
        feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
        usl=7.0, lsl=1.0, target=4.0, time_order=False,
    )
    assert "health_checks" in result
    assert len(result["health_checks"]) >= 5
    assert "overall_rating" in result


def test_workflow_model_evaluation(workflow_df):
    """场景6: 回归 → ROC 评估。"""
    # Step 1: 回归找出关键预测变量
    r1 = orchestrate(AnalysisRequest(
        task="regression", data=workflow_df, target_col="defect_rate",
        feature_cols=["temp", "pressure", "speed"],
    ))
    assert r1.status == "ok"

    # Step 2: 将缺陷率二值化后做 ROC
    high_defect = (workflow_df["defect_rate"] > workflow_df["defect_rate"].median())
    workflow_df["defect_high"] = np.where(high_defect, "高", "低")
    r2 = orchestrate(AnalysisRequest(
        task="roc_analysis", data=workflow_df, target_col="defect_high",
        feature_cols=["temp"],
    ))
    assert r2.status == "ok"


def test_workflow_nonparametric_full(workflow_df):
    """场景7: 非参数全路径。"""
    ri = orchestrate(AnalysisRequest(
        task="variance_test", data=workflow_df, target_col="defect_rate",
        feature_cols=["material"], params={"group_col": "material"},
    ))
    assert ri.status == "ok"

    rj = orchestrate(AnalysisRequest(
        task="hypothesis_test", data=workflow_df, target_col="defect_rate",
        feature_cols=["material"],
        params={"test": "kruskal_wallis", "group_col": "material"},
    ))
    assert rj.status == "ok"

    rk = orchestrate(AnalysisRequest(
        task="bootstrap_ci", data=workflow_df, target_col="defect_rate",
        params={"statistic": "median", "n_bootstrap": 200},
    ))
    assert rk.status == "ok"
