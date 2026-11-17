"""Offline mocked runner coverage for opt-in locked managers."""
import base64
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_installer.errors import AuthorizationRequired, InstallationError, StrategyError
from tool_installer.models import Environment, PlanItem, ToolReference, ToolSpec
from tool_installer.strategy import resolve_tool_strategy
from tool_installer.managers import default_registry
from tool_installer.managers.base import CheckResult


class LockedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.patch = mock.patch("pathlib.Path.home", return_value=self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calls = []
        self.fail = False
        self.runner = mock.Mock()
        self.runner.run.side_effect = self.run_command

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        gen = Path(kwargs["cwd"])
        if cmd[0] == "npm":
            package = gen / "node_modules/pkg"
            package.mkdir(parents=True)
            version = json.loads((gen / "package.json").read_text())["dependencies"]["pkg"]
            (package / "package.json").write_text(json.dumps({"name": "pkg", "version": version, "bin": {"pkg": "cli.js"}}))
            target = gen / "node_modules/pkg/cli.js"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not executed")
            target.chmod(0o755)
            link = gen / "node_modules/.bin/pkg"
            link.parent.mkdir()
            link.symlink_to(target)
        elif cmd[0] == "uv":
            metadata = gen / "lib/python3.14/site-packages/pkg-1.2.3.dist-info"
            metadata.mkdir(parents=True)
            (metadata / "METADATA").write_text("Name: pkg\nVersion: 1.2.3\n")
            (metadata / "entry_points.txt").write_text("[console_scripts]\npkg = pkg:main\n")
            target = gen / "bin/pkg"
            target.parent.mkdir(exist_ok=True)
            target.write_text("not executed")
            target.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 1 if self.fail else 0)

    def item(self, manager="npm-locked", version="1.2.3", **extra):
        path = self.root / "lock"
        if manager == "npm-locked":
            path.write_text(json.dumps({"lockfileVersion": 3, "packages": {
                "": {"dependencies": {"pkg": version}}, "node_modules/pkg": {
                    "version": version, "resolved": "https://registry.npmjs.org/pkg.tgz",
                    "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode()}}}))
        else:
            path.write_text("pkg==" + version + " --hash=sha256:" + "a" * 64)
        tool = ToolSpec(ToolReference("pkg@" + version, "pkg", version))
        env = Environment("linux", "x86_64")
        fields = dict(manager=manager, pkg="pkg", lock="lock")
        fields.update(extra)
        strategy = resolve_tool_strategy(tool, {"pkg": {"linux": fields}}, env, self.root)
        return PlanItem("test", tool, strategy, env)

    def test_install_check_and_idempotence(self):
        for manager in ("npm-locked", "python-locked"):
            with self.subTest(manager=manager):
                item = self.item(manager)
                instance = default_registry(runner=self.runner)[manager]
                instance.install(item)
                count = len(self.calls)
                self.assertEqual(instance.check(item), CheckResult.SATISFIED)
                instance.install(item)
                self.assertEqual(len(self.calls), count)
                (self.home / ".local/bin/pkg").unlink()
        npm = self.calls[0]
        self.assertEqual(npm[0], ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"])
        uv = self.calls[-1]
        self.assertIn("--require-hashes", uv[0])
        self.assertIn(":all:", uv[0])
        self.assertEqual(uv[1]["env"]["UV_PYTHON_DOWNLOADS"], "never")

    def test_foreign_targets_including_dangling_force(self):
        item = self.item(force=True)
        manager = default_registry(runner=self.runner)["npm-locked"]
        dest = self.home / ".local/bin/pkg"
        dest.parent.mkdir(parents=True)
        for kind in ("file", "dangling", "outside"):
            if kind == "file": dest.write_text("mine")
            else: dest.symlink_to(self.root / ("missing" if kind == "dangling" else "lock"))
            with self.assertRaises(AuthorizationRequired): manager.install(item)
            with self.assertRaises(AuthorizationRequired): manager.check(item)
            self.assertTrue(dest.is_symlink() or dest.read_text() == "mine")
            dest.unlink()
        self.assertEqual(self.calls, [])

    def test_failed_update_keeps_old_bin_and_cleans_new_generation(self):
        item = self.item()
        manager = default_registry(runner=self.runner)["npm-locked"]
        manager.install(item)
        dest = self.home / ".local/bin/pkg"
        old = dest.readlink()
        updated = self.item(version="1.2.4")
        self.fail = True
        with self.assertRaises(InstallationError): manager.install(updated)
        self.assertEqual(dest.readlink(), old)
        self.assertEqual(len(list(old.parents[3].glob("gen-*"))), 1)
        self.fail = False
        manager.install(updated)
        self.assertNotEqual(dest.readlink(), old)
        self.assertEqual(manager.check(updated), CheckResult.SATISFIED)

    def test_lock_changed_after_plan(self):
        item = self.item()
        (self.root / "lock").write_text("{}")
        with self.assertRaises(InstallationError): default_registry(runner=self.runner)["npm-locked"].install(item)
        self.assertFalse(self.calls)

    def test_receipt_tampering_fails_closed(self):
        item = self.item()
        manager = default_registry(runner=self.runner)["npm-locked"]
        manager.install(item)
        target = (self.home / ".local/bin/pkg").readlink()
        receipt = target.parents[2] / "receipt.json"
        receipt.write_text("{}")
        with self.assertRaises(AuthorizationRequired): manager.check(item)

    def test_plan_rejects_escape_and_policy_overrides(self):
        for lock in ("../lock", "/tmp/lock", "./lock", "a/../lock"):
            with self.assertRaises(StrategyError): self.item(lock=lock)
        for fields in ({"python": "3.99"}, {"registry": "https://elsewhere"}, {"version_probe": {"command": ["x"]}}, {"bin": "../x"}):
            with self.assertRaises(StrategyError): self.item(**fields)

    def test_saved_lock_and_platform_mismatch_fail_closed(self):
        item = self.item()
        manager = default_registry(runner=self.runner)["npm-locked"]
        manager.install(item)
        changed = replace(item, environment=Environment("macos", "aarch64"))
        with self.assertRaises(AuthorizationRequired): manager.check(changed)
        target = (self.home / ".local/bin/pkg").readlink()
        saved = target.parents[2] / "package-lock.json"
        saved.write_text("{}")
        with self.assertRaises(AuthorizationRequired): manager.install(item)

    def test_python_failure_cleans_without_publishing(self):
        item = self.item("python-locked")
        self.fail = True
        manager = default_registry(runner=self.runner)["python-locked"]
        with self.assertRaises(InstallationError): manager.install(item)
        self.assertFalse((self.home / ".local/bin/pkg").exists())
        self.assertFalse(list((self.home / ".local/share/tool-installer/locked/python-locked/pkg").iterdir()))

    def test_runtime_environment_drops_configuration(self):
        item = self.item()
        with mock.patch.dict("os.environ", {"NODE_OPTIONS": "--require evil", "NPM_CONFIG_IGNORE_SCRIPTS": "false", "UV_CONFIG_FILE": "/evil"}):
            default_registry(runner=self.runner)["npm-locked"].install(item)
        env = self.calls[0][1]["env"]
        for key in ("NODE_OPTIONS", "NPM_CONFIG_IGNORE_SCRIPTS", "UV_CONFIG_FILE"):
            self.assertNotIn(key, env)

    def test_transitive_bin_is_not_root_entry(self):
        for kind in ("npm-locked", "python-locked"):
            item = self.item(kind)
            def run(cmd, **kwargs):
                result = self.run_command(cmd, **kwargs)
                gen = Path(kwargs["cwd"])
                if cmd[0] == "npm":
                    package = gen / "node_modules/pkg/package.json"
                    package.write_text(json.dumps({"name": "pkg", "version": "1.2.3", "bin": {"other": "cli.js"}}))
                elif cmd[0] == "uv":
                    next(gen.glob("lib/python*/site-packages/*.dist-info/entry_points.txt")).write_text("[console_scripts]\nother = pkg:main\n")
                return result
            self.runner.run.side_effect = run
            with self.assertRaises(InstallationError): default_registry(runner=self.runner)[kind].install(item)
            self.assertFalse((self.home / ".local/bin/pkg").exists())

    def test_nonregular_and_oversized_lock_rejected(self):
        import os
        item = self.item()
        from tool_installer.managers.locked import read_lock
        (self.root / "lock").unlink()
        os.mkfifo(self.root / "lock")
        with self.assertRaises(StrategyError): read_lock(self.root, item.strategy.fields, "1.2.3", "npm-locked")
        (self.root / "lock").unlink()
        with (self.root / "lock").open("wb") as stream: stream.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaises(StrategyError): read_lock(self.root, item.strategy.fields, "1.2.3", "npm-locked")

    def test_python_root_dependency_console_script_collision(self):
        item = self.item("python-locked")
        def run(cmd, **kwargs):
            result = self.run_command(cmd, **kwargs)
            if cmd[0] == "uv":
                gen = Path(kwargs["cwd"])
                dep = gen / "lib/python3.14/site-packages/dep-1.0.dist-info"
                dep.mkdir()
                (dep / "METADATA").write_text("Name: dep\nVersion: 1.0\n")
                (dep / "entry_points.txt").write_text("[console_scripts]\npkg = dep:main\n")
                (gen / "bin/pkg").write_text("from dep import main\nmain()\n")
            return result
        self.runner.run.side_effect = run
        with self.assertRaises(InstallationError): default_registry(runner=self.runner)["python-locked"].install(item)
        self.assertFalse((self.home / ".local/bin/pkg").exists())

    def test_receipt_and_saved_lock_fifo_and_size_fail_closed(self):
        import os
        item = self.item()
        manager = default_registry(runner=self.runner)["npm-locked"]
        manager.install(item)
        generation = (self.home / ".local/bin/pkg").readlink().parents[2]
        for filename, limit in (("receipt.json", 65536), ("package-lock.json", 8 * 1024 * 1024)):
            path = generation / filename
            original = path.read_bytes()
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(AuthorizationRequired): manager.check(item)
            path.unlink()
            with path.open("wb") as stream: stream.truncate(limit + 1)
            with self.assertRaises(AuthorizationRequired): manager.check(item)
            path.write_bytes(original)

    def test_lock_symlink_escape(self):
        item = self.item()
        outside = self.home / "outside"
        outside.write_text((self.root / "lock").read_text())
        # A sibling outside the manifest directory cannot be accepted.
        nested = self.root / "manifest"
        nested.mkdir()
        (nested / "lock").symlink_to(outside)
        from tool_installer.managers.locked import read_lock
        with self.assertRaises(StrategyError): read_lock(nested, item.strategy.fields, "1.2.3", "npm-locked")


if __name__ == "__main__": unittest.main()
