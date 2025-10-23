#!/usr/bin/env bash

set -euxo pipefail

# --------- helpers ---------

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

apt_get() {
  apt-get update --fix-missing
  apt-get upgrade -y
  apt-get install -y --no-install-recommends \
    apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build \
    lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip \
    htop iotop fzf ripgrep net-tools snapd vim tree git delta python3 python3-pip \
    python3-venv python3-dev python3-setuptools python3-wheel zsh
}

setup_tsinghua_mirror() {
  mkdir -p /etc/apt/sources.list.d
  cp ./tsinghua.list /etc/apt/sources.list.d/tsinghua.list
}

setup_llvm_18() {
  local LLVM_PATH="/usr/lib/llvm-18"
  local LLVM_VERSION="18"
  wget https://apt.llvm.org/llvm.sh
  chmod +x llvm.sh
  ./llvm.sh "${LLVM_VERSION}"
  rm -f llvm.sh
  ln -sfn "${LLVM_PATH}" /usr/lib/llvm
  ln -sfn "${LLVM_PATH}/bin/clang" /usr/local/bin/clang
}

setup_go() {
  local GO_VERSION="1.22.3"
  local GO_ARCH="linux-amd64"
  local GO_TAR="go${GO_VERSION}.${GO_ARCH}.tar.gz"
  local GO_DST="/usr/local"

  wget "https://dl.google.com/go/${GO_TAR}" -O go.tar.gz
  tar -xzf go.tar.gz -C "${GO_DST}"
  rm -f go.tar.gz

  # 可选：创建符号链接便于全局使用（若希望用 /opt/go 请自行修改路径）
  ln -sfn "${GO_DST}/go" /usr/local/go

  # 配置环境变量（非持久化，仅对当前 RUN 生效；持久化请写入镜像 ENV 或 shell 配置）
  export PATH="${GO_DST}/go/bin:${PATH}"
  export GOPROXY="https://goproxy.cn,direct"

  go install -v golang.org/x/tools/cmd/goimports@latest
  go install -v golang.org/x/tools/cmd/godoc@latest
  go install -v github.com/go-delve/delve/cmd/dlv@latest
  go install -v honnef.co/go/tools/cmd/staticcheck@latest
  go install -v golang.org/x/tools/gopls@latest
}

setup_rust_nightly() {
  local RUSTUP_HOME="${HOME}/.rustup"
  local CARGO_HOME="${HOME}/.cargo"

  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "${CARGO_HOME}/env"

  rustup default nightly
  rustup component add rustfmt clippy

  # 示例工具：优先用 cargo-binstall，失败回退 cargo install
  ensure_cargo_binstall
  try_binstall_then_install xdotool
}

setup_uv() {
  curl --proto '=https' --tlsv1.2 -LsSf https://github.com/astral-sh/uv/releases/download/0.4.24/uv-installer.sh | sh
}

deploy_dotfiles() {
  mkdir -p /root/dotfiles
  cp -a . /root/dotfiles
  cd /root/dotfiles || exit 1
  # 若 xdotool 未在 PATH，可显式使用 ~/.cargo/bin/xdotool
  ~/.cargo/bin/xdotool deploy
}

install_rust_app() {
  ensure_cargo_binstall

  # 批量安装：先 cargo binstall，再回退 cargo install
  local CRATES=(
    kondo jaq bob-nvim rust-script
    parallel-disk-usage bat navi
    starship eza conceal
    zoxide fd-find macchina yazi-fm fnm
    tree-sitter-cli tokei gen-mdbook-summar
  )

  for crate in "${CRATES[@]}"; do
    try_binstall_then_install "${crate}"
  done
}

fuzz_and_coverage() {
  rustup component add llvm-tools-preview --toolchain nightly
  ensure_cargo_binstall
  try_binstall_then_install cargo-fuzz
  try_binstall_then_install grcov
  try_binstall_then_install cargo-tarpaulin
}

install_node_via_fnm() {
  # 确保使用已安装的 fnm
  export PATH="${HOME}/.fnm:${PATH}"
  fnm install v22.2.0
  fnm use v22.2.0
}

main() {
  setup_tsinghua_mirror
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  apt_get
  setup_llvm_18
  setup_go
  setup_rust_nightly
  setup_uv
  deploy_dotfiles
  install_rust_app
  fuzz_and_coverage
  install_node_via_fnm
}

main "$@"