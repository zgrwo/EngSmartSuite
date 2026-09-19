"""Western Electric 规则检测与 X-bar/S 图常数。"""

import numpy as np

from smartsuite.engine._constants import EPSILON


def _xbar_s_constants(n: int) -> tuple[float, float, float, float]:
    """计算 x-bar/S 控制图常数 (c4, A3, B3, B4)，支持任意 n ≥ 2。

    用于 n > 25 时替代 R 图（S 图在大子组时比 R 图更高效）。
    使用 math.gamma 精确计算 c4 无偏常量。

    Returns:
        (c4, A3, B3, B4)
    """
    import math

    c4 = math.sqrt(2.0 / (n - 1)) * math.gamma(n / 2.0) / math.gamma((n - 1) / 2.0)
    # 审查 2026-09-01 C-10：内联 1e-10 与 _constants.EPSILON 同值，统一引用常量
    c4 = max(c4, EPSILON)
    A3 = 3.0 / (c4 * math.sqrt(n))
    common = 3.0 * math.sqrt(max(0.0, 1.0 - c4**2)) / c4
    B3 = max(0.0, 1.0 - common)
    B4 = 1.0 + common
    return c4, A3, B3, B4


def _we_rules_xbar(values, cl, sigma):
    """Western Electric 规则检测 X-bar 图。返回违规子组索引字典。

    审查 2026-09-16 D-2：原 `sigma = max(sigma, EPSILON)` 把微尺度 σ 抬高到 1e-10
    → 超出 ±3σ 的点被静默漏检（σ 带数据量纲）；改为直接使用 σ，仅对非正/非有限
    的退化 σ（如某组子组均值全同）返回空违规，避免 Rule 8 的 `>= 1σ` 全量误报。
    """
    violations: dict[str, list[int]] = {}
    if not np.isfinite(sigma) or sigma <= 0:
        return violations
    vals = np.asarray(values)
    n = len(vals)

    # Rule 1: 单点超出 ±3σ
    r1 = np.where((vals > cl + 3 * sigma) | (vals < cl - 3 * sigma))[0]
    if len(r1):
        violations["规则1: 超出±3σ"] = [int(i) for i in r1]

    # Rule 2: 连续3点中≥2点超出 ±2σ (同侧)
    r2: set[int] = set()
    for i in range(n - 2):
        above = np.sum(vals[i : i + 3] > cl + 2 * sigma)
        below = np.sum(vals[i : i + 3] < cl - 2 * sigma)
        if above >= 2:
            r2.update(j for j in range(i, i + 3) if vals[j] > cl + 2 * sigma)
        if below >= 2:
            r2.update(j for j in range(i, i + 3) if vals[j] < cl - 2 * sigma)
    if r2:
        violations["规则2: 3点中≥2点超出±2σ"] = sorted(r2)

    # Rule 3: 连续5点中≥4点超出 ±1σ (同侧)
    r3: set[int] = set()
    for i in range(n - 4):
        above = np.sum(vals[i : i + 5] > cl + 1 * sigma)
        below = np.sum(vals[i : i + 5] < cl - 1 * sigma)
        if above >= 4:
            r3.update(j for j in range(i, i + 5) if vals[j] > cl + 1 * sigma)
        if below >= 4:
            r3.update(j for j in range(i, i + 5) if vals[j] < cl - 1 * sigma)
    if r3:
        violations["规则3: 5点中≥4点超出±1σ"] = sorted(r3)

    # Rule 4: 连续8点在同一侧
    r4: set[int] = set()
    for i in range(n - 7):
        if all(vals[i : i + 8] > cl) or all(vals[i : i + 8] < cl):
            r4.update(range(i, i + 8))
    if r4:
        violations["规则4: 连续8点同侧"] = sorted(r4)

    # Rule 5: 连续6点单调上升或下降
    r5: set[int] = set()
    for i in range(n - 5):
        if all(vals[i + k + 1] > vals[i + k] for k in range(5)):
            r5.update(range(i, i + 6))
        if all(vals[i + k + 1] < vals[i + k] for k in range(5)):
            r5.update(range(i, i + 6))
    if r5:
        violations["规则5: 连续6点趋势"] = sorted(r5)

    # Rule 6: 连续15点在 ±1σ 内（分层/虚假受控）
    r6: set[int] = set()
    for i in range(n - 14):
        if all(abs(vals[i : i + 15] - cl) < 1 * sigma):
            r6.update(range(i, i + 15))
    if r6:
        violations["规则6: 连续15点在±1σ内"] = sorted(r6)

    # Rule 7（Round-2 #A2r）：连续14点交替升降
    r7: set[int] = set()
    for i in range(n - 13):
        diffs = np.diff(vals[i : i + 14])
        if np.all(diffs > 0) or np.all(diffs < 0):
            continue  # 单调不算交替
        if (np.all(diffs[::2] > 0) and np.all(diffs[1::2] < 0)) or (
            np.all(diffs[::2] < 0) and np.all(diffs[1::2] > 0)
        ):
            r7.update(range(i, i + 14))
    if r7:
        violations["规则7: 连续14点交替升降"] = sorted(r7)

    # Rule 8（Round-2 #A2r）：连续8点在 ±1σ 外（任一侧）
    r8: set[int] = set()
    for i in range(n - 7):
        if all(abs(vals[i + j] - cl) >= 1 * sigma for j in range(8)):
            r8.update(range(i, i + 8))
    if r8:
        violations["规则8: 连续8点在±1σ外"] = sorted(r8)

    return violations


