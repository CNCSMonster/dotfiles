FROM ubuntu:20.04

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

WORKDIR /root/dotfiles
COPY . /root/dotfiles

# 使用仓库脚本一键安装所有依赖、语言环境与工具
RUN chmod +x ./install_apps.sh && ./install_apps.sh

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
