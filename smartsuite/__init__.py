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

# ── 可选依赖映射：包名 → (extras 名称, 安装提示) ──
_OPTIONAL_DEPS: dict[str, tuple[str, str]] = {
    "flask":       ("web",    "pip install smartsuite[web]"),
    "pptx":        ("report", "pip install smartsuite[report]"),
    "reportlab":   ("report", "pip install smartsuite[report]"),
    "pyarrow":     ("web",    "pip install smartsuite[web]"),
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


def check_optional_dep(pkg: str) -> None:
    """检查单个可选依赖，缺失时给出明确的安装提示。

    用于延迟检查仅在特定功能路径上才需要的包（如 Flask），
    避免在不需要该功能的用户那里触发不必要的安装。
    """
    if pkg not in _OPTIONAL_DEPS:
        return
    try:
        __import__(pkg)
    except ImportError:
        extra, hint = _OPTIONAL_DEPS[pkg]
        raise ImportError(
            f"此功能需要「{pkg}」包，但它未安装。\n"
            f"请运行：{hint}\n"
            f"（{pkg} 属于 [{extra}] 可选依赖组）"
        ) from None
