"""手册「常见参数误用」消息 ↔ 引擎输出 双向契约（审查 2026-09-19 C5）。

项目历史教训是「手册数值与实际不一致」反复出现（10+ 次），根因是手册里的断言没有
任何门禁。C5 在各方法章节补了「常见参数误用」表，表里逐条引用了引擎的**实际输出**，
本文件把这份引用变成可执行契约：

- **正向**：按表中记录的方式触发误用，引擎必须给出同一条消息（防引擎文案改了、
  手册没跟着改）；
- **反向**：该消息确实写在对应章节里（防手册删了、测试还在自说自话）。

两侧都断言，任何一侧漂移都会变红。
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

_MANUAL = Path(__file__).resolve().parents[2] / "docs" / "user-manual"


def _numeric(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(20260919)
    return pd.DataFrame(
        {
            "强度": rng.normal(45, 3, n),
            "温度": rng.normal(200, 5, n),
            "压力": rng.normal(80, 4, n),
            "材料": rng.choice(["ABS", "PP"], n),
            "常数": 1.0,
            "零件": [f"P{i % 10}" for i in range(n)],
            "操作员": rng.choice(["甲", "乙"], n),
            "测量": rng.normal(10, 0.2, n),
        }
    )


def _first_message(task: str, **kwargs) -> str:
    # 注意：不能写 `kwargs.pop("data", None) or _numeric()` —— DataFrame 的 __bool__ 会
    # 抛「truth value is ambiguous」（本文件首版即踩此坑）
    data = kwargs.pop("data", None)
    if data is None:
        data = _numeric()
    req = AnalysisRequest(task=task, data=data, **kwargs)
    result = orchestrate(req)
    assert result.status == "error", f"{task} 应为 error，实际 {result.status}"
    return result.messages[0]


# (章节文件, 手册中引用的消息片段, task, 触发参数, 数据行数)
_CASES = [
    (
        "04-root-cause.md",
        "以下列非数值型，无法计算相关性",
        "correlation",
        {"target_col": "材料", "feature_cols": ["温度"]},
        None,
    ),
    (
        "04-root-cause.md",
        "至少需要 1 个因子列与目标列进行相关性分析",
        "correlation",
        {"target_col": "强度", "feature_cols": []},
        None,
    ),
    (
        "04-root-cause.md",
        "没有可用于 ANOVA 分析的特征列",
        "anova",
        {"target_col": "强度", "feature_cols": ["不存在的列"]},
        None,
    ),
    (
        "04-root-cause.md",
        "方差为零（常量列）",
        "correlation",
        {"target_col": "常数", "feature_cols": ["温度"]},
        None,
    ),
    (
        "04-root-cause.md",
        "control_vars 必须是列名列表或逗号分隔字符串",
        "correlation",
        {"target_col": "强度", "feature_cols": ["温度"], "params": {"control_vars": 5}},
        None,
    ),
    (
        "05-reliability.md",
        "需要 2 个评定者列",
        "cohens_kappa",
        {"target_col": "强度", "feature_cols": []},
        None,
    ),
    (
        "05-reliability.md",
        "至少需要 2 个题项列",
        "cronbach_alpha",
        {"target_col": "强度", "feature_cols": []},
        None,
    ),
    (
        "06-modeling.md",
        "不足，需要至少5条",
        "regression",
        {"target_col": "强度", "feature_cols": ["温度", "压力", "材料"]},
        4,
    ),
    (
        "06-modeling.md",
        "目标列需要恰好 2 个不同值",
        "logistic_regression",
        {"target_col": "强度", "feature_cols": ["温度"]},
        None,
    ),
    (
        "06-modeling.md",
        "需要至少 1 个因子列",
        "decision_tree",
        {"target_col": "强度", "feature_cols": []},
        None,
    ),
    (
        "06-modeling.md",
        "需要提供因子定义 (factors)",
        "doe_design",
        {"target_col": "强度", "feature_cols": ["温度", "压力"], "params": {}},
        None,
    ),
    (
        "06-modeling.md",
        "需要提供优化目标 (objectives)",
        "multi_objective",
        {"target_col": "强度", "feature_cols": [], "params": {}},
        None,
    ),
    (
        "06-modeling.md",
        "需要提供参数搜索范围 (ranges)",
        "grid_search",
        {"target_col": "强度", "feature_cols": ["温度"], "params": {}},
        None,
    ),
    (
        "06-modeling.md",
        "未识别到输出列（前缀 output/输出）",
        "inverse_solve",
        {"target_col": "强度", "feature_cols": ["温度", "压力"], "params": {}},
        None,
    ),
    (
        "07-spc.md",
        "规格限无效",
        "process_capability",
        {"target_col": "强度", "feature_cols": [], "params": {"usl": 10, "lsl": 100}},
        None,
    ),
    (
        "08-advanced.md",
        "有效数据不足(至少5个点)",
        "bootstrap_ci",
        {"target_col": "强度", "feature_cols": []},
        1,
    ),
    (
        "07-spc.md",
        "有效数据不足(至少20个点)",
        "change_point",
        {"target_col": "强度", "feature_cols": []},
        5,
    ),
    (
        "08-advanced.md",
        "需要提供事件指示列 (1=失效, 0=删失)",
        "survival_analysis",
        {"target_col": "强度", "feature_cols": [], "params": {}},
        None,
    ),
    (
        "08-advanced.md",
        "需要提供部件列和操作员列",
        "gage_rr",
        {"target_col": "测量", "feature_cols": [], "params": {}},
        None,
    ),
]


@pytest.mark.parametrize(
    ("chapter", "message", "task", "kwargs", "rows"),
    _CASES,
    ids=[f"{c.split('-')[0]}-{t}" for c, _, t, _, _ in _CASES],
)
def test_pitfall_message_is_documented_in_manual(chapter, message, task, kwargs, rows):
    """反向：手册对应章节确实写了这条消息（防手册删除后测试仍自说自话）。"""
    text = (_MANUAL / chapter).read_text(encoding="utf-8")

    assert message in text, f"{chapter} 未记录消息「{message}」"


@pytest.mark.parametrize(
    ("chapter", "message", "task", "kwargs", "rows"),
    _CASES,
    ids=[f"{c.split('-')[0]}-{t}" for c, _, t, _, _ in _CASES],
)
def test_pitfall_message_is_actually_produced(chapter, message, task, kwargs, rows):
    """正向：按手册记录的方式触发误用，引擎必须给出同一条消息。"""
    call_kwargs = dict(kwargs)
    if rows is not None:
        call_kwargs["data"] = _numeric().head(rows)

    produced = _first_message(task, **call_kwargs)

    assert message in produced, f"{task} 实际输出与手册不符：{produced!r}"


def test_manual_pitfall_sections_exist_in_all_method_chapters():
    """五个方法章节都必须有该小节（每章 ≤30 行由写作约束保证）。"""
    chapters = [
        "04-root-cause.md",
        "05-reliability.md",
        "06-modeling.md",
        "07-spc.md",
        "08-advanced.md",
    ]
    for chapter in chapters:
        text = (_MANUAL / chapter).read_text(encoding="utf-8")
        assert "### 常见参数误用" in text, f"{chapter} 缺少「常见参数误用」小节"
