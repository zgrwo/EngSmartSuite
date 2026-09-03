"""保修数据集集成测试。"""

import os

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


@pytest.fixture(scope="module")
def war_df():
    path = os.path.join(os.path.dirname(__file__), "test_warranty_data.xlsx")
    if not os.path.exists(path):
        pytest.skip("test_warranty_data.xlsx not found")
    return pd.read_excel(path)


def test_warranty_data_loaded(war_df):
    assert len(war_df) == 1000
    assert "保修索赔" in war_df.columns


def test_logistic_warranty(war_df):
    r = orchestrate(
        AnalysisRequest(
            task="logistic_regression",
            data=war_df,
            target_col="保修索赔",
            feature_cols=["环境温度", "湿度", "每日循环", "运行小时"],
        )
    )
    assert r.status == "ok"
    assert r.metadata["accuracy"] > 0.5


def test_correlation_warranty(war_df):
    feats = ["维修费用", "维修工时", "运行小时", "环境温度"]
    r = orchestrate(
        AnalysisRequest(
            task="correlation",
            data=war_df,
            target_col="满意度",
            feature_cols=feats,
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # 引擎 r 与测试内逐对 dropna 独立重算对照；每列 r/p 有界
    tc = r.metadata["target_correlations"]
    tp = r.metadata["target_p_adjusted"]
    assert set(tc) == set(feats)
    manual = {}
    for f in feats:
        pair = war_df[["满意度", f]].dropna()
        manual[f] = float(np.corrcoef(pair["满意度"], pair[f])[0, 1])
        assert tc[f] == pytest.approx(manual[f], abs=1e-9)
        assert abs(tc[f]) <= 1 and 0 <= tp[f] <= 1
    # 维修费用为最强（负）相关因子——由测试内重算判定，非硬编码
    assert max(manual, key=lambda k: abs(manual[k])) == "维修费用"


def test_contingency_warranty(war_df):
    r = orchestrate(
        AnalysisRequest(
            task="contingency",
            data=war_df,
            target_col="保修索赔",
            feature_cols=["粉尘等级"],
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status——若引擎恒报 p=1 也绿。
    # 引擎统计量/p/效应量与 scipy chi2_contingency 独立重算对照（精确到 1e-9）
    ct = pd.crosstab(war_df["保修索赔"], war_df["粉尘等级"])
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    assert r.metadata["statistic"] == pytest.approx(chi2, abs=1e-9)
    assert r.metadata["p_value"] == pytest.approx(p, abs=1e-9)
    assert r.metadata["degrees_of_freedom"] == dof == 2
    n = ct.to_numpy().sum()
    manual_v = float(np.sqrt(chi2 / (n * min(ct.shape[0] - 1, ct.shape[1] - 1))))
    assert r.metadata["effect_size"] == pytest.approx(manual_v, abs=1e-9)
    # 数据集事实（独立重算）：索赔率与粉尘等级强相关
    assert p < 0.01


def test_proportion_warranty(war_df):
    r = orchestrate(
        AnalysisRequest(
            task="proportion_ci",
            data=war_df,
            target_col="保修索赔",
            feature_cols=[],
            params={"success_value": 1},
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① successes/n/p_hat 与原始数据计数一致；② Wilson 界与公式独立重算一致
    raw = war_df["保修索赔"]
    assert r.metadata["successes"] == int((raw == 1).sum()) == 154
    assert r.metadata["n"] == len(raw) == 1000
    assert r.metadata["p_hat"] == pytest.approx(float((raw == 1).mean()), abs=1e-12)
    phat, nn, z = r.metadata["p_hat"], r.metadata["n"], 1.959963984540054
    den = 1 + z * z / nn
    ctr = (phat + z * z / (2 * nn)) / den
    half = z * np.sqrt(phat * (1 - phat) / nn + z * z / (4 * nn * nn)) / den
    lo, hi = r.metadata["wilson_ci"]
    assert lo == pytest.approx(ctr - half, abs=1e-12)
    assert hi == pytest.approx(ctr + half, abs=1e-12)
    assert lo <= r.metadata["p_hat"] <= hi


def test_anova_warranty(war_df):
    r = orchestrate(
        AnalysisRequest(
            task="anova",
            data=war_df,
            target_col="满意度",
            feature_cols=["产品型号", "区域"],
        )
    )
    assert r.status == "ok"
    # 审查 2026-09-04 补充：此前仅断言 status。
    # ① 自由度与因子水平数一致（水平数-1）；② 残差自由度 = n-1-Σ(因子 df)；
    # ③ 每因子 F>0、p∈[0,1]、η²∈[0,1]（两因子 OLS 无交互项）
    tbl = r.tables["anova_enhanced"]
    assert list(tbl["来源"]) == ["Q('产品型号')", "Q('区域')", "Residual"]
    df_prod = int(war_df["产品型号"].nunique()) - 1
    df_region = int(war_df["区域"].nunique()) - 1
    # 引擎表格数值为格式化字符串 → 逐项转数值断言
    assert int(tbl.iloc[0]["自由度"]) == df_prod
    assert int(tbl.iloc[1]["自由度"]) == df_region
    assert int(tbl.iloc[2]["自由度"]) == len(war_df) - 1 - df_prod - df_region
    for idx in (0, 1):
        f_val = float(tbl.iloc[idx]["F值"])
        p_val = float(tbl.iloc[idx]["p值"])
        eta2 = float(tbl.iloc[idx]["η²"])
        assert f_val > 0 and 0 <= p_val <= 1 and 0 <= eta2 <= 1
