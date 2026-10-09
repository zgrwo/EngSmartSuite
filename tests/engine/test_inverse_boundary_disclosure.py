"""反解任务（`inverse_solve`）的降级披露防线（B1/B2 契约）。

契约依据 `docs/governance/boundary-contract.md` 硬性要求 1：
**禁止任何只在 `logger.debug`/`logger.warning` 里说明的降级** —— 降级会改变
结果口径（剔了列、丢了行），用户必须能在 `messages` 里看到。

## 修复前实测（本文件建立时的现状）

`src/smartsuite/engine/inverse/_models.py` 共 5 处 `logger.warning` 降级：

| 位置 | 降级 | 修复前用户可见性 |
|---|---|---|
| `:210` | 常量特征列已剔除 | ✅ 已由 `solve.py` 拼等价文案进 `messages` |
| `:213` | auto 候选削减说明 | ✅ 同上（`forward.note`） |
| `:326` | 来料/输出配对回退 | ✅ 同上（`forward.pairing_note`） |
| `:339` | **速率模型丢弃 N 行无效时间** | ❌ **仅日志**（用户看到 n 变小却不知为何） |
| `:358` | **逐输出剔除 N 行缺失/非有限特征** | ❌ **仅日志**（同上） |

另实测：`metadata` 里**完全没有** `boundary_codes`（其余已收口模块都有），
上游无法机器分流「这次结果被降级处理过」。

## 本文件的两条判据

1. **正向**：每一处降级都有 `messages` 披露 + `metadata["boundary_codes"]` 错误码；
2. **反向**：干净数据必须**零码零噪音** —— 否则提示退化为噪音
   （`test_clean_data_has_no_degradation_notice`）。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.inverse.solve import inverse_parameter_solve

_N = 40


def _run(df: pd.DataFrame, params: dict):
    """生产 warnings 口径下跑一次反解（`filterwarnings=error` 只作用于 pytest）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        return inverse_parameter_solve(
            AnalysisRequest(
                task="inverse_solve",
                data=df,
                target_col="",
                feature_cols=[],
                params=params,
            )
        )


def _codes(result) -> list[str]:
    codes = result.metadata.get("boundary_codes")
    assert codes is not None, (
        "metadata 缺 `boundary_codes` —— 降级对上游不可见（其余收口模块均已暴露该键）："
        f"{sorted(result.metadata)}"
    )
    return list(codes)


