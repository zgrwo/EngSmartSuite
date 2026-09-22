"""分析引擎层 — 纯 Python 统计分析函数，零 Excel 依赖。"""

# ── matplotlib.use() 必须在第一次 import matplotlib 之前调用 ──
import matplotlib as _mpl

_mpl.use("Agg")
matplotlib = _mpl  # 向后兼容别名

# 注：核心依赖检查已在 smartsuite/__init__.py:86 统一执行，此处不再重复调用

import logging
import os
import platform
from importlib import import_module

import matplotlib.font_manager as _fm  # noqa: E402 — 显式导入，供字体加载使用

_logger = logging.getLogger(__name__)


# ── 跨平台中文字体加载 ──
# Windows: 先尝试环境变量 SystemRoot/WINDIR，再查注册表，最后用 C:/Windows 回退
def _get_windows_font_dir() -> str:
    sysroot = os.environ.get("SystemRoot", os.environ.get("WINDIR", ""))
    if sysroot and os.path.isdir(f"{sysroot}/Fonts"):
        return sysroot
    # 注册表查询（支持非标安装路径，如 D:\Windows）
    try:  # pragma: no cover — 平台分支：Windows+SystemRoot 生效或 Linux winreg ImportError，单平台运行不可双覆盖
        import winreg as _wr

        with _wr.OpenKey(
            _wr.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        ) as key:
            sysroot = _wr.QueryValueEx(key, "SystemRoot")[0]
        if os.path.isdir(f"{sysroot}/Fonts"):
            return sysroot
    except (OSError, RuntimeError, ImportError):  # pragma: no cover — 与上方 try 同因（平台互斥）
        pass
    return "C:/Windows"  # 最终回退  # pragma: no cover — 与上方 try 同因（平台互斥）


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
        ("/snap/current/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        # 用户字体目录
        (os.path.expanduser("~/.fonts/NotoSansCJK-Regular.ttc"), "Noto Sans CJK SC"),
        (os.path.expanduser("~/.local/share/fonts/NotoSansCJK-Regular.ttc"), "Noto Sans CJK SC"),
    ],
}

_font_loaded = False
_env_font = os.environ.get("MATPLOTLIB_FONT_PATH")

# 环境变量字体（跨平台通用）
if _env_font and os.path.exists(_env_font):
    try:
        _fm.fontManager.addfont(_env_font)  # matplotlib API 无返回值（注册即生效）
        # 审查 2026-09-19 C-1：族名取 FontProperties.get_name()（如 DejaVuSans.ttf →
        # "DejaVu Sans"），文件名 stem 与注册族名常不一致会导致 findfont 静默回退默认字体
        try:
            _env_family = _fm.FontProperties(fname=_env_font).get_name()
        except Exception as e:
            # 审查 2026-09-22 发现 10：except Exception 必须记录日志（红线），
            # 行为安全（确定性回退文件名 stem），按 debug 记录
            _logger.debug("字体族名解析失败，回退文件名: %s", e)
            _env_family = os.path.splitext(os.path.basename(_env_font))[0]
        # 仅当用户未自定义 font.family 时才覆盖（保护用户配置）
        if "font.family" not in matplotlib.rcParams or matplotlib.rcParams["font.family"] == [
            "sans-serif"
        ]:
            matplotlib.rcParams["font.family"] = _env_family
        _font_loaded = True
    except Exception as e:
        _logger.debug("环境变量字体 %s 加载失败: %s", _env_font, e)

# 平台字体
if not _font_loaded:
    system = platform.system()
    for font_path, family in _FONT_CANDIDATES.get(system, []):
        if os.path.exists(font_path):
            try:
                _fm.fontManager.addfont(font_path)
                if "font.family" not in matplotlib.rcParams or matplotlib.rcParams[
                    "font.family"
                ] == ["sans-serif"]:
                    matplotlib.rcParams["font.family"] = family
                _font_loaded = True
                break
            except Exception as e:  # pragma: no cover — 防御分支：addfont 失败（字体损坏/权限）
                _logger.debug("平台字体 %s (%s) 加载失败: %s", font_path, family, e)
                continue

