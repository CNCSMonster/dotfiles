#!/usr/bin/env bash
# Layer 2: 后置脚本 — 依赖 Layer 1 安装的工具
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# GitHub 镜像列表：单一事实来源是 manifest.toml（见 scripts/github-mirror-urls.sh）
if [ -z "${GITHUB_MIRRORS+x}" ]; then
    GITHUB_MIRRORS="$("${SCRIPT_DIR}/github-mirror-urls.sh")"
fi

# ── 2a: Helix runtime（需要先安装 helix）──
# 只落 queries/themes 而缺 grammars/*.so 时，Helix 会静默退化成"所有语言零高亮"：
# helix_core::syntax 打印 `Skipping syntax config for '<lang>' because the parser's
# shared library does not exist`，而 `hx --health <lang>` 依然报 ✓（它只校验配置声明，
# 不校验 .so 是否存在）。源码归档里根本没有 grammars（需 fetch+build 才有），
# 因此这里直接取 Layer 1 同款 release 资产，整包落盘 runtime/，成败按语法库计数判定。
_manifest_get() {
    # _manifest_get <section> <key>：按字面段名取值（[helix.linux] 不会误中 [helix.linux.x86_64]）
    awk -v sec="$1" -v key="$2" '
        /^\[/ { in_sec = ($0 == "[" sec "]"); next }
        in_sec && index($0, "=") > 0 {
            eq = index($0, "=")
            k = substr($0, 1, eq - 1); gsub(/[ \t]/, "", k)
            if (k == key) {
                v = substr($0, eq + 1)
                gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/"/, "", v)
                print v; exit
            }
        }
    ' "${PROJECT_DIR}/manifest.toml"
}

_sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

install_helix_runtime() {
    echo "=========================================="
    echo "Layer 2: 安装 Helix runtime..."
    echo "=========================================="

    if ! command -v hx &>/dev/null; then
        echo "⚠️  helix 未安装，跳过 runtime 安装"
        return 0
    fi

    local os arch
    case "$(uname -s)" in
        Linux)  os="linux" ;;
        Darwin) os="macos" ;;
        *) echo "⚠️  未知系统 $(uname -s)，跳过 Helix runtime"; return 0 ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64)  arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
        *) echo "⚠️  未知架构 $(uname -m)，跳过 Helix runtime"; return 0 ;;
    esac

    local hx_version hx_config_dir hx_runtime_dir
    hx_version=$(hx --version | head -1 | awk '{print $2}')
    hx_config_dir="${HOME}/.config/helix"
    hx_runtime_dir="${hx_config_dir}/runtime"

    # 幂等：同版本且语法库已就位就不再重复下载整包
    if [ "$(cat "${hx_runtime_dir}/.runtime-version" 2>/dev/null)" = "${hx_version}" ] \
        && [ -n "$(find "${hx_runtime_dir}/grammars" -maxdepth 1 -type f 2>/dev/null | head -1)" ]; then
        echo "✅ Helix runtime 已是 ${hx_version}，跳过"
        return 0
    fi

    # 资产名与校验值以 manifest.toml 为单一事实来源（与 Layer 1 装二进制用的是同一个资产）
    if [ ! -f "${PROJECT_DIR}/manifest.toml" ]; then
        echo "❌ 未找到 manifest.toml（${PROJECT_DIR}/manifest.toml），无法解析 Helix 资产"
        return 1
    fi

    local repo tpl asset sha url
    repo="$(_manifest_get "helix.${os}" repo)"
    tpl="$(_manifest_get "helix.${os}.${arch}" asset)"
    [ -n "${tpl}" ] || tpl="$(_manifest_get "helix.${os}" asset)"
    sha="$(_manifest_get "helix.${os}.${arch}" sha256)"

    if [ -z "${repo}" ] || [ -z "${tpl}" ]; then
        echo "❌ manifest.toml 缺少 helix.${os} 的 repo/asset，无法安装 Helix runtime"
        return 1
    fi

    asset="${tpl//\{version\}/${hx_version}}"
    asset="${asset//\{arch\}/${arch}}"
    url="https://github.com/${repo}/releases/download/${hx_version}/${asset}"

    mkdir -p "${hx_runtime_dir}"
    local tmp_dir archive downloaded=false
    tmp_dir=$(mktemp -d)
    archive="${tmp_dir}/${asset}"

    echo "下载 Helix runtime 资产: ${asset}"
    # 候选顺序由 github-mirror-urls.sh 决定（镜像在前、直连最后）
    local candidate
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        echo "  ← ${candidate}"
        if ! curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --max-time 300 \
            -o "${archive}" "${candidate}"; then
            echo "  ⚠️  下载失败，尝试下一个源"
            continue
        fi
        if [ -n "${sha}" ]; then
            local actual
            actual="$(_sha256_of "${archive}")"
            if [ "${actual}" != "${sha}" ]; then
                echo "  ❌ sha256 不符（期望 ${sha:0:12}…，实际 ${actual:0:12}…），尝试下一个源"
                rm -f "${archive}"
                continue
            fi
        else
            echo "  ⚠️  manifest 未 pin 该平台 sha256，跳过校验"
        fi
        if tar xJf "${archive}" -C "${tmp_dir}"; then
            downloaded=true
            break
        fi
        echo "  ⚠️  解包失败，尝试下一个源"
    done < <(GITHUB_MIRRORS="${GITHUB_MIRRORS}" "${SCRIPT_DIR}/github-mirror-urls.sh" "${url}" 2>/dev/null || echo "${url}")

    local runtime_src=""
    if [ "${downloaded}" = true ]; then
        runtime_src="$(find "${tmp_dir}" -maxdepth 3 -type d -name runtime -print -quit 2>/dev/null)"
    fi
    if [ -z "${runtime_src}" ]; then
        rm -rf "${tmp_dir}"
        echo "❌ Helix runtime 未安装（所有下载源均失败，检查网络或镜像）"
        return 1
    fi

    # 整个 runtime/ 落盘：themes / queries / tutor / grammars 一个都不能少
    cp -R "${runtime_src}/." "${hx_runtime_dir}/"
    rm -rf "${tmp_dir}"

    # 成败只能由落盘结果判定。此前只校验 queries 目录非空，于是"queries 装上了、
    # grammars 一个都没装"被判为 ✅ —— 这正是全语言零高亮的成因。
    local so_count
    so_count=$(find "${hx_runtime_dir}/grammars" -maxdepth 1 -type f \
        \( -name '*.so' -o -name '*.dylib' \) 2>/dev/null | wc -l | tr -d ' ' || true)
    if [ -n "$(ls -A "${hx_runtime_dir}/queries" 2>/dev/null)" ] && [ "${so_count}" -gt 0 ]; then
        printf '%s\n' "${hx_version}" > "${hx_runtime_dir}/.runtime-version"
        echo "✅ Helix runtime 安装完成（${so_count} 个 tree-sitter 语法库）"
        return 0
    fi
    echo "❌ Helix runtime 不完整（grammars: ${so_count} 个语法库）——所有语言会退化成零高亮"
    echo "   修复参考: hx --grammar fetch && hx --grammar build（需要 cc 与 git）"
    return 1
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

        if (
            cd "${HOME}/.config/yazi" || exit 1
            # 顺序：先逐个镜像，再直连（直连是必经的兜底，不是 else 分支）。
            # 这里曾经把 `ya pkg install` 只写在镜像 for 循环里，于是当
            # GITHUB_MIRRORS 为空时——CI 的 ci-disable-mirrors.sh 会清空它，
            # 用户也可能没配镜像——循环体一次都不执行，等于"什么都没做就判失败"。
            if command -v git &>/dev/null; then
                for git_mirror in $GITHUB_MIRRORS; do
                    [ -n "$git_mirror" ] || continue
                    echo "  使用镜像: $git_mirror"
                    if GIT_CONFIG_COUNT=1 \
                       GIT_CONFIG_KEY_0="url.${git_mirror}/https://github.com/.insteadof" \
                       GIT_CONFIG_VALUE_0="https://github.com/" \
                       ya pkg install; then
                        exit 0
                    fi
                    echo "  ⚠️  镜像 $git_mirror 失败，尝试下一个..."
                done
            fi

            if [ -n "${GITHUB_MIRRORS// /}" ]; then
                echo "  镜像均不可用，改用直连..."
            else
                echo "  未配置镜像，直连 GitHub..."
            fi
            ya pkg install
        ); then
            installed=true
            break
        fi

        if [ "$installed" != true ]; then
            echo "⚠️  Yazi 插件安装失败，等待后重试..."
            sleep $((attempts * 5))
        fi
    done

    if [ "$installed" = true ]; then
        echo "✅ Yazi 插件安装成功"
        return 0
    fi
    echo "❌ Yazi 插件安装失败（已重试 ${max_attempts} 次）"
    return 1
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
        echo "❌ llvmup 脚本不存在（仓库缺失 ${llvmup}）"
        return 1
    fi

    local llvm_version="${LLVM_VERSION:-18}"

    # Wait for dpkg lock (unattended-upgrade may be running)
    echo "等待 dpkg 锁释放..."
    if command -v fuser &>/dev/null; then
        local max_wait=300
        local waited=0
        while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
            if [ $waited -ge $max_wait ]; then
                echo "❌ dpkg 锁等待超时（${max_wait}s），clangd 未安装"
                return 1
            fi
            sleep 5
            waited=$((waited + 5))
        done
    else
        echo "⚠️  fuser 不存在，跳过 dpkg 锁等待"
    fi

    chmod +x "$llvmup"
    if "$llvmup" default "$llvm_version"; then
        echo "✅ LLVM ${llvm_version} / clangd 安装完成"
        return 0
    fi
    echo "❌ LLVM ${llvm_version} 安装失败"
    return 1
}

