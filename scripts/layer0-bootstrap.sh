#!/usr/bin/env bash
# Layer 0: Bootstrap — 安装 tool-installer 的前置依赖
# 这个脚本不依赖 tool-installer，因为它负责安装 tool-installer 本身
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

sudo_run() {
    if [ "$EUID" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

# ── 0a: 基础系统包 ──
install_system_packages() {
    echo "=========================================="
    echo "Layer 0: 安装基础系统包..."
    echo "=========================================="

    if [[ "$(uname -s)" == "Darwin" ]]; then
        if ! command -v brew &>/dev/null; then
            echo "安装 Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install python3 gh
    else
        export DEBIAN_FRONTEND=noninteractive
        sudo_run apt-get update
        sudo_run apt-get install -y python3 curl gh
    fi
    echo "✅ 基础系统包安装完成"
}

# ── 0b: GitHub CLI 登录 ──
ensure_gh_login() {
    echo "=========================================="
    echo "Layer 0: 检查 GitHub CLI 登录状态..."
    echo "=========================================="

    if gh auth status &>/dev/null; then
        echo "✅ GitHub CLI 已登录"
        return 0
    fi

    echo ""
    echo "⚠️  GitHub CLI 未登录。"
    echo "   登录后可享受 5000 次/小时 API 限额（匿名仅 60 次）。"
    echo ""

    # CI 环境使用 GITHUB_TOKEN
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        echo "检测到 GITHUB_TOKEN 环境变量，使用它登录..."
        gh auth login --with-token <<< "$GITHUB_TOKEN"
        echo "✅ GitHub CLI 已通过 GITHUB_TOKEN 登录"
        return 0
    fi

    # 交互式环境提示登录
    if [ -t 0 ]; then
        gh auth login
    else
        echo "⚠️  非交互式环境，跳过 gh auth login"
        echo "   请手动运行: gh auth login"
        echo "   或设置 GITHUB_TOKEN 环境变量"
    fi
}

# ── 0c: 安装 tool-installer ──
install_tool_installer() {
    echo "=========================================="
    echo "Layer 0: 安装 tool-installer..."
    echo "=========================================="

    mkdir -p ~/.local/bin

    # 从 vendor 目录复制单文件分发
    local artifact="${PROJECT_DIR}/vendor/tool-installer"
    if [ -f "$artifact" ]; then
        cp "$artifact" ~/.local/bin/tool-installer
        chmod +x ~/.local/bin/tool-installer
        echo "✅ tool-installer 已安装到 ~/.local/bin/tool-installer"
        ~/.local/bin/tool-installer --help | head -3
    else
        echo "❌ vendor/tool-installer 不存在，请先构建"
        return 1
    fi
}

# ── 入口 ──
main() {
    install_system_packages
    ensure_gh_login
    install_tool_installer
    echo ""
    echo "✅ Layer 0 (Bootstrap) 完成"
    echo "   下一步: tool-installer install dev"
}

main "$@"
