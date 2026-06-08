#!/usr/bin/env bash
# 三层架构安装脚本（tool-installer 迁移版）
# Layer 0: Bootstrap — 仅安装 tool-installer 二进制（vendor 目录）
# Layer 1: 声明式安装 — tool-installer install dev（系统包 / 字体 / WezTerm / 工具链）
# Layer 2: 后置脚本 — 依赖 Layer 1 工具的配置后处理
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

do_bootstrap() {
    # ── 0a: 安装 tool-installer ──
    echo "=========================================="
    echo "Layer 0: 安装 tool-installer..."
    echo "=========================================="

    mkdir -p ~/.local/bin
    local artifact="${SCRIPT_DIR}/vendor/tool-installer"
    if [ -f "$artifact" ]; then
        install -m 755 "$artifact" ~/.local/bin/tool-installer
        echo "✅ tool-installer 已安装到 ~/.local/bin/tool-installer"
        ~/.local/bin/tool-installer --help | head -3
    else
        echo "❌ vendor/tool-installer 不存在，请先构建"
        return 1
    fi

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
        cd "${SCRIPT_DIR}" && xd deploy --force
        echo "✅ 配置部署完成"
    else
        echo "⚠️  xdotter 未安装，跳过配置部署（macOS 上可能需要手动安装）"
    fi
}

do_install() {
    echo "=========================================="
    echo "Layer 1: 安装开发工具..."
    echo "=========================================="
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v tool-installer &>/dev/null; then
        echo "❌ tool-installer 未安装，请先运行 --bootstrap"
        exit 1
    fi

    # 如果 xdotter 已在 deploy 阶段部署了 ~/.cargo/config.toml，
    # 其中的 sccache wrapper / wild linker 此时尚未安装，会阻断 cargo 编译。
    # 临时禁用这些配置，等 sccache/wild 安装完成后自动恢复。
    local cargo_config="$HOME/.cargo/config.toml"
    local patched=false
    if [ -f "$cargo_config" ] && grep -qE 'rustc-wrapper|ld-path=wild' "$cargo_config" 2>/dev/null; then
        echo "🔧 临时禁用 sccache wrapper / wild linker（工具尚未安装）..."
        cp "$cargo_config" "$cargo_config.bak"
        sed -e 's/^rustc-wrapper = "sccache"/#rustc-wrapper = "sccache"  # temporarily disabled during install/' \
            -e 's/--ld-path=wild/--ld-path=ld/' \
            "$cargo_config.bak" > "$cargo_config"
        patched=true
    fi

    # tool-installer 失败时也要恢复原始配置
    if $patched; then
        local rc=0
        tool-installer install dev || rc=$?
        mv "$cargo_config.bak" "$cargo_config"
        return $rc
    else
        tool-installer install dev
    fi
}

do_post() {
    bash "${SCRIPT_DIR}/scripts/layer2-post.sh"
}

main() {
    case "${1:-}" in
        --bootstrap) do_bootstrap ;;
        --deploy)    do_deploy ;;
        --install)   do_install ;;
        --post)      do_post ;;
        --dry-run)
            if ! command -v tool-installer &>/dev/null; then
                echo "❌ tool-installer 未安装，请先运行 --bootstrap"
                exit 1
            fi
            tool-installer install dev --dry-run
            ;;
        --help|-h) usage; exit 0 ;;
        "")
            echo "=========================================="
            echo "完整安装：三层架构"
            echo "=========================================="
            do_bootstrap
            do_deploy
            do_install
            do_post
            echo ""
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
