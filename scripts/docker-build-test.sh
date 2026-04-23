#!/bin/bash
# =============================================================================
# Docker 构建脚本 - 根据系统资源动态限制构建过程
# =============================================================================
# 用法: ./scripts/docker-build-test.sh [--no-cache] [--retry <n>] [--gh-token <token>] [--file <dockerfile>] [--tag <image-tag>] [--no-china-mirror]
#
# ## BuildKit 资源限制架构说明
#
# Docker BuildKit 采用分层架构，不同层的资源限制机制不同：
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  第 1 层: BuildKit Daemon 容器                                          │
# │  ------------------------------------------------------------------    │
# │  限制方式: --driver-opt memory=Xg --driver-opt cpu-quota=Y             │
# │  作用对象: BuildKit daemon 进程本身                                     │
# │  职责: 解析 Dockerfile、调度构建步骤、管理缓存                           │
# │  限制生效: ✅ 已限制（本脚本动态计算）                                   │
# │                                                                         │
# │  注意: --driver-opt 只限制 daemon 容器，不限制构建容器！                 │
# └─────────────────────────────────────────────────────────────────────────┘
#                                    │
#                                    │ 创建临时容器执行 RUN 命令
#                                    ▼
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  第 2 层: 临时构建容器                                                  │
# │  ------------------------------------------------------------------    │
# │  限制方式: BuildKit docker-container driver 不支持直接限制！            │
# │  作用对象: 执行 RUN 命令的容器                                          │
# │  职责: 执行 apt install、cargo binstall 等命令                          │
# │  限制生效: ❌ 无限制（可使用宿主机全部资源）                             │
# │                                                                         │
# │  风险: 容器内进程看到的 /proc/meminfo 是宿主机内存，不是容器限制        │
# └─────────────────────────────────────────────────────────────────────────┘
#                                    │
#                                    │ cargo/rustc 编译时
#                                    ▼
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  第 3 层: cargo/rustc 编译进程                                          │
# │  ------------------------------------------------------------------    │
# │  限制方式: CARGO_BUILD_JOBS 环境变量                                    │
# │  作用对象: cargo 启动的并行 rustc 编译进程数                            │
# │  职责: Rust 源码编译                                                    │
# │  限制生效: ✅ 已限制（通过 Dockerfile ARG 传入）                        │
# │                                                                         │
# │  ⚠️ 关键：这是唯一有效的内存控制手段！                                  │
# │     每个 rustc 进程约需 1-1.5GB 内存，需根据可用内存计算并行度          │
# └─────────────────────────────────────────────────────────────────────────┘
#
# ## 本脚本的资源限制策略
#
# 1. BuildKit Daemon 限制: 可用内存的 60%，最少 4GB（仅限制调度进程）
# 2. Docker 层数并行度: CPU 核心数的 50%，用于限制同时构建的 Dockerfile 层
# 3. cargo 编译并行度: 根据可用内存精确计算，预留 2GB 系统开销（**关键）
#
# 选项:
#   --no-cache           不使用缓存构建
#   --retry <n>          构建失败时自动重试最多 n 次（默认: 1，即不重试）
#   --gh-token <token>   GitHub Token，加速 cargo-binstall（也可设 GITHUB_TOKEN 环境变量）
#   --file <dockerfile>  指定 Dockerfile 路径（默认: Dockerfile）
#   --tag <image-tag>    指定镜像标签（默认: dotfiles:test）
#   --no-china-mirror    使用官方源（海外 CI 模式，默认使用中国镜像源）
# =============================================================================

set -eo pipefail

cd "$(dirname "$0")/.."

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 Docker 是否可用
if ! command -v docker &> /dev/null; then
    log_error "Docker 未安装或不在 PATH 中"
    exit 1
fi

# ===== 获取系统资源 =====
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
AVAIL_MEM_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
AVAIL_MEM_GB=$((AVAIL_MEM_KB / 1024 / 1024))
TOTAL_CPU=$(nproc)

