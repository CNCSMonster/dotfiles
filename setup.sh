#!/usr/bin/env bash

# 一键配置脚本 - 在干净的 Linux 系统上部署完整的开发环境
# 使用方法：git clone 后直接运行 ./setup.sh
#
# 用法：
#   ./setup.sh           部署配置 + 安装工具（默认）
#   ./setup.sh --deploy  只部署配置文件
#   ./setup.sh --install 只安装开发工具（配置已部署时）

set -exo pipefail

# --------- helpers ---------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

function sudo_run() {
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# 通用重试函数
# 用法: retry_fn <max_retries> <description> <function_name> [args...]
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

download_xdotter() {
  local version="${XDOTTER_VERSION:-v0.3.4}"
  curl -sSL --retry 8 --retry-delay 2 -C - \
    --connect-timeout 30 --max-time 120 \
    "https://github.com/cncsmonster/xdotter/releases/download/${version}/xd.pyz" \
    -o ~/.local/bin/xd
}

deploy_dotfiles(){
  ensure_python3
  mkdir -p ~/.local/bin
  retry_fn 3 "下载 xdotter" download_xdotter
  chmod +x ~/.local/bin/xd
  cd "${SCRIPT_DIR}" && ~/.local/bin/xd deploy --quiet --force

  # 部署字体配置后刷新缓存
  install-fonts

  # CI 环境自适应：GitHub Actions runner 位于国外，rsproxy.cn 反而慢
  # 检测 CI 环境，覆盖 cargo 配置直连 crates.io
  apply_cargo_mirror_override
}

# ========== 字体安装函数 ==========
# 安装 wezterm 配置的字体及 Nerd Font 图标支持
install-fonts() {
  echo "=========================================="
  echo "安装字体..."
  echo "=========================================="

  # 通过 apt 安装 fontconfig（提供 fc-list/fc-cache）和字体包
  sudo_run apt-get update
  sudo_run apt-get install -y --no-install-recommends \
    fontconfig \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-jetbrains-mono \
    fonts-dejavu-core

  # 安装 FiraCode Nerd Font（带图标支持，apt 无此包，从 GitHub 下载）
  if [ -x "$(command -v fc-list)" ] && fc-list | grep -qi "FiraCode.*Nerd"; then
    echo "FiraCode Nerd Font 已安装，跳过"
  else
    echo "安装 FiraCode Nerd Font..."
    local FIRACODE_VERSION="7.0.0"
    local FIRACODE_URL="https://github.com/ryanoasis/nerd-fonts/releases/download/v${FIRACODE_VERSION}/FiraCode.zip"
    local FIRACODE_DEST="/tmp/FiraCode-Nerd-Font.zip"

    echo "下载 FiraCode Nerd Font..."
    if wget --tries=3 --timeout=30 --connect-timeout=15 "$FIRACODE_URL" -O "$FIRACODE_DEST" 2>/dev/null; then
      local FIRACODE_DIR="/usr/local/share/fonts/FiraCode-Nerd-Font"
      sudo_run mkdir -p "$FIRACODE_DIR"

      # 解压到系统字体目录
      if command -v unzip >/dev/null 2>&1; then
        sudo_run unzip -o "$FIRACODE_DEST" -d "$FIRACODE_DIR"
      else
        sudo_run apt-get install -y unzip
        sudo_run unzip -o "$FIRACODE_DEST" -d "$FIRACODE_DIR"
      fi

      rm -f "$FIRACODE_DEST"
      echo "FiraCode Nerd Font 安装完成"
    else
      echo "⚠️  FiraCode Nerd Font 下载失败，跳过"
    fi
  fi

  # 刷新字体缓存
  if [ -x "$(command -v fc-cache)" ]; then
    echo "刷新字体缓存..."
    sudo_run fc-cache -f
  fi
  echo "✅ 字体安装完成"
}

apply_cargo_mirror_override() {
  # 检测是否在 GitHub Actions CI 环境
  if [ -z "$GITHUB_ACTIONS" ] && [ -z "$CI" ]; then
    return 0  # 非 CI 环境，无需覆盖
  fi

  echo "🌐 检测到 CI 环境，配置 cargo 直连 crates.io（跳过 rsproxy）"

  # 生成覆盖配置到 ~/.cargo/config.toml（替换 xdotter 创建的 symlink）
  local cargo_config="$HOME/.cargo/config.toml"
  local original_target
  original_target=$(readlink -f "$cargo_config" 2>/dev/null || echo "")

  if [ -n "$original_target" ]; then
    # 读取原配置内容，修改 source 部分
    # 使用 sed 注释掉 replace-with 行
    sed 's/^replace-with = "rsproxy-sparse"/# replace-with = "rsproxy-sparse"  # disabled in CI/' \
      "$original_target" > "$cargo_config.tmp" && \
      mv "$cargo_config.tmp" "$cargo_config"

    echo "✅ Cargo 配置已切换为 CI 模式（直连 crates.io）"
  else
    echo "⚠️  未找到 ~/.cargo/config.toml，跳过 cargo 配置覆盖"
  fi
}

load_install_functions() {
  source "${SCRIPT_DIR}/shells/common/env.sh"
  source "${SCRIPT_DIR}/shells/common/fn.sh"
  source "${SCRIPT_DIR}/shells/common/install-functions.sh"
}

# ========== 第一部分：部署配置 ==========
do_deploy() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  echo "=========================================="
  echo "部署 dotfiles 配置..."
  echo "=========================================="
  deploy_dotfiles
  echo "✅ 配置部署完成"
}

