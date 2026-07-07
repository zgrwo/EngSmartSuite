"""SmartSuite — 工艺数据分析工具箱。"""

__version__ = "0.1.0"

# ── 核心依赖映射：包名 → 安装提示 ──
_CORE_DEPS: dict[str, str] = {
    "pandas":      "pip install pandas",
    "numpy":       "pip install numpy",
    "scipy":       "pip install scipy",
    "statsmodels": "pip install statsmodels",
    "sklearn":     "pip install scikit-learn",
    "matplotlib":  "pip install matplotlib",
}

def check_core_deps():
    """检查核心依赖，缺失时抛出友好的中文 ImportError。"""
    missing: list[str] = []
    for pkg, hint in _CORE_DEPS.items():
        try:
            __import__(pkg)
        except ImportError:
            missing.append(f"  • {pkg} → {hint}")

    if missing:
        msg = (
            "SmartSuite 缺少必要的核心依赖包：\n\n"
            + "\n".join(missing)
            + "\n\n请安装缺失的包后重试。\n"
            "一键安装全部核心依赖：pip install smartsuite"
        )
        raise ImportError(msg)


# ── 包导入时立即检查核心依赖 ──
# 必须在任何子模块导入之前执行，确保无论从 engine/ 还是 services/ 入口，
# 都能得到友好的中文错误提示而非原始 ModuleNotFoundError。
check_core_deps()
