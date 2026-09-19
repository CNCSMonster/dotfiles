#!/usr/bin/env bash
# 守卫：vendor/tool-installer 必须与 tool-installer/ 源码内容一致。
# zip 条目时间戳随 checkout 变化，逐字节比较不可行，故比较每个条目的文件名与 CRC-32。
# CI（tool-installer-verify.yml 的 Vendor zipapp in sync job）与本地提交前都应运行。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
"$SCRIPT_DIR/build-tool-installer.sh" "$tmp" >/dev/null

python3 - "$ROOT/vendor/tool-installer" "$tmp" <<'EOF'
import sys
import zipfile


def signature(path):
    with zipfile.ZipFile(path) as zf:
        return {info.filename: info.CRC for info in zf.infolist()}


committed, rebuilt = (signature(p) for p in sys.argv[1:3])
if committed == rebuilt:
    print("✅ vendor/tool-installer 与源码一致")
    sys.exit(0)

diff = sorted(k for k in set(committed) | set(rebuilt)
              if committed.get(k) != rebuilt.get(k))
print("❌ vendor/tool-installer 与源码不一致，请运行 ./scripts/build-tool-installer.sh 并一并提交产物",
      file=sys.stderr)
for name in diff:
    print(f"   差异条目: {name}", file=sys.stderr)
sys.exit(1)
EOF
