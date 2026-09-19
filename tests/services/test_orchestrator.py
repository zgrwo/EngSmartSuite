"""Orchestrator 服务层单元测试。

覆盖范围：
- 任务路由（已知/未知任务）
- DEFAULT_PARAMS 注入与参数合并
- 空字符串规范化（'' → 该参数默认值；默认值为 None 时即 '' → None）
- 目标列存在性检查
- 异常捕获与翻译
- NO_TARGET_TASKS 行为
"""

import pytest
import numpy as np
import pandas as pd

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
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
    # 值级断言：用户参数 method=spearman 必须覆盖默认 pearson
    assert result.metadata.get("method") == "spearman", (
        f"参数覆盖失败: method={result.metadata.get('method')}"
    )


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
    # 空字符串应规范化为 None：不报错且输出有效控制限（UCL > CL > LCL）
    assert result.status == "ok", f"空字符串应规范化为 None 而非报错: {result.messages}"
    cl_table = result.tables.get("control_limits")
    assert cl_table is not None and len(cl_table) >= 1, "spc_xbar 应输出 control_limits 表"
    row = cl_table.iloc[0]
    assert row["UCL"] > row["CL"] > row["LCL"], f"控制限应满足 UCL > CL > LCL: {row.to_dict()}"
    # 精确值（固定种子数据）：CL=44.8208, UCL=51.8562, LCL=37.7855
    assert all(
        (
            abs(float(row["CL"]) - 44.8208) < 0.01,
            abs(float(row["UCL"]) - 51.8562) < 0.01,
            abs(float(row["LCL"]) - 37.7855) < 0.01,
        )
    ), f"控制限数值漂移: {row.to_dict()}"


# ── 空字符串归一：非 None 默认值（审查 2026-09-19 E11）──
#
# 旧逻辑仅对「默认值为 None」的参数做 '' → None；默认值非 None 的枚举参数
# 收到 JS 清空后的 '' 会直达引擎并报错（'不支持的检验类型: '）。
# 新语义：'' 一律视为「未提供」→ 回退该参数的默认值；未知键保持原样。


def test_empty_string_enum_param_falls_back_to_default():
    """枚举参数 test_type='' 应回退默认 'ttest'（复现：此前报「不支持的检验类型: 」）。"""
    req = AnalysisRequest(task="power_analysis", data=pd.DataFrame(), params={"test_type": ""})
    result = orchestrate(req)
    assert result.status == "ok", f"空枚举参数应回退默认值: {result.messages}"
    assert result.metadata["test_type"] == DEFAULT_PARAMS["power_analysis"]["test_type"]
    assert result.metadata["required_n"] == 64, "应与空 params 的结果一致"


def test_empty_string_mode_falls_back_to_default():
    """枚举参数 mode='' 应回退默认 'required_n'（复现：此前报「未知模式: 」）。"""
    req = AnalysisRequest(task="power_analysis", data=pd.DataFrame(), params={"mode": ""})
    result = orchestrate(req)
    assert result.status == "ok", f"空枚举参数应回退默认值: {result.messages}"
    assert result.metadata["mode"] == "required_n"


def test_empty_string_numeric_param_falls_back_to_default():
    """数值参数 alpha='' 应回退默认 0.05（而非静默取其它值）。"""
    req = AnalysisRequest(task="power_analysis", data=pd.DataFrame(), params={"alpha": ""})
    result = orchestrate(req)
    assert result.status == "ok", f"空数值参数应回退默认值: {result.messages}"
    assert result.metadata["alpha"] == DEFAULT_PARAMS["power_analysis"]["alpha"]


def test_explicit_param_still_overrides_default():
    """归一化不得吞掉显式传入的非空值（防把有效参数也换成默认）。"""
    req = AnalysisRequest(task="power_analysis", data=pd.DataFrame(), params={"test_type": "anova"})
    result = orchestrate(req)
    assert result.status == "ok", result.messages
    assert result.metadata["test_type"] == "anova", "显式参数必须生效"
    assert result.metadata["required_n"] == 14


def test_unknown_param_key_passes_through_unchanged(monkeypatch):
    """未知键 '' 不归一到默认值（不吞用户输入），原样传给引擎。"""
    from smartsuite.services import orchestrator as orch

    received: dict = {}

    def _spy(req):
        received.update(req.params)
        return AnalysisResult(task=req.task, status="ok", summary="spy")

    monkeypatch.setitem(orch.TASK_REGISTRY, "correlation", _spy)
    req = AnalysisRequest(
        task="correlation",
        data=pd.DataFrame({"a": [1.0, 2.0, 3.0]}),
        target_col="a",
        params={"foo": "", "method": "spearman"},
    )
    result = orchestrate(req)
    assert result.status == "ok", result.messages
    assert received["foo"] == "", "未知键应原样透传"
    assert received["method"] == "spearman", "默认值仍应注入"


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
    # VIF 无需目标列：应正常输出全部 4 个因子的 VIF，且 VIF ≥ 1（数学下界）
    assert result.status == "ok", f"VIF 无需目标列应成功: {result.messages}"
    vt = result.tables.get("vif_table")
    assert vt is not None and len(vt) == 4, (
        f"应输出 4 个因子的 vif_table，实际 {None if vt is None else len(vt)}"
    )
    vif_vals = [float(v) for v in vt.iloc[:, 1]]
    assert all(v >= 1.0 for v in vif_vals), f"VIF 不应小于 1: {vif_vals}"


