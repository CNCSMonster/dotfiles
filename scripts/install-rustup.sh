#!/bin/bash
# Wrapper: 运行 vendor 的 rustup-init.sh 并自动确认
# 安装后确保 rustup 在 PATH 中

set -e

# 运行安装脚本
exec "$(dirname "$0")/vendor/rustup-init.sh" -y

# 安装后：source cargo env 使 rustup 在当前 shell 可用
source "$HOME/.cargo/env" 2>/dev/null || true
