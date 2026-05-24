# =============================================================================
# 交互式 Shell 配置
# =============================================================================
# 用途：配置仅在交互式 shell 中生效的特性
# 范围：prompt、快捷键、命令增强等交互式功能
# 
# 与 env.sh 的分工：
#   - env.sh: 基础环境变量（PATH 等），所有场景都需要
#   - inter.sh: 交互式特性（prompt、快捷键），仅交互式 shell 需要
#
# 示例：
#   ✅ env.sh   - mise activate, PATH, JAVA_HOME
#   ✅ inter.sh - starship prompt, navi widget
# =============================================================================

# 非交互式 shell 直接返回（如：bash -c, Docker RUN, CI/CD）
[[ $- != *i* ]] && return

# 防止重复加载
[[ -n "$INTER_DONE" ]] && return

# =============================================================================
# 交互式工具初始化
# =============================================================================

# zoxide - 智能 cd 命令增强（交互式快捷键）
eval "$(zoxide init $SH)"

# starship - Shell 提示符（仅交互式显示）
eval "$(starship init $SH)"

# 历史搜索使用 shell 自带的 Ctrl+R + fzf，无需额外工具
if [ ! -f "$HOME/.cache/zsh/histfile" ]; then
    mkdir -p "$HOME/.cache/zsh"
    touch "$HOME/.cache/zsh/histfile"
fi

# navi - 命令快捷键（Ctrl+N）
eval "$(navi widget $SH)"

# xdotter / xd - dotfiles 管理器命令补全
# xd 是新版命令名；xdotter 是旧版命令名。两者的补全子命令参数不同。
if command -v xd >/dev/null 2>&1; then
    eval "$(xd completion "$SH")"
elif command -v xdotter >/dev/null 2>&1; then
    eval "$(xdotter completions --shell "$SH")"
fi

# =============================================================================
# Yazi - 文件管理器 shell 集成
# =============================================================================
# 使用 y 命令启动 yazi，退出后自动 cd 到当前目录
# 快捷键：
#   q     - 退出并 cd
#   Q     - 退出不切换目录
y() {
    local tmp="$(mktemp -t "yazi-cwd.XXXXXX")"
    yazi --cwd-file="$tmp"
    if cwd="$(cat -- "$tmp" 2>/dev/null)" && [ -n "$cwd" ] && [ "$cwd" != "$PWD" ]; then
        cd -- "$cwd"
    fi
    rm -f -- "$tmp"
}

# 标记已完成加载
INTER_DONE=1
