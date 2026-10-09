"""分组检验的 ±Inf 披露必须**同名同量**（审查 2026-10-09 R2BD-08，P2）。

缺陷形态（生产口径，目标列 `y` 前 3 行 `+Inf`，分组列把第 0/1 行分到 A、第 2 行分到 B）：

```
status = ok
messages[0] = ⚠ 「y」含 2 个 ±Inf（非有限值），已剔除后分析
messages[1] = ⚠ 「y」含 1 个 ±Inf（非有限值），已剔除后分析
boundary_codes = ['E_DATA_NON_FINITE_DROPPED', 'E_DATA_NON_FINITE_DROPPED']   ← 同码两条
```

真实注入量是 **3 个**。根因：清洗按**分组**发生（各 2/1 个），但披露粒度写的是
**按列**（`column=req.target_col`）—— 两个粒度混用，于是同一列出现两个不同数字。
B1 契约要求披露「**数量与列名**」，同名不同量使总数不可知。

修法：**分组前**对整列清洗一次再切分两组（`_guard.clean_series` 只调用一次），
使披露条数、数量、错误码三者与真实注入量严格一致。
"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.root_cause.hypothesis import hypothesis_test

#: 三条"先分组、后清洗"的独立分支（`_ht_ks` / `_ht_cohens_d` / 独立双样本总入口）
_GROUPED_BRANCHES = ("ks", "cohens_d", "ttest_ind", "mannwhitney")

_INJECTED = 3


def _frame() -> pd.DataFrame:
    """60 行两组数据；3 个 `+Inf` 按 **A:2 + B:1** 切分（复现"2+1=3"的错位）。"""
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "g": ["A"] * 30 + ["B"] * 30,
            "y": np.r_[rng.normal(0, 1, 30), rng.normal(3, 1, 30)],
        }
    )
    frame.loc[0, "y"] = np.inf  # A 组
    frame.loc[1, "y"] = np.inf  # A 组
    frame.loc[30, "y"] = np.inf  # B 组
    return frame


def _run(branch: str):
    return hypothesis_test(
        AnalysisRequest(
            task="hypothesis_test",
            data=_frame(),
            target_col="y",
            feature_cols=["g"],
            params={"test": branch},
        )
    )


@pytest.mark.parametrize("branch", _GROUPED_BRANCHES)
def test_grouped_inf_disclosure_appears_once_with_the_true_total(branch):
    """同一列只能有一条披露，且数字 == 该列真实 ±Inf 总数（此处 3）。"""
    result = _run(branch)
    assert result.status == "ok", f"{branch}: {result.messages}"
    inf_msgs = [m for m in result.messages if "±Inf" in m or "非有限值" in m]
    assert len(inf_msgs) == 1, (
        f"{branch} 对同一列给出 {len(inf_msgs)} 条披露（同名不同量，总数不可知）：{inf_msgs}"
    )
    assert f"{_INJECTED} 个" in inf_msgs[0], (
        f"{branch} 披露的数量与真实注入量（{_INJECTED}）不符：{inf_msgs[0]}"
    )
    assert "「y」" in inf_msgs[0], f"{branch} 披露必须点名列名：{inf_msgs[0]}"


@pytest.mark.parametrize("branch", _GROUPED_BRANCHES)
def test_grouped_inf_boundary_code_is_not_duplicated(branch):
    """机器可读出口同样不得出现同码两条（下游按码计数会得到 2 次清洗）。"""
    result = _run(branch)
    codes = result.metadata.get("boundary_codes", [])
    assert codes.count("E_DATA_NON_FINITE_DROPPED") == 1, (
        f"{branch} 同码重复（计数不可核对）：{codes}"
    )


@pytest.mark.parametrize("branch", _GROUPED_BRANCHES)
def test_grouped_inf_cleaning_matches_dropping_the_rows(branch):
    """真清洗判据：结果必须与"直接删掉那 3 行"同解。"""
    dropped = _frame().drop(index=[0, 1, 30]).reset_index(drop=True)
    injected = _run(branch)
    reference = hypothesis_test(
        AnalysisRequest(
            task="hypothesis_test",
            data=dropped,
            target_col="y",
            feature_cols=["g"],
            params={"test": branch},
        )
    )
    assert injected.status == reference.status == "ok", (injected.messages, reference.messages)
    assert float(injected.metadata["statistic"]) == pytest.approx(
        float(reference.metadata["statistic"]), rel=1e-9
    ), f"{branch} 清洗结果与删行结果不一致（未真清洗）"


def test_grouped_nan_stays_silent():
    """NaN 属缺失语义（契约 L4）—— 分组清洗同样不得因此产生披露。"""
    frame = _frame()
    frame.loc[[0, 1, 30], "y"] = np.nan
    result = hypothesis_test(
        AnalysisRequest(
            task="hypothesis_test",
            data=frame,
            target_col="y",
            feature_cols=["g"],
            params={"test": "ttest_ind"},
        )
    )
    assert result.status == "ok", result.messages
    assert result.messages == [], f"NaN 被当成 ±Inf 披露：{result.messages}"


# ── 索引不变式（2026-10-10 用户级回归）：结论不得依赖 DataFrame 的索引 ──────────
# 复现形态：`pd.concat([g1, g2])` 把两张同为 0..n 的表拼起来 → **索引重复且不连续**。
# 这是极常见的用户操作（分表采集后合并、从 Excel 多次读入拼接）。
# 根因是"清洗后的 Series（保留原索引）+ 另一处的分组标签"混用：
# `.loc[cleaned.index, group_col]` 在重复索引下会对每个标签命中**全部**重复行而
# **膨胀**（实测 100 行 → 200 行 → 布尔索引 IndexError），
# 而 `_guard.clean_series` 的返回语义是**过滤后的对象**，不是等长掩码。
def _two_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(0)
    left = pd.DataFrame({"v": rng.normal(10, 1, 50), "g": "A"})
    right = pd.DataFrame({"v": rng.normal(13, 1, 50), "g": "B"})
    return left, right


@pytest.mark.parametrize("test_type", ["ttest_ind", "mannwhitney", "ks", "cohens_d", "auto"])
def test_concat_index_is_not_a_failure(test_type):
    """索引重复/不连续**不得**让任务报错，且结论必须与 `ignore_index=True` 逐值一致。"""
    left, right = _two_tables()
    concatenated = pd.concat([left, right])  # 索引 0..49, 0..49（重复且不连续）
    reindexed = pd.concat([left, right], ignore_index=True)
    assert not concatenated.index.is_unique, "前置：本用例的索引必须重复，否则失去意义"

    def run(frame):
        return hypothesis_test(
            AnalysisRequest(
                task="hypothesis_test",
                data=frame,
                target_col="v",
                feature_cols=["g"],
                params={"test": test_type},
            )
        )

    dup, flat = run(concatenated), run(reindexed)
    assert dup.status == "ok", f"{test_type}: 索引不连续导致任务报错（用户级回归）：{dup.messages}"
    assert float(dup.metadata["statistic"]) == pytest.approx(
        float(flat.metadata["statistic"]), rel=1e-12
    ), f"{test_type}: 结论依赖索引"
    if test_type != "cohens_d":
        # `cohens_d` 是纯效应量分支（无 p 值，`p_value=None` 是其既有语义）；
        # 其余分支必须给出 p 值 —— 这是 `verify_consistency.py` 门禁的判据。
        assert dup.metadata.get("p_value") is not None, (
            f"{test_type}: metadata['p_value'] 缺失（verify_consistency 门禁的判据）"
        )
        assert float(dup.metadata["p_value"]) == pytest.approx(
            float(flat.metadata["p_value"]), rel=1e-12
        ), f"{test_type}: p 值依赖索引"


@pytest.mark.parametrize("test_type", ["ttest_ind", "mannwhitney", "ks"])
def test_concat_index_with_inf_cleaning_still_agrees(test_type):
    """两者叠加（索引重复 **且** 有 ±Inf 被剔除）—— 最易再犯的组合。"""
    left, right = _two_tables()
    left.loc[0, "v"] = np.inf  # A 组 1 个
    right.loc[[0, 1], "v"] = np.inf  # B 组 2 个（真实总数 3）
    concatenated = pd.concat([left, right])
    reindexed = pd.concat([left, right], ignore_index=True)

    def run(frame):
        return hypothesis_test(
            AnalysisRequest(
                task="hypothesis_test",
                data=frame,
                target_col="v",
                feature_cols=["g"],
                params={"test": test_type},
            )
        )

    dup, flat = run(concatenated), run(reindexed)
    assert dup.status == "ok", f"{test_type}: {dup.messages}"
    assert float(dup.metadata["p_value"]) == pytest.approx(
        float(flat.metadata["p_value"]), rel=1e-12
    ), f"{test_type}: 剔除 ±Inf 后结论依赖索引"
    inf_msgs = [m for m in dup.messages if "±Inf" in m or "非有限值" in m]
    assert len(inf_msgs) == 1 and "3 个" in inf_msgs[0], (
        f"{test_type}: 披露应为单条且总数正确（3）：{dup.messages}"
    )
