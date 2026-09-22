"""手册 CLAIM 比对判据（供 `verify_manual_claims.py` 调用，纯函数、可直测）。

审查 2026-09-21 G-2：原 `verify_manual_claims.py::rpt()` 在「引擎未产出值」
（`actual is None`）时一律记 `match="N/A"`，而失败判定是
`if match not in ("OK", "N/A"): fail_count += 1` —— 于是**手册侧有 CLAIM 值、
但引擎不再产出该值**的情形被静默放过，门禁照常 exit 0。

判据本身只有一行，但它决定门禁是否可信，故提炼为可导入、可直测的纯函数
（与 `manual_claims_freshness.py` 的可导入函数模式一致；原脚本是模块级
「导入即执行」，无法被单元测试引用）。
"""

from __future__ import annotations

from typing import Any

# ── VIF CLAIM 快照（审查 2026-09-21 E1-1）─────────────────────────────────────
# 取值逐因子对应 `docs/user-manual/04-root-cause.md` §4.5 的 `vif_table`（手册按
# 3 位小数展示）。必须为**数值**：rpt() 仅登记 `(int, float)` 的 manual 到
# CLAIM_LOG，字符串会使用例游离在「手册新鲜度」门禁之外。
# 旧实现是单条泛化字符串 "~1.002-1.004"（不登记）+ 硬编码窗口 [1.0, 1.005]
# （比手册精度宽 5 倍），见 tests/scripts/test_claims_gate.py 的反例量化。
VIF_MANUAL_CLAIMS: dict[str, float] = {
    "熔体温度": 1.004,
    "模具温度": 1.002,
    "注射压力": 1.003,
    "冷却时间": 1.004,
}

# 手册为 3 位小数，故容差取半个末位（0.0005）稍微放宽到 0.001
VIF_CLAIM_TOLERANCE = 0.001


def classify_missing(manual: Any) -> tuple[str, str]:
    """引擎未产出值（`actual is None`）时的 `(展示文本, 判定)`。

    - 手册侧**无值**（`manual is None`）→ `("N/A", "N/A")`：合法，不计失败
      （该项目确实没为这条 CLAIM 誊写快照）。
    - 手册侧**有值** → `("N/A", "MISSING")`：引擎漏值，**必须计失败**。
      展示仍是 `N/A` 是因为引擎确实没给出值，与判定名分开表达。

    注意用 `is None` 而非 falsy 判断：`0` / `0.0` / `""` 都是合法 CLAIM 值
    （如 `p=0.0`），误判为「无值」会让门禁重新失明。
    """
    if manual is None:
        return "N/A", "N/A"
    return "N/A", "MISSING"
