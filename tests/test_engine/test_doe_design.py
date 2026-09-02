"""DOE 实验设计模块测试 — 4 层防线：数值正确性 + 数学不变量 + 边界 + 差分。"""

import numpy as np
import pandas as pd
import pytest

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.engine import _doe_arrays as da
from smartsuite.engine.doe_opt import (
    _gen_box_behnken,
    _gen_ccd,
    _gen_fractional,
    _gen_full_factorial,
    _gen_plackett_burman,
    _gen_taguchi,
    _resolve_alpha,
    doe_design,
)


def _assert_orthogonal(m):
    """断言任意两列相关系数 ≈ 0（正交性不变量，容差 1e-6）。"""
    for i in range(m.shape[1]):
        for j in range(i + 1, m.shape[1]):
            assert abs(np.corrcoef(m[:, i], m[:, j])[0, 1]) < 1e-6, f"列 {i},{j} 不正交"


def _distinct_rows(m):
    """去重后的行数（重复行会破坏设计的唯一性，正交性测试无法覆盖）。"""
    return len({tuple(r) for r in m.tolist()})


# ── Task 1: GF(2) 二水平正交表 ──
def test_two_level_oa_l8_shape_and_orthogonal():
    m = da.two_level_oa(8)
    assert m.shape == (8, 7)
    assert (m.sum(axis=0) == 4).all()
    _assert_orthogonal(m)


def test_two_level_oa_l4():
    m = da.two_level_oa(4)
    assert m.shape == (4, 3)
    assert (m.sum(axis=0) == 2).all()


# ── Task 2: GF(3) 三水平正交表 ──
def test_three_level_oa_l9():
    m = da.three_level_oa(9)
    assert m.shape == (9, 4)
    for c in range(4):
        for lvl in (0, 1, 2):
            assert (m[:, c] == lvl).sum() == 3
    _assert_orthogonal(m)


def test_three_level_oa_l27():
    m = da.three_level_oa(27)
    assert m.shape == (27, 13)


# ── Task 3: L18 硬编码正交性 ──
def test_l18_shape_and_orthogonal():
    assert da.L18.shape == (18, 8)
    _assert_orthogonal(da.L18)


def test_l18_level_balance():
    assert (da.L18[:, 0] == 0).sum() == 9
    for c in range(1, 8):
        for lvl in (0, 1, 2):
            assert (da.L18[:, c] == lvl).sum() == 6


# ── Task 4: 全因子 ──
def test_full_factorial_cartesian():
    factors = [
        {"name": "A", "levels": ["低", "高"]},
        {"name": "B", "levels": [180, 200, 220]},
    ]
    m = _gen_full_factorial(factors)
    assert m.shape == (6, 2)
    assert len({tuple(r) for r in m.tolist()}) == 6


# ── Task 5: 部分因子 + Plackett-Burman ──
def test_fractional_2_3():
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(3)]
    m, err = _gen_fractional(factors, 4)
    assert err == []
    assert m.shape == (4, 3)
    _assert_orthogonal(m)


def test_plackett_burman_12():
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(8)]
    m, err = _gen_plackett_burman(factors, 12)
    assert err == []
    assert m.shape == (12, 8)
    _assert_orthogonal(m)


def test_plackett_burman_20():
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(15)]
    m, err = _gen_plackett_burman(factors, 20)
    assert err == []
    assert m.shape == (20, 15)
    _assert_orthogonal(m)


def test_plackett_burman_24():
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(20)]
    m, err = _gen_plackett_burman(factors, 24)
    assert err == []
    assert m.shape == (24, 20)
    _assert_orthogonal(m)


def test_plackett_burman_28_rejected():
    # 28 非标准 PB 规模（27=3^3 无循环差集），应返回错误而非产生不正交设计
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(10)]
    m, err = _gen_plackett_burman(factors, 28)
    assert m is None
    assert any("仅支持运行数" in e for e in err)


def test_fractional_full_factorial_no_duplicate_runs():
    """默认全因子（n_runs=2^k）不应产生重复运行行（审查发现：取前 k 列导致重复）。"""
    for k in (2, 3, 4, 5):
        factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(k)]
        m, err = _gen_fractional(factors, 2**k)
        assert err == []
        assert _distinct_rows(m) == 2**k, f"k={k} 全因子出现重复行"


def test_ccd_factorial_points_no_duplicate():
    """k≥5 半因子 CCD 的阶乘点不应有重复（审查发现：取前 k 列导致 16→8）。"""
    for k in (5, 6):
        m = _gen_ccd(k, 2.0, 0)
        nf = 2 ** (k - 1)
        fact = m[:nf]
        assert _distinct_rows(fact) == nf, f"k={k} 阶乘点出现重复"


# ── Task 6: taguchi 匹配器 ──
def test_taguchi_mixed_6x3_2x2_hits_l36():
    factors = [{"name": f"A{i}", "levels": [0, 1, 2]} for i in range(6)] + [
        {"name": f"B{i}", "levels": [0, 1]} for i in range(2)
    ]
    m, name, spec = _gen_taguchi(factors)
    assert name == "L36"
    assert m.shape == (36, 8)
    _assert_orthogonal(m)


def test_taguchi_3level_hits_l9():
    factors = [{"name": f"A{i}", "levels": [0, 1, 2]} for i in range(3)]
    m, name, spec = _gen_taguchi(factors)
    assert name == "L9"
    assert m.shape == (9, 3)


def test_taguchi_mixed_1x2_5x3_hits_l18():
    factors = [{"name": "B0", "levels": [0, 1]}] + [
        {"name": f"A{i}", "levels": [0, 1, 2]} for i in range(5)
    ]
    m, name, spec = _gen_taguchi(factors)
    assert name == "L18"
    assert m.shape == (18, 6)
    _assert_orthogonal(m)


# ── Task 7: Box-Behnken + CCD ──
def test_box_behnken_k3_point_count():
    m = _gen_box_behnken(3)
    assert m.shape == (12, 3)


def test_ccd_k2_face_point_count():
    m = _gen_ccd(2, 1.0, 3)
    assert m.shape == (11, 2)


# ── Task 8: doe_design 端到端 ──
def _req(method, factors, **kw):
    return AnalysisRequest(
        task="doe_design",
        data=pd.DataFrame(),
        params={"method": method, "factors": factors, **kw},
    )


def test_doe_design_taguchi_l36_end_to_end():
    factors = [{"name": f"A{i}", "levels": [10, 20, 30]} for i in range(6)] + [
        {"name": f"B{i}", "levels": ["低", "高"]} for i in range(2)
    ]
    r = doe_design(_req("taguchi", factors, randomize=False))
    assert r.status == "ok"
    dm = r.tables["design_matrix"]
    # 1 个「运行顺序」列 + 8 个因子列
    assert len(dm) == 36
    assert list(dm.columns) == ["运行顺序", "A0", "A1", "A2", "A3", "A4", "A5", "B0", "B1"]
    assert r.metadata["oa_name"] == "L36"
    # 水平映射正确：三水平因子取 {10,20,30}，二水平取 {"低","高"}
    assert set(dm["A0"].unique()) == {10, 20, 30}
    assert set(dm["B0"].unique()) == {"低", "高"}


def test_doe_design_invalid_method():
    r = doe_design(_req("nope", [{"name": "A", "levels": [1, 2]}]))
    assert r.status == "error"
    assert any("method" in m for m in r.messages)


def test_doe_design_missing_factors():
    r = doe_design(_req("full_factorial", None))
    assert r.status == "error"


def test_doe_design_replicates_and_randomize():
    factors = [{"name": "A", "levels": [1, 2]}, {"name": "B", "levels": [1, 2]}]
    r = doe_design(_req("full_factorial", factors, replicates=2, randomize=True, seed=1))
    dm = r.tables["design_matrix"]
    assert len(dm) == 8  # 4 * 2
    assert "重复" in dm.columns and "运行顺序" in dm.columns


def test_doe_design_deterministic_with_seed():
    factors = [{"name": "A", "levels": [1, 2]}, {"name": "B", "levels": [1, 2]}]
    r1 = doe_design(_req("full_factorial", factors, randomize=True, seed=7))
    r2 = doe_design(_req("full_factorial", factors, randomize=True, seed=7))
    assert r1.tables["design_matrix"].equals(r2.tables["design_matrix"])


def test_doe_design_ccd_rotatable_alpha():
    factors = [{"name": f"X{i}", "levels": [-1, 0, 1]} for i in range(3)]
    r = doe_design(_req("ccd", factors, alpha="rotatable", center_points=3, randomize=False))
    assert r.status == "ok"
    # 2^3 阶乘(8) + 2*3 轴向(6) + 3 中心 = 17
    assert len(r.tables["design_matrix"]) == 17


def test_doe_design_box_behnken():
    factors = [{"name": f"X{i}", "levels": [100, 150, 200]} for i in range(3)]
    r = doe_design(_req("box_behnken", factors, center_points=2, randomize=False))
    assert r.status == "ok"
    # 12 边中点 + 2 中心 = 14
    assert len(r.tables["design_matrix"]) == 14


def test_doe_design_full_factorial_over_limit():
    factors = [{"name": f"X{i}", "levels": list(range(6))} for i in range(6)]
    r = doe_design(_req("full_factorial", factors))
    assert r.status == "error"  # 6^6 = 46656 > 10000


def test_doe_design_fractional_non_two_level():
    factors = [{"name": "A", "levels": [1, 2, 3]}]
    r = doe_design(_req("fractional_factorial", factors))
    assert r.status == "error"


# ── CCD α 正确性（审查发现的两个严重 bug 回归测试）──
def test_doe_design_fractional_invalid_runs():
    """审查 2026-08-29 #R8：fractional_factorial 非 2 的幂 n_runs 分支（doe_opt.py:1990）此前缺测。"""
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(3)]
    r = doe_design(_req("fractional_factorial", factors, n_runs=12))  # 12 不是 2 的幂
    assert r.status == "error"
    assert any("2 的幂" in m for m in r.messages), r.messages


def test_doe_design_plackett_burman_invalid_runs_entry():
    """审查 2026-08-29 #R8：doe_design 入口传非法 PB n_runs 应返回中文错误而非裸异常。"""
    factors = [{"name": f"X{i}", "levels": [0, 1]} for i in range(3)]
    r = doe_design(_req("plackett_burman", factors, n_runs=28))
    assert r.status == "error"
    assert any("仅支持运行数" in m for m in r.messages), r.messages


def test_resolve_alpha_rotatable_full_and_half_fraction():
    # 全因子 k≤4：α = nf^(1/4) = 2^(k/4)
    assert _resolve_alpha("rotatable", 2, 3) == pytest.approx(2**0.5)
    assert _resolve_alpha("rotatable", 4, 3) == pytest.approx(2.0)
    # 半因子 k≥5：α = nf^(1/4) = 2^((k-1)/4)，不是 2^(k/4)
    assert _resolve_alpha("rotatable", 5, 3) == pytest.approx(2.0)  # nf=16 → 16^(1/4)=2
    assert _resolve_alpha("rotatable", 6, 3) == pytest.approx(32**0.25)


def test_resolve_alpha_orthogonal_never_nan():
    for k in range(2, 8):
        a = _resolve_alpha("orthogonal", k, 3)
        assert np.isfinite(a) and a > 0, f"k={k} 时 orthogonal α 应为有限正值，实际 {a!r}"


def test_doe_design_ccd_k5_half_fraction():
    factors = [{"name": f"X{i}", "levels": [-1, 0, 1]} for i in range(5)]
    r = doe_design(_req("ccd", factors, alpha="rotatable", center_points=3, randomize=False))
    assert r.status == "ok"
    # 2^4 半因子(16) + 2*5 轴向(10) + 3 中心 = 29
    assert len(r.tables["design_matrix"]) == 29
    # 轴向点应为 ±α=±2（nf=16 的旋转性 α）
    x0 = r.tables["design_matrix"]["X0"]
    assert 2.0 in set(x0.values) and -2.0 in set(x0.values)


# ═══════════════════════════════════════════════════════════════
# 审查 2026-09-01 L1 缺口：doe_design 已知答案测试（此前仅结构/正交断言）
# ═══════════════════════════════════════════════════════════════


def test_doe_design_full_factorial_known_matrix():
    """L1 数值正确性：2 因子 × 2 水平全因子（randomize=False）的精确设计矩阵。"""
    factors = [
        {"name": "A", "levels": [100, 200]},
        {"name": "B", "levels": ["低", "高"]},
    ]
    r = doe_design(_req("full_factorial", factors, randomize="false"))
    assert r.status == "ok"
    dm = r.tables["design_matrix"]
    assert list(dm.columns) == ["运行顺序", "A", "B"]
    expected = [
        (1, 100, "低"),
        (2, 100, "高"),
        (3, 200, "低"),
        (4, 200, "高"),
    ]
    assert [tuple(row) for row in dm.to_numpy()] == expected


def test_doe_design_taguchi_l9_known_rows():
    """L1 数值正确性：taguchi L9（3 因子 × 3 水平）行组合集合 == 经典 L9 标准表。

    经典 L9（因子水平 1/2/3，行置换等价）九行作为已知答案手工列出。
    """
    factors = [{"name": f, "levels": [1, 2, 3]} for f in ("A", "B", "C")]
    r = doe_design(_req("taguchi", factors, randomize="false"))
    assert r.status == "ok"
    dm = r.tables["design_matrix"]
    assert len(dm) == 9
    got = {tuple(row) for row in dm[["A", "B", "C"]].to_numpy()}
    # 经典 Taguchi L9 正交表（标准九行）
    classic = {
        (1, 1, 1),
        (1, 2, 2),
        (1, 3, 3),
        (2, 1, 2),
        (2, 2, 3),
        (2, 3, 1),
        (3, 1, 3),
        (3, 2, 1),
        (3, 3, 2),
    }
    assert got == classic, f"L9 组合与标准表不符: 缺 {classic - got} 多 {got - classic}"
    assert r.metadata["oa_name"] == "L9"
