#!/usr/bin/env bash
# WezTerm installation script for tool-installer (script manager)
# Handles apt.fury.io source on Linux, brew cask on macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# apt 执行策略（有界超时 / 源预检 / 失败归因）的单一事实来源
source "${SCRIPT_DIR}/lib/apt.sh"

OS="$(uname -s)"
ARCH="$(uname -m)"

if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        echo "Homebrew 未安装，跳过 WezTerm"
        exit 0
    fi
    echo "通过 Homebrew cask 安装 WezTerm..."
    brew install --cask wezterm 2>/dev/null || echo "⚠️  WezTerm 安装失败，跳过"
    exit 0
fi

if [[ "$OS" == "Linux" ]]; then
    if command -v wezterm &>/dev/null || command -v wezterm-gui &>/dev/null; then
        echo "WezTerm 已安装，跳过"
        exit 0
    fi

    echo "添加 WezTerm apt 源..."
    curl -fsSL --retry 3 --connect-timeout 15 https://apt.fury.io/wez/gpg.key | \
        sudo gpg --yes --dearmor -o /usr/share/keyrings/wezterm-fury.gpg 2>/dev/null || {
        echo "⚠️  添加 WezTerm GPG 密钥失败，跳过"
        exit 0
    }

    echo 'deb [signed-by=/usr/share/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *' | \
        sudo tee /etc/apt/sources.list.d/wezterm.list >/dev/null 2>&1 || {
        echo "⚠️  添加 WezTerm apt 源失败，跳过"
        exit 0
    }

    # WezTerm 源刚写入，先探测各源可达性再更新，避免在坏源上无界重试
    apt_sources_health_check || true
    apt_run sudo update || echo "⚠️  apt-get update 未完全成功（原因见上方归因）"
    apt_run sudo install -y wezterm || echo "⚠️  WezTerm 安装失败，跳过"
    exit 0
fi

echo "不支持的系统: $OS"
exit 0
