"""scripts/claims_gate.py 判据自测（审查 2026-09-21 G-2）。

背景：`verify_manual_claims.py` 的 `rpt()` 在「引擎未产出值」（`actual is None`）时
一律记 `match="N/A"`，而失败判定为 `if match not in ("OK", "N/A")` —— 于是
**手册侧有 CLAIM 值、但引擎不再产出该值**的情形被静默放过，门禁照常 exit 0。

判据提炼为纯函数后可直测（原脚本是「导入即执行」的模块级脚本，不可导入测试）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from claims_gate import classify_missing  # noqa: E402


def test_manual_side_has_value_but_engine_missing_is_failure():
    """手册侧有值 + 引擎未产出 → 必须计失败（MISSING 不属于 OK/N/A）。"""
    disp, match = classify_missing(manual=12.6)
    assert match == "MISSING", f"应判定为 MISSING，实际 {match!r}"
    assert match not in ("OK", "N/A"), "MISSING 必须触发 fail_count 递增"
    assert disp == "N/A", f"展示仍为 N/A（引擎确实没给值），实际 {disp!r}"


def test_manual_side_also_missing_is_legitimate_na():
    """手册侧本就无值 → 合法 N/A，不计失败。"""
    disp, match = classify_missing(manual=None)
    assert (disp, match) == ("N/A", "N/A")


def test_zero_manual_value_is_not_treated_as_missing():
    """falsy 陷阱守卫：手册侧值为 0（合法 CLAIM，如 p=0.0）不得误判为「无值」。"""
    disp, match = classify_missing(manual=0.0)
    assert match == "MISSING", "0.0 是合法手册值 → 引擎未产出时应计失败"


def test_empty_string_manual_value_counts_as_present():
    """空串手册值同样「有值」（用 is None 判据，不用 falsy）。"""
    _, match = classify_missing(manual="")
    assert match == "MISSING"


# ── E1-1（2026-09-21 审查）：VIF CLAIM 的可门禁性 ──────────────────────────────
# 原实现用**单条泛化字符串** CLAIM "~1.002-1.004" + 硬编码判定窗口 [1.0, 1.005]：
#   ① 字符串不满足 rpt() 的 `isinstance(manual, (int, float))` → 不进 CLAIM_LOG
#      → 手册新鲜度门禁（快照↔手册）对这 4 条完全失明；
#   ② 窗口宽 0.005，比手册声明的 3 位小数精度宽 5 倍——引擎漂移到 [1.0, 1.005]
#      内任意值都判 OK（例：模具温度 1.0016 → 1.0045 旧检查通过、新检查拒绝）。
def test_vif_manual_claims_are_numeric():
    """4 条 VIF CLAIM 必须为数值类型（否则不进 CLAIM_LOG，新鲜度门禁失明）。"""
    from claims_gate import VIF_MANUAL_CLAIMS

    assert len(VIF_MANUAL_CLAIMS) == 4, f"应有 4 个因子，实际 {list(VIF_MANUAL_CLAIMS)}"
    for name, val in VIF_MANUAL_CLAIMS.items():
        assert isinstance(val, (int, float)), f"{name} 的 CLAIM 必须为数值，实际 {type(val)}"
        assert not isinstance(val, bool)


def test_vif_manual_claims_match_user_manual_table():
    """快照值必须与 user-manual 4.5 节 VIF 表的逐因子值一致（手册↔快照链）。"""
    from claims_gate import VIF_MANUAL_CLAIMS

    manual_path = Path(__file__).resolve().parents[2] / "docs" / "user-manual" / "04-root-cause.md"
    text = manual_path.read_text(encoding="utf-8")
    start = text.index("### 4.5 VIF")
    end = text.index("#### 解读说明", start)
    section = text[start:end]

    for name, val in VIF_MANUAL_CLAIMS.items():
        rows = [ln for ln in section.splitlines() if ln.startswith(f"| {name} |")]
        assert rows, f"手册 4.5 节应含「{name}」行"
        assert f"{val:.3f}" in rows[0], f"手册「{name}」行应为 {val:.3f}，实际: {rows[0]!r}"


def test_vif_claim_tolerance_is_tighter_than_old_hardcoded_window():
    """容差必须显著严于旧硬编码窗口 [1.0, 1.005]（否则等于没修）。

    反例量化：模具温度引擎实测 1.0016、手册 1.002；若漂移到 1.0045：
      旧判定 1.0 <= 1.0045 <= 1.005 → OK（漏放）
      新判定 |1.0045 - 1.002| = 0.0025 > 0.001 → DIFF（拦住）
    """
    from claims_gate import VIF_CLAIM_TOLERANCE, VIF_MANUAL_CLAIMS

    assert 0 < VIF_CLAIM_TOLERANCE <= 0.001, f"容差应 ≤ 0.001（旧窗口 0.005），实际 {VIF_CLAIM_TOLERANCE}"
    old_lo, old_hi = 1.0, 1.005
    drifted = 1.0045
    manual = VIF_MANUAL_CLAIMS["模具温度"]
    assert old_lo <= drifted <= old_hi, "反例应落在旧窗口内（证明旧检查会漏放）"
    assert abs(drifted - manual) > VIF_CLAIM_TOLERANCE, "反例应被新容差拒绝"
