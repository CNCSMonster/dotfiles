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
if [[ -x "/opt/homebrew/bin/brew)" ]]; then
    eval $(/opt/homebrew/bin/brew shellenv)
fi

# rust 工具链镜像源
export RUSTUP_DIST_SERVER='https://mirrors.ustc.edu.cn/rust-static'
export RUSTUP_UPDATE_ROOT='https://mirrors.ustc.edu.cn/rust-static/rustup'

# go路径
export GOBIN="$HOME/go/bin"
export PATH="$GOBIN:$PATH"

# ort crate使用的onnxruntime库路径
export ORT_LIB_LOCATION=/usr/local/lib/libonnxruntime.a

# nvim 路径
export PATH="/opt/nvim/bin:$PATH"

# moonbit 路径
export PATH="$HOME/.moon/bin:$PATH"

# llvm镜像源
export LLVM_PATH='/usr/lib/llvm'
export LLVM_BIN_PATH="$LLVM_PATH/bin"
export PATH="$LLVM_BIN_PATH:$PATH"

# snap 路径
export PATH="/snap/bin:$PATH"

# 用户可执行程序目录
export PATH="$HOME/.cargo/bin:\
$HOME/.config/shells/scripts:\
$PATH:\
$HOME/.local/bin:\
$HOME/.local/scripts:\
$XDG_DATA_HOME/JetBrains/Toolbox/scripts:\
/usr/lib/jvm/default/bin"

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
export EDITOR='lvim'

# nodejs 本体镜像
export FNM_NODE_DIST_MIRROR='https://npmmirror.com/mirrors/node'

# # mcfly
# export MCFLY_FUZZY=2
# export MCFLY_RESULTS=25
