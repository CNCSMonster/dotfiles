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

# =============================================================================
# 历史搜索（fzf 增强，替换 Ctrl+R）
# =============================================================================
# 设计原则：稳定性优先，不引入 atuin/mcfly 等外部工具
# 详见：docs/history-search.md
#
# 工作方式：
#   1. precmd hook 将每条命令的 PWD + 命令写入 sidecar 文件
#   2. Ctrl+R 从 sidecar 读取，fzf 展示时带目录信息
#   3. 当前目录的命令排在前面（fzf 对靠前条目有匹配加权）

mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}" 2>/dev/null
if [ ! -f "$HOME/.cache/zsh/histfile" ]; then
    mkdir -p "$HOME/.cache/zsh"
    touch "$HOME/.cache/zsh/histfile"
fi

_fhd_track() {
  local cmd
  if [[ -n "$ZSH_VERSION" ]]; then
    cmd=$(fc -ln -1 2>/dev/null) || return 0
    cmd="${cmd#"${cmd%%[![:space:]]*}"}"
  else
    cmd=$(HISTTIMEFORMAT='' history 1 2>/dev/null | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//') || return 0
  fi
  [[ -n "$cmd" ]] && printf '%s\t%s\n' "$PWD" "$cmd" >> "${XDG_CACHE_HOME:-$HOME/.cache}/shell-cwd-history" 2>/dev/null
  return 0
}

if [[ -n "$ZSH_VERSION" ]]; then
  precmd_functions+=(_fhd_track)
else
  PROMPT_COMMAND="_fhd_track${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
fi

_fhd_source() {
  local sidecar="${XDG_CACHE_HOME:-$HOME/.cache}/shell-cwd-history"
  local sh_hist="${HISTFILE:-$HOME/.cache/zsh/histfile}"

  {
    if [[ -f "$sidecar" ]]; then
      awk -F'\t' -v cwd="$PWD" '
        { dir=$1; cmd=$2
          if (dir == cwd && !seen_cwd[cmd]++) lines[++n_cwd]=cmd
          if (!seen_all[cmd]++) lines_all[++n_all]=cmd
        }
        END {
          for (i=n_cwd; i>0; i--) print lines[i]
          for (i=n_all; i>0; i--)
            if (!seen_cwd[lines_all[i]]++) print lines_all[i]
        }
      ' "$sidecar"
    fi
    if [[ -f "$sh_hist" ]]; then
      { tac "$sh_hist" 2>/dev/null || tail -r "$sh_hist" 2>/dev/null; } \
        | LC_ALL=C sed 's/^: [0-9][0-9]*:[0-9][0-9]*;//'
    fi
  } | awk '!seen[$0]++'
}

if [[ -n "$ZSH_VERSION" ]]; then
  _fhd_widget() {
    local selected
    selected=$(_fhd_source | fzf --height 50% --layout=reverse --border --tiebreak=index)
    if [[ -n "$selected" ]]; then
      LBUFFER="$selected"
      RBUFFER=""
    fi
    zle reset-prompt
  }
  zle -N _fhd_widget
  bindkey '^R' _fhd_widget
else
  _fhd_widget() {
    local selected
    selected=$(_fhd_source | fzf --height 50% --layout=reverse --border --tiebreak=index)
    if [[ -n "$selected" ]]; then
      READLINE_LINE="$selected"
      READLINE_POINT=${#selected}
    fi
  }
  bind -x '"\C-r": _fhd_widget'
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
