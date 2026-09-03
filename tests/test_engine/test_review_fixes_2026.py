"""2026 全库深度审查（review-2026-xx）修复回归测试。

覆盖 P0/P1 缺陷族（红→绿验证）：
1. spc c/u 图负计数静默 NaN（同族残留）
2. CUSUM/EWMA 用户 mu/sigma 传 NaN/Inf 穿透（哨兵 L1）
3. alpha 无 (0,1) 校验的 root_cause 系（可伪造显著性）
4. KS 双样本组内全 NaN → scipy 空数组 ValueError
5. correlation / decision_tree / scatter_plot / 回归族 常量或极小样本缺守卫
6. attribute 图文本映射语义提示 + NaN 分组行剔除
7. change_point n=20 默认参数必失败；survival 中位寿命=0 的 falsy 误读
"""

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest


def _req(task, df, target=None, features=None, params=None):
    return AnalysisRequest(
        task=task,
        data=df,
        target_col=target,
        feature_cols=features or [],
        params=params or {},
    )


# ── 1. c/u 图负计数守卫 ──
def _attr_neg_df(chart_type, n_groups=10):
    x = list(range(n_groups))
    y = [-2] * n_groups if chart_type in ("c",) else [-2] * n_groups
    return pd.DataFrame({"x": x, "y": y}), x


def test_spc_c_chart_negative_counts_rejected():
    from smartsuite.engine.spc_monitor import attribute_chart

    df, x = _attr_neg_df("c")
    r = attribute_chart(
        _req(
            "spc_attribute",
            df,
            target="y",
            features=["x"],
            params={"chart_type": "c", "group_col": "x"},
        )
    )
    assert r.status == "error"
    assert any("负计数值" in m for m in r.messages)


def test_spc_u_chart_negative_counts_rejected():
    from smartsuite.engine.spc_monitor import attribute_chart

    df, x = _attr_neg_df("u")
    df["n"] = 20
    r = attribute_chart(
        _req(
            "spc_attribute",
            df,
            target="y",
            features=["x"],
            params={"chart_type": "u", "group_col": "x", "n_col": "n"},
        )
    )
    assert r.status == "error"
    assert any("负计数值" in m for m in r.messages)


# ── 2. CUSUM/EWMA NaN/Inf 参数守卫 ──
def test_spc_cusum_rejects_nan_sigma():
    from smartsuite.engine.spc_monitor import cusum_chart

    np.random.seed(1)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 40)})
    r = cusum_chart(_req("spc_cusum", df, target="y", params={"mu": "nan", "sigma": "nan"}))
    assert r.status == "error"
    assert any("有限数值" in m or "NaN" in m for m in r.messages)


def test_spc_ewma_rejects_nan_sigma():
    from smartsuite.engine.spc_monitor import ewma_chart

    np.random.seed(1)
    df = pd.DataFrame({"y": np.random.normal(0, 1, 40)})
    r = ewma_chart(_req("spc_ewma", df, target="y", params={"mu": "nan", "sigma": "nan"}))
    assert r.status == "error"
    assert any("有限数值" in m or "NaN" in m for m in r.messages)


# ── 3. alpha (0,1) 校验 ──
def _alpha_df(n=30):
    return pd.DataFrame(
        {
            "group": ["A"] * n + ["B"] * n + ["C"] * n,
            "val": np.concatenate(
                [
                    np.random.normal(10, 1, n),
                    np.random.normal(13, 1, n),
                    np.random.normal(16, 1, n),
                ]
            ),
        }
    )


def test_anova_alpha_out_of_range_rejected():
    from smartsuite.engine.root_cause import anova_analysis

    df = _alpha_df()
    for bad in (0, 1.5):
        r = anova_analysis(
            _req("anova", df, target="val", features=["group"], params={"alpha": bad})
        )
        assert r.status == "error", f"alpha={bad} 应报错"
        assert any("alpha" in m for m in r.messages)


def test_hypothesis_test_alpha_out_of_range_rejected():
    from smartsuite.engine.root_cause import hypothesis_test

    df = pd.DataFrame(
        {
            "g": ["A"] * 20 + ["B"] * 20,
            "v": np.concatenate([np.random.normal(0, 1, 20), np.random.normal(0.5, 1, 20)]),
        }
    )
    r = hypothesis_test(
        _req(
            "hypothesis_test",
            df,
            target="v",
            features=["g"],
            params={"test": "ttest_ind", "group_col": "g", "alpha": 2},
        )
    )
    assert r.status == "error"
    assert any("alpha" in m for m in r.messages)


def test_contingency_alpha_out_of_range_rejected():
    from smartsuite.engine.root_cause import contingency_analysis

    df = pd.DataFrame({"a": ["A"] * 40 + ["B"] * 40, "b": ["X", "Y"] * 40})
    r = contingency_analysis(
        _req("contingency", df, target="a", features=["b"], params={"alpha": 0})
    )
    assert r.status == "error"
    assert any("alpha" in m for m in r.messages)


