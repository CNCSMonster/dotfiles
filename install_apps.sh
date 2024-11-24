#!/usr/bin/env zsh

# 更新和升级系统
apt-get update --fix-missing && apt-get upgrade -y &&
    apt-get install -y --no-install-recommends apt-utils ca-certificates

# 复制清华源列表
COPY ./tsinghua.list /etc/apt/sources.list.d/tsinghua.list

# 设置环境变量
export DEBIAN_FRONTEND=noninteractive
export TZ=Asia/Shanghai

# 安装基本工具
apt-get update --fix-missing && apt-get upgrade -y &&
    apt-get install --fix-missing -y --no-install-recommends apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build \
        lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip htop iotop fzf ripgrep net-tools snapd \
        vim tree git delta python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel

# 下载和安装zsh
apt-get install -y --no-install-recommends zsh

# 安装LLVM和Clang
LLVM_PATH=/usr/lib/llvm-18
PATH=${LLVM_PATH}/bin:$PATH
LLVM_VERSION=18
wget https://apt.llvm.org/llvm.sh
chmod +x llvm.sh
./llvm.sh ${LLVM_VERSION}
rm ./llvm.sh
ln -s /usr/lib/llvm-${LLVM_VERSION} /usr/lib/llvm
ln -s /usr/lib/llvm/bin/clang /usr/local/bin/clang

# 安装Golang和一些工具
GOBIN=/opt/go/bin
PATH=/opt/go/bin:$PATH
GORPOXY=https://goproxy.cn
wget https://dl.google.com/go/go1.22.3.linux-amd64.tar.gz -O go.tar.gz
tar -xzvf go.tar.gz -C /opt
rm go.tar.gz
GOBIN=/opt/go/bin
PATH=/opt/go/bin:$PATH
GORPOXY="https://goproxy.cn,direct"
go install -v golang.org/x/tools/cmd/goimports@latest
go install -v golang.org/x/tools/cmd/godoc@latest
go install -v github.com/go-delve/delve/cmd/dlv@latest
go install -v honnef.co/go/tools/cmd/staticcheck@latest
go install -v golang.org/x/tools/gopls@latest

# 安装Rust和一些工具
RUSTUP_DIST_SERVER="https://rsproxy.cn"
RUSTUP_UPDATE_ROOT="https://rsproxy.cn/rustup"
CARGO_BIN=/root/.cargo/bin
PATH=$CARGO_BIN:$PATH
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs >rustup.sh
chmod u+x ./rustup.sh
./rustup.sh -y
rm ./rustup.sh
rustup default nightly

CARGO_BIN=/root/.cargo/bin
PATH=$CARGO_BIN:$PATH
cargo install xdotter

# 安装uv for python-pros
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/astral-sh/uv/releases/download/0.4.24/uv-installer.sh | sh

# 复制dotfiles
cargo install cargo-binstall parallel-disk-usage bat navi \
    starship eza conceal \
    zoxide fd-find macchina yazi-fm fnm \
    tree-sitter-cli tokei gen-mdbook-summary
cargo binstall -y kondo jaq bob-nvim rust-script
