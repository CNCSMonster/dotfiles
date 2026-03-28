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


########################################################
# 通用 Rust/Cargo 工具安装函数
########################################################

# 统一的 cargo 工具安装函数（推荐模式）
# 使用 --disable-strategies compile，下载失败后统一 cargo install
#
# 优势：
# 1. 预编译下载和源码编译分离，日志清晰
# 2. 避免 GitHub API 限流导致的时间浪费（每个无预编译的 crate 等待 120 秒）
# 3. 可以统一设置 CARGO_BUILD_JOBS 并行编译
# 4. 使用 --locked 标志，确保可复现性
#
# 参数：多个 crate 名称，可带版本号 (例如：bat@0.26.1 eza zoxide@0.9.8)
# 示例：
#   cargo_install_common bat@0.26.1 eza
#   cargo_install_common "gitui@0.28.1"
function cargo_install_common() {
    ensure_cargo_binstall
    
    local CRATES=("$@")
    local TOTAL=${#CRATES[@]}
    local COUNT=0
    local SUCCESS=0
    local FAILED=()
    
    echo "开始安装 ${TOTAL} 个 Rust 工具..."
    for crate in "${CRATES[@]}"; do
        COUNT=$((COUNT + 1))
        echo "[${COUNT}/${TOTAL}] 正在安装：${crate}"
        
        # 只尝试预编译二进制（GitHub Releases + QuickInstall）
        # 禁用 compile 策略，避免无预编译时浪费 120 秒等待时间
        if cargo binstall "${crate}" -y --disable-strategies compile 2>/dev/null; then
            echo "[${COUNT}/${TOTAL}] ✅ 下载成功：${crate} (预编译)"
            SUCCESS=$((SUCCESS + 1))
        else
            echo "[${COUNT}/${TOTAL}] ⚠️ 无预编译：${crate}，稍后源码编译"
            FAILED+=("${crate}")
        fi
    done
    
    # 统一编译失败的 crate
    if [ ${#FAILED[@]} -gt 0 ]; then
        echo ""
        echo "=========================================="
        echo "开始源码编译 ${#FAILED[@]} 个 crate（使用 --locked）..."
        echo "=========================================="
        
        local TOTAL_FAILED=${#FAILED[@]}
        local FAILED_COUNT=0
        local COMPILED=0
        
        for crate in "${FAILED[@]}"; do
            FAILED_COUNT=$((FAILED_COUNT + 1))
            echo "[${FAILED_COUNT}/${TOTAL_FAILED}] 源码编译：${crate}"
            
            # 使用 --locked 确保可复现性
            if cargo install "${crate}" --locked 2>/dev/null; then
                echo "[${FAILED_COUNT}/${TOTAL_FAILED}] ✅ 编译成功：${crate}"
                COMPILED=$((COMPILED + 1))
            else
                # --locked 失败则尝试不带 --locked（兼容性回退）
                echo "[${FAILED_COUNT}/${TOTAL_FAILED}] ⚠️ --locked 失败，尝试不带 --locked..."
                if cargo install "${crate}" 2>/dev/null; then
                    echo "[${FAILED_COUNT}/${TOTAL_FAILED}] ✅ 编译成功：${crate}"
                    COMPILED=$((COMPILED + 1))
                else
                    echo "[${FAILED_COUNT}/${TOTAL_FAILED}] ❌ 编译失败：${crate}"
                fi
            fi
        done
        
        SUCCESS=$((SUCCESS + COMPILED))
    fi
    
    echo ""
    echo "=========================================="
    echo "安装完成：${SUCCESS}/${TOTAL} 成功"
    
    if [ $SUCCESS -eq $TOTAL ]; then
        echo "全部成功！"
        return 0
    else
        local FAILED_TOTAL=$((TOTAL - SUCCESS))
        echo "失败 (${FAILED_TOTAL}): 请手动安装"
        return 1
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

# 自动计算 Cargo 编译任务数（基于可用内存和 CPU 核心数）
# 用法：setup-cargo-build-env
# 效果：设置 CARGO_BUILD_JOBS 环境变量
#
# 计算逻辑：
# - 预留 2GB 系统开销
# - 每 1.5GB 内存支持 1 个编译任务
# - 不超过 CPU 核心数的 50%
# - 最大不超过 8 个并行（超过后收益递减）
function setup-cargo-build-env() {
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
}

# 下载常用 rust 的工具
function install-common-rust-tools() {
    # 设置编译环境（自动计算 CARGO_BUILD_JOBS）
    setup-cargo-build-env

    # 使用统一的 cargo 安装函数
    # 策略：--disable-strategies compile，下载失败后统一 cargo install
    #
    # 优势：
    # 1. 预编译下载和源码编译分离，日志清晰
    # 2. 避免 GitHub API 限流导致的时间浪费
    # 3. 使用 --locked 标志，确保可复现性
    #
    # 固定版本号避免上游更新带来的兼容性问题
    # 最后验证：2026-03-28，Docker Ubuntu 24.04 + Rust stable
    cargo_install_common \
        kondo@0.9.0 \
        jaq@2.3.0 \
        rust-script@0.36.0 \
        parallel-disk-usage@0.21.1 \
        bat@0.26.1 \
        navi@2.24.0 \
        mcfly@0.9.4 \
        starship@1.23.0 \
        eza@0.21.0 \
        conceal@0.5.1 \
        zoxide@0.9.8 \
        fd-find@10.2.0 \
        macchina@6.0.0 \
        fnm@1.38.1 \
        tree-sitter-cli@0.25.4 \
        tokei@13.0.0-alpha.9 \
        gen-mdbook-summary@0.0.6 \
        mise@2026.2.15 \
        uv@0.10.10 \
        gitui@0.28.1 \
        cargo-audit

    local MAIN_TOOLS_STATUS=$?

    setup-yazi
    local YAZI_STATUS=$?

    # 如果主工具安装有失败，返回错误（用于 setup.sh 判断）
    if [ $MAIN_TOOLS_STATUS -ne 0 ]; then
        echo "⚠️  警告：部分 Rust 主工具安装失败，请手动安装"
        return 1
    fi

    # yazi 失败不影响主工具，但记录日志
    if [ $YAZI_STATUS -ne 0 ]; then
        echo "⚠️  警告：yazi 安装失败，请手动安装"
    fi

    return 0
}

function setup-yazi(){
    # yazi-fm 是 yazi 的主程序包名，yazi-cli 是 ya 命令行工具
    # 使用统一的 cargo 安装函数
    cargo_install_common yazi-fm yazi-cli
    return $?
}

function setup-cargo-fuzz() {
  rustup component add llvm-tools-preview --toolchain nightly
  # 设置编译环境（自动计算 CARGO_BUILD_JOBS）
  setup-cargo-build-env
  # 使用统一的 cargo 安装函数
  cargo_install_common cargo-fuzz grcov cargo-tarpaulin
  return $?
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

    # 编译 tree-sitter 语法文件
    echo "编译 Helix tree-sitter 语法..."
    hx --grammar fetch >/dev/null 2>&1 || true
    hx --grammar build >/dev/null 2>&1 || true

    # 下载 languages.toml 和 themes（从官方仓库）
    # 这些文件在官方 tarball 中不包含，需要单独下载
    echo "下载 Helix languages.toml 和 themes..."
    local HELIX_RUNTIME_TMP="/tmp/helix-runtime-files"
    git clone --depth 1 --filter=blob:none --sparse \
        "https://github.com/helix-editor/helix.git" "$HELIX_RUNTIME_TMP" >/dev/null 2>&1
    if [ -d "$HELIX_RUNTIME_TMP" ]; then
        cd "$HELIX_RUNTIME_TMP"
        git sparse-checkout set runtime/languages.toml runtime/themes >/dev/null 2>&1
        cp runtime/languages.toml "$HOME/.config/helix/"
        cp -r runtime/themes "$HELIX_RUNTIME_DIR/"
        cd - >/dev/null
        rm -rf "$HELIX_RUNTIME_TMP"
    fi

    # 验证安装
    if command -v hx >/dev/null 2>&1; then
        echo "Helix 安装成功：$(hx --version)"
    else
        echo "Helix 安装失败"
        return 1
    fi
}

# 安装 Marksman（Markdown LSP 服务器）
# Marksman 是一个 Markdown 语言服务器，提供：
# - 文档大纲（outline/symbols）
# - 跨文件引用
# - 自动补全
# 官方文档：https://github.com/artempyanykh/marksman
function install-marksman() {
    local MARKSMAN_VERSION="2026-02-08"
    local ARCH=$(uname -m)
    local MARKSMAN_ARCH=""
    case $ARCH in
        x86_64) MARKSMAN_ARCH="x64" ;;
        aarch64) MARKSMAN_ARCH="arm64" ;;
        *)
            echo "不支持的架构：$ARCH"
            return 1
            ;;
    esac

    local MARKSMAN_BIN_DIR="$HOME/.cargo/bin"
    local MARKSMAN_TMP="/tmp/marksman"

    # 检查是否已安装
    if [ -x "${MARKSMAN_BIN_DIR}/marksman" ]; then
        echo "marksman 已安装，跳过"
        return 0
    fi

    echo "安装 marksman ${MARKSMAN_VERSION}..."

    # 下载预编译二进制
    local MARKSMAN_URL="https://github.com/artempyanykh/marksman/releases/download/${MARKSMAN_VERSION}/marksman-linux-${MARKSMAN_ARCH}"
    mkdir -p "$MARKSMAN_TMP"
    github_download "$MARKSMAN_URL" "${MARKSMAN_TMP}/marksman"

    # 安装
    chmod +x "${MARKSMAN_TMP}/marksman"
    mv "${MARKSMAN_TMP}/marksman" "$MARKSMAN_BIN_DIR/"

    # 清理
    rm -rf "$MARKSMAN_TMP"

    # 验证
    if command -v marksman >/dev/null 2>&1; then
        echo "marksman 安装成功：$(marksman --version)"
    else
        echo "marksman 安装失败"
        return 1
    fi
}

# ========== LSP 服务器安装函数 ==========

# 安装 TypeScript/JavaScript 语言服务器
# 实现语言：TypeScript
# 安装方式：npm (mise 已安装 node 和 pnpm)
function install-typescript-lsp() {
    local LSP_BIN_DIR="$HOME/.local/bin/lsp"
    mkdir -p "$LSP_BIN_DIR"

    # 检查是否已安装
    if command -v typescript-language-server >/dev/null 2>&1; then
        echo "typescript-language-server 已安装，跳过"
        return 0
    fi

    echo "安装 typescript-language-server..."

    # 使用 pnpm 全局安装（pnpm 由 mise 管理）
    pnpm add -g typescript-language-server typescript 2>/dev/null || \
    npm install -g typescript-language-server typescript 2>/dev/null || {
        echo "typescript-language-server 安装失败"
        return 1
    }

    echo "typescript-language-server 安装成功：$(typescript-language-server --version)"
}

# 安装 Python 语言服务器 (Pyright)
# 实现语言：TypeScript
# 安装方式：npm (比 pip 版本更新)
function install-pyright() {
    # 检查是否已安装
    if command -v pyright >/dev/null 2>&1; then
        echo "pyright 已安装，跳过"
        return 0
    fi

    echo "安装 pyright..."

    # 使用 pnpm 全局安装
    pnpm add -g pyright 2>/dev/null || \
    npm install -g pyright 2>/dev/null || {
        echo "pyright 安装失败"
        return 1
    }

    echo "pyright 安装成功：$(pyright --version)"
}

# 安装 Go 语言服务器 (gopls)
# 实现语言：Go
# 安装方式：go install
function install-gopls() {
    # 检查是否已安装
    if command -v gopls >/dev/null 2>&1; then
        echo "gopls 已安装，跳过"
        return 0
    fi

    echo "安装 gopls..."

    # 使用 go install 安装
    export GOPATH="$HOME/.go"
    export PATH="$GOPATH/bin:$PATH"
    go install golang.org/x/tools/gopls@latest 2>/dev/null || {
        echo "gopls 安装失败"
        return 1
    }

    # 复制到 cargo bin 目录以便 Helix 找到
    mkdir -p "$HOME/.cargo/bin"
    cp "$GOPATH/bin/gopls" "$HOME/.cargo/bin/" 2>/dev/null || true

    echo "gopls 安装成功：$(gopls version)"
}

# 安装 Zig 语言服务器 (zls)
# 实现语言：Zig
# 安装方式：下载预编译二进制
function install-zls() {
    local ZLS_VERSION="0.15.1"
    local ARCH=$(uname -m)
    local ZLS_ARCH=""
    case $ARCH in
        x86_64) ZLS_ARCH="x86_64" ;;
        aarch64) ZLS_ARCH="aarch64" ;;
        *)
            echo "不支持的架构：$ARCH"
            return 1
            ;;
    esac

    local ZLS_BIN_DIR="$HOME/.cargo/bin"
    local ZLS_TMP="/tmp/zls"

    # 检查是否已安装
    if command -v zls >/dev/null 2>&1; then
        echo "zls 已安装，跳过"
        return 0
    fi

    echo "安装 zls ${ZLS_VERSION}..."

    # 下载预编译二进制
    local ZLS_URL="https://github.com/zigtools/zls/releases/download/${ZLS_VERSION}/zls-${ZLS_ARCH}-linux.tar.xz"
    mkdir -p "$ZLS_TMP"

    github_download "$ZLS_URL" "${ZLS_TMP}/zls.tar.xz"

    # 解压
    tar -xf "${ZLS_TMP}/zls.tar.xz" -C "$ZLS_TMP"

    # 安装
    mv "${ZLS_TMP}/zls" "$ZLS_BIN_DIR/" 2>/dev/null || {
        # 如果解压后目录不同，尝试查找
        find "$ZLS_TMP" -name "zls" -type f -executable -exec mv {} "$ZLS_BIN_DIR/" \;
    }

    # 清理
    rm -rf "$ZLS_TMP"

    # 验证
    if command -v zls >/dev/null 2>&1; then
        echo "zls 安装成功：$(zls --version)"
    else
        echo "zls 安装失败"
        return 1
    fi
}

