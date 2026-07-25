"""Reporter 服务层单元测试。

覆盖范围：
- PDF 输出（正常/空结果）
- PPT 输出（正常/空结果）
- HTML 输出（正常/空结果）
- 无图表/无表格场景
"""
import os
import tempfile

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.services.orchestrator import orchestrate


# ── PDF 输出测试 ──

def test_reporter_pdf_output(sample_doe_data):
    """验证 PDF 报告正常生成。"""
    from smartsuite.services.reporter import to_pdf
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = to_pdf(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_reporter_pdf_empty_result():
    """验证空结果生成 PDF 不崩溃。"""
    from smartsuite.services.reporter import to_pdf
    empty_result = AnalysisResult(
        task="test", status="ok",
        summary="测试空结果",
        tables={},
        figures=[],
    )
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = to_pdf(empty_result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── PPT 输出测试 ──

def test_reporter_ppt_output(sample_doe_data):
    """验证 PPT 报告正常生成。"""
    from smartsuite.services.reporter import to_ppt
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={"direction": "maximize"},
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        out = to_ppt(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_reporter_ppt_empty_result():
    """验证空结果生成 PPT 不崩溃。"""
    from smartsuite.services.reporter import to_ppt
    empty_result = AnalysisResult(
        task="test", status="ok",
        summary="测试空结果",
        tables={},
        figures=[],
    )
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        out = to_ppt(empty_result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── HTML 输出测试 ──

def test_reporter_html_output(sample_doe_data):
    """验证 HTML 报告正常生成。"""
    from smartsuite.services.reporter import to_html
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        out = to_html(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        # 验证 HTML 内容包含基本结构
        with open(out, encoding="utf-8") as f:
            content = f.read()
        assert "<html" in content.lower() or "<!doctype" in content.lower()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_reporter_html_empty_result():
    """验证空结果生成 HTML 不崩溃。"""
    from smartsuite.services.reporter import to_html
    empty_result = AnalysisResult(
        task="test", status="ok",
        summary="测试空结果",
        tables={},
        figures=[],
    )
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        out = to_html(empty_result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── 边界场景测试 ──

def test_reporter_result_with_tables_no_figures(sample_doe_data):
    """验证有表格无图表的结果正常输出。"""
    from smartsuite.services.reporter import to_html
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率", feature_cols=["料温"],
    )
    result = orchestrate(req)
    # 清空图表
    result_no_figs = AnalysisResult(
        task=result.task, status=result.status,
        summary=result.summary, tables=result.tables,
        figures=[],  # 无图表
        metadata=result.metadata,
    )
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        out = to_html(result_no_figs, path)
        assert os.path.exists(out)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_reporter_error_result():
    """验证错误状态结果正常输出。"""
    from smartsuite.services.reporter import to_html
    error_result = AnalysisResult(
        task="test", status="error",
        summary="分析失败",
        messages=["错误消息 1", "错误消息 2"],
        tables={},
        figures=[],
    )
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        out = to_html(error_result, path)
        assert os.path.exists(out)
        with open(out, encoding="utf-8") as f:
            content = f.read()
        # 错误消息应包含在输出中
        assert "错误消息" in content or "error" in content.lower()
    finally:
        if os.path.exists(path):
            os.unlink(path)
