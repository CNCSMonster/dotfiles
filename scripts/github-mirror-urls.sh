#!/usr/bin/env bash
# GitHub 下载镜像候选：单一事实来源是 manifest.toml 的 [_github-release].github_mirrors
# （CI 由 scripts/ci-disable-mirrors.sh 注释该行 → 无镜像 → 直连）。
# 用法:
#   github-mirror-urls.sh              输出镜像前缀列表（空格分隔，可能为空）
#   github-mirror-urls.sh <direct-url> 输出下载候选 URL，逐行：镜像在前、直连最后
# 显式设置 GITHUB_MIRRORS 环境变量可覆盖（含设为空以禁用）。
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -n "${GITHUB_MIRRORS+x}" ]; then
    mirrors="$GITHUB_MIRRORS"
else
    mirrors="$(sed -n 's/^github_mirrors = \(.*\)/\1/p' "$PROJECT_DIR/manifest.toml" \
        | head -1 | tr -d '[]"' | tr ',' ' ')"
fi

if [ "$#" -eq 0 ]; then
    echo "$mirrors"
    exit 0
fi

url="$1"
for m in $mirrors; do
    [ -n "$m" ] && echo "${m%/}/$url"
done
echo "$url"
