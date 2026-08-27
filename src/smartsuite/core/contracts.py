from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class AnalysisRequest(BaseModel):
    """分析请求 — Excel 层与引擎层之间的唯一数据入口合约。

    Pydantic v2 自动验证：无效输入会产生明确错误消息。
    """

    model_config = {"arbitrary_types_allowed": True}

    task: str = Field(..., min_length=1, description="分析方法名称（必须在 TASK_REGISTRY 中注册）")
    data: pd.DataFrame = Field(
        ...,
        description="输入数据（不能为 None，允许空 DataFrame 以支持无数据方法如 power_analysis）",
    )
    target_col: str = Field(default="", description="目标列名")
    feature_cols: list[str] = Field(default_factory=list, description="特征列名列表")
    params: dict[str, Any] = Field(default_factory=dict, description="分析参数")

    @field_validator("task")
    @classmethod
    def task_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task 不能为空字符串")
        return v.strip()


@dataclass
class AnalysisResult:
    """分析结果 — 引擎层与 Reporter 层之间的唯一数据出口合约。"""

    task: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    figures: list[Figure] = field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    messages: list[str] = field(default_factory=list)
