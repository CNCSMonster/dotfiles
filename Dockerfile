FROM ubuntu:20.04

SHELL ["/bin/bash", "-c"]

RUN apt-get update --fix-missing && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends apt-utils ca-certificates
COPY ./tsinghua.list /etc/apt/sources.list.d/tsinghua.list
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
RUN apt-get update --fix-missing && apt-get upgrade -y && \
    apt-get install --fix-missing -y --no-install-recommends apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build \
    lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip htop iotop fzf ripgrep net-tools snapd \
    vim tree git delta python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel

# 下载zsh
RUN apt-get install -y --no-install-recommends zsh 

# Install LLVM and Clang
RUN LLVM_PATH=/usr/lib/llvm-18 PATH=${LLVM_PATH}/bin:$PATH && \
    LLVM_VERSION=18 &&\
    wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && ./llvm.sh ${LLVM_VERSION} && rm ./llvm.sh && \
    ln -s /usr/lib/llvm-${LLVM_VERSION} /usr/lib/llvm && \
    ln -s /usr/lib/llvm/bin/clang /usr/local/bin/clang

# Install Golang and some tools
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
    wget https://dl.google.com/go/go1.22.3.linux-amd64.tar.gz -O go.tar.gz
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
    tar -xzvf go.tar.gz -C /opt && \
    rm go.tar.gz 
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY="https://goproxy.cn,direct" && \
    go install -v golang.org/x/tools/cmd/goimports@latest && \
    go install -v golang.org/x/tools/cmd/godoc@latest && \
    go install -v github.com/go-delve/delve/cmd/dlv@latest && \
    go install -v honnef.co/go/tools/cmd/staticcheck@latest && \
    go install -v golang.org/x/tools/gopls@latest


# Install Rust and some tools
RUN RUSTUP_DIST_SERVER="https://rsproxy.cn" RUSTUP_UPDATE_ROOT="https://rsproxy.cn/rustup" && \
    CARGO_BIN=/root/.cargo/bin && PATH=$CARGO_BIN:$PATH && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > rustup.sh && \
    chmod u+x ./rustup.sh && ./rustup.sh -y && rm ./rustup.sh && \
    rustup default nightly

RUN CARGO_BIN=/root/.cargo/bin && PATH=$CARGO_BIN:$PATH && \
    cargo install xdotter

# Install uv for python-pros
RUN curl --proto '=https' --tlsv1.2 -LsSf https://github.com/astral-sh/uv/releases/download/0.4.24/uv-installer.sh | sh

COPY . /root/dotfiles

# 使用xdotter程序写入配置
WORKDIR /root/dotfiles
RUN /root/.cargo/bin/xdotter deploy

RUN /root/.cargo/bin/cargo install cargo-binstall parallel-disk-usage bat navi

RUN /root/.cargo/bin/cargo install starship eza conceal 

RUN /root/.cargo/bin/cargo install zoxide fd-find macchina yazi-fm fnm

RUN /root/.cargo/bin/cargo install tree-sitter-cli tokei gen-mdbook-summary

RUN /root/.cargo/bin/cargo binstall -y kondo jaq bob-nvim

RUN /root/.cargo/bin/cargo binstall -y rust-script

# 添加fuzz工具链
RUN /root/.cargo/bin/rustup component add llvm-tools-preview --toolchain nightly&& \
    /root/.cargo/bin/cargo install cargo-fuzz grcov

# 添加单元测试覆盖率报告生成工具
RUN /root/.cargo/bin/cargo install cargo-tarpaulin

# 使用bob-nvim安装nvim, 使用fnm安装node
RUN PATH=/root/.cargo/bin:$PATH && \
    bob install stable && bob use stable && \
    fnm install v22.2.0

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
