#!/bin/bash
# Docker 构建验证脚本 - 检查所有工具是否正确安装
# 在容器内运行: docker run --rm dotfiles:test /root/dotfiles/scripts/verify-docker-build.sh

# 注意：不使用 set -eo pipefail，因为需要继续执行所有检查并汇总结果
set +e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_cmd() {
    local cmd=$1
    local desc=${2:-$1}
    if command -v "$cmd" &> /dev/null; then
        echo -e "${GREEN}[PASS]${NC} $desc: $(command -v "$cmd")"
        ((PASS++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $desc: 未找到"
        ((FAIL++))
        return 0  # 返回 0 避免脚本提前退出
    fi
}

check_version() {
    local cmd=$1
    local desc=${2:-$1}
    if command -v "$cmd" &> /dev/null; then
        local version=$("$cmd" --version 2>&1 | head -n1 || echo "版本未知")
        echo -e "${GREEN}[PASS]${NC} $desc: $version"
        ((PASS++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $desc: 未找到"
        ((FAIL++))
        return 0  # 返回 0 避免脚本提前退出
    fi
}

check_symlink() {
    local link=$1
    local desc=${2:-$1}
    if [ -L "$link" ]; then
        local target=$(readlink -f "$link")
        echo -e "${GREEN}[PASS]${NC} $desc -> $target"
        ((PASS++))
        return 0
    elif [ -e "$link" ]; then
        echo -e "${YELLOW}[WARN]${NC} $desc: 存在但非符号链接"
        ((WARN++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $desc: 不存在"
        ((FAIL++))
        return 0  # 返回 0 避免脚本提前退出
    fi
}

check_dir() {
    local dir=$1
    local desc=${2:-$1}
    if [ -d "$dir" ]; then
        echo -e "${GREEN}[PASS]${NC} $desc: 目录存在"
        ((PASS++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $desc: 目录不存在"
        ((FAIL++))
        return 0  # 返回 0 避免脚本提前退出
    fi
}

check_file() {
    local file=$1
    local desc=${2:-$file}
    if [ -f "$file" ]; then
        echo -e "${GREEN}[PASS]${NC} $desc: 文件存在"
        ((PASS++))
        return 0
    else
        echo -e "${RED}[FAIL]${NC} $desc: 文件不存在"
        ((FAIL++))
        return 0  # 返回 0 避免脚本提前退出
    fi
}

# 加载环境变量
if [ -f "$HOME/.config/shells/common/env.sh" ]; then
    source "$HOME/.config/shells/common/env.sh"
fi

echo "========================================"
echo "  Docker 构建验证"
echo "  $(date)"
echo "========================================"
echo

echo "=== 1. 系统工具 ==="
check_version gcc
check_version g++
check_version make
check_version cmake
check_version ninja "ninja-build"
check_version git
check_version curl
check_version wget
check_version fzf
check_version rg "ripgrep"
check_version zsh
check_version python3
echo

echo "=== 2. Rust 工具链 ==="
check_version rustc
check_version cargo
check_cmd rustfmt
check_cmd clippy-driver "clippy"
check_cmd rust-analyzer
echo

echo "=== 3. Rust 工具 (cargo binstall) ==="
check_version mise
check_version bat
check_version eza
check_version starship
check_cmd zoxide
check_cmd fd
check_version yazi
check_cmd mcfly
check_cmd navi
check_cmd tokei
echo

echo "=== 4. LLVM 工具链 ==="
if [ -d "/usr/lib/llvm" ]; then
    check_cmd /usr/lib/llvm/bin/clang "clang (via llvm)"
    check_cmd /usr/lib/llvm/bin/clang++ "clang++ (via llvm)"
else
    check_version clang
    check_version clang++
fi
echo

echo "=== 5. Neovim ==="
check_version nvim "Neovim"
echo

echo "=== 6. mise 运行时 ==="
# mise 需要先激活
if command -v mise &> /dev/null; then
    eval "$(mise activate bash 2>/dev/null)" || true
fi
check_version go
check_version node
check_version pnpm
check_version zig || echo -e "${YELLOW}[INFO]${NC} zig 可能是 latest 版本，需要网络下载"
echo

echo "=== 7. 符号链接验证 ==="
check_symlink "$HOME/.zshrc" "~/.zshrc"
check_dir "$HOME/.config/shells" "~/.config/shells"
check_dir "$HOME/.config/shells/common" "~/.config/shells/common"
check_symlink "$HOME/.config/mise" "~/.config/mise"
check_dir "$HOME/.config/yazi" "~/.config/yazi"
check_dir "$HOME/.config/git" "~/.config/git"
echo

echo "=== 8. 配置完整性 ==="
check_file "$HOME/.config/git/config" "~/.config/git/config"
check_file "$HOME/.cargo/config.toml" "~/.cargo/config.toml"
check_file "$HOME/.config/starship.toml" "starship 配置"
echo

echo "=== 9. 额外工具验证 ==="
# setup.sh 安装但之前未检查的工具
check_cmd cargo-fuzz "cargo-fuzz"
check_cmd uv "uv"
echo

echo "=== 10. 功能测试 ==="
# GCC 编译测试
echo -n "GCC 编译测试: "
if echo 'int main() { return 0; }' > /tmp/test.c && gcc /tmp/test.c -o /tmp/test_gcc && /tmp/test_gcc; then
    echo -e "${GREEN}[PASS]${NC}"
    ((PASS++))
else
    echo -e "${RED}[FAIL]${NC}"
    ((FAIL++))
fi

# Clang 编译测试
echo -n "Clang 编译测试: "
CLANG_CMD="clang"
[ -x "/usr/lib/llvm/bin/clang" ] && CLANG_CMD="/usr/lib/llvm/bin/clang"
if $CLANG_CMD /tmp/test.c -o /tmp/test_clang 2>/dev/null && /tmp/test_clang; then
    echo -e "${GREEN}[PASS]${NC}"
    ((PASS++))
else
    echo -e "${RED}[FAIL]${NC}"
    ((FAIL++))
fi

# Rust 编译测试
echo -n "Rust 编译测试: "
if echo 'fn main() {}' > /tmp/test.rs && rustc /tmp/test.rs -o /tmp/test_rust 2>/dev/null && /tmp/test_rust; then
    echo -e "${GREEN}[PASS]${NC}"
    ((PASS++))
else
    echo -e "${RED}[FAIL]${NC}"
    ((FAIL++))
fi

# 清理
rm -f /tmp/test.c /tmp/test.rs /tmp/test_gcc /tmp/test_clang /tmp/test_rust
echo

echo "========================================"
echo "  验证结果汇总"
echo "========================================"
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${YELLOW}警告: $WARN${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
echo "========================================"

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}验证未完全通过，存在 $FAIL 个失败项${NC}"
    exit 1
else
    echo -e "${GREEN}验证通过!${NC}"
    exit 0
fi
