#!/usr/bin/env bash

# 说明, 该脚本应该在部署了dotfiles之后运行, 因为该脚本中会使用dotfiles中配置

set -euxo pipefail

# --------- helpers ---------

# 该方法应该在部署了dotfiles之后运行
setup_llvm_18() {
  local LLVM_VERSION="18"
  sudo "install-llvm" "${LLVM_VERSION}"
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
  sudo ln -sfn "${GO_DST}/go" /usr/local/go

  # 配置环境变量并持久化
  echo "export PATH=\"${GO_DST}/go/bin:\$PATH\"" >> "${HOME}/.profile"
  echo "export GOPROXY=\"https://goproxy.cn,direct\"" >> "${HOME}/.profile"
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
}

setup_uv() {
  curl --proto '=https' --tlsv1.2 -LsSf https://github.com/astral-sh/uv/releases/download/0.4.24/uv-installer.sh | sh
}

deploy_dotfiles() {
  sudo mkdir -p /root/dotfiles
  sudo cp -a . /root/dotfiles
  cd /root/dotfiles || exit 1
  # 安装xdotter
  ensure_cargo_binstall
  try_binstall_then_install xdotter
  xdotool deploy
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
  echo "export PATH=\"${HOME}/.fnm:\$PATH\"" >> "${HOME}/.profile"
  export PATH="${HOME}/.fnm:${PATH}"
  fnm install v22.2.0
  fnm use v22.2.0
}

main() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  apt_get
  setup_rust_nightly
  deploy_dotfiles
  setup_llvm_18
  install_rust_app
  fuzz_and_coverage
  setup_go
  setup_uv
}

main "$@"