# 安装 YAML 语言服务器
# 实现语言：TypeScript
# 安装方式：npm
function install-yaml-lsp() {
    # 检查是否已安装
    if command -v yaml-language-server >/dev/null 2>&1; then
        echo "yaml-language-server 已安装，跳过"
        return 0
    fi

    echo "安装 yaml-language-server..."

    # 使用 pnpm 全局安装
    pnpm add -g yaml-language-server 2>/dev/null || \
    npm install -g yaml-language-server 2>/dev/null || {
        echo "yaml-language-server 安装失败"
        return 1
    }

    echo "yaml-language-server 安装成功：$(yaml-language-server --version)"
}

# 安装 TOML 语言服务器 (taplo)
# 实现语言：Rust
# 安装方式：cargo binstall (预编译) 或 cargo install
function install-taplo() {
    local TAPLO_BIN_DIR="$HOME/.cargo/bin"

    # 检查是否已安装
    if command -v taplo >/dev/null 2>&1; then
        echo "taplo 已安装，跳过"
        return 0
    fi

    echo "安装 taplo..."

    # 优先使用 cargo binstall (预编译二进制)
    if command -v cargo-binstall >/dev/null 2>&1; then
        cargo binstall taplo-cli -y --no-symlinks 2>/dev/null && {
            mv "$TAPLO_BIN_DIR/taplo-cli" "$TAPLO_BIN_DIR/taplo" 2>/dev/null || true
            echo "taplo 安装成功 (binstall): $(taplo --version)"
            return 0
        }
    fi

    # 回退到 cargo install
    cargo install taplo-cli 2>/dev/null || {
        echo "taplo 安装失败"
        return 1
    }

    echo "taplo 安装成功：$(taplo --version)"
}

