"""SmartSuite Web UI 启动脚本 — 由 run_smartsuite.bat / run_smartsuite.sh 调用。

单独运行时也可直接双击此文件启动。
"""
import os
import sys
import webbrowser

# 确保项目根目录在 sys.path 中
_project_dir = os.path.dirname(os.path.abspath(__file__))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from smartsuite.web.app import main

if __name__ == "__main__":
    host = os.environ.get("SMARTSUITE_HOST", "127.0.0.1")
    port = int(os.environ.get("SMARTSUITE_PORT", "5050"))

    print(f"\n  SmartSuite Web UI 启动中...")
    print(f"  地址: http://{host}:{port}")
    print(f"  按 Ctrl+C 停止\n")

    # 1 秒后自动打开浏览器（仅在未设置 NO_BROWSER 环境变量时）
    if not os.environ.get("SMARTSUITE_NO_BROWSER"):
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    main(host=host, port=port, debug=False)
