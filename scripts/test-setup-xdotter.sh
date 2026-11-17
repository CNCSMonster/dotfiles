#!/usr/bin/env bash
# 运行真实 parser/plan/CLI，执行器被 mock；绝不下载、安装或部署。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "vendor/tool-installer"))
import tool_installer.cli as cli
from tool_installer.managers.base import CheckResult
from tool_installer.managers.github_release import GithubReleaseManager

text = (root / "setup.sh").read_text()
code = text.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
with tempfile.TemporaryDirectory() as tmp:
    os.environ['HOME'] = tmp
    sys.argv = ['-', str(root)]
    seen = []
    def execute(plan, registry):
        assert len(plan.items) == 1
        item = plan.items[0]
        assert item.tool.reference.name == 'xdotter'
        assert item.tool.reference.version != 'latest'
        assert len(item.strategy.fields['sha256']) == 64
        assert not item.tool.allow_fail
        seen.append(item)
    def run():
        try:
            exec(compile(code, 'ensure_xdotter', 'exec'), {})
        except SystemExit as exc:
            return exc.code
    with patch.object(cli, 'execute_plan', execute):
        assert run() == 0
        assert len(seen) == 1
        target = Path(tmp) / '.local/bin/xd'
        target.parent.mkdir(parents=True)
        target.write_text('user-binary')
        with patch.object(GithubReleaseManager, 'check', return_value=CheckResult.NOT_SATISFIED):
            assert run() != 0
        assert target.read_text() == 'user-binary'
        assert len(seen) == 1
        with patch.object(GithubReleaseManager, 'check', return_value=CheckResult.SATISFIED):
            assert run() == 0
        assert len(seen) == 2
print('PASS: pinned single-tool CLI plan / existing binary fail-closed / matching binary')
PY
