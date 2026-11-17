# Start configuration added by Zim install {{{
#
# User configuration sourced by interactive shells
#

# -----------------
# Zsh configuration
# -----------------



#
# History
#

export HISTFILE="${XDG_CACHE_HOME}/zsh/histfile"
HISTSIZE=1000
SAVEHIST=1000

# save history after each command
setopt INC_APPEND_HISTORY

# share history across all sessions
setopt SHARE_HISTORY

# Remove older command from the history if a duplicate is to be added.
setopt HIST_IGNORE_ALL_DUPS

# 交互式允许 # 开头的注释行。
# zsh 的 INTERACTIVE_COMMENTS 默认关闭；本文件启用了 EXTENDED_GLOB（见文件后段），
# 关闭时行首 # 会被当成 glob 修饰符解析，表现为 `zsh: bad pattern: #`。
setopt INTERACTIVE_COMMENTS
# 注释行不写入历史（与 SHARE_HISTORY / INC_APPEND_HISTORY 配合，避免跨会话累积）。
HISTORY_IGNORE='\#*'

#
# Input/output
#

# Set editor default keymap to emacs (`-e`) or vi (`-v`)
bindkey -e

# Edit command buffer
autoload -z edit-command-line
zle -N edit-command-line
bindkey "^O" edit-command-line
bindkey -s "^Y" 'ya^M'

# Prompt for spelling correction of commands.
#setopt CORRECT

# Customize spelling correction prompt.
# SPROMPT='zsh: correct %F{red}%R%f to %F{green}%r%f [nyae]? '

