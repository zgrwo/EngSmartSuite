"""端到端集成测试。"""
import os
import tempfile

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import TASK_REGISTRY, orchestrate
from smartsuite.services.reporter import to_pdf, to_ppt


def test_full_pipeline_anova_to_pdf(sample_doe_data):
    req = AnalysisRequest(
        task="anova", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温", "注射压力", "保压时间"],
        params={"alpha": 0.05},
    )
    result = orchestrate(req)
    assert result.status in ("ok", "warning")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        to_pdf(result, path)
        assert os.path.getsize(path) > 100
    finally:
        os.unlink(path)


def test_full_pipeline_rsm_to_ppt(sample_doe_data):
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    assert len(result.figures) >= 1

    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        to_ppt(result, path)
        assert os.path.getsize(path) > 1000
    finally:
        os.unlink(path)


def test_all_tasks_registered():
    """确保所有引擎函数都在 TASK_REGISTRY 中注册（双向检查）。"""
    import smartsuite.engine as eng
    assert len(eng.__all__) > 0, "engine.__all__ 为空，注册表验证无效"
    registered_func_names = {f.__name__ for f in TASK_REGISTRY.values()}
    # __all__ → TASK_REGISTRY: engine 导出的都在 registry 中
    # 排除配色常量（GROUP_COLORS/PALETTE，非分析函数，不在 TASK_REGISTRY 中）
    _analysis_names = {n for n in eng.__all__ if not n.isupper()}
    missing_in_registry = _analysis_names - registered_func_names
    assert not missing_in_registry, f"engine.__all__ 中有未注册的函数: {missing_in_registry}"
    # TASK_REGISTRY → __all__: registry 中的都在 engine 导出中
    missing_in_all = registered_func_names - set(eng.__all__)
    assert not missing_in_all, f"TASK_REGISTRY 中有未在 engine.__all__ 中导出的函数: {missing_in_all}"


def test_invalid_task_returns_error():
    import pandas as pd
    req = AnalysisRequest(
        task="nonexistent", data=pd.DataFrame({"a": [1, 2, 3]}), target_col="a")
    result = orchestrate(req)
    assert result.status == "error"


def test_missing_column_validation(sample_doe_data):
    from smartsuite.core.exceptions import ValidationError
    from smartsuite.services.data_io import validate_data
    try:
        validate_data(sample_doe_data, "不存在的列", ["料温"])
        raise AssertionError("should have raised ValidationError")
    except ValidationError:
        pass
