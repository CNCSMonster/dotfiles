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
  curl -sSL --connect-timeout 30 --max-time 120 \
    https://github.com/cncsmonster/xdotter/releases/latest/download/xd.pyz \
    -o ~/.local/bin/xd
}

# 使用 xdotter (github.com/cncsmonster/xdotter) 部署 dotfiles
deploy_dotfiles(){
  ensure_python3
  mkdir -p ~/.local/bin
  retry_fn 5 "下载 xdotter" download_xdotter
  chmod +x ~/.local/bin/xd
  # 使用 xd 部署
  ~/.local/bin/xd --config "${SCRIPT_DIR}/xdotter.toml" --quiet --force
}

# 初始化 git submodules (zcomet 等)
# 即使用户 clone 时没有加 --recursive，也能自动初始化
init_submodules() {
  if [[ -d "${SCRIPT_DIR}/.git" ]]; then
    # 是 git 仓库，尝试初始化 submodule
    cd "${SCRIPT_DIR}"
    if git submodule status &>/dev/null; then
      echo "正在初始化 submodules..."
      git submodule update --init --recursive 2>/dev/null || true
    fi
  fi
  # 如果不是 git 仓库（如 zip 下载），跳过 submodule 初始化
  # zcomet 会在首次登录时 fallback 到 git clone
}


main() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  deploy_dotfiles
  init_submodules

  # 直接加载需要的函数定义文件，而不是通过 source bashrc/zshrc
  # 因为 bashrc 在非交互式模式下会在第 8 行 return，导致后面的函数定义无法加载
  export SH_COMMON_DIR="$HOME/.config/shells/common"
  source "$SH_COMMON_DIR/env.sh"
  source "$SH_COMMON_DIR/fn.sh"
  source "$SH_COMMON_DIR/install-functions.sh"
  
  install-common-tools
  retry_fn 3 "安装 Neovim" install-neovim
  retry_fn 3 "安装 Helix" install-helix
  llvmup default 19
  retry_fn 5 "安装 Rust" install-rust stable
  retry_fn 3 "安装 Rust 工具" install-common-rust-tools
  retry_fn 3 "安装 cargo-fuzz" setup-cargo-fuzz
  # 使用 mise 安装 go, zig, node, pnpm 等工具
  mise trust && mise install
}

main "$@"
