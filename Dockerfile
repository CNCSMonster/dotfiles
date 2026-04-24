# =============================================================================
# Dotfiles 测试镜像
# =============================================================================
# 用于验证 dotfiles 一键配置脚本在干净环境中的执行效果
#
# ## 构建资源限制说明
#
# BuildKit docker-container driver 采用分层架构，资源限制机制如下：
#
# 1. BuildKit Daemon 容器（调度层）
#    - 限制方式：--driver-opt memory=Xg --driver-opt cpu-quota=Y
#    - 限制效果：✅ 生效（限制调度进程本身）
#
# 2. 临时构建容器（执行层，执行 RUN 命令）
#    - 限制方式：BuildKit docker-container driver 不支持直接限制
#    - 限制效果：❌ 无限制（可使用宿主机全部资源）
#    - 风险：容器内 /proc/meminfo 显示的是宿主机内存
#
# 3. cargo/rustc 编译进程（应用层）
#    - 限制方式：CARGO_BUILD_JOBS 环境变量（限制并行 rustc 进程数）
#    - 限制效果：✅ 生效（**这是唯一有效的内存控制手段**）
#    - 计算：每个 rustc 进程约需 1-1.5GB，需根据可用内存计算并行度
#
# 因此，CARGO_BUILD_JOBS 是防止 OOM 的关键，由 docker-build-test.sh 动态计算。
# =============================================================================

# 使用基础镜像，默认官方源
# 国内构建可传入中国镜像站：
#   --build-arg BASE_IMAGE=docker.m.daocloud.io/library/ubuntu:24.04
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# -----------------------------------------------------------------------------
# 中国镜像源开关
# -----------------------------------------------------------------------------
# 默认启用中国镜像源（国内构建），CI 环境传 0 使用官方源
# 用法:
#   国内构建: ./scripts/docker-build-test.sh  (默认 USE_CHINA_MIRROR=1)
#   CI 构建:  docker buildx build --build-arg USE_CHINA_MIRROR=0 ...
# -----------------------------------------------------------------------------
ARG USE_CHINA_MIRROR=1

# -----------------------------------------------------------------------------
# Rust 编译并行度限制
# -----------------------------------------------------------------------------
# 由 docker-build-test.sh 根据可用内存动态计算传入：
#   公式: BUILD_JOBS = floor((可用内存 - 2GB预留) / 1.5GB)
#   限制: 不超过 CPU 核心数的 50%，最大 8
#
# 作用: cargo 读取此环境变量，限制同时启动的 rustc 编译进程数
# 默认: 2 (当未通过 --build-arg 传入时)
# -----------------------------------------------------------------------------
ARG BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${BUILD_JOBS}

# apt 网络波动：重试 5 次、单次超时 300s，减少偶发超时失败
COPY ./apt-retry.conf /etc/apt/apt.conf.d/99-retry-timeout.conf

# Rust 镜像源由 setup.sh 内 deploy_dotfiles 统一软链接 ~/.cargo/config.toml，此处不预 COPY 避免路径冲突

# 安装 ca-certificates：
# - 国内 (USE_CHINA_MIRROR=1): 先用 HTTP 清华源安装，再切回 HTTPS
# - 海外 (USE_CHINA_MIRROR=0): 直接用默认源（已有系统 CA 证书）
RUN if [ "${USE_CHINA_MIRROR}" = "1" ]; then \
      echo 'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble main restricted universe multiverse' > /etc/apt/sources.list && \
      echo 'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-updates main restricted universe multiverse' >> /etc/apt/sources.list && \
      echo 'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-security main restricted universe multiverse' >> /etc/apt/sources.list; \
    fi && \
    for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates && break; \
      [ "$i" -eq 5 ] && exit 1; echo "apt 失败，15s 后重试 $i/5"; sleep 15; \
    done && \
    if [ "${USE_CHINA_MIRROR}" = "1" ]; then \
      sed -i 's|http://mirrors.tuna.tsinghua.edu.cn|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi

# 清理默认源配置（避免冲突）
RUN rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null; true

# 安装基础工具（带重试）
# 国内: 走 HTTPS 清华源（已安装 ca-certificates）
# 海外: 走默认源
# 包含 gcc/build-essential/clang，用于编译需要 C 编译器的 Rust 工具（如 tree-sitter-cli）
RUN for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends wget git curl gcc build-essential clang && break; \
      [ "$i" -eq 5 ] && exit 1; echo "apt 失败，15s 后重试 $i/5"; sleep 15; \
    done

# 复制 dotfiles 并执行一键配置
COPY . /root/dotfiles
WORKDIR /root/dotfiles

# -----------------------------------------------------------------------------
# GitHub Token（可选，加速 cargo-binstall 下载预编译二进制）
# -----------------------------------------------------------------------------
# 匿名访问 GitHub API 限额 60 次/小时，批量安装 Rust 工具易触发 403。
# 传入 token 后限额提升至 5000 次/小时，大部分 crate 可直接下载预编译二进制。
# 用法: ./scripts/docker-build-test.sh --gh-token <token>
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# CI 严格模式（默认启用）
# -----------------------------------------------------------------------------
# CARGO_INSTALL_STRICT=1 时，任何 Rust 工具安装失败都会终止构建。
# 禁用方式：./scripts/docker-build-test.sh --no-strict
#   或：docker buildx build --build-arg CARGO_INSTALL_STRICT=0 ...
# -----------------------------------------------------------------------------
ARG CARGO_INSTALL_STRICT=1
ENV CARGO_INSTALL_STRICT=${CARGO_INSTALL_STRICT}

# -----------------------------------------------------------------------------
# xdotter 版本（固定版本，避免破坏性变更）
# -----------------------------------------------------------------------------
ARG XDOTTER_VERSION=v0.4.0
ENV XDOTTER_VERSION=${XDOTTER_VERSION}

#   或: docker buildx build --secret id=github_token,env=GITHUB_TOKEN ...
# 不传则匿名访问，下载失败的 crate 会 fallback 到源码编译。
# -----------------------------------------------------------------------------

# 执行一键配置脚本
# 此步骤会安装所有依赖、语言环境与工具
# cargo 编译受 CARGO_BUILD_JOBS 限制，避免内存耗尽
# CI=true: 触发 setup.sh 中的 rsproxy 自适应（Docker 构建在 GitHub runner 上，位于国外）
# --mount=secret: token 仅在本层可见，不会写入镜像层
RUN --mount=type=secret,id=github_token,required=false \
    export CI=true && \
    if [ -f /run/secrets/github_token ]; then \
      export GITHUB_TOKEN=$(cat /run/secrets/github_token); \
    fi && \
    chmod +x ./setup.sh && ./setup.sh

# 清理 cargo 缓存（registry、git 依赖、编译中间文件），只保留安装的二进制
RUN rm -rf ~/.cargo/registry/src ~/.cargo/registry/cache ~/.cargo/git ~/.cargo/.package-cache && \
    find ~/.cargo/bin -type f -name '*.crate' -delete 2>/dev/null || true

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
