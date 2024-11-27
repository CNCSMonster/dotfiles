# 用于与 各种应用交互的 配置，比如注册应用的init函数,注册应用补全函数等等

# 如果是非交互式则退出，仅在交互模式下初始化
[[ $- != *i* ]] && return

[[ -n "$INTER_DONE" ]] && return

# mise
eval "$(mise activate $SH)"

# zoxide is a faster way to navigate your filesystem
eval "$(zoxide init $SH)"

# starship is the minimal, blazing-fast, and infinitely customizable prompt for any shell!
eval "$(starship init $SH)"

# mcfly is shell history search engine to replace origin <C+r>
eval "$(mcfly init $SH)"
if [ ! -f "$HOME/.cache/zsh/histfile" ]; then
    mkdir -p "$HOME/.cache/zsh"
    touch "$HOME/.cache/zsh/histfile"
fi

# 配置navi的快捷键为ctrl+n
eval "$(navi widget $SH)"

# eval "$(opam env)"

INTER_DONE=1