def _we_rules_r(values, cl, ucl, lcl=0):
    """R 控制图的模式检测规则（右偏分布，不同于 X-bar 的对称规则）。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    n = len(vals)

    # Rule R1a: 超出 UCL
    r1 = np.where(vals > ucl)[0]
    if len(r1):
        violations["R1a: 超出UCL"] = [int(i) for i in r1]

    # Rule R1b: 低于 LCL (仅当 LCL>0 时)
    if lcl > 0:
        r1b = np.where(vals < lcl)[0]
        if len(r1b):
            violations["R1b: 低于LCL"] = [int(i) for i in r1b]

    # Rule R2: 连续 7 点在中心线同侧
    r2_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i : i + 7] > cl):
            r2_seen.update(range(i, i + 7))
        if all(vals[i : i + 7] < cl):
            r2_seen.update(range(i, i + 7))
    if r2_seen:
        violations["R2: 连续7点同侧"] = sorted(r2_seen)

    # Rule R3: 连续 7 点上升 (变异性恶化) — 严格单调，与 X-bar Rule 5 一致
    r3_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i + k + 1] > vals[i + k] for k in range(6)):
            r3_seen.update(range(i, i + 7))
    if r3_seen:
        violations["R3: 连续7点上升 (变异增大)"] = sorted(r3_seen)

    # Rule R4: 连续 7 点下降 (变异性改善)
    r4_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i + k + 1] < vals[i + k] for k in range(6)):
            r4_seen.update(range(i, i + 7))
    if r4_seen:
        violations["R4: 连续7点下降 (变异减小)"] = sorted(r4_seen)

    # 去重每个规则内的索引
    return {k: sorted(set(v)) for k, v in violations.items()}


def _we_rules_s(values, cl, ucl, lcl=0):
    """S 控制图的模式检测规则（与 R 图规则一致，使用 S 命名）。"""
    violations: dict[str, list[int]] = {}
    vals = np.asarray(values)
    n = len(vals)

    # Rule S1a: 超出 UCL
    r1 = np.where(vals > ucl)[0]
    if len(r1):
        violations["S1a: 超出UCL"] = [int(i) for i in r1]

    # Rule S1b: 低于 LCL (仅当 LCL>0 时)
    if lcl > 0:
        r1b = np.where(vals < lcl)[0]
        if len(r1b):
            violations["S1b: 低于LCL"] = [int(i) for i in r1b]

    # Rule S2: 连续 7 点在中心线同侧
    s2_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i : i + 7] > cl):
            s2_seen.update(range(i, i + 7))
        if all(vals[i : i + 7] < cl):
            s2_seen.update(range(i, i + 7))
    if s2_seen:
        violations["S2: 连续7点同侧"] = sorted(s2_seen)

    # Rule S3: 连续 7 点上升 (变异性恶化)
    s3_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i + k + 1] > vals[i + k] for k in range(6)):
            s3_seen.update(range(i, i + 7))
    if s3_seen:
        violations["S3: 连续7点上升 (变异增大)"] = sorted(s3_seen)

    # Rule S4: 连续 7 点下降 (变异性改善)
    s4_seen: set[int] = set()
    for i in range(n - 6):
        if all(vals[i + k + 1] < vals[i + k] for k in range(6)):
            s4_seen.update(range(i, i + 7))
    if s4_seen:
        violations["S4: 连续7点下降 (变异减小)"] = sorted(s4_seen)

    return {k: sorted(set(v)) for k, v in violations.items()}