if not _font_loaded:  # pragma: no cover — 无系统字体环境才进入（findfont 回退链）
    # 回退: 尝试使用 matplotlib 字体查找机制（保护用户已有配置）
    _fallback_fonts = [
        "SimHei",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    # 仅当未自定义时才设置回退链
    if matplotlib.rcParams.get("font.sans-serif", ["sans-serif"]) == ["sans-serif"]:
        matplotlib.rcParams["font.sans-serif"] = _fallback_fonts
    # 尝试为每个 fallback 字体查找并注册字体文件
    # 匹配成功才注册并标记加载成功（findfont 默认 fallback_to_default=True，
    # 需比对返回路径排除默认 DejaVu 回退）
    for _fb in _fallback_fonts:
        try:
            _fb_path = _fm.findfont(_fb)
            if _fb_path and os.path.exists(_fb_path) and "DejaVu" not in _fb_path:
                _fm.fontManager.addfont(_fb_path)
                # 仅当用户未自定义 font.family 时才覆盖（保护用户配置，与上方两分支一致）
                if "font.family" not in matplotlib.rcParams or matplotlib.rcParams[
                    "font.family"
                ] == ["sans-serif"]:
                    matplotlib.rcParams["font.family"] = _fb
                _font_loaded = True
                break
        except (OSError, RuntimeError, ValueError):
            pass
if not _font_loaded:  # pragma: no cover — 完全无中文字体环境才触发（告警分支）
    _logger.warning(
        "未检测到中文字体，图表中文可能无法正常显示。"
        "Windows: 安装微软雅黑; Mac: 使用 PingFang SC; "
        "Linux: apt install fonts-noto-cjk 或设置 MATPLOTLIB_FONT_PATH 环境变量"
    )

matplotlib.rcParams["axes.unicode_minus"] = False

# ── 统一可视化样式 ──
from smartsuite.core.constants import GROUP_COLORS  # noqa: F401 — 公开导出（定义已下沉 core，避免此处拉起引擎）
from smartsuite.engine._palette import PALETTE  # noqa: F401 — 公开导出，供 services 层使用
from smartsuite.engine._palette import _to_argb  # noqa: F401 — 公开导出，供 services 层使用
from smartsuite.engine._constants import (
    CLIFFS_DELTA_LARGE,  # noqa: F401 — 公开导出
    CLIFFS_DELTA_MEDIUM,  # noqa: F401
    CLIFFS_DELTA_SMALL,  # noqa: F401
    CORRELATION_LARGE,  # noqa: F401
    CORRELATION_MEDIUM,  # noqa: F401
    CORRELATION_SMALL,  # noqa: F401
    CRAMERS_V_LARGE,  # noqa: F401
    CRAMERS_V_MEDIUM,  # noqa: F401
    CRAMERS_V_SMALL,  # noqa: F401
)
from smartsuite.engine._constants import CPK_GOOD, CPK_MINIMUM, DW_SAFE_LOWER, DW_SAFE_UPPER  # noqa: F401 — 公开导出
from smartsuite.engine._palette import get_palette_style

# 审查 2026-09-21 R1-10：展示含入口径是 Web/HTML/CLI 共用的引擎能力，属**公开面**。
# 此前 services/bridge.py 直连私有模块 engine._utils 取用，使上层依赖内部实现
# （符号改名/搬移会静默破坏分层契约）；改为从包名公开导出，bridge 再桥接。
from smartsuite.engine._utils import round_for_display  # noqa: F401 — 公开导出，供 services 层桥接

_palette_style = get_palette_style()
for key, val in _palette_style.items():
    matplotlib.rcParams[key] = val

# ── 分析函数惰性导出（审查 2026-09-19 B2 第③层）──
# 此前 4 个 try/except 在导入期急切拉入 42 个分析函数（连带 sklearn/statsmodels/
# scipy，实测 doe_opt 单块 0.71s），使任何触碰 engine 的路径都付满额启动成本。
# 改为 PEP 562 模块级 __getattr__：按名解析、只加载命中所在子包、结果写回 globals 缓存。
# 保留原有的中文 ImportError 提示（依赖缺失时的友好文案）。
_LAZY_SUBPACKAGES: tuple[str, ...] = (
    "smartsuite.engine.doe_opt",
    "smartsuite.engine.root_cause",
    "smartsuite.engine.spc_monitor",
    "smartsuite.engine.inverse",
)


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    for package in _LAZY_SUBPACKAGES:
        try:
            module = import_module(package)
        except ImportError as e:  # pragma: no cover — 核心依赖缺失才触发的防御分支
            raise ImportError(
                f"SmartSuite 引擎初始化失败 ({package.rsplit('.', 1)[-1]}): {e}；"
                "请确保已安装所有核心依赖：pip install smartsuite"
            ) from e
        if hasattr(module, name):
            attr = getattr(module, name)
            globals()[name] = attr  # 缓存：后续访问不再进 __getattr__
            return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CPK_GOOD",
    "CPK_MINIMUM",
    "DW_SAFE_LOWER",
    "DW_SAFE_UPPER",  # 公开统计常量
    "GROUP_COLORS",
    "PALETTE",  # 公开配色常量/工具，供 services/web 层使用
    "round_for_display",  # 公开展示含入口径（量纲感知），供 services 层桥接
    "correlation_analysis",
    "anova_analysis",
    "contingency_analysis",
    "cohens_kappa",
    "cronbach_alpha",
    "hypothesis_test",
    "decision_tree_analysis",
    "vif_analysis",
    "power_analysis",
    "normality_check",
    "distribution_summary",
    "proportion_ci",
    "variance_test",
    "regression_analysis",
    "response_surface_analysis",
    "grid_search",
    "multi_objective_opt",
    "inverse_parameter_solve",
    "doe_analysis",
    "doe_design",
    "roc_analysis",
    "logistic_regression",
    "lasso_regression",
    "robust_regression",
    "quantile_regression",
    "xbar_r_chart",
    "attribute_chart",
    "cusum_chart",
    "ewma_chart",
    "change_point_detect",
    "process_capability_analysis",
    "trend_forecast",
    "anomaly_detect",
    "outlier_consensus",
    "bootstrap_ci",
    "box_chart",
    "gage_rr",
    "tolerance_interval",
    "scatter_plot",
    "spc_nonparametric",
    "survival_analysis",
    "median_ci",
]
