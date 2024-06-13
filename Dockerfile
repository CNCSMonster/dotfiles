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
    vim tree git delta python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel clang

# 下载zsh
RUN apt-get install -y --no-install-recommends zsh 

# Install LLVM and Clang
# RUN LLVM_PATH=/usr/lib/llvm-18 PATH=${LLVM_PATH}/bin:$PATH && \
#     LLVM_VERSION=18 &&\
#     wget https://apt.llvm.org/llvm.sh && \
#     chmod +x llvm.sh && ./llvm.sh 18 && rm ./llvm.sh && \
#     ln -s /usr/lib/llvm-18 /usr/lib/llvm && \
#     ln -s /usr/lib/llvm/bin/clang /usr/local/bin/clang

# Install Golang and some tools
# RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
#     wget https://dl.google.com/go/go1.22.3.linux-amd64.tar.gz -O go.tar.gz
# RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
#     tar -xzvf go.tar.gz -C /opt && \
#     rm go.tar.gz 
# RUN GOBIN=/opt/go/bin PATH=/opt/go/bin:$PATH GORPOXY=https://goproxy.cn && \
#     go install -v golang.org/x/tools/cmd/goimports@latest && \
#     go install -v golang.org/x/tools/cmd/godoc@latest && \
#     go install -v github.com/go-delve/delve/cmd/dlv@latest && \
#     go install -v honnef.co/go/tools/cmd/staticcheck@latest && \
#     go install -v golang.org/x/tools/gopls@latest


# Install Rust and some tools
RUN RUSTUP_DIST_SERVER="https://rsproxy.cn" RUSTUP_UPDATE_ROOT="https://rsproxy.cn/rustup" && \
    CARGO_BIN=/root/.cargo/bin && PATH=$CARGO_BIN:$PATH && \
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
    cargo install cargo-binstall parallel-disk-usage bat navi

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo install starship eza conceal 

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo install zoxide fd-find macchina yazi-fm fnm

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo install tree-sitter-cli tokei

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo binstall -y kondo jaq bob-nvim

RUN CARGO_BIN=/root/.cargo/bin PATH=$CARGO_BIN:$PATH && \
    cargo binstall -y rust-script

# 使用bob-nvim安装nvim, 使用fnm安装node
RUN PATH=/root/.cargo/bin:$PATH && \
    bob install stable && \
    fnm install v22.2.0




WORKDIR /root

CMD [ "/usr/bin/zsh" ]
