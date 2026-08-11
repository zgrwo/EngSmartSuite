"""SmartSuite 一键启动脚本（跨平台逻辑入口）。

双击运行即可: 自动检测 Python → 安装依赖（离线优先）→ 启动 Web UI。
run_smartsuite.bat / run_smartsuite.sh 只是纯 ASCII 启动器，
全部逻辑由此脚本承担。

离线模式: 若检测到 packages/ 目录（由 setup_offline download 生成），
优先使用本地 wheel 离线安装，无需联网。
"""

import os
import subprocess
import sys
from pathlib import Path

import common

_VENV_DIR = ".venv-smartsuite"
_MIN_PY = (3, 10)


def venv_python(root) -> Path:
    """虚拟环境 Python 解释器路径（按平台选择目录结构）。"""
    return root / _VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_python():
    """返回 (python_exe, version_text)；找不到 >=3.10 时打印提示并返回 None。"""
    best = common.find_python()
    if best is None:
        print("  [X] 未找到 Python 3.10+")
        print()
        print("      请从 https://www.python.org/downloads/ 下载安装 Python 3.10+")
        print('      安装时请勾选 "Add Python to PATH" 选项')
        print("      如已安装但未被检测到，请将 Python 加入系统 PATH 后重试")
        common.pause()
        return None
    return best


def ensure_venv(root, py_exe) -> Path:
    """确保 .venv-smartsuite 存在，返回其 Python 解释器路径。"""
    venv_py = venv_python(root)
    if not venv_py.exists():
        print("        首次运行，正在创建虚拟环境...")
        if common.run([py_exe, "-m", "venv", str(venv_py.parent), "--clear"]) != 0:
            print("  [X] 虚拟环境创建失败，请检查磁盘空间和权限")
            common.pause()
            sys.exit(1)
        print("  [OK] 虚拟环境创建成功")
    else:
        print("  [OK] 虚拟环境已就绪")
    return venv_py


def ensure_deps(root, run_python) -> int:
    """在虚拟环境中安装依赖（离线优先，失败回退在线）。返回退出码。"""
    if common.run_quiet([str(run_python), "-c", "import smartsuite"]):
        print("  [OK] SmartSuite 已安装")
        return 0

    packages = common.packages_dir()
    whls = list(packages.glob("*.whl")) if packages.exists() else []
    if whls:
        print(f"        检测到离线依赖包 ({len(whls)} 个 wheel)，尝试离线安装...")
        cmd = [str(run_python), "-m", "pip", "install", "--no-index",
               f"--find-links={packages}", "-e", f"{root}[web,report]", "--quiet"]
        if common.run(cmd, cwd=root) == 0 and common.run_quiet(
            [str(run_python), "-c", "import smartsuite"]
        ):
            print("  [OK] 离线安装完成")
            return 0
        print("        离线安装未完成，回退到在线安装...")
    else:
        print("        正在安装 SmartSuite 及全部依赖 (约需 2-5 分钟)...")

    cmd = [str(run_python), "-m", "pip", "install", "-e", f"{root}[all]", "--quiet"]
    if common.run(cmd, cwd=root) != 0:
        print("  [X] 安装失败，请检查网络连接后重试")
        print("      或运行 setup_offline.bat → 下载依赖 → 再启动本脚本")
        common.pause()
        return 1
    print("  [OK] 安装完成")
    return 0


def launch(root, run_python) -> int:
    print()
    print("  [启动] 启动 Web 界面...")
    print()
    common.banner([
        f"浏览器将自动打开 {common.web_url()}",
        "上传 Excel → 选列 → 点按钮 → 看结果",
        "按 Ctrl+C 或关闭此窗口停止服务",
    ])
    print()
    return common.run([str(run_python), str(root / "run_server.py")], cwd=root)


def main(argv) -> int:
    common.reconfigure_utf8()
    common.set_console_title("SmartSuite 一键启动")

    # 引导阶段解释器可能 <3.10，重执行到最佳版本
    if sys.version_info < _MIN_PY:
        best = common.find_python()
        if best is None:
            print("  [X] 未找到 Python 3.10+，请先安装。")
            common.pause()
            return 1
        return subprocess.run([best[0], str(Path(__file__).resolve()), *argv]).returncode

    root = common.project_root()

    print()
    common.banner(["SmartSuite — 工艺数据分析工具箱", "一键启动"])
    print()

    print("  [1] 检测 Python 环境...")
    best = ensure_python()
    if best is None:
        return 1
    py_exe, py_ver = best
    print(f"  [OK] 找到 {py_ver}")

    print("  [2] 检测 SmartSuite...")
    if common.run_quiet([py_exe, "-c", "import smartsuite"]):
        print("  [OK] SmartSuite 已安装，跳过虚拟环境")
        run_python = py_exe
    else:
        print("  [ ] 未检测到全局安装，创建独立虚拟环境...")
        run_python = ensure_venv(root, py_exe)
        print("  [3] 安装依赖...")
        if ensure_deps(root, run_python) != 0:
            return 1

    rc = launch(root, run_python)
    print()
    print("  SmartSuite 已停止。")
    common.pause()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
