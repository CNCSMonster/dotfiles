#!/usr/bin/env bash
# System packages installation script for tool-installer (script manager)
# Always exits 0; prints warnings on failure instead of failing.
set -uo pipefail

OS="$(uname -s)"

if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        echo "安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
            echo "⚠️  Homebrew 安装失败"
            exit 0
        }
    fi
    echo "通过 Homebrew 安装基础系统包..."
    brew install --yes python3 gh fzf ripgrep tree git || echo "⚠️  部分包安装失败"
    exit 0
fi

if [[ "$OS" == "Linux" ]]; then
    echo "检查并安装基础系统包..."
    missing=()
    for pkg in python3 curl gnupg software-properties-common gh build-essential pkg-config libssl-dev \
               libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev \
               fzf ripgrep zsh tree git htop; do
        command -v "$pkg" &>/dev/null || dpkg -s "$pkg" &>/dev/null || missing+=("$pkg")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        echo "✅ 基础系统包已就绪"
        exit 0
    fi
    export DEBIAN_FRONTEND=noninteractive
    local sudo_cmd="sudo"
    command -v sudo &>/dev/null || sudo_cmd=""
    $sudo_cmd apt-get update -qq || echo "⚠️  apt-get update 失败"
    $sudo_cmd apt-get install -y "${missing[@]}" || echo "⚠️  部分包安装失败"
    exit 0
fi

echo "不支持的系统: $OS"
exit 0
