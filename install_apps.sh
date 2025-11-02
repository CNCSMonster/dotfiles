#!/usr/bin/env bash

# 说明, 该脚本应该在部署了dotfiles之后运行, 因为该脚本中会使用dotfiles中配置

set -exo pipefail

# --------- helpers ---------

# use ./install_app

function sudo_run() {
    # 如果当前用户是root用户, 则直接运行命令
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# 为部署xdotter做准备工作
function prepare-xdotter(){
    # 确保tar和wget已安装
    sudo_run apt-get update
    sudo_run apt-get install -y wget tar
    # 安装xdotter
    # 如果存在cargo-binstall, 使用cargo binstall下载
    if command -v cargo-binstall >/dev/null 2>&1; then
      cargo binstall xdotter -y
    # 否则如果存在cargo, 使用cargo 下载
    elif command -v cargo >/dev/null 2>&1; then
      cargo install xdotter
    # 否则，从链接下载xdotter, 链接为https://github.com/CNCSMonster/xdotter/releases/download/v0.0.9/xdotter-x86_64-unknown-linux-gnu.tar.gz
    else
      # 下载文件夹到临时目录
      wget https://github.com/CNCSMonster/xdotter/releases/download/v0.0.9/xdotter-x86_64-unknown-linux-gnu.tar.gz -O /tmp/xdotter.tar.gz
      # 解压到临时目录
      mkdir -p /tmp/xdotter
      tar -xzf /tmp/xdotter.tar.gz -C /tmp/xdotter
      # 移动解压后目录中xdotter 到 $HOME/.cargo/bin/
      mkdir -p "${HOME}/.cargo/bin"
      mv /tmp/xdotter/xdotter "${HOME}/.cargo/bin/"
    fi
}

  # 用xdotter部署dotfiles
deploy_dotfiles(){
  "${HOME}/.cargo/bin/xdotter" deploy -q
}


main() {
  export DEBIAN_FRONTEND=noninteractive
  export TZ=Asia/Shanghai
  prepare-xdotter
  deploy_dotfiles
  # 应用配置好的dotfiles后, 刷新当前shell环境(可能bash/zsh/fish等)
  . ~/.bashrc || true
  . ~/.zshrc || true
  load_setup
  install-common-tools
  install-neovim
  llvmup install 19
  install-rust nightly
  install-common-rust-tools
  setup-cargo-fuzz
  setup-uv
  # setup go,zig,node,pnpm, etc.
  mise install
}

main "$@"