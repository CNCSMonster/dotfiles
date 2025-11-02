FROM ubuntu:24.04

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

COPY . /root/dotfiles
WORKDIR /root/dotfiles

# 使用仓库脚本一键安装所有依赖、语言环境与工具
RUN ./install_apps.sh

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
