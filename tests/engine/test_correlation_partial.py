"""偏相关分析补测（审查 2026-09-19 C1）。

`root_cause/correlation.py` 的偏相关分支此前**零覆盖**（CI 实测该文件 74%，
342-443 整段未执行）——而它是「控制混淆变量」这一核心分析能力，出错的后果是
用户据此排除掉真正的影响因子。

数值验证用**独立算法**而非重复引擎公式：偏相关由零阶相关闭式解
r_xy·z = (r_xy − r_xz·r_yz) / √((1−r_xz²)(1−r_yz²))
复算，与引擎的「残差回归 + pearsonr」路径互相印证；p 值另用 scipy 独立复算。
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause.correlation import correlation_analysis


def _analyze(data: pd.DataFrame, target: str, features: list[str], control_vars):
    req = AnalysisRequest(
        task="correlation",
        data=data,
        target_col=target,
        feature_cols=features,
        params={"control_vars": control_vars},
    )
    return correlation_analysis(req)


def _confounded(n: int = 80) -> pd.DataFrame:
    """x、y 同受 z 驱动但彼此无直接关系 → 零阶相关高、偏相关应显著降低（削弱）。"""
    rng = np.random.default_rng(7)
    z = rng.normal(size=n)
    return pd.DataFrame(
        {
            "y": z + rng.normal(scale=0.6, size=n),
            "x1": z + rng.normal(scale=0.6, size=n),
            "x2": rng.normal(size=n),  # 与 z 无关的陪衬因子
            "z": z,
        }
    )


def _suppressed(n: int = 80) -> pd.DataFrame:
    """y = z − x：零阶相关被 z 抵消趋近 0，控制 z 后偏相关显著为负（抑制）。"""
    rng = np.random.default_rng(11)
    z = rng.normal(size=n)
    x = z + rng.normal(scale=0.3, size=n)
    y = z - x + rng.normal(scale=0.3, size=n)
    return pd.DataFrame({"y": y, "x1": x, "z": z})


def _partial_row(result, factor: str) -> dict:
    df = result.tables["partial_correlations"]
    rows = df[df["因子"] == factor]
    assert len(rows) == 1, f"{factor} 应恰有一行：{df}"
    return rows.iloc[0].to_dict()


def _formula_partial(data: pd.DataFrame, x: str, y: str, z: str) -> float:
    """闭式解复算：与引擎的「残差回归 + pearsonr」是两条不同路径。"""
    r = data[[x, y, z]].corr().to_numpy()
    xy, xz, yz = r[0, 1], r[0, 2], r[1, 2]
    return float((xy - xz * yz) / np.sqrt((1 - xz**2) * (1 - yz**2)))


# ── 数值正确性 ──


def test_partial_correlation_matches_closed_form():
    """偏相关数值与闭式解一致（独立算法交叉验证）。"""
    data = _confounded()
    result = _analyze(data, "y", ["x1", "x2"], ["z"])
    assert result.status == "ok", result.messages

    row = _partial_row(result, "x1")
    expected = _formula_partial(data, "x1", "y", "z")
    assert row["偏相关(r_partial)"] == pytest.approx(round(expected, 4), abs=1e-4)


def test_partial_p_value_matches_scipy():
    """p 值由 t = r√(df/(1−r²))、df = n−k−2 独立复算。"""
    data = _confounded()
    n, k = len(data), 1
    result = _analyze(data, "y", ["x1", "x2"], ["z"])

    r_partial = _formula_partial(data, "x1", "y", "z")
    df_partial = n - k - 2
    t_val = r_partial * np.sqrt(df_partial / (1 - r_partial**2))
    expected_p = float(2 * sps.t.sf(abs(t_val), df_partial))

    assert _partial_row(result, "x1")["p值"] == pytest.approx(round(expected_p, 4), abs=1e-4)


def test_zero_order_value_matches_plain_correlation():
    """同表的「零阶相关」应等于不控制任何变量时的普通相关系数。"""
    data = _confounded()
    result = _analyze(data, "y", ["x1"], ["z"])

    assert _partial_row(result, "x1")["零阶相关(r)"] == pytest.approx(
        round(float(data["x1"].corr(data["y"])), 4), abs=1e-4
    )


# ── 「抑制 / 削弱 / 稳定」三态判定（±0.05 阈值）──


def test_change_label_attenuation_when_confounder_removed():
    data = _confounded()
    row = _partial_row(_analyze(data, "y", ["x1"], ["z"]), "x1")

    assert abs(row["偏相关(r_partial)"]) < abs(row["零阶相关(r)"]) - 0.05
    assert row["变化"] == "削弱"


def test_change_label_suppression_when_effect_hidden_by_control():
    data = _suppressed()
    row = _partial_row(_analyze(data, "y", ["x1"], ["z"]), "x1")

    assert abs(row["偏相关(r_partial)"]) > abs(row["零阶相关(r)"]) + 0.05
    assert row["变化"] == "抑制"
    assert row["偏相关(r_partial)"] < 0, "抑制情形此处应为负"


def test_change_label_stable_when_control_is_irrelevant():
    rng = np.random.default_rng(3)
    n = 80
    x = rng.normal(size=n)
    data = pd.DataFrame(
        {
            "y": 0.8 * x + rng.normal(scale=0.3, size=n),
            "x1": x,
            "z": rng.normal(size=n),  # 与 x、y 均无关
        }
    )
    row = _partial_row(_analyze(data, "y", ["x1"], ["z"]), "x1")

    assert abs(abs(row["偏相关(r_partial)"]) - abs(row["零阶相关(r)"])) <= 0.05
    assert row["变化"] == "稳定"


# ── 表格结构与元数据 ──


def test_partial_table_sorted_by_absolute_partial():
    """按 |r_partial| 降序 —— 用户第一眼看到的是控制混淆后最强的因子。"""
    result = _analyze(_confounded(), "y", ["x1", "x2"], ["z"])
    df = result.tables["partial_correlations"]

    assert list(df.columns) == ["因子", "零阶相关(r)", "偏相关(r_partial)", "p值", "变化"]
    assert list(df["因子"]) == sorted(df["因子"], key=lambda f: -abs(_partial_row(result, f)["偏相关(r_partial)"]))


def test_control_and_target_excluded_from_factor_list():
    """控制变量与目标列本身不得作为「因子」出现在偏相关表中。"""
    result = _analyze(_confounded(), "y", ["x1", "x2", "z"], ["z"])
    factors = set(result.tables["partial_correlations"]["因子"])

    assert factors == {"x1", "x2"}


def test_metadata_records_partial_values_and_controls():
    data = _confounded()
    result = _analyze(data, "y", ["x1"], ["z"])

    meta = result.metadata["partial_correlations"]["x1"]
    assert meta["r_partial"] == pytest.approx(_formula_partial(data, "x1", "y", "z"), abs=1e-6)
    assert meta["r_zero"] == pytest.approx(float(data["x1"].corr(data["y"])), abs=1e-6)
    assert result.metadata["control_vars"] == ["z"]


def test_summary_mentions_control_and_direction():
    result = _analyze(_confounded(), "y", ["x1"], ["z"])

    assert "控制「z」后" in result.summary
    assert "最强偏相关" in result.summary


def test_partial_analysis_adds_a_figure():
    """偏相关会额外产出一张对比柱状图（零阶 vs 偏相关）。"""
    with_control = _analyze(_confounded(), "y", ["x1", "x2"], ["z"])
    without = _analyze(_confounded(), "y", ["x1", "x2"], [])

    assert len(with_control.figures) == len(without.figures) + 1


# ── 入参与边界 ──


@pytest.mark.parametrize("control", [["z"], "z", " z , "])
def test_control_vars_accepts_list_and_comma_separated_string(control):
    """list 与逗号分隔字符串（含空白）语义一致 —— 原实现按字符拆分曾静默变空。"""
    result = _analyze(_confounded(), "y", ["x1"], control)

    assert result.status == "ok"
    assert "partial_correlations" in result.tables
    assert result.metadata["control_vars"] == ["z"]


def test_invalid_control_vars_type_returns_chinese_error():
    result = _analyze(_confounded(), "y", ["x1"], 123)

    assert result.status == "error"
    assert "control_vars 必须是列名列表或逗号分隔字符串" in result.messages[0]


def test_unknown_control_column_is_ignored_gracefully():
    """控制列不存在（或非数值）时被过滤掉 → 退化为普通相关，不报错。"""
    result = _analyze(_confounded(), "y", ["x1"], ["不存在的列"])

    assert result.status == "ok"
    assert result.metadata["control_vars"] == []
    assert "partial_correlations" not in result.tables


def test_no_control_vars_means_no_partial_table():
    """未指定控制变量时不得产出偏相关表（防误报「已控制混淆」）。"""
    result = _analyze(_confounded(), "y", ["x1", "x2"], [])

    assert "partial_correlations" not in result.tables
    assert result.metadata["partial_correlations"] == {}


def test_insufficient_samples_skimmed_per_factor():
    """有效样本 < 控制变量数 + 3 的因子被跳过（自由度不足），其余正常出结果。"""
    data = _confounded(n=6)
    data.loc[data.index[2:], "x1"] = np.nan  # x1 仅 2 个有效点 < 1+3
    result = _analyze(data, "y", ["x1", "x2"], ["z"])

    assert result.status == "ok"
    factors = set(result.tables["partial_correlations"]["因子"])
    assert "x1" not in factors, "有效样本过少的因子应被跳过"
    assert "x2" in factors


def test_control_vars_column_not_in_feature_cols_still_works():
    """控制列不必出现在 feature_cols 中（它只参与残差回归，不是被评估的因子）。"""
    result = _analyze(_confounded(), "y", ["x1"], ["z"])

    assert result.status == "ok"
    assert "z" in result.metadata["control_vars"]
