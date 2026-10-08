"""SmartSuite — 工艺数据分析工具箱。"""

import importlib.util
import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from typing import Any, cast

__version__ = "1.5.0"


LOG_DIR_ENV = "SMARTSUITE_LOG_DIR"
"""覆盖日志目录的环境变量名（运维/容器/测试显式指定）。"""


def _default_log_dir() -> str:
    """解析默认日志目录 —— **绝不落在包安装目录内**。

    契约：docs/governance/boundary-contract.md（B0/B1）

    审查 2026-09-24（第三轮复核 P1-7）：原实现为

        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")

    源码检出（src 布局）下解析到仓库根 `logs/`，正确。但 **wheel/site-packages 安装**
    后 `dirname(__file__)` 是 `.../site-packages/smartsuite`，该路径变成
    `.../site-packages/logs`，产生两类后果：

      1. 可写时污染 Python 的 site-packages（卸载包不会清理）；
      2. 不可写时静默降级到系统临时目录，用户找不到日志也不知该去哪找。

    新优先级：
      1. `SMARTSUITE_LOG_DIR` 环境变量（相对路径按 cwd 解析）；
      2. 当前工作目录下的 `logs/` —— 与 `run_server.py` 从仓库根启动的既有行为一致，
         源码检出的开发者体验不变；
      3. 调用方无法写入时由 `setup_logging` 降级并**记日志说明落点**。
    """
    env_dir = os.environ.get(LOG_DIR_ENV)
    if env_dir and env_dir.strip():
        return os.path.abspath(os.path.normpath(env_dir.strip()))
    return os.path.abspath(os.path.join(os.getcwd(), "logs"))


def setup_logging(log_dir: str | None = None, console_level: int = logging.INFO):
    """配置双通道日志：控制台 INFO + 文件 DEBUG（自动轮转，保留最近 5 个文件）。

    Args:
        log_dir: 日志目录。缺省时按 `_default_log_dir()` 解析
            （`SMARTSUITE_LOG_DIR` 环境变量 → cwd/logs）。
        console_level: 控制台最低级别，默认 INFO

    审查 2026-08-19 Round-2：
    - 幂等守卫基于本包 handler 标记（此前任何 root.handlers 都会跳过，干扰其他包）；
    - log_dir 做 normpath 归一化；
    - 日志目录创建失败时降级到系统临时目录，仍失败则仅保留控制台日志。

    审查 2026-09-24（第三轮复核 P1-7）：默认落点由"包相对路径"改为 cwd，
    避免 wheel 安装后写入 site-packages；降级链保留但**必须记日志说明落点**，
    不再静默（用户需要知道日志实际在哪）。
    """
    if log_dir is None:
        log_dir = _default_log_dir()
    log_dir = os.path.normpath(log_dir)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 全局最低为 DEBUG，各 handler 自行过滤

    # 幂等守卫：仅当本包已添加过 handler 时跳过（不因其他包添加到 root 的 handler 而静默失败）
    if any(getattr(h, "_smartsuite_managed", False) for h in root.handlers):
        return

    # 日志文件：目录创建失败 → 降级到系统临时目录；再失败 → 仅控制台
    log_file = None
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "smartsuite.log")
    except OSError as e:
        _fallback_dir = tempfile.gettempdir()
        logging.getLogger(__name__).warning(
            "日志目录不可用 (%s: %s)，降级到系统临时目录 %s", log_dir, e, _fallback_dir
        )
        try:
            os.makedirs(_fallback_dir, exist_ok=True)
            log_file = os.path.join(_fallback_dir, "smartsuite.log")
        except OSError as e2:
            logging.getLogger(__name__).warning(
                "临时目录创建也失败 (%s)，仅使用控制台日志（本次运行不留日志文件）", e2
            )
            log_file = None

    if log_file is not None:
        # 文件 handler — DEBUG 全量，自动轮转（单文件 ≤ 1MB，保留 5 个）
        fh = RotatingFileHandler(
            log_file, maxBytes=1 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        # cast(Any)：logging.Handler 无该属性声明；幂等标记见 :33 getattr
        cast(Any, fh)._smartsuite_managed = True
        root.addHandler(fh)

    # 控制台 handler — INFO 以上，紧凑格式
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter("[%(levelname)-5s] %(name)s | %(message)s"))
    cast(Any, ch)._smartsuite_managed = True  # 同上（幂等标记，见 :33 getattr）
    root.addHandler(ch)

    logging.getLogger(__name__).info(
        "日志已配置（文件=%s, 控制台=%s）",
        log_file or "无（仅控制台）",
        logging.getLevelName(console_level),
    )


# ── 核心依赖映射：包名 → 安装提示 ──
_CORE_DEPS: dict[str, str] = {
    "pandas": "pip install pandas",
    "numpy": "pip install numpy",
    "scipy": "pip install scipy",
    "statsmodels": "pip install statsmodels",
    "sklearn": "pip install scikit-learn",
    "matplotlib": "pip install matplotlib",
}


def _module_available(pkg: str) -> bool:
    """依赖是否可用——**只探测不导入**（审查 2026-09-19 B2 第①层）。

    原实现用 `__import__` 真实导入 6 个核心依赖，使任何 `import smartsuite.*`
    （哪怕只取数据契约）都付满额启动成本（实测 sklearn 单项 0.89s、合计 ~1.5s）。

    `find_spec` 对已导入模块走 `sys.modules[name].__spec__`，个别模块该值为 None
    会抛 ValueError——此时模块已在 sys.modules 中，等价于「可用」。
    语义差异：本函数只回答「能否找到」，不回答「导入是否成功」；已安装但导入即
    失败的损坏环境不再命中友善文案，而会在首次实际使用时暴露原始错误。
    """
    if pkg in sys.modules:
        return True
    try:
        return importlib.util.find_spec(pkg) is not None
    except (ImportError, ValueError):
        return False


def check_core_deps():
    """检查核心依赖，缺失时抛出友好的中文 ImportError。"""
    missing = [
        f"  • {pkg} → {hint}" for pkg, hint in _CORE_DEPS.items() if not _module_available(pkg)
    ]

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
