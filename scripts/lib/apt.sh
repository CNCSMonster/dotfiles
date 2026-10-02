#!/usr/bin/env bash
# apt 执行策略的单一事实来源（有界超时 / 可见输出 / 失败归因）。
# 被 setup.sh（Layer 1 运行时依赖预检）与 scripts/install-system-packages.sh（Layer 0）source。
#
# 背景（2026-09 真实事故）：宿主把 apt 源指向腾讯云内网源 mirrors.tencentyun.com，
# 该域名解析到链路本地地址 169.254.0.3，在非腾讯云内网环境是 TCP 黑洞。apt 默认超时与
# 重试叠加，使 ./setup.sh 在「🔍 缺少 Layer 1 运行时依赖」之后静默挂起 4 分钟以上，
# 最终只留下「❌ 运行时依赖安装失败」，没有任何可执行的修复指引。
#
# 三条原则：
#   1. 有界 —— 连接超时、重试次数、dpkg 锁等待都有上限，坏源不会把脚本挂死。
#   2. 可见 —— 不用 -qq / 2>/dev/null 吞掉输出，apt 当前在做什么用户看得见。
#   3. 可归因 —— 装包前先探测源可达性；失败时打印「原因 + 可直接执行的修复命令」。
#
# 边界：本库只诊断、只提示，绝不改写 /etc/apt 下的用户源配置（换源属于用户决策）。
# 本文件只被 source，不单独执行，因此不设置 set 选项（避免改变调用方的 shell 模式）。

# 有界超时策略：命令行参数优先于 /etc/apt/apt.conf.d 与用户配置，保证坏源在分钟内归因。
# 与仓库根目录 apt-retry.conf（Docker 构建用，Retries 5 / Timeout 300）刻意不同：
# CI 构建宁可久等也要成功，本机安装宁可快速失败也要给出归因，不要互相"对齐"。
APT_OPTS=(
    -o "Acquire::http::Timeout=30"
    -o "Acquire::https::Timeout=30"
    -o "Acquire::Retries=1"
    -o "DPkg::Lock::Timeout=60"
)

# 私网/链路本地地址判定（169.254.x 是云内网专用源与 metadata 服务的常见段）
_apt_is_private_ip() {
    case "$1" in
        127.*|10.*|192.168.*|169.254.*|0.*) return 0 ;;
        172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
    esac
    return 1
}

# 把 apt 输出翻译成「原因 + 修复动作」。只读日志，不改任何配置。
# 用法: apt_failure_hint <apt 输出日志文件>
apt_failure_hint() {
    local log="$1"
    local hits=""

    # 1) sudo / 权限：apt 根本没跑起来
    if grep -qiE 'sudo:.*(password is required|a terminal is required|no tty)' "$log" 2>/dev/null; then
        echo "❌ 需要 sudo 权限（当前无交互终端）。请在终端执行后重跑:"
        echo "     sudo -v && ./setup.sh"
        return 0
    fi
    if grep -qE 'Permission denied' "$log" 2>/dev/null && grep -qiE 'lock|/var/lib' "$log" 2>/dev/null; then
        echo "❌ 权限不足：apt 需要 root（当前既非 root 也无可用 sudo）"
        echo "   请用 root 运行，或配置 sudo 后重跑 ./setup.sh"
        return 0
    fi

    # 2) dpkg/apt 前端锁被后台任务占用
    if grep -qiE 'could not get lock|could not open lock|unable to acquire .*lock|waiting for cache lock' "$log" 2>/dev/null; then
        echo "❌ dpkg/apt 前端锁被占用（常见: apt-daily / unattended-upgrades 在后台运行）"
        echo "   查看: ps aux | grep -E 'apt|dpkg'；等它结束后重跑 ./setup.sh"
        return 0
    fi

    # 3) DNS 失败（先于"源不可达"判断，否则会被误归因为网络源问题）
    if grep -qiE 'temporary failure resolving|could not resolve|name or service not known' "$log" 2>/dev/null; then
        echo "❌ DNS 解析失败：检查网络 / 代理 / /etc/resolv.conf 后重跑 ./setup.sh"
        return 0
    fi

    # 4) 源不可达（含云内网专用源）
    hits="$(grep -E 'Failed to fetch|Could not connect|Connection timed out|^[[:space:]]*Err:' "$log" 2>/dev/null \
        | sed -E 's/^[[:space:]]+//' | sort -u)"
    if [ -n "$hits" ]; then
        echo "❌ apt 源获取失败（apt 原始诊断）:"
        echo "$hits" | sed 's/^/     /'
        if grep -qi 'tencentyun' "$log" 2>/dev/null; then
            echo "   原因: 腾讯云内网源在非腾讯云内网环境不可达（解析到 169.254.x）。换成公网源后重跑:"
            echo "     sudo sed -i 's/mirrors\\.tencentyun\\.com/mirrors.cloud.tencent.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null"
        else
            echo "   处理: 把上方不可达的源换成本机可达的公网源后重跑 ./setup.sh"
        fi
        return 0
    fi

    echo "⚠️  apt 执行失败，原始输出见上方；修复后重跑 ./setup.sh"
    return 0
}

