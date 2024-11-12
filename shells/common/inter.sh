# 用于与 各种应用交互的 配置，比如注册应用的init函数,注册应用补全函数等等

# 如果是非交互式则退出，仅在交互模式下初始化
[[ $- != *i* ]] && return

[[ -n "$INTER_DONE" ]] && return


# eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv | rg -v 'export PATH=')"

# direnv
eval "$(direnv hook $SH)"

# fnm 
eval "$(fnm env --use-on-cd)"
eval "$(fnm completions --shell $SH)"

# fgm
eval "$(fgm init)"
eval "$(fgm completions --shell $SH)"

# zoxide is a faster way to navigate your filesystem
eval "$(zoxide init $SH)"

# starship is the minimal, blazing-fast, and infinitely customizable prompt for any shell!
eval "$(starship init $SH)"
# eval "$(mcfly init $SH)"

# 配置navi的快捷键为ctrl+n
eval "$(navi widget $SH)"


# eval "$(opam env)"

INTER_DONE=1
