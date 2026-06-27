"""xlwings 加载项入口 — 注册 Ribbon 按钮回调。"""
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
    from smartexcel.excel.dialogs import select_columns_dialog
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
    xw.apps.active.api.MsgBox("请先运行一项分析，结果将自动输出到新 Sheet。")

def run_report_ppt():
    xw.apps.active.api.MsgBox("请先运行一项分析（如响应面），选择 PPT 输出。")


if __name__ == "__main__":
    xw.serve()