# Remove path separator from WORDCHARS.
WORDCHARS=${WORDCHARS//[\/]}

# Completion
_comp_options+=(globdots)

# 补全选项与 fzf-tab 联动配置：
# 1. 禁用 zsh 原生菜单选择，允许 fzf-tab 接管菜单展示与捕获公共前缀
zstyle ":completion:*" menu no
# 2. 补全行为选项：自动菜单（非 fzf-tab 场景回退），保留歧义列表，允许在词内顺畅执行补全
setopt AUTO_MENU
setopt LIST_AMBIGUOUS
setopt COMPLETE_IN_WORD
unsetopt MENU_COMPLETE

#
# fzf-tab
#
zstyle ':fzf-tab:complete:*' fzf-bindings 'ctrl-s:toggle' 'ctrl-a:toggle-all'

# ------------------
# Initialize modules
# ------------------


_source-existent() {
    [[ -r $1 ]] && source $1
}

#==================#
# Plugins (Part 1) #
#==================#

# zcomet trust boundary: startup is offline and never repairs user checkouts.
# BEGIN ZCOMET PIN GUARD
_dotfiles_zcomet_checkout_ok() {
    local dir="$1" pin="$2" repo="$3" actual dirty origin
    if [[ ! $pin =~ '^[0-9a-f]{40}$' || ! -d "$dir/.git" ]]; then
        print -u2 -- "[zsh] 警告：跳过 $dir：缺失独立 Git checkout 或 pin 非完整 SHA；请按插件 SOP 人工处理（未修改目录）"
        return 1
    fi
    if ! actual=$(command git -C "$dir" rev-parse --verify HEAD 2>/dev/null) ||
       ! dirty=$(command git -C "$dir" status --porcelain --untracked-files=no 2>/dev/null); then
        print -u2 -- "[zsh] 警告：跳过 $dir：Git 校验失败；未修改目录，请按插件 SOP 人工检查"
        return 1
    fi
    origin=$(command git -C "$dir" config --get remote.origin.url 2>/dev/null)
    if [[ "$actual" != "$pin" || -n "$dirty" ||
          ( "$origin" != "https://github.com/$repo" &&
            "$origin" != "https://github.com/$repo.git" &&
            "$origin" != "git@github.com:$repo.git" ) ]]; then
        print -u2 -- "[zsh] 警告：跳过 $dir：期望 $pin，实际 $actual，或 tracked 文件/origin 不符；未删除、覆盖或更新，请按插件 SOP 人工检查"
        return 1
    fi
}

_dotfiles_zcomet_load_manager() {
    local dir="$ZSH_CONFIG_HOME/.zcomet"
    local pin=3dfe6f837479c6731e74400a233739500ec6d648
    _dotfiles_zcomet_checkout_ok "$dir" "$pin" agkozak/zcomet || return 1
    [[ -f "$dir/zcomet.zsh" ]] || return 1
    source "$dir/zcomet.zsh" || return 1
    (( $+functions[zcomet] ))
}

_dotfiles_zcomet_plugin() {
    local action="$1" repo="${2%@*}" pin="${2##*@}" dir
    shift 2
    dir="${ZDOTDIR:-$HOME}/.zcomet/repos/$repo"
    _dotfiles_zcomet_checkout_ok "$dir" "$pin" "$repo" || return 1
    # Absolute local paths cannot trigger clone/fetch or a checkout switch.
    zcomet "$action" "$dir" "$@"
}

if ! _dotfiles_zcomet_load_manager; then
    print -u2 -- "[zsh-config] 警告：zcomet 未通过固定版本校验，跳过插件系统；启动不会安装或更新"
    return 0
fi
# END ZCOMET PIN GUARD

# 自定义补全目录优先加载（启动 0 开销，按需 Tab 补全）
[[ -d "$ZSH_CONFIG_HOME/completions" ]] && fpath=("$ZSH_CONFIG_HOME/completions" $fpath)
[[ -d "${XDG_CACHE_HOME:-$HOME/.cache}/zsh/completions" ]] && fpath=("${XDG_CACHE_HOME:-$HOME/.cache}/zsh/completions" $fpath)

_dotfiles_zcomet_plugin fpath zsh-users/zsh-completions@28c5bdcaf81bb89e56d0df8267d822c3b8aed9e0 src
_dotfiles_zcomet_plugin fpath nix-community/nix-zsh-completions@6e782b97091b07eb849b58953eb200ccc56ef833

_dotfiles_zcomet_plugin load tj/git-extras@13cbdfc51e22e635939d07af86b33fca78c45411 etc/git-extras-completion.zsh
_dotfiles_zcomet_plugin load QuarticCat/zsh-smartcache@54aba13a6824e212992fd754c598c9e9acd259a3
_dotfiles_zcomet_plugin load chisui/zsh-nix-shell@8b86281cf9e9ef9f207433dd8b36d157dd48d50a
_dotfiles_zcomet_plugin load romkatv/zsh-no-ps2@4b23567dc503170672386660706e55ce0201770c

AUTOPAIR_SPC_WIDGET=magic-space
AUTOPAIR_BKSPC_WIDGET=backward-delete-char
AUTOPAIR_DELWORD_WIDGET=backward-delete-word
_dotfiles_zcomet_plugin load hlissner/zsh-autopair@34a8bca0c18fcf3ab1561caef9790abffc1d3d49

#==================#
# Plugins (Part 2) #
#==================#

# 开启快速缓存校验模式（-C），若超过24小时或不存在则刷新全量缓存
local _comp_dump="${XDG_CACHE_HOME:-$HOME/.cache}/zsh/zcompdump"
zstyle ":zcomet:compinit" dump-file "$_comp_dump"
setopt EXTENDED_GLOB
if [[ -f "$_comp_dump" && -n "$_comp_dump"(#qN.mh-24) ]]; then
    zstyle ":zcomet:compinit" arguments -C
fi
zcomet compinit

_dotfiles_zcomet_plugin load Aloxaf/fzf-tab@d7e0234614dbe5369fdd760907d12c0e05a4dccc  # NOTE: after updating this plugin, run `build-fzf-tab-module` in its directory to compile the optional C module for better performance

zstyle ':completion:*:descriptions' format '[%d]'
zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}
zstyle ':fzf-tab:*' switch-group '<' '>'
zstyle ':fzf-tab:*' prefix       ''
zstyle ':fzf-tab:complete:kill:argument-rest' fzf-preview 'ps hwwo cmd --pid=$word'
zstyle ':fzf-tab:complete:kill:argument-rest' fzf-flags   '--preview-window=down:3:wrap'
zstyle ':fzf-tab:complete:kill:*'             popup-pad   0 3
zstyle ':fzf-tab:complete:*' fzf-bindings 'ctrl-s:toggle' 'ctrl-a:toggle-all'

cmds=('bat')
for cmd in "${(@kv)cmds}"; do
    zstyle ":fzf-tab:complete:${cmd}:*" fzf-preview 'eza -a1 --color=auto -s=type $realpath'
done

_dotfiles_zcomet_plugin load zsh-users/zsh-autosuggestions@e52ee8ca55bcc56a17c828767a3f98f22a68d4eb
ZSH_AUTOSUGGEST_MANUAL_REBIND=true
ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS+=(qc-{sub,shell}-r)

_dotfiles_zcomet_plugin load zdharma-continuum/fast-syntax-highlighting@5ecd353c81214f82bdeca5483fab6ccc5a2d5494
unset 'FAST_HIGHLIGHT[chroma-man]'  # chroma-man will stick history browsing
unset 'FAST_HIGHLIGHT[chroma-ssh]'  # old ssh highlighting has false positives with args


# ------------------------------
# Post-init module configuration
# ------------------------------

# }}} End configuration added by Zim install
