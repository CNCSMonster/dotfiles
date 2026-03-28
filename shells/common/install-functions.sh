########################################################
# 各种下载安装的函数
########################################################

# 网络波动：curl/wget 统一重试与超时（Docker 构建及本机均生效）
# curl --retry 8: 内置重试 8 次，处理频繁的小网络波动（每 2 秒重试）
# wget --tries 8: 内置重试 8 次，处理频繁的小网络波动
# -C -: 断点续传，从断开的地方继续下载（节省带宽）
CURL_RETRY_OPTS="--retry 8 --retry-delay 2 --connect-timeout 30 --max-time 300"
WGET_RETRY_OPTS="--tries=8 --timeout=60 --connect-timeout=30 -c"

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

# 下载常用 rust 的工具
function install-common-rust-tools() {
    # 如果 CARGO_BUILD_JOBS 未设置，根据可用内存自动计算
    # Docker 环境：由 docker-build-test.sh 通过 --build-arg 传入
    # 本机环境：自动检测可用内存并计算
    if [ -z "$CARGO_BUILD_JOBS" ]; then
        local TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}')
        local AVAIL_MEM_KB=$(grep MemAvailable /proc/meminfo 2>/dev/null | awk '{print $2}')
        local AVAIL_MEM_GB=$((AVAIL_MEM_KB / 1024 / 1024))
        local TOTAL_CPU=$(nproc 2>/dev/null || echo 4)
        
        # 预留 2GB 系统开销，每 1.5GB 支持一个编译任务
        local USABLE_MEM=$((AVAIL_MEM_GB - 2))
        [ $USABLE_MEM -lt 1 ] && USABLE_MEM=1
        
        local BUILD_JOBS=$((USABLE_MEM * 10 / 15))
        [ $BUILD_JOBS -lt 1 ] && BUILD_JOBS=1
        
        # 不超过 CPU 核心数的 50%
        local MAX_JOBS=$((TOTAL_CPU / 2))
        [ $MAX_JOBS -lt 1 ] && MAX_JOBS=1
        [ $BUILD_JOBS -gt $MAX_JOBS ] && BUILD_JOBS=$MAX_JOBS
        
        # 最大 8 个并行（超过后收益递减）
        [ $BUILD_JOBS -gt 8 ] && BUILD_JOBS=8
        
        export CARGO_BUILD_JOBS=$BUILD_JOBS
        echo "自动设置 CARGO_BUILD_JOBS=$BUILD_JOBS (基于可用内存 ${AVAIL_MEM_GB}GB, CPU ${TOTAL_CPU} 核)"
    else
        echo "使用已有 CARGO_BUILD_JOBS=$CARGO_BUILD_JOBS"
    fi

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
    local TOTAL=${#CRATES[@]}
    local COUNT=0
    
    echo "开始安装 ${TOTAL} 个 Rust 工具..."
    for crate in "${CRATES[@]}"; do
        COUNT=$((COUNT + 1))
        echo "[${COUNT}/${TOTAL}] 正在安装：${crate}"
        if ! cargo binstall "${crate}" -y --disable-strategies compile; then
            echo "[${COUNT}/${TOTAL}] binstall 下载失败：${crate}，稍后从源码编译"
            FAILED+=("${crate}")
        fi
    done
    
    if [ ${#FAILED[@]} -gt 0 ]; then
        echo ""
        echo "以下 ${#FAILED[@]} 个 crate 无预编译二进制，开始源码编译："
        local TOTAL_FAILED=${#FAILED[@]}
        local FAILED_COUNT=0
        for crate in "${FAILED[@]}"; do
            FAILED_COUNT=$((FAILED_COUNT + 1))
            echo "[${FAILED_COUNT}/${TOTAL_FAILED}] 源码编译：${crate}"
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

# 安装 yq（固定版本，用户级安装，无需 sudo）
# yq 是一个便携式的数据文件处理器，支持 YAML/JSON/XML/TOML 等格式
# 官方文档：https://mikefarah.gitbook.io/yq/
# 安装位置：
#   - 二进制：~/.local/bin/yq
function install-yq() {
    local ARCH=$(uname -m)
    local YQ_ARCH=""
    case $ARCH in
        x86_64) YQ_ARCH="amd64" ;;
        aarch64) YQ_ARCH="arm64" ;;
        armv7l) YQ_ARCH="arm" ;;
        *)
            echo "不支持的架构：$ARCH"
            return 1
            ;;
    esac

    # 固定版本号（最新稳定版）
    local YQ_VERSION="v4.52.4"

    # 用户级路径
    local YQ_BIN_DIR="$HOME/.local/bin"

    # 检查是否已安装相同版本
    if [ -x "${YQ_BIN_DIR}/yq" ]; then
        local INSTALLED_VERSION=$("${YQ_BIN_DIR}/yq" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        if [ "$INSTALLED_VERSION" = "${YQ_VERSION#v}" ]; then
            echo "yq $YQ_VERSION 已安装，跳过"
            return 0
        fi
        echo "发现旧版本 $INSTALLED_VERSION，升级到 $YQ_VERSION..."
    fi

    echo "安装 yq $YQ_VERSION..."

    # 下载 yq（使用 GitHub 镜像加速）
    local YQ_URL="https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_${YQ_ARCH}"
    local DEST="/tmp/yq_linux_${YQ_ARCH}"

    github_download "$YQ_URL" "$DEST"

    # 安装二进制（无需 sudo）
    mkdir -p "$YQ_BIN_DIR"
    cp "$DEST" "$YQ_BIN_DIR/yq"
    chmod +x "$YQ_BIN_DIR/yq"

    # 清理临时文件
    rm -f "$DEST"

    # 验证安装
    if command -v yq >/dev/null 2>&1; then
        echo "yq 安装成功：$(yq --version)"
    else
        echo "yq 安装失败"
        return 1
    fi
}

# 安装 Helix 编辑器（固定版本，用户级安装，无需 sudo）
# Helix 是一个现代化的模态文本编辑器，开箱即用，无需配置
# 官方文档：https://helix-editor.com/
# 安装位置：
#   - 二进制：~/.cargo/bin/hx
#   - runtime: ~/.config/helix/runtime
function install-helix() {
    local ARCH=$(uname -m)
    local HELIX_ARCH=""
    case $ARCH in
        x86_64) HELIX_ARCH="x86_64" ;;
        aarch64) HELIX_ARCH="aarch64" ;;
        *)
            echo "不支持的架构：$ARCH"
            return 1
            ;;
    esac

    # 固定版本号（最新稳定版 2025-07）
    local HELIX_VERSION="25.07.1"

    # 用户级路径
    local HELIX_BIN_DIR="$HOME/.cargo/bin"
    local HELIX_RUNTIME_DIR="$HOME/.config/helix/runtime"
    local HELIX_TMP="/tmp/helix-${HELIX_VERSION}"

    # 检查是否已安装相同版本
    if [ -x "${HELIX_BIN_DIR}/hx" ]; then
        local INSTALLED_VERSION=$("${HELIX_BIN_DIR}/hx" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        if [ "$INSTALLED_VERSION" = "$HELIX_VERSION" ]; then
            echo "Helix $HELIX_VERSION 已安装，跳过"
            return 0
        fi
        echo "发现旧版本 $INSTALLED_VERSION，升级到 $HELIX_VERSION..."
    fi

    echo "安装 Helix $HELIX_VERSION..."

    # 下载 Helix（使用 GitHub 镜像加速）
    # 注意：Helix 使用 .tar.xz 格式压缩
    local HELIX_URL="https://github.com/helix-editor/helix/releases/download/${HELIX_VERSION}/helix-${HELIX_VERSION}-${HELIX_ARCH}-linux.tar.xz"
    local DEST="/tmp/helix-${HELIX_VERSION}.tar.xz"

    github_download "$HELIX_URL" "$DEST"

    # 解压（目录名为 helix-VERSION-ARCH-linux）
    local HELIX_TMP="/tmp/helix-${HELIX_VERSION}-${HELIX_ARCH}-linux"
    tar -xJf "$DEST" -C /tmp

    # 安装二进制（无需 sudo）
    mkdir -p "$HELIX_BIN_DIR"
    cp "${HELIX_TMP}/hx" "$HELIX_BIN_DIR/"

    # 安装 runtime（无需 sudo）
    mkdir -p "$HELIX_RUNTIME_DIR"
    cp -r "${HELIX_TMP}/runtime/"* "$HELIX_RUNTIME_DIR/"

    # 清理临时文件
    rm -rf "$HELIX_TMP" "$DEST"

    # 验证安装
    if command -v hx >/dev/null 2>&1; then
        echo "Helix 安装成功：$(hx --version)"
    else
        echo "Helix 安装失败"
        return 1
    fi
}

