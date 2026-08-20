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
    """Cronbach's α 对零方差题项：精确断言（Round-2 批次D #2c）。

    实测引擎行为（已验证）：零方差题项被排除出方差和但参与题项数 k，
    α=(k/(k-1))*(1-Σvar_i/var_total) 仍可计算 → status=ok，α≈0.75，
    且该题项的项总相关标记为 "N/A (零方差)"。此前 assert in ("ok","error")
    恒真——任何结果都通过。
    """
    from smartsuite.core.contracts import AnalysisRequest

    # 一个题项零方差（所有值相同）
    df = pd.DataFrame({
        "item1": [5.0, 5.0, 5.0, 5.0, 5.0],  # 零方差
        "item2": [1.0, 3.0, 2.0, 4.0, 3.0],
        "item3": [2.0, 4.0, 3.0, 5.0, 4.0],
    })
    req = AnalysisRequest(task="cronbach_alpha", data=df, target_col="item1",
                          feature_cols=["item1", "item2", "item3"])
    result = cronbach_alpha(req)
    assert result.status == "ok", f"零方差题项应可计算 α: {result.messages}"
    alpha = result.metadata["alpha"]
    assert 0.7 < alpha < 0.8, f"α 应为 0.75 左右（k=3, 一个零方差项），实际 {alpha:.4f}"
    assert result.metadata["k"] == 3 and result.metadata["n"] == 5
    item_tbl = result.tables["item_analysis"]
    zero_row = item_tbl[item_tbl["题项"] == "item1"]
    assert len(zero_row) == 1
    assert "零方差" in str(zero_row.iloc[0]["项总相关"]), (
        f"零方差题项应标记 'N/A (零方差)': {zero_row.iloc[0]['项总相关']}"
    )
    assert float(zero_row.iloc[0]["方差"]) == 0.0
def test_hypothesis_kruskal_group_col_none_injection(sample_two_group_data):
    """审查 2026-08-19 #1.1：orchestrator 注入 group_col=None 时 kruskal 分支不得 KeyError，
    应回退到 feature_cols[0]。"""
    from smartsuite.services.orchestrator import orchestrate

    req = AnalysisRequest(
        task="hypothesis_test", data=sample_two_group_data,
        target_col="强度", feature_cols=["工艺"],
        params={"test": "kruskal", "alpha": 0.05},  # 不传 group_col → orchestrator 注入 None
    )
    result = orchestrate(req)
    assert result.status == "ok", f"kruskal 失败: {result.messages}"
    assert result.metadata.get("test") == "Kruskal-Wallis H 检验 (非参数 ANOVA)"


def test_hypothesis_jonckheere_group_col_none_injection():
    """审查 2026-08-19 #1.1：jonckheere 分支同样不得 KeyError。"""
    from smartsuite.services.orchestrator import orchestrate

    rng = np.random.RandomState(7)
    df = pd.DataFrame({
        "val": np.concatenate([
            rng.normal(10, 1, 12), rng.normal(12, 1, 12), rng.normal(14, 1, 12),
        ]),
        "level": ["低"] * 12 + ["中"] * 12 + ["高"] * 12,
    })
    req = AnalysisRequest(
        task="hypothesis_test", data=df,
        target_col="val", feature_cols=["level"],
        params={"test": "jonckheere", "alpha": 0.05},
    )
    result = orchestrate(req)
    assert result.status == "ok", f"jonckheere 失败: {result.messages}"
    assert "Jonckheere" in result.metadata.get("test", "")


def test_hypothesis_kruskal_group_col_missing_column():
    """审查 2026-08-19 #2.10：group_col 指向不存在的列应返回明确中文错误而非 KeyError。"""
    from smartsuite.services.orchestrator import orchestrate

    df = pd.DataFrame({"val": np.random.RandomState(1).normal(0, 1, 30)})
    req = AnalysisRequest(
        task="hypothesis_test", data=df,
        target_col="val", feature_cols=[],
        params={"test": "kruskal", "group_col": "不存在的列", "alpha": 0.05},
    )
    result = orchestrate(req)
    assert result.status == "error"
    assert any("不存在的列" in m for m in result.messages)


def test_hypothesis_ks_group_col_none_injection():
    """Round-2 批次D #4c：orchestrate 路径不传 group_col（DEFAULT_PARAMS 注入 None）
    时 KS 双样本不得 KeyError，应回退 feature_cols[0] 正常执行。"""
    from smartsuite.services.orchestrator import orchestrate

    np.random.seed(7)
    df = pd.DataFrame({
        "y": np.concatenate([np.random.normal(10, 1, 50), np.random.normal(12, 1, 50)]),
        "g": ["A"] * 50 + ["B"] * 50,
    })
    req = AnalysisRequest(task="hypothesis_test", data=df, target_col="y",
                          feature_cols=["g"], params={"test": "ks", "alpha": 0.05})
    result = orchestrate(req)
    assert result.status == "ok", f"KS group_col=None 注入应正常: {result.messages}"
    assert "Kolmogorov-Smirnov" in result.metadata.get("test", ""), (
        f"应执行 KS 检验: {result.metadata.get('test')}"
    )
    assert 0 <= result.metadata["p_value"] <= 1


def test_hypothesis_ttest_ind_group_col_none_injection():
    """Round-2 批次D #4c：独立双样本 t 检验同样不得因 group_col=None KeyError。"""
    from smartsuite.services.orchestrator import orchestrate

    np.random.seed(7)
    df = pd.DataFrame({
        "y": np.concatenate([np.random.normal(10, 1, 50), np.random.normal(12, 1, 50)]),
        "g": ["A"] * 50 + ["B"] * 50,
    })
    req = AnalysisRequest(task="hypothesis_test", data=df, target_col="y",
                          feature_cols=["g"], params={"test": "ttest_ind", "alpha": 0.05})
    result = orchestrate(req)
    assert result.status == "ok", f"ttest_ind group_col=None 注入应正常: {result.messages}"
    assert result.metadata.get("p_value") is not None
