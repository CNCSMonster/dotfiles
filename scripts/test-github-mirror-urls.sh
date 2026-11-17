#!/usr/bin/env bash
# Offline regression tests; only a temporary script/manifest/parser fixture is used.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/scripts" "$TMP/vendor"
cp "$ROOT/scripts/github-mirror-urls.sh" "$TMP/scripts/"
cp "$ROOT/vendor/tool-installer" "$TMP/vendor/"
unset GITHUB_MIRRORS
SCRIPT="$TMP/scripts/github-mirror-urls.sh"
URL='https://github.com/example/repo/releases/download/v1/a.tar.gz'
COUNT=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
check() {
    local name="$1" expected="$2"
    shift 2
    "$@" >"$TMP/out" 2>"$TMP/err" || fail "$name: unexpected failure"
    printf '%s\n' "$expected" >"$TMP/expected"
    cmp -s "$TMP/expected" "$TMP/out" || fail "$name: wrong output"
    [ ! -s "$TMP/err" ] || fail "$name: unexpected stderr"
    COUNT=$((COUNT + 1))
}
reject() {
    local name="$1"
    shift
    if "$@" >"$TMP/out" 2>"$TMP/err"; then fail "$name: expected failure"; fi
    [ ! -s "$TMP/out" ] || fail "$name: emitted candidates on failure"
    [ -s "$TMP/err" ] || fail "$name: missing diagnostic"
    COUNT=$((COUNT + 1))
}
printf '%s\n' '[_github-release]' 'github_mirrors = ["https://one.example", "https://two.example/"]' >"$TMP/manifest.toml"
check single-line "https://one.example/$URL
https://two.example/$URL
$URL" bash "$SCRIPT" "$URL"
# Same key in other tables must not leak; comments and literal strings are legal TOML.
printf '%s\n' '[other]' 'github_mirrors = ["https://wrong.example"]' '[_github-release]' '  github_mirrors = [' '    "https://one.example", # first' "    'https://two.example/'," '] # trailing comment' '[after]' 'github_mirrors = ["https://also-wrong.example"]' >"$TMP/manifest.toml"
check multiline "https://one.example/$URL
https://two.example/$URL
$URL" bash "$SCRIPT" "$URL"
check prefix-list 'https://one.example https://two.example' bash "$SCRIPT"
check override "https://override.example/$URL
https://last.example/$URL
$URL" env GITHUB_MIRRORS='https://override.example/ https://last.example' bash "$SCRIPT" "$URL"
check empty-override "$URL" env GITHUB_MIRRORS= bash "$SCRIPT" "$URL"
check empty-prefix '' env GITHUB_MIRRORS= bash "$SCRIPT"
for declaration in '# github_mirrors = ["https://disabled.example"]' 'github_mirrors = []'; do
    printf '%s\n' '[_github-release]' "$declaration" >"$TMP/manifest.toml"
    check disabled "$URL" bash "$SCRIPT" "$URL"
done
printf '%s\n' '[other]' 'github_mirrors = ["https://wrong.example"]' >"$TMP/manifest.toml"
check missing-section "$URL" bash "$SCRIPT" "$URL"
printf '%s\n' '[_github-release]' 'github_mirrors = ["https://one.example",' >"$TMP/manifest.toml"
reject invalid-toml bash "$SCRIPT" "$URL"
reject invalid-toml-prefix bash "$SCRIPT"
check override-bypasses-invalid "$URL" env GITHUB_MIRRORS= bash "$SCRIPT" "$URL"
for declaration in 'github_mirrors = "https://one.example"' 'github_mirrors = ["https://one.example", 42]' 'github_mirrors = [""]' 'github_mirrors = ["https://one.example bad"]'; do
    printf '%s\n' '[_github-release]' "$declaration" >"$TMP/manifest.toml"
    reject invalid-mirror bash "$SCRIPT" "$URL"
done
# Missing files also fail closed, without falling back to a direct candidate.
rm -- "$TMP/manifest.toml"
reject missing-manifest bash "$SCRIPT" "$URL"
printf 'PASS: %s isolated offline checks\n' "$COUNT"
