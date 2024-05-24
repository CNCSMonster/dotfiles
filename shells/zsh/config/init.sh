ZSH_CONFIG_HOME="$HOME/.config/zsh"

source "$ZSH_CONFIG_HOME/env.sh"

if [ -z "$INIT_DONE" ]; then
	INIT_DONE=1
else
	return
fi

# 整理 PATH，删除重复路径
if [ -n "$PATH" ]; then
	old_PATH=$PATH:
	PATH=
	while [ -n "$old_PATH" ]; do
		x=${old_PATH%%:*}
		case $PATH: in
		*:"$x":*) ;;
		*) PATH=$PATH:$x ;;
		esac
		old_PATH=${old_PATH#*:}
	done
	PATH=${PATH#:}
	unset old_PATH x
fi

export PATH

source "$HOME/.config/zsh/inter.sh"