# ── 2d: 字体缓存刷新 ──
refresh_fonts() {
    echo "=========================================="
    echo "Layer 2: 刷新字体缓存..."
    echo "=========================================="

    if command -v fc-cache &>/dev/null; then
        if fc-cache -f; then
            echo "✅ 字体缓存已刷新"
            return 0
        fi
        echo "❌ fc-cache 执行失败"
        return 1
    fi
    echo "⚠️  fc-cache 不存在，跳过"
    return 0
}

# ── 2e: git 全局配置优先级修复 ──
# gh 等工具会写 ~/.gitconfig；而 git 只要 ~/.gitconfig 存在就不再读
# XDG 的 ~/.config/git/config，导致 dotfiles 部署的 git 配置失效。
# 用 include.path 把 dotfiles 配置挂接进去（非破坏性，不删除用户文件）。
ensure_git_config_include() {
    echo "=========================================="
    echo "Layer 2: 检查 git 全局配置优先级..."
    echo "=========================================="

    command -v git &>/dev/null || return 0
    local git_dir="${XDG_CONFIG_HOME:-$HOME/.config}/git"
    local xdg_cfg="${git_dir}/config"
    local local_cfg="${git_dir}/config.local"

    # 确保本地私有配置文件存在（避免硬编码个人信息污染全局）
    if [ ! -f "${local_cfg}" ]; then
        local curr_name curr_email
        curr_name=$(git config --global user.name 2>/dev/null || true)
        curr_email=$(git config --global user.email 2>/dev/null || true)
        mkdir -p "${git_dir}"
        if [ -n "${curr_name}" ] && [ -n "${curr_email}" ] && [ "${curr_name}" != "cncsmonster" ]; then
            cat > "${local_cfg}" <<EOF
[user]
    name = ${curr_name}
    email = ${curr_email}
EOF
            echo "✅ 已根据系统既有 Git 身份自动生成 ${local_cfg}"
        elif [ -f "${PROJECT_DIR}/git/config.local.example" ]; then
            cp "${PROJECT_DIR}/git/config.local.example" "${local_cfg}"
            echo "⚠️  已生成 ${local_cfg}，请按需修改本地用户名与邮箱"
        fi
    fi

    [ -f "${xdg_cfg}" ] || return 0
    if [ ! -f "${HOME}/.gitconfig" ]; then
        echo "✅ 无 ~/.gitconfig，git 直接读取 XDG 配置"
        return 0
    fi

    if git config --global --get-all include.path 2>/dev/null | grep -Fxq "${xdg_cfg}"; then
        echo "✅ ~/.gitconfig 已 include dotfiles git 配置"
        return 0
    fi

    if ! git config --global include.path "${xdg_cfg}"; then
        echo "❌ 写入 ~/.gitconfig include.path 失败"
        return 1
    fi
    echo "✅ 已在 ~/.gitconfig 中添加 include.path -> ${xdg_cfg}"
    local name
    name=$(git config --global user.name 2>/dev/null) || true
    if [ -z "${name}" ]; then
        echo "⚠️  include 后仍未读到 user.name，请检查 ${xdg_cfg}"
    fi
    return 0
}