# ========== 第二部分：安装工具 ==========
do_install() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai

  load_install_functions

  echo "=========================================="
  echo "安装开发工具..."
  echo "=========================================="

  install-common-tools
  retry_fn 3 "安装 Neovim" install-neovim
  retry_fn 3 "安装 Helix" install-helix
  retry_fn 3 "安装 Helix Runtime" install-helix-runtime
  retry_fn 3 "安装 marksman" install-marksman
  retry_fn 3 "安装 yq" install-yq
  llvmup default 19
  retry_fn 5 "安装 Rust" install-rust stable

  # Rust 工具安装
  if ! retry_fn 3 "安装 Rust 工具" install-common-rust-tools; then
    if [ "${CARGO_INSTALL_STRICT:-0}" = "1" ]; then
      echo "❌ 错误：CARGO_INSTALL_STRICT=1，Rust 工具安装失败，终止脚本"
      exit 1
    fi
    echo "⚠️  警告：Rust 工具安装失败，继续执行后续步骤..."
  fi

  # Cargo 开发工具：编译加速
  retry_fn 3 "安装 sccache" install-sccache
  retry_fn 3 "安装 wild" install-wild

  retry_fn 3 "安装 cargo-fuzz" setup-cargo-fuzz

  # 使用 mise 安装 go, zig, node, pnpm 等工具
  mise trust && mise install
  eval "$(mise hook-env -s $SH)" 2>/dev/null || true

  retry_fn 3 "安装 Helix LSP" install-helix-lsp

  # 安装 Zellij 终端复用器
  retry_fn 3 "安装 Zellij" install-zellij

  retry_fn 3 "安装 Yazi 插件" install-yazi-plugins

  echo ""
  echo "=========================================="
  echo "✅ 所有工具安装完成"
  echo "=========================================="
}

# ========== 入口 ==========
main() {
  if [[ $# -eq 0 ]]; then
    do_deploy
    do_install
  else
    case "$1" in
      --deploy)  do_deploy ;;
      --install) do_install ;;
      *)
        echo "用法: $0 [--deploy|--install]"
        echo "  无参数    部署配置 + 安装工具（默认）"
        echo "  --deploy  只部署配置文件"
        echo "  --install 只安装开发工具"
        exit 1
        ;;
    esac
  fi
}

main "$@"
