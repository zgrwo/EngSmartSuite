import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause import (
    anova_analysis,
    correlation_analysis,
    cronbach_alpha,
    decision_tree_analysis,
    hypothesis_test,
    vif_analysis,
)


def test_correlation_analysis_basic(sample_doe_data):
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = correlation_analysis(req)

    assert result.task == "correlation"
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables
    corr = result.tables["correlation_matrix"]
    assert corr.shape[0] >= 5
    assert corr.values.min() >= -1.0
    assert corr.values.max() <= 1.0
    assert len(result.summary) > 0


def test_anova_basic(sample_doe_data):
    req = AnalysisRequest(
        task="anova",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"alpha": 0.05},
    )
    result = anova_analysis(req)

    assert result.task == "anova"
    assert result.status == "ok"
    assert "anova_enhanced" in result.tables
    assert len(result.summary) > 0
    assert "r_squared" in result.metadata


def test_hypothesis_test_two_sample(sample_two_group_data):
    req = AnalysisRequest(
        task="hypothesis_test", data=sample_two_group_data,
        target_col="强度", feature_cols=["工艺"],
        params={"test": "ttest_ind", "group_col": "工艺"},
    )
    result = hypothesis_test(req)
    assert result.status == "ok"
    assert "p_value" in result.metadata
    assert len(result.summary) > 0


def test_decision_tree(sample_doe_data):
    req = AnalysisRequest(
        task="decision_tree", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
        params={"max_depth": 3},
    )
    result = decision_tree_analysis(req)
    assert result.status == "ok"
    assert "feature_importance" in result.tables
    fi = result.tables["feature_importance"]
    assert "综合重要性" in fi.columns
    assert len(fi) >= 1


def test_vif_analysis(sample_doe_data):
    req = AnalysisRequest(
        task="vif", data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = vif_analysis(req)
    assert result.status == "ok"
    assert "vif_table" in result.tables


def test_mcnemar_numeric_binary_data():
    """验证 McNemar 检验对数值型二值数据 (0/1) 正确计数（修复 P0 Bug F2.1）。"""
    import numpy as np
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.engine.root_cause import hypothesis_test

    # 构造明显不对称的数据: 大量 0→1 翻转，极少 1→0 翻转
    # 修复前 str() Bug 会导致此数据产生全零计数和 p=1.0
    before = np.array([0] * 25 + [1] * 25)
    after = np.array([1] * 22 + [0] * 3 + [0] * 3 + [1] * 22)
    df = pd.DataFrame({"before": before, "after": after})

    req = AnalysisRequest(task="hypothesis_test", data=df, target_col="before",
                          feature_cols=["before", "after"],
                          params={"test": "mcnemar"})
    result = hypothesis_test(req)
    assert result.status == "ok"
    # b≈3, c≈22 → McNemar 应高度显著（p << 0.001）
    p_val = result.metadata["p_value"]
    assert p_val < 0.001, f"McNemar should detect significant change, got p={p_val:.4f} (bug: all counts may be zero)"


def test_cronbach_zero_variance_item():
    """验证 Cronbach's α 对零方差题项不崩溃（修复 P2 Bug F2.10）。"""
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.engine.root_cause import cronbach_alpha

    # 一个题项零方差（所有值相同）
    df = pd.DataFrame({
        "item1": [5.0, 5.0, 5.0, 5.0, 5.0],  # 零方差
        "item2": [1.0, 3.0, 2.0, 4.0, 3.0],
        "item3": [2.0, 4.0, 3.0, 5.0, 4.0],
    })
    req = AnalysisRequest(task="cronbach_alpha", data=df, target_col="item1",
                          feature_cols=["item1", "item2", "item3"])
    result = cronbach_alpha(req)
    # 不应崩溃，status 为 ok（α 可计算或返回错误均可，但不能崩溃）
    assert result.status in ("ok", "error")
