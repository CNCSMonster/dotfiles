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


_source-existent() {
    [[ -r $1 ]] && source $1
}

#==================#
# Plugins (Part 1) #
#==================#

# zcomet - zsh 插件管理器
# 优先使用 submodule 版本，fallback 到运行时 clone
# 支持后台安装模式（通过环境变量控制）

_zcomet_load() {
    local ZCOMET_DIR="$ZSH_CONFIG_HOME/.zcomet"
    local LOCK_DIR="$ZSH_CONFIG_HOME/.zcomet.lock"
    local LOG_FILE="$ZSH_CONFIG_HOME/.zcomet-install.log"
    
    # 1. 如果已存在且有效，直接加载
    if [[ -f $ZCOMET_DIR/zcomet.zsh ]]; then
        source $ZCOMET_DIR/zcomet.zsh
        return 0
    fi
    
    # 2. 检查是否有 git
    if ! command -v git &>/dev/null; then
        echo "[zsh] 警告：git 未安装，zcomet 插件系统不可用" >&2
        return 0
    fi
    
    # 3. 检查是否已有后台进程在安装
    if [[ -d $LOCK_DIR ]]; then
        echo "[zsh] zcomet 正在后台安装中，安装完成后重启 shell 即可使用" >&2
        return 0
    fi
    
    # 4. 清理无效目录（可能是之前失败留下的）
    if [[ -d $ZCOMET_DIR ]] && [[ ! -f $ZCOMET_DIR/zcomet.zsh ]]; then
        echo "[zsh] 检测到无效的 .zcomet 目录，正在清理..." >&2
        rm -rf "$ZCOMET_DIR" 2>/dev/null
    fi
    
    # 5. 根据环境变量决定安装模式
    # ZCOMET_BG_INSTALL=0 → 前台安装（等待完成，阻塞）
    # 未设置或=1 → 后台安装（立即返回，不阻塞）【默认】
    if [[ "${ZCOMET_BG_INSTALL:-1}" != "0" ]]; then
        # === 后台模式（默认）===
        
        # 获取锁，防止重复启动
        if ! mkdir "$LOCK_DIR" 2>/dev/null; then
            echo "[zsh] zcomet 正在后台安装中" >&2
            return 0
        fi
        
        # 后台执行 clone
        {
            {
                echo "[zsh] 开始安装 zcomet..."
                # 确保目录不存在
                rm -rf "$ZCOMET_DIR" 2>/dev/null
                if git clone --depth 1 https://github.com/agkozak/zcomet "$ZCOMET_DIR" 2>&1; then
                    echo "[zsh] zcomet 安装完成！重启 shell 后生效"
                else
                    echo "[zsh] zcomet 安装失败，请检查网络连接"
                    rmdir "$LOCK_DIR" 2>/dev/null
                fi
            } > "$LOG_FILE" 2>&1
        } &!
        
        # 提示用户
        echo "[zsh] zcomet 正在后台安装中，当前会话部分功能不可用" >&2
        echo "[zsh] 安装日志：$LOG_FILE" >&2
        echo "[zsh] 安装完成后重启 shell 即可使用完整功能" >&2
    else
        # === 前台模式（可选，阻塞等待）===
        echo "[zsh] 首次启动，正在下载 zcomet（等待约 10-30 秒）..." >&2
        # 确保目录不存在
        rm -rf "$ZCOMET_DIR" 2>/dev/null
        if git clone --depth 1 https://github.com/agkozak/zcomet "$ZCOMET_DIR" 2>&1; then
            source "$ZCOMET_DIR/zcomet.zsh"
            echo "[zsh] zcomet 加载完成" >&2
        else
            echo "[zsh] 警告：zcomet 下载失败，插件功能不可用" >&2
        fi
    fi
}

_zcomet_load

# 检查 zcomet 是否成功加载，失败则跳过后续插件配置
if ! (( $+functions[zcomet] )); then
    echo "[zsh-config] 警告：zcomet 未加载，跳过插件系统" >&2
    return 0
fi

# Update every 7 days.
# Start p10k instant prompt only when no update, otherwise update logs might not be displayed.
_qc_last_update=($ZSH_CONFIG_HOME/.zcomet/update(Nm-7))
if [[ -z $_qc_last_update ]] {
    touch $ZSH_CONFIG_HOME/.zcomet/update
    zcomet self-update
    zcomet update
    zcomet compile $ZSH_CONFIG_HOME/*.zsh  # NOTE: https://github.com/romkatv/zsh-bench#cutting-corners
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

_source-existent $ZSH_CONFIG_HOME/p10k.zsh