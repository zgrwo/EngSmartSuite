"""参考值装载器 —— 把"引擎之外的裁判"做成可提交、可空跑的数据契约。

## 为什么保留这一层（即使当前不使用任何第三方工具）

`docs/governance/improvement-plan.md` 阶段 P3 指出本项目最大的验证差距是
**验证是内向闭环**：引擎算出的数进手册、手册的数被脚本回对引擎，闭环里没有外人。

`tests/golden/test_spc_msa_golden.py` 用**教科书公式的独立实现**补了一部分，
能抓"公式转写错、常数错位、口径误用"。**另一层它抓不到**：
当"教材理解本身有偏差"时（如 X-bar 不等子组的加权方式、Gage R&R 嵌套设计、
ANOVA 不平衡设计的 SS 选择），只有**第三方工具的实际行为**能作为规范。

本模块把这个缺口做成**可提交、可空跑的数据契约**：

  - **有值时**：自动逐值对账，成为 PR 门禁的一部分；
  - **无值时**：对应用例 skip（不假装已验证），并由
    `test_reference_loader.py` 的缺口登记表**持续披露哪些方法没有外部锚定**；
  - **将来补值时**：无需改动任何测试代码 —— 只往 JSON 里填数。

## 独立性分级（写在 provenance.independence 里）

| 级别 | 含义 | 能抓到什么 |
|:---|:---|:---|
| `external-tool` | 第三方工具的实际输出（任意统计软件的权威实现） | **最强**：连"教材理解偏差"一起抓 |
| `independent-implementation` | 本项目之外的独立实现（scipy/statsmodels 第二路径、手写公式） | 公式转写错、常数错位、口径误用 |
| `hand-transcribed` | 手工录入的公开常数表（如 ASTM/Montgomery 附录） | 常数表错位 |
| `none` | 未锚定 | — |

> ⚠️ **独立性必须在生成时如实标注**。第三轮复核的 P1-4 教训：
> `crossval` 曾写满 `R 参考: qcc(...)` 却无任何对应数值 —— 把
> `independent-implementation` 冒充成 `external-tool` 是**虚假标注**，
> 比不标注更有害。

> ⚠️ **当前状态（2026-09-24 决定）**：本项目**不使用任何第三方统计工具做验证**。
> 故 `external-tool` 级别目前为空，`provenance.independence` 为 `none`。
> 本装载器的价值在于**把未锚定状态记录在案**，而不是假装已锚定。

## 使用方式

    from tests.golden._loader import get_value, requires_reference

    @requires_reference("process_capability", "injection_process", "cpk")
    def test_cpk_matches_external():
        expected = get_value("process_capability", "injection_process", "cpk")
        assert orchestrate(...).metadata["cpk"] == pytest.approx(expected, rel=1e-6)
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REFERENCE_PATH = Path(__file__).resolve().parent / "reference.json"

_INDEPENDENCE_LEVELS = (
    "external-tool",
    "independent-implementation",
    "hand-transcribed",
    "none",
)


@dataclass(frozen=True)
class Reference:
    """参考值表及其出处。"""

    provenance: dict[str, Any]
    values: dict[str, dict[str, dict[str, Any]]]

    @property
    def independence(self) -> str:
        return str(self.provenance.get("independence") or "none")

    def is_anchored(self, task: str) -> bool:
        """该任务是否已有至少一个非空参考值。"""
        return any(
            v is not None for case in self.values.get(task, {}).values() for v in case.values()
        )

    def anchored_tasks(self) -> set[str]:
        return {t for t in self.values if self.is_anchored(t)}


@functools.lru_cache(maxsize=1)
def load_reference() -> Reference:
    """装载并校验 `reference.json`。缺文件/格式非法 → 明确报错（不静默空跑）。"""
    if not REFERENCE_PATH.exists():  # pragma: no cover — 文件随仓库分发
        raise FileNotFoundError(
            f"缺少参考值表 {REFERENCE_PATH}。"
            "若为有意移除，请同步删除 tests/golden/ 下依赖它的用例。"
        )
    raw = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    provenance = raw.get("provenance") or {}
    values = raw.get("values") or {}
    if not isinstance(provenance, dict) or not isinstance(values, dict):
        raise ValueError(f"{REFERENCE_PATH.name} 结构非法：provenance/values 必须是对象")
    level = provenance.get("independence") or "none"
    if level not in _INDEPENDENCE_LEVELS:
        raise ValueError(
            f"{REFERENCE_PATH.name} 的 provenance.independence={level!r} 非法，"
            f"可选：{list(_INDEPENDENCE_LEVELS)}"
        )
    return Reference(provenance=provenance, values=values)


def get_value(task: str, case: str, metric: str) -> Any:
    """取参考值；缺失返回 None（调用方一般已在 requires_reference 后调用）。"""
    return load_reference().values.get(task, {}).get(case, {}).get(metric)


def _has_value(task: str, case: str, metric: str) -> bool:
    return get_value(task, case, metric) is not None


def requires_reference(*keys: str):
    """装饰器：参考值缺失时 skip，并在 skip 原因里说明需要什么。

    用法：`@requires_reference("gage_rr", "nested_10x3x2", "ev")`

    设计取舍：**skip 而非 xfail**。xfail 会在"参考值补齐后仍然失败"时被忽略，
    而 skip 的语义明确是"前提未满足"；配合
    `test_reference_loader.py` 的缺口披露，不会造成"假装已验证"。
    """
    if len(keys) != 3:
        raise ValueError("requires_reference 需要恰好 3 个参数：task, case, metric")
    task, case, metric = keys

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _has_value(task, case, metric):
                pytest.skip(
                    f"参考值缺失：{task}/{case}/{metric} —— "
                    "需先按 tests/golden/reference.json 的 _schema 填入外部参考值"
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco
