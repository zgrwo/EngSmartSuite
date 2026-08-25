"""DOE 设计结果 vs pyDOE2 交叉验证（benchmark，可选测试依赖）。

pyDOE2 是外部基准库（pip install pyDOE2）；未安装时本模块自动跳过。
比较方式：按「点集」比较（与行列顺序、编码无关），消除顺序/浮点差异。

覆盖：
- fullfact   → 全因子（含混合水平）
- ff2n       → 二水平全因子
- bbdesign   → Box-Behnken 边中点
- ccdesign   → 中心复合（旋转性，k≤4 全因子）

编码约定：我方二水平用 0/1，pyDOE2 用 -1/+1，比较前统一转 0/1。

注：CCD 的 alpha='orthogonal' 不与 pyDOE2 比较——pyDOE2 的 'orthogonal'
实现的是「正交分块」（alpha 依赖各块中心点数），而本模块实现的是「效应正交」
（alpha = sqrt((sqrt(nf·N)-nf)/2)），两者是不同概念，无直接可比基准。
"""

import numpy as np
import pytest

pytest.importorskip("pyDOE2")
from pyDOE2 import bbdesign, ccdesign, ff2n, fullfact

from smartsuite.engine.doe_opt import (
    _gen_box_behnken,
    _gen_ccd,
    _gen_fractional,
    _gen_full_factorial,
)


def _as_set(m, tol=6):
    """矩阵 → 点集（四舍五入到 tol 位，消除顺序/浮点/编码差异）。"""
    return {tuple(round(float(x), tol) for x in row) for row in m}


def test_fullfact_matches_pydoe2():
    for levels in ([2, 2], [2, 3], [3, 3], [2, 2, 2], [2, 3, 2], [3, 4]):
        factors = [{"name": f"F{i}", "levels": list(range(nlv))} for i, nlv in enumerate(levels)]
        mine = _gen_full_factorial(factors)
        ref = fullfact(levels)
        assert _as_set(mine) == _as_set(ref), f"levels={levels} 全因子不一致"


def test_two_level_full_factorial_matches_ff2n():
    for k in (2, 3, 4, 5):
        factors = [{"name": f"F{i}", "levels": [0, 1]} for i in range(k)]
        mine, err = _gen_fractional(factors, 2**k)
        assert err == []
        ref = (ff2n(k) + 1) // 2  # -1/+1 → 0/1
        assert _as_set(mine) == _as_set(ref), f"k={k} 二水平全因子不一致"


def test_box_behnken_edges_match_pydoe2():
    for k in (3, 4, 5):
        mine = _gen_box_behnken(k)
        ref = bbdesign(k)
        # pyDOE2 的 bbdesign 含中心点（全零行），只比较非中心点（边中点）
        ref_edges = ref[~np.all(ref == 0, axis=1)]
        assert _as_set(mine) == _as_set(ref_edges), f"k={k} Box-Behnken 边中点不一致"


def test_ccd_rotatable_matches_pydoe2():
    for k in (2, 3, 4):
        alpha = 2 ** (k / 4)
        mine = _gen_ccd(k, alpha, 0)  # 阶乘 + 轴向，无中心点
        ref = ccdesign(k, center=(1, 1), alpha="rotatable")
        ref_noncenter = ref[~np.all(ref == 0, axis=1)]
        assert _as_set(mine) == _as_set(ref_noncenter), f"k={k} CCD 旋转性不一致"
