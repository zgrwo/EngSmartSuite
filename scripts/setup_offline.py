"""SmartSuite 离线安装脚本（跨平台逻辑入口）。

所有界面文字均在此处（UTF-8）；setup_offline.bat / setup_offline.sh
只是纯 ASCII 启动器，全部逻辑由此脚本承担。

用法:
  setup_offline.bat                        - 交互式菜单（双击运行）
  setup_offline.bat download               - 下载当前平台依赖到 packages/
  setup_offline.bat download --py 312      - 下载指定 Python 版本（3 位数字）
  setup_offline.bat download 312 win_amd64 - 指定 Python + 平台（跨平台下载）
  setup_offline.bat install                - 从本地 packages/ 一键离线安装
  setup_offline.bat install-reqs           - 从 packages/requirements.txt 离线安装
  setup_offline.bat clean                  - 删除 packages/ 重新下载
  setup_offline.bat --print-cmd ...        - 只打印将执行的命令，不实际执行

macOS / Linux 将 setup_offline.bat 换成 setup_offline.sh。
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import common

USAGE = """SmartSuite 离线安装脚本

用法:
  setup_offline.bat                        - 交互式菜单（双击运行）
  setup_offline.bat download               - 下载当前平台依赖到 packages/
  setup_offline.bat download --py 312      - 下载指定 Python 版本（3 位数字）
  setup_offline.bat download 312 win_amd64 - 指定 Python + 平台（跨平台下载）
  setup_offline.bat install                - 从本地 packages/ 一键离线安装
  setup_offline.bat install-reqs           - 从 packages/requirements.txt 离线安装
  setup_offline.bat clean                  - 删除 packages/ 重新下载
  setup_offline.bat --print-cmd ...        - 只打印将执行的命令，不实际执行

