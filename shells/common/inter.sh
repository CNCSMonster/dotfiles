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
if command -v xd >/dev/null 2>&1; then
    eval "$(xd completion "$SH")"
fi

# llm-proxy - 本地 LLM 代理命令行补全
if command -v llm-proxy >/dev/null 2>&1; then
    eval "$(llm-proxy completion "$SH")"
fi

# codex - OpenAI 代码助手补全
if command -v codex >/dev/null 2>&1; then
    eval "$(codex completion "$SH" 2>/dev/null)"
fi

# opencode - OpenCode 代码助手补全
if command -v opencode >/dev/null 2>&1; then
    eval "$(opencode completion "$SH" 2>/dev/null)"
fi

# just - 命令运行器补全
if command -v just >/dev/null 2>&1; then
    eval "$(JUST_COMPLETE="$SH" just)"
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

# =============================================================================
# mise - 交互式 shell 激活
# =============================================================================
# 职责：交互式 shell 中加载 [env] 环境变量并安装 prompt hook
# 与 env.sh 的分工：
#   - env.sh: 非交互式/所有场景的基础环境变量（PATH 等）
#   - inter.sh: 交互式 shell 中加载 [env] 并安装 prompt hook
# 为什么拆分：
#   - activate 依赖 prompt 触发，每次 prompt 自动更新 PATH 和 [env]
#   - 不适合非交互式 shell（CI、脚本），因为非交互式没有 prompt
#   - 因此放在 inter.sh 中，仅在交互式 shell 中执行
if command -v mise &>/dev/null; then
    eval "$(mise activate $SH)" 2>/dev/null || true
fi

# 标记已完成加载
INTER_DONE=1
