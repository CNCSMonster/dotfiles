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
#   --build-arg BASE_IMAGE=docker.m.daocloud.io/library/ubuntu:26.04
ARG BASE_IMAGE=ubuntu:26.04
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

# Rust 镜像源由 setup.sh 内 do_deploy (xd deploy) 统一软链接 ~/.cargo/config.toml，此处不预 COPY 避免路径冲突

# 安装基础引导工具与 ca-certificates：
# - 国内 (USE_CHINA_MIRROR=1): 先用 HTTP 清华源安装，再切回 HTTPS
#   （codename 从 /etc/os-release 动态获取，兼容 ubuntu:24.04/26.04 等不同基镜像）
# - 海外 (USE_CHINA_MIRROR=0): 保留基镜像自带官方源，仅安装系统已带的 ca-certificates
# 仅安装 setup.sh 引导所需的最小工具链 (git, curl, wget, python3, ca-certificates)；
# 完整的 build-essential, clang, cmake 等由 setup.sh Layer 0 (system-packages 模块) 统一安装，
# 并在同层立即清理 apt 索引与缓存，避免中间层膨胀冻结。
RUN . /etc/os-release && \
    if [ "${USE_CHINA_MIRROR}" = "1" ]; then \
      rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null; true; \
      echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ ${VERSION_CODENAME} main restricted universe multiverse" > /etc/apt/sources.list && \
      echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ ${VERSION_CODENAME}-updates main restricted universe multiverse" >> /etc/apt/sources.list && \
      echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ ${VERSION_CODENAME}-security main restricted universe multiverse" >> /etc/apt/sources.list; \
    fi && \
    for i in 1 2 3 4 5; do \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates git curl wget python3 && break; \
      [ "$i" -eq 5 ] && exit 1; echo "apt 失败，15s 后重试 $i/5"; sleep 15; \
    done && \
    if [ "${USE_CHINA_MIRROR}" = "1" ]; then \
      sed -i 's|http://mirrors.tuna.tsinghua.edu.cn|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

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
# TOOL_INSTALLER_STRICT=1 时，allow_fail 工具失败不再静默吞掉：
# 安装跑完后以完整失败清单汇总并非零退出（终止构建）。
# 禁用方式：./scripts/docker-build-test.sh --no-strict
#   或：docker buildx build --build-arg TOOL_INSTALLER_STRICT=0 ...
# -----------------------------------------------------------------------------
ARG TOOL_INSTALLER_STRICT=1
ENV TOOL_INSTALLER_STRICT=${TOOL_INSTALLER_STRICT}

#   或: docker buildx build --secret id=github_token,env=GITHUB_TOKEN ...
# 不传则匿名访问，下载失败的 crate 会 fallback 到源码编译。
# -----------------------------------------------------------------------------

# 执行一键配置脚本
# 此步骤会安装所有依赖、语言环境与工具
# cargo 编译受 CARGO_BUILD_JOBS 限制，避免内存耗尽
# CI=true: 供 tool-installer / setup.sh 内部识别 CI 环境
# --mount=secret: token 仅在本层可见，不会写入镜像层
RUN --mount=type=secret,id=github_token,required=false \
    export CI=true && \
    if [ -f /run/secrets/github_token ]; then \
      export GITHUB_TOKEN=$(cat /run/secrets/github_token); \
    fi && \
    chmod +x ./setup.sh && ./setup.sh && \
    # ── 生产镜像体积深度优化与构建残留清理 ── \
    # 1. 清理 Go 编译缓存与模块缓存 (gopls 构建遗留，省 ~540MB) \
    rm -rf /root/.cache/go-build /root/go/pkg/mod /root/go/pkg/sumdb && \
    # 2. 清理 Cargo 编译缓存与注册表索引 (省 ~40MB) \
    rm -rf /root/.cargo/registry /root/.cargo/.package-cache /root/.cargo/target && \
    # 3. 移除 LLVM 静态归档库（只保留 clang/clang++ 运行时所需的 .so 动态库，省 ~550MB） \
    rm -f /usr/lib/llvm-*/lib/*.a && \
    # 4. 移除 Node.js / 全局 npm 包的 SourceMap 调试文件 (省 ~120MB) \
    find /root/.local -name "*.map" -delete 2>/dev/null || true && \
    # 5. 清理 Python 字节码缓存 (省 ~25MB) \
    find /root /usr -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /root /usr -name "*.pyc" -delete 2>/dev/null || true && \
    # 6. 二进制符号剥离 (省 ~120MB，注意必须排除 .NET 单文件打包的 marksman 避免 bundle 损坏) \
    find /root/.cargo/bin /root/.local/bin /root/.rustup/toolchains/*/bin -type f ! -name "marksman" -exec strip --strip-unneeded {} + 2>/dev/null || true && \
    # 7. 清理 Rust 文档与 crate 临时安装包 \
    rm -rf /root/.rustup/toolchains/*/share/doc /root/.rustup/toolchains/*/share/man && \
    find /root/.cargo/bin -name '*.crate' -delete 2>/dev/null || true && \
    # 8. 清理系统文档、man 手册与各包管理器缓存 \
    rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
      /root/.local/share/mise/downloads/* /root/.cache/mise/* \
      /root/.cache/pip /root/.cache/uv /root/.npm/_logs /root/.npm/_cacache \
      /var/cache/apt/archives/* /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    apt-get clean

WORKDIR /root

CMD [ "/usr/bin/zsh" ]
