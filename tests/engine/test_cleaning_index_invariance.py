"""清洗路径的**索引不变式**：结论不得依赖 DataFrame 的索引是否连续/唯一。

## 为什么需要这条门禁（2026-10-10 用户级回归）

`pd.concat([上半, 下半])` —— 两张各自从 0 开始编号的表拼接（分表采集后合并、
从 Excel 多次读入再拼接）—— 会产生**索引重复且不连续**的 DataFrame。这是
极常见的用户操作，而本轮 R2BD-02/03/11 的清洗改造一度让 `hypothesis_test`
在**全部** `test` 分支上抛 `IndexError`（实测 `size of axis is 100 but size of
corresponding boolean axis is 400`），`scripts/verify_consistency.py` 随之 70/71
—— 该门禁是 `ci.yml` 的 `quick` 腿，quick 红则 e2e/full/quality 全部不可达。

## 根因与纪律

`_guard.clean_series` / `clean_frame` 的返回语义是**过滤后的对象（保留原索引）**，
**不是等长布尔掩码**。于是"清洗结果 + 另一处取的分组标签/位置数组"混用就会炸：

```python
cleaned = clean_series(req.data[col], ...)[0]      # 保留原索引
labels = req.data.loc[cleaned.index, group_col]    # ✗ 重复索引下 .loc 会**膨胀**
```

`.loc` 对重复标签会命中**全部**重复行（100 行 → 200 行），随后布尔索引越界。
正确做法：**先把参与清洗的列 `reset_index(drop=True)`，再按位置取标签**，
使清洗结果与分组标签同源同长。

## 本门禁的判据

对每个任务跑两遍 —— 一遍用重复索引，一遍用 `ignore_index=True` —— 断言：

1. 两次都不得抛异常（`IndexError` 属红线：引擎必须返回 `AnalysisResult`）；
2. `status` 一致；
3. 双方共有的数值型 `metadata` 逐值一致（`rtol=1e-9`）。

叠加 `±Inf` 注入（清洗会真的改变行数）—— 那是"清洗后对象 + 别处位置数组"
最容易被暴露的组合。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import TASK_REGISTRY

#: (task, 上半帧的列, 下半帧的列, target, features, params)
#: 帧列中 `"g"` 表示分组标签列（取字典值作为该半边的组名），其余为 N(·,1) 数值列。
_CASES: list[tuple[str, dict, dict, str, list[str], dict]] = [
    ("process_capability", {"y": None}, {"y": None}, "y", [], {"usl": 14.0, "lsl": 6.0}),
    ("distribution_summary", {"y": None}, {"y": None}, "y", [], {}),
    ("normality_check", {"y": None}, {"y": None}, "y", [], {}),
    ("outlier_consensus", {"y": None}, {"y": None}, "y", [], {}),
    ("trend_forecast", {"y": None}, {"y": None}, "y", [], {}),
    ("spc_xbar", {"y": None}, {"y": None}, "y", [], {}),
    ("spc_nonparametric", {"y": None}, {"y": None}, "y", [], {}),
    (
        "tolerance_interval",
        {"y": None},
        {"y": None},
        "y",
        [],
        {"coverage": 0.99, "confidence": 0.95},
    ),
    ("median_ci", {"y": None}, {"y": None}, "y", [], {}),
    ("bootstrap_ci", {"y": None}, {"y": None}, "y", [], {"n_bootstrap": 200}),
    (
        "scatter_plot",
        {"y": None, "x1": None},
        {"y": None, "x1": None},
        "y",
        ["x1"],
        {"fit": "linear"},
    ),
    ("regression", {"y": None, "x1": None}, {"y": None, "x1": None}, "y", ["x1"], {}),
    (
        "lasso_regression",
        {"y": None, "x1": None, "x2": None},
        {"y": None, "x1": None, "x2": None},
        "y",
        ["x1", "x2"],
        {},
    ),
    ("robust_regression", {"y": None, "x1": None}, {"y": None, "x1": None}, "y", ["x1"], {}),
    (
        "hypothesis_test",
        {"y": None, "g": "A"},
        {"y": None, "g": "B"},
        "y",
        ["g"],
        {"test": "ttest_ind"},
    ),
]

_N_PER_HALF = 40


def _half(spec: dict, seed: int, inject_inf: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    columns = {}
    for name, literal in spec.items():
        if literal is None:
            columns[name] = rng.normal(10.0 if name == "y" else 1.0, 1.0, _N_PER_HALF)
        else:
            columns[name] = [literal] * _N_PER_HALF
    frame = pd.DataFrame(columns)
    if inject_inf:
        frame.loc[0, "y"] = np.inf
    return frame


def _run(task, target, feats, params, data):
    """直接调编排层注册的函数（异常会原样冒出，便于断言"不得抛异常"）。"""
    with warnings.catch_warnings():
        # 生产口径：本用例要断言"生产下结论不依赖索引"，而 pytest 的
        # filterwarnings=["error"] 会把 numpy 的溢出 RuntimeWarning 升为异常，
        # 使执行在产生结论之前中断 → 断言空过（假绿，见该轮报告 §三）。
        warnings.simplefilter("default")
        return TASK_REGISTRY[task](
            AnalysisRequest(
                task=task, data=data, target_col=target, feature_cols=feats, params=params
            )
        )


@pytest.mark.parametrize("inject_inf", [False, True], ids=["clean", "with-inf"])
@pytest.mark.parametrize(
    ("task", "upper", "lower", "target", "feats", "params"),
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_conclusion_does_not_depend_on_dataframe_index(
    task, upper, lower, target, feats, params, inject_inf
):
    """重复/不连续索引不得改变任何结论（`pd.concat` 拼接是常见用户操作）。"""
    top, bottom = _half(upper, 11, inject_inf), _half(lower, 12, inject_inf)
    duplicated = pd.concat([top, bottom])
    assert not duplicated.index.is_unique, "前置：本用例的索引必须重复，否则失去意义"

    with_dup_index = _run(task, target, feats, params, duplicated)
    flat_index = _run(task, target, feats, params, pd.concat([top, bottom], ignore_index=True))

    assert with_dup_index.status == flat_index.status, (
        f"{task}（注入 ±Inf={inject_inf}）索引改变了 status："
        f"{with_dup_index.status} vs {flat_index.status}；"
        f"messages={with_dup_index.messages}"
    )
    mismatched = []
    numeric = (int, float, np.integer, np.floating)
    for key, value in (with_dup_index.metadata or {}).items():
        other = flat_index.metadata.get(key)
        comparable = (
            isinstance(value, numeric)
            and not isinstance(value, bool)
            and isinstance(other, numeric)
        )
        if comparable and not np.isclose(
            float(value), float(other), rtol=1e-9, atol=0.0, equal_nan=True
        ):
            mismatched.append(f"{key}: {value} != {other}")
    assert not mismatched, f"{task}（注入 ±Inf={inject_inf}）结论依赖索引：{mismatched}"
