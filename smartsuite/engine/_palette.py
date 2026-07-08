"""统一可视化配色方案 — SmartSuite 工艺数据分析。

语义化色彩映射，确保所有图表配色一致，便于工艺人员快速解读。

使用方式:
    from smartsuite.engine._palette import PALETTE
    ax.bar(..., color=PALETTE["data"]["primary"])
Note: PALETTE 应在导入后视为只读常量，运行时不应对其进行修改。
"""

# 只读配色常量 — 运行时不应修改
PALETTE = {
    # ── 数据层级 ──
    "data": {
        "primary": "#2171b5",       # 深蓝 — 主数据系列、柱状图主体、趋势线
        "secondary": "#6baed6",     # 浅蓝 — 次要数据、箱线图填充、背景
        "tertiary": "#9ecae1",      # 极浅蓝 — 置信带填充、直方图
        "scatter": "#2171b5",       # 散点颜色
        "line": "#2171b5",          # 折线颜色
    },

    # ── 目标/预测 ──
    "target": {
        "primary": "#d94801",       # 深橙 — 预测值、目标值、最优标记（星号）
        "fill": "#fd8d3c",          # 浅橙 — 预测区间填充、对照箱线图
        "band": "#d94801",          # 置信/预测带 (alpha=0.2)
    },

    # ── 异常/违规/警告 ──
    "anomaly": {
        "primary": "#e31a1c",       # 红色 — 异常点标记、违规标记、失控点
        "fill": "#fb6a4a",          # 浅红 — 异常区域高亮 (alpha=0.15)
        "line": "#e31a1c",          # 异常阈值线
    },

    # ── 规格/控制/显著性 ──
    "spec": {
        "primary": "#e31a1c",       # 红色 — 规格限、控制限 (UCL/LCL)
        "secondary": "#d94801",     # 橙色 — 警告限 (±2σ)、显著性阈值
        "tertiary": "#969696",      # 灰色 — ±1σ 参考线
        "target": "#fd8d3c",        # 橙色 — 目标值线
    },

    # ── 中心/参考 ──
    "center": {
        "primary": "#238b45",       # 绿色 — 中心线 (CL)、均值线
        "secondary": "#74c476",     # 浅绿 — 参考区域
    },

    # ── 统计判断 ──
    "judge": {
        "good": "#238b45",          # 绿色 — 合格、稳定、可接受
        "warn": "#d94801",          # 橙色 — 需改进、警告
        "bad": "#e31a1c",           # 红色 — 不合格、异常
    },

    # ── 对比色（双样本、A/B 测试、Pareto 前沿）──
    "contrast": {
        "a": "#6baed6",             # 蓝 — 组 A
        "b": "#fd8d3c",             # 橙 — 组 B
        "c": "#74c476",             # 绿 — 组 C
        "d": "#9e9ac8",             # 紫 — 组 D
    },

    # ── 正负方向 ──
    "direction": {
        "positive": "#2171b5",      # 蓝色 — 正向效应/正值
        "negative": "#d94801",      # 橙色 — 负向效应/负值
        "zero": "#969696",          # 灰色 — 零线/参考线
    },

    # ── 色图 (colormap) ──
    "cmap": {
        "correlation": "RdBu_r",    # 相关性 — 红蓝 diverging
        "response": "RdYlGn",       # 响应面 — 红黄绿 (红=差, 绿=好)
        "sequential": "viridis",    # 通用 sequential
        "heatmap": "RdBu_r",        # 热力图
    },

    # ── 其他 ──
    "misc": {
        "grid": "#e0e0e0",          # 网格线
        "background": "white",      # 背景
        "edge": "#ffffff",          # 边框（直方图等）
    },
}


# ── Web UI 分组配色（与 PALETTE 主色系统一）──
GROUP_COLORS = {
    "要因筛选": "#e8f5e9",   # 浅绿 — data.primary 淡色
    "信度诊断": "#fff8e1",   # 浅黄 — judge.warn 淡色
    "建模优化": "#e3f2fd",   # 浅蓝 — data.primary 淡色
    "过程监控": "#fce4ec",   # 浅红 — anomaly 淡色
    "高级分析": "#f3e5f5",   # 浅紫 — contrast.d 淡色
}


def get_palette_style():
    """返回 matplotlib rcParams 样式字典，用于全局图表美化。"""
    return {
        "axes.edgecolor": "#cccccc",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.color": "#e0e0e0",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
