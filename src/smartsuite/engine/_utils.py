"""引擎层共享工具函数。

本模块存放被多个引擎子模块（root_cause, doe_opt, spc_monitor, exploratory）共同使用的
通用工具函数，避免代码重复和跨子模块导入。
"""

import logging
import warnings

import numpy as np
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)


def shapiro_p(data) -> float:
    """Shapiro-Wilk p 值 — 退化输入显式短路，保证跨 scipy 版本确定性。

    scipy 版本行为不一致：<1.18 对零极差数据发 UserWarning 并返回 p=1.0，
    >=1.18 静默返回 NaN（warnings-as-errors 环境下前者会中断分析）。
    统一语义：无方差数据 W=1 → p=1.0（正态性检验不拒绝）。

    ## 不可判定时返回 NaN（审查 2026-10-09 P0-3）

    原实现把 scipy 的 NaN 一律归一为 `1.0`（`return 1.0 if np.isnan(p) else p`）。
    但 `:28` 的零极差短路已经接管了"无方差"这一唯一合法场景，故该分支实际只对
    **真实失败**生效 —— 而 scipy 在下列情形**全部返回 NaN**（实测 1.18.1）：
    含 `NaN` / `±Inf`、`n < 3`、以及量级过大（`Σy²` 溢出，`|y| ≳ 1e154`）。

    把"无法计算"伪造成 `1.0`（= 不拒绝正态）会让**强右偏**数据被判「满足正态性」，
    且判决随量级翻转（实测同一份偏度 1.4547 的数据：1e152 判非正态、1e153 判正态），
    用户据此免做数据变换。违反陷阱 9 规则 2「不可估计时不得伪造 0.0/1.0」。

    Args:
        data: 一维数值序列（n >= 3，调用方保证）

    Returns:
        p 值；**不可判定时为 `NaN`** —— 由调用方显式处置（标注"无法判定"或拒绝），
        不得静默当作"正态"。
    """
    if float(np.max(data)) == float(np.min(data)):
        return 1.0
    # 退化输入（含 ±Inf/NaN、n<3、量级溢出）会让 scipy 内部发
    # `invalid value encountered` / `overflow encountered` RuntimeWarning 并返回 NaN。
    # 该告警在此**是预期路径**，故就地窄静默 —— 关键收益是**行为一致**：
    # `pyproject.toml` 的 `filterwarnings = ["error"]` 只作用于 pytest，若不静默，
    # 同一输入在 pytest 下会变成异常、在生产下才走 NaN 分支，于是"不得伪造正态"的
    # 断言在 CI 里空过（P0-6 同一条假绿通道）。静默不掩盖问题：结果非有限时
    # 一律向上传播 NaN。
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return float(sp_stats.shapiro(data)[1])


def is_positive_finite(value: float) -> bool:
    """参数守卫谓词：是否为**正的有限数**。

    审查 2026-09-21 D-1（P1）：`x <= 0` 作为「必须为正」的守卫会漏两路——
    NaN 与任何数比较恒为 False（IEEE-754），`+Inf` 也不满足 `<= 0`。
    实测 `k/h/L="nan"|"inf"` 绕过守卫后 CUSUM 报警数由 4 静默降为 0。

    用法：`if not is_positive_finite(k): return AnalysisResult(status="error", ...)`
    """
    return bool(np.isfinite(value)) and value > 0


def safe_float(value, default: float) -> float:
    """安全转换参数值为 float，防御 CLI/YAML 字符串参数导致的 TypeError。

    所有从 req.params 提取数值参数的位置均应使用此函数，
    避免 `"0.05" < 0.05` 之类的类型比较崩溃。

    Args:
        value: 待转换的值（可能为 None、str、int、float 等）
        default: 转换失败时返回的默认值

    Returns:
        转换后的 float 值，或 default
    """
    if value is None:
        return default
    try:
        result = float(value)
    except (ValueError, TypeError):
        logger.debug("参数值转换失败: %r → 使用默认值 %s", value, default)
        return default
    # 审查 2026-08-19 #2.6：float("nan")/float("inf") 不抛异常但会产生
    # 非有限值，docstring 承诺"转换失败返回默认值"，NaN/Inf 视为转换失败
    if not np.isfinite(result):
        logger.debug("参数值非有限: %r → 使用默认值 %s", value, default)
        return default
    return result


