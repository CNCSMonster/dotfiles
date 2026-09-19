#!/usr/bin/env bash
# 安装 uv (Python 包管理器)
# 使用官方推荐的安装方式：从 astral.sh CDN 下载预编译二进制
# 不依赖 GitHub，适合国内网络环境
set -eo pipefail

# 固定版本号（与 tools.toml 同步）
UV_VERSION="0.11.18"

# 检查是否已安装相同版本
if command -v uv &>/dev/null; then
    INSTALLED_VER=$(uv --version 2>&1 | head -1 || echo "")
    if echo "$INSTALLED_VER" | grep -q "$UV_VERSION"; then
        echo "uv $UV_VERSION 已安装，跳过"
        exit 0
    fi
fi

echo "安装 uv $UV_VERSION（从 astral.sh 下载）..."
mkdir -p ~/.cargo/bin

# 锁版方式：astral 的 install.sh 无版本参数、也不读 UV_VERSION（裸 URL 永远指向 latest），
# 官方锁版姿势是使用带版本号的安装器 URL（已验证返回 "installer for uv <版本>"）。
# --no-modify-path：rc 文件已由 dotfiles 统一管理，禁止安装脚本改写（会顺符号链接污染仓库源文件）
curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" 2>/dev/null | sh -s -- --no-modify-path

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
