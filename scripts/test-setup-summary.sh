#!/usr/bin/env bash
# 完整流程只运行 mock，不接触安装、sudo 或本机部署。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$(bash -c '
source "$1/setup.sh"
preflight_sudo() { :; }
do_bootstrap() { echo "optional failure reported"; }
do_deploy() { :; }
do_install() { :; }
do_post() { :; }
check_repo_pollution() { :; }
main
' _ "$ROOT")"
[[ "$out" != *"全部安装完成"* ]] || exit 1
[[ "$out" == *"不代表全部工具安装成功"* ]] || exit 1
# 条件调用 main 会禁用函数内部 errexit，失败必须显式向上传播。
for mode in --deploy full; do
  bash -c '
source "$1/setup.sh"
ensure_xdotter() { return 42; }
preflight_sudo() { :; }
do_bootstrap() { :; }
do_install() { echo "FAIL: install must not run"; exit 99; }
do_post() { echo "FAIL: post must not run"; exit 99; }
check_repo_pollution() { :; }
if [ "$2" = full ]; then
  if main; then exit 98; else rc=$?; fi
else
  if main --deploy; then exit 98; else rc=$?; fi
fi
[ "$rc" -eq 1 ]
' _ "$ROOT" "$mode" >/dev/null
done
echo 'PASS: optional summary semantics / conditional main propagates deploy failure'
