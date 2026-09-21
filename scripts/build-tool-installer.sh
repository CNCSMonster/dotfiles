#!/usr/bin/env bash
# 从 tool-installer/ 源码重建 vendor/tool-installer zipapp。
# 修改安装器源码后必须运行本脚本并提交产物：setup.sh 只认 vendor/ 下的 zipapp，
# 比对方式是字节比较，漏跑会导致改动不生效。
# 可选参数：输出路径（默认 vendor/tool-installer），同步守卫用它构建到临时文件。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
OUT="${1:-$ROOT/vendor/tool-installer}"

cd "$ROOT"
find tool-installer -name __pycache__ -type d -prune -exec rm -rf {} +

# zipapp 只装运行时。tests/ 是开发期产物，整目录打包会让每次改测试都触发
# vendor 重建、并让 vendor-sync 守卫在"源码没动"的情况下报差异。
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R tool-installer/tool_installer "$stage/tool_installer"
cp tool-installer/__main__.py "$stage/__main__.py"
python3 -m zipapp "$stage" \
    --compress \
    --python "/usr/bin/env python3" \
    --output "$OUT"
chmod +x "$OUT"

# 冒烟：产物可执行且 dry-run 计划非空
"$OUT" install dev --dry-run | grep -q '^PLAN '
"$OUT" --help >/dev/null

echo "✅ 已重建 $(basename "$OUT") 到 $OUT（$(wc -c < "$OUT") 字节）"
