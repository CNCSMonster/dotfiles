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
# The following lines were added by compinstall
zstyle :compinstall filename "$HOME/.zshrc"
autoload -Uz compinit
compinit
_comp_options+=(globdots)
# End of lines added by compinstall

# -----------------
# Zim configuration
# -----------------

# Use degit instead of git as the default tool to install and update modules.
#zstyle ':zim:zmodule' use 'degit'

# --------------------
# Module configuration
# --------------------

#
# git
#

# Set a custom prefix for the generated aliases. The default prefix is 'G'.
#zstyle ':zim:git' aliases-prefix 'g'

#
# input
#

# Append `../` to your input for each `.` you type after an initial `..`
#zstyle ':zim:input' double-dot-expand yes

#
# termtitle
#

# Set a custom terminal title format using prompt expansion escape sequences.
# See http://zsh.sourceforge.net/Doc/Release/Prompt-Expansion.html#Simple-Prompt-Escapes
# If none is provided, the default '%n@%m: %~' is used.
#zstyle ':zim:termtitle' format '%1~'

#
# zsh-autosuggestions
#

# Disable automatic widget re-binding on each precmd. This can be set when
# zsh-users/zsh-autosuggestions is the last module in your ~/.zimrc.
ZSH_AUTOSUGGEST_MANUAL_REBIND=1

# Customize the style that the suggestions are shown with.
# See https://github.com/zsh-users/zsh-autosuggestions/blob/master/README.md#suggestion-highlight-style
#ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=242'

#
# zsh-syntax-highlighting
#

# Set what highlighters will be used.
# See https://github.com/zsh-users/zsh-syntax-highlighting/blob/master/docs/highlighters.md
ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets)

# Customize the main highlighter styles.
# See https://github.com/zsh-users/zsh-syntax-highlighting/blob/master/docs/highlighters/main.md#how-to-tweak-it
#typeset -A ZSH_HIGHLIGHT_STYLES
#ZSH_HIGHLIGHT_STYLES[comment]='fg=242'

#
# fzf-tab
#
zstyle ':fzf-tab:complete:*' fzf-bindings 'ctrl-s:toggle' 'ctrl-a:toggle-all'

cmds=('bat')
for cmd in "${(@kv)cmds}"; do
    zstyle ":fzf-tab:complete:${cmd}:*" fzf-preview 'exa -a1 --color=auto -s=type $realpath'
done

# ------------------
# Initialize modules
# ------------------

hash -d zdot=$ZSH_CONFIG_HOME

_source-existent() {
    [[ -r $1 ]] && source $1
}

#==================#
# Plugins (Part 1) #
#==================#

[[ -d ~zdot/.zcomet ]] || git clone https://github.com/agkozak/zcomet ~zdot/.zcomet/bin

source ~zdot/.zcomet/bin/zcomet.zsh

# Update every 7 days.
# Start p10k instant prompt only when no update, otherwise update logs might not be displayed.
_qc_last_update=(~zdot/.zcomet/update(Nm-7))
if [[ -z $_qc_last_update ]] {
    touch ~zdot/.zcomet/update
    zcomet self-update
    zcomet update
    zcomet compile ~zdot/*.zsh  # NOTE: https://github.com/romkatv/zsh-bench#cutting-corners
} else {
    _source-existent ~cache/p10k-instant-prompt-${(%):-%n}.zsh
}

zcomet fpath zsh-users/zsh-completions src
zcomet fpath nix-community/nix-zsh-completions

zcomet load tj/git-extras etc/git-extras-completion.zsh
zcomet load QuarticCat/zsh-smartcache
zcomet load chisui/zsh-nix-shell
zcomet load romkatv/zsh-no-ps2

AUTOPAIR_SPC_WIDGET=magic-space
AUTOPAIR_BKSPC_WIDGET=backward-delete-char
AUTOPAIR_DELWORD_WIDGET=backward-delete-word
zcomet load hlissner/zsh-autopair

#==================#
# Plugins (Part 2) #
#==================#

zcomet compinit

zcomet load Aloxaf/fzf-tab  # TODO: run `build-fzf-tab-module` after update
zstyle ':fzf-tab:*' fzf-bindings 'tab:accept'
zstyle ':fzf-tab:*' switch-group '<' '>'
zstyle ':fzf-tab:*' prefix       ''
zstyle ':fzf-tab:complete:kill:argument-rest' fzf-preview 'ps hwwo cmd --pid=$word'
zstyle ':fzf-tab:complete:kill:argument-rest' fzf-flags   '--preview-window=down:3:wrap'
zstyle ':fzf-tab:complete:kill:*'             popup-pad   0 3
zstyle ':fzf-tab:complete:*' fzf-bindings 'ctrl-s:toggle' 'ctrl-a:toggle-all'

cmds=('bat')
for cmd in "${(@kv)cmds}"; do
    zstyle ":fzf-tab:complete:${cmd}:*" fzf-preview 'exa -a1 --color=auto -s=type $realpath'
done

zcomet load zsh-users/zsh-autosuggestions
ZSH_AUTOSUGGEST_MANUAL_REBIND=true
ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS+=(qc-{sub,shell}-r)

zcomet load zdharma-continuum/fast-syntax-highlighting
unset 'FAST_HIGHLIGHT[chroma-man]'  # chroma-man will stuck history browsing
unset 'FAST_HIGHLIGHT[chroma-ssh]'  # 旧版 ssh 不支持参数后置，高亮有误

zcomet load romkatv/powerlevel10k

# ------------------------------
# Post-init module configuration
# ------------------------------

# }}} End configuration added by Zim install

_source-existent ~zdot/p10k.zsh