# 检查磁盘空间
DISK_AVAIL=$(df -BG . | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$DISK_AVAIL" -lt 10 ]; then
    log_warn "磁盘可用空间不足 10GB (当前: ${DISK_AVAIL}GB)，构建可能失败"
fi

log_info "=== 系统资源检测 ==="
log_info "总内存: ${TOTAL_MEM_GB}GB, 可用: ${AVAIL_MEM_GB}GB"
log_info "CPU 核心: ${TOTAL_CPU}"
log_info "磁盘可用: ${DISK_AVAIL}GB"

# =============================================================================
# 第 1 层: BuildKit Daemon 资源限制
# =============================================================================
# --driver-opt 限制的是 BuildKit daemon 容器，负责调度构建任务
# 注意: 这不会传递给执行 RUN 命令的临时构建容器！

# 内存限制: 可用内存的 60%，最少 4GB，最多不超过总内存的 70%
MEM_LIMIT=$((AVAIL_MEM_GB * 60 / 100))
[ $MEM_LIMIT -lt 4 ] && MEM_LIMIT=4
MAX_MEM=$((TOTAL_MEM_GB * 70 / 100))
[ $MEM_LIMIT -gt $MAX_MEM ] && MEM_LIMIT=$MAX_MEM

# 交换空间限制: 内存限制 + 额外 2GB
MEM_SWAP=$((MEM_LIMIT + 2))

# CPU 限制: 总核心数的 75%
CPU_CORES=$((TOTAL_CPU * 75 / 100))
[ $CPU_CORES -lt 2 ] && CPU_CORES=2
CPU_QUOTA=$((CPU_CORES * 100000))

# Docker 层数并行度: 限制同时构建的 Dockerfile 层数
# 这是 BuildKit worker 的配置，与 cargo 编译并行度无关
MAX_PARALLELISM=$((TOTAL_CPU / 2))
[ $MAX_PARALLELISM -lt 2 ] && MAX_PARALLELISM=2
[ $MAX_PARALLELISM -gt 8 ] && MAX_PARALLELISM=8

# =============================================================================
# 第 3 层: cargo/rustc 编译并行度计算
# =============================================================================
# 关键背景:
# - 构建容器不受 --driver-opt 限制，可使用宿主机全部资源
# - 容器内 /proc/meminfo 显示的是宿主机内存，不是容器限制
# - cargo 默认启动 nproc 个并行 rustc 进程，每个约需 1-1.5GB 内存
#
# 计算策略:
# - 预留 2GB 给系统和其他进程（apt、下载、解压等）
# - 每个 rustc 进程按 1.5GB 计算（取上限确保安全）
# - 公式: BUILD_JOBS = floor((可用内存 - 2GB) / 1.5GB)
# - 同时不超过 CPU 核心数的 50%，避免 CPU 争抢

# 预留给系统的内存（GB）
RESERVED_MEM=2

# 每个 rustc 进程需要的内存（GB）
MEM_PER_RUSTC=15  # 1.5GB * 10 用于整数计算

# 计算可用内存（GB），预留系统开销
USABLE_MEM=$((AVAIL_MEM_GB - RESERVED_MEM))
[ $USABLE_MEM -lt 1 ] && USABLE_MEM=1

# 计算编译并行度: (可用内存 * 10) / 15，向下取整
BUILD_JOBS=$((USABLE_MEM * 10 / MEM_PER_RUSTC))
[ $BUILD_JOBS -lt 1 ] && BUILD_JOBS=1

# 不超过 CPU 核心数的 50%（CPU 也需要给其他进程预留）
MAX_BUILD_JOBS=$((TOTAL_CPU / 2))
[ $MAX_BUILD_JOBS -lt 1 ] && MAX_BUILD_JOBS=1
[ $BUILD_JOBS -gt $MAX_BUILD_JOBS ] && BUILD_JOBS=$MAX_BUILD_JOBS

# 最大 8 个并行（超过后收益递减）
[ $BUILD_JOBS -gt 8 ] && BUILD_JOBS=8

# 预估内存占用
ESTIMATED_MEM=$((BUILD_JOBS * 15 / 10))  # GB

log_info ""
log_info "=== 资源限制分层配置 ==="
log_info ""
log_info "【第 1 层】BuildKit Daemon (--driver-opt):"
log_info "  内存限制: ${MEM_LIMIT}GB (可用的 60%)"
log_info "  交换空间: ${MEM_SWAP}GB"
log_info "  CPU 限制: ${CPU_CORES} 核"
log_info "  层数并行: ${MAX_PARALLELISM} (同时构建的 Dockerfile 层)"
log_info ""
log_info "【第 2 层】临时构建容器:"
log_info "  资源限制: 无 (BuildKit docker-container driver 不支持)"
log_info "  风险提示: 容器可使用宿主机全部资源"
log_info ""
log_info "【第 3 层】cargo/rustc 编译 (CARGO_BUILD_JOBS):"
log_info "  编译并行度: ${BUILD_JOBS}"
log_info "  预留内存: ${RESERVED_MEM}GB (系统开销)"
log_info "  预估占用: ${ESTIMATED_MEM}GB (${BUILD_JOBS} × 1.5GB/rustc)"
log_info ""
log_info "【镜像源】APT 配置:"
log_info "  中国镜像: $([ "$USE_CHINA_MIRROR" = "1" ] && echo "启用 (清华源)" || echo "禁用 (官方源)")"
log_info ""

# 安全检查
if [ $AVAIL_MEM_GB -lt 4 ]; then
    log_error "可用内存不足 4GB，无法安全构建"
    log_error "当前可用: ${AVAIL_MEM_GB}GB"
    log_error "建议: 关闭其他程序释放内存后重试"
    exit 1
fi

if [ $AVAIL_MEM_GB -lt 6 ]; then
    log_warn "可用内存较低 (低于 6GB)，构建可能较慢"
    log_warn "建议: 关闭其他程序释放内存以加速构建"
fi

# 解析参数
NO_CACHE_ARGS=()
RETRY_BUILD=1
DOCKERFILE_PATH="Dockerfile"
IMAGE_TAG="dotfiles:test"
GH_TOKEN=""
# CI 默认启用严格模式，任何 Rust 工具安装失败都会终止构建
CARGO_INSTALL_STRICT="${CARGO_INSTALL_STRICT:-1}"
# 默认使用中国镜像源（国内构建），--no-china-mirror 切换为官方源
USE_CHINA_MIRROR=1

# 本地缓存目录（与 builder 解耦，支持不同 builder 复用）
CACHE_DIR=".buildx-cache"
CACHE_DIR_NEW=".buildx-cache-new"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-cache)
            NO_CACHE_ARGS=(--no-cache)
            log_info "使用 --no-cache 模式"
            shift
            ;;
        --retry)
            if [[ -z "${2:-}" || ! "$2" =~ ^[0-9]+$ ]] || [[ "$2" -lt 1 ]]; then
                log_error "--retry 需要正整数 (至少 1)"
                exit 1
            fi
            RETRY_BUILD="$2"
            log_info "构建失败时最多重试: ${RETRY_BUILD} 次"
            shift 2
            ;;
        --file)
            if [[ -z "${2:-}" ]]; then
                log_error "--file 需要一个参数"
                exit 1
            fi
            DOCKERFILE_PATH="$2"
            shift 2
            ;;
        --tag)
            if [[ -z "${2:-}" ]]; then
                log_error "--tag 需要一个参数"
                exit 1
            fi
            IMAGE_TAG="$2"
            shift 2
            ;;
        --gh-token)
            if [[ -z "${2:-}" ]]; then
                log_error "--gh-token 需要一个参数"
                exit 1
            fi
            GH_TOKEN="$2"
            log_info "已设置 GitHub Token（加速 cargo-binstall 下载）"
            shift 2
            ;;
        --no-china-mirror)
            USE_CHINA_MIRROR=0
            log_info "使用官方源（海外 CI 模式）"
            shift
            ;;
        *)
            log_error "未知参数: $1"
                log_info "用法: ./scripts/docker-build-test.sh [--no-cache] [--retry <n>] [--gh-token <token>] [--file <dockerfile>] [--tag <image-tag>] [--no-china-mirror]"
            exit 1
            ;;
    esac
