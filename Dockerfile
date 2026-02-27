# =============================================================================
# Dotfiles 测试镜像
# =============================================================================
# 用于验证 dotfiles 一键配置脚本在干净环境中的执行效果
#
# ## 构建资源限制说明
#
# 由于 BuildKit docker-container driver 的限制：
# - --driver-opt 只限制 BuildKit daemon，不限制构建容器
# - 构建容器可使用宿主机全部资源
# - 容器内 /proc/meminfo 显示宿主机内存
#
# 因此需要通过 CARGO_BUILD_JOBS 限制 cargo 编译并行度。
# 该值由 docker-build-test.sh 根据宿主机可用资源动态计算。
#
# 每个 rustc 进程约需 1-1.5GB 内存，过度并行会导致 OOM。
# =============================================================================

# 使用中国镜像站作为默认基础镜像来源，降低拉取超时概率
# 如需切回官方源，可在构建时传入：
#   --build-arg BASE_IMAGE=ubuntu:24.04
ARG BASE_IMAGE=docker.m.daocloud.io/library/ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

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

# 先用默认源安装 ca-certificates，再全量切国内源（否则 https 镜像站校验证书会失败）
# 外层重试：单次 apt 失败（如网络抖动）时自动重试
RUN for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates && break; \
      [ "$i" -eq 5 ] && exit 1; echo "apt 失败，15s 后重试 $i/5"; sleep 15; \
    done
COPY ./tsinghua.list /etc/apt/sources.list
RUN rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null; true

# 安装基础工具（此后 apt 均走清华源，同样带重试）
RUN for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends wget git curl && break; \
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
#   或: docker buildx build --secret id=github_token,env=GITHUB_TOKEN ...
# 不传则匿名访问，下载失败的 crate 会 fallback 到源码编译。
# -----------------------------------------------------------------------------

# 执行一键配置脚本
# 此步骤会安装所有依赖、语言环境与工具
# cargo 编译受 CARGO_BUILD_JOBS 限制，避免内存耗尽
# --mount=secret: token 仅在本层可见，不会写入镜像层
RUN --mount=type=secret,id=github_token,required=false \
    if [ -f /run/secrets/github_token ]; then \
      export GITHUB_TOKEN=$(cat /run/secrets/github_token); \
    fi && \
    chmod +x ./setup.sh && ./setup.sh

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
