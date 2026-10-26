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
# 按需 AI Shell 模式 (跨 Zsh/Bash，完全受控于 ai-shell on/off)
# 支持: 自然语言回车 / ?? (通用) / git? (Git专属) / gh? (CLI专属)
# ========================================================
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

    if [[ $ret -eq 0 && -n "$target_cmd" ]]; then
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
    case "$1" in
        on|enable)
            if [ -n "$ZSH_VERSION" ]; then
                unsetopt NOMATCH 2>/dev/null || true
                command_not_found_handler() {
                    if (( $+commands[${1}.exe] )); then
                        ${1}.exe "${@[2,-1]}"
                        return $?
                    fi
                    local first="$1"
                    if [[ "$first" =~ ^([a-zA-Z0-9_-]+)[\?？]$ ]]; then
                        local tool="${match[1]}"
                        shift
                        if [[ "$tool" == "fix" ]]; then
                            local last_cmd="$(fc -ln -1 2>/dev/null)"
                            _ai_shell_exec "上一条命令报错了，请诊断并给出修复建议: $last_cmd"
                            return $?
                        fi
                        _ai_shell_exec --scope "$tool" "$*"
                        return $?
                    fi
                    local query="$*"
                    [[ ${#query} -lt 3 ]] && { echo "zsh: command not found: $1" >&2; return 127; }
                    _ai_shell_exec "$query"
                }
                alias '??'='noglob _ai_shell_exec'
                alias 'git?'='noglob _ai_shell_exec --scope git'
                alias 'gh?'='noglob _ai_shell_exec --scope gh'
            elif [ -n "$BASH_VERSION" ]; then
                command_not_found_handle() {
                    local first="$1"
                    if [[ "$first" =~ ^([a-zA-Z0-9_-]+)[\?？]$ ]]; then
                        local tool="${BASH_REMATCH[1]}"
                        shift
                        if [[ "$tool" == "fix" ]]; then
                            local last_cmd="$(history -p '!!' 2>/dev/null)"
                            _ai_shell_exec "上一条命令报错了，请诊断并给出修复建议: $last_cmd"
                            return $?
                        fi
                        _ai_shell_exec --scope "$tool" "$*"
                        return $?
                    fi
                    local query="$*"
                    [[ ${#query} -lt 3 ]] && { echo "bash: $1: command not found" >&2; return 127; }
                    _ai_shell_exec "$query"
                }
                alias ??='_ai_shell_exec'
                alias git?='_ai_shell_exec --scope git'
                alias gh?='_ai_shell_exec --scope gh'
                alias fix?='_ai_shell_exec fix'
            fi
            echo -e "\033[32m⚡ AI Shell 模式已开启\033[0m"
            echo -e "   - 方式1: 直接输入自然语言回车 (自动推导，执行报错自动反思)"
            echo -e "   - 方式2: ?? <需求> (通用提问)"
            echo -e "   - 方式3: <工具>? <需求> (如 fd? docker? git? 等任意工具)"
            echo -e "   - 方式4: fix? (一键诊断并修复上一条失败命令)"
            echo -e "   - 关闭模式: 运行 'ai-shell off'"
            ;;
        off|disable)
            if [ -n "$ZSH_VERSION" ]; then
                setopt NOMATCH 2>/dev/null || true
                unalias '??' 'git?' 'gh?' 2>/dev/null || true
                command_not_found_handler() {
                    if (( $+commands[${1}.exe] )); then
                        ${1}.exe "${@[2,-1]}"
                    else
                        echo "zsh: command not found: $1" >&2
                        return 127
                    fi
                }
            elif [ -n "$BASH_VERSION" ]; then
                unalias ?? git? gh? 2>/dev/null || true
                unset -f command_not_found_handle 2>/dev/null || true
            fi
            echo -e "\033[33m💤 AI Shell 模式已关闭，已完全恢复原生 Shell 行为。\033[0m"
            ;;
        status)
            if [ -n "$ZSH_VERSION" ]; then
                if alias "??" >/dev/null 2>&1; then
                    echo "AI Shell 当前状态: 🟢 已开启 (ON)"
                else
                    echo "AI Shell 当前状态: ⚪ 已关闭 (OFF)"
                fi
            elif [ -n "$BASH_VERSION" ]; then
                if alias ?? >/dev/null 2>&1; then
                    echo "AI Shell 当前状态: 🟢 已开启 (ON)"
                else
                    echo "AI Shell 当前状态: ⚪ 已关闭 (OFF)"
                fi
            fi
            ;;
        *)
            echo "用法: ai-shell on (开启) | ai-shell off (关闭) | ai-shell status (状态)"
            ;;
    esac
}
