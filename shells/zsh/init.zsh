set +u
# 用于防止重复初始化， 比如source多次init.zsh
if [ -z "$INIT_DONE" ]; then
	INIT_DONE=1
else
	return
fi

export SH_COMMON_DIR="$HOME/.config/shells/common"
source "$SH_COMMON_DIR/env.sh"
# 设置zsh的配置文件目录
export ZSH_CONFIG_HOME="$XDG_CONFIG_HOME/shells/zsh"

source "$ZSH_CONFIG_HOME/config.zsh"

source "$SH_COMMON_DIR/inter.sh"
source "$SH_COMMON_DIR/alias.sh"
source "$SH_COMMON_DIR/fn.sh"


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



