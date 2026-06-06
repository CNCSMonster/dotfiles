#!/bin/bash
# Wrapper: 运行 vendor 的 rustup-init.sh 并自动确认
# 安装后确保 rustup 在 PATH 中

set -e

# CI 环境（GitHub Actions 等海外 runner）直连官方源，rsproxy.cn 可能超时
# 非 CI 环境使用 rsproxy.cn（字节跳动维护）作为 Rust 下载镜像
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    export RUSTUP_DIST_SERVER="${RUSTUP_DIST_SERVER:-https://static.rust-lang.org}"
    export RUSTUP_UPDATE_ROOT="${RUSTUP_UPDATE_ROOT:-https://static.rust-lang.org/rustup}"
else
    export RUSTUP_DIST_SERVER="${RUSTUP_DIST_SERVER:-https://rsproxy.cn}"
    export RUSTUP_UPDATE_ROOT="${RUSTUP_UPDATE_ROOT:-https://rsproxy.cn/rustup}"
fi

# 运行安装脚本（tool-installer 会在安装后重新评估 PATH）
exec "$(dirname "$0")/vendor/rustup-init.sh" -y
