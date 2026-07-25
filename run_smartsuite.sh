#!/usr/bin/env bash
# ============================================================
#  SmartSuite 一键启动脚本 (macOS / Linux)
#  双击或命令行执行: 自动检测 → 安装 → 打开浏览器 → 分析
#
#  离线模式: 若检测到 packages/ 目录（由 setup_offline.bat download 生成），
#            优先使用本地 wheel 离线安装，无需联网。
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv-smartsuite"

# ── Python 版本提取（兼容 macOS BSD grep / Linux GNU grep）──
_py_ver() {
    # 优先用 Python 自身输出（精确且跨平台），失败时回退到 grep/sed
    "$1" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || \
    "$1" --version 2>&1 | sed -nE 's/.*([0-9]+\.[0-9]+).*/\1/p' | head -1
}

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║     SmartSuite — 工艺数据分析工具箱         ║"
echo "  ║     一键启动脚本 v1.0                        ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── 1. 查找 Python 3.10+ ──
echo "  [1/4] 检测 Python 环境..."
PYTHON=""
for p in python3 python; do
    if command -v "$p" &>/dev/null; then
        ver=$(_py_ver "$p")
        [ -z "$ver" ] && continue
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$p"
            break
        fi
        if [ "$major" -ge 4 ] 2>/dev/null; then
            PYTHON="$p"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [✗] 未找到 Python 3.10+，请先安装 Python"
    echo "       macOS: brew install python@3.12"
    echo "       Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "       下载: https://www.python.org/downloads/"
    exit 1
fi
echo "  [✓] 找到 $($PYTHON --version)"

# ── 2. 创建虚拟环境 (首次) ──
echo "  [2/4] 准备虚拟环境..."
NEED_INSTALL=0
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "        首次运行，正在创建虚拟环境..."
    "$PYTHON" -m venv "$VENV_DIR" --clear
    NEED_INSTALL=1
else
    echo "  [✓] 虚拟环境已就绪"
fi

# ── 3. 安装/更新依赖 ──
echo "  [3/4] 检查依赖..."
if [ "$NEED_INSTALL" = "1" ] || ! "$VENV_DIR/bin/python" -c "import smartsuite" 2>/dev/null; then
    # 优先检测 packages/ 目录（由 setup_offline.bat download 生成）
    if ls "$PROJECT_DIR/packages/"*.whl >/dev/null 2>&1; then
        echo "        检测到离线依赖包 (packages/)，尝试离线安装..."
        if "$VENV_DIR/bin/python" -m pip install --no-index \
            --find-links="$PROJECT_DIR/packages" \
            -e "$PROJECT_DIR[web,report]" --quiet 2>/dev/null; then
            if "$VENV_DIR/bin/python" -c "import smartsuite" 2>/dev/null; then
                echo "  [✓] 离线安装完成"
            else
                echo "        离线安装不完整，回退到在线安装..."
                "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR[all]" --quiet
                echo "  [✓] 在线安装完成"
            fi
        else
            echo "        离线安装失败，回退到在线安装..."
            "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR[all]" --quiet
            echo "  [✓] 在线安装完成"
        fi
    else
        echo "        正在安装 SmartSuite 及全部依赖 (约需 2-5 分钟)..."
        "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR[all]" --quiet
        echo "  [✓] 安装完成"
    fi
else
    echo "  [✓] SmartSuite 已安装"
fi

# ── 4. 启动 Web UI ──
echo "  [4/4] 启动 Web 界面..."
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║  浏览器将自动打开 http://127.0.0.1:5050      ║"
echo "  ║  上传 Excel → 选列 → 点按钮 → 看结果         ║"
echo "  ║  按 Ctrl+C 停止服务                          ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

exec "$VENV_DIR/bin/python" "$PROJECT_DIR/run_server.py"
