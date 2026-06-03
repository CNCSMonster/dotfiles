#!/usr/bin/env bash
# 安装 uv (Python 包管理器)
# 使用官方推荐的安装方式：从 astral.sh CDN 下载预编译二进制
# 不依赖 GitHub，适合国内网络环境
set -eo pipefail

# 检查是否已安装
if command -v uv &>/dev/null; then
    INSTALLED_VER=$(uv --version 2>&1 | head -1 || echo "")
    if [ -n "$INSTALLED_VER" ]; then
        echo "uv 已安装：$INSTALLED_VER，跳过"
        exit 0
    fi
fi

echo "安装 uv（从 astral.sh 下载）..."
mkdir -p ~/.cargo/bin

# 官方安装脚本（会检测架构和操作系统）
curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh

# 验证安装结果
if command -v uv &>/dev/null; then
    echo "✅ uv 安装成功：$(uv --version)"
else
    # 安装脚本可能放到了 ~/.cargo/bin，确认
    if [ -x ~/.cargo/bin/uv ]; then
        echo "✅ uv 安装成功：$(~/.cargo/bin/uv --version)"
    else
        echo "❌ uv 安装失败"
        exit 1
    fi
fi
