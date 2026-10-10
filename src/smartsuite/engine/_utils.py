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
    # 审查 2026-10-10（远端 CI 实测）：原先**依赖 scipy 自己传播 NaN** —— 而
    # `scipy.stats.shapiro` 对"含 ±Inf"与"量级溢出"两类输入的返回**随构建而变**：
    # Windows/scipy 1.18 返回 NaN（守卫通过），**Linux/该腿的 scipy 返回有限值**
    # （实测 1e155 下返回 `3.78e-14`、含 `inf` 时返回有限 p）→ 同一份代码在两条 CI 腿上
    # 结论不同，守卫在 Linux 上失败。**"不可判定"必须由我们确定性判定，不能外包给第三方库**。
    _arr = np.asarray(data, dtype=float)
    if not np.all(np.isfinite(_arr)):
        # 含 NaN/±Inf：样本不是有效观测，S-W 统计量无从谈起
        return float("nan")
    _max_abs = float(np.max(np.abs(_arr))) if _arr.size else 0.0
    if np.isfinite(_max_abs) and _max_abs > 0 and np.log10(_max_abs) > 154:
        # Σy² 在 float64 下必然溢出（1e154² = 1e308 ≈ 上界）⇒ 统计量不可计算。
        # 该判据只依赖浮点表示范围，**与环境无关**（见 boundary-contract #21 同源理由）。
        return float("nan")
    # 退化输入（n<3 等）会让 scipy 内部发 `invalid value encountered` /
    # `overflow encountered` RuntimeWarning 并返回 NaN。
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
    except (ValueError, TypeError, OverflowError):
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


def _is_micro_scale(scale: float, decimals: int) -> bool:
    """微尺度判据 —— `round_for_display` 与 `disp` 的**唯一**阈值来源。

    固定 `decimals` 位小数会把量级低于 `0.5×10^-decimals` 的值整组吞成 `0.0000`。
    本函数只回答"这个量级需要改走有效数字（科学计数）吗"，两个格式化入口共用它，
    使阈值只在一处定义（避免"同一判据两处各写一份必然漂移"，见审查 P2-3）。
    """
    return scale != 0.0 and scale < 0.5 * 10.0 ** (-decimals)


def disp(value, decimals: int = 4) -> str:
    """量纲感知的**展示格式化**（summary / 图内文本 / 预格式化单元格的唯一实现）。

    为什么需要（审查 2026-10-09 R2BD-06 / C-1）：展示层原本是**双通道** ——
    数值列经 `round_for_display` 走尺度感知，而 `summary` 拼接、图例/标题文案、
    以及"先格式化成字符串再放进表"的单元格走 `f"{x:.4f}"` 手写定点格式，
    于是微尺度（ppm/ppb、nm 级厚度、微应变）下这些通道被整段吞成 `0.0000`：
    实测 ×1e-9 时 `spc_xbar` 摘要为 `CL=0.0000, UCL=0.0000, LCL=0.0000`，
    而**同一结果**的 `control_limits` 表却写着 `1.004000e-08` —— 两套口径自相矛盾。

    口径（与 `round_for_display` 同源，见 `_is_micro_scale`）：

    - 常规量级（`|x| ≥ 0.5×10^-decimals`）→ `f"{x:.{decimals}f}"`，与此前逐字一致；
    - 微尺度 → `f"{x:.{decimals}g}"`（`decimals` 位**有效数字**，自动科学计数）；
    - 显式零 → 常规分支（`0.0000` 是真值 0 的正确显示，不改）；
    - `NaN` → `"N/A"`（无法判定，见哨兵契约 L2）；`±Inf` → `"+∞"` / `"-∞"`。

    Args:
        value: 标量（数值或可转 float 的对象）
        decimals: 常规量级的小数位（同时也是微尺度分支的有效数字位数）

    Returns:
        展示用字符串。**调用方不得再对其做二次舍入或再套 `:.Nf`。**
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(x):
        return "N/A"
    if np.isinf(x):
        return "+∞" if x > 0 else "-∞"
    if _is_micro_scale(abs(x), decimals):
        return f"{x:.{decimals}g}"
    return f"{x:.{decimals}f}"


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

    ⚠️ 本函数只处理**数值列**；`summary` 拼接、图内文本与预格式化字符串单元格
    走同源的 `disp()`（同一 `_is_micro_scale` 阈值）。两者是一对，勿单独改其一。
    """
    scalar_input = np.isscalar(values)
    arr = np.atleast_1d(np.asarray(values, dtype=float))
    finite = arr[np.isfinite(arr)]
    scale = float(np.max(np.abs(finite))) if finite.size else 0.0
    if not _is_micro_scale(scale, decimals):
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