# ── 2f: 设置默认 shell 为 zsh ──
set_default_shell_zsh() {
    echo "=========================================="
    echo "Layer 2: 设置默认 shell..."
    echo "=========================================="

    # 以 PATH 为准，别硬编码：Linux 发行版间 zsh 路径不一致（/usr/bin、/usr/local/bin、nix store）
    local zsh_path
    zsh_path="$(command -v zsh 2>/dev/null || true)"
    [ -z "$zsh_path" ] && zsh_path="/bin/zsh"   # macOS 兜底：/bin/zsh 必定存在

    if [ ! -x "$zsh_path" ]; then
        echo "⚠️  zsh 未找到，跳过"
        return 0
    fi

    # 查真实登录 shell，而非 $SHELL —— 后者只是当前会话继承的环境变量，
    # 在容器/CI 里常是 /bin/bash，会误判成"还没设置"从而重复 chsh。
    local _user current=""
    _user="$(id -un 2>/dev/null || true)"
    if command -v dscl >/dev/null 2>&1; then
        current="$(dscl . -read "/Users/${_user}" UserShell 2>/dev/null | awk '{print $2}')"
    elif command -v getent >/dev/null 2>&1 && [ -n "$_user" ]; then
        current="$(getent passwd "$_user" 2>/dev/null | cut -d: -f7)"
    fi

    if [ "$current" = "$zsh_path" ]; then
        echo "✅ 默认 shell 已经是 zsh"
        return 0
    fi

    if chsh -s "$zsh_path"; then
        echo "✅ 默认 shell 已设置为 zsh（重新登录生效）"
        return 0
    fi
    # chsh 失败不影响本次安装的正确性，且必须由用户手动收尾（如系统未把 zsh 列入
    # /etc/shells），因此按契约返回 0 —— 这里打印 ⚠️ 而不是 ✅，本来就没有假成功。
    echo "⚠️  chsh 失败，可手动执行: chsh -s $zsh_path"
    return 0
}