done

# ===== 检查 buildx 是否可用 =====
if ! docker buildx version &> /dev/null; then
    log_error "docker buildx 未安装，请升级 Docker"
    log_info "Docker 版本要求: >= 19.03 (BuildKit 支持)"
    exit 1
fi

# ===== 创建 BuildKit 配置文件 =====
# 配置 BuildKit worker 的层数并行度
BUILDKIT_CONFIG=$(cat <<EOF
debug = false

[worker.oci]
  max-parallelism = ${MAX_PARALLELISM}
  gc = true
  gckeepstorage = 10000

[worker.containerd]
  max-parallelism = ${MAX_PARALLELISM}
  gc = true
EOF
)

# 说明：
# - builder 级参数（memory/cpu/max-parallelism）与机器可用资源相关
# - 为了保持“动态适配”，builder 名称带上资源配置指纹
# - 为了避免切换 builder 丢缓存，缓存使用本地目录（CACHE_DIR），不依赖 builder 内部状态
BUILDER_PROFILE="${MEM_LIMIT}g-${MEM_SWAP}g-${CPU_QUOTA}-${MAX_PARALLELISM}"
BUILDER_NAME="dotfiles-builder-${BUILDER_PROFILE}"

TMP_CONFIG="/tmp/buildkitd-${BUILDER_NAME}.toml"
echo "$BUILDKIT_CONFIG" > "$TMP_CONFIG"

