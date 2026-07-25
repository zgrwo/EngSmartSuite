#!/usr/bin/env bash
# ============================================================
# SmartSuite 离线安装脚本（macOS / Linux）
# 用法:
#   联网下载:  bash setup_offline.sh download
#   离线安装:  bash setup_offline.sh install
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGES_DIR="$SCRIPT_DIR/packages"

download_deps() {
    echo "[1/4] 创建 packages 目录..."
    mkdir -p "$PACKAGES_DIR"

    echo "[2/4] 下载构建依赖 (setuptools, wheel)..."
    echo "       这些是 pip 构建 smartsuite 包时必需的，"
    echo "       但 pip download 不会自动包含它们。"
    pip download 'setuptools>=68.0' wheel -d "$PACKAGES_DIR"

    echo "[3/4] 下载全部运行时依赖到 packages/ ..."
    echo "       含核心依赖 + web + report + dev"
    pip download '.[web,report,dev]' -d "$PACKAGES_DIR"

    echo "[4/4] 生成 requirements.txt..."
    python3 scripts/gen_requirements.py "$PACKAGES_DIR"

    echo ""
    echo "========================================"
    echo " 下载完成！文件数量:"
    ls "$PACKAGES_DIR"/*.whl 2>/dev/null | wc -l
    echo "========================================"
    echo ""
    echo "请将整个项目文件夹复制到离线机器，"
    echo "然后在离线机器上运行:"
    echo "  bash setup_offline.sh install        （原有方式，一键安装）"
    echo "  bash setup_offline.sh install-reqs   （requirements.txt 方式，标准 pip 流程）"
}

install_offline() {
    if [ ! -d "$PACKAGES_DIR" ]; then
        echo "[错误] packages/ 文件夹不存在，请先在有网机器上运行:"
        echo "       bash setup_offline.sh download"
        exit 1
    fi

    # 检查 Python
    if ! command -v python3 &>/dev/null; then
        echo "[错误] 找不到 python3，请先安装 Python >=3.10"
        exit 1
    fi

    # Step 1: 安装构建依赖（关键！）
    echo "[1/3] 安装构建依赖 (setuptools, wheel)..."
    echo "       这一步解决 'setuptools 找不到' 的错误"
    pip install --no-index --find-links="$PACKAGES_DIR" setuptools wheel

    # Step 2: 安装所有运行时依赖
    echo "[2/3] 从本地 packages/ 安装全部运行时依赖..."
    pip install --no-index --find-links="$PACKAGES_DIR" --no-build-isolation 'smartsuite[web,report,dev]'

    # Step 3: 安装 smartsuite 本身（开发模式）
    echo "[3/3] 安装 smartsuite 本身（开发模式）..."
    pip install --no-deps --no-build-isolation -e "$SCRIPT_DIR"

    echo ""
    echo "========================================"
    echo " 安装完成！"
    echo "========================================"
    echo " 验证: python3 -c 'import smartsuite; print(\"OK\")'"
}

install_reqs() {
    if [ ! -f "$PACKAGES_DIR/requirements.txt" ]; then
        echo "[错误] packages/requirements.txt 不存在，请先在有网机器上运行:"
        echo "       bash setup_offline.sh download"
        exit 1
    fi

    # 检查 Python
    if ! command -v python3 &>/dev/null; then
        echo "[错误] 找不到 python3，请先安装 Python >=3.10"
        exit 1
    fi

    # Step 1: 安装构建依赖
    echo "[1/3] 安装构建依赖 (setuptools, wheel)..."
    pip install --no-index --find-links="$PACKAGES_DIR" setuptools wheel

    # Step 2: 从 requirements.txt 安装全部依赖
    echo "[2/3] 从 packages/requirements.txt 安装全部依赖..."
    pip install --no-index --find-links="$PACKAGES_DIR" -r "$PACKAGES_DIR/requirements.txt"

    # Step 3: 安装 smartsuite 本身（开发模式）
    echo "[3/3] 安装 smartsuite 本身（开发模式）..."
    pip install --no-deps --no-build-isolation -e "$SCRIPT_DIR"

    echo ""
    echo "========================================"
    echo " 安装完成！"
    echo "========================================"
    echo " 验证: python3 -c 'import smartsuite; print(\"OK\")'"
}

case "${1:-}" in
    download)
        download_deps
        ;;
    install)
        install_offline
        ;;
    install-reqs)
        install_reqs
        ;;
    *)
        echo "SmartSuite 离线安装脚本"
        echo "========================================"
        echo "用法:"
        echo "  bash setup_offline.sh download      - 在有网机器上下载所有依赖到 packages/"
        echo "  bash setup_offline.sh install        - 从本地 packages/ 离线安装（原有方式）"
        echo "  bash setup_offline.sh install-reqs   - 从 packages/requirements.txt 离线安装"
        echo "========================================"
        ;;
esac
