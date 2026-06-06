#!/usr/bin/env bash
# Layer 2: 后置脚本 — 依赖 Layer 1 安装的工具
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 2a: Helix runtime（需要先安装 helix）──
install_helix_runtime() {
    echo "=========================================="
    echo "Layer 2: 安装 Helix runtime..."
    echo "=========================================="

    if ! command -v hx &>/dev/null; then
        echo "⚠️  helix 未安装，跳过 runtime 安装"
        return 0
    fi

    local hx_version
    hx_version=$(hx --version | head -1 | awk '{print $2}')
    local hx_config_dir="${HOME}/.config/helix"
    local hx_runtime_dir="${hx_config_dir}/runtime"

    mkdir -p "${hx_runtime_dir}"

    # 下载 themes 和 queries
    local repo_url="https://github.com/helix-editor/helix"
    local tmp_dir
    tmp_dir=$(mktemp -d)

    echo "下载 Helix runtime (themes/queries/tutor)..."
    if command -v gh &>/dev/null; then
        gh api "repos/helix-editor/helix/tarball/${hx_version}" \
            --jq '.tarball_url' 2>/dev/null | \
            xargs curl -fsSL | tar xz -C "${tmp_dir}" --strip-components=1 2>/dev/null || \
            curl -fsSL "${repo_url}/archive/refs/tags/${hx_version}.tar.gz" | \
            tar xz -C "${tmp_dir}" --strip-components=1
    else
        curl -fsSL "${repo_url}/archive/refs/tags/${hx_version}.tar.gz" | \
            tar xz -C "${tmp_dir}" --strip-components=1
    fi

    # 复制 runtime 文件
    cp -r "${tmp_dir}/runtime/themes" "${hx_runtime_dir}/" 2>/dev/null || true
    cp -r "${tmp_dir}/runtime/queries" "${hx_runtime_dir}/" 2>/dev/null || true
    cp -r "${tmp_dir}/runtime/tutor" "${hx_runtime_dir}/" 2>/dev/null || true
    rm -rf "${tmp_dir}"

    echo "✅ Helix runtime 安装完成"
}

# ── 2b: Yazi 插件 ──
install_yazi_plugins() {
    echo "=========================================="
    echo "Layer 2: 安装 Yazi 插件..."
    echo "=========================================="

    if ! command -v ya &>/dev/null; then
        echo "⚠️  yazi 未安装，跳过插件安装"
        return 0
    fi

    # 保留现有插件安装逻辑
    if [ -f "${PROJECT_DIR}/shells/common/install-functions.sh" ]; then
        source "${PROJECT_DIR}/shells/common/install-functions.sh"
        install-yazi-plugins
    else
        echo "⚠️  install-functions.sh 不存在，跳过"
    fi
}

# ── 2c: LLVM / clangd ──
install_llvm() {
    echo "=========================================="
    echo "Layer 2: 安装 LLVM / clangd..."
    echo "=========================================="

    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "macOS: 跳过 llvmup（LLVM 由 Homebrew 提供）"
        return 0
    fi

    local llvmup="${SCRIPT_DIR}/llvmup"
    if [ ! -f "$llvmup" ]; then
        echo "⚠️  llvmup 脚本不存在，跳过 LLVM 安装"
        return 0
    fi

    chmod +x "$llvmup"
    "$llvmup" default 22
    echo "✅ LLVM 22 / clangd 安装完成"
}

# ── 2d: 字体缓存刷新 ──
refresh_fonts() {
    echo "=========================================="
    echo "Layer 2: 刷新字体缓存..."
    echo "=========================================="

    if command -v fc-cache &>/dev/null; then
        fc-cache -f
        echo "✅ 字体缓存已刷新"
    else
        echo "⚠️  fc-cache 不存在，跳过"
    fi
}

# ── 入口 ──
main() {
    install_helix_runtime
    install_yazi_plugins
    install_llvm
    refresh_fonts
    echo ""
    echo "✅ Layer 2 (后置脚本) 完成"
}

main "$@"