log_info "=== 准备 BuildKit Builder ==="
log_info "目标 builder: $BUILDER_NAME"
log_info "BuildKit Daemon 资源限制: memory=${MEM_LIMIT}g, cpu-quota=${CPU_QUOTA}"

# 若该资源配置对应的 builder 已存在则复用；不存在则新建
if docker buildx inspect "$BUILDER_NAME" &> /dev/null; then
    log_info "复用已有 builder: $BUILDER_NAME"
    docker buildx inspect --bootstrap "$BUILDER_NAME" > /dev/null
else
    log_info "创建新 builder: $BUILDER_NAME"
    docker buildx create \
        --name "$BUILDER_NAME" \
        --driver docker-container \
        --driver-opt memory=${MEM_LIMIT}g \
        --driver-opt memory-swap=${MEM_SWAP}g \
        --driver-opt cpu-quota=$CPU_QUOTA \
        --buildkitd-config "$TMP_CONFIG" \
        --bootstrap > /dev/null
fi

log_info "Builder 就绪"

# ===== 开始构建 =====
START_TIME=$(date +%s)
log_info ""
log_info "=== 开始构建 ==="
log_info "开始时间: $(date)"
log_info "cargo 编译并行度: ${BUILD_JOBS} (CARGO_BUILD_JOBS)"
log_info "Dockerfile: ${DOCKERFILE_PATH}"
log_info "镜像标签: ${IMAGE_TAG}"

# 使用 buildx 构建（支持 --retry 应对网络等偶发失败）
# --build-arg BUILD_JOBS 传递给 Dockerfile，用于设置 CARGO_BUILD_JOBS
# --cache-from/--cache-to 使用本地目录缓存，支持不同 builder 复用层缓存
mkdir -p "$CACHE_DIR"
CACHE_FROM_ARGS=(--cache-from "type=local,src=${CACHE_DIR}")
CACHE_TO_ARGS=(--cache-to "type=local,dest=${CACHE_DIR_NEW},mode=max")

