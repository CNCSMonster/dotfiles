"""Real npm with audited synthetic tarballs, no network or lifecycle execution.

The test runner injects offline/cache policy, which is not production policy.
HTTPS locks are unchanged (not file: locks). Wrong SRI can yield ENOTCACHED:
this proves rejection, not a comparison against downloaded incorrect bytes.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_installer.errors import AuthorizationRequired, InstallationError
from tool_installer.managers import default_registry
from tool_installer.managers.base import CheckResult
from tool_installer.models import Environment, PlanItem, ToolReference, ToolSpec
from tool_installer.strategy import resolve_tool_strategy


class OfflineRunner:
    """Real subprocess execution; never synthesize installed files or results."""
    def __init__(self, test):
        self.test = test
        self.results = []

    def run(self, args, check=False, **kwargs):
        self.test.assertEqual(args, ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"])
        env = self.test.environment(Path(kwargs["cwd"]))
        for key in ("NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG"):
            env[key] = kwargs["env"][key]
        result = subprocess.run([self.test.npm, *args[1:], "--offline"],
                                cwd=kwargs["cwd"], env=env, check=check,
                                capture_output=True, text=True, timeout=45)
        self.results.append(result)
        return result


class LockedNpmIntegrationTests(unittest.TestCase):
    def setUp(self):
        npm, node = shutil.which("npm"), shutil.which("node")
        if not npm or not node:
            self.skipTest("real host npm and node required; downloading them is forbidden")
        tmp = tempfile.TemporaryDirectory(prefix="locked-npm-integration-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home, self.cache, self.temp = [self.root / n for n in ("home", "cache", "tmp")]
        self.home.mkdir()
        self.temp.mkdir()
        self.npm = str(Path(npm).resolve())
        self.path = os.pathsep.join(dict.fromkeys([str(Path(node).resolve().parent),
                                                  str(Path(self.npm).parent), os.defpath]))
        for kind in ("user", "global"):
            (self.root / (kind + ".npmrc")).write_text("")
        patch = mock.patch.dict(os.environ, self.environment(self.home), clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.name = "locked-npm-fixture"
        package = {"name": self.name, "version": "1.0.0", "bin": {self.name: "cli.js"}}
        self.contents = {"package/package.json": json.dumps(package).encode(),
                         "package/cli.js": b'#!/usr/bin/env node\nconsole.log("local fixture");\n'}
        archive_path = self.root / "fixture.tgz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for name, content in self.contents.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o755 if name.endswith("cli.js") else 0o644
                archive.addfile(info, io.BytesIO(content))
        # Exact allow-list audit of every member, including bytes; no extraction.
        with tarfile.open(archive_path, "r:gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(self.contents))
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                self.assertEqual(archive.extractfile(member).read(), self.contents[member.name])
        self.sri = "sha512-" + base64.b64encode(hashlib.sha512(archive_path.read_bytes()).digest()).decode()
        result = subprocess.run([self.npm, "cache", "add", str(archive_path), "--offline",
                                 "--ignore-scripts", "--no-audit", "--no-fund"],
                                cwd=self.root, env=self.environment(self.home),
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.runner = OfflineRunner(self)
        self.manager = default_registry(runner=self.runner)["npm-locked"]
        self.dest = self.home / ".local/bin" / self.name

    def environment(self, home):
        return {"PATH": self.path, "HOME": str(home), "TMPDIR": str(self.temp),
                "TMP": str(self.temp), "TEMP": str(self.temp), "LC_ALL": "C",
                "NPM_CONFIG_CACHE": str(self.cache), "NPM_CONFIG_OFFLINE": "true",
                "NPM_CONFIG_IGNORE_SCRIPTS": "true", "NPM_CONFIG_AUDIT": "false",
                "NPM_CONFIG_FUND": "false", "NPM_CONFIG_UPDATE_NOTIFIER": "false",
                "NPM_CONFIG_USERCONFIG": str(self.root / "user.npmrc"),
                "NPM_CONFIG_GLOBALCONFIG": str(self.root / "global.npmrc")}

    def item(self, integrity=None):
        lock = {"lockfileVersion": 3, "packages": {
            "": {"dependencies": {self.name: "1.0.0"}},
            "node_modules/" + self.name: {"version": "1.0.0",
                "resolved": "https://registry.invalid/locked-npm-fixture-1.0.0.tgz",
                "integrity": integrity or self.sri, "bin": {self.name: "cli.js"}}}}
        (self.root / "lock.json").write_text(json.dumps(lock))
        tool = ToolSpec(ToolReference(self.name + "@1.0.0", self.name, "1.0.0"))
        env = Environment("linux", "x86_64")
        fields = {"manager": "npm-locked", "pkg": self.name, "bin": self.name, "lock": "lock.json"}
        strategy = resolve_tool_strategy(tool, {self.name: {"linux": fields}}, env, self.root)
        return PlanItem("integration", tool, strategy, env)

    def test_real_npm_installs_https_lock_from_local_sri_cache(self):
        item = self.item()
        self.manager.install(item)
        self.assertEqual(len(self.runner.results), 1)
        self.assertEqual(self.runner.results[0].returncode, 0)
        self.assertTrue(self.dest.is_symlink())
        self.assertEqual(self.dest.read_bytes(), self.contents["package/cli.js"])
        self.assertEqual(self.manager.check(item), CheckResult.SATISFIED)
        self.manager.install(item)
        self.assertEqual(len(self.runner.results), 1)

    def test_wrong_sri_fails_and_keeps_previous_bin(self):
        self.manager.install(self.item())
        old_target = self.dest.readlink()
        old_bytes = self.dest.read_bytes()
        store = self.home / ".local/share/tool-installer/locked/npm-locked" / self.name
        generations = sorted(store.glob("gen-*"))
        wrong = "sha512-" + base64.b64encode(b"x" * 64).decode()
        with self.assertRaises(InstallationError):
            self.manager.install(self.item(wrong))
        self.assertNotEqual(self.runner.results[-1].returncode, 0)
        self.assertRegex(self.runner.results[-1].stderr, "ENOTCACHED|EINTEGRITY")
        self.assertEqual(self.dest.readlink(), old_target)
        self.assertEqual(self.dest.read_bytes(), old_bytes)
        self.assertEqual(sorted(store.glob("gen-*")), generations)

    def test_foreign_publication_target_is_not_overwritten(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_text("foreign user bin")
        with self.assertRaises(AuthorizationRequired):
            self.manager.install(self.item())
        self.assertEqual(self.dest.read_text(), "foreign user bin")
        self.assertEqual(self.runner.results, [])


if __name__ == "__main__":
    unittest.main()
