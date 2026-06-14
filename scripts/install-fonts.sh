#!/usr/bin/env bash
# Font installation script for tool-installer (script manager)
# Installs system fonts + FiraCode Nerd Font
# Always exits 0; prints warnings on failure instead of failing.
set -uo pipefail

OS="$(uname -s)"

if [[ "$OS" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
        echo "通过 Homebrew 安装字体..."
        brew install --cask --yes \
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

if [[ "$OS" != "Linux" ]]; then
    echo "不支持的系统: $OS"
    exit 0
fi

is_interactive_tty() {
    [ -t 1 ]
}

wait_for_dpkg_lock() {
    local max_wait=120
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || \
          fuser /var/lib/dpkg/lock >/dev/null 2>&1 || \
          fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
        if [ $waited -ge $max_wait ]; then
            echo "⚠️  dpkg 锁等待超时，跳过系统字体包安装"
            return 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    return 0
}

install_system_fonts() {
    wait_for_dpkg_lock || return 0

    if [ "$EUID" -eq 0 ]; then
        apt-get install -y --no-install-recommends \
            fontconfig \
            fonts-noto-cjk \
            fonts-noto-color-emoji \
            fonts-jetbrains-mono \
            fonts-dejavu-core || echo "⚠️  系统字体包安装失败"
    elif is_interactive_tty; then
        echo "🔐 安装系统字体包需要 sudo 权限..."
        sudo apt-get install -y --no-install-recommends \
            fontconfig \
            fonts-noto-cjk \
            fonts-noto-color-emoji \
            fonts-jetbrains-mono \
            fonts-dejavu-core || echo "⚠️  系统字体包安装失败"
    else
        echo "⚠️  非交互环境，跳过系统字体包安装（避免 sudo 密码输入挂起）"
    fi
}

install_fira_code() {
    local user_font_dir="$HOME/.local/share/fonts/FiraCode-Nerd-Font"

    if fc-list 2>/dev/null | grep -qi "FiraCode.*Nerd"; then
        echo "FiraCode Nerd Font 已安装，跳过"
        return 0
    fi

    echo "安装 FiraCode Nerd Font -> $user_font_dir ..."
    local fira_version="v3.4.0"
    local fira_asset="FiraCode.zip"
    local fira_repo="ryanoasis/nerd-fonts"
    local fira_tmp="/tmp/FiraCode-Nerd-Font-${UID:-$$}.zip"

    rm -f "$fira_tmp"

    local downloaded=false
    for mirror in "https://ghfast.top/https://github.com/${fira_repo}/releases/download/${fira_version}/${fira_asset}" \
                  "https://mirror.ghproxy.com/https://github.com/${fira_repo}/releases/download/${fira_version}/${fira_asset}" \
                  "https://github.com/${fira_repo}/releases/download/${fira_version}/${fira_asset}"; do
        echo "尝试下载: $mirror"
        if wget --tries=2 --timeout=180 --connect-timeout=15 "$mirror" -O "$fira_tmp" 2>/dev/null; then
            downloaded=true
            break
        fi
        echo "⚠️  该镜像失败，尝试下一个..."
    done

    if [ "$downloaded" != true ]; then
        echo "⚠️  FiraCode Nerd Font 下载失败，跳过"
        return 0
    fi

    mkdir -p "$user_font_dir"
    if command -v unzip &>/dev/null; then
        unzip -o "$fira_tmp" -d "$user_font_dir" 2>/dev/null || echo "⚠️  FiraCode 解压失败"
    else
        if [ "$EUID" -eq 0 ]; then
            apt-get install -y unzip >/dev/null 2>&1 || true
        elif is_interactive_tty; then
            echo "🔐 安装 unzip 需要 sudo 权限..."
            sudo apt-get install -y unzip >/dev/null 2>&1 || true
        fi
        if command -v unzip &>/dev/null; then
            unzip -o "$fira_tmp" -d "$user_font_dir" 2>/dev/null || echo "⚠️  FiraCode 解压失败"
        else
            echo "⚠️  无 unzip，尝试 Python 解压..."
            python3 -c "import zipfile; zipfile.ZipFile('$fira_tmp').extractall('$user_font_dir')" 2>/dev/null || echo "⚠️  FiraCode 解压失败"
        fi
    fi
    rm -f "$fira_tmp"

    if command -v fc-cache &>/dev/null; then
        fc-cache -f "$user_font_dir" 2>/dev/null || true
    fi
}

install_system_fonts
install_fira_code

exit 0
