#!/usr/bin/env bash
# 三层架构安装脚本（tool-installer 迁移版）
# Layer 0: Bootstrap — 仅安装 tool-installer 二进制（vendor 目录）
# Layer 1: 声明式安装 — tool-installer install dev（系统包 / 字体 / WezTerm / 工具链）
# Layer 2: 后置脚本 — 依赖 Layer 1 工具的配置后处理
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# deploy 冲突（如目标是已存在的非空真实目录）不阻断后续 Layer，最后汇总报告
DEPLOY_CONFLICT=false

export PATH="$HOME/.local/bin:$PATH"

if [[ "$(uname -s)" != "Darwin" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    export TZ=Asia/Shanghai
fi

usage() {
    echo "用法: $0 [选项]"
    echo ""
    echo "  无参数        完整安装（bootstrap + deploy + install + post）"
    echo "  --bootstrap   仅 Layer 0：系统包 + gh 登录 + tool-installer"
    echo "  --deploy      仅配置部署（xdotter）"
    echo "  --install     仅 Layer 1：tool-installer 安装工具"
    echo "  --post        仅 Layer 2：后置脚本"
    echo "  --dry-run     显示 tool-installer 安装计划"
}

export MISE_HTTP_TIMEOUT="${MISE_HTTP_TIMEOUT:-300}"

# ── 预检：sudo 凭证 ──
# 一次性提升/探测 sudo，避免各安装脚本在非交互环境各自静默跳过 apt 步骤
preflight_sudo() {
    [[ "$(uname -s)" == "Linux" ]] || return 0
    [ "$(id -u)" -eq 0 ] && return 0
    if sudo -n true 2>/dev/null; then
        return 0
    fi
    if [ -t 0 ]; then
        echo "🔐 提前提升 sudo 权限（后续 apt 安装不再重复提示）..."
        sudo -v || echo "⚠️  sudo 失败，apt 相关包将由后续预检门禁报告"
    else
        echo "⚠️  非交互环境且无 sudo 缓存：Layer 0/2 的 apt 步骤会跳过"
        echo "   请在终端手动执行: sudo apt-get update && sudo apt-get install -y libclang-dev libicu-dev unzip"
    fi
}

# ── 预检：Layer 1 工具的运行时依赖 ──
# marksman(.NET/ICU)、tree-sitter-cli(bindgen/libclang) 等缺依赖时会编译/探测失败，
# 但往往要等整个安装序列跑到最后才暴露。此处 fail-fast 并给出精确修复命令。
preflight_runtime_deps() {
    [[ "$(uname -s)" == "Linux" ]] || return 0
    command -v dpkg &>/dev/null || return 0

    local missing=()
    local pkg
    for pkg in libclang-dev libicu-dev unzip; do
        dpkg -s "$pkg" &>/dev/null || missing+=("$pkg")
    done
    [ ${#missing[@]} -eq 0 ] && return 0

    echo "🔍 缺少 Layer 1 运行时依赖: ${missing[*]}"
    local sudo_cmd
    if [ "$(id -u)" -eq 0 ]; then
        sudo_cmd=""
    elif sudo -n true 2>/dev/null; then
        sudo_cmd="sudo"
    else
        echo "❌ 无法自动安装（需要 sudo 终端）。请执行后重跑 setup:"
        echo "   sudo apt-get update && sudo apt-get install -y ${missing[*]}"
        return 1
    fi
    $sudo_cmd apt-get update -qq || true
    if DEBIAN_FRONTEND=noninteractive $sudo_cmd apt-get install -y --no-install-recommends "${missing[@]}"; then
        echo "✅ 运行时依赖已补齐"
    else
        echo "❌ 运行时依赖安装失败: ${missing[*]}"
        return 1
    fi
}

# ── 收尾自检：仓库是否被安装器穿透 symlink 污染 ──
# CI 会在跑 setup.sh 前执行 scripts/ci-disable-mirrors.sh，故意注释掉镜像行，
# 因此 manifest.toml / cargo config 的这一类改动是预期状态而非污染，需放行；
# 其余任何改动都可能来自穿透写入，照报。
_only_mirror_preprocessing() {
    local path
    for path in $(git -C "${SCRIPT_DIR}" diff --name-only -- . 2>/dev/null); do
        case "$path" in
            manifest.toml|langs/rust/cargo/config.toml) ;;
            *) return 1 ;;
        esac
    done
    ! git -C "${SCRIPT_DIR}" diff -U0 -- manifest.toml langs/rust/cargo/config.toml 2>/dev/null \
        | grep -E '^[+-][^+-]' \
        | grep -qvE '^[+-][[:space:]]*#?(github_mirrors|replace-with = "rsproxy-sparse")'
}

check_repo_pollution() {
    git -C "${SCRIPT_DIR}" rev-parse --git-dir &>/dev/null || return 0
    local dirty
    dirty="$(git -C "${SCRIPT_DIR}" status --porcelain --untracked-files=no 2>/dev/null)"
    [ -n "$dirty" ] || return 0
    if _only_mirror_preprocessing; then
        echo "✅ 工作区改动仅为 CI 镜像预处理（ci-disable-mirrors.sh），非污染"
        return 0
    fi
    echo "⚠️  dotfiles 仓库工作区存在改动（若有安装器穿透 symlink 写源文件，会出现在此）:"
    echo "$dirty" | sed 's/^/   /'
}

# 确保 tool-installer 是最新的（vendor 中的版本）
# 适用于任何入口：全新环境、旧环境、或跳过 bootstrap 的 --install
_ensure_tool_installer() {
    # tool-installer 是 python zipapp；裸系统（Ubuntu 最小镜像/全新安装）可能没有 python3
    if ! command -v python3 &>/dev/null && command -v apt-get &>/dev/null; then
        echo "🐍 缺少 python3（tool-installer 运行所需），通过 apt 预装..."
        if [ "$(id -u)" -eq 0 ]; then
            DEBIAN_FRONTEND=noninteractive apt-get update -qq && \
                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
        elif sudo -n true 2>/dev/null; then
            DEBIAN_FRONTEND=noninteractive sudo apt-get update -qq && \
                DEBIAN_FRONTEND=noninteractive sudo apt-get install -y --no-install-recommends python3
        fi
    fi

    local artifact="${SCRIPT_DIR}/vendor/tool-installer"
    if [ ! -f "$artifact" ]; then
        echo "❌ vendor/tool-installer 不存在于 ${SCRIPT_DIR}"
        echo "   可能原因: 仓库未正确克隆或 vendor 文件被删除"
        return 1
    fi

    mkdir -p "$HOME/.local/bin" || {
        echo "❌ 无法创建 ~/.local/bin 目录"
        return 1
    }

    local target="$HOME/.local/bin/tool-installer"
    local need_update=false

    if [ ! -f "$target" ]; then
        echo "🆕 tool-installer 未安装，准备安装..."
        need_update=true
    elif [ "$artifact" -ef "$target" ]; then
        # source 和 target 是同一个 inode（hardlink），需要重建
        echo "⚠️  tool-installer 是 hardlink，需要重新创建..."
        need_update=true
    elif ! cmp -s "$artifact" "$target" 2>/dev/null; then
        echo "🔄 tool-installer 版本不匹配，准备更新..."
        need_update=true
    fi

    if [ "$need_update" = true ]; then
        # 多级 fallback 确保可靠写入：
        # 1. install -m 755（首选，处理 hardlink/symlink）
        # 2. rm + install（处理文件被占用的情况）
        # 3. cat + chmod（最后手段）
        if install -m 755 "$artifact" "$target" 2>/dev/null; then
            : # 成功
        elif rm -f "$target" 2>/dev/null && install -m 755 "$artifact" "$target" 2>/dev/null; then
            : # 成功
        elif cat "$artifact" > "$target" 2>/dev/null && chmod +x "$target"; then
            : # 成功
        else
            echo "❌ 无法更新 tool-installer（所有写入方式均失败）"
            return 1
        fi

        # 验证：确保写入后的文件与 vendor 一致
        if ! cmp -s "$artifact" "$target" 2>/dev/null; then
            echo "❌ tool-installer 写入后校验失败（文件不完整或损坏）"
            return 1
        fi

        echo "✅ tool-installer 已更新到 ${target}"
    fi

    # 验证可执行性
    if ! "$target" --help &>/dev/null; then
        echo "❌ ${target} 无法执行"
        return 1
    fi

    return 0
}

do_bootstrap() {
    # ── 0a: 安装 tool-installer ──
    echo "=========================================="
    echo "Layer 0: 安装 tool-installer..."
    echo "=========================================="

    _ensure_tool_installer || return 1
    ~/.local/bin/tool-installer --help | head -3

    # ── 0b: 安装系统基础包与构建工具链（确保后续步骤的 gpg 等依赖）──
    echo ""
    echo "安装系统基础包与构建工具链..."
    ~/.local/bin/tool-installer install system-packages || echo "⚠️  部分系统包安装失败"

    echo ""
    echo "✅ Layer 0 (Bootstrap) 完成"
    echo "   下一步: tool-installer install dev"
}

# 确保 xdotter 已安装（bootstrap 后 tool-installer 可用，用其安装 extras 组）
# 多重回退策略：tool-installer → 直接下载 → vendor
ensure_xdotter() {
    if command -v xd &>/dev/null; then
        return 0
    fi
    echo "安装 xdotter..."

    # 方案 1: tool-installer（最优，使用 GitHub API，可能被限流）
    if command -v tool-installer &>/dev/null; then
        if tool-installer install extras 2>/dev/null; then
            command -v xd &>/dev/null && return 0
        fi
        echo "⚠️  tool-installer 安装 xdotter 失败，尝试直接下载..."
    fi

    # 方案 2: 直接 curl 下载 musl 静态二进制（仅 Linux x86_64）
    if [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]]; then
        mkdir -p ~/.local/bin
        local xd_url="https://github.com/CNCSMonster/xdotter/releases/latest/download/xd-x86_64-unknown-linux-musl"
        if curl -fsSL --retry 3 --connect-timeout 15 "$xd_url" -o ~/.local/bin/xd 2>/dev/null; then
            chmod +x ~/.local/bin/xd
            echo "✅ xdotter 已通过直接下载安装"
            return 0
        fi
    fi

    # 方案 3: vendor 目录（仅 Linux x86_64）
    if [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" && -f "${SCRIPT_DIR}/vendor/xdotter" ]]; then
        install -m 755 "${SCRIPT_DIR}/vendor/xdotter" ~/.local/bin/xd
        echo "✅ xdotter 已从 vendor 目录安装"
        return 0
    fi

    # macOS 无回退，跳过 xdotter（deploy 会检查 xd 是否存在）
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "⚠️  macOS 上 xdotter 安装失败（无 vendor 兜底），将跳过 xd deploy"
        return 0
    fi

    echo "❌ 所有安装方式均失败，无法继续"
    return 1
}

do_deploy() {
    echo "=========================================="
    echo "部署配置文件（xdotter deploy）..."
    echo "=========================================="
    ensure_xdotter
    export PATH="$HOME/.local/bin:$PATH"
    if command -v xd &>/dev/null; then
        cd "${SCRIPT_DIR}"
        if xd deploy --force; then
            echo "✅ 配置部署完成"
        else
            DEPLOY_CONFLICT=true
            echo "⚠️  部分配置未部署（xdotter 出于安全不会递归删除非空真实目录）"
            echo "   其余配置已生效。请手动处理冲突目标后重跑: ./setup.sh --deploy"
        fi
    else
        echo "⚠️  xdotter 未安装，跳过配置部署（macOS 上可能需要手动安装）"
    fi
}

do_install() {
    echo "=========================================="
    echo "Layer 1: 安装开发工具..."
    echo "=========================================="
    export PATH="$HOME/.local/bin:$PATH"

    preflight_runtime_deps || exit 1

    # 加载环境变量（注入 mise shims 等 PATH，确保 npm/uv 等工具可找到）
    if [ -f "$HOME/.config/shells/common/env.sh" ]; then
        source "$HOME/.config/shells/common/env.sh"
    elif [ -f "${SCRIPT_DIR}/shells/common/env.sh" ]; then
        source "${SCRIPT_DIR}/shells/common/env.sh"
    fi

    # 确保 tool-installer 是最新的（处理旧环境或跳过 bootstrap 的情况）
    _ensure_tool_installer || exit 1

    if ! command -v tool-installer &>/dev/null; then
        echo "❌ tool-installer 未安装"
        exit 1
    fi

    # 如果 xdotter 已在 deploy 阶段部署了 ~/.cargo/config.toml，
    # 其中的 sccache wrapper / wild linker / clang linker wrapper 此时尚未安装，
    # 会阻断 cargo 编译（clang 要到 Layer 2 的 llvmup 才有；--ld-path 是 clang 专属参数，
    # gcc 驱动不认识，必须整行禁用让 rustc 用默认 cc）。
    # 临时禁用这些配置，等 sccache/wild/LLVM 安装完成后自动恢复。
    local cargo_config="$HOME/.cargo/config.toml"
    local patched=false
    local cargo_config_link_target=""
    if [ -f "$cargo_config" ] && grep -qE 'rustc-wrapper|ld-path=|^linker = "clang"' "$cargo_config" 2>/dev/null; then
        echo "🔧 临时禁用 sccache wrapper / 自定义 linker（工具尚未安装）..."
        cp "$cargo_config" "$cargo_config.bak"
        # ~/.cargo/config.toml 是 xdotter 部署的 symlink；直接写会污染 dotfiles 源文件。
        # 替换为真实文件再写入，安装结束后恢复 symlink。
        if [ -L "$cargo_config" ]; then
            cargo_config_link_target="$(readlink -f "$cargo_config")"
            rm "$cargo_config"
        fi
        sed -e 's/^rustc-wrapper = "sccache"/#rustc-wrapper = "sccache"  # temporarily disabled during install/' \
            -e 's/^linker = "clang"/#linker = "clang"  # temporarily disabled during install/' \
            -e 's/^rustflags = .*\-\-ld-path.*$/#rustflags disabled during install (clang-only --ld-path)/' \
            "$cargo_config.bak" > "$cargo_config"
        patched=true
    fi

    # tool-installer 失败、甚至 Ctrl-C 中断时，都必须恢复 symlink 与原始配置，
    # 否则 ~/.cargo/config.toml 会以"临时禁用"状态的真实文件遗留下来，与仓库脱钩。
    _install_cleanup() {
        rm -rf /tmp/cargo-install* 2>/dev/null || true
        if [ "$patched" = true ]; then
            patched=false
            if [ -n "$cargo_config_link_target" ]; then
                rm -f "$cargo_config"
                ln -s "$cargo_config_link_target" "$cargo_config"
                rm -f "$cargo_config.bak"
            elif [ -f "$cargo_config.bak" ]; then
                mv "$cargo_config.bak" "$cargo_config"
            fi
        fi
        trap - EXIT INT TERM
    }
    trap '_install_cleanup' EXIT
    trap '_install_cleanup; exit 130' INT
    trap '_install_cleanup; exit 143' TERM

    # set -e：安装失败时退出码自然传播，EXIT trap 负责恢复
    tool-installer install dev
    _install_cleanup
}

do_post() {
    # Layer 2 依赖 Layer 1 工具的 shim（yazi/ya、helix 等），需先注入 mise PATH
    if [ -f "$HOME/.config/shells/common/env.sh" ]; then
        source "$HOME/.config/shells/common/env.sh"
    elif [ -f "${SCRIPT_DIR}/shells/common/env.sh" ]; then
        source "${SCRIPT_DIR}/shells/common/env.sh"
    fi
    bash "${SCRIPT_DIR}/scripts/layer2-post.sh"
}

main() {
    case "${1:-}" in
        --bootstrap) do_bootstrap ;;
        --deploy)
            do_deploy
            if [ "$DEPLOY_CONFLICT" = true ]; then exit 1; fi
            ;;
        --install)
            do_install
            # 单跑 --install 同样会临时改写 ~/.cargo/config.toml（symlink），
            # 是穿透污染最可能发生的路径，因此与完整安装一样做检测。
            check_repo_pollution
            ;;
        --post)      do_post ;;
        --dry-run)
            _ensure_tool_installer || exit 1
            tool-installer install dev --dry-run
            ;;
        --help|-h) usage; exit 0 ;;
        "")
            echo "=========================================="
            echo "完整安装：三层架构"
            echo "=========================================="
            preflight_sudo
            do_bootstrap
            do_deploy
            do_install
            do_post
            check_repo_pollution
            echo ""
            if [ "$DEPLOY_CONFLICT" = true ]; then
                echo "=========================================="
                echo "⚠️  工具安装完成，但有配置因冲突未部署"
                echo "   处理冲突后请重跑: ./setup.sh --deploy"
                echo "=========================================="
                exit 1
            fi
            echo "=========================================="
            echo "✅ 全部安装完成"
            echo "=========================================="
            ;;
        *)
            echo "未知选项: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"
