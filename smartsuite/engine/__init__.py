"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

# ── matplotlib.use() 必须在第一次 import matplotlib 之前调用 ──
import matplotlib as _mpl
_mpl.use("Agg")
matplotlib = _mpl  # 向后兼容别名

# ── 启动时自动检查核心依赖 ──
from smartsuite import check_core_deps
check_core_deps()

import logging
import os
import platform

_logger = logging.getLogger(__name__)

# ── 跨平台中文字体加载 ──
# Windows: 先尝试环境变量 SystemRoot/WINDIR，再查注册表，最后用 C:/Windows 回退
def _get_windows_font_dir() -> str:
    sysroot = os.environ.get("SystemRoot", os.environ.get("WINDIR", ""))
    if sysroot and os.path.isdir(f"{sysroot}/Fonts"):
        return sysroot
    # 注册表查询（支持非标安装路径，如 D:\Windows）
    try:
        import winreg as _wr
        with _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE,
                         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            sysroot = _wr.QueryValueEx(key, "SystemRoot")[0]
        if os.path.isdir(f"{sysroot}/Fonts"):
            return sysroot
    except (OSError, RuntimeError):
        pass
    return "C:/Windows"  # 最终回退

_WINDOWS_SYSROOT = _get_windows_font_dir()
_FONT_CANDIDATES = {
    "Windows": [
        (f"{_WINDOWS_SYSROOT}/Fonts/msyh.ttc", "Microsoft YaHei"),
        (f"{_WINDOWS_SYSROOT}/Fonts/simhei.ttf", "SimHei"),
        (f"{_WINDOWS_SYSROOT}/Fonts/msyhbd.ttf", "Microsoft YaHei"),
    ],
    "Darwin": [
        ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "Heiti SC"),
        ("/Library/Fonts/Arial Unicode.ttf", "Arial Unicode MS"),
    ],
    "Linux": [
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "Droid Sans Fallback"),
        # Flatpak / Snap 容器路径
        ("/app/share/fonts/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/snap/current/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
         "Noto Sans CJK SC"),
        # 用户字体目录
        (os.path.expanduser("~/.fonts/NotoSansCJK-Regular.ttc"), "Noto Sans CJK SC"),
        (os.path.expanduser("~/.local/share/fonts/NotoSansCJK-Regular.ttc"),
         "Noto Sans CJK SC"),
    ],
}

_font_loaded = False
_env_font = os.environ.get("MATPLOTLIB_FONT_PATH")

# 环境变量字体（跨平台通用）
if _env_font and os.path.exists(_env_font):
    try:
        _font_prop = matplotlib.font_manager.fontManager.addfont(_env_font)
        # 仅当用户未自定义 font.family 时才覆盖（保护用户配置）
        if "font.family" not in matplotlib.rcParams or \
           matplotlib.rcParams["font.family"] == ["sans-serif"]:
            if hasattr(_font_prop, "family_name") and _font_prop.family_name:
                matplotlib.rcParams["font.family"] = _font_prop.family_name
            else:
                matplotlib.rcParams["font.family"] = os.path.splitext(
                    os.path.basename(_env_font))[0]
        _font_loaded = True
    except Exception as e:
        _logger.debug("环境变量字体 %s 加载失败: %s", _env_font, e)

# 平台字体
if not _font_loaded:
    system = platform.system()
    for font_path, family in _FONT_CANDIDATES.get(system, []):
        if os.path.exists(font_path):
            try:
                matplotlib.font_manager.fontManager.addfont(font_path)
                if "font.family" not in matplotlib.rcParams or \
                   matplotlib.rcParams["font.family"] == ["sans-serif"]:
                    matplotlib.rcParams["font.family"] = family
                _font_loaded = True
                break
            except Exception as e:
                _logger.debug("平台字体 %s (%s) 加载失败: %s", font_path, family, e)
                continue

