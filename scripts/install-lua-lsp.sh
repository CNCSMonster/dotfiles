#!/usr/bin/env bash
# Lua language server installer for tool-installer (script manager)
# Downloads the full GitHub release archive and keeps the directory structure,
# because lua-language-server's bin/lua-language-server is a launcher script
# that depends on main.lua and script/ at runtime.
set -uo pipefail

VERSION="${TOOL_INSTALLER_VERSION:-3.17.1}"
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        case "$ARCH" in
            x86_64)  ASSET="lua-language-server-${VERSION}-linux-x64.tar.gz" ;;
            aarch64) ASSET="lua-language-server-${VERSION}-linux-arm64.tar.gz" ;;
            *)
                echo "⚠️  不支持的架构: $ARCH"
                exit 0
                ;;
        esac
        ;;
    Darwin)
        case "$ARCH" in
            arm64)   ASSET="lua-language-server-${VERSION}-darwin-arm64.tar.gz" ;;
            x86_64)  ASSET="lua-language-server-${VERSION}-darwin-x64.tar.gz" ;;
            *)
                echo "⚠️  不支持的架构: $ARCH"
                exit 0
                ;;
        esac
        ;;
    *)
        echo "⚠️  不支持的操作系统: $OS"
        exit 0
        ;;
esac

INSTALL_DIR="$HOME/.local/share/lua-language-server"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/lua-language-server"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# 幂等检查：已存在且能正常返回版本则跳过
if [ -x "$BIN_PATH" ]; then
    if "$BIN_PATH" --version >/dev/null 2>&1; then
        echo "lua-language-server 已安装且可用，跳过"
        exit 0
    fi
    echo "检测到旧的 lua-language-server 不完整，重新安装..."
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "下载 lua-language-server ${VERSION} (${ASSET})..."

downloaded=false
for mirror in "https://ghfast.top/https://github.com/LuaLS/lua-language-server/releases/download/${VERSION}/${ASSET}" \
              "https://mirror.ghproxy.com/https://github.com/LuaLS/lua-language-server/releases/download/${VERSION}/${ASSET}" \
              "https://github.com/LuaLS/lua-language-server/releases/download/${VERSION}/${ASSET}"; do
    echo "尝试下载: $mirror"
    if wget --tries=2 --timeout=180 --connect-timeout=15 "$mirror" -O "$TMP_DIR/$ASSET" 2>/dev/null; then
        downloaded=true
        break
    fi
    echo "⚠️  该镜像失败，尝试下一个..."
done

if [ "$downloaded" != true ]; then
    echo "⚠️  lua-language-server 下载失败，跳过"
    exit 0
fi

# 清理旧安装，然后完整解压
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if ! tar -xzf "$TMP_DIR/$ASSET" -C "$INSTALL_DIR"; then
    echo "⚠️  lua-language-server 解压失败，跳过"
    exit 0
fi

# 创建包装脚本，指向实际 bin
cat > "$BIN_PATH" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/bin/lua-language-server" "\$@"
EOF
chmod +x "$BIN_PATH"

echo "✅ lua-language-server ${VERSION} 安装完成"
exit 0
