"""xlwings 加载项入口 — 注册 Ribbon 按钮回调。"""
import os

import xlwings as xw

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.data_io import read_excel_range, validate_data
from smartsuite.services.orchestrator import orchestrate
from smartsuite.services.reporter import to_excel, to_ppt


def _prepare_request(sheet, target, features, task, **params):
    df = read_excel_range(sheet)
    warnings = validate_data(df, target, features)
    from smartsuite.services.data_io import preprocess_data
    df, features_encoded, _, _ = preprocess_data(df, features)
    return AnalysisRequest(task=task, data=df, target_col=target,
                           feature_cols=features_encoded, params=params), warnings


def _run_and_report(task, output="excel", **params):
    try:
        wb = xw.Book.caller()
        if wb is None:
            xw.apps.active.api.MsgBox("无法获取工作簿，请确保从 Excel 中运行")
            return
        sheet = wb.sheets.active
        from smartsuite.excel.dialogs import select_columns_dialog
        dlg = select_columns_dialog(sheet, title=f"配置: {task}")
        if not dlg:
            xw.apps.active.api.MsgBox("分析已取消")
            return
        req, warnings = _prepare_request(sheet, dlg["target"], dlg["features"], task, **params)
        result = orchestrate(req)
        if warnings:
            result.messages = warnings + result.messages

        if output == "excel":
            to_excel(result, wb, sheet_name=f"{task}_结果")
            if result.status == "error":
                xw.apps.active.api.MsgBox("; ".join(result.messages))
            else:
                msg = result.summary
                if result.messages:
                    msg += "\n\n" + "\n".join(result.messages)
                xw.apps.active.api.MsgBox(msg)
        elif output == "ppt":
            path = os.path.join(os.path.expanduser("~"), "Desktop", f"{task}_report.pptx")
            to_ppt(result, path)
            if result.status == "error":
                xw.apps.active.api.MsgBox("; ".join(result.messages))
            else:
                xw.apps.active.api.MsgBox(f"PPT 报告已保存至: {path}\n\n{result.summary}")
    except Exception:
        import traceback
        xw.apps.active.api.MsgBox(f"分析执行失败:\n{traceback.format_exc()}")


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
