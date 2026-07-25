"""分析方法脚手架 — 新增方法的完整模板。

用法：
    1. 复制此文件到 src/smartsuite/engine/ 并重命名
    2. 按 11 步注册链完成集成（见 CONTRIBUTING.md）
    3. 运行 python scripts/falsy_audit.py 确认零 HIGH 风险

注意：
    - 所有阈值使用 _constants.py 中的常量
    - 数值变量检查用 `if x is not None:` 而非 `if x:`
    - 效应量 + 95% CI 必须报告（APA 第 7 版）
    - summary 使用中文工艺语言
"""

import logging

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import stats as sp_stats

from smartsuite.core.contracts import AnalysisRequest, AnalysisResult
from smartsuite.engine._constants import EPSILON
from smartsuite.engine._palette import PALETTE
from smartsuite.engine._utils import safe_float as _safe_float

logger = logging.getLogger(__name__)


def new_method_analysis(req: AnalysisRequest) -> AnalysisResult:
    """【方法名称】— 一句话描述。

    适用场景：
        - 场景 1
        - 场景 2

    参数（通过 req.params）：
        alpha (float): 显著性水平，默认 0.05
        ...

    返回：
        AnalysisResult: 含 tables/figures/summary/metadata
    """
    # ── 1. 参数提取 ──
    alpha = _safe_float(req.params.get("alpha", 0.05), 0.05)
    # seed = req.params.get("random_state", 42)  # 含随机算法时取消注释

    # ── 2. 数据准备 ──
    data = req.data[req.target_col].dropna()
    if len(data) < 5:
        return AnalysisResult(
            task="new_method",
            status="error",
            messages=["有效数据不足（至少 5 个观测值）"],
        )

    # ── 3. 核心计算 ──
    n = len(data)
    mean = float(data.mean())
    std = float(data.std(ddof=1))
    # ... 你的统计计算 ...

    # ── 4. 效应量 + 95% CI (APA 第 7 版必须) ──
    effect_size = 0.0  # 替换为实际效应量
    effect_size_ci = (0.0, 0.0)  # 替换为实际 CI
    effect_label = "可忽略"  # 使用 _constants.py 阈值判断

    # ── 5. 结论（中文工艺语言）──
    if effect_size > 0:
        conclusion = "存在显著效应"
    else:
        conclusion = "未发现显著效应"

    summary = (
        f"【方法名】: {conclusion} "
        f"(效应量={effect_size:.3f}, 95%CI=[{effect_size_ci[0]:.3f}, {effect_size_ci[1]:.3f}], "
        f"{effect_label})"
    )

    # ── 6. 可视化 ──
    fig = Figure(figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.hist(data, bins=15, color=PALETTE["data"]["secondary"], edgecolor="white", alpha=0.8)
    ax.axvline(mean, color=PALETTE["data"]["primary"], linewidth=2, label=f"均值={mean:.2f}")
    ax.set_xlabel(req.target_col, fontsize=10)
    ax.set_ylabel("频数", fontsize=10)
    ax.set_title(f"【方法名】分析 (n={n})", fontsize=11)
    ax.legend(fontsize=9)
    fig.tight_layout()

    # ── 7. 结果表 ──
    result_table = pd.DataFrame({
        "统计量": ["样本量", "均值", "标准差", "效应量", "95%CI下限", "95%CI上限"],
        "值": [str(n), f"{mean:.4f}", f"{std:.4f}",
               f"{effect_size:.4f}", f"{effect_size_ci[0]:.4f}", f"{effect_size_ci[1]:.4f}"],
    })

    # ── 8. 返回 ──
    return AnalysisResult(
        task="new_method",
        tables={"results": result_table},
        figures=[fig],
        summary=summary,
        metadata={
            "n": n,
            "mean": mean,
            "std": std,
            "effect_size": effect_size,
            "effect_size_ci": effect_size_ci,
            "effect_label": effect_label,
            "alpha": alpha,
        },
    )
