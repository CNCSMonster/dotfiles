########################################################
# 各种下载安装的函数
########################################################

# 网络波动：curl/wget 统一重试与超时（Docker 构建及本机均生效）
CURL_RETRY_OPTS="--retry 5 --retry-delay 3 --connect-timeout 30 --max-time 300"
WGET_RETRY_OPTS="--tries=5 --timeout=60 --connect-timeout=30"

# GitHub 镜像加速：依次尝试多个镜像站，失败再直连
# 设置 GITHUB_MIRROR="" 可禁用镜像
# 可用镜像站列表（按优先级排序）：
#   - https://mirror.ghproxy.com (ghproxy)
#   - https://gh-proxy.com (gh-proxy)
#   - https://gh.api.99988866.xyz (99988866)
#   - https://github.moeyy.xyz (moeyy)
GITHUB_MIRRORS="${GITHUB_MIRRORS:-https://mirror.ghproxy.com https://gh-proxy.com https://gh.api.99988866.xyz https://github.moeyy.xyz}"

# 从 GitHub 下载文件的通用函数（自动尝试多个镜像站 → 直连）
github_download() {
    local url="$1"
    local output="$2"
    
    # 尝试每个镜像站
    for mirror in $GITHUB_MIRRORS; do
        local mirror_url="${mirror}/${url}"
        echo "尝试镜像站: ${mirror_url}"
        if wget $WGET_RETRY_OPTS "$mirror_url" -O "$output" 2>/dev/null; then
            return 0
        fi
        echo "镜像站 ${mirror} 失败，尝试下一个..."
    done
    
    echo "所有镜像站均失败，尝试直连 GitHub..."
    wget $WGET_RETRY_OPTS "$url" -O "$output"
}

# 用于确保sudo命令不存在，但是为root用户时也能正常运行
# 因为很多比较精简的系统可能没有安装sudo
sudo_run() {
    # 如果当前用户是root用户, 则直接运行命令
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}


# 下载基础工具链
function install-common-tools() {
    sudo_run apt-get update --fix-missing
    sudo_run apt-get upgrade -y
    sudo_run apt-get install -y --no-install-recommends \
        apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build vim \
        lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip \
        htop iotop fzf ripgrep net-tools snapd vim tree git delta python3 python3-pip \
        python3-venv python3-dev python3-setuptools python3-wheel zsh sudo \
        libssl-dev libgit2-dev
}

# 确保rustup已安装，如果未安装，则下载并安装
function setup-rustup() {
    local RUSTUP_HOME="${HOME}/.rustup"
    local CARGO_HOME="${HOME}/.cargo"
    if ! command -v rustup >/dev/null 2>&1; then
        # rsproxy.cn 提供 rustup 国内镜像
        export RUSTUP_DIST_SERVER="https://rsproxy.cn"
        export RUSTUP_UPDATE_ROOT="https://rsproxy.cn/rustup"
        curl $CURL_RETRY_OPTS --proto '=https' --tlsv1.2 -sSf https://rsproxy.cn/rustup-init.sh | sh -s -- -y
        source "${CARGO_HOME}/env"
    fi
}

# 根据命令行参数指定版本号下载rust
# 如果没有指定，默认下载 stable 版本
# 例如: 
# install-rust           - 安装最新 stable
# install-rust nightly   - 安装最新 nightly
# install-rust 1.80.0    - 安装指定版本
function install-rust() {
    local RUST_VERSION=${1:-stable}
    setup-rustup
    rustup default "$RUST_VERSION"
    rustup component add rustfmt clippy rust-analyzer
}

# 下载比较新版的neovim
# 因为apt-get源里的版本太老了
function install-neovim(){
    # get target arch
    local ARCH=$(uname -m)
    local NVIM_URL="https://github.com/neovim/neovim/releases/download/nightly/nvim-linux-${ARCH}.tar.gz"
    local DEST="/tmp/nvim-linux-${ARCH}.tar.gz"

    github_download "$NVIM_URL" "$DEST"

    tar -xzf "$DEST" -C /tmp
    # 删除旧版本
    sudo_run rm -rf /usr/local/neovim || true
    sudo_run mv /tmp/nvim-linux-${ARCH} /usr/local/neovim
    sudo_run ln -sf /usr/local/neovim/bin/nvim /usr/local/bin/nvim
}

ensure_cargo_binstall() {
  if command -v cargo-binstall >/dev/null 2>&1; then
    return 0
  fi
  
  # 优先使用官方脚本下载预编译二进制，避免从源码编译
  # 官方文档：https://github.com/cargo-bins/cargo-binstall
  local ARCH=$(uname -m)
  local TARGET=""
  case $ARCH in
    x86_64) TARGET="x86_64-unknown-linux-musl" ;;
    aarch64) TARGET="aarch64-unknown-linux-musl" ;;
    armv7l) TARGET="armv7-unknown-linux-musleabihf" ;;
    *) 
      echo "Unsupported architecture: $ARCH, falling back to cargo install"
      cargo install cargo-binstall
      return
      ;;
  esac
  
  local URL="https://github.com/cargo-bins/cargo-binstall/releases/latest/download/cargo-binstall-${TARGET}.tgz"
  mkdir -p "${HOME}/.cargo/bin"
  local TMP_TGZ="/tmp/cargo-binstall-${TARGET}.tgz"
  
  if github_download "$URL" "$TMP_TGZ" && tar -xzf "$TMP_TGZ" -C "${HOME}/.cargo/bin" 2>/dev/null; then
    echo "cargo-binstall installed successfully via precompiled binary"
    rm -f "$TMP_TGZ"
  else
    echo "Failed to download precompiled binary, falling back to cargo install"
    cargo install cargo-binstall
  fi
}


