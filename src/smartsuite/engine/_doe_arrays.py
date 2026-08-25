"""DOE 正交表 — 纯 numpy，零外部依赖。

提供三类正交数组生成：
- two_level_oa(n_runs): GF(2) 饱和二水平正交表 OA(2^n, 2^n-1)
- three_level_oa(n_runs): GF(3) 饱和三水平正交表 OA(3^m, (3^m-1)/2)
- L18: 标准田口混合水平表 OA(18, 2^1·3^7)（硬编码，正交性由测试校验）

混合 2/3 水平的多列构造在 doe_opt._gen_taguchi 中以 L18 为基做直积实现，
不在此处硬编码 L36（避免 828 个数的转录风险）。
"""

from itertools import product as _product

import numpy as np


def two_level_oa(n_runs: int) -> np.ndarray:
    """GF(2) 饱和二水平正交表 OA(2^n, 2^n-1)。

    运行号 0..2^n-1 的 n 个二进制位作为独立列，取全部非空子集的按位异或
    得到 2^n-1 个互相正交的列（值 {0,1}）。
    """
    n = int(round(np.log2(n_runs)))
    rows = np.arange(n_runs)
    cols = []
    for mask in range(1, 1 << n):
        col = np.zeros(n_runs, dtype=int)
        for j in range(n):
            if mask & (1 << j):
                col ^= (rows >> j) & 1
        cols.append(col)
    return np.column_stack(cols)


def two_level_factor_columns(n_runs: int, n_factors: int) -> np.ndarray:
    """从 GF(2) 饱和表取 n_factors 个因子列：独立列优先、高次交互列次之。

    直接取「前 n_factors 列」会把交互列（mask=3=b0^b1）排在独立列
    （mask=4=b2）之前，导致列跨越不足、产生重复运行行。此处按
    「独立列(mask=2^j) → 高次交互列」排序，既消除重复，又最大化分辨率。
    """
    m = two_level_oa(n_runs)
    n = int(round(np.log2(n_runs)))
    indep = [2**j - 1 for j in range(n)]  # 独立列索引（mask = 2^j）
    rest = [i for i in range(m.shape[1]) if i not in indep]
    # 交互列按 mask 二进制位数降序（高次交互优先，提升分辨率）
    rest.sort(key=lambda i: -bin(i + 1).count("1"))
    order = indep + rest
    return m[:, order[:n_factors]]


def three_level_oa(n_runs: int) -> np.ndarray:
    """GF(3) 饱和三水平正交表 OA(3^m, (3^m-1)/2)。

    运行号为 GF(3)^m 的全排列；列为非零线性组合，每个 {c, 2c} 对取一个代表
    （值 {0,1,2}）。
    """
    m = int(round(np.log(n_runs) / np.log(3)))
    rows = np.array(list(_product(range(3), repeat=m)))  # shape (3^m, m)
    cols = []
    seen = set()
    for coeffs in _product(range(3), repeat=m):
        if all(c == 0 for c in coeffs):
            continue
        key = min(coeffs, tuple((2 * c) % 3 for c in coeffs))
        if key in seen:
            continue
        seen.add(key)
        col = sum(coeffs[i] * rows[:, i] for i in range(m)) % 3
        cols.append(col)
    return np.column_stack(cols)


# L18 = OA(18, 2^1·3^7)。标准田口混合水平表。
# 列 0 为二水平(0/1)，列 1-7 为三水平(0/1/2)。
# 正交性由 tests/test_engine/test_doe_design.py 的 test_l18_* 校验。
L18 = np.array(
    [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 1, 1, 1, 1],
        [0, 0, 2, 2, 2, 2, 2, 2],
        [0, 1, 0, 0, 1, 1, 2, 2],
        [0, 1, 1, 1, 2, 2, 0, 0],
        [0, 1, 2, 2, 0, 0, 1, 1],
        [0, 2, 0, 1, 0, 2, 1, 2],
        [0, 2, 1, 2, 1, 0, 2, 0],
        [0, 2, 2, 0, 2, 1, 0, 1],
        [1, 0, 0, 2, 2, 1, 1, 0],
        [1, 0, 1, 0, 0, 2, 2, 1],
        [1, 0, 2, 1, 1, 0, 0, 2],
        [1, 1, 0, 1, 2, 0, 2, 1],
        [1, 1, 1, 2, 0, 1, 0, 2],
        [1, 1, 2, 0, 1, 2, 1, 0],
        [1, 2, 0, 2, 1, 2, 0, 1],
        [1, 2, 1, 0, 2, 0, 1, 2],
        [1, 2, 2, 1, 0, 1, 2, 0],
    ],
    dtype=int,
)
