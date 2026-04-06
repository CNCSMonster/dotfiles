if [ -n "$ZSH_VERSION" ]; then
    SH='zsh'
elif [ -n "$BASH_VERSION" ]; then
    SH='bash'
fi

# XDG
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share"

# 如果下载了brew，则添加其需要的环境变量
if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval $(/opt/homebrew/bin/brew shellenv)
    export PATH=/opt/homebrew/opt/llvm/bin:$PATH
fi

# 常用系统路径（应对系统默认路径缺失的情况）
export PATH="/usr/local/sbin:\
/usr/local/bin:\
/usr/sbin:\
/usr/bin:\
/sbin:\
/bin"


# rust 工具链镜像源 (rsproxy.cn - 字节跳动维护)
export RUSTUP_DIST_SERVER='https://rsproxy.cn'
export RUSTUP_UPDATE_ROOT='https://rsproxy.cn/rustup'


# Rust 工具安装失败控制
# CARGO_INSTALL_STRICT=1 时，任何工具安装失败都会终止整个 setup.sh 脚本
# 默认值为 0，允许部分工具失败，继续安装后续工具
# export CARGO_INSTALL_STRICT=1
# go路径
export GOBIN="$HOME/go/bin"
export PATH="$GOBIN:$PATH"

# ort crate使用的onnxruntime库路径
export ORT_LIB_LOCATION=/usr/local/lib/libonnxruntime.a

# moonbit 路径
export PATH="$HOME/.moon/bin:$PATH"

# llvm镜像源
export LLVM_PATH='/usr/lib/llvm'
export LLVM_BIN_PATH="$LLVM_PATH/bin"
export PATH="$LLVM_BIN_PATH:$PATH"

# snap 路径
export PATH="/snap/bin:$PATH"

# 用户可执行程序目录
# 将本地目录放在 PATH 前面，优先于系统/WSL Windows PATH
export PATH="$HOME/.local/bin:\
$HOME/.cargo/bin:\
$HOME/.config/shells/scripts:\
$PATH:\
$HOME/.local/scripts:\
$XDG_DATA_HOME/JetBrains/Toolbox/scripts:\
/usr/lib/jvm/default/bin"

# PATH 去重（保留不存在的目录，因为它们可能稍后被创建）
# 使用 awk 实现，兼容所有 POSIX shell
cleanup_path() {
    echo "$1" | tr ':' '\n' | awk '
    {
        dir = $0
        # 跳过空目录
        if (dir == "") next
        # 去重
        if (seen[dir]++) next
        # 输出
        if (first++) printf ":"
        printf "%s", dir
    }
    '
}
export PATH="$(cleanup_path "$PATH")"

####################
# dir alias config #
####################
hash -d cache=$XDG_CACHE_HOME

# fcitx5
# export XMODIFIERS='@im=fcitx'
# export GTK_IM_MODULE='fcitx'
# export QT_IM_MODULE='fcitx'
# export SDL_IM_MODULE='fcitx'
# export QT_QPA_PLATFORMTHEME='qt5ct'

# vimtex 工作缓存目录
# export VIMTEX_OUTPUT_DIRECTORY='./target/tex'

# 默认编辑器
export EDITOR='hx'

# # mcfly
export MCFLY_FUZZY=2
export MCFLY_RESULTS=25

# =============================================================================
# mise 版本管理工具
# =============================================================================
# 提供 npm/node/go/zig 等命令的环境变量
# 注意：这是基础环境配置，交互式和非交互式环境都需要
# 与 inter.sh 的区别：
#   - env.sh: 基础环境变量（PATH 等），所有场景都需要
#   - inter.sh: 交互式特性（prompt、快捷键），仅交互式 shell 需要
if command -v mise &>/dev/null; then
    eval "$(mise activate $SH)" 2>/dev/null || true
fi
