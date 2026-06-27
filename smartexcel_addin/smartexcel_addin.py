"""SmartExcel Suite xlwings Add-in."""
import os
import xlwings as xw
from smartexcel.core.contracts import AnalysisRequest
from smartexcel.services.data_io import read_excel_range, validate_data
from smartexcel.services.orchestrator import orchestrate
from smartexcel.services.reporter import to_excel, to_ppt


def _prepare_request(sheet, target, features, task, **params):
    df = read_excel_range(sheet)
    validate_data(df, target, features)
    return AnalysisRequest(task=task, data=df, target_col=target,
                           feature_cols=features, params=params)


def _run_and_report(task, output="excel", **params):
    wb = xw.Book.caller()
    sheet = wb.sheets.active
    dlg = select_columns_dialog(sheet, title=f"配置: {task}")
    if not dlg:
        return
    req = _prepare_request(sheet, dlg["target"], dlg["features"], task, **params)
    result = orchestrate(req)

    if output == "excel":
        to_excel(result, wb, sheet_name=f"{task}_结果")
    elif output == "ppt":
        path = os.path.join(os.path.expanduser("~"), "Desktop", f"{task}_report.pptx")
        to_ppt(result, path)
        xw.apps.active.api.MsgBox(f"PPT 报告已保存至: {path}")

    if result.status == "error":
        xw.apps.active.api.MsgBox("; ".join(result.messages))
    else:
        xw.apps.active.api.MsgBox(result.summary)


def select_columns_dialog(sheet, title="选择分析列"):
    """弹窗引导用户选择目标列和因子列。"""
    used_range = sheet.range("A1").expand()
    headers = used_range.rows[0].value or []
    header_str = ", ".join(str(h) for h in headers if h)
    target = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入目标列名 (Y):", title)
    if not target:
        return {}
    features_str = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入因子列名 (X), 逗号分隔:", title)
    if not features_str:
        return {}
    return {"target": str(target).strip(),
            "features": [f.strip() for f in features_str.split(",")]}


# ---- Ribbon button callbacks (called via VBA RunPython) ----

def run_correlation():
    _run_and_report("correlation")

def run_anova():
    _run_and_report("anova")

def run_hypothesis_test():
    _run_and_report("hypothesis_test")

def run_regression():
    _run_and_report("regression")

def run_response_surface():
    _run_and_report("response_surface")

def run_grid_search():
    _run_and_report("grid_search")

def run_spc():
    _run_and_report("spc_xbar")

def run_process_capability():
    _run_and_report("process_capability")

def run_report_excel():
    xw.Book.caller()
    xw.apps.active.api.MsgBox("请先运行一项分析（如相关性分析），结果会自动输出到新工作表。")

def run_report_ppt():
    xw.Book.caller()
    xw.apps.active.api.MsgBox("请先运行一项分析（如响应面分析），结果会保存到桌面。")


if __name__ == "__main__":
    xw.Book("smartexcel_addin.xlsm").set_mock_caller()
