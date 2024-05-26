FROM ubuntu:20.04

SHELL ["/bin/bash", "-c"]

RUN apt-get update --fix-missing && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends apt-utils ca-certificates
COPY ./tsinghua.list /etc/apt/sources.list.d/tsinghua.list
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
RUN apt-get update --fix-missing && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends apt-utils ca-certificates build-essential gcc g++ gdb make cmake ninja-build \
    lsb-release software-properties-common gnupg gpg pkg-config wget curl unzip htop iotop fzf ripgrep net-tools snapd \
    vim tree git delta python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel 

# 下载zsh
RUN apt-get install -y --no-install-recommends zsh 

# 下载nvim
RUN wget https://github.com/neovim/neovim/releases/download/nightly/nvim-linux64.tar.gz -O nvim-linux64.tar.gz && \
    tar -xzvf nvim-linux64.tar.gz -C /opt/ && rm nvim-linux64.tar.gz && mv /opt/nvim-linux64 /opt/nvim

# Install LLVM and Clang
RUN LLVM_PATH=/usr/lib/llvm-14 PATH=${LLVM_PATH}/bin:$PATH && \
    wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && ./llvm.sh 14 && rm ./llvm.sh && \
    ln -s /usr/lib/llvm-14 /usr/lib/llvm && \
    ln -s /usr/lib/llvm/bin/clang /usr/bin/clang

# Install Golang and some tools
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
    wget https://dl.google.com/go/go1.22.3.linux-amd64.tar.gz -O go.tar.gz
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
    tar -xzvf go.tar.gz -C /opt && \
    rm go.tar.gz 
RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
    go install -v golang.org/x/tools/cmd/goimports@latest && \
    go install -v golang.org/x/tools/cmd/godoc@latest && \
    go install -v github.com/go-delve/delve/cmd/dlv@latest && \
    go install -v honnef.co/go/tools/cmd/staticcheck@latest && \
    go install -v golang.org/x/tools/gopls@latest


# Install Rust and some tools
RUN CARGO_BIN=/root/.cargo/bin && PATH=$CARGO_BIN:$PATH && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > rustup.sh && \
    chmod u+x ./rustup.sh && ./rustup.sh -y && rm ./rustup.sh && \
    rustup default nightly

RUN CARGO_BIN=/root/.cargo/bin && PATH=$CARGO_BIN:$PATH && \
    cargo install xdotter

COPY . /root/dotfiles
# 使用xdotter程序写入配置
WORKDIR /root/dotfiles
RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    xdotter deploy

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo install cargo-binstall parallel-disk-usage bat navi starship eza conceal 

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo install zoxide fd-find

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo binstall -y yazi-fm kondo macchina mcfly

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
