"""SmartSuite xlwings Add-in."""
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
    df, features_encoded, _ = preprocess_data(df, features)
    return AnalysisRequest(task=task, data=df, target_col=target,
                           feature_cols=features_encoded, params=params), warnings


def _run_and_report(task, output="excel", **params):
    try:
        wb = xw.Book.caller()
        if wb is None:
            xw.apps.active.api.MsgBox("无法获取工作簿，请确保从 Excel 中运行")
            return
        sheet = wb.sheets.active
        dlg = select_columns_dialog(sheet, title=f"配置: {task}")
        if not dlg:
            xw.apps.active.api.MsgBox("分析已取消")
            return
        req, warnings = _prepare_request(sheet, dlg["target"], dlg["features"], task, **params)
        result = orchestrate(req)

        # 合并 validate_data 的警告消息
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
                msg = f"PPT 报告已保存至: {path}\n\n{result.summary}"
                xw.apps.active.api.MsgBox(msg)
    except Exception:
        import traceback
        xw.apps.active.api.MsgBox(f"分析执行失败:\n{traceback.format_exc()}")


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
    xw.Book("smartsuite_addin.xlsm").set_mock_caller()