def threshold_label(value, thresholds, labels=("可忽略", "小", "中", "大")):
    """通用效应量阈值标签函数。

    跨模块共享工具：被 root_cause 与 doe_opt 子包调用。

    Args:
        value: 待判定的效应量值
        thresholds: 升序阈值列表，如 [0.01, 0.06, 0.14]
        labels: 对应标签元组，比 thresholds 多一个元素

    Returns:
        效应量等级标签字符串
    """
    if not np.isfinite(value):
        return "N/A"
    for t, label in zip(thresholds, labels, strict=False):
        if value < t:
            return label
    return labels[-1]


def durbin_watson(residuals):
    """Durbin-Watson 统计量 — 检测残差一阶自相关。

    跨模块共享工具：被 doe_opt 子包 (regression_analysis) 和 spc_monitor.py (trend_forecast) 调用。

    Args:
        residuals: 残差数组

    Returns:
        DW 统计量 (0-4)，接近 2 表示无自相关

    Raises:
        ValueError: 残差数量不足 2 个
    """
    if len(residuals) < 2:
        raise ValueError(
            f"Durbin-Watson 统计量需要至少 2 个残差值，当前仅有 {len(residuals)} 个。"
            f"请确保回归模型有足够的观测数据。"
        )
    diff = np.diff(residuals)
    # 审查 2026-09-16 D-2：原分母 `Σe² + EPSILON` 把微尺度残差（~1e-13）的 DW 压到 ~0
    # → 假"正自相关"；DW 为量纲无关比值，仅残差全零（完美拟合）无定义 → 中性值 2.0
    denom = float(np.sum(np.square(residuals)))
    if denom == 0:
        return 2.0
    dw = float(np.sum(np.square(diff)) / denom)
    return dw


def round_for_display(values, decimals: int = 4):
    """表格显示舍入：常规量级按 decimals 位小数；微尺度数据改按有效数字。

    固定 decimals 位小数对量级 < 0.5×10^-decimals 的数据会整组归零——
    单位换算后的纳米/微应变测量值（~1e-10）在预测/异常表中全部显示
    0.0000（审查 2026-09-05 新观察 O-1）。当组内最大绝对值低于该阈值时，
    按组内最大值的量级统一取 decimals 位有效数字；常规量级的行为与
    round(x, decimals) 逐位一致，既有表格显示不受影响。

    Args:
        values: 标量或数组（ndarray/Series/list，按位置转换）；NaN/Inf 原样保留
        decimals: 常规量级的小数位（同时也是微尺度分支的有效数字位数）

    Returns:
        标量输入返回 float，数组输入返回 ndarray
    """
    scalar_input = np.isscalar(values)
    arr = np.atleast_1d(np.asarray(values, dtype=float))
    finite = arr[np.isfinite(arr)]
    scale = float(np.max(np.abs(finite))) if finite.size else 0.0
    if scale == 0.0 or scale >= 0.5 * 10.0 ** (-decimals):
        out = np.round(arr, decimals)
    else:
        mag = int(np.floor(np.log10(scale)))
        out = np.round(arr, max(decimals - 1 - mag, 0))
    return float(out[0]) if scalar_input else out


def _adjust_xlabels(ax, n_labels: int, fig=None):
    """自适应调整 X 轴刻度标签：根据标签数量选择旋转角度和字号。

    统一所有控制图、箱线图的 X 轴标签显示策略，消除硬编码 fontsize/rotation。
    与 _fmt_labels / _fmt_attr_labels 配合使用（后者负责文字截断和稀疏化）。

    Args:
        ax: matplotlib Axes 对象
        n_labels: 标签总数（含可能被 _fmt_labels 置空的标签）
        fig: 可选，用于多标签时自动调整子图边距
    """
    if n_labels <= 4:
        ax.tick_params(axis="x", labelsize=9)
    elif n_labels <= 8:
        ax.tick_params(axis="x", labelsize=9, rotation=30)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    elif n_labels <= 15:
        ax.tick_params(axis="x", labelsize=8, rotation=45)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    else:
        ax.tick_params(axis="x", labelsize=7.5, rotation=60)
        for label in ax.get_xticklabels():
            label.set_ha("right")
        if fig:
            fig.subplots_adjust(bottom=0.25)
