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
    echo "通过 Homebrew 安装系统基础包与构建工具链..."
    # gh、ripgrep → user-tools 模块 (github-release 精确锁定)
    brew install python3 fzf tree git || echo "⚠️  部分包安装失败"
    exit 0
fi

if [[ "$OS" == "Linux" ]]; then
    echo "检查并安装系统基础包与构建工具链..."
    missing=()
    # gh、ripgrep → user-tools 模块 (github-release 精确锁定)
    # clang: cargo 配置 linker=clang + verify 编译测试；Layer 2 llvmup 需要 sudo 终端，
    # 非交互环境由这里的 apt clang 兜底（llvmup 成功时装 LLVM 22 覆盖）
    for pkg in python3 curl wget gnupg software-properties-common build-essential gcc g++ clang cmake ninja-build pkg-config libssl-dev \
               libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev libclang-dev libicu-dev unzip iproute2 \
               fzf zsh tree git htop; do
        command -v "$pkg" &>/dev/null || dpkg -s "$pkg" &>/dev/null || missing+=("$pkg")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        echo "✅ 系统基础包与构建工具链已就绪"
        exit 0
    fi
    export DEBIAN_FRONTEND=noninteractive
    sudo_cmd="sudo"
    command -v sudo &>/dev/null || sudo_cmd=""
    $sudo_cmd apt-get update -qq || echo "⚠️  apt-get update 失败"
    $sudo_cmd apt-get install -y "${missing[@]}" || echo "⚠️  部分包安装失败"
    exit 0
fi

echo "不支持的系统: $OS"
exit 0
