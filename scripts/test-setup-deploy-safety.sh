#!/usr/bin/env bash
# 回归测试：setup.sh --deploy 在 xdotter --force 覆盖既有普通文件之前必须先备份。
# 背景：--force 会直接替换目标处的真实文件（无提示、无备份），一次误部署即丢用户配置。
# 全部离线：HOME 指向临时目录，xd 用假实现；不运行真实部署。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  echo "FAIL: $*"
  exit 1
}

# 假 xdotter：--dry-run 打印与真实版本同构的计划行；--force 直接覆盖成 symlink。
make_fake_xd() {
  local dir="$1" mode="${2:-conflict}"
  mkdir -p "$dir"
  cat > "$dir/xd" <<FAKE
#!/usr/bin/env bash
set -euo pipefail
target="\$HOME/.config/x/a.toml"
case "\${1:-}" in
  deploy)
    if [ "\${2:-}" = "--dry-run" ]; then
      case "$mode" in
        conflict)
          echo "# Deploy plan (1 条目)"
          echo "! \$target -> \$PWD/a.toml [skip: 默认模式不替换已有对象 (普通文件)]"
          echo "[规划阻塞错误] dry-run 计划包含会跳过并计为失败的链接"
          # 真实 xdotter 在存在冲突时以非零退出；备份逻辑不能依赖退出码
          exit 1
          ;;
        garbage)
          echo "error: 无法读取配置"
          exit 1
          ;;
      esac
      exit 0
    fi
    rm -f "\$target"
    ln -s "\$PWD/a.toml" "\$target"
    echo "Deploy: 1 succeeded, 0 skipped, 0 failed (planned 1)"
    ;;
  --version|-V) echo "xd (fake)" ;;
  *) exit 0 ;;
esac
FAKE
  chmod +x "$dir/xd"
}

# ── 用例 1：冲突时先备份再覆盖 ──
case_backup_on_conflict() {
  local home="$TMP/c1/home" fakebin="$TMP/c1/bin" repo="$TMP/c1/repo"
  mkdir -p "$home/.config/x" "$repo"
  printf 'user-data\n' > "$home/.config/x/a.toml"
  printf 'repo-data\n' > "$repo/a.toml"
  make_fake_xd "$fakebin" conflict

  set +e
  HOME="$home" PATH="$fakebin:$PATH" bash -c 'source "$1/setup.sh"; ensure_xdotter() { :; }; _confirm_deploy_overwrite() { :; }; main --deploy' _ "$ROOT" >"$TMP/c1/out" 2>&1
  local rc=$?
  set -e
  [ "$rc" -eq 0 ] || fail "冲突部署应成功，实际 rc=$rc：$(cat "$TMP/c1/out")"
  [ -L "$home/.config/x/a.toml" ] || fail "目标未部署为 symlink"
  grep -rl 'user-data' "$home/.local/state" >/dev/null 2>&1 \
    || fail "既有文件被覆盖且没有备份：$(cat "$TMP/c1/out")"
}

# ── 用例 2：拿不到可解析计划时中止覆盖（fail-closed）──
case_unparseable_plan_aborts() {
  local home="$TMP/c2/home" fakebin="$TMP/c2/bin"
  mkdir -p "$home/.config/x"
  printf 'user-data\n' > "$home/.config/x/a.toml"
  make_fake_xd "$fakebin" garbage

  set +e
  HOME="$home" PATH="$fakebin:$PATH" bash -c 'source "$1/setup.sh"; ensure_xdotter() { :; }; _confirm_deploy_overwrite() { :; }; main --deploy' _ "$ROOT" >"$TMP/c2/out" 2>&1
  local rc=$?
  set -e
  [ "$rc" -ne 0 ] || fail "无法解析计划时应非零退出：$(cat "$TMP/c2/out")"
  [ ! -L "$home/.config/x/a.toml" ] || fail "无法解析计划时仍执行了覆盖"
  grep -q 'user-data' "$home/.config/x/a.toml" || fail "既有文件内容被改动"
}

case_no_tty() {
  local home="$TMP/c4/home" fakebin="$TMP/c4/bin"
  mkdir -p "$home/.config/x"
  printf 'user-data\n' > "$home/.config/x/a.toml"
  make_fake_xd "$fakebin" conflict
  if HOME="$home" PATH="$fakebin:$PATH" bash -c 'source "$1/setup.sh"; ensure_xdotter() { :; }; main --deploy' _ "$ROOT" </dev/null >"$TMP/c4/out" 2>&1; then
    fail "无TTY未确认覆盖应非零退出"
  fi
  [ ! -L "$home/.config/x/a.toml" ] || fail "无TTY仍覆盖"
  grep -q '无 TTY' "$TMP/c4/out" || fail "未报告缺少授权"
}

case_ci_explicit_approval() {
  local home="$TMP/c5/home" fakebin="$TMP/c5/bin"
  mkdir -p "$home/.config/x"
  printf 'user-data\n' > "$home/.config/x/a.toml"
  make_fake_xd "$fakebin" conflict
  set +e
  CI=1 DOTFILES_DEPLOY_ASSUME_YES=1 HOME="$home" PATH="$fakebin:$PATH" \
    bash -c 'source "$1/setup.sh"; ensure_xdotter() { :; }; main --deploy' _ "$ROOT" </dev/null >"$TMP/c5/out" 2>&1
  local rc=$?
  set -e
  [ "$rc" -eq 0 ] || fail "CI 显式授权应部署成功：$rc：$(cat "$TMP/c5/out")"
  [ -L "$home/.config/x/a.toml" ] || fail "CI 显式授权后未部署 symlink"
  grep -rl 'user-data' "$home/.local/state" >/dev/null 2>&1 \
    || fail "CI 显式授权不能绕过备份：$(cat "$TMP/c5/out")"
  grep -q 'CI 显式授权' "$TMP/c5/out" || fail "未报告 CI 授权来源"
}

case_backup_on_conflict
case_unparseable_plan_aborts
case_no_tty
case_ci_explicit_approval
echo "PASS: 已授权备份 / 无TTY保护 / CI 显式授权 / fail-closed"