# 自动检测 GitHub Token：命令行参数 > 环境变量 > gh CLI
if [ -z "$GH_TOKEN" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
    GH_TOKEN="$GITHUB_TOKEN"
    log_info "从环境变量 GITHUB_TOKEN 获取 token"
elif [ -z "$GH_TOKEN" ] && command -v gh &>/dev/null; then
    GH_TOKEN=$(gh auth token 2>/dev/null || true)
    [ -n "$GH_TOKEN" ] && log_info "从 gh CLI 获取 token"
fi

SECRET_ARGS=()
if [ -n "$GH_TOKEN" ]; then
    export __DOCKER_GH_TOKEN="$GH_TOKEN"
    SECRET_ARGS=(--secret id=github_token,env=__DOCKER_GH_TOKEN)
    log_info "GitHub Token 已配置，cargo-binstall 将使用认证访问（5000 次/小时）"
else
    log_warn "未配置 GitHub Token，cargo-binstall 使用匿名访问（60 次/小时），可能触发 rate limit"
    log_warn "提示: --gh-token <token> 或设置 GITHUB_TOKEN 环境变量"
fi

BUILD_EXIT_CODE=1
for BUILD_ATTEMPT in $(seq 1 "$RETRY_BUILD"); do
    rm -rf "$CACHE_DIR_NEW"
    [ "$RETRY_BUILD" -gt 1 ] && log_info "构建尝试 $BUILD_ATTEMPT/$RETRY_BUILD"
    docker buildx build \
        --builder "$BUILDER_NAME" \
        --progress=plain \
        --tag "${IMAGE_TAG}" \
        --file "${DOCKERFILE_PATH}" \
        --build-arg BUILD_JOBS=${BUILD_JOBS} \
        --build-arg USE_CHINA_MIRROR=${USE_CHINA_MIRROR} \
        --load \
        "${CACHE_FROM_ARGS[@]}" \
        "${CACHE_TO_ARGS[@]}" \
        "${NO_CACHE_ARGS[@]}" \
        "${SECRET_ARGS[@]}" \
        . 2>&1 | tee build.log
    BUILD_EXIT_CODE=${PIPESTATUS[0]}
    if [ -d "$CACHE_DIR_NEW" ]; then
        rm -rf "$CACHE_DIR"
        mv "$CACHE_DIR_NEW" "$CACHE_DIR"
    fi
    [ "$BUILD_EXIT_CODE" -eq 0 ] && break
    if grep -q "Killed" build.log 2>/dev/null; then
        log_warn "检测到进程被 Kill (可能 OOM)，不再自动重试"
        break
    fi
    if [ "$BUILD_ATTEMPT" -lt "$RETRY_BUILD" ]; then
        log_info "构建失败，15s 后重试..."
        sleep 15
    fi
done

# 记录结束时间
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

log_info "=== 构建完成 ==="
log_info "结束时间: $(date)"
log_info "耗时: ${MINUTES}分${SECONDS}秒"

if [ $BUILD_EXIT_CODE -eq 0 ]; then
    log_info "构建成功!"
    
    # 显示镜像信息
    log_info "=== 镜像信息 ==="
    docker images "${IMAGE_TAG}"
    
    log_info "=== 下一步 ==="
    log_info "运行验证脚本: docker run --rm ${IMAGE_TAG} /root/dotfiles/scripts/verify-docker-build.sh"
    log_info "交互式测试: docker run -it --rm ${IMAGE_TAG} /usr/bin/zsh"
else
    log_error "构建失败! 退出码: $BUILD_EXIT_CODE"
    log_info "检查 build.log 查看详细错误"
    
    # 检查是否是 OOM
    if grep -q "Killed" build.log; then
        log_warn "检测到进程被 Kill，可能是内存不足 (OOM)"
        log_warn "建议: 关闭其他程序释放内存后重试"
    fi
    
    exit $BUILD_EXIT_CODE
fi