# 安装 Lua 语言服务器
# 实现语言：Lua/C++
# 安装方式：下载预编译二进制
function install-lua-lsp() {
    local LUA_LSP_VERSION="3.17.1"
    local ARCH=$(uname -m)
    local LUA_LSP_ARCH=""
    case $ARCH in
        x86_64) LUA_LSP_ARCH="x64" ;;
        aarch64) LUA_LSP_ARCH="arm64" ;;
        *)
            echo "不支持的架构：$ARCH"
            return 1
            ;;
    esac

    local LUA_LSP_BIN_DIR="$HOME/.cargo/bin"
    local LUA_LSP_RUNTIME_DIR="$HOME/.local/share/lua-language-server"
    local LUA_LSP_TMP="/tmp/lua-language-server"

    # 检查是否已安装
    if command -v lua-language-server >/dev/null 2>&1; then
        echo "lua-language-server 已安装，跳过"
        return 0
    fi

    echo "安装 lua-language-server ${LUA_LSP_VERSION}..."

    # 下载预编译二进制
    local LUA_LSP_URL="https://github.com/LuaLS/lua-language-server/releases/download/${LUA_LSP_VERSION}/lua-language-server-${LUA_LSP_VERSION}-linux-${LUA_LSP_ARCH}.tar.gz"
    mkdir -p "$LUA_LSP_TMP"
    mkdir -p "$LUA_LSP_RUNTIME_DIR"

    github_download "$LUA_LSP_URL" "${LUA_LSP_TMP}/lua-language-server.tar.gz"

    # 解压到运行时目录
    tar -xzf "${LUA_LSP_TMP}/lua-language-server.tar.gz" -C "$LUA_LSP_RUNTIME_DIR"

    # 创建启动脚本
    cat > "${LUA_LSP_BIN_DIR}/lua-language-server" << EOF
#!/bin/bash
exec "$LUA_LSP_RUNTIME_DIR/bin/lua-language-server" "\$@"
EOF
    chmod +x "${LUA_LSP_BIN_DIR}/lua-language-server"

    # 清理
    rm -rf "$LUA_LSP_TMP"

    # 验证
    if command -v lua-language-server >/dev/null 2>&1; then
        echo "lua-language-server 安装成功：$(lua-language-server --version)"
    else
        echo "lua-language-server 安装失败"
        return 1
    fi
}

# GitUI 已移动到 install-common-rust-tools 中统一安装
# 使用固定版本 gitui@0.28.1
# 如果安装失败，请开发者手动测试合适的版本并更新 install-common-rust-tools