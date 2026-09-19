"""DOE 实验设计与效应分析（doe_analysis / doe_design）。"""

import logging
import math
import numbers
from itertools import combinations, product

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import (
    round_for_display,
    threshold_label,
)
from smartsuite.engine._utils import (
    safe_float as _safe_float,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# DOE 实验设计（doe_design）— 生成实验设计矩阵
# ══════════════════════════════════════════════════════════════════════


def _lenth_pse(effects):
    """Lenth 伪标准误 — 用于无重复 DOE 的效应显著性判断。

    审查 2026-09-16 C-3：效应值带数据量纲，原 `max(pse, EPSILON)=1e-10` 绝对下限
    会把微尺度 PSE/SME 抬高到与效应同量级 → 失真。改为返回原始值；
    全零效应返回 0（调用方 `me > 0` 守卫不画 SME 参考线）。
    """
    abs_effects = np.sort(np.abs(effects))
    # 取中位数的一半作为初始 s0
    median_abs = np.median(abs_effects)
    s0 = 1.5 * median_abs
    # 剔除 > 2.5*s0 的效应后重新计算 PSE
    trimmed = abs_effects[abs_effects < 2.5 * s0]
    if len(trimmed) == 0:
        return float(s0)
    pse = 1.5 * np.median(trimmed)
    return float(pse)


# DOE 效应量阈值（η² 类逐步效应量, Richardson 2011）
_DOE_EFFECT_THRESHOLDS = [0.05, 0.15, 0.30]


def doe_analysis(req: AnalysisRequest) -> AnalysisResult:
    """DOE 主效应与交互效应分析，含显著性检验。"""
    cols = [c for c in req.feature_cols if c in req.data.columns]
    if len(cols) < 1:
        return AnalysisResult(
            task="doe_analysis",
            status="error",
            messages=["需要至少 1 个因子"],
        )

    df = req.data[[req.target_col] + cols].dropna()
    if len(df) < 3:
        return AnalysisResult(
            task="doe_analysis",
            status="error",
            messages=[f"有效样本({len(df)})不足"],
        )

    grand_mean = float(df[req.target_col].mean())
    grand_std = float(df[req.target_col].std(ddof=1))

    # ── 回归法估计效应（编码变量 -1/+1，比中位数分割更准确）──
    effects = []
    coded_map: dict[str, np.ndarray] = {}  # 编码列缓存（供交互效应复用）
    y = df[req.target_col].values
    for col in cols:
        col_vals = df[col]
        unique_vals = col_vals.unique()
        if len(unique_vals) <= 1:
            effects.append(
                {
                    "因子": col,
                    "主效应": 0.0,
                    "效应占比": 0.0,
                    "t值": 0.0,
                    "p值": 1.0,
                    "显著": "否",
                    "效应量": "可忽略",
                }
            )
            continue

        if len(unique_vals) == 2:
            # 二水平因子：直接编码 -1/+1（效应 = 全范围差异）
            s = sorted(unique_vals)
            _lo, hi = s[0], s[-1]
            coded = np.where(col_vals == hi, 1, -1)
        else:
            # Round-2 #A3c：多水平/连续因子需 z-score，字符串列无法运算
            if not pd.api.types.is_numeric_dtype(col_vals):
                return AnalysisResult(
                    task="doe_analysis",
                    status="error",
                    messages=[
                        f"因子列「{col}」含 {len(unique_vals)} 个非数值水平，"
                        "DOE 效应估计仅支持二水平类别或数值因子。"
                        "请先 One-Hot 编码或转为数值。"
                    ],
                )
            # 多水平/连续因子：标准化后作为线性效应
            # 审查 2026-09-16 C-3：std 带数据量纲，绝对 EPSILON 会稀释微尺度因子
            _std = float(col_vals.std(ddof=1))
            coded = (
                (col_vals - col_vals.mean()) / _std
                if _std > 0
                else pd.Series(0.0, index=col_vals.index)
            )
        coded_map[col] = coded

        X = np.column_stack([np.ones(len(coded)), coded])
        try:
            beta, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
            # 二水平因子: 效应 = 2*β (对应 -1→+1 的全部范围变化)
            # 连续因子: 效应 = 2*β (对应 ±1σ 的变化，约覆盖 68% 数据)
            # 注: 两种效应量的物理含义不同（全范围 vs 2σ），Pareto 图中并排展示时需注意解读差异
            effect = float(2 * beta[1])
            # t 检验（审查 2026-09-16 B-1：se 带数据量纲，原 `se > EPSILON` 绝对判据
            # 会把微/ppb 尺度数据的 t 置 0、p 置 1、显著静默漏判 → 改精确零判据；
            # t=β/se 本身量纲无关，仅 se 精确为 0（完美拟合）时不可计算 → NaN+无法判定）
            resid_std = float(np.std(y - X @ beta, ddof=2)) if len(y) > 2 else 1.0
            Sxx = float(np.sum((coded - np.mean(coded)) ** 2))
            se = resid_std / np.sqrt(Sxx) if Sxx > 0 else float("nan")
            t_val = float(beta[1] / se) if np.isfinite(se) and se > 0 else float("nan")
            dof = len(y) - 2
            p_val = (
                float(2 * sp_stats.t.sf(abs(t_val), dof))
                if dof > 0 and np.isfinite(t_val)
                else float("nan")
            )
        except (ValueError, np.linalg.LinAlgError, TypeError) as e:
            logger.warning("DOE 效应估计失败 (因子: %s): %s", col, e)
            # 标记为计算失败而非静默赋零，避免伪造正常结果
            effects.append(
                {
                    "因子": col,
                    "主效应": None,
                    "效应占比": None,
                    "t值": None,
                    "p值": None,
                    "显著": "计算失败",
                    "效应量": "计算异常（详见日志）",
                }
            )
            continue

        # 审查 2026-09-16 B-1：效应占比分母原为 abs(grand_mean)+EPSILON 并附加
        # 绝对门槛，微尺度整体均值会扭曲/清零占比 → 改精确零判据（量纲同比，占比无量纲）
        effect_ratio = abs(effect) / abs(grand_mean) if grand_mean != 0 else 0.0
        alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
        # Round-2 P3：alpha 越界（如 2.0）→ 全因子"显著"
        if not 0 < alpha < 1:
            return AnalysisResult(
                task="doe_analysis",
                status="error",
                messages=[f"alpha 必须在 (0, 1) 区间内，当前: {alpha!r}"],
            )
        effects.append(
            {
                "因子": col,
                "主效应": round_for_display(effect),
                "效应占比": round(effect_ratio, 4),
                "t值": round(t_val, 3),
                "p值": round(p_val, 4),
                "显著": (
                    "无法判定" if not np.isfinite(p_val) else ("是" if p_val < alpha else "否")
                ),
                "效应量": threshold_label(
                    effect_ratio, _DOE_EFFECT_THRESHOLDS, ("可忽略", "小", "中", "大")
                ),
            }
        )

    # ── 两两交互效应（MED-2 修复 2026-08-29：docstring 承诺但此前缺失）──
    # 编码交互列 = coded_i × coded_j，同样单变量 lstsq 回归，效应 = 2β（口径与主效应一致）
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    coded_names = list(coded_map.keys())
    if len(coded_names) >= 2:
        for i in range(len(coded_names)):
            for j in range(i + 1, len(coded_names)):
                ci_name, cj_name = coded_names[i], coded_names[j]
                inter = coded_map[ci_name] * coded_map[cj_name]
                inter_name = f"{ci_name}×{cj_name}"
                X_i = np.column_stack([np.ones(len(inter)), inter])
                try:
                    beta_i, _, _, _ = np.linalg.lstsq(X_i, y, rcond=None)
                    effect_i = float(2 * beta_i[1])
                    resid_std_i = float(np.std(y - X_i @ beta_i, ddof=2)) if len(y) > 2 else 1.0
                    Sxx_i = float(np.sum((inter - np.mean(inter)) ** 2))
                    se_i = resid_std_i / np.sqrt(Sxx_i) if Sxx_i > 0 else float("nan")
                    t_i = (
                        float(beta_i[1] / se_i) if np.isfinite(se_i) and se_i > 0 else float("nan")
                    )
                    dof_i = len(y) - 2
                    p_i = (
                        float(2 * sp_stats.t.sf(abs(t_i), dof_i))
                        if dof_i > 0 and np.isfinite(t_i)
                        else float("nan")
                    )
                except (ValueError, np.linalg.LinAlgError, TypeError) as e:
                    logger.warning("DOE 交互效应估计失败 (%s): %s", inter_name, e)
                    effects.append(
                        {
                            "因子": inter_name,
                            "主效应": None,
                            "效应占比": None,
                            "t值": None,
                            "p值": None,
                            "显著": "计算失败",
                            "效应量": "计算异常（详见日志）",
                        }
                    )
                    continue
                ratio_i = abs(effect_i) / abs(grand_mean) if grand_mean != 0 else 0.0
                effects.append(
                    {
                        "因子": inter_name,
                        "主效应": round_for_display(effect_i),
                        "效应占比": round(ratio_i, 4),
                        "t值": round(t_i, 3),
                        "p值": round(p_i, 4),
                        "显著": (
                            "无法判定" if not np.isfinite(p_i) else ("是" if p_i < alpha else "否")
                        ),
                        "效应量": threshold_label(
                            ratio_i, _DOE_EFFECT_THRESHOLDS, ("可忽略", "小", "中", "大")
                        ),
                    }
                )

    effects_df = pd.DataFrame(effects)
    # 分离计算失败的因子（避免 None 值影响排序和统计）
    failed_effects = (
        effects_df[effects_df["主效应"].isna()] if "主效应" in effects_df else pd.DataFrame()
    )
    valid_effects = effects_df[effects_df["主效应"].notna()].sort_values(
        "主效应", key=abs, ascending=False
    )
    top_name = str(valid_effects["因子"].iloc[0]) if len(valid_effects) > 0 else "N/A"
    top_val = float(valid_effects["主效应"].iloc[0]) if len(valid_effects) > 0 else 0

    # ── Lenth PSE 参考线（无重复时替代 p 值作为显著性参考）──
    effect_array = valid_effects["主效应"].values
    pse = _lenth_pse(effect_array) if len(effect_array) >= 3 else 0
    # Lenth 临界值使用 t 分布近似（自由度 ≈ m/3，m = 效应数目）
    m = len(effect_array)
    lenth_df = max(1, int(m / 3))
    lenth_t_crit = float(sp_stats.t.ppf(1 - alpha / 2, lenth_df)) if m >= 3 else 2.0
    me = lenth_t_crit * pse  # 同步边际误差 (SME) 近似

    # ── Pareto 图含显著性阈值 ──
    n_plot = max(len(valid_effects), 1)
    fig = Figure(figsize=(max(n_plot * 0.9, 6), 4))
    ax = fig.add_subplot(111)
    ef = valid_effects.sort_values("主效应", key=abs)
    colors = [
        PALETTE["target"]["primary"] if v < 0 else PALETTE["data"]["primary"] for v in ef["主效应"]
    ]
    ax.barh(ef["因子"], ef["主效应"], color=colors, height=0.6)
    ax.axvline(0, color=PALETTE["direction"]["zero"], linewidth=0.8)
    # 自适应轴范围：主效应远小于 Lenth 阈值时不再把阈值线画进来（否则柱子被压成发丝）
    max_abs = float(np.max(np.abs(effect_array))) if len(effect_array) else 0.0
    xmax = max(max_abs * 1.35, 1e-12)
    me_in_view = me > 0 and me <= xmax
    if me_in_view:
        xmax = max(xmax, me * 1.15)
    ax.set_xlim(-xmax, xmax)
    if me > 0:
        if me_in_view:
            ax.axvline(
                me,
                color=PALETTE["anomaly"]["primary"],
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"Lenth ME={round_for_display(me):g} (α={alpha})",
            )
            ax.axvline(
                -me, color=PALETTE["anomaly"]["primary"], linestyle="--", linewidth=1, alpha=0.6
            )
            ax.legend(fontsize=8)
        else:
            ax.text(
                0.02,
                0.96,
                f"Lenth ME=±{round_for_display(me):g}（全部未达显著）",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8,
                color=PALETTE["anomaly"]["primary"],
            )
    # 标注效应值
    for i, (_, row) in enumerate(ef.iterrows()):
        v = row["主效应"]
        ha = "left" if v >= 0 else "right"
        ax.text(
            v,
            i,
            f" {round_for_display(v):+g}",
            va="center",
            ha=ha,
            fontsize=8,
            fontweight="bold" if abs(v) > me else "normal",
        )
    ax.set_xlabel("主效应", fontsize=10)
    ax.set_title(
        f"DOE主效应 — {req.target_col} | 均值={round_for_display(grand_mean):g}, "
        f"σ={round_for_display(grand_std):g}",
        fontsize=11,
    )
    if me_in_view:
        ax.legend(fontsize=8)
    fig.tight_layout()

    # ── 汇总 ──
    sig_count = int((valid_effects["显著"] == "是").sum())
    fail_count = len(failed_effects)
    top_effect_label = str(valid_effects["效应量"].iloc[0]) if len(valid_effects) > 0 else "N/A"
    summary_parts = [
        f"最强主效应: {top_name} (效应={round_for_display(top_val):g}, {top_effect_label})",
        f"显著因子: {sig_count}/{len(valid_effects)}",
    ]
    if fail_count > 0:
        summary_parts.append(f"⚠ {fail_count} 个因子计算失败")
    summary = "。".join(summary_parts)

    # 合并有效结果和失败标记到输出表
    output_table = (
        pd.concat([valid_effects, failed_effects], ignore_index=True)
        if fail_count > 0
        else valid_effects
    )

    return AnalysisResult(
        task="doe_analysis",
        tables={"effect_estimates": output_table},
        figures=[fig],
        summary=summary,
        metadata={
            "grand_mean": grand_mean,
            "failed_factors": fail_count,
            "grand_std": grand_std,
            "top_effect_factor": top_name,
            "lenth_pse": pse,
            "lenth_me": me,
            "significant_count": sig_count,
        },
    )


_VALID_DOE_METHODS = (
    "full_factorial",
    "fractional_factorial",
    "plackett_burman",
    "taguchi",
    "box_behnken",
    "ccd",
)

# Plackett-Burman 支持的运行数（N-1 必须为素数且 ≡ 3 mod 4，保证循环构造正交）。
# 注：28 不是标准 PB 规模（27=3³ 非素数，无循环差集，构造方式不同），故不列入。
_PB_SUPPORTED = (12, 20, 24)


def _legendre(a: int, p: int) -> int:
    """Legendre 符号：+1（二次剩余）/ -1（非剩余）/ 0（a ≡ 0 mod p）。"""
    a %= p
    if a == 0:
        return 0
    return 1 if pow(a, (p - 1) // 2, p) == 1 else -1


def _pb_generator(n_runs: int) -> list[int]:
    """Plackett-Burman 生成首行（+1 → 1，-1 → 0），基于二次剩余构造。

    N-1 = p 为素数时，g[j] = χ(j)（j=0..p-1），其中 χ(0) 约定为 +1。
    循环移位 + 末行全 0 后构成正交矩阵（由测试校验）。
    """
    if n_runs not in _PB_SUPPORTED:
        raise ValueError(f"plackett_burman 当前仅支持运行数 {list(_PB_SUPPORTED)}")
    p = n_runs - 1
    return [1 if (j == 0 or _legendre(j, p) == 1) else 0 for j in range(p)]


def _is_num(v) -> bool:
    """数值标量判定（审查 2026-09-19 E12）：numbers.Real 覆盖 int/float/numpy 全系；
    numpy 2.x 起 np.int64/np.float32 不再是 int/float 子类，旧判据会误判为非数值。
    bool 必须排除（bool ⊂ numbers.Real），否则 True 会被当作数值 1。
    """
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def _as_bool(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "是")
    return bool(v)


def _parse_factors(params):
    """解析并校验 factors 参数。返回 (parsed_list | None, [错误消息])。"""
    factors = params.get("factors")
    if not factors:
        return None, ["需要提供因子定义 (factors)，格式: [{'name': ..., 'levels': [...]}]"]
    parsed, seen = [], set()
    for i, f in enumerate(factors):
        name = f.get("name")
        levels = f.get("levels")
        if not name or not isinstance(name, str):
            return None, [f"第 {i + 1} 个因子缺少有效的 name"]
        if name in seen:
            return None, [f"因子名重复: {name}"]
        seen.add(name)
        if not isinstance(levels, (list, tuple)) or len(set(map(str, levels))) < 2:
            return None, [f"因子「{name}」的水平数必须 ≥ 2 且互异"]
        parsed.append({"name": name, "levels": list(levels)})
    return parsed, []


def _gen_full_factorial(factors) -> np.ndarray:
    """全因子：所有水平组合的笛卡尔积，返回水平索引矩阵。"""
    idx = [range(len(f["levels"])) for f in factors]
    return np.array(list(product(*idx)), dtype=int)


def _gen_fractional(factors, n_runs):
    """2^(k-p) 部分因子：GF(2) 饱和表取 k 个因子列（独立列优先）。返回 (矩阵, 错误列表)。"""
    from smartsuite.engine._doe_arrays import _two_level_factor_columns

    n = int(round(np.log2(n_runs)))
    if 2**n != n_runs:
        return None, [f"fractional_factorial 的运行数必须是 2 的幂，当前: {n_runs}"]
    k = len(factors)
    if k > n_runs - 1:
        return None, [f"因子数({k})超过 2^n-1({n_runs - 1})，正交表装不下"]
    return _two_level_factor_columns(n_runs, k), []


def _pb_matrix(n_runs) -> np.ndarray:
    """Plackett-Burman 矩阵：循环移位 + 末行全 0。"""
    g = np.array(_pb_generator(n_runs))
    rows = [np.roll(g, i) for i in range(n_runs - 1)]
    rows.append(np.zeros(n_runs - 1, dtype=int))
    return np.array(rows, dtype=int)


def _gen_plackett_burman(factors, n_runs):
    """Plackett-Burman 筛选设计。返回 (矩阵, 错误列表)。"""
    k = len(factors)
    try:
        m = _pb_matrix(n_runs)
    except ValueError as e:
        logger.warning("PB 设计生成失败 (n_runs=%s): %s", n_runs, e)
        return None, [f"plackett_burman 当前仅支持运行数: {sorted(_PB_SUPPORTED)}"]
    if k > n_runs - 1:
        return None, [f"因子数({k})超过 PB 运行数上限({n_runs - 1})"]
    return m[:, :k], []


def _two_level_base(name, runs) -> np.ndarray:
    """二水平正交表：L12 走 PB，其余走 GF(2)。"""
    from smartsuite.engine._doe_arrays import two_level_oa

    if name == "L12":
        return _pb_matrix(12)
    return two_level_oa(runs)


def _gen_taguchi(factors):
    """田口正交数组匹配器。返回 (编码矩阵, 表名, 列构成描述)。

    纯二水平 → L4/L8/L12/L16/L32；纯三水平 → L9/L27；
    混合 2/3 水平 → 以 L18 为基与 2^m 全因子做直积。
    失败时抛 ValueError（中文消息）。
    """
    from smartsuite.engine._doe_arrays import L18, three_level_oa, two_level_oa

    n2 = sum(1 for f in factors if len(f["levels"]) == 2)
    n3 = sum(1 for f in factors if len(f["levels"]) == 3)

    if n3 == 0:
        for name, runs, c2 in (
            ("L4", 4, 3),
            ("L8", 8, 7),
            ("L12", 12, 11),
            ("L16", 16, 15),
            ("L32", 32, 31),
        ):
            if n2 <= c2:
                two_cols = _two_level_base(name, runs)
                three_cols = None
                spec = f"2^{c2}"
                break
        else:
            raise ValueError(f"二水平因子数({n2})过多，无正交表可匹配")
    elif n2 == 0:
        for oa_name, runs, c3 in (("L9", 9, 4), ("L27", 27, 13)):
            if n3 <= c3:
                three_cols = three_level_oa(runs)
                two_cols = None
                name = oa_name
                spec = f"3^{c3}"
                break
        else:
            raise ValueError(f"三水平因子数({n3})过多，无正交表可匹配")
    else:
        if n3 > 7:
            raise ValueError(
                "三水平因子数超过 7 且含二水平因子时无正交表可匹配；"
                "建议改用 full_factorial 或减少三水平因子数"
            )
        if n2 <= 1:
            two_cols = L18[:, 0:1]
            three_cols = L18[:, 1:8]
            name, spec = "L18", "2^1·3^7"
        else:
            m = 1
            while 2 ** (m + 1) - 1 < n2:
                m += 1
            ff = two_level_oa(2**m)  # (2^m) × (2^m-1)
            c1 = L18[:, 0]
            three = L18[:, 1:8]
            tiled_c1 = np.tile(c1, 2**m)
            two_list = [tiled_c1]
            for i in range(ff.shape[1]):
                a = np.repeat(ff[:, i], 18)
                two_list.append(a)
                two_list.append(tiled_c1 ^ a)
            two_cols = np.column_stack(two_list)  # (18·2^m) × (2^(m+1)-1)
            three_cols = np.tile(three, (2**m, 1))  # (18·2^m) × 7
            name = f"L{18 * 2**m}"
            spec = f"2^{2 ** (m + 1) - 1}·3^7"

    # 依因子顺序拼装列（二水平因子取二水平列，三水平因子取三水平列）
    cols, p2, p3 = [], 0, 0
    for f in factors:
        if len(f["levels"]) == 2:
            assert two_cols is not None  # 分支保证：二水平因子必有二水平列来源
            cols.append(two_cols[:, p2])
            p2 += 1
        else:
            assert three_cols is not None  # 分支保证：三水平因子必有三水平列来源
            cols.append(three_cols[:, p3])
            p3 += 1
    return np.column_stack(cols), name, spec


def _gen_box_behnken(k) -> np.ndarray:
    """Box-Behnken：每对因子的 2×2 方形角点（其余取中心），返回 -1/0/+1 编码。"""
    rows = []
    for i, j in combinations(range(k), 2):
        for a in (-1, 1):
            for b in (-1, 1):
                r = np.zeros(k)
                r[i], r[j] = a, b
                rows.append(r)
    return np.array(rows)


def _gen_ccd(k, alpha, center_points) -> np.ndarray:
    """中心复合设计：2^k（或 2^(k-1)）阶乘 + 2k 轴向点 + 中心点。"""
    if k <= 4:
        fact = np.array(list(product([-1.0, 1.0], repeat=k)))
    else:
        from smartsuite.engine._doe_arrays import _two_level_factor_columns

        n = int(round(np.log2(2 ** (k - 1))))
        fact = 2 * _two_level_factor_columns(2**n, k) - 1  # 0/1 → -1/+1
    axial = []
    for i in range(k):
        for s in (-alpha, alpha):
            r = np.zeros(k)
            r[i] = s
            axial.append(r)
    center = np.zeros((center_points, k))
    return np.vstack([fact, np.array(axial), center])


def _resolve_alpha(alpha, k, center_points):
    """解析 CCD 轴向距离 α。返回 float 或 None（非法）。"""
    # 阶乘点数量：k≤4 全因子 2^k，k≥5 半因子 2^(k-1)
    nf = 2**k if k <= 4 else 2 ** (k - 1)
    if alpha == "rotatable":
        # 旋转性：α = nf^(1/4)（k≤4 时即 2^(k/4)）
        return float(nf ** (1 / 4))
    if alpha == "face":
        return 1.0
    if alpha == "orthogonal":
        # 正交性：α = sqrt((sqrt(nf·N) − nf) / 2)，N = 总运行数
        ns = 2 * k
        n_total = nf + ns + center_points
        return float(np.sqrt((np.sqrt(nf * n_total) - nf) / 2))
    if _is_num(alpha) and alpha > 0:
        return float(alpha)
    return None


def _assemble_design(req, factors, coded, method, oa_name, oa_spec):
    """映射到实际水平 + 重复 + 随机化 + 运行顺序，组装 AnalysisResult。"""
    replicates = req.params.get("replicates", 1)
    try:
        replicates = int(replicates)
    except (ValueError, TypeError):
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=[f"replicates 值无效: {replicates}，请输入整数"],
        )
    if replicates < 1:
        return AnalysisResult(task="doe_design", status="error", messages=["replicates 必须 ≥ 1"])

    cols = {}
    for ci, f in enumerate(factors):
        lv = f["levels"]
        col = coded[:, ci]
        if method in ("box_behnken", "ccd"):
            lo, mid, hi = float(lv[0]), float(lv[1]), float(lv[2])
            vals = np.where(col >= 0, mid + col * (hi - mid), mid + col * (mid - lo))
        else:
            vals = np.array([lv[int(i)] for i in col])
        cols[f["name"]] = vals

    df = pd.DataFrame(cols)
    if replicates > 1:
        df = pd.concat([df] * replicates, ignore_index=True)
        df.insert(0, "重复", np.repeat(np.arange(1, replicates + 1), len(coded)))

    randomize = _as_bool(req.params.get("randomize", True), True)
    seed = req.params.get("seed", 42)
    try:
        seed = int(seed)
    except (ValueError, TypeError):
        seed = 42
    if randomize:
        df = df.sample(frac=1.0, random_state=np.random.RandomState(seed)).reset_index(drop=True)
    df.insert(0, "运行顺序", np.arange(1, len(df) + 1))

    info = pd.DataFrame(
        {
            "指标": ["方法", "正交表", "列构成", "运行数", "因子数"],
            "值": [method, oa_name or "—", oa_spec or "—", str(len(df)), str(len(factors))],
        }
    )
    summary = f"{method} 设计：{len(factors)} 个因子，共 {len(df)} 次运行" + (
        f"（正交表 {oa_name}）" if oa_name else ""
    )
    return AnalysisResult(
        task="doe_design",
        tables={"design_matrix": df, "design_info": info},
        summary=summary,
        metadata={
            "method": method,
            "n_runs": len(df),
            "n_factors": len(factors),
            "oa_name": oa_name,
            "oa_spec": oa_spec,
            "randomized": randomize,
            "seed": seed,
            "replicates": replicates,
        },
    )


def doe_design(req: AnalysisRequest) -> AnalysisResult:
    """DOE 实验设计 — 输入因子（名称+水平）与设计方法，输出实验设计矩阵。

    参数 (params):
        factors: 必需，[{name, levels}]，levels 为水平值列表（数值或标签）
        method: full_factorial | fractional_factorial | plackett_burman
                | taguchi（仅支持 2/3 水平因子）| box_behnken | ccd（默认 full_factorial）
        replicates: 重复次数（默认 1）
        randomize: 是否随机化运行顺序（默认 True）
        seed: 随机种子（默认 42）
        center_points: RSM 中心点重复数（BB/CCD，默认 3）
        alpha: CCD 轴向距离 rotatable|orthogonal|face|数值（默认 rotatable）
        n_runs: 指定运行数（fractional_factorial / plackett_burman）

    数据要求: 无（忽略 req.data，因子从 params 读取）
    """
    method = req.params.get("method", "full_factorial")
    if method not in _VALID_DOE_METHODS:
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=[f"method 无效: {method!r}，支持: {list(_VALID_DOE_METHODS)}"],
        )
    factors, errs = _parse_factors(req.params)
    if errs:
        return AnalysisResult(task="doe_design", status="error", messages=errs)

    oa_name, oa_spec = None, None
    try:
        if method == "full_factorial":
            # 审查 2026-09-19 D-2：np.prod 按 int64 累乘会回绕（50+ 个因子时为 0），
            # 绕过上限检查直达 MemoryError；math.prod 为任意精度整数
            total = math.prod(len(f["levels"]) for f in factors)
            if total > 10000:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[f"全因子运行数({total})超过上限 10000，请改用 taguchi/ccd 降维"],
                )
            coded = _gen_full_factorial(factors)
        elif method == "fractional_factorial":
            if any(len(f["levels"]) != 2 for f in factors):
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=["fractional_factorial 要求所有因子为 2 水平"],
                )
            # 审查 2026-09-05 M-4：`or` falsy 陷阱（n_runs=0 被静默顶替为默认值）
            n_runs = req.params.get("n_runs")
            if n_runs is None:
                n_runs = 2 ** len(factors)
            try:
                n_runs = int(n_runs)
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="doe_design", status="error", messages=[f"n_runs 值无效: {n_runs}"]
                )
            # M-4 配套：n_runs<=0 显式拒绝（np.log2(0)=-inf 会让 int() 溢出崩溃）
            if n_runs <= 0:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[f"n_runs 必须为正整数，当前: {n_runs}"],
                )
            coded, err = _gen_fractional(factors, n_runs)
            if err:
                return AnalysisResult(task="doe_design", status="error", messages=err)
            oa_name = f"2^{int(np.log2(n_runs))}"
            oa_spec = f"2^(k-p), 运行数={n_runs}"
        elif method == "plackett_burman":
            if any(len(f["levels"]) != 2 for f in factors):
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=["plackett_burman 要求所有因子为 2 水平"],
                )
            k = len(factors)
            # 审查 2026-09-05 M-4：`or` falsy 陷阱（n_runs=0 被静默顶替为默认值）
            n_runs = req.params.get("n_runs")
            if n_runs is None:
                n_runs = next((n for n in _PB_SUPPORTED if n - 1 >= k), None)
            try:
                if n_runs is None:  # 无支持的默认运行数
                    raise TypeError("n_runs 无默认值")
                n_runs = int(n_runs)
            except (ValueError, TypeError):
                return AnalysisResult(
                    task="doe_design", status="error", messages=[f"n_runs 值无效: {n_runs}"]
                )
            if n_runs <= 0:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[f"n_runs 必须为正整数，当前: {n_runs}"],
                )
            coded, err = _gen_plackett_burman(factors, n_runs)
            if err:
                return AnalysisResult(task="doe_design", status="error", messages=err)
            oa_name = f"PB{n_runs}"
            oa_spec = f"2^{n_runs - 1}"
        elif method == "taguchi":
            bad_levels = [f["name"] for f in factors if len(f["levels"]) not in (2, 3)]
            if bad_levels:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[f"taguchi 仅支持 2 或 3 水平因子，以下因子不符: {bad_levels}"],
                )
            coded, oa_name, oa_spec = _gen_taguchi(factors)
        else:  # box_behnken / ccd
            bad = [
                f["name"]
                for f in factors
                if len(f["levels"]) != 3 or not all(_is_num(v) for v in f["levels"])
            ]
            if bad:
                return AnalysisResult(
                    task="doe_design",
                    status="error",
                    messages=[
                        f"{method} 要求所有因子为 3 个数值水平（低/中/高），以下因子不符: {bad}"
                    ],
                )
            k = len(factors)
            if method == "box_behnken" and not (3 <= k <= 12):
                return AnalysisResult(
                    task="doe_design", status="error", messages=["box_behnken 支持 3-12 个因子"]
                )
            if method == "ccd" and not (2 <= k <= 10):
                return AnalysisResult(
                    task="doe_design", status="error", messages=["ccd 支持 2-10 个因子"]
                )
            center_points = req.params.get("center_points", 3)
            try:
                center_points = int(center_points)
            except (ValueError, TypeError):
                center_points = 3
            if center_points < 0:
                return AnalysisResult(
                    task="doe_design", status="error", messages=["center_points 必须 ≥ 0"]
                )
            if method == "box_behnken":
                coded = np.vstack(
                    [
                        _gen_box_behnken(k),
                        np.zeros((center_points, k)),
                    ]
                )
                oa_name, oa_spec = "Box-Behnken", f"k={k}"
            else:
                alpha = _resolve_alpha(req.params.get("alpha", "rotatable"), k, center_points)
                if alpha is None:
                    return AnalysisResult(
                        task="doe_design",
                        status="error",
                        messages=[
                            f"alpha 无效: {req.params.get('alpha')!r}，"
                            "支持 rotatable|orthogonal|face 或正数值"
                        ],
                    )
                coded = _gen_ccd(k, alpha, center_points)
                oa_name, oa_spec = "CCD", f"k={k}, α={alpha:.4f}"
    except ValueError as e:
        logger.warning("DOE 设计生成失败 (method=%s): %s", method, e)
        return AnalysisResult(
            task="doe_design",
            status="error",
            messages=["实验设计生成失败：请检查因子水平、alpha 与 center_points 参数配置"],
        )

    return _assemble_design(req, factors, coded, method, oa_name, oa_spec)
