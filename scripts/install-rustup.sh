#!/bin/bash
# Wrapper: 运行 vendor 的 rustup-init.sh 并自动确认
# 安装后确保 rustup 在 PATH 中

set -e

# 使用 rsproxy.cn（字节跳动维护）作为 Rust 下载镜像
# 国内环境下 static.rust-lang.org 无法访问
export RUSTUP_DIST_SERVER="${RUSTUP_DIST_SERVER:-https://rsproxy.cn}"
export RUSTUP_UPDATE_ROOT="${RUSTUP_UPDATE_ROOT:-https://rsproxy.cn/rustup}"

# 运行安装脚本（tool-installer 会在安装后重新评估 PATH）
exec "$(dirname "$0")/vendor/rustup-init.sh" -y