# ── 注册表完整性测试 ──


def test_all_tasks_have_default_params():
    """验证所有注册任务都有 DEFAULT_PARAMS 条目。"""
    for task in TASK_REGISTRY:
        assert task in DEFAULT_PARAMS, f"{task} 缺少 DEFAULT_PARAMS 条目"


def test_default_params_keys_are_registered():
    """验证 DEFAULT_PARAMS 的键都是已注册任务（反向一致性，防幽灵条目）。"""
    for task in DEFAULT_PARAMS:
        assert task in TASK_REGISTRY, f"DEFAULT_PARAMS 中的 '{task}' 不在 TASK_REGISTRY 中"


def test_task_registry_count():
    """验证注册任务数量符合预期（42 个分析方法）。"""
    assert len(TASK_REGISTRY) == 42, f"期望 42 个任务，实际 {len(TASK_REGISTRY)}"


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


# ── 核心依赖检查（审查 #R2：__init__.py 公共函数纳入缺测检查后补测）──


def test_check_core_deps_ok_when_installed():
    """核心依赖齐全时 check_core_deps 不抛异常。"""
    import smartsuite as pkg

    pkg.check_core_deps()  # 本环境已安装全部依赖，应正常返回


def test_check_core_deps_raises_friendly_import_error(monkeypatch):
    """缺失依赖时抛出含中文安装提示的 ImportError。"""
    import smartsuite as pkg

    monkeypatch.setattr(pkg, "_CORE_DEPS", {"smartsuite_no_such_pkg_xyz": "pip install xxx"})
    with pytest.raises(ImportError) as ei:
        pkg.check_core_deps()
    assert "缺少必要的核心依赖包" in str(ei.value)
    assert "pip install" in str(ei.value)


# ── 异常翻译表（orchestrate 兜底分支，覆盖 248-294）──


def _raise(exc):
    def _fn(req):
        raise exc

    return _fn


def test_orchestrate_smartsuite_error_returns_chinese_error(monkeypatch):
    """引擎抛 SmartSuiteError → 兜底为 status=error 中文消息（orchestrator.py:248-260）。"""
    from smartsuite.core.exceptions import AnalysisError
    from smartsuite.services import orchestrator as orch

    monkeypatch.setitem(orch.TASK_REGISTRY, "correlation", _raise(AnalysisError("矩阵病态")))
    req = AnalysisRequest(task="correlation", data=pd.DataFrame({"a": [1, 2]}), target_col="a")
    result = orchestrate(req)
    assert result.status == "error"
    assert "分析执行失败: 矩阵病态" in result.messages[0]
    assert "请联系开发者" in result.messages[1]


def test_orchestrate_known_exception_detail_map(monkeypatch):
    """ValueError/KeyError 命中翻译表 → 中文工艺术语，不暴露异常原文（orchestrator.py:261-294）。"""
    from smartsuite.services import orchestrator as orch

    req = AnalysisRequest(task="correlation", data=pd.DataFrame({"a": [1, 2]}), target_col="a")
    monkeypatch.setitem(orch.TASK_REGISTRY, "correlation", _raise(ValueError("bad data")))
    r1 = orchestrate(req)
    assert r1.status == "error"
    assert "数据格式不符合分析要求" in r1.messages[0]
    assert "bad data" not in r1.messages[0], "不得泄漏异常原文"

    monkeypatch.setitem(orch.TASK_REGISTRY, "correlation", _raise(KeyError("内部键")))
    r2 = orchestrate(req)
    assert "键不存在" in r2.messages[0], "KeyError 应翻译为数据处理异常提示"


def test_orchestrate_unmapped_exception_falls_back_to_generic(monkeypatch):
    """翻译表未登记的异常类型 → 通用中文兜底（orchestrator.py:286）。"""
    from smartsuite.services import orchestrator as orch

    class ExoticError(Exception):
        pass

    monkeypatch.setitem(orch.TASK_REGISTRY, "correlation", _raise(ExoticError("mystery")))
    req = AnalysisRequest(task="correlation", data=pd.DataFrame({"a": [1, 2]}), target_col="a")
    result = orchestrate(req)
    assert result.status == "error"
    assert "分析计算过程中出现异常" in result.messages[0]
