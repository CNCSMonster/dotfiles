#!/usr/bin/env bash
# Termux/Android 最小远程开发工具安装脚本
# 用途：手机连接远程开发环境；不安装完整本地开发工具链
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${SCRIPT_DIR}/termux-manifest.toml"

check_termux() {
    if [[ -z "${PREFIX:-}" ]] || [[ ! -x "${PREFIX}/bin/pkg" ]]; then
        echo "❌ 此脚本仅支持 Termux 环境"
        echo "   请在 Termux 中运行"
        exit 1
    fi
    echo "✅ Termux 环境检测通过"
}

read_packages() {
    if [[ ! -f "$MANIFEST" ]]; then
        echo "❌ 找不到 Termux 配置：${MANIFEST}" >&2
        exit 1
    fi

    awk '
        /^\[packages\]$/ { in_packages = 1; next }
        /^\[/ { in_packages = 0 }
        in_packages && /^"[^"].*"[[:space:]]*=/ {
            package = $0
            sub(/^"/, "", package)
            sub(/"[[:space:]]*=.*/, "", package)
            print package
        }
    ' "$MANIFEST"
}

usage() {
    echo "用法: $0 [选项]"
    echo ""
    echo "  无参数        安装缺失的最小远程开发工具"
    echo "  --dry-run     只显示待安装的包"
    echo "  --help        显示帮助"
}

command_for_package() {
    case "$1" in
        openssh) printf '%s\n' ssh ;;
        ripgrep) printf '%s\n' rg ;;
        yazi) printf '%s\n' ya ;;
        *) printf '%s\n' "$1" ;;
    esac
}

install_packages() {
    local dry_run="${1:-false}"
    local packages=()
    local missing=()

    mapfile -t packages < <(read_packages)
    if [[ ${#packages[@]} -eq 0 ]]; then
        echo "❌ Termux 配置中没有可安装的包" >&2
        exit 1
    fi

    for package in "${packages[@]}"; do
        if ! command -v "$(command_for_package "$package")" &>/dev/null; then
            missing+=("$package")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        echo "✅ Termux 远程开发工具已就绪"
        return 0
    fi

    echo "待安装：${missing[*]}"
    if [[ "$dry_run" == true ]]; then
        return 0
    fi

    pkg update -y
    pkg install -y "${missing[@]}"
    echo "✅ Termux 远程开发工具安装完成"
}

main() {
    local dry_run=false

    case "${1:-}" in
        "") ;;
        --dry-run) dry_run=true ;;
        --help|-h)
            usage
            return 0
            ;;
        *)
            echo "未知选项: $1" >&2
            usage >&2
            return 1
            ;;
    esac

    check_termux
    install_packages "$dry_run"
}

main "$@"
