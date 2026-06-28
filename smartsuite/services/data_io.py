"""Data I/O — Excel 数据读写与校验。"""
import pandas as pd

from smartsuite.core.exceptions import ValidationError


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


def preprocess_data(df: pd.DataFrame, features: list[str],
                    categorical_cols: set[str] | None = None
                    ) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    """预处理数据：One-Hot 编码类别列、数值强制转换、中位数填充缺失值。

    Args:
        df: 原始 DataFrame
        features: 要使用的原始列名列表
        categorical_cols: 需做 One-Hot 编码的类别列名集合，为 None 则自动检测

    Returns:
        (encoded_df, encoded_cols, cat_map)
    """
    if categorical_cols is None:
        categorical_cols = {c for c in features if str(df[c].dtype) in ('object', 'string')}

    df = df.copy()
    encoded_cols: list[str] = []
    cat_map: dict[str, list[str]] = {}

    for col in features:
        if col in categorical_cols:
            dummies = pd.get_dummies(df[col].astype(str), prefix=col, drop_first=True)
            for dc in dummies.columns:
                df[dc] = dummies[dc].astype(float)
                encoded_cols.append(dc)
            cat_map[col] = list(dummies.columns)
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            if df[col].isnull().any():
                df[col] = df[col].fillna(df[col].median())
            encoded_cols.append(col)

    return df, encoded_cols, cat_map
