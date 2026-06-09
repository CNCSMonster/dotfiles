#!/usr/bin/env bash
# Font installation script for tool-installer (script manager)
# Installs system fonts + FiraCode Nerd Font
# Always exits 0; prints warnings on failure instead of failing.
set -uo pipefail

OS="$(uname -s)"

if [[ "$OS" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
        echo "通过 Homebrew 安装字体..."
        brew install --cask \
            font-jetbrains-mono \
            font-fira-code \
            font-fira-code-nerd-font \
            font-noto-sans-cjk \
            font-noto-color-emoji \
            2>/dev/null || echo "⚠️  部分字体可能已安装，继续..."
    else
        echo "⚠️  Homebrew 未安装，跳过字体安装"
    fi
    exit 0
fi

if [[ "$OS" == "Linux" ]]; then
    # Wait for dpkg lock before attempting install
    max_wait=120
    waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
        if [ $waited -ge $max_wait ]; then
            echo "⚠️  dpkg 锁等待超时，跳过字体安装"
            exit 0
        fi
        sleep 5
        waited=$((waited + 5))
    done

    echo "安装系统字体包..."
    for i in {1..3}; do
        if apt-get install -y --no-install-recommends \
            fontconfig \
            fonts-noto-cjk \
            fonts-noto-color-emoji \
            fonts-jetbrains-mono \
            fonts-dejavu-core \
            2>/dev/null; then
            break
        fi
        echo "⚠️  字体包安装失败，等待锁释放..."
        sleep 3
    done || echo "⚠️  部分字体包安装失败"

    if ! fc-list 2>/dev/null | grep -qi "FiraCode.*Nerd"; then
        echo "安装 FiraCode Nerd Font..."
        fira_url="https://github.com/ryanoasis/nerd-fonts/releases/download/v7.0.0/FiraCode.zip"
        fira_tmp="/tmp/FiraCode-Nerd-Font.zip"
        if wget --tries=3 --timeout=30 --connect-timeout=15 "$fira_url" -O "$fira_tmp" 2>/dev/null; then
            fira_dir="/usr/local/share/fonts/FiraCode-Nerd-Font"
            mkdir -p "$fira_dir" 2>/dev/null || true
            if command -v unzip &>/dev/null; then
                unzip -o "$fira_tmp" -d "$fira_dir" 2>/dev/null || echo "⚠️  FiraCode 解压失败"
            else
                apt-get install -y unzip 2>/dev/null || true
                unzip -o "$fira_tmp" -d "$fira_dir" 2>/dev/null || echo "⚠️  FiraCode 解压失败"
            fi
            rm -f "$fira_tmp"
        else
            echo "⚠️  FiraCode Nerd Font 下载失败，跳过"
        fi
    else
        echo "FiraCode Nerd Font 已安装，跳过"
    fi

    if command -v fc-cache &>/dev/null; then
        echo "刷新字体缓存..."
        fc-cache -f 2>/dev/null || true
    fi
    exit 0
fi

echo "不支持的系统: $OS"
exit 0
