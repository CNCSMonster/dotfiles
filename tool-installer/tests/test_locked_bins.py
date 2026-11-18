"""Offline multi-bin coverage for opt-in locked managers.

All installs are synthesized by a mocked runner inside a temporary HOME; no
network, no real package manager, no user HOME writes, no entry-point execution.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_installer.errors import AuthorizationRequired, InstallationError, StrategyError
from tool_installer.managers import default_registry
from tool_installer.managers.base import CheckResult
from tool_installer.managers.locked import declared_bins
from tool_installer.models import Environment, PlanItem, ToolReference, ToolSpec
from tool_installer.strategy import resolve_tool_strategy

BINS = ("alpha", "beta")


class LockedBinsTests(unittest.TestCase):
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
        self.fail_command = False
        # Which bins the synthetic root declares. Defaults to both.
        self.declared = set(BINS)
        self.runner = mock.Mock()
        self.runner.run.side_effect = self.run_command

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        gen = Path(kwargs["cwd"])
        if cmd[0] == "uv" and cmd[2] == "python":
            return subprocess.CompletedProcess(cmd, 0, stdout="[]")
        if cmd[0] == "npm":
            package = gen / "node_modules/pkg"
            package.mkdir(parents=True, exist_ok=True)
            version = json.loads((gen / "package.json").read_text())["dependencies"]["pkg"]
            (package / "package.json").write_text(json.dumps({
                "name": "pkg", "version": version,
                "bin": {name: name + ".js" for name in self.declared}}))
            for name in BINS:
                target = package / (name + ".js")
                target.write_text("not executed")
                target.chmod(0o755)
                link = gen / "node_modules/.bin" / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target)
        elif cmd[0] == "uv" and cmd[2] == "pip":
            metadata = gen / "lib/python3.14/site-packages/pkg-1.2.3.dist-info"
            metadata.mkdir(parents=True, exist_ok=True)
            (metadata / "METADATA").write_text("Name: pkg\nVersion: 1.2.3\n")
            (metadata / "entry_points.txt").write_text(
                "[console_scripts]\n" + "".join(name + " = pkg:main\n" for name in self.declared))
            for name in BINS:
                target = gen / "bin" / name
                target.parent.mkdir(exist_ok=True)
                target.write_text("not executed")
                target.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 1 if self.fail_command else 0)

    def item(self, manager="npm-locked", version="1.2.3", **extra):
        if manager == "npm-locked":
            (self.root / "lock").write_text(json.dumps({"lockfileVersion": 3, "packages": {
                "": {"dependencies": {"pkg": version}}, "node_modules/pkg": {
                    "version": version, "resolved": "https://registry.npmjs.org/pkg.tgz",
                    "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode()}}}))
        else:
            (self.root / "lock").write_text("pkg==" + version + " --hash=sha256:" + "a" * 64)
        tool = ToolSpec(ToolReference("pkg@" + version, "pkg", version))
        env = Environment("linux", "x86_64")
        fields = dict(manager=manager, pkg="pkg", lock="lock", bins=list(BINS))
        fields.update(extra)
        strategy = resolve_tool_strategy(tool, {"pkg": {"linux": fields}}, env, self.root)
        return PlanItem("test", tool, strategy, env)

    def bindir(self):
        return self.home / ".local/bin"

    def store(self, manager="npm-locked"):
        # bin defaults to the logical tool name when bins is declared.
        return self.home / ".local/share/tool-installer/locked" / manager / "pkg"

    def generation_of(self, name="alpha"):
        target = Path(os.readlink(self.bindir() / name))
        # npm: gen/node_modules/pkg/alpha.js -> parents[2] = gen
        # python: gen/bin/alpha -> parents[1] = gen
        return target.parents[2] if "node_modules" in target.parts else target.parents[1]

    def receipt_path(self, name="alpha"):
        return self.generation_of(name) / "receipt.json"

    # ---- happy path ----------------------------------------------------

    def test_dual_bins_publish_check_and_idempotence(self):
        for manager in ("npm-locked", "python-locked"):
            with self.subTest(manager=manager):
                item = self.item(manager)
                instance = default_registry(runner=self.runner)[manager]
                instance.install(item)
                for name in BINS:
                    dest = self.bindir() / name
                    self.assertTrue(dest.is_symlink(), name)
                    self.assertEqual(dest.read_bytes(), b"not executed")
                self.assertEqual(instance.check(item), CheckResult.SATISFIED)
                receipt = json.loads(self.receipt_path().read_text())
                self.assertEqual(set(receipt["targets"]), set(BINS))
                # Every recorded target is absolute, lies inside the one generation,
                # and is the target of that bin live symlink.
                generation = self.generation_of()
                for name, target in receipt["targets"].items():
                    self.assertTrue(Path(target).is_absolute())
                    self.assertEqual(Path(target).parent, generation / ("node_modules/pkg" if manager == "npm-locked" else "bin"))
                    self.assertEqual(str((self.bindir() / name).resolve()), target)
                self.assertEqual(len(list(self.store(manager).glob("gen-*"))), 1)
                count = len(self.calls)
                instance.install(item)
                self.assertEqual(len(self.calls), count, "idempotence ran install again")
                self.assertEqual(instance.check(item), CheckResult.SATISFIED)
                # Reset HOME bin dir between managers so stores do not collide.
                for name in BINS:
                    (self.bindir() / name).unlink()
                self.calls.clear()

    def test_bins_only_strategy_without_bin_field(self):
        # "二选一": bins alone is sufficient; no bin field is required.
        fields = dict(manager="npm-locked", pkg="pkg", lock="lock", bins=list(BINS))
        (self.root / "lock").write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "": {"dependencies": {"pkg": "1.2.3"}}, "node_modules/pkg": {
                "version": "1.2.3", "resolved": "https://registry.npmjs.org/pkg.tgz",
                "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode()}}}))
        tool = ToolSpec(ToolReference("pkg@1.2.3", "pkg", "1.2.3"))
        strategy = resolve_tool_strategy(tool, {"pkg": {"linux": fields}},
                                         Environment("linux", "x86_64"), self.root)
        # resolve_tool_strategy defaults bin to the logical tool name; prove the
        # manager also tolerates a genuinely bin-less strategy payload.
        from dataclasses import replace
        binless = replace(strategy, fields={k: v for k, v in strategy.fields.items() if k != "bin"})
        item = PlanItem("test", tool, binless, Environment("linux", "x86_64"))
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(item)
        self.assertEqual(set(p.name for p in self.bindir().iterdir()), set(BINS))
        self.assertEqual(instance.check(item), CheckResult.SATISFIED)

    def test_bins_wins_over_coexisting_bin(self):
        item = self.item(bin="legacy-name")
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(item)
        self.assertEqual(set(p.name for p in self.bindir().iterdir()), set(BINS))
        self.assertFalse((self.bindir() / "legacy-name").exists())
        self.assertEqual(instance.check(item), CheckResult.SATISFIED)
        self.assertEqual(set(json.loads(self.receipt_path().read_text())["targets"]), set(BINS))

    # ---- verification failure rolls back the whole set -----------------

    def test_one_bin_verification_failure_fails_all_and_keeps_old_entries(self):
        manager = "npm-locked"
        instance = default_registry(runner=self.runner)[manager]
        old = self.item(manager)
        instance.install(old)
        old_links = {name: os.readlink(self.bindir() / name) for name in BINS}
        old_generations = sorted(self.store(manager).glob("gen-*"))
        # New version whose root declares only alpha (beta verification fails).
        self.declared = {"alpha"}
        updated = self.item(manager, version="1.2.4")
        with self.assertRaises(InstallationError):
            instance.install(updated)
        for name in BINS:
            self.assertEqual(os.readlink(self.bindir() / name), old_links[name])
        self.assertEqual(sorted(self.store(manager).glob("gen-*")), old_generations,
                         "failed attempt left a new generation")
        # item() rewrote the lock for 1.2.4; restore the original plan before checking.
        self.assertEqual(instance.check(self.item(manager)), CheckResult.SATISFIED)

    def test_python_one_bin_verification_failure_fails_all(self):
        self.declared = {"alpha"}
        item = self.item("python-locked")
        with self.assertRaises(InstallationError):
            default_registry(runner=self.runner)["python-locked"].install(item)
        self.assertFalse((self.bindir() / "alpha").exists())
        self.assertFalse((self.bindir() / "beta").exists())
        self.assertEqual(list(self.store("python-locked").glob("gen-*")), [])

    def test_update_publication_failure_restores_old_links(self):
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(self.item())
        old_links = {name: os.readlink(self.bindir() / name) for name in BINS}
        old_generations = sorted(self.store().glob("gen-*"))
        updated = self.item(version="1.2.4")
        real_replace = os.replace
        state = {"n": 0}
        def flaky(src, dst, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                raise OSError("synthetic update publication failure")
            return real_replace(src, dst, **kwargs)
        with mock.patch("tool_installer.managers.locked.os.replace", side_effect=flaky):
            with self.assertRaises(InstallationError):
                instance.install(updated)
        for name in BINS:
            self.assertEqual(os.readlink(self.bindir() / name), old_links[name])
        self.assertEqual(sorted(self.store().glob("gen-*")), old_generations)
        self.assertEqual(len(list((self.bindir()).glob(".tool-installer-*"))), 0,
                         "no staged temporary symlink may remain")

    def test_python_dependency_same_name_bin_rejected_and_rolls_back(self):
        item = self.item("python-locked")
        def run(cmd, **kwargs):
            result = self.run_command(cmd, **kwargs)
            if cmd[0] == "uv" and cmd[2] == "pip":
                gen = Path(kwargs["cwd"])
                dep = gen / "lib/python3.14/site-packages/dep-1.0.dist-info"
                dep.mkdir(parents=True, exist_ok=True)
                (dep / "METADATA").write_text("Name: dep\nVersion: 1.0\n")
                (dep / "entry_points.txt").write_text("[console_scripts]\nbeta = dep:main\n")
            return result
        self.runner.run.side_effect = run
        with self.assertRaises(InstallationError):
            default_registry(runner=self.runner)["python-locked"].install(item)
        self.assertFalse((self.bindir() / "alpha").exists())
        self.assertFalse((self.bindir() / "beta").exists())
        self.assertEqual(list(self.store("python-locked").glob("gen-*")), [])

    def test_publication_failure_rolls_back_partial_new_entries(self):
        # First publish is forced to fail at the second bin (foreign dest appears
        # between staging and publication via a patched os.link).
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        real_link = os.link
        state = {"n": 0}
        def flaky(src, dst, **kwargs):
            state["n"] += 1
            if state["n"] == 2:
                raise OSError("synthetic publication failure")
            return real_link(src, dst, **kwargs)
        with mock.patch("tool_installer.managers.locked.os.link", side_effect=flaky):
            with self.assertRaises(InstallationError):
                instance.install(item)
        self.assertFalse((self.bindir() / "alpha").exists())
        self.assertFalse((self.bindir() / "beta").exists())
        self.assertEqual(list(self.store().glob("gen-*")), [])

    # ---- foreign entries / force / HOME --------------------------------

    def test_foreign_bin_is_never_overwritten_even_with_force(self):
        for force in (False, True):
            with self.subTest(force=force):
                item = self.item(force=force)
                instance = default_registry(runner=self.runner)["npm-locked"]
                dest = self.bindir() / "alpha"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("foreign user bin")
                with self.assertRaises(AuthorizationRequired):
                    instance.install(item)
                with self.assertRaises(AuthorizationRequired):
                    instance.check(item)
                self.assertEqual(dest.read_text(), "foreign user bin")
                self.assertFalse((self.bindir() / "beta").exists(), "no partial new entry")
                self.assertEqual(self.calls, [], "no package command may run")
                dest.unlink()

    def test_foreign_symlink_is_not_migrated(self):
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        outside = self.root / "outside"
        outside.write_text("mine")
        dest = self.bindir() / "beta"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(outside)
        with self.assertRaises(AuthorizationRequired):
            instance.install(item)
        self.assertEqual(os.readlink(dest), str(outside))
        self.assertFalse((self.bindir() / "alpha").exists())
        self.assertEqual(self.calls, [])

    def test_mixed_owned_and_foreign_bins_fail_closed(self):
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(item)
        owned_alpha = os.readlink(self.bindir() / "alpha")
        (self.bindir() / "beta").unlink()
        (self.bindir() / "beta").write_text("foreign user bin")
        with self.assertRaises(AuthorizationRequired):
            instance.check(item)
        with self.assertRaises(AuthorizationRequired):
            instance.install(self.item(force=True))
        self.assertEqual(os.readlink(self.bindir() / "alpha"), owned_alpha)
        self.assertEqual((self.bindir() / "beta").read_text(), "foreign user bin")
        self.assertEqual(len(list(self.store().glob("gen-*"))), 1, "no partial new generation")

    def test_missing_home_fails_closed(self):
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        with mock.patch("pathlib.Path.home", side_effect=RuntimeError("HOME unavailable")):
            with self.assertRaises(RuntimeError):
                instance.install(item)
        self.assertEqual(self.calls, [], "no install work without HOME")
        self.assertFalse((self.root / "home/.local/bin").exists())

    # ---- receipt completeness / digest / old generation retention -----

    def test_receipt_missing_one_bin_is_not_satisfied_and_repairs(self):
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(item)
        receipt = json.loads(self.receipt_path().read_text())
        del receipt["targets"]["beta"]
        self.receipt_path().write_text(json.dumps(receipt))
        self.assertEqual(instance.check(item), CheckResult.NOT_SATISFIED)
        # A reinstall must repair the incomplete receipt rather than early-return.
        instance.install(item)
        self.assertEqual(set(json.loads(self.receipt_path().read_text())["targets"]), set(BINS))
        self.assertEqual(instance.check(item), CheckResult.SATISFIED)

    def test_lock_digest_mismatch_is_not_satisfied(self):
        item = self.item()
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(item)
        self.assertEqual(instance.check(item), CheckResult.SATISFIED)
        # Same root/version, different lock bytes -> different planned digest.
        # The saved lock still validates against the receipt digest, but the
        # receipt digest no longer matches the current plan, so check declines.
        (self.root / "lock").write_text((self.root / "lock").read_text() + " ")
        from dataclasses import replace
        tool = ToolSpec(ToolReference("pkg@1.2.3", "pkg", "1.2.3"))
        fields = dict(manager="npm-locked", pkg="pkg", lock="lock", bins=list(BINS))
        changed_strategy = resolve_tool_strategy(tool, {"pkg": {"linux": fields}},
                                                 Environment("linux", "x86_64"), self.root)
        changed = replace(item, strategy=changed_strategy)
        self.assertNotEqual(changed.strategy.lock_digest, item.strategy.lock_digest)
        self.assertEqual(instance.check(changed), CheckResult.NOT_SATISFIED)

    def test_successful_update_keeps_old_generation(self):
        instance = default_registry(runner=self.runner)["npm-locked"]
        instance.install(self.item())
        old = self.generation_of()
        old_links = {name: os.readlink(self.bindir() / name) for name in BINS}
        updated = self.item(version="1.2.4")
        instance.install(updated)
        self.assertTrue(old.is_dir(), "old generation must survive")
        self.assertEqual(len(list(self.store().glob("gen-*"))), 2)
        for name in BINS:
            self.assertNotEqual(os.readlink(self.bindir() / name), old_links[name])
        self.assertEqual(instance.check(updated), CheckResult.SATISFIED)

    # ---- schema ---------------------------------------------------------

    def test_schema_accepts_safe_bins(self):
        for manager in ("npm-locked", "python-locked"):
            with self.subTest(manager=manager):
                item = self.item(manager, bins=["a", "b.c", "d-e", "f_g"])
                self.assertEqual(declared_bins(item.strategy.fields), ["a", "b.c", "d-e", "f_g"])

    def test_schema_rejects_illegal_bins(self):
        illegal = [
            [], ["../escape"], ["a/b"], ["-leading"], [".hidden"], ["a", "a"],
            ["a", ""], ["a", 1], "not-an-array", ["a", "with space"],
            ["a\nb"], ["a\\b"], ["a;b"],
        ]
        for value in illegal:
            with self.subTest(bins=value):
                with self.assertRaises(StrategyError):
                    self.item(bins=value)

    def test_read_lock_accepts_bins_and_rejects_illegal_bins(self):
        from tool_installer.managers.locked import read_lock
        item = self.item()
        text, digest = read_lock(self.root, item.strategy.fields, "1.2.3", "npm-locked")
        self.assertEqual(digest, item.strategy.lock_digest)
        self.assertTrue(text)
        bad = dict(item.strategy.fields, bins=["../escape"])
        with self.assertRaises(StrategyError):
            read_lock(self.root, bad, "1.2.3", "npm-locked")


if __name__ == "__main__":
    unittest.main()
