"""Audit 服务层单元测试。

覆盖范围：
- export_workbook 基本导出（多 Sheet Excel 工作簿）
- export_workbook 自定义 tasks 列表
- auto_report 一键报告（HTML 输出）
- export_workbook 空数据/失败任务优雅降级
"""
import os
import tempfile

import openpyxl
import pandas as pd

from smartsuite.services.audit import auto_report, export_workbook


# ── export_workbook 测试 ──


def test_export_workbook_basic(sample_doe_data):
    """验证 export_workbook 正常生成多 Sheet Excel 工作簿。"""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        out = export_workbook(
            sample_doe_data,
            target_col="不良率",
            feature_cols=["料温", "模温"],
            output_path=path,
            tasks=["correlation", "distribution_summary"],
        )
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

        # 验证工作簿结构
        wb = openpyxl.load_workbook(out)
        # 每个成功 task 应有一个 _summary sheet
        assert len(wb.sheetnames) >= 2  # 至少 2 个 task
        # 验证表头颜色格式正确（aRGB 无 # 前缀 — F-01 修复验证）
        for ws in wb.worksheets:
            # 检查至少有一个带填充的单元格
            fills_found = False
            for row in ws.iter_rows():
                for cell in row:
                    if cell.fill and cell.fill.fgColor and cell.fill.fgColor.rgb:
                        rgb = cell.fill.fgColor.rgb
                        assert not rgb.startswith("#"), (
                            f"openpyxl 颜色不应包含 # 前缀: {rgb}"
                        )
                        assert len(rgb) == 8, (
                            f"aRGB 应为 8 位 hex: {rgb}"
                        )
                        fills_found = True
                        break
                if fills_found:
                    break
        wb.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_export_workbook_custom_tasks(sample_doe_data):
    """验证 export_workbook 自定义 tasks 列表。"""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        out = export_workbook(
            sample_doe_data,
            target_col="强度",
            feature_cols=["料温", "模温", "注射压力"],
            output_path=path,
            tasks=["anova"],
        )
        assert os.path.exists(out)
        wb = openpyxl.load_workbook(out)
        sheet_names_lower = [s.lower() for s in wb.sheetnames]
        assert any("anova" in s for s in sheet_names_lower), (
            f"应包含 anova sheet: {wb.sheetnames}"
        )
        wb.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_export_workbook_subdir_creation():
    """验证 export_workbook 自动创建不存在的输出目录。"""
    df = pd.DataFrame({"y": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})
    tmpdir = tempfile.mkdtemp()
    subdir = os.path.join(tmpdir, "nested", "subdir")
    out_path = os.path.join(subdir, "output.xlsx")
    try:
        out = export_workbook(
            df, target_col="y", feature_cols=[],
            output_path=out_path,
            tasks=["distribution_summary"],
        )
        assert os.path.exists(out)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
        # 清理嵌套目录
        for d in [subdir, os.path.join(tmpdir, "nested"), tmpdir]:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)


def test_export_workbook_all_tasks_fail():
    """验证所有 task 失败时不崩溃，生成仅含错误信息的 Sheet。"""
    df = pd.DataFrame({"y": [1, 1, 1, 1, 1]})  # 常量数据，许多分析会失败
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        out = export_workbook(
            df, target_col="y", feature_cols=[],
            output_path=path,
            tasks=["regression", "anova"],  # 缺少 feature_cols，这些 task 会失败
        )
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        # 验证至少创建了一个 sheet（降级行为）
        wb = openpyxl.load_workbook(out)
        assert len(wb.sheetnames) >= 1, "应至少有一个 Sheet（错误信息或降级）"
        wb.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── auto_report 测试 ──


def test_auto_report_smoke(sample_doe_data):
    """验证 auto_report 正常生成 HTML 报告。"""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        result = auto_report(
            sample_doe_data,
            target_col="不良率",
            feature_cols=["料温", "模温"],
            output_path=path,
            title="测试自动报告",
        )
        assert result["output_path"] == path
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        # 验证 HTML 内容
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        assert "<html" in html.lower() or "<!doctype" in html.lower(), (
            "输出应为有效 HTML"
        )
        assert "测试自动报告" in html or "SmartSuite" in html, (
            "HTML 应包含报告标题或项目名"
        )
        # 验证返回结构
        assert "data_quality" in result
        assert "batch_results" in result
        assert "audit" in result
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_auto_report_auto_path(sample_doe_data):
    """验证 auto_report 不指定 output_path 时自动生成路径。"""
    import os as _os
    cwd = _os.getcwd()
    default_path = _os.path.join(cwd, "smartsuite_report.html")
    try:
        result = auto_report(
            sample_doe_data,
            target_col="强度",
            feature_cols=["料温", "模温"],
        )
        assert os.path.exists(result["output_path"])
        assert os.path.getsize(result["output_path"]) > 0
    finally:
        if os.path.exists(default_path):
            os.unlink(default_path)


def test_auto_report_with_spec_limits(sample_doe_data):
    """验证 auto_report 含规格限参数时正常生成（含过程能力分析）。"""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        result = auto_report(
            sample_doe_data,
            target_col="强度",
            feature_cols=["料温", "模温"],
            output_path=path,
            usl=55,
            lsl=35,
        )
        assert os.path.exists(path)
        assert "output_path" in result
    finally:
        if os.path.exists(path):
            os.unlink(path)
