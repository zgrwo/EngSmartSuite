"""对话框交互 — 列选择和参数配置。"""
import xlwings as xw


def select_columns_dialog(sheet, title: str = "选择分析列") -> dict:
    """弹窗引导用户选择目标列和因子列。"""
    used_range = sheet.range("A1").expand()
    headers = used_range.rows[0].value or []
    header_str = ", ".join(str(h) for h in headers if h)

    target = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入目标列名 (Y):", title
    )
    if not target:
        return {}

    features_str = xw.apps.active.api.InputBox(
        f"可选列: {header_str}\n\n请输入因子列名 (X), 逗号分隔:", title
    )
    if not features_str:
        return {}

    return {"target": str(target).strip(),
            "features": [f.strip() for f in features_str.split(",")]}
