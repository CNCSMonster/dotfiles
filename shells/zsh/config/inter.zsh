# 如果是非交互式则退出，仅在交互模式下初始化
[[ $- != *i* ]] && return

[[ -n "$INTER_DONE" ]] && return


if [ -n "$ZSH_VERSION" ]; then
	SH='zsh'
	source "$HOME/.config/shells/zsh/config.zsh"
elif [ -n "$BASH_VERSION" ]; then
	SH='bash'
fi

# eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv | rg -v 'export PATH=')"

# fnm 
eval "$(fnm env --use-on-cd)"
eval "$(fnm completions --shell $SH)"

# fgm
eval "$(fgm init)"

# zoxide is a faster way to navigate your filesystem
eval "$(zoxide init $SH)"

# starship is the minimal, blazing-fast, and infinitely customizable prompt for any shell!
eval "$(starship init $SH)"
# eval "$(mcfly init $SH)"

# 配置navi的快捷键为ctrl+n
# eval "$(navi widget $SH)"
_navi_call() {
   local result="$(navi "$@" </dev/tty)"
   printf "%s" "$result"
}
_navi_widget() {
   local -r input="${LBUFFER}"
   local -r last_command="$(echo "${input}" | navi fn widget::last_command)"
   local replacement="$last_command"

   if [ -z "$last_command" ]; then
      replacement="$(_navi_call --print)"
   elif [ "$LASTWIDGET" = "_navi_widget" ] && [ "$input" = "$previous_output" ]; then
      replacement="$(_navi_call --print --query "$last_command")"
   else
      replacement="$(_navi_call --print --best-match --query "$last_command")"
   fi

   if [ -n "$replacement" ]; then
      local -r find="${last_command}_NAVIEND"
      previous_output="${input}_NAVIEND"
      previous_output="${previous_output//$find/$replacement}"
   else
      previous_output="$input"
   fi

   zle kill-whole-line
   LBUFFER="${previous_output}"
   region_highlight=("P0 100 bold")
   zle redisplay
}
zle -N _navi_widget
bindkey '^n' _navi_widget

# eval "$(opam env)"

INTER_DONE=1
