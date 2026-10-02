#!/usr/bin/env bash
# System packages installation script for tool-installer (script manager)
# Always exits 0; prints warnings on failure instead of failing.
#
# 本脚本现只剩 macOS 分支（Homebrew 引导 + 基础包）。
# Linux 清单已迁到 manifest.toml 的声明式 [system-packages.linux]
# （manager = "apt"），由 tool-installer 的 AptManager 直接安装：
# 有界超时 / 源预检 / 失败归因 / 非预期状态授权统一走那一侧，
# 见 docs/tool-installer-migration-plan.md §4.3。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

echo "不支持的系统: $OS（Linux 系统包由 manifest 的 manager = \"apt\" 负责）"
exit 0