macOS / Linux 将 setup_offline.bat 换成 setup_offline.sh。
"""

# 与 pyproject.toml [build-system] 保持一致的下限（>=83.0 修 PYSEC-2026-3447）
_BUILD_DEPS = ("setuptools>=83.0", "wheel")
_RUNTIME_EXTRAS = ".[all,dev]"  # all = web + report，dev = 目标机开发工具
_RUNTIME_SPEC = "smartsuite[all,dev]"
_MIN_PY = (3, 10)
_PY_RE = re.compile(r"3[0-9]{2}")

# 菜单 [2]-[4]：目标 (python_version, platform)
_MENU_TARGETS = {
    "2": ("312", "win_amd64"),
    "3": ("311", "win_amd64"),
    "4": ("310", "win_amd64"),
}


def clear_screen() -> None:
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)


def ask_yes_no(prompt) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, OSError):
        return False
    return ans in ("y", "yes")


def fail_box(title, *hints) -> None:
    print()
    print("=" * 50)
    print(f" [错误] {title}")
    print("=" * 50)
    for hint in hints:
        print(f"   {hint}")
    print()


def run_or_print(cmd, cwd, print_cmd) -> int:
    """执行命令；print_cmd 模式下只打印将执行的命令（返回 0）。"""
    if print_cmd:
        print("  将执行:")
        print("   " + " ".join(str(a) for a in cmd))
        return 0
    return common.run(cmd, cwd=cwd)


def label_py(target_py: str) -> str:
    return f"{target_py[0]}.{target_py[1:]}"


def validate_py(text: str) -> str:
    text = text.strip()
    if not _PY_RE.fullmatch(text):
        raise ValueError(f"无效的 Python 版本: {text!r}（应为 3 位数字，如 312）")
    return text


def parse_download_args(args):
    """把 download 的剩余参数解析为 (target_py, platform)。

    支持: 空 / --py 312 / --py 312 win_amd64 / 312 / 312 win_amd64
    """
    target_py = None
    platform = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--py":
            i += 1
            if i >= len(args):
                raise ValueError("--py 需要一个版本参数（如 312）")
            target_py = args[i]
        elif a == "--platform":
            i += 1
            if i >= len(args):
                raise ValueError("--platform 需要一个平台参数（如 win_amd64）")
            platform = args[i]
        else:
            positional.append(a)
        i += 1
    if positional:
        if target_py is None:
            target_py = positional.pop(0)
        if positional:
            if platform is not None:
                raise ValueError(f"多余的参数: {positional}")
            platform = positional.pop(0)
        if positional:
            raise ValueError(f"多余的参数: {positional}")
    if target_py is not None:
        target_py = validate_py(target_py)
    if target_py is None and platform is not None:
        raise ValueError("指定平台时必须同时指定 Python 版本（如 download 312 win_amd64）")
    return target_py, platform


def target_info(target_py, platform):
    """返回 (显示标签, pip download 平台参数列表)。"""
    if target_py is None:
        return "当前平台", []
    args = [
        "--python-version",
        target_py,
        "--implementation",
        "cp",
        "--abi",
        f"cp{target_py}",
        "--only-binary=:all:",
    ]
    if platform:
        args = ["--platform", platform] + args
        label = f"{platform} + Python {label_py(target_py)}"
    else:
        label = f"当前系统 + Python {label_py(target_py)}"
    return label, args


def download_commands(packages, platform_args):
    return [
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            *_BUILD_DEPS,
            "-d",
            str(packages),
            *platform_args,
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            _RUNTIME_EXTRAS,
            "-d",
            str(packages),
            *platform_args,
        ],
        [sys.executable, str(common.scripts_dir() / "gen_requirements.py"), str(packages)],
    ]


def do_download(argv, print_cmd, confirm=False) -> int:
    try:
        target_py, platform = parse_download_args(argv)
    except ValueError as e:
        print(f"[错误] {e}")
        print()
        print(USAGE)
        return 1

    label, platform_args = target_info(target_py, platform)
    root = common.project_root()
    packages = common.packages_dir()

    print(f"下载依赖 — {label}")
    print("=" * 50)
    print()
    if target_py:
        print(f"  目标 Python: {label_py(target_py)} (cp{target_py})")
        print(f"  目标平台:   {platform or '当前系统'}")
        print("  下载格式:    仅 wheel (目标机器无需编译器)")
        print()
        print("  离线安装时，目标机器 Python 版本必须精确匹配。")
        print()
    else:
        best = common.find_python()
        if best:
            print(f"  {best[1]}")
        else:
            print("  [警告] 未检测到 Python，下载可能失败")
        print("  将下载适配本机的 wheel 文件；生成的 packages/")
        print("  仅能在与本机相同 OS 和 Python 版本的机器上安装。")
        print("  如需给其他机器使用，请用: download --py <版本> <平台>")
        print()

    if packages.exists() and any(packages.iterdir()):
        n = len(list(packages.glob("*.whl")))
        print(f"  [警告] packages/ 已存在 {n} 个 wheel，将追加下载")
        print("         如需全新下载，请先执行: setup_offline clean")
        print()

    if confirm and not ask_yes_no("确认下载？[Y/N]: "):
        print("已取消")
        return 1

    cmds = download_commands(packages, platform_args)

    print("[1/4] 准备 packages 目录...")
    if print_cmd:
        print("  将创建目录: " + str(packages))
    else:
        packages.mkdir(parents=True, exist_ok=True)

    print("[2/4] 下载构建依赖 (setuptools, wheel)...")
    if run_or_print(cmds[0], root, print_cmd) != 0:
        fail_box(
            "构建依赖下载失败",
            "可能原因: 网络不通 / PyPI 不可达 / pip 版本过旧",
            "请检查网络后重试",
        )
        return 1

    print("[3/4] 下载全部运行时依赖 (核心 + Web + 报告 + 开发)...")
    if run_or_print(cmds[1], root, print_cmd) != 0:
        fail_box(
            "运行时依赖下载失败",
            "可能原因: 部分包无对应平台的 wheel 文件 / 网络问题",
            "请尝试其他 Python 版本或检查网络",
        )
        return 1

    print("[4/4] 生成 requirements.txt...")
    if run_or_print(cmds[2], root, print_cmd) != 0:
        print("  [警告] requirements.txt 生成失败，[R] 安装方式将不可用")

    print()
    print("=" * 50)
    print(" 下载完成！")
    print("=" * 50)
    print(f" 目标: {label}")
    print()
    print(" 下一步:")
    print("  1. 将整个项目文件夹复制到 U 盘/共享目录")
    print("  2. 在目标机器上运行 setup_offline.bat，选 [I] 一键安装")
    print()
    print(" 已下载文件:")
    for f in sorted(packages.glob("*.whl")):
        print(f"   {f.name}")
    print()
    print(" 如需精确版本锁定: python scripts/gen_requirements.py packages")
    print("=" * 50)
    return 0


def install_commands(root, packages):
    return [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            f"--find-links={packages}",
            "setuptools",
            "wheel",
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "-e",
            str(root),
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            f"--find-links={packages}",
            "--no-build-isolation",
            _RUNTIME_SPEC,
        ],
    ]


def install_reqs_commands(root, packages):
    return [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            f"--find-links={packages}",
            "setuptools",
            "wheel",
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            f"--find-links={packages}",
            "-r",
            str(packages / "requirements.txt"),
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "-e",
            str(root),
        ],
    ]


def verify_command():
    code = common.IMPORT_CHECK + "print('  [OK] smartsuite 及 Web/报告依赖导入成功')"
    return [sys.executable, "-c", code]


def _completion_box() -> None:
    print()
    print("=" * 50)
    print(" 安装完成！")
    print("=" * 50)
    print(" 启动 Web UI:   python run_server.py")
    print(" 或双击 run_smartsuite.bat 一键启动")
    print("=" * 50)


def do_install(print_cmd) -> int:
    root = common.project_root()
    packages = common.packages_dir()

    if not packages.exists() or not any(packages.iterdir()):
        fail_box(
            "packages/ 文件夹不存在",
            "请先在有网机器上运行: setup_offline.bat download",
            "然后将整个项目文件夹复制到本机再安装",
        )
        return 1

    print("离线安装 — 一键安装")
    print("=" * 50)
    print()

    cmds = install_commands(root, packages)
    steps = [
        (0, "安装构建依赖 (setuptools, wheel)"),
        (1, "安装 smartsuite 本身 (可编辑, 不装依赖)"),
        (2, "安装全部运行时依赖"),
    ]
    for idx, title in steps:
        print(f"[{idx + 1}/3] {title}...")
        if run_or_print(cmds[idx], root, print_cmd) != 0:
            fail_box(
                "运行时依赖安装失败",
                "可能原因: Python 版本与下载时不匹配",
                f"当前 Python: {sys.version.split()[0]}",
                "请确认 packages/ 中的 wheel 与当前 Python 兼容。",
                "如版本不匹配，请回到有网机器重新下载对应版本。",
            )
            return 1

    print()
    print("[验证] 导入 smartsuite 及 Web/报告依赖...")
    if run_or_print(verify_command(), root, print_cmd) != 0:
        print("  [警告] 导入验证失败，请检查依赖是否完整")
    else:
        print("  [OK] smartsuite 及 Web/报告依赖可用")
    _completion_box()
    return 0


def do_install_reqs(print_cmd) -> int:
    root = common.project_root()
    packages = common.packages_dir()
    reqs = packages / "requirements.txt"

    if not reqs.exists():
        fail_box(
            "packages/requirements.txt 不存在",
            "请先在有网机器上运行: setup_offline.bat download",
            "需要 Python 环境以生成 requirements.txt",
        )
        return 1

    print("离线安装 — requirements.txt 方式")
    print("=" * 50)
    print()

    cmds = install_reqs_commands(root, packages)
    steps = [
        (0, "安装构建依赖 (setuptools, wheel)"),
        (1, "从 requirements.txt 安装全部依赖"),
        (2, "安装 smartsuite 本身 (可编辑)"),
    ]
    for idx, title in steps:
        print(f"[{idx + 1}/3] {title}...")
        if run_or_print(cmds[idx], root, print_cmd) != 0:
            fail_box(
                "依赖安装失败",
                "可能原因: Python 版本与下载时不匹配",
                f"当前 Python: {sys.version.split()[0]}",
                "请确认 packages/ 中的 wheel 与当前 Python 兼容。",
            )
            return 1

    _completion_box()
    return 0


def do_clean(print_cmd) -> int:
    packages = common.packages_dir()
    if not packages.exists():
        print("packages/ 不存在，无需清理")
        return 0
    print("删除 packages/ 目录")
    print("=" * 50)
    print()
    print("将删除所有已下载的依赖文件。")
    if not ask_yes_no("确认删除？[Y/N]: "):
        print("已取消")
        return 0
    if print_cmd:
        print(f"  (dry-run) 将删除目录: {packages}")
        return 0
    shutil.rmtree(packages)
    print("已删除 packages/")
    return 0


def print_menu() -> None:
    common.banner(["SmartSuite 离线安装工具"])
    print("  ★ 下载依赖（在有网机器上操作）")
    print("  ──────────────────────────────────")
    print("  [1] 当前平台")
    print("  [2] Windows x64 + Python 3.12")
    print("  [3] Windows x64 + Python 3.11")
    print("  [4] Windows x64 + Python 3.10")
    print("  [5] 自定义 Python 版本")
    print()
    print("  ★ 离线安装（在无网目标机器上操作）")
    print("  ──────────────────────────────────")
    print("  [I] 一键安装 (推荐)")
    print("  [R] requirements.txt 方式安装")
    print("  [D] 删除 packages/ 重新下载")
    print("  ──────────────────────────────────")
    print("  [Q] 退出")
    print()
    best = common.find_python()
    if best:
        print(f"  当前机器: {best[1]}")
    else:
        print("  当前机器: Python 未检测到")
    packages = common.packages_dir()
    if packages.exists():
        n = len(list(packages.glob("*.whl")))
        print(f"  已下载: packages/ 含 {n} 个 wheel 文件")
    else:
        print("  已下载: packages/ 不存在 (需先下载)")
    print()


def menu_custom_download(print_cmd) -> int:
    while True:
        text = input("目标 Python 版本（3 位数字，如 312，直接回车取消）: ").strip()
        if not text:
            return 1
        try:
            target_py = validate_py(text)
        except ValueError as e:
            print(f"  [错误] {e}")
            continue
        break
    platform = input("目标平台（留空=当前系统，win_amd64=Windows x64）: ").strip() or None
    argv = [target_py] + ([platform] if platform else [])
    return do_download(argv, print_cmd, confirm=True)


def run_menu(print_cmd) -> int:
    while True:
        clear_screen()
        common.set_console_title("SmartSuite 离线安装工具")
        print_menu()
        choice = input("请按键选择: ").strip().lower()
        if choice == "q":
            return 0
        # 每个动作独立一屏（模拟原 .bat 的 cls）
        clear_screen()
        if choice == "1":
            do_download([], print_cmd, confirm=True)
        elif choice in _MENU_TARGETS:
            target_py, platform = _MENU_TARGETS[choice]
            do_download([target_py, platform], print_cmd, confirm=True)
        elif choice == "5":
            menu_custom_download(print_cmd)
        elif choice in ("i", "install"):
            do_install(print_cmd)
        elif choice in ("r", "reqs", "requirements"):
            do_install_reqs(print_cmd)
        elif choice in ("d", "clean"):
            do_clean(print_cmd)
        else:
            continue
        common.pause()


def main(argv) -> int:
    common.reconfigure_utf8()
    common.set_console_title("SmartSuite 离线安装工具")

    if argv and argv[0] in ("-h", "--help", "help", "usage"):
        print(USAGE)
        return 0

    print_cmd = "--print-cmd" in argv
    args = [a for a in argv if not a.startswith("--")]

    # 引导阶段解释器可能 <3.10，重执行到最佳版本
    if sys.version_info < _MIN_PY:
        best = common.find_python()
        if best is None:
            print("[错误] 未找到 Python 3.10+，请先安装。")
            common.pause()
            return 1
        return subprocess.run([best[0], str(Path(__file__).resolve()), *argv]).returncode

    if not args:
        return run_menu(print_cmd)

    action = args[0]
    if action == "download":
        return do_download(args[1:], print_cmd)
    if action == "install":
        return do_install(print_cmd)
    if action == "install-reqs":
        return do_install_reqs(print_cmd)
    if action == "clean":
        return do_clean(print_cmd)
    print(f"[错误] 未知命令: {action}")
    print()
    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
