#!/usr/bin/env bash
# Offline regression tests: no user startup files, network, sudo or installation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='dotfiles-shell-test-') as tmp:
    base = Path(tmp)
    bin = base / 'bin'
    home = base / 'home'
    bin.mkdir()
    home.mkdir()
    env = {'PATH': str(bin), 'HOME': str(home), 'LC_ALL': 'C'}
    def mock(name, body):
        path = bin / name
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)
    def run(code, extra=None, shell=None):
        return subprocess.run((shell or ['/bin/bash', '--noprofile', '--norc']) + ['-c', code],
                              env=dict(env, **(extra or {})), text=True, capture_output=True)
    def assert_ok(result):
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    # Only load function declarations; never source the user's complete shell environment.
    fn = (root / 'shells/common/fn.sh').read_text().split('# npm/pnpm')[0]
    mock('dirname', 'exec /usr/bin/dirname "$@"')
    mock('fd', 'printf "%s\n" "$SELECTED"')
    mock('fzf', '''if [[ "$EXPECT_QUERY" != NONE ]]; then
    [[ $# == 2 && "$1" == -q && "$2" == "$EXPECT_QUERY" ]] || exit 42
else
    [[ $# == 0 ]] || exit 43
fi
printf '%s\n' "$SELECTED"''')
    dest = home / 'space dir'
    dest.mkdir()
    dash = home / '-dash dir'
    dash.mkdir()
    zsh = shutil.which('zsh')
    assert zsh, 'zsh is required for the fj compatibility regression'
    shells = [('/bin/bash', ['/bin/bash', '--noprofile', '--norc']), (zsh, [zsh, '-f'])]
    for name, shell in shells:
        for args, query, selected, expected in [
            ("'space query *'", 'space query *', str(dest / 'file name'), str(dest)),
            ("'fd pattern' 'two words'", 'two words', str(dest), str(dest)),
            ('', 'NONE', str(dest), str(dest)),
            ('', 'NONE', '', str(home)),
            ('', 'NONE', '-dash dir', str(dash)),
            ('', 'NONE', '-dash dir/file name', str(dash))]:
            result = run(fn + f'\ncd "{home}"; target=sentinel; fj {args}; '
                         f'[[ "$PWD" == "{expected}" && "$target" == sentinel ]]',
                         {'SELECTED': selected, 'EXPECT_QUERY': query}, shell)
            assert_ok(result)
        print(f'PASS: fj spaces/cancellation/dash paths/local target under {name} (6 cases)')
    # Darwin and all installer processes are mocks; PATH has no real brew/curl/sudo.
    mock('uname', 'echo "${TEST_OS:-Darwin}"')
    mock('curl', '''case "$MODE" in
 download-fail) exit 22 ;;
 bootstrap-fail) echo 'exit 23' ;;
 *) echo 'exit 0' ;;
esac''')
    install = root / 'scripts/install-system-packages.sh'
    for mode, message in [('download-fail', '下载失败'), ('bootstrap-fail', 'Homebrew 安装失败'),
                          ('bootstrap-no-brew', '基础包安装失败')]:
        result = run(f'/bin/bash "{install}"', {'MODE': mode})
        assert result.returncode != 0 and message in result.stderr, result
    mock('brew', '[[ "$MODE" != package-fail ]]')
    result = run(f'/bin/bash "{install}"', {'MODE': 'package-fail'})
    assert result.returncode != 0 and '基础包安装失败' in result.stderr, result
    assert_ok(run(f'/bin/bash "{install}"', {'MODE': 'success'}))
    assert_ok(run(f'/bin/bash "{install}"', {'MODE': 'success', 'TEST_OS': 'Linux'}))
    print('PASS: Homebrew download/bootstrap/missing brew/package failures and success (6 cases)')
    verify = (root / 'scripts/verify-docker-build.sh').read_text()
    helpers = verify.split('# 加载环境变量')[0]
    mock('healthy', 'echo "healthy 1.0"; echo second-line')
    mock('broken', 'echo "loader failure" >&2; exit 37')
    mock('go', '[[ "$1" == version ]] || exit 64; echo "go version test"')
    mock('zig', '[[ "$1" == version ]] || exit 64; echo "0.test"')
    for cmd, args, passed, failed, log in [
        ('healthy', '', 1, 0, 'healthy 1.0'),
        ('broken', '', 0, 1, 'exit 37'),
        ('missing', '', 0, 1, '未找到'),
        ('go', 'go version', 1, 0, 'go version test'),
        ('zig', 'zig version', 1, 0, '0.test')]:
        result = run(helpers + f'\ncheck_version {cmd} {args}\n[[ "$PASS" == {passed} && "$FAIL" == {failed} ]]')
        assert_ok(result)
        assert log in result.stdout, result
        if failed:
            assert '[PASS]' not in result.stdout, result
    assert 'check_version go "go" version' in verify
    assert 'check_version zig "zig" version' in verify
    result = run(helpers + '\ncheck_runs broken; [[ "$PASS" == 0 && "$FAIL" == 1 ]]')
    assert_ok(result)
    print('PASS: version success/failure/missing/go/zig/check_runs (6 cases)')
print('PASS: all 24 offline shell regression cases')
PY
