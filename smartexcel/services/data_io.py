"""Data I/O — Excel 数据读写与校验。"""
import pandas as pd

from smartexcel.core.exceptions import ValidationError


def read_excel_range(sheet, range_addr: str | None = None) -> pd.DataFrame:
    """从 Excel 选区读取 DataFrame。"""
    if range_addr:
        data_range = sheet.range(range_addr)
    else:
        data_range = sheet.range("A1").expand()
    df = data_range.options(pd.DataFrame, header=True).value
    if df is None or df.empty:
        raise ValidationError("所选区域无有效数据")
    return df


def validate_data(df: pd.DataFrame, target_col: str,
                  feature_cols: list[str]) -> list[str]:
    """校验数据列存在性、类型、缺失值。返回警告消息列表。"""
    messages = []
    missing = [c for c in [target_col] + feature_cols if c not in df.columns]
    if missing:
        raise ValidationError(f"以下列不存在于数据中: {missing}")

    for col in feature_cols + [target_col]:
        if df[col].dtype == 'object':
            try:
                pd.to_numeric(df[col])
            except (ValueError, TypeError):
                messages.append(f"列「{col}」包含非数值数据")

    null_count = df[[target_col] + feature_cols].isnull().sum().sum()
    if null_count > 0:
        messages.append(f"检测到 {null_count} 个缺失值，分析中将自动排除")

    return messages