def _clean_forward_frame(seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    inc = rng.normal(1.1, 0.05, _N)
    u1 = rng.uniform(4.0, 7.0, _N)
    u2 = rng.uniform(2.0, 4.0, _N)
    return pd.DataFrame(
        {
            "IncomingA": inc,
            "VariableU1": u1,
            "VariableU2": u2,
            "OutputY1": 1.3 - 0.06 * u2 + 0.05 * inc,
        }
    )


def _constant_feature_frame() -> pd.DataFrame:
    """`VariableU1` 整列恒为 5.0（常量），其余列正常。"""
    df = _clean_forward_frame()
    df["VariableU1"] = 5.0
    return df


def _rate_frame(*, invalid_time_rows: int = 0, nan_incoming_rows: int = 0) -> pd.DataFrame:
    """速率模型历史：`Y = 来料 − (a + b·U)·t`。

    `invalid_time_rows`：把前若干行时间置 0（可被 `_split_rows` 判为历史，
    但速率 `(来料−输出)/t` 在 t=0 时不可用 → 被 `_fit_rate_forward` 剔除）。
    `nan_incoming_rows`：把前若干行来料置 NaN（历史行仍成立 → 被逐输出的
    特征有限性掩码剔除）。
    """
    rng = np.random.default_rng(1)
    inc = rng.normal(1.1, 0.05, _N)
    u = rng.uniform(4.0, 8.0, _N)
    t = rng.uniform(45.0, 90.0, _N)
    rate = 0.002 + 0.0004 * u
    df = pd.DataFrame(
        {"IncomingZ1": inc, "VariableU1": u, "FixedTime": t, "OutputZ1": inc - rate * t}
    )
    if invalid_time_rows:
        df.loc[df.index[:invalid_time_rows], "FixedTime"] = 0.0
    if nan_incoming_rows:
        df.loc[df.index[:nan_incoming_rows], "IncomingZ1"] = np.nan
    return df


def _rate_params() -> dict:
    return {"model": "rate", "time_col": "FixedTime"}


class TestRateRowDropsAreDisclosed:
    """**修复前为红**：速率模型的两处行剔除此前只写日志（契约硬性要求 1）。"""

    def test_invalid_time_rows_are_disclosed_with_count(self):
        """时间列无效（缺失或 0）被剔除的行数必须让用户看到。

        实测：40 行历史中前 2 行时间为 0 → 速率拟合实际只用 38 行。
        修复前 `messages` 里没有任何一条提到这件事（只有 `logger.warning`），
        用户看到 `n_history=40` 却不知道速率模型是按 38 行拟合的。
        """
        result = _run(_rate_frame(invalid_time_rows=2), _rate_params())
        assert result.status == "ok", result.messages
        dropped_msgs = [m for m in result.messages if "剔除" in m and "时间" in m]
        assert dropped_msgs, (
            "速率模型剔除了时间无效的历史行却未向用户披露（只写日志 → 违反契约硬性要求 1）："
            f"messages={result.messages}"
        )
        detail = dropped_msgs[0]
        assert "2" in detail, f"披露必须含被剔除行数（实测 2 行）：{detail}"
        assert "38" in detail, f"披露应说明剔剩多少行（实测 40−2=38）：{detail}"
        assert "E_DATA_INVALID_TIME_DROPPED" in _codes(result), result.metadata

    def test_per_output_incomplete_rows_are_disclosed_with_output_name(self):
        """逐输出剔除「含缺失/非有限特征」的行时，必须点名输出与行数。

        实测：来料列前 3 行为 NaN → `finite_union` 掩码把该输出少用 3 行。
        """
        result = _run(_rate_frame(nan_incoming_rows=3), _rate_params())
        assert result.status == "ok", result.messages
        dropped_msgs = [m for m in result.messages if "剔除" in m and "OutputZ1" in m]
        assert dropped_msgs, (
            f"速率模型按输出剔除了含缺失特征的行却未披露：messages={result.messages}"
        )
        detail = dropped_msgs[0]
        assert "3" in detail, f"披露必须含被剔除行数（实测 3 行）：{detail}"
        assert "37" in detail, f"披露应说明剔剩多少行（实测 40−3=37）：{detail}"
        assert "E_DATA_INCOMPLETE_ROWS_DROPPED" in _codes(result), result.metadata


class TestForwardDegradationsCarryCodes:
    """`messages` 已有文案的三处降级，此前**没有错误码**（上游只能做子串匹配）。"""

    def test_constant_feature_drop_has_code_and_single_notice(self):
        """常量特征列剔除：文案已在（保持逐字不变），补码且不得重复说两遍。"""
        result = _run(_constant_feature_frame(), {"model": "linear", "random_state": 42})
        assert result.status == "ok", result.messages
        notices = [m for m in result.messages if "常量" in m and "VariableU1" in m]
        assert len(notices) == 1, f"同一降级只能说一次（实测 {len(notices)} 次）：{result.messages}"
        assert "未参与建模" in notices[0], notices[0]
        assert "E_DATA_CONSTANT_COLUMN" in _codes(result), result.metadata

    def test_pairing_fallback_has_code(self):
        """来料/输出配对回退（共用/顺序配对）会影响方程与反解口径，须带码。"""
        df = _rate_frame().rename(columns={"IncomingZ1": "IncomingA", "OutputZ1": "OutputY"})
        result = _run(df, _rate_params())
        assert result.status == "ok", result.messages
        assert any("配对" in m for m in result.messages), result.messages
        assert "E_DESIGN_PAIRING_FALLBACK" in _codes(result), result.metadata

    def test_auto_candidate_reduction_has_code(self, monkeypatch):
        """auto 因规模跳过候选（gpr/gbm/poly）会改变可比模型集合，须带码。"""
        from smartsuite.engine.inverse import _models

        assert _models.INVERSE_AUTO_CANDIDATE_MAX_ROWS == 500  # 默认预算锚点
        monkeypatch.setattr(_models, "INVERSE_AUTO_CANDIDATE_MAX_ROWS", 20)
        result = _run(_clean_forward_frame(), {"model": "auto", "random_state": 42})
        assert result.status == "ok", result.messages
        assert any("已跳过候选" in m for m in result.messages), result.messages
        assert "E_SCALE_AUTO_CANDIDATE_SKIPPED" in _codes(result), result.metadata


class TestNoDegradationNoNoise:
    """反向不变量（修复前后都必须绿）：干净数据零码零噪音。"""

    def test_clean_data_has_no_degradation_notice(self):
        result = _run(_clean_forward_frame(), {"model": "linear", "random_state": 42})
        assert result.status == "ok", result.messages
        assert _codes(result) == [], f"干净数据却给出降级码：{result.metadata}"
        noisy = [m for m in result.messages if "剔除" in m or "常量" in m or "跳过候选" in m]
        assert noisy == [], f"干净数据却给出降级提示（提示退化为噪音）：{noisy}"

    def test_clean_rate_model_has_no_row_drop_notice(self):
        result = _run(_rate_frame(), _rate_params())
        assert result.status == "ok", result.messages
        assert _codes(result) == [], f"干净速率历史却给出降级码：{result.metadata}"


@pytest.mark.parametrize("invalid_time_rows", [1, 5])
def test_disclosed_count_tracks_actual_rows(invalid_time_rows):
    """数量必须与真实剔除行数一致（防止文案里的数字变成装饰）。"""
    result = _run(_rate_frame(invalid_time_rows=invalid_time_rows), _rate_params())
    assert result.status == "ok", result.messages
    detail = next(m for m in result.messages if "剔除" in m and "时间" in m)
    assert str(invalid_time_rows) in detail, detail
    assert str(_N - invalid_time_rows) in detail, detail
