"""CLI-level offline regression for opt-in hash-locked installation plans."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_installer import cli
from tool_installer.models import Environment


class LockedCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "sentinel").write_text("untouched", encoding="utf-8")
        self.config = self.root / "tools.toml"
        self.config.write_text(
            '[tool-installer]\nmanifest = "manifest.toml"\n'
            '[module]\n"node-cli@1.2.3" = "npm fixture"\n'
            '"python-cli@1.2.3" = "python fixture"\n', encoding="utf-8")
        for target in ("linux-x86_64", "macos-aarch64"):
            self.write_lock("npm", target)
            self.write_lock("python", target)
        (self.root / "manifest.toml").write_text("\n".join(
            f'[{name}.{os_name}.{arch}]\nmanager = "{kind}-locked"\n'
            f'pkg = "{name}"\nlock = "{kind}-{os_name}-{arch}.lock"\n'
            for name, kind in (("node-cli", "npm"), ("python-cli", "python"))
            for os_name, arch in (("linux", "x86_64"), ("macos", "aarch64"))
        ), encoding="utf-8")

    def write_lock(self, kind, target, pkg=None, version="1.2.3"):
        pkg = pkg or ("node-cli" if kind == "npm" else "python-cli")
        if kind == "npm":
            text = json.dumps({"lockfileVersion": 3, "packages": {
                "": {"dependencies": {pkg: version}},
                "node_modules/" + pkg: {
                    "version": version, "resolved": "https://registry.npmjs.org/fixture.tgz",
                    "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode("ascii")}}})
        else:
            text = pkg + "==" + version + " --hash=sha256:" + "a" * 64 + "\n"
        path = self.root / f"{kind}-{target}.lock"
        path.write_text(text, encoding="utf-8")
        return path

    def snapshot_home(self):
        return {str(p.relative_to(self.home)): (
            "symlink", os.readlink(p)) if p.is_symlink() else (
            "directory", None) if p.is_dir() else ("file", p.read_bytes())
            for p in self.home.rglob("*")}

    def invoke(self, environment, config=None, module="module", dry_run=True):
        stdout, stderr = io.StringIO(), io.StringIO()
        before = self.snapshot_home()
        # Keep parsing, resolution, lock validation and rendering real. Any accidental
        # executor/manager, external process or network entry is an immediate failure.
        targets = ("tool_installer.cli.execute_plan", "tool_installer.cli.default_registry",
                   "tool_installer.managers.locked.LockedManager.install",
                   "subprocess.Popen", "subprocess.run", "os.system",
                   "urllib.request.urlopen", "urllib.request.OpenerDirector.open",
                   "socket.create_connection", "socket.socket.connect")
        from contextlib import ExitStack
        with ExitStack() as stack:
            guards = [stack.enter_context(mock.patch(
                target, side_effect=AssertionError("Forbidden offline operation: " + target)))
                for target in targets]
            stack.enter_context(mock.patch.dict(os.environ, {
                "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
                "XDG_DATA_HOME": str(self.home / ".local/share"),
                "XDG_CACHE_HOME": str(self.home / ".cache")}))
            stack.enter_context(mock.patch("pathlib.Path.home", return_value=self.home))
            stack.enter_context(mock.patch.object(cli, "detect_environment", return_value=environment))
            rendered = stack.enter_context(mock.patch.object(
                cli, "print_dry_run", wraps=cli.print_dry_run))
            with redirect_stdout(stdout), redirect_stderr(stderr):
                args = ["install", module, "--config", str(config or self.config)]
                if dry_run:
                    args.append("--dry-run")
                code = cli.main(args)
            for guard in guards:
                guard.assert_not_called()
        self.assertEqual(self.snapshot_home(), before, "CLI wrote into HOME")
        return code, stdout.getvalue(), stderr.getvalue(), rendered

    def test_valid_locks_dry_run_selects_platform_lock(self):
        for os_name, arch in (("linux", "x86_64"), ("macos", "aarch64")):
            with self.subTest(os=os_name, arch=arch):
                code, out, err, rendered = self.invoke(Environment(os_name, arch))
                self.assertEqual(code, 0, err)
                self.assertEqual(err, "")
                self.assertEqual(len(out.splitlines()), 2)
                rendered.assert_called_once()
                for item, kind in zip(rendered.call_args.args[0].items, ("npm", "python")):
                    self.assertEqual(item.strategy.manager, kind + "-locked")
                    self.assertEqual(item.strategy.fields["lock"], f"{kind}-{os_name}-{arch}.lock")
                    self.assertEqual(item.strategy.lock_root, self.root.resolve())
                    self.assertRegex(item.strategy.lock_digest, r"^[0-9a-f]{64}$")
                    self.assertIn(f"manager={kind}-locked os={os_name} arch={arch}", out)

    def test_invalid_locks_fail_before_render_or_install(self):
        # An expired lock means its pinned root version no longer matches tools.toml.
        for kind in ("npm", "python"):
            for fault in ("missing", "wrong-root", "stale-version"):
                for dry_run in (True, False):
                    with self.subTest(kind=kind, fault=fault, dry_run=dry_run):
                        path = self.write_lock(kind, "linux-x86_64")
                        if fault == "missing":
                            path.unlink()
                        elif fault == "wrong-root":
                            self.write_lock(kind, "linux-x86_64", pkg="unrelated")
                        else:
                            self.write_lock(kind, "linux-x86_64", version="1.2.2")
                        code, out, err, rendered = self.invoke(
                            Environment("linux", "x86_64"), dry_run=dry_run)
                        self.assertNotEqual(code, 0)
                        self.assertIn("Invalid locked-manager lock", err)
                        self.assertEqual(out, "")
                        rendered.assert_not_called()
                        self.write_lock(kind, "linux-x86_64")

    def test_unmigrated_default_manifest_still_has_60_plan_items(self):
        config = Path(__file__).resolve().parents[2] / "tools.toml"
        for os_name, arch in (("linux", "x86_64"), ("macos", "aarch64")):
            with self.subTest(os=os_name, arch=arch):
                code, out, err, rendered = self.invoke(
                    Environment(os_name, arch), config=config, module="dev")
                self.assertEqual(code, 0, err)
                self.assertEqual(err, "")
                lines = out.splitlines()
                self.assertEqual(len(lines), 60)
                self.assertTrue(all(line.startswith("PLAN ") for line in lines))
                plan = rendered.call_args.args[0]
                self.assertEqual(len(plan.items), 60)
                self.assertTrue(all(item.strategy.manager not in {
                    "npm-locked", "python-locked"} for item in plan.items))
                self.assertTrue(all(item.strategy.lock_root is None and
                                    item.strategy.lock_digest is None for item in plan.items))


if __name__ == "__main__":
    unittest.main()
