#!/usr/bin/env bash
# Offline caller regressions: isolated copies and mocked side effects.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/scripts/lib" "$TMP/bin" "$TMP/home"
cp "$ROOT/scripts/install-fonts.sh" "$ROOT/scripts/install-lua-lsp.sh" "$ROOT/scripts/layer2-post.sh" "$TMP/scripts/"
printf 'apt_run() { return 0; }\n' >"$TMP/scripts/lib/apt.sh"
cat >"$TMP/scripts/github-mirror-urls.sh" <<'MOCK'
#!/usr/bin/env bash
if [ "$MODE" = fail ]; then
    printf 'https://must-not-download.example/partial\n'
    echo 'mock parser failure' >&2
    exit 23
fi
printf '%s\n' "https://first.example/$1" "https://second.example/$1" "$1"
MOCK
cat >"$TMP/bin/wget" <<'MOCK'
#!/usr/bin/env bash
for arg in "$@"; do
    case "$arg" in https://*) printf '%s\n' "$arg" >>"$DOWNLOAD_LOG";; esac
done
# Success mode accepts only the second candidate; archives are mocked too.
if [ "$MODE" = download-success ]; then
    for arg in "$@"; do [[ "$arg" == https://second.example/* ]] && exit 0; done
fi
exit 1
MOCK
cat >"$TMP/bin/uname" <<'MOCK'
#!/usr/bin/env bash
case "$1" in -s) echo Linux;; -m) echo x86_64;; esac
MOCK
# Protect the font installer fixed /tmp archive from test cleanup.
cat >"$TMP/bin/rm" <<'MOCK'
#!/usr/bin/env bash
for arg in "$@"; do
    case "$arg" in /tmp/FiraCode-Nerd-Font-*) exit 0;; esac
done
exec /bin/rm "$@"
MOCK
for cmd in tar unzip fc-cache; do printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/bin/$cmd"; done
for cmd in fc-list fuser; do printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/bin/$cmd"; done
for cmd in sudo apt-get curl brew; do
    printf '#!/usr/bin/env bash\necho forbidden >>"$FORBIDDEN_LOG"\nexit 99\n' >"$TMP/bin/$cmd"
done
chmod +x "$TMP/bin/"* "$TMP/scripts/github-mirror-urls.sh"
export PATH="$TMP/bin:$PATH" HOME="$TMP/home" TMPDIR="$TMP"
export DOWNLOAD_LOG="$TMP/downloads" FORBIDDEN_LOG="$TMP/forbidden"
unset GITHUB_MIRRORS
fail() { echo "FAIL: $*" >&2; exit 1; }
for script in install-fonts.sh install-lua-lsp.sh layer2-post.sh; do
    : >"$DOWNLOAD_LOG"
    rc=0
    MODE=fail bash "$TMP/scripts/$script" >"$TMP/out" 2>"$TMP/err" || rc=$?
    [ "$rc" -eq 23 ] || fail "$script swallowed helper failure ($rc)"
    [ ! -s "$DOWNLOAD_LOG" ] || fail "$script downloaded partial output"
    [ -s "$TMP/err" ] || fail "$script lost diagnostic"
done
for script in install-fonts.sh install-lua-lsp.sh; do
    : >"$DOWNLOAD_LOG"
    MODE=success bash "$TMP/scripts/$script" >"$TMP/out" 2>"$TMP/err" || fail "$script changed download-failure warning policy"
    urls=()
    while IFS= read -r url; do urls+=("$url"); done <"$DOWNLOAD_LOG"
    [ "${#urls[@]}" -eq 3 ] || fail "$script lost candidates"
    direct="${urls[2]}"
    [ "${urls[0]}" = "https://first.example/$direct" ] || fail "$script changed first candidate"
    [ "${urls[1]}" = "https://second.example/$direct" ] || fail "$script changed second candidate"
    [ ! -s "$TMP/err" ] || fail "$script unexpected stderr"
    : >"$DOWNLOAD_LOG"
    MODE=download-success bash "$TMP/scripts/$script" >"$TMP/out" 2>"$TMP/err" || fail "$script success path failed"
    urls=()
    while IFS= read -r url; do urls+=("$url"); done <"$DOWNLOAD_LOG"
    [ "${#urls[@]}" -eq 2 ] || fail "$script did not stop after success"
    [ ! -s "$TMP/err" ] || fail "$script success path stderr"
done
[ ! -s "$FORBIDDEN_LOG" ] || fail 'attempted network/package operation'
echo 'PASS: 7 isolated offline caller checks'
