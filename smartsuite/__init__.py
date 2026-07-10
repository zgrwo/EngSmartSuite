"""SmartSuite — 工艺数据分析工具箱。"""
import logging
import os
from logging.handlers import RotatingFileHandler

__version__ = "0.1.0"


def setup_logging(log_dir: str | None = None, console_level: int = logging.INFO):
    """配置双通道日志：控制台 INFO + 文件 DEBUG（自动轮转，保留最近 5 个文件）。

    Args:
        log_dir: 日志目录，默认项目根目录下的 logs/
        console_level: 控制台最低级别，默认 INFO
    """
    if log_dir is None:
        # 项目根目录相对于 __init__.py 是 ../../
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "smartsuite.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 全局最低为 DEBUG，各 handler 自行过滤

    # 避免重复添加（多次调用 setup_logging 时幂等）
    if root.handlers:
        return

    # 文件 handler — DEBUG 全量，自动轮转（单文件 ≤ 1MB，保留 5 个）
    fh = RotatingFileHandler(
        log_file, maxBytes=1 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    # 控制台 handler — INFO 以上，紧凑格式
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter(
        "[%(levelname)-5s] %(name)s | %(message)s"
    ))
    root.addHandler(ch)

    logging.getLogger(__name__).info(
        "日志已配置（文件=%s, 控制台=%s）", log_file,
        logging.getLevelName(console_level)
    )

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
