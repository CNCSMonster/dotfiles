########################################################
# 各种下载安装的函数
########################################################

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
        python3-venv python3-dev python3-setuptools python3-wheel zsh
}

# 确保rustup已安装，如果未安装，则下载并安装
function setup-rustup() {
    local RUSTUP_HOME="${HOME}/.rustup"
    local CARGO_HOME="${HOME}/.cargo"
    if ! command -v rustup >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "${CARGO_HOME}/env"
    fi
}

# 根据命令行参数指定版本号下载rust
# 如果没有指定，默认下载nightly版本
# 例如: 
# install-rust 1.80.0
# install-rust nightly
function install-rust() {
    local RUST_VERSION=$1
    if [ -z "$RUST_VERSION" ]; then
        RUST_VERSION="nightly"
    fi
    setup-rustup
    rustup default $RUST_VERSION
    rustup component add rustfmt clippy rust-analyzer
}

# 下载比较新版的neovim
# 因为apt-get源里的版本太老了
function install-neovim(){
    # get target arch
    local ARCH=$(uname -m)
    wget https://github.com/neovim/neovim/releases/download/nightly/nvim-linux-${ARCH}.tar.gz -O /tmp/nvim-linux-${ARCH}.tar.gz
    tar -xzf /tmp/nvim-linux-${ARCH}.tar.gz -C /tmp
    # 删除旧版本
    sudo rm -rf /usr/local/neovim || true
    sudo mv /tmp/nvim-linux-${ARCH} /usr/local/neovim
    sudo ln -sf /usr/local/neovim/bin/nvim /usr/local/bin/nvim
}

ensure_cargo_binstall() {
  local CARGO_BIN="${HOME}/.cargo/bin/cargo"
  if ! command -v cargo-binstall >/dev/null 2>&1; then
    "${CARGO_BIN}" install cargo-binstall
  fi
}


# 下载常用rust的工具
function install-common-rust-tools() {
    ensure_cargo_binstall
    # 批量安装：先 cargo binstall，再回退 cargo install
    local CRATES=(
        kondo jaq rust-script
        parallel-disk-usage bat navi
        starship eza conceal mise kondo
        zoxide fd-find macchina yazi-fm fnm
        tree-sitter-cli tokei gen-mdbook-summary
    )
    for crate in "${CRATES[@]}"; do
        cargo binstall "${crate}" -y
    done
}

function setup-uv() {
  # On macOS and Linux.
  curl -LsSf https://astral.sh/uv/install.sh | sh
}

function setup-cargo-fuzz() {
  rustup component add llvm-tools-preview --toolchain nightly
  ensure_cargo_binstall
  cargo binstall cargo-fuzz grcov cargo-tarpaulin -y
}

