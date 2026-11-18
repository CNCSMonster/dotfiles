"""Entirely offline maintenance tests: resolver processes are replaced with runners."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("update_tool_locks", Path(__file__).resolve().parents[2] / "scripts/update-tool-locks.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
HASH = "--hash=sha256:" + "a" * 64
FLAGS = "--generate-hashes --only-binary --no-strip-markers --no-strip-extras --no-annotate --no-header --python --no-python-downloads --no-config"


def npm_lock(version="1.2.3"):
    return json.dumps({"lockfileVersion": 3, "packages": {"": {"dependencies": {"demo": version}},
        "node_modules/demo": {"version": version, "resolved": "https://registry.npmjs.org/demo/-/demo.tgz",
        "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode()}}})


class UpdateLocksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = m.Environment("linux", "x86_64")
        self.tools = self.root / "tools.toml"
        self.tools.write_text('[tool-installer]\nmanifest="manifest.toml"\n[demo-module]\n"demo@1.2.3"="demo"\n')
        self.fields = {"manager": "npm-locked", "pkg": "demo", "lock": "lock.json", "bin": "demo"}
        self.configure()
        self.args = ["--tools", str(self.tools), "--module", "demo-module", "--tool", "demo"]
        self.calls = []

    def configure(self, manager="npm-locked", lock="lock.json", extra=""):
        lines = ['[demo]', f'manager="{manager}"', 'pkg="demo"', f'lock="{lock}"',
                 '[demo.linux]', '[demo.macos]']
        if extra:
            lines += [f'[demo.{self.host.os}.{self.host.arch}]', extra]
        (self.root / "manifest.toml").write_text("\n".join(lines) + "\n")

    def invoke(self, *args, runner=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return m.main(self.args + list(args), runner=runner or self.forbidden)

    def forbidden(self, *args, **kwargs):
        self.fail("offline check or early failure invoked resolver")

    def runner(self, command, *, cwd, extra_env=None):
        self.calls.append(command)
        if command[-1] == "--version":
            return "test-generator 1.0"
        if command[-1] == "--help":
            return FLAGS
        if "install" in command:
            self.assertEqual(json.loads((cwd / "package.json").read_text())["dependencies"], {"demo": "1.2.3"})
            (cwd / "package-lock.json").write_text(npm_lock())
        else:
            self.assertEqual((cwd / "requirements.in").read_text(), "demo==1.2.3\n")
            (cwd / "requirements.txt").write_text("demo==1.2.3 " + chr(92) + "\n    " + HASH + "\n")
        return ""

    def test_default_and_explicit_check_never_run_process(self):
        (self.root / "lock.json").write_text(npm_lock())
        with patch.object(m.subprocess, "run", side_effect=AssertionError("process forbidden")):
            self.assertEqual(self.invoke(), 0)
            self.assertEqual(self.invoke("--check"), 0)

    def test_wrong_root_missing_and_unpinned_fail_offline(self):
        self.assertEqual(self.invoke(), 1)
        (self.root / "lock.json").write_text(npm_lock("9.0.0"))
        self.assertEqual(self.invoke(), 1)
        self.tools.write_text(self.tools.read_text().replace("demo@1.2.3", "demo@latest"))
        self.assertEqual(self.invoke("--generate"), 1)

    def test_npm_generate_is_explicit_and_records_provenance(self):
        with patch.object(m.shutil, "which", return_value="/mock/npm"):
            self.assertEqual(self.invoke("--generate", runner=self.runner), 0)
        data = json.loads((self.root / "lock.json").read_text())
        provenance = data["x-tool-lock-generator"]
        self.assertEqual(provenance["version"], "test-generator 1.0")
        self.assertEqual(provenance["platforms"], list(m.PLATFORM_NAMES))
        self.assertEqual(provenance["resolution"], "universal")
        installs = [call for call in self.calls if "install" in call]
        self.assertEqual(len(installs), len(m.PLATFORMS))
        self.assertEqual(installs[-1][1:], ["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"])
        self.assertFalse(any(self.root.glob("node_modules")))

    def test_existing_requires_force_before_any_process(self):
        output = self.root / "lock.json"
        output.write_text("original")
        self.assertEqual(self.invoke("--generate"), 1)
        self.assertEqual(self.invoke("--force"), 1)
        self.assertEqual(output.read_text(), "original")
        with patch.object(m.shutil, "which", return_value="/mock/npm"):
            self.assertEqual(self.invoke("--generate", "--force", runner=self.runner), 0)
        m.validate(output.read_text(), self.fields, "1.2.3")

    def test_resolver_failure_and_invalid_root_preserve_existing(self):
        output = self.root / "lock.json"
        output.write_text("original")
        def invalid(command, *, cwd, extra_env=None):
            if command[-1] == "--version":
                return "1.0"
            (cwd / "package-lock.json").write_text(npm_lock("8.0.0"))
            return ""
        with patch.object(m.shutil, "which", return_value="/mock/npm"):
            self.assertEqual(self.invoke("--generate", "--force", runner=invalid), 1)
            def fail(*args, **kwargs):
                raise m.ConfigError("resolver failed")
            self.assertEqual(self.invoke("--generate", "--force", runner=fail), 1)
        self.assertEqual(output.read_text(), "original")

    def test_python_generate_flattens_and_preserves_safe_flags(self):
        self.configure("python-locked", "requirements.txt")
        with patch.object(m.shutil, "which", return_value="/mock/uv"):
            self.assertEqual(self.invoke("--generate", runner=self.runner), 0)
        text = (self.root / "requirements.txt").read_text()
        m.validate_python_lock(text, "demo", "1.2.3")
        self.assertEqual(text.splitlines()[-1], "demo==1.2.3 " + HASH)
        compiles = [call for call in self.calls if "--output-file" in call]
        self.assertEqual(len(compiles), len(m.PLATFORMS))
        for call in compiles:
            self.assertIn("--no-strip-markers", call)
            self.assertIn("--no-strip-extras", call)
            self.assertIn("--no-python-downloads", call)
            self.assertNotIn("--universal", call)
            self.assertIn("--python-platform", call)

    def test_markers_are_rejected_not_stripped(self):
        with self.assertRaisesRegex(m.ConfigError, "markers"):
            m.flatten_python('demo==1.2.3; python_version > "3.10" ' + HASH)
        for text in ["demo[extra]==1.2.3 " + HASH, "demo @ https://example.org/a.whl " + HASH]:
            with self.assertRaises(m.ConfigError):
                m.validate_python_lock(m.flatten_python(text), "demo", "1.2.3")
        with self.assertRaises(m.ConfigError):
            m.flatten_python("demo==1.2.3 " + chr(92))

    def test_old_uv_refuses_before_resolve(self):
        fields = dict(self.fields, manager="python-locked")
        with patch.object(m.shutil, "which", return_value="/mock/uv"):
            with self.assertRaisesRegex(m.ConfigError, "flags"):
                m.generate(fields, "1.2.3", runner=lambda *a, **k: "old uv")

    def test_platform_specific_declaration_is_refused_before_resolve(self):
        self.configure(extra='pkg="overridden"')
        with self.assertRaisesRegex(m.ConfigError, "differs"):
            m.select_universal(self.tools, "demo-module", "demo")

    def test_arch_override_and_unsafe_lock_paths(self):
        self.configure(extra='pkg="overridden"')
        fields, _, _ = m.select(self.tools, "demo-module", "demo", self.host)
        self.assertEqual(fields["pkg"], "overridden")
        for raw in ["../outside", "/tmp/outside", "./lock.json", "a//b"]:
            self.configure(lock=raw)
            self.assertEqual(self.invoke("--generate"), 1)
        self.configure()
        (self.root / "real").write_text(npm_lock())
        (self.root / "lock.json").symlink_to(self.root / "real")
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.invoke("--generate", "--force"), 1)

    def test_atomic_publication_failure_keeps_original_and_cleans_temp(self):
        output = self.root / "lock.json"
        output.write_text("old")
        with patch.object(m.os, "replace", side_effect=OSError("replace denied")):
            with self.assertRaises(OSError):
                m.publish(output, "new", force=True)
        self.assertEqual(output.read_text(), "old")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["lock.json", "manifest.toml", "tools.toml"])
        with self.assertRaises(m.ConfigError):
            m.publish(output, "new")

    def test_runner_environment_is_allowlisted_and_configs_are_distinct(self):
        completed = m.subprocess.CompletedProcess(["npm"], 0, stdout="11.0\n", stderr="")
        with patch.dict(m.os.environ, {"NODE_OPTIONS": "--require evil.js", "UV_INDEX": "secret",
                                      "npm_config_registry": "https://bad.invalid", "HTTPS_PROXY": "secret"}):
            with patch.object(m.subprocess, "run", return_value=completed) as run:
                self.assertEqual(m.run_command(["/mock/npm", "--version"], cwd=self.root,
                                               extra_env={"NPM_CONFIG_OS": "darwin"}), "11.0")
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 300)
        env = kwargs["env"]
        for key in ["NODE_OPTIONS", "UV_INDEX", "npm_config_registry", "HTTPS_PROXY"]:
            self.assertNotIn(key, env)
        self.assertEqual(env["UV_NO_CONFIG"], "1")
        self.assertEqual(env["UV_PYTHON_DOWNLOADS"], "never")
        self.assertNotEqual(env["NPM_CONFIG_USERCONFIG"], env["NPM_CONFIG_GLOBALCONFIG"])
        self.assertEqual(env["NPM_CONFIG_OS"], "darwin")
        for key in ["NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG"]:
            self.assertEqual(Path(env[key]).read_text(), "")

    def test_runner_failure_and_timeout_do_not_expose_process_output(self):
        failure = m.subprocess.CompletedProcess(["npm"], 1, stdout="private-token", stderr="private-token")
        for outcome in [failure, m.subprocess.TimeoutExpired("npm", 300, output="private-token", stderr="private-token")]:
            with patch.object(m.subprocess, "run", **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome})):
                with self.assertRaises(m.ConfigError) as error:
                    m.run_command(["/mock/npm", "--version"], cwd=self.root)
            self.assertNotIn("private-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()
