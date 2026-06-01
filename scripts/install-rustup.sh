#!/bin/bash
# Wrapper: 运行 vendor 的 rustup-init.sh 并自动确认
# 安装后确保 rustup 在 PATH 中

set -e

# 运行安装脚本（tool-installer 会在安装后重新评估 PATH）
exec "$(dirname "$0")/vendor/rustup-init.sh" -y
