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
