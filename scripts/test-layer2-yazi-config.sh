#!/usr/bin/env bash
# 隔离回归：Yazi 配置目录缺失时，layer2-post 应先创建目录再运行 ya pkg install。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home/.config" "$TMP/bin"
cat > "$TMP/bin/ya" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "pkg" ] && [ "$2" = "install" ] || exit 9
printf 'ya called in %s\n' "$PWD" >> "$YA_LOG"
exit 0
EOF
chmod +x "$TMP/bin/ya"
export HOME="$TMP/home"
export PATH="$TMP/bin:$PATH"
export YA_LOG="$TMP/ya.log"
export GITHUB_MIRRORS=""
# 从真实脚本中提取函数，不执行整个 layer2 安装流程。
source <(sed -n '/^install_yazi_plugins() {/,/^}/p' "$ROOT/scripts/layer2-post.sh")
install_yazi_plugins
[ -d "$HOME/.config/yazi" ] || { echo "FAIL: yazi config dir not created"; exit 1; }
grep -q "ya called in $HOME/.config/yazi" "$YA_LOG" || { echo "FAIL: ya pkg install not invoked in config dir"; exit 1; }
echo "PASS: missing Yazi config dir is created before plugin install"
