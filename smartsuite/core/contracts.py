from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from matplotlib.figure import Figure


@dataclass
class AnalysisRequest:
    """分析请求 — Excel 层与引擎层之间的唯一数据入口合约。"""

    task: str
    data: pd.DataFrame
    target_col: str
    feature_cols: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


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
