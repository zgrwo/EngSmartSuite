"""参数解析：请求行 JSON 载荷、枚举/数值默认值与 float 防护（原 inverse.py，2026-09-21 拆分）。"""

import json

import numpy as np
import pandas as pd

from smartsuite.engine._utils import safe_float


def _coerce_request_value(value):
    """请求行取值归一：数值字符串转 float，空字符串转 None。"""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return value
    return value


def _parse_request_rows(value, limit: int | None = None) -> tuple[list[dict], int]:
    """解析界面/API 录入的请求行（对象列表或其 JSON 字符串）。

    空值返回 ``([], 0)``；非列表或含非对象行时抛中文 ValueError（入口转为
    status=error）。数值字符串统一转 float，避免追加后与历史数据 dtype 冲突。
    ``limit`` 非空且超出时在**追加物化前**截断，返回 (rows, 截断条数)。
    """
    if value is None:
        return [], 0
    if isinstance(value, str):
        if not value.strip():
            return [], 0
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("参数「request_rows」不是有效的 JSON 字符串") from None
    if not isinstance(value, list):
        raise ValueError('参数「request_rows」必须是对象列表（每行形如 {"列名": 数值}）')
    truncated = 0
    if limit is not None and len(value) > limit:
        truncated = len(value) - limit
        value = value[:limit]
    rows: list[dict] = []
    for i, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"参数「request_rows」第 {i} 行不是对象：{row!r}")
        for key, raw in row.items():
            if isinstance(raw, bool):
                raise ValueError(
                    f"参数「request_rows」第 {i} 行的「{key}」为布尔值（{raw!r}），"
                    "请改用 0/1 数值（审查 2026-09-13 C-3）"
                )
        rows.append({str(k): _coerce_request_value(v) for k, v in row.items()})
    return rows, truncated


def _append_request_rows(
    df: pd.DataFrame,
    rows: list[dict],
    messages: list[str],
    variable_cols=(),
) -> pd.DataFrame:
    """把录入的请求行追加到数据末尾（可调参数留空 → 引擎按请求行分类）。

    未知列名忽略并把警告写入 messages；``variable_cols`` 中的可调参数取值
    不参与请求行（由反解计算），显式剔除并提示，避免静默并入训练历史。
    原数据行顺序与索引语义保持不变。
    """
    variable_cols = {str(c) for c in variable_cols}
    unknown = sorted({key for row in rows for key in row if key not in df.columns})
    if unknown:
        messages.append(f"request_rows 中以下列不存在于数据中，已忽略：{unknown}")
    dropped_variable = sorted({key for row in rows for key in row if key in variable_cols})
    if dropped_variable:
        messages.append(
            f"request_rows 中以下可调参数取值已忽略（请求行由反解计算）：{dropped_variable}"
        )
    cleaned = [{k: v for k, v in row.items() if k not in variable_cols} for row in rows]
    appended = pd.DataFrame(cleaned, columns=list(df.columns))
    messages.append(f"已追加 {len(cleaned)} 条界面录入的请求行（可调参数留空，按请求行处理）")
    return pd.concat([df, appended], ignore_index=True)


_LOW_CV_R2 = 0.3  # spec §5：选中模型 CV R² 低于该值提示"可解释性弱"（n>2000 为 5 折）


_LOW_CV_R2 = 0.3  # spec §5：选中模型 CV R² 低于该值提示"可解释性弱"（n>2000 为 5 折）
_INVERSE_MODELS = ("auto", "linear", "poly", "gpr", "gbm", "rate")


_INVERSE_MODELS = ("auto", "linear", "poly", "gpr", "gbm", "rate")
_WEIGHT_MODES = ("std", "range", "none")


_WEIGHT_MODES = ("std", "range", "none")
_DEFAULT_ATTAIN_TOL = 0.5  # spec §3 attain_tol 默认值


_DEFAULT_ATTAIN_TOL = 0.5  # spec §3 attain_tol 默认值
_DEFAULT_MAX_STARTS = 10  # spec §3 max_starts 默认值


_DEFAULT_MAX_STARTS = 10  # spec §3 max_starts 默认值
_DEFAULT_RANDOM_STATE = 42  # spec §3 random_state 默认值


def _str_param(params, key, default) -> str:
    """取字符串参数（N-7）：None/空白回退默认值，其余（含数值 0）按字面转换。"""
    raw = params.get(key)
    if raw is None:
        return default
    text = str(raw).strip()
    return text if text else default


def _parse_float_param(params, key, default, messages) -> float:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return float(default)
    value = safe_float(raw, float("nan"))
    if not np.isfinite(value):
        messages.append(f"参数「{key}」取值无效（{raw!r}），已回退默认值 {default!r}")
        return float(default)
    return float(value)


def _parse_optional_float(params, key, messages) -> float | None:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value = safe_float(raw, float("nan"))
    if not np.isfinite(value):
        messages.append(f"参数「{key}」取值无效（{raw!r}），已忽略并使用历史范围")
        return None
    return float(value)


def _parse_json_param(params, key, messages, fallback_note) -> dict:
    raw = params.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    messages.append(f"参数「{key}」不是有效的 JSON 对象（{raw!r}），{fallback_note}")
    return {}
