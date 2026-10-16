#!/usr/bin/env bash
# check-git-conflict 回归测试。
#
# 背景：修复前的实现用未锚定的子串模式匹配整个 staged diff，任何含
# 「连续 7 个及以上等号」的行（例如 manifest.toml 里的分隔线）或行内
# 标记字样都会被误判为冲突标志。本测试锁定修复后的行为：
#   - 普通内容 / 分隔线 / 行内字样 → 放行
#   - 行首的真实合并冲突标记 → 拦截
#
# 说明：测试用的标记字样在运行时拼装（repeat_char），避免本文件自身
# 被修复前的旧检查器误拦，使测试提交能先于修复落地。
#
# 用法：bash scripts/test-check-git-conflict.sh

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKER="$REPO_ROOT/shells/scripts/check-git-conflict"

if [ ! -x "$CHECKER" ]; then
    echo "找不到可执行文件：$CHECKER" >&2
    exit 2
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

PASS=0
FAIL=0

# 输出 $1 重复 $2 次组成的字符串（运行时拼装，源码不含字面标记）。
repeat_char() {
    local char="$1" count="$2" out="" i
    for ((i = 0; i < count; i++)); do
        out+="$char"
    done
    printf '%s' "$out"
}

# 新建一个仅用于本用例的临时 git 仓库。
new_case_repo() {
    local dir
    dir="$(mktemp -d "$TMP_ROOT/case.XXXXXX")"
    git -C "$dir" init -q
    printf '%s' "$dir"
}

# 在仓库 $1 中运行被测脚本，输出 stdout+stderr。
run_checker() {
    (cd "$1" && "$CHECKER" 2>&1)
}

# 断言：应放行（退出码 0）。
expect_pass() {
    local desc="$1" repo="$2" out rc
    out="$(run_checker "$repo")"
    rc=$?
    if [ "$rc" -eq 0 ]; then
        echo "✅ PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL: $desc（应放行，实际退出码 $rc）"
        printf '%s\n' "$out" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
}

# 断言：应拦截（退出码非 0）且输出点名文件 $3。
expect_block() {
    local desc="$1" repo="$2" name="$3" out rc
    out="$(run_checker "$repo")"
    rc=$?
    if [ "$rc" -ne 0 ] && [[ "$out" == *"$name"* ]]; then
        echo "✅ PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL: $desc（应拦截并点名 $name，实际退出码 $rc）"
        printf '%s\n' "$out" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
}

echo "== 用例 1：连续等号分隔线（回归） =="
repo="$(new_case_repo)"
printf 'note\n# %s\n' "$(repeat_char '=' 60)" > "$repo/separator.txt"
git -C "$repo" add separator.txt
expect_pass "分隔线不误报" "$repo"

echo "== 用例 2：真实合并冲突标记 =="
repo="$(new_case_repo)"
{
    printf '%s HEAD\n' "$(repeat_char '<' 7)"
    printf 'ours\n'
    printf '%s\n' "$(repeat_char '=' 7)"
    printf 'theirs\n'
    printf '%s main\n' "$(repeat_char '>' 7)"
} > "$repo/conflict.txt"
git -C "$repo" add conflict.txt
expect_block "冲突标记被拦截" "$repo" "conflict.txt"

echo "== 用例 3：行中标记字样（回归） =="
repo="$(new_case_repo)"
printf 'a %s b\n' "$(repeat_char '=' 7)" > "$repo/inline.txt"
git -C "$repo" add inline.txt
expect_pass "行中字样不误报" "$repo"

echo "== 用例 4：普通文件 =="
repo="$(new_case_repo)"
printf 'hello\nworld\n' > "$repo/normal.txt"
git -C "$repo" add normal.txt
expect_pass "普通文件放行" "$repo"

echo
echo "结果：通过 $PASS，失败 $FAIL"
[ "$FAIL" -eq 0 ]