if not _font_loaded:
    # 回退: 尝试使用 matplotlib 字体查找机制（保护用户已有配置）
    _fallback_fonts = ["SimHei", "Microsoft YaHei", "PingFang SC",
                       "Noto Sans CJK SC", "DejaVu Sans"]
    # 仅当未自定义时才设置回退链
    if matplotlib.rcParams.get("font.sans-serif", ["sans-serif"]) == ["sans-serif"]:
        matplotlib.rcParams["font.sans-serif"] = _fallback_fonts
    # 尝试为每个 fallback 字体查找并注册字体文件
    # 需要显式导入 font_manager（新版 matplotlib lazy-loading 不自动暴露为属性）
    import matplotlib.font_manager as _fm  # noqa: E402
    for _fb in _fallback_fonts:
        try:
            _fb_path = _fm.findfont(_fb, fallback_to_default=False)
            if _fb_path and os.path.exists(_fb_path):
                _fm.fontManager.addfont(_fb_path)
        except (OSError, RuntimeError, ValueError):
            pass
    _logger.warning(
        "未检测到中文字体，图表中文可能无法正常显示。"
        "Windows: 安装微软雅黑; Mac: 使用 PingFang SC; "
        "Linux: apt install fonts-noto-cjk 或设置 MATPLOTLIB_FONT_PATH 环境变量"
    )

matplotlib.rcParams["axes.unicode_minus"] = False

# ── 统一可视化样式 ──
from smartsuite.engine._palette import GROUP_COLORS  # noqa: F401 — 公开导出，供 services 层使用
from smartsuite.engine._palette import PALETTE  # noqa: F401 — 公开导出，供 services 层使用
from smartsuite.engine._palette import get_palette_style

_palette_style = get_palette_style()
for key, val in _palette_style.items():
    matplotlib.rcParams[key] = val

try:
    from smartsuite.engine.doe_opt import (
        doe_analysis,
        grid_search,
        lasso_regression,
        logistic_regression,
        multi_objective_opt,
        quantile_regression,
        regression_analysis,
        response_surface_analysis,
        robust_regression,
        roc_analysis,
    )
except ImportError as e:
    raise ImportError(
        f"SmartSuite 引擎初始化失败 (doe_opt): {e}\n"
        "请确保已安装所有核心依赖：pip install smartsuite"
    ) from e

try:
    from smartsuite.engine.root_cause import (
        anova_analysis,
        cohens_kappa,
        contingency_analysis,
        correlation_analysis,
        cronbach_alpha,
        decision_tree_analysis,
        distribution_summary,
        hypothesis_test,
        normality_check,
        power_analysis,
        proportion_ci,
        variance_test,
        vif_analysis,
    )
except ImportError as e:
    raise ImportError(
        f"SmartSuite 引擎初始化失败 (root_cause): {e}\n"
        "请确保已安装所有核心依赖：pip install smartsuite"
    ) from e

try:
    from smartsuite.engine.spc_monitor import (
        anomaly_detect,
        attribute_chart,
        bootstrap_ci,
        box_chart,
        change_point_detect,
        cusum_chart,
        ewma_chart,
        gage_rr,
        median_ci,
        outlier_consensus,
        process_capability_analysis,
        spc_nonparametric,
        survival_analysis,
        tolerance_interval,
        trend_forecast,
        xbar_r_chart,
    )
except ImportError as e:
    raise ImportError(
        f"SmartSuite 引擎初始化失败 (spc_monitor): {e}\n"
        "请确保已安装所有核心依赖：pip install smartsuite"
    ) from e

__all__ = [
    "GROUP_COLORS", "PALETTE",  # 公开配色常量，供 services/web 层使用
    "correlation_analysis", "anova_analysis", "contingency_analysis",
    "cohens_kappa", "cronbach_alpha",
    "hypothesis_test",
    "decision_tree_analysis", "vif_analysis", "power_analysis", "normality_check",
    "distribution_summary",
    "proportion_ci", "variance_test",
    "regression_analysis", "response_surface_analysis", "grid_search",
    "multi_objective_opt", "doe_analysis", "roc_analysis",
    "logistic_regression", "lasso_regression",
    "robust_regression", "quantile_regression",
    "xbar_r_chart", "attribute_chart", "cusum_chart", "ewma_chart", "change_point_detect",
    "process_capability_analysis", "trend_forecast", "anomaly_detect",
    "outlier_consensus", "bootstrap_ci", "box_chart", "gage_rr", "tolerance_interval",
    "spc_nonparametric",
    "survival_analysis", "median_ci",
]