# ── 4. KS 组内空样本守卫 ──
def test_hypothesis_ks_rejects_empty_group_side():
    from smartsuite.engine.root_cause import hypothesis_test

    df = pd.DataFrame({"g": ["A"] * 10 + ["B"] * 10, "v": [1.0] * 10 + [float("nan")] * 10})
    r = hypothesis_test(
        _req(
            "hypothesis_test",
            df,
            target="v",
            features=["g"],
            params={"test": "ks", "group_col": "g"},
        )
    )
    assert r.status == "error", "KS 组内全 NaN 应返回中文错误而非 scipy ValueError"
    assert any("KS" in m for m in r.messages)


# ── 5. 常量/极小样本守卫 ──
def test_correlation_rejects_two_row_data():
    from smartsuite.engine.root_cause import correlation_analysis

    df = pd.DataFrame({"x": [1.0, 2.0], "y": [1.0, 2.0]})
    r = correlation_analysis(_req("correlation", df, target="y", features=["x"]))
    assert r.status == "error"


def test_decision_tree_rejects_constant_target():
    from smartsuite.engine.root_cause import decision_tree_analysis

    df = pd.DataFrame({"x": np.arange(10.0), "y": [5.0] * 10})
    r = decision_tree_analysis(_req("decision_tree", df, target="y", features=["x"]))
    assert r.status == "error"
    assert any("常量" in m for m in r.messages)


def test_scatter_plot_linear_rejects_constant_y():
    from smartsuite.engine.exploratory import scatter_plot

    df = pd.DataFrame({"x": np.arange(20.0), "y": [3.0] * 20})
    r = scatter_plot(_req("scatter_plot", df, target="y", features=["x"], params={"fit": "linear"}))
    assert r.status == "error"
    assert any("常量" in m for m in r.messages)


def test_regression_variants_reject_constant_y():
    from smartsuite.engine.doe_opt import lasso_regression, quantile_regression, robust_regression

    np.random.seed(7)
    df = pd.DataFrame(
        {"x1": np.random.normal(0, 1, 30), "x2": np.random.normal(0, 1, 30), "y": [2.0] * 30}
    )
    for fn, task in (
        (lasso_regression, "lasso_regression"),
        (robust_regression, "robust_regression"),
        (quantile_regression, "quantile_regression"),
    ):
        r = fn(_req(task, df, target="y", features=["x1", "x2"]))
        assert r.status == "error", f"{task} 常量 Y 应报错"
        assert any("常量" in m for m in r.messages), f"{task} 错误消息应说明常量列"


# ── 6. attribute 图：文本映射语义 + NaN 组排除 ──
def test_attribute_text_mapping_semantics_note():
    from smartsuite.engine.spc_monitor import attribute_chart

    np.random.seed(4)
    n = 60
    df = pd.DataFrame(
        {
            "x": np.repeat(range(1, 13), 5),
            "y": np.where(np.random.rand(n) < 0.1, "不合格", "合格"),
        }
    )
    r = attribute_chart(
        _req(
            "spc_attribute",
            df,
            target="y",
            features=["x"],
            params={"chart_type": "p", "group_col": "x"},
        )
    )
    assert r.status == "ok"
    assert r.metadata.get("text_binary_mapped") is True
    assert "文本质量列已映射" in r.summary, "应提示 1 事件语义（合格=1 → 合格率图）"


def test_attribute_nan_group_rows_excluded():
    from smartsuite.engine.spc_monitor import attribute_chart

    df = pd.DataFrame(
        {
            "x": list(range(8)) * 2,
            "g": ["G1", "G2", "G3", "G4", "G5", "G6", None, None] * 2,
            "y": [0, 1, 0, 1, 0, 1, 0, 1] * 2,
        }
    )
    r = attribute_chart(
        _req(
            "spc_attribute",
            df,
            target="y",
            features=["x"],
            params={"chart_type": "p", "group_col": "g"},
        )
    )
    assert r.status == "ok", r.messages
    assert r.metadata.get("nan_group_rows_dropped") == 4


# ── 7. change_point / survival 小缺陷 ──
def test_change_point_default_min_segment_runs_on_n20():
    from smartsuite.engine.detection import change_point_detect

    np.random.seed(3)
    y = np.concatenate([np.random.normal(0, 1, 10), np.random.normal(3, 1, 10)])
    df = pd.DataFrame({"y": y})
    r = change_point_detect(_req("change_point", df, target="y"))
    assert r.status == "ok", f"n=20 默认 min_segment 不应报错: {r.messages}"


def test_survival_median_zero_not_read_as_na():
    from smartsuite.engine.spc_monitor import survival_analysis

    times = np.array([0.0] * 6 + [1.0] * 4 + [2.0] * 2)
    events = np.ones(len(times))
    df = pd.DataFrame({"time": times, "event": events})
    r = survival_analysis(_req("survival_analysis", df, target="time", features=["event"]))
    assert r.status == "ok", r.messages
    assert r.metadata["median_survival"] == 0.0
    assert "中位寿命=0" in r.summary and "未达到" not in r.summary
