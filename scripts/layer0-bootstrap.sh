#!/usr/bin/env bash
# Layer 0: Bootstrap — 安装 tool-installer 的前置依赖
# 这个脚本不依赖 tool-installer，因为它负责安装 tool-installer 本身
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

sudo_run() {
    if [ "$EUID" -eq 0 ]; then "$@"
    elif sudo -n true 2>/dev/null; then sudo "$@"
    else
        echo "⚠️  需要 sudo 权限，但当前用户无 NOPASSWD 配置"
        echo "   请手动安装: sudo apt-get install -y python3 curl gh"
        return 1
    fi
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
        brew install python3 gh fzf ripgrep tree git
    else
        # 检查所需包是否已安装，已装则跳过 sudo
        local missing=()
        for pkg in python3 curl gh build-essential pkg-config libssl-dev \
                   libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev \
                   fzf ripgrep zsh tree git htop; do
            command -v "$pkg" &>/dev/null || dpkg -s "$pkg" &>/dev/null || missing+=("$pkg")
        done
        if [ ${#missing[@]} -eq 0 ]; then
            echo "✅ 基础系统包已就绪（python3, curl, gh, build-essential）"
        else
            export DEBIAN_FRONTEND=noninteractive
            sudo_run apt-get update
            sudo_run apt-get install -y "${missing[@]}"
        fi
    fi
    echo "✅ 基础系统包安装完成"
}

# ── 0b: GitHub CLI 登录 ──
ensure_gh_login() {
    echo "=========================================="
    echo "Layer 0: 检查 GitHub CLI 登录状态..."
    echo "=========================================="

    # 优先通过环境变量认证（CI 和容器环境）
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        if gh auth status &>/dev/null; then
            echo "✅ GitHub CLI 已登录（通过 GITHUB_TOKEN）"
            return 0
        fi
        echo "检测到 GITHUB_TOKEN 环境变量，配置 gh 认证..."
        gh auth login --with-token <<< "$GITHUB_TOKEN" 2>/dev/null || true
        if gh auth status &>/dev/null; then
            echo "✅ GitHub CLI 已通过 GITHUB_TOKEN 登录"
            return 0
        fi
    fi

    if gh auth status &>/dev/null; then
        echo "✅ GitHub CLI 已登录"
        return 0
    fi

    echo ""
    echo "⚠️  GitHub CLI 未登录。"
    echo "   登录后可享受 5000 次/小时 API 限额（匿名仅 60 次）。"
    echo ""

    # 交互式环境提示登录
    if [ -t 0 ]; then
        gh auth login
    else
        echo "⚠️  非交互式环境，跳过 gh auth login"
        echo "   请手动运行: gh auth login"
        echo "   或设置 GITHUB_TOKEN 环境变量"
    fi
}

# ── 0b: WezTerm 终端 ──
install_wezterm() {
    echo "=========================================="
    echo "Layer 0: 安装 WezTerm..."
    echo "=========================================="

    if [[ "$(uname -s)" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install --cask wezterm 2>/dev/null || echo "⚠️  WezTerm 安装失败，跳过"
        else
            echo "⚠️  Homebrew 未安装，跳过 WezTerm"
        fi
        return 0
    fi

    # 检查是否已安装
    if command -v wezterm &>/dev/null || command -v wezterm-gui &>/dev/null; then
        echo "✅ WezTerm 已安装，跳过"
        return 0
    fi

    # Ubuntu 24+ 强制使用 nightly
    local nightly=false
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [ "${ID}" = "ubuntu" ] && [[ "${VERSION_ID}" == 24* ]]; then
            echo "检测到 Ubuntu 24，使用 nightly 版本"
            nightly=true
        fi
    fi

    # 添加 wez fury repo
    curl -fsSL --retry 3 --connect-timeout 15 https://apt.fury.io/wez/gpg.key | \
        sudo_run gpg --yes --dearmor -o /usr/share/keyrings/wezterm-fury.gpg
    echo 'deb [signed-by=/usr/share/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *' | \
        sudo_run tee /etc/apt/sources.list.d/wezterm.list
    sudo_run chmod 644 /usr/share/keyrings/wezterm-fury.gpg
    sudo_run apt-get update

    if [ "$nightly" = true ]; then
        sudo_run apt-get install -y wezterm-nightly
    else
        sudo_run apt-get install -y wezterm
    fi
    echo "✅ WezTerm 安装完成"
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
    install_wezterm
    ensure_gh_login
    install_tool_installer
    echo ""
    echo "✅ Layer 0 (Bootstrap) 完成"
    echo "   下一步: tool-installer install dev"
}

main "$@"
