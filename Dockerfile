FROM ubuntu:24.04


ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

COPY ./tsinghua.list /etc/apt/sources.d/tsinghua.list

# 下载基础工具
RUN apt update && \
    apt install -y wget git curl

COPY . /root/dotfiles
WORKDIR /root/dotfiles


# 使用仓库脚本一键安装所有依赖、语言环境与工具
RUN chmod +x ./install_apps.sh && ./install_apps.sh

# # 清理apt缓存
# RUN apt clean

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
