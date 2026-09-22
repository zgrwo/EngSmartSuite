"""detection 子包内部共享助手（审查 2026-09-21 A-1）。

本包只再导出**公开 API**（见 `__init__.py` 的约定），私有助手留在定义它们的模块里。
但 IQR 判据被 `anomaly_detect` 与 `outlier_consensus` **共用同一政策**
（`Q1 − k·IQR` / `Q3 + k·IQR`，且 `IQR == 0` 时拒绝），两处各写一份会让判据与
常量来源漂移——故把这一处集中到本模块。

Z-score 判据同样在两处重复（同一 `ddof=1` 与同一阈值常量），但两边的**下游用途不同**
（`outlier_consensus` 需把 Z 值写进结果表，`anomaly_detect` 只用掩码），
强行合并会为了统一而改造调用方，故保留就地实现并在两处加交叉引用注释。
"""

from __future__ import annotations

import pandas as pd


def iqr_outlier_mask(data: pd.Series, multiplier: float) -> tuple[pd.Series, float, float] | None:
    """IQR 异常掩码：返回 `(掩码, 下界, 上界)`；`IQR == 0`（常量列）时返回 `None`。

    调用方约定：`None` 表示「数据无变化，IQR 判据无法适用」，由各任务给出自己的
    中文错误（错误文案含任务名，故不在此处生成 `AnalysisResult`）。

    边界与掩码**一次算出后共用**：`anomaly_detect` 还需把上下界画到图上，
    若在调用方另行重算 quantile，就会出现「图上的界」与「判异常用的界」两套来源。
    """
    q1, q3 = data.quantile(0.25), data.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return (data < lower) | (data > upper), float(lower), float(upper)
