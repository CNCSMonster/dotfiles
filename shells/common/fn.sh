# fzf jump
function fj() {
    # 如果有两个命令行参数，第一个参数将作为 `fd` 的输入，第二个参数将作为 `fzf` 的查询来源。

    # 检查命令行参数的数量
    if [ $# -eq 2 ]; then
        # 如果有两个参数，第一个作为 fd 的输入，第二个作为 fzf 的查询输入
        target=$(fd "$1" | fzf -q "$2")
    elif [ $# -eq 1 ]; then
        # 如果没有两个参数，使用第一个参数作为fzf查询输入
        target=$(fd . | fzf -q $1)
    else
        target=$(fd . | fzf)
    fi

    # 检查是否选择了目标目录
    if [ -n "$target" ]; then
        if [ -d "$target" ]; then
            cd "$target"
        else
            cd $(dirname $target)
        fi
    else
        echo "No target dir selected"
    fi

}

### 各种下载用的函数 ###

# 下载基础工具链
function setup_apt_get() {
    sudo apt-get update --fix-missing
    sudo apt-get upgrade -y
    sudo apt-get install -y --no-install-recommends \
        apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build \
        lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip \
        htop iotop fzf ripgrep net-tools snapd vim tree git delta python3 python3-pip \
        python3-venv python3-dev python3-setuptools python3-wheel zsh
}


# 用命令行参数指定版本号下载llvm
# 例如: install-llvm 18
function install-llvm() {
    local LLVM_VERSION=$1
    local LLVM_PATH="/usr/lib/llvm-${LLVM_VERSION}"
    sudo wget https://apt.llvm.org/llvm.sh | sudo sh -s -- "${LLVM_VERSION}"
    sudo ln -sfn "${LLVM_PATH}" /usr/lib/llvm
    sudo ln -sfn "${LLVM_PATH}/bin/clang" /usr/local/bin/clang
}

# 下载rust工具链
function setup-rust() {
  local RUSTUP_HOME="${HOME}/.rustup"
  local CARGO_HOME="${HOME}/.cargo"

  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "${CARGO_HOME}/env"

  rustup default nightly
  rustup component add rustfmt clippy
}

# 确保rustup已安装，如果未安装，则下载并安装
ensure_rustup() {
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
    rustup install $RUST_VERSION
    rustup default $RUST_VERSION
    rustup component add rustfmt clippy rust-analyzer
}

ensure_cargo_binstall() {
  local CARGO_BIN="${HOME}/.cargo/bin/cargo"
  if ! command -v cargo-binstall >/dev/null 2>&1; then
    "${CARGO_BIN}" install cargo-binstall
  fi
}

try_binstall_then_install() {
  local crate_name="$1"
  shift || true
  local extra_args=("$@")
  local CARGO_BIN="${HOME}/.cargo/bin/cargo"

  if command -v cargo-binstall >/dev/null 2>&1; then
    "${CARGO_BIN}" binstall -y "${extra_args[@]}" "${crate_name}" || \
    "${CARGO_BIN}" install "${extra_args[@]}" "${crate_name}"
  else
    "${CARGO_BIN}" install "${extra_args[@]}" "${crate_name}"
  fi
}


# 下载常用rust工具
function install_rust_app() {
    ensure_cargo_binstall
    # 批量安装：先 cargo binstall，再回退 cargo install
    local CRATES=(
        kondo jaq bob-nvim rust-script
        parallel-disk-usage bat navi
        starship eza conceal mise
        zoxide fd-find macchina yazi-fm fnm
        tree-sitter-cli tokei gen-mdbook-summary
    )

    for crate in "${CRATES[@]}"; do
        try_binstall_then_install "${crate}"
    done
}