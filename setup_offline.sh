#!/usr/bin/env bash
# ============================================================
# SmartSuite 离线安装脚本（macOS / Linux）
# 用法:
#   联网下载 (当前平台):      bash setup_offline.sh download
#   联网下载 (指定 Python):   bash setup_offline.sh download 312
#   联网下载 (跨平台):        bash setup_offline.sh download 312 win_amd64
#   离线安装:  bash setup_offline.sh install
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGES_DIR="$SCRIPT_DIR/packages"

download_deps() {
    local target_py="${1:-}"
    local target_platform="${2:-}"
    local platform_args=()

    if [ -n "$target_py" ]; then
        if ! [[ "$target_py" =~ ^3[0-9]{2}$ ]]; then
            echo "[错误] 无效的 Python 版本: 「$target_py」，应为 3 位数字（如 310/311/312/313）"
            exit 1
        fi
        platform_args+=(--python-version "$target_py" --implementation cp --abi "cp$target_py" --only-binary=:all:)
        if [ -n "$target_platform" ]; then
            platform_args+=(--platform "$target_platform")
            echo "目标平台: $target_platform + Python ${target_py:0:1}.${target_py:1} (cp$target_py)"
        else
            echo "目标: 当前操作系统 + Python ${target_py:0:1}.${target_py:1} (cp$target_py)"
        fi
        echo "⚠ 离线安装时，目标机器 Python 版本必须精确匹配，且仅支持 wheel 安装（无需编译器）"
    fi

    echo "[1/4] 创建 packages 目录..."
    mkdir -p "$PACKAGES_DIR"

    echo "[2/4] 下载构建依赖 (setuptools, wheel)..."
    echo "       这些是 pip 构建 smartsuite 包时必需的，"
    echo "       但 pip download 不会自动包含它们。"
    pip download 'setuptools>=68.0' wheel -d "$PACKAGES_DIR" ${platform_args[@]+"${platform_args[@]}"}

    echo "[3/4] 下载全部运行时依赖到 packages/ ..."
    echo "       含核心依赖 + web + report + dev"
    pip download '.[web,report,dev]' -d "$PACKAGES_DIR" ${platform_args[@]+"${platform_args[@]}"}

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

    # Step 2: 安装 smartsuite 本身（开发模式，不装依赖）
    #         必须先装 smartsuite，pip 才能解析 [web,report,dev] extras 的依赖
    echo "[2/3] 安装 smartsuite 本身（开发模式，不装依赖）..."
    pip install --no-deps --no-build-isolation -e "$SCRIPT_DIR"

    # Step 3: 安装所有运行时依赖（通过已安装的 smartsuite 元数据解析 extras）
    echo "[3/3] 从本地 packages/ 安装全部运行时依赖..."
    pip install --no-index --find-links="$PACKAGES_DIR" --no-build-isolation 'smartsuite[web,report,dev]'

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
        download_deps "${2:-}" "${3:-}"
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
        echo "  bash setup_offline.sh download                 - 下载当前平台依赖到 packages/"
        echo "  bash setup_offline.sh download 312             - 下载当前 OS + Python 3.12 的依赖"
        echo "  bash setup_offline.sh download 312 win_amd64   - 跨平台下载 (Windows x64 + Python 3.12)"
        echo "  bash setup_offline.sh install                  - 从本地 packages/ 离线安装（原有方式）"
        echo "  bash setup_offline.sh install-reqs             - 从 packages/requirements.txt 离线安装"
        echo "========================================"
        ;;
esac
