#!/usr/bin/env bash
# 从 tool-installer/ 源码重建 vendor/tool-installer zipapp。
# 修改安装器源码后必须运行本脚本并提交产物：setup.sh 只认 vendor/ 下的 zipapp，
# 比对方式是字节比较，漏跑会导致改动不生效。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

cd "$ROOT"
find tool-installer -name __pycache__ -type d -prune -exec rm -rf {} +
python3 -m zipapp tool-installer \
    --compress \
    --python "/usr/bin/env python3" \
    --output vendor/tool-installer
chmod +x vendor/tool-installer

# 冒烟：产物可执行且 dry-run 计划非空
vendor/tool-installer install dev --dry-run | grep -q '^PLAN '
vendor/tool-installer --help >/dev/null

echo "✅ 已重建 vendor/tool-installer（$(wc -c < vendor/tool-installer) 字节）"
