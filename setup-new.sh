#!/usr/bin/env bash
# 三层架构安装脚本（tool-installer 迁移版）
# Layer 0: Bootstrap (bash) — 系统包 + gh 登录 + tool-installer
# Layer 1: 工具安装 (tool-installer) — 声明式 TOML
# Layer 2: 后置脚本 (bash) — 依赖 Layer 1 的工具
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PATH="$HOME/.local/bin:$PATH"

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
    bash "${SCRIPT_DIR}/scripts/layer0-bootstrap.sh"
}

do_deploy() {
    echo "=========================================="
    echo "部署配置文件（xdotter deploy）..."
    echo "=========================================="
    if command -v xd &>/dev/null; then
        cd "${SCRIPT_DIR}" && xd deploy --force
    else
        echo "⚠️  xdotter 未安装，跳过配置部署"
        echo "   运行 --bootstrap 或 --install 后重试"
    fi
}

do_install() {
    echo "=========================================="
    echo "Layer 1: 安装开发工具..."
    echo "=========================================="
    if ! command -v tool-installer &>/dev/null; then
        echo "❌ tool-installer 未安装，请先运行 --bootstrap"
        exit 1
    fi
    tool-installer install dev
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
