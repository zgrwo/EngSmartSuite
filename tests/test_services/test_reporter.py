"""Reporter 服务层单元测试。

覆盖范围：
- PDF 输出（正常/空结果）
- PPT 输出（正常/空结果）
- HTML 输出（正常/空结果）
- 无图表/无表格场景
"""

import os
import tempfile

import pandas as pd

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.services.orchestrator import orchestrate


# ── PDF 输出测试 ──


def test_reporter_pdf_output(sample_doe_data):
    """验证 PDF 报告正常生成。"""
    from smartsuite.services.reporter import to_pdf

    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温"],
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
        task="test",
        status="ok",
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
        task="response_surface",
        data=sample_doe_data,
        target_col="强度",
        feature_cols=["料温", "模温"],
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
        task="test",
        status="ok",
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
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温"],
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
        task="test",
        status="ok",
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
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温"],
    )
    result = orchestrate(req)
    # 清空图表
    result_no_figs = AnalysisResult(
        task=result.task,
        status=result.status,
        summary=result.summary,
        tables=result.tables,
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
        task="test",
        status="error",
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


# ── 分支补测（应用层 100% 覆盖专项）──


class _FakeRange:
    def __init__(self):
        self.value = None
        self.font = type("F", (), {"bold": False})()
        self.left = 0
        self.top = 0


class _FakePictures:
    def add(self, buf, left, top, width, height):
        return True


class _FakeSheet:
    def __init__(self):
        self.ranges: dict = {}
        self.pictures = _FakePictures()

    def range(self, addr):
        if addr not in self.ranges:
            self.ranges[addr] = _FakeRange()
        return self.ranges[addr]


class _FakeSheets:
    def __init__(self):
        self._sheets = [_FakeSheet()]

    def add(self, _name, after=None):
        s = _FakeSheet()
        self._sheets.append(s)
        return s

    def __getitem__(self, idx):
        return self._sheets[idx]


class _FakeWorkbook:
    def __init__(self):
        self.sheets = _FakeSheets()


def test_to_excel_writes_tables_and_figures(sample_doe_data):
    """to_excel（V1 遗留，xlwings 鸭子类型）：表格+图表全写入（reporter.py:33-69）。"""
    import warnings as _w

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    from smartsuite.services.reporter import to_excel

    fig = Figure(figsize=(4, 3))
    fig.add_subplot(111).plot([1, 2], [3, 4])
    result = AnalysisResult(
        task="correlation",
        status="ok",
        summary="测试",
        tables={"main_table": sample_doe_data.head(5)},
        figures=[fig],
    )
    wb = _FakeWorkbook()
    with _w.catch_warnings():
        _w.simplefilter("ignore", DeprecationWarning)
        name = to_excel(result, wb, "结果Sheet")
    assert name == "结果Sheet"
    assert wb.sheets._sheets[1].ranges["A1"].value == "分析结论", "结论写入新建 Sheet"
    assert len(wb.sheets._sheets) == 3, "原 Sheet + 结果 Sheet + 图表 Sheet"


def test_to_excel_failure_raises_output_error():
    """工作簿不可写 → OutputError 中文兜底（reporter.py:70-72）。"""
    import warnings as _w

    import pytest

    from smartsuite.core.exceptions import OutputError
    from smartsuite.services.reporter import to_excel

    class _BrokenSheets:
        @staticmethod
        def add(_name, after=None):
            raise OSError("不可写")

    class _BrokenWB:
        def __init__(self):
            self.sheets = _BrokenSheets()

    result = AnalysisResult(task="t", status="ok", summary="x", tables={}, figures=[])
    with _w.catch_warnings():
        _w.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(OutputError) as ei:
            to_excel(result, _BrokenWB())
    assert "Excel 输出失败" in str(ei.value)


def test_to_pdf_font_register_failure_falls_back_to_helvetica(sample_doe_data, monkeypatch):
    """CJK 字体注册失败 → 记警告并回退标准字体，PDF 仍生成（reporter.py:95-108）。

    用 TTFont 构造失败触发 101-103 的 except-continue 分支；
    不动 registerFont 本体，避免破坏 reportlab 标准字体内部注册。
    """
    from smartsuite.core.contracts import AnalysisRequest
    from smartsuite.services.orchestrator import orchestrate
    from smartsuite.services.reporter import to_pdf

    def _boom(*args, **kwargs):
        raise RuntimeError("字体损坏")

    monkeypatch.setattr("reportlab.pdfbase.ttfonts.TTFont", _boom)
    req = AnalysisRequest(
        task="correlation",
        data=sample_doe_data,
        target_col="不良率",
        feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        out = to_pdf(result, path)
        assert os.path.getsize(out) > 0
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def test_to_pdf_page_break_on_many_tables(sample_doe_data):
    """多行长表格把 y 压到阈值下 → 换页继续（reporter.py:121-123）。

    每表约占 208pt，5 表（上限 5）累计 >1000pt，中段必触发换页。
    """
    from smartsuite.core.contracts import AnalysisResult
    from smartsuite.services.reporter import to_pdf

    tables = {
        f"table_{i}": pd.DataFrame({"v": list(range(16)), "w": list(range(16))}) for i in range(5)
    }
    result = AnalysisResult(task="test", status="ok", summary="多表换页", tables=tables, figures=[])
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        out = to_pdf(result, path)
        assert os.path.getsize(out) > 0
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def test_to_pdf_failure_raises_output_error(tmp_path):
    """输出目录不可创建 → OutputError 中文兜底（reporter.py:152-154）。"""
    import pytest

    from smartsuite.core.exceptions import OutputError
    from smartsuite.services.reporter import to_pdf

    blocker = tmp_path / "blocked"
    blocker.write_text("file")
    result = AnalysisResult(task="t", status="ok", summary="x", tables={}, figures=[])
    with pytest.raises(OutputError) as ei:
        to_pdf(result, str(blocker / "sub" / "out.pdf"))
    assert "PDF 输出失败" in str(ei.value)


def test_to_ppt_failure_raises_output_error(tmp_path):
    """PPT 输出目录不可创建 → OutputError 中文兜底（reporter.py:190-192）。"""
    import pytest

    from smartsuite.core.exceptions import OutputError
    from smartsuite.services.reporter import to_ppt

    blocker = tmp_path / "blocked"
    blocker.write_text("file")
    result = AnalysisResult(task="t", status="ok", summary="x", tables={}, figures=[])
    with pytest.raises(OutputError) as ei:
        to_ppt(result, str(blocker / "sub" / "out.pptx"))
    assert "PPT 输出失败" in str(ei.value)


def test_to_html_truncation_note_over_50_rows():
    """>50 行表格 → 「仅显示前50行」提示（reporter.py:261-264）。"""
    from smartsuite.core.contracts import AnalysisResult
    from smartsuite.services.reporter import to_html

    result = AnalysisResult(
        task="test",
        status="ok",
        summary="长表",
        tables={"big": pd.DataFrame({"v": range(60)})},
        figures=[],
    )
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        to_html(result, path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "仅显示前50行" in content and "共60行" in content
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


# 注：reporter.py 的 PIL ImportError 回退分支（281-282）为环境防御代码，
# matplotlib 3.x 的 PNG 管线硬依赖 PIL，savefig 成功即证明 PIL 在场——
# 该分支在支持环境内不可达，已按标准做法标注 # pragma: no cover（附理由注释）。
