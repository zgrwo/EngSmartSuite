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
    echo "[1/2] 创建 packages 目录..."
    mkdir -p "$PACKAGES_DIR"

    echo "[2/2] 下载全部依赖到 packages/ ..."
    echo "       含核心依赖 + web + report + dev"
    pip download .[web,report,dev] -d "$PACKAGES_DIR"

    echo ""
    echo "========================================"
    echo " 下载完成！文件数量:"
    ls "$PACKAGES_DIR"/*.whl 2>/dev/null | wc -l
    echo "========================================"
    echo ""
    echo "请将 packages/ 文件夹复制到离线机器的项目根目录，"
    echo "然后在离线机器上运行: bash setup_offline.sh install"
}

install_offline() {
    if [ ! -d "$PACKAGES_DIR" ]; then
        echo "[错误] packages/ 文件夹不存在，请先在有网机器上运行:"
        echo "       bash setup_offline.sh download"
        exit 1
    fi

    echo "[1/2] 从本地 packages/ 安装全部依赖..."
    pip install --no-index --find-links="$PACKAGES_DIR" smartsuite[web,report,dev]

    echo "[2/2] 安装 smartsuite 本身（开发模式）..."
    pip install --no-deps -e "$SCRIPT_DIR"

    echo ""
    echo "========================================"
    echo " 安装完成！"
    echo "========================================"
    echo " 验证: python -c 'import smartsuite; print(\"OK\")'"
}

case "${1:-}" in
    download)
        download_deps
        ;;
    install)
        install_offline
        ;;
    *)
        echo "SmartSuite 离线安装脚本"
        echo "========================================"
        echo "用法:"
        echo "  bash setup_offline.sh download  - 在有网机器上下载所有依赖到 packages/"
        echo "  bash setup_offline.sh install    - 从本地 packages/ 离线安装"
        echo "========================================"
        ;;
esac
