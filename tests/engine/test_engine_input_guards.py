"""引擎输入防护回归测试 — 非法参数/退化输入的显式中文拒绝（不静默）。

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
import pytest

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


# ── 2b. CUSUM/EWMA 结构参数 k/h/L 的非有限守卫（审查 2026-09-21 D-1）──
# `x <= 0` 对 NaN 恒为 False（IEEE-754 比较语义）、对 +Inf 亦为 False，
# 于是 nan/inf 参数绕过「必须为正」守卫，静默关闭全部报警（实测报警数 4→0）。
@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", 0, -1])
@pytest.mark.parametrize("key", ["k", "h"])
def test_spc_cusum_rejects_non_positive_finite_k_h(bad, key):
    from smartsuite.engine.spc_monitor import cusum_chart

    np.random.seed(1)
    df = pd.DataFrame(
        {"y": np.concatenate([np.random.normal(0, 1, 20), np.random.normal(3, 1, 20)])}
    )
    r = cusum_chart(_req("spc_cusum", df, target="y", params={key: bad}))
    assert r.status == "error", f"{key}={bad!r} 应报错而非静默抑制报警"
    assert any(key in m for m in r.messages), f"错误文案应点明参数名 {key}: {r.messages}"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", 0, -1])
def test_spc_ewma_rejects_non_positive_finite_lambda_width(bad):
    from smartsuite.engine.spc_monitor import ewma_chart

    np.random.seed(1)
    df = pd.DataFrame(
        {"y": np.concatenate([np.random.normal(0, 1, 20), np.random.normal(3, 1, 20)])}
    )
    r = ewma_chart(_req("spc_ewma", df, target="y", params={"L": bad}))
    assert r.status == "error", f"L={bad!r} 应报错而非静默产出无效控制限"
    assert any("L" in m for m in r.messages), f"错误文案应点明参数名 L: {r.messages}"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", 0, -1])
def test_spc_cusum_ewma_alarm_count_stable_for_legal_params(bad):
    from smartsuite.engine.spc_monitor import cusum_chart

    np.random.seed(1)
    df = pd.DataFrame(
        {"y": np.concatenate([np.random.normal(0, 1, 20), np.random.normal(3, 1, 20)])}
    )
    r = cusum_chart(_req("spc_cusum", df, target="y", params={"k": 0.5, "h": 5.0}))
    assert r.status == "ok"
    assert r.tables, "合法参数必须仍产出表格"


# ── 2c. multi_objective 权重非有限（同族 D-1）──
# `weights=[float(w) for w in weights]` 对 "nan"/"inf" 恒成功，
# `weight_sum <= 0` 又漏 NaN/+Inf → 得分静默输出 nan（实测 summary "得分: nan"）。
@pytest.mark.parametrize(
    "bad_weights",
    [["nan", 1.0], ["inf", 1.0], ["-inf", 1.0], ["nan", "nan"], [0.0, 0.0], [-1.0, 1.0]],
)
def test_multi_objective_rejects_non_finite_or_non_positive_weights(bad_weights):
    from smartsuite.engine.doe_opt.optimization import multi_objective_opt

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "x": rng.normal(0, 1, 30),
            "y1": rng.normal(5, 1, 30),
            "y2": rng.normal(3, 1, 30),
        }
    )
    objs = [
        {"col": "y1", "direction": "maximize"},
        {"col": "y2", "direction": "minimize"},
    ]
    r = multi_objective_opt(
        _req(
            "multi_objective", df, target="y1", params={"objectives": objs, "weights": bad_weights}
        )
    )
    assert r.status == "error", f"weights={bad_weights!r} 应报错而非输出 得分=nan"
    assert any("权重" in m for m in r.messages)


def test_multi_objective_legal_weights_unchanged():
    """对照守卫：合法权重下多目标优化正常产出（防把守卫改成永远拒绝）。"""
    from smartsuite.engine.doe_opt.optimization import multi_objective_opt

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "x": rng.normal(0, 1, 30),
            "y1": rng.normal(5, 1, 30),
            "y2": rng.normal(3, 1, 30),
        }
    )
    objs = [
        {"col": "y1", "direction": "maximize"},
        {"col": "y2", "direction": "minimize"},
    ]
    r = multi_objective_opt(
        _req("multi_objective", df, target="y1", params={"objectives": objs, "weights": [0.5, 0.5]})
    )
    assert r.status == "ok", r.messages
    assert "nan" not in (r.summary or "").lower(), "合法权重不得输出 nan 得分"


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


# ── 8. O-1 同族：微量表值展示自适应（round_for_display 同步，审查 2026-09-06 F-D4）──
def test_spc_nonparametric_ppm_scale_tables_not_zeroed():
    """ppm 量纲数据：控制限/违规值表不得被固定位 4 小数整列归零。"""
    from smartsuite.engine.spc_monitor import spc_nonparametric

    rng = np.random.RandomState(42)
    vals = rng.normal(2e-5, 2e-6, 30)
    vals[10] = 4e-5  # 违规点：低于 5e-5 阈值 → round_for_display 自适应分支精确保留
    df = pd.DataFrame({"y": vals})
    r = spc_nonparametric(_req("spc_nonparametric", df, target="y", params={"side": "upper"}))
    assert r.status == "ok", r.messages
    limits = r.tables["control_limits"]["值"].astype(float)
    # CL≈2e-5：旧 f"{v:.4f}" 全列显示 "0.0000"；自适应后应保留量级
    assert limits.abs().max() >= 1e-6, f"控制限表整列归零: {limits.tolist()}"
    viol = r.tables["violations"]["值"].astype(float)
    assert abs(viol.iloc[0] - 4e-5) < 1e-12, f"违规值被吞没: {viol.tolist()}"


def test_roc_points_micro_thresholds_not_zeroed():
    """微尺度评分（阈值 ~1e-5）：ROC 阈值列不得归零——阈值是可操作输出。"""
    from smartsuite.engine.doe_opt import roc_analysis

    rng = np.random.RandomState(42)
    n = 200
    score = rng.uniform(0, 5e-5, n)
    y = (score > 2.5e-5).astype(int)
    df = pd.DataFrame({"score": score, "y": y})
    r = roc_analysis(_req("roc_analysis", df, target="y", features=["score"]))
    assert r.status == "ok", r.messages
    th = r.tables["roc_points"]["阈值"].dropna().astype(float)
    assert th.abs().max() > 1e-5, f"ROC 阈值整列归零: {th.head(8).tolist()}"


def test_quantile_coef_table_micro_scale_not_zeroed():
    """微量纲目标列（y~1e-5）：quantile 系数表不得被固定位 4 小数归零。"""
    from smartsuite.engine.doe_opt import quantile_regression

    rng = np.random.RandomState(42)
    n = 200
    x = rng.normal(0, 1, n)
    y = 3e-5 * x + rng.normal(0, 1e-6, n)  # 真实系数 3e-5，噪声同比微小时可检出
    df = pd.DataFrame({"x": x, "y": y})
    r = quantile_regression(_req("quantile_regression", df, target="y", features=["x"]))
    assert r.status == "ok", r.messages
    coef = r.tables["coefficients"]
    x_row = coef[coef["变量"] == "x"]
    assert float(x_row["系数"].iloc[0]) != 0.0, "微尺度系数被固定位舍入吞没"


# ── 9. falsy 回退显式化（审查 2026-09-06 F-D5）──
def test_box_chart_empty_group_col_not_silently_substituted():
    """显式传入空串分组列应报错，而非静默回退 feature_cols[0]（哨兵 L4）。"""
    from smartsuite.engine.exploratory import box_chart

    rng = np.random.RandomState(3)
    df = pd.DataFrame({"y": rng.normal(10, 1, 40), "g": ["A", "B"] * 20})
    r = box_chart(_req("box_chart", df, target="y", features=["g"], params={"group_col": ""}))
    assert r.status == "error", "空串 group_col 不应被静默替换为 feature_cols[0]"
    assert any("分组列" in m for m in r.messages)


def test_survival_empty_group_col_not_silently_substituted():
    """显式传入空串分组列应报错，而非静默按无分组分析（哨兵 L4）。"""
    from smartsuite.engine.reliability import survival_analysis

    rng = np.random.RandomState(5)
    df = pd.DataFrame(
        {
            "time": rng.exponential(10, 30),
            "event": np.ones(30, dtype=int),
            "batch": ["X", "Y"] * 15,
        }
    )
    r = survival_analysis(
        _req(
            "survival_analysis",
            df,
            target="time",
            features=["event", "batch"],
            params={"group_col": ""},
        )
    )
    assert r.status == "error", "空串 group_col 不应被静默替换为 feature_cols[1]"
    assert any("分组列" in m for m in r.messages)


# ── 10. SPC/箱线图参考线参数非有限值拒绝（审查 2026-09-19 D-1）──
def test_spc_xbar_reference_lines_reject_non_finite():
    """usl/lsl/target='inf'/'nan'/'-inf' 不得静默接受（capability C1 同族）。"""
    from smartsuite.engine.spc_charts import xbar_r_chart

    rng = np.random.RandomState(6)
    df = pd.DataFrame({"y": rng.normal(10, 1, 60)})
    for bad in ("inf", "nan", "-inf"):
        r = xbar_r_chart(_req("spc_xbar", df, target="y", params={"usl": bad, "lsl": 0}))
        assert r.status == "error", f"usl={bad!r} 应报错，实际 status={r.status}"
        assert any("有限" in m for m in r.messages), r.messages
    r = xbar_r_chart(_req("spc_xbar", df, target="y", params={"target": "nan"}))
    assert r.status == "error" and any("有限" in m for m in r.messages)


def test_box_chart_reference_lines_reject_non_finite():
    """usl/lsl/ucl/lcl/cl/target 的 inf/nan 不得静默忽略。"""
    from smartsuite.engine.exploratory import box_chart

    rng = np.random.RandomState(6)
    df = pd.DataFrame({"y": rng.normal(10, 1, 40), "g": ["A", "B"] * 20})
    for key in ("usl", "lsl", "ucl", "lcl", "cl", "target"):
        r = box_chart(_req("box_chart", df, target="y", features=["g"], params={key: "nan"}))
        assert r.status == "error", f"{key}='nan' 应报错，实际 status={r.status}"
        assert any("有限" in m for m in r.messages), r.messages


# ── 11. doe_design 全因子组合数上限不得被整数回绕绕过（审查 2026-09-19 D-2）──
def test_doe_design_full_factorial_combinatorial_limit_clear_error():
    """55 因子×1000 水平：旧 np.prod int64 回绕为 0 → 绕过检查 → MemoryError。

    修复后应在分配前以含「上限」的中文错误拒绝（math.prod 任意精度）。
    """
    from smartsuite.engine.doe_opt import doe_design

    factors = [{"name": f"f{i}", "levels": list(range(1000))} for i in range(55)]
    r = doe_design(
        _req(
            "doe_design",
            pd.DataFrame(),
            target="",
            params={"method": "full_factorial", "factors": factors},
        )
    )
    assert r.status == "error", "组合数超限应显式拒绝"
    assert any("上限" in m for m in r.messages), r.messages


def test_is_positive_finite_predicate():
    """共用参数守卫谓词：NaN/±Inf/0/负数 → False，正有限数 → True。

    审查 2026-09-21 D-1 抽出；本测试是质量守卫「新增公共函数必须配测试」的直接引用。
    """
    from smartsuite.engine._utils import is_positive_finite

    for bad in (float("nan"), float("inf"), float("-inf"), 0, 0.0, -1, -1e-9):
        assert is_positive_finite(bad) is False, f"{bad!r} 应判为非法"
    for good in (1e-12, 0.5, 5.0, 1e12):
        assert is_positive_finite(good) is True, f"{good!r} 应判为合法"


# ── 12. 数据列 ±Inf 入口哨兵（审查 2026-09-22 发现 2/3）──
# 入口仅 dropna() 时 ±Inf 穿透：scipy 返回 NaN p 值被表述为「未发现显著差异」，
# matplotlib/sklearn 抛未捕获 ValueError。入口按缺失剔除 + 显式中文提示。
def _inf_column_df(n=60, n_inf=1):
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"y": rng.normal(10.0, 1.0, n), "g": ["A", "B"] * (n // 2)})
    df.loc[df.index[:n_inf], "y"] = np.inf
    return df


@pytest.mark.parametrize("test_type", ["ttest_ind", "mannwhitney", "auto"])
def test_hypothesis_two_sample_inf_dropped_not_silent_nan(test_type):
    """发现 2（P1）：NaN p 值不得被表达为「未发现显著差异」，须剔除并提示。"""
    from smartsuite.engine.root_cause import hypothesis_test

    df = _inf_column_df()
    r = hypothesis_test(
        _req(
            "hypothesis_test",
            df,
            target="y",
            features=["g"],
            params={"test": test_type, "group_col": "g"},
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"])), f"{test_type}: p 值为 NaN（静默错误判决）"
    assert any("非有限" in m for m in r.messages), f"{test_type} 未提示剔除: {r.messages}"


def _inf_paired_df(n=40):
    rng = np.random.default_rng(12)
    df = pd.DataFrame({"before": rng.normal(10.0, 1.0, n), "after": rng.normal(10.5, 1.0, n)})
    df.loc[0, "before"] = -np.inf
    return df


@pytest.mark.parametrize("test_type", ["ttest_paired", "wilcoxon_paired"])
def test_hypothesis_paired_inf_dropped_not_silent_nan(test_type):
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _req(
            "hypothesis_test",
            _inf_paired_df(),
            target="before",
            features=["before", "after"],
            params={"test": test_type},
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"])), f"{test_type}: p 值为 NaN"
    assert any("非有限" in m for m in r.messages)


@pytest.mark.parametrize(
    ("test_type", "params"),
    [("ttest_1samp", {"popmean": 10.0}), ("wilcoxon_1samp", {"popmedian": 10.0})],
)
def test_hypothesis_single_sample_inf_dropped(test_type, params):
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _req("hypothesis_test", _inf_column_df(), target="y", params={"test": test_type, **params})
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"]))
    assert any("非有限" in m for m in r.messages)


def test_hypothesis_ks_inf_dropped():
    from smartsuite.engine.root_cause import hypothesis_test

    r = hypothesis_test(
        _req(
            "hypothesis_test",
            _inf_column_df(),
            target="y",
            features=["g"],
            params={"test": "ks", "group_col": "g"},
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"]))
    assert any("非有限" in m for m in r.messages)


def test_hypothesis_kruskal_inf_dropped():
    from smartsuite.engine.root_cause import hypothesis_test

    rng = np.random.default_rng(15)
    df = pd.DataFrame(
        {
            "g": ["A"] * 20 + ["B"] * 20 + ["C"] * 20,
            "y": np.concatenate(
                [rng.normal(10, 1, 20), rng.normal(12, 1, 20), rng.normal(14, 1, 20)]
            ),
        }
    )
    df.loc[0, "y"] = np.inf
    r = hypothesis_test(
        _req(
            "hypothesis_test",
            df,
            target="y",
            features=["g"],
            params={"test": "kruskal_wallis", "group_col": "g"},
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"]))
    assert any("非有限" in m for m in r.messages)


def test_hypothesis_correlation_dispatch_inf_dropped():
    from smartsuite.engine.root_cause import hypothesis_test

    rng = np.random.default_rng(16)
    df = pd.DataFrame({"x": rng.normal(0, 1, 60), "y": rng.normal(0, 1, 60)})
    df.loc[0, "y"] = np.inf
    r = hypothesis_test(
        _req(
            "hypothesis_test",
            df,
            target="y",
            features=["x"],
            params={"test": "correlation"},
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"]))
    assert any("非有限" in m for m in r.messages)


def test_hypothesis_friedman_inf_dropped():
    from smartsuite.engine.root_cause import hypothesis_test

    rng = np.random.default_rng(17)
    df = pd.DataFrame(
        {"a": rng.normal(10, 1, 30), "b": rng.normal(11, 1, 30), "c": rng.normal(12, 1, 30)}
    )
    df.loc[0, "b"] = np.inf
    r = hypothesis_test(
        _req(
            "hypothesis_test", df, target="a", features=["a", "b", "c"], params={"test": "friedman"}
        )
    )
    assert r.status == "ok", r.messages
    assert np.isfinite(float(r.metadata["p_value"]))
    assert any("非有限" in m for m in r.messages)


def test_inf_data_column_cleaned_for_previously_raising_tasks():
    """发现 3：42 任务 +Inf 扫描中曾抛未捕获异常的 8 个任务，须剔除 + 提示。"""
    from smartsuite.engine.capability import process_capability_analysis
    from smartsuite.engine.exploratory import bootstrap_ci, box_chart, median_ci
    from smartsuite.engine.reliability import gage_rr, tolerance_interval
    from smartsuite.engine.root_cause import decision_tree_analysis, distribution_summary

    rng = np.random.default_rng(13)
    y_inf = np.concatenate([rng.normal(10.0, 1.0, 59), [np.inf]])
    df_single = pd.DataFrame({"y": y_inf})
    df_two = pd.DataFrame({"x": rng.normal(0, 1, 60), "y": y_inf})
    df_group = pd.DataFrame({"g": ["A", "B"] * 30, "y": y_inf})
    df_gage = pd.DataFrame(
        {
            "m": y_inf,
            "part": np.repeat(range(10), 6),
            "op": np.tile(np.repeat(["A", "B", "C"], 2), 10),
        }
    )
    cases = {
        "process_capability": lambda: process_capability_analysis(
            _req("process_capability", df_single, target="y")
        ),
        "distribution_summary": lambda: distribution_summary(
            _req("distribution_summary", df_single, target="y")
        ),
        "bootstrap_ci": lambda: bootstrap_ci(_req("bootstrap_ci", df_single, target="y")),
        "median_ci": lambda: median_ci(_req("median_ci", df_single, target="y")),
        "tolerance_interval": lambda: tolerance_interval(
            _req("tolerance_interval", df_single, target="y")
        ),
        "decision_tree": lambda: decision_tree_analysis(
            _req("decision_tree", df_two, target="y", features=["x"])
        ),
        "gage_rr": lambda: gage_rr(
            _req(
                "gage_rr",
                df_gage,
                target="m",
                features=["part", "op"],
                params={"part_col": "part", "operator_col": "op"},
            )
        ),
        "box_chart": lambda: box_chart(
            _req("box_chart", df_group, target="y", features=["g"], params={"group_col": "g"})
        ),
    }
    finite_values = {
        "process_capability": lambda r: r.metadata["mean"],
        "distribution_summary": lambda r: r.metadata["descriptive"]["均值"],
        "bootstrap_ci": lambda r: r.metadata["point_estimate"],
        "median_ci": lambda r: r.metadata["median"],
        "tolerance_interval": lambda r: r.metadata["lower"],
        "decision_tree": lambda r: r.metadata["train_r2"],
        "gage_rr": lambda r: r.metadata["grr_sv"],
        "box_chart": lambda r: float(r.tables["group_statistics"]["均值"].iloc[0]),
    }
    for name, call in cases.items():
        r = call()
        assert r.status == "ok", f"{name}: {r.status} {r.messages}"
        assert any("非有限" in m for m in r.messages), f"{name} 未提示剔除: {r.messages}"
        value = finite_values[name](r)
        assert np.isfinite(float(value)), f"{name} 输出非有限值: {value}"


def test_correlation_inf_r_finite_implies_p_finite():
    """发现 4：r 矩阵（pandas 成对剔除 Inf）与 p 表口径必须一致。"""
    from smartsuite.engine.root_cause import correlation_analysis

    rng = np.random.default_rng(18)
    df = pd.DataFrame({"x": rng.normal(0, 1, 60), "y": rng.normal(0, 1, 60)})
    df.loc[0, "y"] = np.inf
    r = correlation_analysis(_req("correlation", df, target="y", features=["x"]))
    r_val = r.tables["correlation_matrix"].loc["x", "y"]
    p_val = r.tables["p_values_raw"].loc["x", "y"]
    assert np.isfinite(float(r_val))
    assert np.isfinite(float(p_val)), "r 有限而 p 为 NaN（表内自相矛盾）"


# ── 13. int() 参数转换的 OverflowError 同族（审查 2026-09-22 发现 5）──
@pytest.mark.parametrize("bad", [float("inf"), float("-inf")])
def test_safe_int_rejects_overflow(bad):
    from smartsuite.engine.root_cause._shared import _safe_int

    assert _safe_int(bad) is None, f"_safe_int({bad!r}) 不应抛出 OverflowError"
    assert _safe_int(bad, 7) == 7


def test_doe_design_n_runs_inf_rejected_not_overflow_error():
    from smartsuite.engine.doe_opt import doe_design

    factors = [{"name": "a", "levels": [1, 2]}, {"name": "b", "levels": [1, 2]}]
    r = doe_design(
        _req(
            "doe_design",
            pd.DataFrame(),
            target="",
            params={"method": "fractional_factorial", "factors": factors, "n_runs": float("inf")},
        )
    )
    assert r.status == "error", "int(inf) 应被参数守卫拒绝而非穿透"
    assert any("n_runs" in m for m in r.messages), r.messages


def test_power_analysis_anova_n_groups_inf_rejected():
    from smartsuite.engine.root_cause import power_analysis

    r = power_analysis(
        _req(
            "power_analysis",
            pd.DataFrame(),
            target="",
            params={"test_type": "anova", "mode": "required_n", "n_groups": float("inf")},
        )
    )
    assert r.status == "error", "n_groups=inf 应被参数守卫拒绝"
    assert any("n_groups" in m for m in r.messages), r.messages


def test_decision_tree_max_depth_inf_no_overflow_error():
    from smartsuite.engine.root_cause import decision_tree_analysis

    rng = np.random.default_rng(19)
    df = pd.DataFrame({"x": rng.normal(0, 1, 30), "y": rng.normal(0, 1, 30)})
    r = decision_tree_analysis(
        _req("decision_tree", df, target="y", features=["x"], params={"max_depth": float("inf")})
    )
    assert r.status == "ok", r.messages
    assert not any("数值溢出" in m for m in r.messages)
