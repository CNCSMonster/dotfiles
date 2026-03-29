########################################################
# 各种快捷功能函数
########################################################

# fzf jump
function fj() {
    # 如果有两个命令行参数，第一个参数将作为 `fd` 的输入，第二个参数将作为 `fzf` 的查询来源。

    # 检查命令行参数的数量
    if [ $# -eq 2 ]; then
        # 如果有两个参数，第一个作为 fd 的输入，第二个作为 fzf 的查询输入
        target=$(fd "$1" | fzf -q "$2")
    elif [ $# -eq 1 ]; then
        # 如果没有两个参数，使用第一个参数作为fzf查询输入
        target=$(fd . | fzf -q $1)
    else
        target=$(fd . | fzf)
    fi

    # 检查是否选择了目标目录
    if [ -n "$target" ]; then
        if [ -d "$target" ]; then
            cd "$target"
        else
            cd $(dirname $target)
        fi
    else
        echo "No target dir selected"
    fi
}

# ============================================================
# npm/pnpm 镜像源切换（淘宝镜像）
# ============================================================
# 用法 1: npm-cn install <package>  (临时使用)
# 用法 2: use-npm-mirror 后正常使用 npm (持续生效)
# 用法 3: use-npm-official 切换回官方源
# ============================================================

# 临时使用淘宝镜像运行 npm 命令
function npm-cn() {
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com npm "$@"
}

# 临时使用淘宝镜像运行 pnpm 命令
function pnpm-cn() {
    PNPM_CONFIG_REGISTRY=https://registry.npmmirror.com pnpm "$@"
}

# 切换到淘宝镜像模式（持续生效，直到 use-npm-official）
function use-npm-mirror() {
    export NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
    export PNPM_CONFIG_REGISTRY=https://registry.npmmirror.com
    echo "✅ 已切换到淘宝镜像模式"
}

# 切换回官方源
function use-npm-official() {
    unset NPM_CONFIG_REGISTRY
    unset PNPM_CONFIG_REGISTRY
    echo "✅ 已切换到官方源"
}

# 如果调用则载入 install-functions.sh, 获取用于安装各种软件的函数
function load_setup() {
    source "$HOME/.config/shells/common/install-functions.sh"
}

