#!/usr/bin/env bash

# 一键配置脚本 - 在干净的 Ubuntu 系统上部署完整的开发环境
# 使用方法：git clone 后直接运行 ./setup.sh
# 功能：部署 dotfiles → 安装系统依赖 → 安装开发工具链

set -exo pipefail

# --------- helpers ---------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

function sudo_run() {
    # 如果当前用户是root用户, 则直接运行命令
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# 通用重试函数 - 接收函数名作为参数
# 用法: retry_fn <max_retries> <description> <function_name> [args...]
# 示例: retry_fn 5 "安装 Rust" install-rust stable
retry_fn() {
    local max_retries=${1:-5}
    local description=$2
    local fn=$3
    shift 3
    local retry=0
    
    while [ $retry -lt $max_retries ]; do
        if $fn "$@"; then
            return 0
        fi
        retry=$((retry + 1))
        echo "${description}失败，重试 $retry/$max_retries..."
        sleep 5
    done
    
    echo "错误: ${description}失败，已达最大重试次数"
    return 1
}

ensure_python3() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  sudo_run apt-get update
  sudo_run apt-get install -y python3
}

# 下载 xdotter (供 retry_fn 调用)
download_xdotter() {
  # --retry 8: curl 内置重试 8 次，处理频繁的小网络波动
  # --retry-delay 2: 重试间隔 2 秒
  # -C -: 断点续传，从断开的地方继续下载
  # 使用环境变量 XDOTTER_VERSION 指定版本，避免破坏性变更
  local version="${XDOTTER_VERSION:-v0.3.4}"
  curl -sSL --retry 8 --retry-delay 2 -C - \
    --connect-timeout 30 --max-time 120 \
    "https://github.com/cncsmonster/xdotter/releases/download/${version}/xd.pyz" \
    -o ~/.local/bin/xd
}

# 使用 xdotter (github.com/cncsmonster/xdotter) 部署 dotfiles
deploy_dotfiles(){
  ensure_python3
  mkdir -p ~/.local/bin
  # retry_fn 3: 外层重试 3 次，处理持续的大问题（如镜像站全部不可用）
  retry_fn 3 "下载 xdotter" download_xdotter
  chmod +x ~/.local/bin/xd
  # 使用 xd 部署 (xdotter v0.3.4+ 移除了 --config 参数，需 cd 到配置目录执行)
  cd "${SCRIPT_DIR}" && ~/.local/bin/xd deploy --quiet --force
}

main() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  deploy_dotfiles

  # 直接加载需要的函数定义文件，而不是通过 source bashrc/zshrc
  # 因为 bashrc 在非交互式模式下会在第 8 行 return，导致后面的函数定义无法加载
  # 使用相对路径直接 source 原文件，不依赖 xdotter 部署的 symlink
  source "${SCRIPT_DIR}/shells/common/env.sh"
  source "${SCRIPT_DIR}/shells/common/fn.sh"
  source "${SCRIPT_DIR}/shells/common/install-functions.sh"

  install-common-tools
  retry_fn 3 "安装 Neovim" install-neovim
  retry_fn 3 "安装 Helix" install-helix
  retry_fn 3 "安装 Helix Runtime" install-helix-runtime
  retry_fn 3 "安装 marksman" install-marksman
  retry_fn 3 "安装 yq" install-yq
  llvmup default 19
  retry_fn 5 "安装 Rust" install-rust stable
  
  # Rust 工具安装
  # CARGO_INSTALL_STRICT=1 时，失败会终止脚本；否则继续执行
  if ! retry_fn 3 "安装 Rust 工具" install-common-rust-tools; then
    if [ "${CARGO_INSTALL_STRICT:-0}" = "1" ]; then
      echo "❌ 错误：CARGO_INSTALL_STRICT=1，Rust 工具安装失败，终止脚本"
      exit 1
    fi
    echo "⚠️  警告：Rust 工具安装失败，继续执行后续步骤..."
  fi
  
  retry_fn 3 "安装 cargo-fuzz" setup-cargo-fuzz
  # 使用 mise 安装 go, zig, node, pnpm 等工具
  mise trust && mise install
  # 更新 mise 环境变量（Docker 非交互式环境需要手动触发 hook-env）
  # $SH 已在 env.sh 中设置
  eval "$(mise hook-env -s $SH)" 2>/dev/null || true

  # 安装 Helix LSP 语言服务器（智能检测，只安装缺失的）
  retry_fn 3 "安装 Helix LSP" install-helix-lsp

  # 安装 Yazi 插件
  retry_fn 3 "安装 Yazi 插件" install-yazi-plugins
}

main "$@"
