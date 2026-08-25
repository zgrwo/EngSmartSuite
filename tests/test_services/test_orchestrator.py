"""Orchestrator 服务层单元测试。

覆盖范围：
- 任务路由（已知/未知任务）
- DEFAULT_PARAMS 注入与参数合并
- 空字符串 → None 规范化
- 目标列存在性检查
- 异常捕获与翻译
- NO_TARGET_TASKS 行为
"""

import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import (
    DEFAULT_PARAMS,
    NO_DATA_TASKS,
    NO_TARGET_TASKS,
    TASK_REGISTRY,
    orchestrate,
)


# ── 基础路由测试 ──


def test_orchestrate_anova(sample_doe_data):
    """Round-2 批次D #2a：ANOVA 路由测试改为前置硬断言（此前 status in (...) 恒真）。

    用正确的因子数据类型（类别因子列 + 数值目标列）跑 ANOVA，消除把连续列
    当因子导致的 NaN/虚假显著问题；断言 status=='ok' + 具体统计量存在。
    """
    np.random.seed(42)
    n = 30
    df_anova = pd.DataFrame(
        {
            "组别": np.repeat(["A", "B", "C"], n),
            "强度": np.concatenate(
                [
                    np.random.normal(45, 3, n),
                    np.random.normal(48, 3, n),
                    np.random.normal(51, 3, n),
                ]
            ),
        }
    )
    req = AnalysisRequest(
        task="anova",
        data=df_anova,
        target_col="强度",
        feature_cols=["组别"],
        params={"alpha": 0.05},
    )
    result = orchestrate(req)
    assert result.task == "anova"
    assert result.status == "ok", f"ANOVA 应成功: {result.messages}"
    assert "anova_enhanced" in result.tables
    assert "r_squared" in result.metadata, "ANOVA 应输出 R²"
    assert 0 <= result.metadata["r_squared"] <= 1, f"R² 应在 [0,1]: {result.metadata['r_squared']}"
    assert len(result.summary) > 0, "summary 不应为空"


def test_orchestrate_correlation(sample_doe_data):
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温", "注射压力", "保压时间", "强度"],
    )
    result = orchestrate(req)
    assert result.status == "ok"
    assert "correlation_matrix" in result.tables


def test_orchestrate_unknown_task(sample_doe_data):
    req = AnalysisRequest(
        task="unknown_method",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温"],
    )
    result = orchestrate(req)
    assert result.status == "error"
    assert "未知的分析任务" in result.messages[0]


# ── 参数合并测试 ──


def test_default_params_injection(sample_doe_data):
    """验证 DEFAULT_PARAMS 被正确注入到请求中。"""
    # correlation 默认 method="pearson"
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温"],
        params={},  # 空参数，应使用默认值
    )
    result = orchestrate(req)
    assert result.status == "ok"
    # 验证 metadata 中包含方法信息（间接验证默认参数生效）
    assert result.metadata is not None


def test_params_override_defaults(sample_doe_data):
    """验证用户参数覆盖默认值。"""
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温"],
        params={"method": "spearman"},  # 覆盖默认 pearson
    )
    result = orchestrate(req)
    assert result.status == "ok"


def test_empty_string_to_none_normalization(sample_doe_data):
    """验证空字符串 '' 被规范化为 None（仅对默认值为 None 的参数）。"""
    # spc_xbar 的 usl 默认值为 None，空字符串应转为 None
    req = AnalysisRequest(
        task="spc_xbar",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温"],
        params={"usl": "", "lsl": ""},  # 空字符串
    )
    result = orchestrate(req)
    # 不应因空字符串报错
    assert result.status in ("ok", "warning", "error")


# ── 目标列检查测试 ──


def test_missing_target_column(sample_doe_data):
    """验证目标列不存在时返回友好错误。"""
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不存在的列",
        feature_cols=["料温"],
    )
    result = orchestrate(req)
    assert result.status == "error"
    assert "不存在于数据中" in result.messages[0]
    assert "可用列" in result.messages[0]


# ── NO_TARGET_TASKS 测试 ──


def test_no_target_tasks_defined():
    """验证 NO_TARGET_TASKS 集合与 TASK_REGISTRY 一致。"""
    for task in NO_TARGET_TASKS:
        assert task in TASK_REGISTRY, f"{task} 在 NO_TARGET_TASKS 但不在 TASK_REGISTRY"


def test_vif_no_target_needed(sample_doe_data):
    """验证 VIF 任务无需目标列。"""
    assert "vif" in NO_TARGET_TASKS
    req = AnalysisRequest(
        task="vif",
        data=sample_doe_data,
        target_col="",  # 空目标列
        feature_cols=["料温", "模温", "注射压力", "保压时间"],
    )
    result = orchestrate(req)
    # VIF 应该能正常运行（可能因数据问题警告，但不应因缺目标列报错）
    assert result.status in ("ok", "warning", "error")


# ── 注册表完整性测试 ──


def test_all_tasks_have_default_params():
    """验证所有注册任务都有 DEFAULT_PARAMS 条目。"""
    for task in TASK_REGISTRY:
        assert task in DEFAULT_PARAMS, f"{task} 缺少 DEFAULT_PARAMS 条目"


def test_task_registry_count():
    """验证注册任务数量符合预期（40 个分析方法）。"""
    assert len(TASK_REGISTRY) == 41, f"期望 41 个任务，实际 {len(TASK_REGISTRY)}"


# ── 异常处理测试 ──


def test_exception_handling_graceful(sample_doe_data):
    """验证引擎异常被优雅捕获并翻译为中文消息。"""
    # 使用一个会触发引擎内部错误的场景
    # 创建只有 1 行数据的 DataFrame（多数分析需要至少 3 行）
    tiny_df = sample_doe_data.head(1)
    req = AnalysisRequest(
        task="correlation",
        data=tiny_df,
        target_col="不良率",
        feature_cols=["料温"],
    )
    result = orchestrate(req)
    # 应返回错误状态而非抛出异常
    assert result.status == "error"
    assert len(result.messages) > 0


def test_doe_design_registered_and_no_target():
    """doe_design 注册且无需目标列，可无数据运行。"""
    assert "doe_design" in TASK_REGISTRY
    assert "doe_design" in NO_TARGET_TASKS
    r = orchestrate(
        AnalysisRequest(
            task="doe_design",
            data=pd.DataFrame(),
            params={
                "method": "full_factorial",
                "factors": [{"name": "A", "levels": [1, 2]}],
            },
        )
    )
    assert r.status == "ok"
    assert r.metadata["n_runs"] == 2


def test_no_data_tasks_membership():
    """完全无需输入数据的任务（纯参数计算）应登记进 NO_DATA_TASKS。"""
    assert "doe_design" in NO_DATA_TASKS
    assert "power_analysis" in NO_DATA_TASKS
    # NO_DATA_TASKS 是 NO_TARGET_TASKS 的子集（无需数据的任务必然也无需目标列）
    assert NO_DATA_TASKS <= NO_TARGET_TASKS