# 有界且可见的 apt-get 执行。
# 用法: apt_run <sudo 前缀（空串或 "sudo"）> <apt-get 参数...>
#   例: apt_run "$sudo_cmd" update
#       apt_run "$sudo_cmd" install -y --no-install-recommends libclang-dev
# 返回 apt-get 的退出码，失败时自动打印 apt_failure_hint。
# 调用方应在 if / || 中使用（本仓库两个调用点都设置了 set -e）。
apt_run() {
    local sudo_prefix="$1"
    shift
    local log rc=0
    local -a cmd=()

    log="$(mktemp "${TMPDIR:-/tmp}/apt-run.XXXXXX")" || log="${TMPDIR:-/tmp}/apt-run.$$"

    # shellcheck disable=SC2206 # 前缀按空白拆分是有意设计（"sudo" 或空）
    [ -n "$sudo_prefix" ] && cmd+=($sudo_prefix)
    # env 写在 sudo 之后：sudo 的 env_reset 会丢弃 `VAR=x sudo ...` 形式的赋值，
    # 导致非交互安装时 dpkg 退化为交互式提问而挂起。
    cmd+=(env DEBIAN_FRONTEND=noninteractive apt-get "${APT_OPTS[@]}")

    "${cmd[@]}" "$@" 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}

    if [ "$rc" -ne 0 ]; then
        apt_failure_hint "$log"
    fi
    rm -f "$log"
    return "$rc"
}

# 装包前的源可达性预检：逐源 5s 探测，先暴露黑洞源，而不是让 apt 自己去撞超时。
# 只提示不阻断（包可能已在缓存或别的源可用），随后 apt 仍以有界超时执行。
# 返回 0 = 未发现不可达源；1 = 存在不可达源（提示信息已打印）。
apt_sources_health_check() {
    command -v curl &>/dev/null || return 0

    local files=()
    local f uri host ip
    local dead=()
    local internal=()

    files+=(/etc/apt/sources.list)
    if [ -d /etc/apt/sources.list.d ]; then
        for f in /etc/apt/sources.list.d/*; do
            [ -e "$f" ] && files+=("$f")
        done
    fi

    # 同时覆盖经典 .list 格式与 deb822 (.sources) 的 URIs 字段
    while IFS= read -r uri; do
        [ -n "$uri" ] || continue
        if curl -m 5 -s -o /dev/null "$uri/"; then
            continue
        fi
        host="${uri#*://}"
        host="${host%%/*}"
        host="${host%%:*}"
        ip=""
        if command -v getent &>/dev/null; then
            ip="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}')"
        fi
        if [ -n "$ip" ] && _apt_is_private_ip "$ip"; then
            internal+=("$uri → $ip")
        else
            dead+=("$uri${ip:+ → $ip}")
        fi
    done < <(grep -rhoE 'https?://[^/[:space:]]+' "${files[@]}" 2>/dev/null | sort -u)

    if [ ${#dead[@]} -eq 0 ] && [ ${#internal[@]} -eq 0 ]; then
        return 0
    fi

    if [ ${#internal[@]} -gt 0 ]; then
        echo "❌ 检测到解析到私网/链路本地地址的 apt 源（本机网络不可达，会拖到超时）:"
        printf '     %s\n' "${internal[@]}"
        if printf '%s\n' "${internal[@]}" | grep -qi tencentyun; then
            echo "   腾讯云内网源 → 公网源（复制执行后重跑 ./setup.sh）:"
            echo "     sudo sed -i 's/mirrors\\.tencentyun\\.com/mirrors.cloud.tencent.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null"
        else
            echo "   处理: 把该源替换为本机可达的公网源后重跑 ./setup.sh"
        fi
    fi
    if [ ${#dead[@]} -gt 0 ]; then
        echo "⚠️  以下 apt 源 5s 内无响应（已定位风险源，apt 仍以有界超时继续尝试）:"
        printf '     %s\n' "${dead[@]}"
    fi
    return 1
}
