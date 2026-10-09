"""`process_capability` 的量级上界守卫与出口保洁（审查 2026-10-09 R2BD-01，P0）。

缺陷形态（生产口径实测，`warnings.simplefilter("default")`）：

| 数据量级 S | status | 结果表内容 | summary |
| :--- | :--- | :--- | :--- |
| 1 | ok | Cp=1.304 Cpk=1.304 Ppk=1.281，整体σ=0.9805 | 正常 |
| 1e-9 | ok | 指标正确（无量纲） | 正常（显示层见 R2BD-06） |
| 1e150 / 1e153 | **ok** | `descriptive_stats` 的均值打印成 104 位整数 `.0000` | 指标正确 |
| **1e154** | **ok** | **整体σ = `inf`；Ppk=Pp=Cpm = `0.000`** | **「判定: 勉强」—— 伪造的指标 + 明确结论** |
| **1e160** | **RAISED(OverflowError)** | — | 未捕获异常逃出引擎 |

根因：`sigma_overall > 0` 对 `inf` 为真 → 走"正常"分支算出 `Ppk=0.000`；
`(mu - target) ** 2` 在 Python float 域触发 `OverflowError`（numpy 的
`inf`+RuntimeWarning 路径**不会**出现，故任何 `np.errstate`/告警过滤器都拦不住）。

⚠️ **本文件的断言必须在生产口径下跑**：`pyproject.toml` 的
`filterwarnings = ["error"]` **只作用于 pytest**，pytest 口径下
`RuntimeWarning: overflow encountered in square` 会在产出错误结论**之前**
把执行打断 —— 于是"不得给出错误结论"的断言恒真（空过 / 假绿，
见该轮报告 §三 的 4/48 口径分歧实测）。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine.capability import process_capability_analysis


def _capability_request(scale: float) -> AnalysisRequest:
    """同一构造数据仅乘 `scale`：规格限与目标值同比缩放，无量纲指标应保持不变。"""
    rng = np.random.default_rng(2026)
    y = (10.0 + rng.standard_normal(60)) * scale
    return AnalysisRequest(
        task="process_capability",
        data=pd.DataFrame({"y": y}),
        target_col="y",
        feature_cols=[],
        params={"usl": 14.0 * scale, "lsl": 6.0 * scale, "target": 10.0 * scale},
    )


def _run(scale: float, policy: str):
    """按指定 warnings 口径运行**引擎入口**（不经 orchestrator 的兜底捕获）。

    `policy="default"` = 生产口径（Web/CLI 用户所见）；`policy="error"` = pytest 口径。
    直接调引擎而非 `orchestrate`，是为了让"未捕获异常逃出引擎"这一红线**可断言** ——
    orchestrator 的 `except Exception` 兜底会把 `OverflowError` 翻译成泛化文案，
    从而掩盖引擎自身的违约。
    """
    with warnings.catch_warnings():
        warnings.simplefilter(policy)
        return process_capability_analysis(_capability_request(scale))


@pytest.mark.parametrize("scale", [1e153, 1e154, 1e160])
def test_extreme_magnitude_is_rejected_not_answered(scale):
    """×1e153 及以上必须 B0 拒绝并点名量级，不得给出结论、不得抛异常。

    生产口径下的判据是"引擎返回了 `AnalysisResult`"——`OverflowError` 逃出
    引擎本身即红线违约（R2BD-01 的第二形态）。
    """
    result = _run(scale, "default")
    assert result.status == "error", (
        f"×{scale:g} 下引擎仍给出结论（sigma=inf / Ppk=0 是伪造值）："
        f"summary={result.summary!r}, messages={result.messages}"
    )
    blob = " ".join(result.messages)
    assert "量级" in blob, f"拒绝理由必须指向量级（否则用户排查不到真因）：{result.messages}"
    assert "单位换算" in blob or "中心化" in blob, f"B0 拒绝须给可执行建议：{result.messages}"
    assert "E_SCALE_EXTREME_MAGNITUDE" in result.metadata.get("boundary_codes", []), (
        f"机器可读错误码缺失：{result.metadata.get('boundary_codes')}"
    )


def test_verdict_is_identical_under_both_warning_policies():
    """两种 warnings 口径下结论必须一致（本轮头号假绿通道的封堵范式）。

    pytest 口径会把 numpy 的溢出 `RuntimeWarning` 升为异常，使执行在**产出错误
    结论之前**中断；若只按 pytest 口径断言"不得给出错误结论"，用例会空过。
    这里对两个口径各跑一遍并断言同一结论 —— 照抄
    `tests/guards/test_boundary_contract.py::TestInfNotBlamedAsConstant` 的范式。
    """
    for scale in (1e153, 1e160):
        prod = _run(scale, "default")
        pyt = _run(scale, "error")
        assert prod.status == pyt.status == "error", (
            f"×{scale:g} 两种口径结论不一致：生产={prod.status}、pytest={pyt.status}"
        )
        assert "量级" in " ".join(pyt.messages), (
            f"pytest 口径下应由引擎自身拒绝（而非被 warnings-as-errors 打断）：{pyt.messages}"
        )


def test_normal_and_micro_scale_still_answer():
    """量级守卫不得误伤常规/微尺度数据（前置对照，防"加守卫把正常路径也拒了"）。"""
    macro, micro = _run(1.0, "default"), _run(1e-9, "default")
    assert macro.status == "ok" and micro.status == "ok", (macro.messages, micro.messages)
    # 无量纲能力指数与量纲无关：两处必须逐位一致
    for key in ("cp", "cpk", "pp", "ppk", "cpm"):
        assert float(micro.metadata[key]) == pytest.approx(float(macro.metadata[key]), rel=1e-9), (
            f"{key} 随量纲变化"
        )


def test_indices_are_finite_at_safe_magnitude():
    """安全量级下能力指数必须有限（出口保洁的正面用例，与 B0 拒绝互补）。"""
    result = _run(1.0, "default")
    assert result.status == "ok", result.messages
    for key in ("cp", "cpk", "pp", "ppk", "cpm", "sigma_overall", "sigma_within", "mean"):
        assert np.isfinite(float(result.metadata[key])), f"{key} 非有限：{result.metadata[key]}"
    # 结果表内不得渗出 ±Inf（`check_tables_finite` 的判据；字符串单元格另计）
    for name, frame in result.tables.items():
        blob = " ".join(str(v) for v in frame.to_numpy().ravel())
        assert "inf" not in blob.lower().replace("infinite", ""), f"表「{name}」渗出 inf：{blob}"


def _run_boxcox(scale: float, policy: str = "default"):
    """Box-Cox 路径：入口量级守卫看的是**原始**数据，变换后的量级另算。"""
    rng = np.random.default_rng(7)
    y = np.abs((10.0 + rng.standard_normal(60)) * scale)
    req = AnalysisRequest(
        task="process_capability",
        data=pd.DataFrame({"y": y}),
        target_col="y",
        feature_cols=[],
        params={
            "usl": 14.0 * scale,
            "lsl": 6.0 * scale,
            "target": 10.0 * scale,
            "transform": "boxcox",
        },
    )
    with warnings.catch_warnings():
        warnings.simplefilter(policy)
        return process_capability_analysis(req)


@pytest.mark.parametrize("scale", [1e145, 1e148])
def test_boxcox_transformed_overflow_never_fakes_indices(scale):
    """Box-Cox 把量级推过溢出线时，不得伪造 `Ppk=0.000` + `status=ok`。

    R2BD-01 的同一机制有一条入口守卫**拦不到**的残留路径：MLE 功率变换
    `(x^λ−1)/λ` 在 λ>1 时把量级放大若干数量级，`Σ(x−μ)²` 随即溢出。
    实测（修复前，生产口径）：`status=ok`、`sigma_overall=inf` 入表、
    `Ppk=Pp=Cpm=0.000`、`judge` 仍宣称「判定: 勉强」—— 与 ×1e153 的形态逐字相同。

    两种合规处置（与 `test_normality_check_does_not_fake_normal_at_overflow_scale`
    同范式）：**要么** B0 拒绝并点名量级，**要么**出结果但不得伪造 0 值。
    """
    result = _run_boxcox(scale)
    if result.status == "error":
        assert "量级" in " ".join(result.messages), (
            f"拒绝理由必须指向量级（否则用户排查不到真因）：{result.messages}"
        )
    else:
        for key in ("pp", "ppk", "cpm"):
            value = result.metadata[key]
            assert value is None or np.isfinite(float(value)), (
                f"×{scale:g} 下 {key}={value}（σ 溢出时的伪造值）"
            )
        blob = " ".join(
            str(v) for frame in result.tables.values() for v in frame.to_numpy().ravel()
        )
        assert "inf" not in blob, f"×{scale:g} 下结果表渗出 inf：{blob}"


def test_boxcox_at_safe_magnitude_still_answers():
    """变换后量级守卫不得误伤合法 Box-Cox（防"加守卫把正常路径也拒了"）。"""
    result = _run_boxcox(1e100)
    assert result.status == "ok", result.messages
    assert result.metadata["boxcox_lambda"] is not None
    assert np.isfinite(float(result.metadata["sigma_overall"]))
    assert np.isfinite(float(result.metadata["ppk"]))
