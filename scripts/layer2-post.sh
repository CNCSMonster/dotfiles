#!/usr/bin/env bash
# Layer 2: 后置脚本 — 依赖 Layer 1 安装的工具
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# GitHub mirrors (same as install-functions.sh)
GITHUB_MIRRORS="${GITHUB_MIRRORS:-https://ghfast.top https://mirror.ghproxy.com}"

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
    local download_ok=false

    # Try gh API tarball first
    local tarball_url=""
    if command -v gh &>/dev/null; then
        tarball_url=$(gh api "repos/helix-editor/helix/tarball/${hx_version}" \
            --jq '.tarball_url' 2>/dev/null) || true
    fi

    if [[ -n "${tarball_url}" ]]; then
        if curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --max-time 300 \
            "${tarball_url}" | tar xz -C "${tmp_dir}" --strip-components=1 2>/dev/null; then
            download_ok=true
        fi
    fi

    # Fallback: try GitHub mirror then direct
    if [ "${download_ok}" = false ]; then
        local direct_url="${repo_url}/archive/refs/tags/${hx_version}.tar.gz"
        for mirror in $GITHUB_MIRRORS; do
            if curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --max-time 300 \
                "${mirror}/${direct_url}" | tar xz -C "${tmp_dir}" --strip-components=1 2>/dev/null; then
                download_ok=true
                break
            fi
        done
    fi

    if [ "${download_ok}" = false ]; then
        curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --max-time 300 \
            "${repo_url}/archive/refs/tags/${hx_version}.tar.gz" | \
            tar xz -C "${tmp_dir}" --strip-components=1 2>/dev/null || true
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

    # 安装 yazi 插件（带 GitHub 镜像 fallback）

    local attempts=0
    local max_attempts=3
    local installed=false

    while [ $attempts -lt $max_attempts ]; do
        attempts=$((attempts + 1))
        echo "安装 Yazi 插件（第 ${attempts}/${max_attempts} 次尝试）..."

        if cd "${HOME}/.config/yazi"; then
            if command -v git &>/dev/null; then
                for git_mirror in $GITHUB_MIRRORS; do
                    [ -n "$git_mirror" ] || continue
                    echo "  使用镜像: $git_mirror"
                    if GIT_CONFIG_COUNT=1 \
                       GIT_CONFIG_KEY_0="url.${git_mirror}/https://github.com/.insteadof" \
                       GIT_CONFIG_VALUE_0="https://github.com/" \
                       ya pkg install; then
                        installed=true
                        break 2
                    fi
                    echo "  ⚠️  镜像 $git_mirror 失败，尝试下一个..."
                done
            else
                if ya pkg install; then
                    installed=true
                    break
                fi
            fi
        fi

        if [ "$installed" != true ]; then
            echo "⚠️  Yazi 插件安装失败，等待后重试..."
            sleep $((attempts * 5))
        fi
    done

    if [ "$installed" = true ]; then
        echo "✅ Yazi 插件安装成功"
    else
        echo "⚠️  Yazi 插件安装失败（已重试 ${max_attempts} 次），跳过"
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

    # Wait for dpkg lock (unattended-upgrade may be running)
    echo "等待 dpkg 锁释放..."
    local max_wait=300
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
        if [ $waited -ge $max_wait ]; then
            echo "⚠️  dpkg 锁等待超时（${max_wait}s），跳过 LLVM 安装"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done

    chmod +x "$llvmup"
    if "$llvmup" default 22; then
        echo "✅ LLVM 22 / clangd 安装完成"
    else
        echo "⚠️  LLVM 22 安装失败，跳过"
        return 0
    fi
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
