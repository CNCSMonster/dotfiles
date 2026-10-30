########################################################
# 各种快捷功能函数
########################################################

# fzf jump
function fj() {
    # 如果有两个命令行参数，第一个参数将作为 `fd` 的输入，第二个参数将作为 `fzf` 的查询来源。

    # 检查命令行参数的数量
    if [ $# -eq 2 ]; then
        # 如果有两个参数，第一个作为 fd 的输入，第二个作为 fzf 的查询输入
        target=$(fd "$1" | fzf -q "$2")
    elif [ $# -eq 1 ]; then
        # 如果没有两个参数，使用第一个参数作为fzf查询输入
        target=$(fd . | fzf -q $1)
    else
        target=$(fd . | fzf)
    fi

    # 检查是否选择了目标目录
    if [ -n "$target" ]; then
        if [ -d "$target" ]; then
            cd "$target"
        else
            cd $(dirname $target)
        fi
    else
        echo "No target dir selected"
    fi
}

# ============================================================
# npm/pnpm 镜像源切换（淘宝镜像）
# ============================================================
# 用法 1: npm-cn install <package>  (临时使用)
# 用法 2: use-npm-mirror 后正常使用 npm (持续生效)
# 用法 3: use-npm-official 切换回官方源
# ============================================================

# 临时使用淘宝镜像运行 npm 命令
function npm-cn() {
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com npm "$@"
}

# 临时使用淘宝镜像运行 pnpm 命令
function pnpm-cn() {
    PNPM_CONFIG_REGISTRY=https://registry.npmmirror.com pnpm "$@"
}

# 切换到淘宝镜像模式（持续生效，直到 use-npm-official）
function use-npm-mirror() {
    export NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
    export PNPM_CONFIG_REGISTRY=https://registry.npmmirror.com
    echo "✅ 已切换到淘宝镜像模式"
}

# 切换回官方源
function use-npm-official() {
    unset NPM_CONFIG_REGISTRY
    unset PNPM_CONFIG_REGISTRY
    echo "✅ 已切换到官方源"
}

# ============================================================
# Windows 宿主命令执行（以 Windows 家目录与环境变量规范运行）
# ============================================================
function winrun() {
    powershell.exe -NoProfile -Command "
        \$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User');
        if (-not \$env:CNCSMONSTER_API_KEY) {
            \$env:CNCSMONSTER_API_KEY = [Environment]::GetEnvironmentVariable('CNCSMONSTER_API_KEY', 'User')
        };
        cd \$HOME;
        $*
    "
}

# ========================================================
# 按需 AI Shell 模式 (跨 Zsh/Bash)
# 支持: 自然语言回车 / ?? (通用) / <工具>? (如 git?) / fix?
# 会话内开关: ai-shell on|off|status
# 跨会话持久: ai-shell persist on|off （默认不跨会话，需显式开启）
# ========================================================
# 判断未识别的输入是否应按自然语言交给 AI 推导：
#   - 只要含非 ASCII 字符（中文等）就一定是自然语言，长度再短也要接手
#   - 纯 ASCII 输入只有在长度 >= 3 时才接手，避免把打错的短命令（如 lg）劫持成 AI 提问
# 注意：zsh/bash 的 ${#var} 统计的是字符数，"你好" 只有 2 个字符，
# 因此不能直接用字符数做门槛，否则两字中文需求会被当成打错的命令丢弃。
_ai_shell_is_natural_language() {
    local query="$1"
    [[ "$query" == *[![:ascii:]]* ]] && return 0
    [[ ${#query} -ge 3 ]]
}

# 跨会话持久模式的标记文件（存在 = 新开的交互式 shell 自动进入 AI 模式）
_ai_shell_persist_file() {
    echo "${XDG_CONFIG_HOME:-$HOME/.config}/ai-shell/persist"
}

# 统一的 command not found 处理器：WSL .exe 兜底 → AI 推导 → 原生报错
_ai_shell_command_not_found() {
    local first="$1"

    # WSL 场景：命令找不到时自动补 .exe（不受 AI 开关影响）
    if command -v "${first}.exe" >/dev/null 2>&1; then
        shift
        "${first}.exe" "$@"
        return $?
    fi

    if [ -z "${AI_SHELL_ENABLED:-}" ]; then
        _ai_shell_not_found_message "$first"
        return 127
    fi

    # <工具>? / fix?（仅这两个分支要摘掉首个词）
    if [[ "$first" =~ ^([a-zA-Z0-9_-]+)[\?？]$ ]]; then
        local tool
        if [ -n "$ZSH_VERSION" ]; then
            tool="${match[1]}"
        else
            tool="${BASH_REMATCH[1]}"
        fi
        shift
        if [[ "$tool" == "fix" ]]; then
            local last_cmd
            if [ -n "$ZSH_VERSION" ]; then
                last_cmd="$(fc -ln -1 2>/dev/null)"
            else
                last_cmd="$(history -p '!!' 2>/dev/null)"
            fi
            _ai_shell_exec "上一条命令报错了，请诊断并给出修复建议: $last_cmd"
            return $?
        fi
        _ai_shell_exec --scope "$tool" "$*"
        return $?
    fi

    # 自然语言：首词就是需求的一部分，不能 shift 掉
    local query="$*"
    if _ai_shell_is_natural_language "$query"; then
        _ai_shell_exec "$query"
        return $?
    fi
    _ai_shell_not_found_message "$first"
    return 127
}

# 原生报错文案：保持与 zsh/bash 各自的默认输出一致
_ai_shell_not_found_message() {
    if [ -n "$ZSH_VERSION" ]; then
        echo "zsh: command not found: $1" >&2
    else
        echo "bash: $1: command not found" >&2
    fi
}

_ai_shell_install_handler() {
    # 如果 mise 已经将 command_not_found 包装为 _command_not_found_handler，切勿覆盖
    [ -n "${_mise_cmd_not_found:-}" ] && return 0
    if [ -n "$ZSH_VERSION" ]; then
        command_not_found_handler() { _ai_shell_command_not_found "$@"; }
    elif [ -n "$BASH_VERSION" ]; then
        command_not_found_handle() { _ai_shell_command_not_found "$@"; }
    fi
}

_ai_shell_enable() {
    AI_SHELL_ENABLED=1
    if [ -n "$ZSH_VERSION" ]; then
        unsetopt NOMATCH 2>/dev/null || true
        alias '??'='noglob _ai_shell_exec'
        alias 'git?'='noglob _ai_shell_exec --scope git'
        alias 'gh?'='noglob _ai_shell_exec --scope gh'
        alias 'fix?'='noglob _ai_shell_exec fix'
    elif [ -n "$BASH_VERSION" ]; then
        alias '??'='_ai_shell_exec'
        alias 'git?'='_ai_shell_exec --scope git'
        alias 'gh?'='_ai_shell_exec --scope gh'
        alias 'fix?'='_ai_shell_exec fix'
    fi
}

_ai_shell_disable() {
    AI_SHELL_ENABLED=
    if [ -n "$ZSH_VERSION" ]; then
        setopt NOMATCH 2>/dev/null || true
        unalias '??' 'git?' 'gh?' 'fix?' 2>/dev/null || true
    elif [ -n "$BASH_VERSION" ]; then
        unalias '??' 'git?' 'gh?' 'fix?' 2>/dev/null || true
    fi
}

_ai_shell_exec() {
    local scope="generic"
    if [ "$1" = "--scope" ]; then
        scope="$2"
        shift 2
    fi

    local query="$*"
    [[ -z "$query" ]] && return 0

    local script_path="${SH_COMMON_DIR:-$HOME/.config/shells/common}/../scripts/ai-shell-backend.py"
    if [ ! -f "$script_path" ]; then
        script_path="$HOME/dotfiles/shells/scripts/ai-shell-backend.py"
    fi

    local target_cmd
    target_cmd=$(python3 "$script_path" --scope "$scope" "$query")
    local ret=$?

    if [[ $ret -ne 0 || -z "$target_cmd" ]]; then
        return 127
    fi

    if [[ -n "$target_cmd" ]]; then
        # 用户明确选择进入编辑模式 (按 e)
        if [[ "$target_cmd" == EDIT:* ]]; then
            target_cmd="${target_cmd#EDIT:}"
            if [ -n "$ZSH_VERSION" ]; then
                print -s "$target_cmd"
                print -z "$target_cmd"
            elif [ -n "$BASH_VERSION" ]; then
                history -s "$target_cmd"
                read -e -i "$target_cmd" -p "$ " edited_cmd
                [[ -n "$edited_cmd" ]] && eval "$edited_cmd"
            fi
            return 0
        fi

        # 默认直接执行，并在异常时捕获 Stderr 自动反思修复
        if [ -n "$ZSH_VERSION" ]; then
            print -s "$target_cmd"
        elif [ -n "$BASH_VERSION" ]; then
            history -s "$target_cmd"
        fi
        echo -e "\033[32m▶ 执行:\033[0m $target_cmd"

        local err_dir="/dev/shm"
        [ ! -d "$err_dir" ] && err_dir="/tmp"
        local err_tmp="$err_dir/ai_shell_err_$$.log"
        rm -f "$err_tmp"

        eval "$target_cmd" 2> >(tee >(tail -n 10 > "$err_tmp") >&2)
        local cmd_ret=$?
        sleep 0.05

        # 命令非 0 失败、排除主动中断(130/143)、且有错误日志时，触发深度为1的反思
        if [[ $cmd_ret -ne 0 && $cmd_ret -ne 130 && $cmd_ret -ne 143 && -s "$err_tmp" && -z "$AI_SHELL_REFLECT_DEPTH" ]]; then
            export AI_SHELL_REFLECT_DEPTH=1
            local fix_cmd
            fix_cmd=$(python3 "$script_path" --fix "$target_cmd" --err-file "$err_tmp")
            unset AI_SHELL_REFLECT_DEPTH
            rm -f "$err_tmp"

            if [[ -n "$fix_cmd" ]]; then
                [[ "$fix_cmd" == EDIT:* ]] && fix_cmd="${fix_cmd#EDIT:}"
                if [ -n "$ZSH_VERSION" ]; then
                    print -s "$fix_cmd"
                    print -z "$fix_cmd"
                elif [ -n "$BASH_VERSION" ]; then
                    history -s "$fix_cmd"
                    read -e -i "$fix_cmd" -p "$ " edited_cmd
                    [[ -n "$edited_cmd" ]] && eval "$edited_cmd"
                fi
            fi
        else
            rm -f "$err_tmp"
        fi
    fi
}

ai-shell() {
    case "${1:-}" in
        on|enable)
            _ai_shell_enable
            echo -e "\033[32m⚡ AI Shell 模式已开启\033[0m"
            echo -e "   - 方式1: 直接输入自然语言回车 (自动推导，执行报错自动反思)"
            echo -e "   - 方式2: ?? <需求> (通用提问)"
            echo -e "   - 方式3: <工具>? <需求> (如 fd? docker? git? 等任意工具)"
            echo -e "   - 方式4: fix? (一键诊断并修复上一条失败命令)"
            echo -e "   - 本次会话关闭: 'ai-shell off'；每次启动都开启: 'ai-shell persist on'"
            ;;
        off|disable)
            _ai_shell_disable
            echo -e "\033[33m💤 AI Shell 模式已关闭，已完全恢复原生 Shell 行为。\033[0m"
            ;;
        status)
            if [ -n "${AI_SHELL_ENABLED:-}" ]; then
                echo "AI Shell 当前会话: 🟢 已开启 (ON)"
            else
                echo "AI Shell 当前会话: ⚪ 已关闭 (OFF)"
            fi
            local pfile="$(_ai_shell_persist_file)"
            if [ -f "$pfile" ]; then
                local ptime
                ptime="$(cat "$pfile" 2>/dev/null)"
                if [ -n "$ptime" ]; then
                    echo "AI Shell 跨会话模式: 📌 已持久开启 (自 $ptime，新终端自动开启)"
                else
                    echo "AI Shell 跨会话模式: 📌 已持久开启 (新终端自动开启)"
                fi
            else
                echo "AI Shell 跨会话模式: ⚪ 未启用 (新终端默认关闭)"
            fi
            ;;
        persist)
            case "${2:-}" in
                on|enable)
                    mkdir -p "$(dirname "$(_ai_shell_persist_file)")" &&
                        date '+%Y-%m-%d %H:%M:%S' > "$(_ai_shell_persist_file)" || {
                        echo "❌ 写入持久标记失败: $(_ai_shell_persist_file)" >&2
                        return 1
                    }
                    _ai_shell_enable
                    echo -e "\033[32m📌 跨会话模式已开启：今后每个交互式 shell 启动时自动进入 AI Shell（当前会话已生效）\033[0m"
                    echo "   - 取消: ai-shell persist off"
                    ;;
                off|disable)
                    rm -f "$(_ai_shell_persist_file)" || {
                        echo "❌ 删除持久标记失败: $(_ai_shell_persist_file)" >&2
                        return 1
                    }
                    echo -e "\033[33m📌 跨会话模式已关闭：新开的终端不再自动进入 AI Shell（当前会话状态不变，需要时用 'ai-shell off'）\033[0m"
                    ;;
                *)
                    local pfile="$(_ai_shell_persist_file)"
                    if [ -f "$pfile" ]; then
                        echo "AI Shell 跨会话模式: 📌 已持久开启 (新终端自动开启)"
                    else
                        echo "AI Shell 跨会话模式: ⚪ 未启用 (新终端默认关闭)"
                    fi
                    echo "用法: ai-shell persist on (跨会话开启) | ai-shell persist off (取消跨会话)"
                    ;;
            esac
            ;;
        *)
            echo "用法: ai-shell on (本次会话开启) | ai-shell off (本次会话关闭) | ai-shell status (状态)"
            echo "      ai-shell persist on/off (跨会话持久模式，新终端自动生效)"
            ;;
    esac
}
