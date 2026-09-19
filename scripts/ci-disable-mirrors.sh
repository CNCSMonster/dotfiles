#!/usr/bin/env bash
# 供可直连海外的 CI runner 使用：注释掉镜像站配置，让构建直连上游。
# 机制：deploy 是 symlink 仓库文件、tool-installer 读仓库 manifest，
# 所以在 setup 之前改仓库副本即可生效，安装器本身无需感知 CI。
# 幂等：重复执行只保持注释状态；国内部署不跑本脚本，镜像默认保留。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# GitHub release 下载直连，不走 ghfast 镜像
perl -pi -e 's/^github_mirrors/#github_mirrors/' manifest.toml
# crates.io 直连，不走 rsproxy（海外访问国内镜像偶发 504，曾挂 CI）
perl -pi -e 's/^replace-with = "rsproxy-sparse"/#replace-with = "rsproxy-sparse"  # disabled for CI/' langs/rust/cargo/config.toml

grep -q '^#github_mirrors' manifest.toml
grep -q '^#replace-with = "rsproxy-sparse"' langs/rust/cargo/config.toml
echo "✅ CI 镜像已禁用：manifest.toml github_mirrors / cargo rsproxy replace-with"
