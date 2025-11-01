FROM ubuntu:24.04

SHELL ["/bin/bash", "-c"]

RUN mkdir -p /etc/apt/sources.list.d
COPY ./tsinghua.list /etc/apt/sources.list.d/tsinghua.list

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

COPY . /root/dotfiles
WORKDIR /root/dotfiles

# 安装xdotter, 然后部署dotfiles

# 案后安装其他工具链

# 使用仓库脚本一键安装所有依赖、语言环境与工具
RUN chmod +x ./install_apps.sh && ./install_apps.sh

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