# 安装 GitUI（Rust 编写，使用 cargo 安装）
# GitUI 是一个快速的 Git TUI 客户端，Rust 编写
# 官方文档：https://github.com/extrawurst/gitui
# 安装位置：~/.cargo/bin/gitui
#
# 策略：
# 1. 先尝试 cargo binstall 下载预编译二进制（快速）
# 2. 如果失败，则 cargo install 从源码编译（慢但稳定）
# 3. 如果最新版本编译失败，尝试往下找一个版本
function install-gitui() {
    ensure_cargo_binstall

    # 检查是否已安装
    if command -v gitui >/dev/null 2>&1; then
        local INSTALLED_VERSION=$(gitui --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        if [ -n "$INSTALLED_VERSION" ]; then
            echo "GitUI v$INSTALLED_VERSION 已安装，跳过"
            return 0
        fi
    fi

    echo "安装 GitUI..."

    # 尝试安装，支持版本回退
    local VERSIONS=("gitui" "gitui@0.27.0" "gitui@0.26.3")
    local INSTALLED=false

    for version_spec in "${VERSIONS[@]}"; do
        echo "尝试安装：$version_spec"
        
        # 先尝试 cargo binstall
        if cargo binstall "$version_spec" -y --disable-strategies compile 2>/dev/null; then
            if command -v gitui >/dev/null 2>&1; then
                echo "GitUI 安装成功 (cargo binstall): $(gitui --version)"
                INSTALLED=true
                break
            fi
        fi
        
        # binstall 失败，尝试 cargo install
        echo "cargo binstall 失败，尝试 cargo install..."
        if cargo install "$version_spec" --locked 2>/dev/null; then
            if command -v gitui >/dev/null 2>&1; then
                echo "GitUI 安装成功 (cargo install): $(gitui --version)"
                INSTALLED=true
                break
            fi
        fi
        
        echo "$version_spec 安装失败，尝试下一个版本..."
    done

    if [ "$INSTALLED" = true ]; then
        return 0
    else
        echo "GitUI 安装失败：所有版本都失败"
        return 1
    fi
}