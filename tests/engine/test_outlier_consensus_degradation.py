"""`outlier_consensus` 的 IsolationForest 降级必须**用户可见**（审查 2026-10-09 R2BD-04，P1）。

缺陷形态（生产口径，语义注入：令 `IsolationForest.fit_predict` 抛错）：

```
### A. 正常情况
  status = ok   messages = []   boundary_codes = []
      IQR  Z-Score  IsoForest  投票数   置信度
      是   是       是         3       高 (≥2票)
      否   否       是         1       低 (1票)     ← 仅靠 IsoForest 一票入选

### B. 强制 IsolationForest 抛错
  status = ok   messages = []   boundary_codes = []
      是   是       否         2       高 (≥2票)     ← 上述那一行**整行消失**
```

两处违约同时成立：

1. **禁止静默降级**（`boundary-contract.md` 硬性要求 1）：降级只写 `logger.debug`，
   `messages` 与正常情况**逐字相同**（信息没有到达用户可见处）；
2. **不可分辨**：结果表的 `IsoForest` 列照常渲染为「否」—— 与"IsoForest 跑了且
   认为都不是异常"**字面完全一致**；投票制（≥2 票 = 高置信）的语义随成员数
   3→2 变化，属 B2 降级却无任何标注。

本文件用 `monkeypatch` 触发降级（**不改源码**，只在运行时替换方法），
按报告 §四.4 的语义注入法构造。
"""

import logging

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.detection.outlier import outlier_consensus


def _frame() -> pd.DataFrame:
    """100 个常规观测 + 3 个强离群点（IQR/Z/IsoForest 三法均能投票）。"""
    rng = np.random.default_rng(4)
    values = np.concatenate([rng.normal(10.0, 1.0, 100), [40.0, -20.0, 38.0]])
    return pd.DataFrame({"y": values})


def _run():
    return outlier_consensus(
        AnalysisRequest(
            task="outlier_consensus", data=_frame(), target_col="y", feature_cols=[], params={}
        )
    )


def _degrade(monkeypatch, exc: Exception) -> None:
    """语义注入：让 IsolationForest 的 `fit_predict` 抛错（模拟 sklearn 版本/数值失败）。

    引擎在函数体内 `from sklearn.ensemble import IsolationForest`，故打补丁到
    `sklearn.ensemble` 上的类方法即可命中该 import 出来的同一个类对象。
    """
    import sklearn.ensemble

    def _boom(self, X, y=None):  # noqa: N803 - 签名须与 sklearn 一致
        raise exc

    monkeypatch.setattr(sklearn.ensemble.IsolationForest, "fit_predict", _boom)


def test_normal_run_votes_with_three_methods():
    """前置对照：正常情况下三种方法都参与投票。"""
    result = _run()
    assert result.status == "ok", result.messages
    assert list(result.metadata["voting_methods"]) == ["IQR", "Z-Score", "Isolation Forest"]
    assert "Isolation Forest" in " ".join(result.messages) or not [
        m for m in result.messages if "不可用" in m
    ], f"正常路径不应出现降级提示：{result.messages}"


@pytest.mark.parametrize("exc", [RuntimeError("模拟 sklearn 数值失败"), ValueError("模拟输入非法")])
def test_isolation_forest_failure_is_disclosed(monkeypatch, exc):
    """降级必须出现在 `messages` 与 `boundary_codes` 里，并说明投票数变化。"""
    _degrade(monkeypatch, exc)
    result = _run()
    assert result.status == "ok", result.messages
    blob = " ".join(result.messages)
    assert "IsolationForest" in blob, f"降级未在 messages 中披露：{result.messages}"
    assert "2 种方法" in blob and "IQR" in blob and "Z-Score" in blob, (
        f"披露必须说明**哪两个方法**仍在参与投票：{result.messages}"
    )
    assert "E_NUMERIC_METHOD_UNAVAILABLE" in result.metadata["boundary_codes"], (
        f"缺少机器可读错误码：{result.metadata.get('boundary_codes')}"
    )
    assert list(result.metadata["voting_methods"]) == ["IQR", "Z-Score"], (
        f"metadata 应如实回报实际参与投票的方法：{result.metadata.get('voting_methods')}"
    )


def test_degraded_run_is_distinguishable_from_normal_run(monkeypatch):
    """可分辨性：正常与降级两次运行的 `messages` 必须不同（报告判据 C）。"""
    normal = _run()
    _degrade(monkeypatch, RuntimeError("模拟失败"))
    degraded = _run()
    assert normal.messages != degraded.messages, (
        "降级后 messages 与正常情况逐字相同 → 用户无法分辨「未运行」与「未发现」"
    )
    assert len(degraded.messages) > len(normal.messages)


def test_degradation_is_logged_at_warning_level(monkeypatch, caplog):
    """可观测性：`logger.debug` 只能被开发者看见，降级必须记 WARNING 及以上。"""
    _degrade(monkeypatch, RuntimeError("模拟失败"))
    with caplog.at_level(logging.WARNING, logger="smartsuite.engine.detection.outlier"):
        _run()
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        f"降级只写到了 debug 级：{[r.levelname for r in caplog.records]}"
    )
    assert any("IsolationForest" in r.getMessage() for r in caplog.records)


def test_result_table_marks_the_skipped_method(monkeypatch):
    """结果表必须把"未参与"与"参与了但认为不是异常"区分开（原二者同为「否」）。"""
    normal = _run()
    assert "未参与" not in normal.tables["anomalies"].to_string()

    _degrade(monkeypatch, RuntimeError("模拟失败"))
    degraded = _run()
    table = degraded.tables["anomalies"]
    if len(table):
        assert set(table["IsoForest"]) == {"未参与"}, (
            f"IsoForest 未参与投票，却在表里显示为「否」（与'跑了没发现'同形）："
            f"{table.to_dict('records')}"
        )
    counts = degraded.tables["method_counts"].set_index("方法")
    iso_rows = [idx for idx in counts.index if "Isolation Forest" in str(idx)]
    assert iso_rows, f"method_counts 缺少 Isolation Forest 行：{list(counts.index)}"
    assert "未参与" in str(iso_rows[0]), (
        f"method_counts 未标注该方法本轮未参与投票：{iso_rows[0]!r}"
    )


def test_summary_discloses_the_degradation(monkeypatch):
    """摘要（用户最先读到的通道）也必须带上降级标注。"""
    _degrade(monkeypatch, RuntimeError("模拟失败"))
    result = _run()
    assert "未参与" in result.summary or "不可用" in result.summary, (
        f"summary 未披露降级，用户会以为做了三方法投票：{result.summary}"
    )
