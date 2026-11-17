#!/usr/bin/env bash
# Offline regression: only extracted pin code and mock manager run, never user rc.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 - "$root" <<'PY'
import os, pathlib, re, subprocess, sys, tempfile
root = pathlib.Path(sys.argv[1])
config = (root / 'shells/zsh/config.zsh').read_text()
pins = re.findall(r'^_dotfiles_zcomet_plugin (?:load|fpath) (\S+)', config, re.M)
assert len(pins) == 10
assert all(re.fullmatch(r'[0-9a-f]{40}', p.split('@')[1]) for p in pins)
assert not re.search(r'^\s*(?:zcomet (?:self-update|update)|.*git clone|rm -rf)', config, re.M)
guard = config.split('# BEGIN ZCOMET PIN GUARD\n')[1].split('if ! _dotfiles_zcomet_load_manager;')[0]
with tempfile.TemporaryDirectory(prefix='zcomet-pins-') as tmp:
    home = pathlib.Path(tmp)
    manager = home / 'config/.zcomet'
    manager.mkdir(parents=True)
    (manager / '.git').mkdir()
    (manager / 'zcomet.zsh').write_text('zcomet() { print -r -- "$*" >> "$HOME/calls"; }; true\n')
    for p in pins:
        (home / '.zcomet/repos' / p.split('@')[0] / '.git').mkdir(parents=True)
    bindir = home / 'bin'; bindir.mkdir()
    (bindir / 'git').write_text('#!/bin/sh\ncase "$3" in rev-parse) printf "%s\n" "$MOCK_SHA";; status) printf "%s" "$MOCK_DIRTY";; config) printf "https://github.com/%s.git\n" "$MOCK_REPO";; *) exit 93;; esac\n')
    (bindir / 'git').chmod(0o755)
    env = dict(os.environ, HOME=tmp, ZDOTDIR=tmp, ZSH_CONFIG_HOME=str(home/'config'), PATH=str(bindir)+':/usr/bin:/bin', MOCK_DIRTY='', MOCK_REPO='agkozak/zcomet')
    def run(code, sha):
        return subprocess.run(['zsh', '-dfc', guard+'\n'+code], env=dict(env, MOCK_SHA=sha), capture_output=True, text=True, check=True)
    sha = '3dfe6f837479c6731e74400a233739500ec6d648'
    run('_dotfiles_zcomet_load_manager || exit 1', sha)
    assert not (home/'calls').exists()
    run('if _dotfiles_zcomet_load_manager; then exit 1; fi', '0'*40)
    for p in pins:
        repo, sha = p.split('@')
        env['MOCK_REPO'] = repo
        run('zcomet() { print -r -- "$*" >> "$HOME/calls"; }; _dotfiles_zcomet_plugin load '+p+' || exit 1', sha)
        assert (home/'calls').read_text().splitlines()[-1] == 'load '+str(home/'.zcomet/repos'/repo)
    env['MOCK_REPO'] = pins[0].split('@')[0]
    before = (home/'calls').read_text()
    out = run('zcomet() { exit 94; }; if _dotfiles_zcomet_plugin load '+pins[0]+'; then exit 1; fi', '0'*40)
    assert '警告' in out.stderr
    assert (home/'calls').read_text() == before
    env['MOCK_DIRTY'] = ' M plugin.zsh'
    run('zcomet() { exit 94; }; if _dotfiles_zcomet_plugin load '+pins[0]+'; then exit 1; fi', pins[0].split('@')[1])
    env['MOCK_DIRTY'] = ''
    (home/'.zcomet/repos'/pins[0].split('@')[0]/'ignored.zwc').touch()
    run('zcomet() { return 0; }; _dotfiles_zcomet_plugin load '+pins[0]+' || exit 1', pins[0].split('@')[1])
    env['MOCK_REPO'] = 'untrusted/repo'
    run('zcomet() { exit 94; }; if _dotfiles_zcomet_plugin load '+pins[0]+'; then exit 1; fi', pins[0].split('@')[1])
    run('zcomet() { exit 94; }; if _dotfiles_zcomet_plugin load missing/repo@'+('a'*40)+'; then exit 1; fi', 'a'*40)
    assert not (home/'.zcomet/repos/missing').exists()
    print('PASS: 10 full pins; manager pin; local-only checkout; mismatch warning; no startup update/clone/delete')
PY
zsh -n "$root/shells/zsh/config.zsh"