# ── 入口 ──
# 返回码契约（本文件统一遵守）：
#   0 = 成功，或本步骤对当前环境不适用 / 需用户手动收尾（打印 ⚠️ 说明）
#   1 = 本步骤在该环境应当完成、但确实没完成（打印 ❌）
# 之所以要区分：Layer 2 的每一步都在下载或读取外部资源，历史上失败被 `|| true`
# 吞掉后仍无条件打印 ✅，导致 setup.sh 最后报"全部安装完成"而配置并未生效。
_record() {
    local label="$1"
    shift
    if "$@"; then
        return 0
    fi
    LAYER2_FAILURES+=("$label")
    return 0
}

main() {
    LAYER2_FAILURES=()

    _record "Helix runtime" install_helix_runtime
    _record "Yazi 插件" install_yazi_plugins
    _record "LLVM / clangd" install_llvm
    _record "字体缓存" refresh_fonts
    _record "git 全局配置 include" ensure_git_config_include
    _record "默认 shell (zsh)" set_default_shell_zsh

    echo ""
    if [ ${#LAYER2_FAILURES[@]} -eq 0 ]; then
        echo "✅ Layer 2 (后置脚本) 完成"
        return 0
    fi
    echo "⚠️  Layer 2 (后置脚本) 有 ${#LAYER2_FAILURES[@]} 项未完成：${LAYER2_FAILURES[*]}"
    echo "   工具安装本身未受影响，但这些配置尚未生效。"
    echo "   修复后重跑: ./setup.sh --post"
    return 1
}

main "$@"
