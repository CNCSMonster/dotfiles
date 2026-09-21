#!/usr/bin/env bash
# Rootless Docker：让普通用户免 sudo 用裸 docker / docker compose
#
# 用法: tool-installer install devbox-tools
#       或 bash scripts/setup-rootless-docker.sh   （普通用户运行，不要 sudo）
#
# 为什么不用「加 docker 组 / rootful」：把用户加进 docker 组 ≡ 交出宿主 root
# （docker run -v /:/host 一行即提权），且该通道绕过 sudo。rootless 靠 user
# namespace 把容器 uid 0 映射到宿主非特权 subuid 段，容器逃逸拿不到宿主 root。
#
# 本脚本【不写任何 shell 配置文件】。rootless 的 socket 由 docker context 提供：
# setuptool 会注册并激活 "rootless" context（endpoint=unix:///run/user/$UID/docker.sock），
# docker CLI 自动读取。手动 export DOCKER_HOST 既冗余、又会因优先级高于 context 而
# 屏蔽后续 context 切换，且往 ~/.bashrc / ~/.zshrc 追加会写穿符号链接污染仓库。
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "非 Linux：跳过 rootless docker（macOS 用 Docker Desktop / colima）"
    exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
    echo "❌ 请勿用 sudo 运行本脚本：rootless 守护进程必须以普通用户身份初始化" >&2
    exit 1
fi

USER_NAME="$(id -un)"
sudo_cmd="sudo"
command -v sudo &>/dev/null || sudo_cmd=""

# ── 1: 装包（仅缺依赖时） ──
install_packages() {
    if command -v dockerd-rootless-setuptool.sh >/dev/null; then
        echo "✅ rootless 依赖已具备，跳过 apt 安装"
        return 0
    fi
    command -v apt-get >/dev/null || {
        echo "❌ 未找到 dockerd-rootless-setuptool.sh，且本机不是 apt 发行版，请先自行安装 docker-ce-rootless-extras" >&2
        exit 1
    }

    . /etc/os-release
    local codename="${VERSION_CODENAME:-jammy}" arch
    case "$(uname -m)" in
        x86_64)  arch=amd64 ;;
        aarch64) arch=arm64 ;;
        *) echo "❌ 不支持的架构: $(uname -m)" >&2; exit 1 ;;
    esac
    local id="${ID:-ubuntu}"

    echo "==> [1/5] 清理冲突旧包（若存在）"
    $sudo_cmd apt-get remove -y docker docker-engine containerd runc 2>/dev/null || true

    echo "==> [2/5] 添加 Docker 官方 apt 源 ($id/$codename, $arch)"
    $sudo_cmd install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${id}/gpg" \
        | $sudo_cmd tee /etc/apt/keyrings/docker.asc >/dev/null
    $sudo_cmd chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${id} ${codename} stable" \
        | $sudo_cmd tee /etc/apt/sources.list.d/docker.list >/dev/null
    $sudo_cmd apt-get update

    echo "==> [3/5] 安装引擎 + rootless 依赖"
    # docker-ce-rootless-extras 带入 dockerd-rootless-setuptool.sh 与 slirp4netns
    # uidmap=userns 映射必需; dbus-user-session=systemd --user 会话
    # fuse-overlayfs=native overlay 不可用时的回退（WSL 内核 6.18 通常原生即可）
    $sudo_cmd apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin \
        docker-ce-rootless-extras \
        uidmap dbus-user-session slirp4netns fuse-overlayfs
}

# ── 2: 屏蔽 rootful，减少常驻攻击面，避免与 rootless 抢资源 ──
mask_rootful() {
    echo "==> [4/5] 停用并屏蔽 rootful 守护进程"
    $sudo_cmd systemctl disable --now docker docker.socket 2>/dev/null || true
    $sudo_cmd systemctl mask docker docker.socket 2>/dev/null || true
}

# ── 3: 用户级初始化 rootless ──
setup_rootless() {
    if ! systemctl --user show-environment >/dev/null 2>&1; then
        echo "❌ systemd --user 不可用：WSL2 需在 /etc/wsl.conf 写 [systemd] systemd=true 后 wsl --shutdown 重启" >&2
        exit 1
    fi

    if systemctl --user is-enabled docker >/dev/null 2>&1; then
        echo "✅ rootless docker 服务已启用，跳过 setuptool"
    else
        # --skip-iptables：宿主 iptables 在 WSL/嵌套环境下常缺内核模块，
        # rootless 走 slirp4netns 用户态网络，不依赖宿主 iptables 规则。
        dockerd-rootless-setuptool.sh install --skip-iptables
        systemctl --user enable --now docker
    fi

    # linger 决定「无登录会话时 rootless 是否常驻」，失败不致命
    $sudo_cmd loginctl enable-linger "$USER_NAME" 2>/dev/null \
        || echo "  ⚠️  enable-linger 需授权，已跳过（仅影响无会话时常驻）"
}

# ── 4: 让 docker CLI 指向 rootless（靠 context，不靠环境变量） ──
ensure_context() {
    echo "==> [5/5] 校正 docker context"
    if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
        echo "✅ docker CLI 已能连上守护进程"
        return 0
    fi
    if docker context use rootless >/dev/null 2>&1; then
        echo "已切换到 rootless context"
    else
        echo "⚠️  未找到 rootless context，请检查 docker context ls" >&2
    fi
}

main() {
    echo "=========================================="
    echo "Rootless Docker 配置（opt-in，不写 shell 配置）"
    echo "=========================================="
    install_packages
    mask_rootful
    setup_rootless
    ensure_context
    echo ""
    echo "✅ 完成。rootless 就绪状态："
    docker version --format '  client={{.Client.Version}} server={{.Server.Version}}' 2>/dev/null \
        || echo "  server 未起，排查: systemctl --user status docker"
    docker context ls --format '  context={{.Name}} endpoint={{.DockerEndpoint}}' 2>/dev/null || true
}

main "$@"
