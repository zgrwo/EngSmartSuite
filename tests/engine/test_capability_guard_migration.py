"""`capability.py` 迁移到 `_guard` 的行为锁定（第三十五轮）。

契约：[boundary-contract.md](../../docs/governance/boundary-contract.md) ——
      「边界处理：逐函数手抄 → **一处声明、一处执行**」；
      [improvement-plan.md](../../docs/governance/improvement-plan.md) 硬指标表
      如实标注本项为 ⏳ 未达标（执行点已建，但全引擎仅 `spc_xbar.py` 一处接入）。

## 本轮做什么

把 `capability.py` 的边界处理从**手抄**改为走 `_guard`：

| 迁移前 | 迁移后 |
|:---|:---|
| `data, n_inf = drop_non_finite(data)` + 手写 `non_finite_note(...)` | `clean_series(data, report=...)` |
| `warn_msgs: list[str] = []` + 多处 `warn_msgs.append(...)` | `BoundaryReport` + `report.add(BoundaryIssue(...))` |
| `messages=warn_msgs` | `messages=report.messages()` |

收益不只是"少写几行"：迁移后 `BoundaryIssue.code` 会在**一个地方**产出，
使"给每个处置配机器可读错误码"成为可能（手抄形态下每处都不带码）。

## 为什么先写**行为锁定**测试

迁移是**重构**，正确性的判据是"可观测行为一字不变"：

- 正常数据 → 不出现任何披露（**不得凭空加提示**，否则提示变噪音）；
- 含 ±Inf → 出现恰好一条披露，且**含剔除数量**；
- 常量列 → 仍是明确拒绝（B0），不是"剔除后继续"；
- 样本量不足 → 仍是明确拒绝；
- 警告的**条数与内容**与迁移前一致（含子组口径提示、Box-Cox 提示等）。

这些断言在迁移**前后都必须通过** —— 若迁移后有哪条变了，说明重构引入了行为改变。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate

_SPEC = {"usl": 56.0, "lsl": 44.0}


def _run(df: pd.DataFrame, params: dict | None = None, target: str = "y"):
    return orchestrate(
        AnalysisRequest(
            task="process_capability",
            data=df,
            target_col=target,
            feature_cols=[],
            params={**_SPEC, **(params or {})},
        )
    )


def _normal(n: int = 30, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"y": 50.0 + rng.normal(0, 1.5, n)})


class TestCleanDataGetsNoWarning:
    """干净数据**不得**出现任何披露 —— 否则提示退化为噪音，用户会学会忽略它。"""

    def test_clean_data_has_no_non_finite_message(self):
        r = _run(_normal())
        assert r.status == "ok", r.messages
        assert not [m for m in r.messages if "非有限值" in m], r.messages

    def test_clean_data_still_emits_the_moving_range_caveat(self):
        """⚠️ **"无披露"只针对清洗类提示**：子组口径提示与数据是否含 Inf 无关，
        故干净数据上**仍然应该有** —— 本用例把这两类提示区分开，
        防止迁移时把"清洗的披露"与"口径的披露"一起改掉。"""
        r = _run(_normal())
        assert r.status == "ok", r.messages
        assert any("移动极差" in m for m in r.messages), (
            f"未给子组信息时应有移动极差口径提示：{r.messages}"
        )


class TestNonFiniteDisclosureIsUnchanged:
    """含 ±Inf 时的披露：条数与内容在迁移前后应一致。"""

    def test_inf_removal_is_disclosed_once_with_count(self):
        df = _normal()
        df.loc[df.index[:4], "y"] = np.inf
        r = _run(df)
        assert r.status == "ok", r.messages
        hits = [m for m in r.messages if "非有限值" in m]
        assert len(hits) == 1, f"应恰好一条披露，实际 {hits}"
        assert "4" in hits[0], f"披露应含剔除数量 4：{hits[0]}"
        assert "y" in hits[0], f"披露应含列名：{hits[0]}"

    def test_negative_inf_is_also_disclosed(self):
        df = _normal()
        df.loc[df.index[:2], "y"] = -np.inf
        r = _run(df)
        assert r.status == "ok", r.messages
        assert any("非有限值" in m and "2" in m for m in r.messages), r.messages

    def test_nan_does_not_produce_non_finite_message(self):
        """NaN 走 `dropna`（缺失语义），**不算**非有限值 —— 不应产生该提示。

        这条划清了两个概念：`NaN` = 缺失（本来就会被丢），`±Inf` = 非有限值（需披露）。
        """
        df = _normal()
        df.loc[df.index[:3], "y"] = np.nan
        r = _run(df)
        assert r.status == "ok", r.messages
        assert not [m for m in r.messages if "非有限值" in m], r.messages


class TestRejectionsAreUnchanged:
    """B0 拒绝路径不变 —— 迁移不得把"拒绝"变成"剔除后继续"。"""

    def test_constant_column_is_still_rejected(self):
        df = pd.DataFrame({"y": [50.0] * 20})
        r = _run(df)
        assert r.status == "error", f"常量列应拒绝：{r.status} / {r.messages}"
        assert any("常量" in m for m in r.messages), r.messages

    def test_constant_column_message_does_not_blame_non_finite(self):
        """常量列拒绝文案**不得**提到非有限值（那是错误归因的反面）。"""
        df = pd.DataFrame({"y": [50.0] * 20})
        r = _run(df)
        assert not any("非有限值" in m for m in r.messages), r.messages

    def test_insufficient_sample_is_still_rejected(self):
        r = _run(pd.DataFrame({"y": [50.0, 51.0]}))
        assert r.status == "error"
        assert any("不足" in m for m in r.messages), r.messages

    @pytest.mark.parametrize("n", [3, 4])
    def test_tiny_but_valid_sample_still_runs(self, n):
        """边界另一侧：`n = 3/4` 应能跑（拒绝条件是 `< 3`）。"""
        rng = np.random.default_rng(3)
        r = _run(pd.DataFrame({"y": 50.0 + rng.normal(0, 1.0, n)}))
        assert r.status == "ok", r.messages


class TestWarningSetIsUnchanged:
    """警告的**集合**在迁移前后一致（不增不减）。"""

    def test_subgroup_caveat_appears_when_subgroups_absent(self):
        r = _run(_normal())
        assert any("移动极差" in m for m in r.messages), r.messages

    def test_subgroup_caveat_absent_when_subgroup_col_given(self):
        """给了 `subgroup_col` → 不再需要移动极差口径提示。"""
        rng = np.random.default_rng(11)
        df = pd.DataFrame(
            {
                "y": 50.0 + rng.normal(0, 1.0, 60),
                "g": np.repeat([f"B{i}" for i in range(20)], 3),
            }
        )
        r = orchestrate(
            AnalysisRequest(
                task="process_capability",
                data=df,
                target_col="y",
                feature_cols=["g"],
                params={**_SPEC, "subgroup_col": "g"},
            )
        )
        assert r.status == "ok", r.messages
        assert not [m for m in r.messages if "移动极差" in m], r.messages

    def test_boxcox_message_appears_only_when_transform_requested(self):
        r_plain = _run(_normal())
        assert not [m for m in r_plain.messages if "Box-Cox" in m], r_plain.messages
        r_box = _run(_normal(), {"transform": "boxcox"})
        assert r_box.status == "ok", r_box.messages
        # 请求了变换 → 要么成功（有 λ）要么失败（有提示），但不该静默
        has_lambda = r_box.metadata.get("boxcox_lambda") is not None
        has_msg = any("Box-Cox" in m for m in r_box.messages)
        assert has_lambda or has_msg, f"请求了 Box-Cox 却既无 λ 也无提示：{r_box.messages}"


class TestGuardIsActuallyUsed:
    """**本轮的目标断言**：`capability.py` 确实走 `_guard`（而非手抄）。

    这条在迁移**前会失败** —— 它就是本轮的驱动断言。
    """

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[2] / "src" / "smartsuite" / "engine" / "capability.py"
        ).read_text(encoding="utf-8")

    def test_capability_imports_guard(self):
        src = self._source()
        assert "from smartsuite.engine._guard import" in src, (
            "capability.py 应走 _guard（边界处理一处声明、一处执行）"
        )

    def test_capability_no_longer_hand_rolls_cleaning(self):
        """迁移后**不得**再直接调 `_utils` 的无披露清洗函数。"""
        src = self._source()
        assert "drop_non_finite(" not in src, (
            "capability.py 仍在使用 drop_non_finite（应改为 _guard.clean_series）"
        )
        assert "non_finite_note(" not in src, (
            "capability.py 仍在手写披露文案（应改为 report.add(BoundaryIssue(...))）"
        )

    def test_capability_uses_boundary_report(self):
        src = self._source()
        assert "BoundaryReport" in src, "应使用 BoundaryReport 收集处置记录"
        assert "report.messages()" in src, "用户可见提示应由 report.messages() 产出"


class TestBoundaryCodesAreExposed:
    """迁移的**收益兑现**：错误码现在是机器可读的（迁移前只有中文文案）。"""

    def test_clean_data_has_no_cleaning_code(self):
        """干净数据**不产生清洗码**。

        ⚠️ 我首版断言"干净数据没有任何码" —— **实测证伪**：无子组时引擎用移动极差法，
        那是一个**真实的口径假设**（隐含"数据行序 = 采样时间顺序"），
        故它本身就有一条 B3 记录 `E_CAPABILITY_SUBGROUP_SIGMA_CAVEAT`。
        本用例据此改为只断言"没有清洗类码"，并顺带把"无子组必有口径码"钉住。
        """
        r = _run(_normal())
        assert r.status == "ok", r.messages
        codes = r.metadata["boundary_codes"]
        assert "E_DATA_NON_FINITE_DROPPED" not in codes, codes
        assert codes == ["E_CAPABILITY_SUBGROUP_SIGMA_CAVEAT"], (
            f"无子组时应恰好有口径提示码，实际 {codes}"
        )

    def test_non_finite_removal_yields_the_documented_code(self):
        df = _normal()
        df.loc[df.index[:4], "y"] = np.inf
        r = _run(df)
        assert r.status == "ok", r.messages
        assert "E_DATA_NON_FINITE_DROPPED" in r.metadata["boundary_codes"], r.metadata[
            "boundary_codes"
        ]

    def test_codes_are_deduplicated(self):
        """同一种处置发生多次也只出现一个码（`report.codes()` 去重）。"""
        df = _normal()
        df.loc[df.index[:2], "y"] = np.inf
        df.loc[df.index[2:4], "y"] = -np.inf
        r = _run(df)
        codes = r.metadata["boundary_codes"]
        assert codes.count("E_DATA_NON_FINITE_DROPPED") == 1, codes

    def test_boundary_codes_are_machine_readable(self):
        """码必须是 `E_<域>_<原因>` 形态的 ASCII 串（可被日志/监控直接消费）。

        这条也防止将来有人把中文文案塞进 `code` —— 那会让码失去"稳定标识"的作用。
        """
        import re

        df = _normal()
        df.loc[df.index[:4], "y"] = np.inf
        r = _run(df)
        for code in r.metadata["boundary_codes"]:
            assert re.fullmatch(r"E_[A-Z0-9_]+", code), f"码格式不合约定: {code!r}"

    def test_normality_caveat_is_coded_not_just_texted(self):
        """数据不满足正态假设时的提示**带码**（而不只是一句中文）。"""
        rng = np.random.default_rng(29)
        # 强偏态数据 → 触发正态性提示
        df = pd.DataFrame({"y": np.concatenate([rng.exponential(1.0, 25), [12.0]])})
        r = _run(df)
        assert r.status == "ok", r.messages
        assert any(c == "E_CAPABILITY_DATA_NOT_NORMAL" for c in r.metadata["boundary_codes"]) or (
            not [m for m in r.messages if "正态" in m]
        ), f"若有正态性提示则必须有码：{r.messages} / {r.metadata['boundary_codes']}"