# 下载常用rust的工具
function install-common-rust-tools() {
    ensure_cargo_binstall
    # 批量安装：cargo binstall 优先下载预编译二进制
    # 固定版本号避免上游更新带来的兼容性问题
    # 最后验证：2026-02-23，Docker Ubuntu 24.04 + Rust stable
    local CRATES=(
        kondo@0.9.0
        jaq@2.3.0
        rust-script@0.36.0
        parallel-disk-usage@0.21.1
        bat@0.26.1
        navi@2.24.0
        mcfly@0.9.4
        starship@1.23.0
        eza@0.21.0
        conceal@0.5.1
        zoxide@0.9.8
        fd-find@10.2.0
        macchina@6.0.0
        fnm@1.38.1
        tree-sitter-cli@0.25.4
        tokei@13.0.0-alpha.9
        gen-mdbook-summary@0.0.6
        mise@2026.2.15
        uv@0.10.10
    )
    # 策略：先尝试 binstall 下载预编译二进制（禁止 fallback 到源码编译，避免
    # GitHub API 403 rate limit 导致 120s 重试循环后再花几十分钟编译）。
    # 下载失败的 crate 收集起来，最后统一 cargo install 从源码编译。
    local FAILED=()
    for crate in "${CRATES[@]}"; do
        if ! cargo binstall "${crate}" -y --disable-strategies compile; then
            echo "binstall 下载失败: ${crate}，稍后从源码编译"
            FAILED+=("${crate}")
        fi
    done
    if [ ${#FAILED[@]} -gt 0 ]; then
        echo "以下 crate 无预编译二进制，从源码编译: ${FAILED[*]}"
        for crate in "${FAILED[@]}"; do
            cargo install "${crate}" --locked || cargo install "${crate}"
        done
    fi

    setup-yazi
}

function setup-yazi(){
    # yazi-fm 是 yazi 的主程序包名，yazi-cli 是 ya 命令行工具
    # 使用 cargo binstall 下载预编译二进制，速度快且稳定
    # 官方文档：https://yazi-rs.github.io/docs/installation/
    if ! cargo binstall yazi-fm yazi-cli -y --disable-strategies compile; then
        cargo install yazi-fm yazi-cli --locked || cargo install yazi-fm yazi-cli
    fi
}

function setup-cargo-fuzz() {
  rustup component add llvm-tools-preview --toolchain nightly
  ensure_cargo_binstall
  local FUZZ_CRATES=(cargo-fuzz grcov cargo-tarpaulin)
  local FAILED=()
  for crate in "${FUZZ_CRATES[@]}"; do
      if ! cargo binstall "${crate}" -y --disable-strategies compile; then
          FAILED+=("${crate}")
      fi
  done
  if [ ${#FAILED[@]} -gt 0 ]; then
      for crate in "${FAILED[@]}"; do
          cargo install "${crate}" --locked || cargo install "${crate}"
      done
  fi
}

# 下载wezterm终端模拟器
function setup-wezterm() {
    # check if install nightly
    nightly=${1:-false}
     if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [ "${ID}" = "ubuntu" ] && [[ "${VERSION_ID}" == 24* ]]; then
            echo "Detected Ubuntu 24, forcing nightly version for wezterm"
            nightly=true
        fi
    fi
    curl $CURL_RETRY_OPTS -fsSL https://apt.fury.io/wez/gpg.key | sudo_run gpg --yes --dearmor -o /usr/share/keyrings/wezterm-fury.gpg
    echo 'deb [signed-by=/usr/share/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *' | sudo_run tee /etc/apt/sources.list.d/wezterm.list
    sudo_run chmod 644 /usr/share/keyrings/wezterm-fury.gpg
    sudo_run apt update
    # 需要注意，现在wezterm在ubuntu 24上只支持nightly版本，修改如下脚本为如果是在ubuntu 24上，即使没有指定nightly也安装nightly版本
    if [ "$nightly" = true ]; then
        sudo_run apt install wezterm-nightly -y
        return
    else
        sudo_run apt install wezterm -y
    fi
}

# 飞书：请手动从官网下载 https://www.feishu.cn/download
# 原因：下载链接需要签名验证，无法保证自动化脚本长期可用

function setup-vscode(){
    # 使用微软官方 APT 仓库安装 VSCode，支持自动更新
    # 官方文档：https://code.visualstudio.com/docs/setup/linux
    
    # 添加 GPG 密钥
    wget $WGET_RETRY_OPTS -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /tmp/microsoft.gpg
    sudo_run install -D -o root -g root -m 644 /tmp/microsoft.gpg /usr/share/keyrings/microsoft.gpg
    rm -f /tmp/microsoft.gpg
    
    # 添加仓库
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/vscode stable main" | sudo_run tee /etc/apt/sources.list.d/vscode.list
    
    # 安装
    sudo_run apt-get update
    sudo_run apt-get install -y code
}