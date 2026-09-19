"""SmartSuite Web UI 启动脚本 — 由 run_smartsuite.bat / run_smartsuite.sh 调用。

单独运行时也可直接双击此文件启动。
"""
import os
import sys
import webbrowser

# 确保 src/ 目录在 sys.path 中（src/ 布局）
_project_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_project_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from smartsuite.web.app import cli

if __name__ == "__main__":
    host = os.environ.get("SMARTSUITE_HOST", "127.0.0.1")
    port = int(os.environ.get("SMARTSUITE_PORT", "5050"))

    # 审查 2026-09-19 E14a：不再自行拼接启动逻辑，统一走 console 入口 cli()，
    # 避免与 smartsuite-web 出现第三份启动代码（本脚本只保留「读环境变量 +
    # 自动开浏览器」这两个自有职责）
    # 1 秒后自动打开浏览器（仅在未设置 NO_BROWSER 环境变量时）
    if not os.environ.get("SMARTSUITE_NO_BROWSER"):
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            import logging

            logging.getLogger(__name__).debug("浏览器自动打开失败", exc_info=True)

    sys.exit(cli(["--host", host, "--port", str(port)]))
