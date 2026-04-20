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
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install python3
    else
      echo "Python3 未安装，请先安装 Python3（推荐 Homebrew: brew install python3）"
      return 1
    fi
  else
    sudo_run apt-get update
    sudo_run apt-get install -y python3
  fi
}

download_xdotter() {
  local version="${XDOTTER_VERSION:-v0.4.3}"
  local arch
  arch=$(uname -m)
  local os
  os=$(uname -s)

  local binary_name
  if [[ "$os" == "Darwin" ]]; then
    binary_name="xd-${arch}-apple-darwin"
  else
    binary_name="xd-${arch}-unknown-linux-gnu"
  fi
  local url="https://github.com/cncsmonster/xdotter/releases/download/${version}/${binary_name}"
  local dest="/tmp/${binary_name}"

  echo "尝试下载 xdotter 预编译二进制: ${binary_name}"
  if ! curl -sSL --retry 3 --retry-delay 2 \
    --connect-timeout 30 --max-time 120 \
    "$url" -o "$dest" 2>/dev/null; then
    echo "⚠️  下载失败，回退到 cargo install"
    cargo install --git https://github.com/cncsmonster/xdotter.git --tag "${version}" --locked
    return $?
  fi

  # 检查下载的是否为有效二进制文件（而非 GitHub 404 HTML 页面）
  if ! file "$dest" | grep -qE 'ELF|Mach-O|executable'; then
    echo "⚠️  下载的不是有效二进制文件（可能是 404 页面），回退到 cargo install"
    rm -f "$dest"
    cargo install --git https://github.com/cncsmonster/xdotter.git --tag "${version}" --locked
    return $?
  fi

  # SHA256 校验（仅 Linux x86_64，其他架构暂无）
  local EXPECTED_SHA256=""
  if [[ "$os" != "Darwin" ]]; then
    case "$arch" in
      x86_64) EXPECTED_SHA256="6334cdf31d7bf9a0ef35bb358ae425a0de64ca308bcce1cd5ac7af88b4dfb3fc" ;;
      *) echo "⚠️  架构 $arch 无 SHA256 记录，跳过校验";;
    esac
  fi

  if [ -n "$EXPECTED_SHA256" ]; then
    local ACTUAL_SHA256
    ACTUAL_SHA256=$(sha256sum "$dest" | awk '{print $1}')
    if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
      echo "❌ xdotter SHA256 校验失败!"
      echo "  期望: $EXPECTED_SHA256"
      echo "  实际: $ACTUAL_SHA256"
      rm -f "$dest"
      return 1
    fi
  fi

  mv "$dest" ~/.cargo/bin/xd
  chmod +x ~/.cargo/bin/xd
  echo "✅ xdotter 预编译二进制安装成功"
}

deploy_dotfiles(){
  mkdir -p ~/.cargo/bin
  retry_fn 3 "下载 xdotter" download_xdotter
  cd "${SCRIPT_DIR}" && ~/.cargo/bin/xd deploy --quiet --force

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

  if [[ "$(uname -s)" == "Darwin" ]]; then
    # macOS: 使用 Homebrew 安装字体
    if ! command -v brew >/dev/null 2>&1; then
      echo "⚠️  Homebrew 未安装，跳过字体安装"
      return 0
    fi
    echo "使用 Homebrew 安装字体..."
    brew install --cask \
      font-jetbrains-mono \
      font-fira-code \
      font-fira-code-nerd-font \
      font-noto-sans-cjk \
      font-noto-color-emoji \
      2>/dev/null || echo "⚠️  部分字体可能已安装，继续执行..."
    echo "✅ 字体安装完成（macOS/Homebrew）"
  else
    # Linux: 通过 apt 安装 fontconfig（提供 fc-list/fc-cache）和字体包
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
  fi
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
  # macOS readlink 不支持 -f，用 realpath 或手动处理
  if command -v realpath >/dev/null 2>&1; then
    original_target=$(realpath "$cargo_config" 2>/dev/null || echo "")
  else
    original_target=$(readlink -f "$cargo_config" 2>/dev/null || echo "")
  fi

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
  if [[ "$(uname -s)" != "Darwin" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    export TZ=Asia/Shanghai
  fi
  echo "=========================================="
  echo "部署 dotfiles 配置..."
  echo "=========================================="
  deploy_dotfiles
  echo "✅ 配置部署完成"
}

# ========== 第二部分：安装工具 ==========
do_install() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    export TZ=Asia/Shanghai
  fi

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
