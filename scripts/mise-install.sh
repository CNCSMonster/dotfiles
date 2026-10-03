#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v mise &>/dev/null; then
  echo "❌ mise 未安装，请先安装 mise"
  exit 1
fi

export MISE_YES=1
mise trust --silent "$REPO_DIR/mise/config.toml" 2>/dev/null || true
mise install

# mise 以“版本目录存在”判定已安装：下载中断会留下空目录并被永久跳过，
# 表现为 `mise install` 报 all tools are installed 但 `mise which <bin>` 找不到二进制。
# 这里检查所有被配置引用的版本目录非空，空目录/未安装视为失败。
python3 - <<'PY'
import json, os, subprocess, sys

proc = subprocess.run(["mise", "ls", "--json"], capture_output=True, text=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)

bad = []
checked = 0
for tool, versions in json.loads(proc.stdout or "{}").items():
    for v in versions:
        if not v.get("source"):
            continue  # 无配置引用的孤立安装交给 mise prune
        checked += 1
        label = f'{tool}@{v.get("version")}'
        path = v.get("install_path") or ""
        if not v.get("installed"):
            bad.append(f"{label} 未安装")
        elif not os.path.isdir(path) or not os.listdir(path):
            bad.append(f"{label} 安装目录为空: {path}")

if bad:
    print("❌ mise 工具校验失败（删除对应空目录后重跑 ./scripts/mise-install.sh）:", file=sys.stderr)
    for item in bad:
        print(f"   {item}", file=sys.stderr)
    sys.exit(1)
print(f"✅ mise 工具校验通过（{checked} 个）")
PY
