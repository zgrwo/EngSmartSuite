"""端到端工作流集成测试 — 模拟真实分析场景。"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.audit import process_audit
from smartsuite.services.data_io import missing_pattern_analysis, recommend_analysis
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture
def workflow_df():
    """模拟注塑工艺数据。"""
    np.random.seed(42)
    n = 150
    return pd.DataFrame(
        {
            "temp": np.random.normal(200, 8, n),
            "mold_temp": np.random.normal(60, 8, n),
            "pressure": np.random.normal(80, 8, n),
            "speed": np.random.normal(50, 12, n),
            "cooling": np.random.normal(20, 4, n),
            "material": np.random.choice(["ABS", "PP", "PA6"], n),
            "maintenance": np.random.choice(["是", "否"], n, p=[0.15, 0.85]),
            "defect_rate": np.random.normal(4, 1.5, n),
        }
    )


def test_workflow_root_cause_to_regression(workflow_df):
    """场景1: 要因筛选 → 回归建模。"""
    # Step 1: 相关性筛选
    r1 = orchestrate(
        AnalysisRequest(
            task="correlation",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
        )
    )
    assert r1.status == "ok"

    # Step 2: VIF 诊断
    r2 = orchestrate(
        AnalysisRequest(
            task="vif",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
        )
    )
    assert r2.status == "ok"

    # Step 3: 回归
    r3 = orchestrate(
        AnalysisRequest(
            task="regression",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
        )
    )
    assert r3.status == "ok"
    assert "r_squared" in r3.metadata


def test_workflow_hypothesis_to_anova(workflow_df):
    """场景2: 假设检验 → ANOVA → 事后比较。"""
    # Step 1: 两两对比
    r1 = orchestrate(
        AnalysisRequest(
            task="hypothesis_test",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["maintenance"],
            params={"test": "auto", "group_col": "maintenance"},
        )
    )
    assert r1.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。auto 对二组方差齐时选学生 t（等方差）；
    # 与 scipy 独立重算对照（组序可能致符号翻转 → 比较 |t|）
    g_yes = workflow_df.loc[workflow_df["maintenance"] == "是", "defect_rate"]
    g_no = workflow_df.loc[workflow_df["maintenance"] == "否", "defect_rate"]
    manual = stats.ttest_ind(g_yes, g_no, equal_var=True)
    assert abs(r1.metadata["statistic"]) == pytest.approx(abs(manual.statistic), abs=1e-9)
    assert r1.metadata["p_value"] == pytest.approx(manual.pvalue, abs=1e-9)

    # Step 2: 多组 ANOVA
    r2 = orchestrate(
        AnalysisRequest(
            task="anova",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["material"],
        )
    )
    assert r2.status == "ok"
    # 审查 2026-09-04 补充：单因子 ANOVA F/p 与 scipy f_oneway 独立重算对照
    grp = [
        workflow_df.loc[workflow_df["material"] == m, "defect_rate"] for m in ["ABS", "PP", "PA6"]
    ]
    F, pF = stats.f_oneway(*grp)
    anova_tbl = r2.tables["anova_enhanced"]
    anova_row = anova_tbl[anova_tbl["来源"] == "Q('material')"].iloc[0]
    assert anova_row["F值"] == pytest.approx(F, abs=1e-9)
    assert anova_row["p值"] == pytest.approx(pF, abs=1e-9)

    # Step 3: 非参数验证
    r3 = orchestrate(
        AnalysisRequest(
            task="hypothesis_test",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["material"],
            params={"test": "kruskal_wallis", "group_col": "material"},
        )
    )
    assert r3.status == "ok"
    H, pK = stats.kruskal(*grp)
    assert r3.metadata["statistic"] == pytest.approx(H, abs=1e-9)
    assert r3.metadata["p_value"] == pytest.approx(pK, abs=1e-9)


def test_workflow_spc_full(workflow_df):
    """场景3: SPC 全流程 — 控制图 → 能力 → 趋势 → 异常。"""
    # Step 1: 控制图
    r1 = orchestrate(
        AnalysisRequest(
            task="spc_cusum",
            data=workflow_df,
            target_col="defect_rate",
            params={"k": 0.5, "h": 5.0},
        )
    )
    assert r1.status == "ok"
    # 审查 2026-09-04 补充：报警数非负 + 结果表存在（此前仅 status）
    assert r1.metadata["total_alarms"] >= 0
    assert "cusum_stats" in r1.tables

    # Step 2: 过程能力
    r2 = orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=workflow_df,
            target_col="defect_rate",
            params={"usl": 7.0, "lsl": 1.0, "target": 4.0},
        )
    )
    assert r2.status == "ok"
    # 审查 2026-09-04 补充：① Pp=(USL−LSL)/(6·s) 用原始数据 ddof=1 标准差独立重算；
    # ② 数学不变量 Cp≥Cpk、Pp≥Ppk；③ n 与数据一致
    md2 = r2.metadata
    s = workflow_df["defect_rate"].std(ddof=1)
    assert md2["pp"] == pytest.approx((7.0 - 1.0) / (6 * s), abs=1e-9)
    assert md2["cp"] >= md2["cpk"] > 0
    assert md2["pp"] >= md2["ppk"] > 0
    assert md2["n"] == len(workflow_df)

    # Step 3: 趋势预测
    r3 = orchestrate(
        AnalysisRequest(
            task="trend_forecast",
            data=workflow_df,
            target_col="defect_rate",
            params={"forecast_steps": 5},
        )
    )
    assert r3.status == "ok"
    # 审查 2026-09-04 补充：预测步数兑现 + RMSE 有限非负
    assert len(r3.tables["forecast"]) == 5
    assert r3.metadata["rmse"] > 0
    assert np.isfinite(r3.metadata["rmse"])

    # Step 4: 异常共识
    r4 = orchestrate(
        AnalysisRequest(
            task="outlier_consensus",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "pressure"],
        )
    )
    assert r4.status == "ok"
    # 审查 2026-09-04 补充：计数有界 + 明细表行数 == 声明总数（此前仅 status）
    assert len(r4.tables["anomalies"]) == r4.metadata["total_flagged"]
    for k in ("iqr_count", "zscore_count", "isoforest_count", "total_flagged"):
        assert 0 <= r4.metadata[k] <= len(workflow_df)


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
    r3 = orchestrate(
        AnalysisRequest(
            task="normality_check",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "pressure", "speed"],
        )
    )
    assert r3.status == "ok"


def test_workflow_comprehensive_audit(workflow_df):
    """场景5: 综合过程审计。"""
    result = process_audit(
        workflow_df,
        target_col="defect_rate",
        feature_cols=["temp", "mold_temp", "pressure", "speed", "cooling"],
        usl=7.0,
        lsl=1.0,
        target=4.0,
        time_order=False,
    )
    assert "health_checks" in result
    assert len(result["health_checks"]) >= 5
    assert "overall_rating" in result


def test_workflow_model_evaluation(workflow_df):
    """场景6: 回归 → ROC 评估。"""
    # Step 1: 回归找出关键预测变量
    r1 = orchestrate(
        AnalysisRequest(
            task="regression",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["temp", "pressure", "speed"],
        )
    )
    assert r1.status == "ok"
    # 审查 2026-09-04 补充：F 统计量/p 有界；系数表行数 = 截距 + 3 自变量
    assert 0 <= r1.metadata["f_pvalue"] <= 1
    assert r1.metadata["f_statistic"] >= 0
    assert len(r1.tables["coefficients"]) == 4

    # Step 2: 将缺陷率二值化后做 ROC
    high_defect = workflow_df["defect_rate"] > workflow_df["defect_rate"].median()
    workflow_df["defect_high"] = np.where(high_defect, "高", "低")
    r2 = orchestrate(
        AnalysisRequest(
            task="roc_analysis",
            data=workflow_df,
            target_col="defect_high",
            feature_cols=["temp"],
        )
    )
    assert r2.status == "ok"
    # 审查 2026-09-04 补充：AUC ∈ [0,1] 且 ROC 点表非平凡
    assert 0 <= r2.metadata["auc"] <= 1
    assert len(r2.tables["roc_points"]) >= 2


def test_workflow_nonparametric_full(workflow_df):
    """场景7: 非参数全路径。"""
    ri = orchestrate(
        AnalysisRequest(
            task="variance_test",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["material"],
            params={"group_col": "material"},
        )
    )
    assert ri.status == "ok"
    # 审查 2026-09-04 补充：Levene(center=median)/Bartlett p 与 scipy 独立重算对照
    grp = [
        workflow_df.loc[workflow_df["material"] == m, "defect_rate"] for m in ["ABS", "PP", "PA6"]
    ]
    assert ri.metadata["n_groups"] == 3
    assert ri.metadata["levene_p"] == pytest.approx(
        stats.levene(*grp, center="median").pvalue, abs=1e-9
    )
    assert ri.metadata["bartlett_p"] == pytest.approx(stats.bartlett(*grp).pvalue, abs=1e-9)

    rj = orchestrate(
        AnalysisRequest(
            task="hypothesis_test",
            data=workflow_df,
            target_col="defect_rate",
            feature_cols=["material"],
            params={"test": "kruskal_wallis", "group_col": "material"},
        )
    )
    assert rj.status == "ok"
    H, pK = stats.kruskal(*grp)
    assert rj.metadata["statistic"] == pytest.approx(H, abs=1e-9)
    assert rj.metadata["p_value"] == pytest.approx(pK, abs=1e-9)

    rk = orchestrate(
        AnalysisRequest(
            task="bootstrap_ci",
            data=workflow_df,
            target_col="defect_rate",
            params={"statistic": "median", "n_bootstrap": 200},
        )
    )
    assert rk.status == "ok"
    # 审查 2026-09-04 补充：原始中位数落在 CI 内且点估计与其接近
    raw_median = float(workflow_df["defect_rate"].median())
    assert rk.metadata["n"] == len(workflow_df)
    assert rk.metadata["ci_lower"] <= raw_median <= rk.metadata["ci_upper"]
    assert rk.metadata["point_estimate"] == pytest.approx(raw_median, abs=0.1)
