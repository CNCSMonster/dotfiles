"""Real offline uv installer component coverage, NOT LockedManager E2E.

LockedManager has no wheelhouse input. Changing its runner command to add one
would not test its real behavior. This test exercises the real uv installer with
its hash/binary policy plus explicit offline inputs; manager planning, receipts,
ownership and publication remain covered by test_locked_managers.py mocks.
Only the complete synthetic wheel below is installed. Its module/entrypoint is
never imported or executed, and no external package or build backend is used.
"""
import base64
import configparser
import csv
from email.parser import Parser
import hashlib
import importlib.metadata
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


NAME = "locked-offline-fixture"
VERSION = "1.0.0"
MODULE = "locked_offline_fixture"
DIST_INFO = MODULE + "-" + VERSION + ".dist-info"
ENTRY = NAME
# Reviewed complete payload: no imports, dependencies, side effects or build hooks.
# Raising main also makes accidental entrypoint execution fail visibly.
PAYLOAD = {
    MODULE + ".py": b'def main():\n    raise RuntimeError("fixture entry point must never run")\n',
    DIST_INFO + "/METADATA": (
        "Metadata-Version: 2.1\nName: " + NAME + "\nVersion: " + VERSION + "\n\n"
    ).encode("ascii"),
    DIST_INFO + "/WHEEL": (
        "Wheel-Version: 1.0\nGenerator: stdlib-test-fixture\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n\n"
    ).encode("ascii"),
    DIST_INFO + "/entry_points.txt": (
        "[console_scripts]\n" + ENTRY + " = " + MODULE + ":main\n"
    ).encode("ascii"),
}


def record_hash(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


class OfflineUvInstallerComponentTests(unittest.TestCase):
    def setUp(self):
        uv = shutil.which("uv")
        if uv is None:
            self.skipTest("uv not found on PATH; real offline test requires existing uv")
        self.uv = str(Path(uv).absolute())
        temporary = tempfile.TemporaryDirectory(prefix="locked-python-integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.wheelhouse = self.root / "wheelhouse"
        self.venv = self.root / "venv"
        for directory in (self.home, self.wheelhouse, self.root / "tmp"):
            directory.mkdir()
        # Allowlist: no inherited proxy, credentials, pip/uv config, active venv,
        # PYTHONPATH or user cache. Commands use absolute executables.
        self.env = {
            "PATH": os.defpath,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "XDG_DATA_HOME": str(self.home / "data"),
            "TMPDIR": str(self.root / "tmp"),
            "UV_CACHE_DIR": str(self.root / "uv-cache"),
            "UV_NO_CONFIG": "1",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "PYTHONNOUSERSITE": "1",
            "LC_ALL": "C",
        }
        self.wheel = self.wheelhouse / (MODULE + "-" + VERSION + "-py3-none-any.whl")
        record = io.StringIO(newline="")
        writer = csv.writer(record, lineterminator="\n")
        for name, data in PAYLOAD.items():
            writer.writerow((name, record_hash(data), len(data)))
        writer.writerow((DIST_INFO + "/RECORD", "", ""))
        with zipfile.ZipFile(self.wheel, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in PAYLOAD.items():
                archive.writestr(name, data)
            archive.writestr(DIST_INFO + "/RECORD", record.getvalue())
        self.audit_wheel()
        result = self.run_command([sys.executable, "-I", "-m", "venv", "--without-pip", str(self.venv)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.python = self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.assertTrue(self.python.is_file())

    def run_command(self, command):
        return subprocess.run(command, cwd=self.root, env=self.env, timeout=60,
                              capture_output=True, text=True, check=False)

    def audit_wheel(self):
        with zipfile.ZipFile(self.wheel) as archive:
            self.assertEqual(set(archive.namelist()), set(PAYLOAD) | {DIST_INFO + "/RECORD"})
            self.assertEqual(len(archive.namelist()), len(PAYLOAD) + 1)
            for name, data in PAYLOAD.items():
                self.assertEqual(archive.read(name), data)
            rows = list(csv.reader(io.StringIO(archive.read(DIST_INFO + "/RECORD").decode("ascii"))))
            self.assertEqual(rows, [[name, record_hash(data), str(len(data))]
                                    for name, data in PAYLOAD.items()] + [[DIST_INFO + "/RECORD", "", ""]])
        metadata = Parser().parsestr(PAYLOAD[DIST_INFO + "/METADATA"].decode("ascii"))
        self.assertEqual(metadata["Name"], NAME)
        self.assertEqual(metadata["Version"], VERSION)
        self.assertIsNone(metadata["Requires-Dist"])
        wheel = Parser().parsestr(PAYLOAD[DIST_INFO + "/WHEEL"].decode("ascii"))
        self.assertEqual(wheel["Root-Is-Purelib"], "true")
        self.assertEqual(wheel.get_all("Tag"), ["py3-none-any"])
        entries = configparser.ConfigParser()
        entries.read_string(PAYLOAD[DIST_INFO + "/entry_points.txt"].decode("ascii"))
        self.assertEqual(entries.sections(), ["console_scripts"])
        self.assertEqual(dict(entries["console_scripts"]), {ENTRY: MODULE + ":main"})

    def install(self, digest):
        requirements = self.root / "requirements.txt"
        requirements.write_text(NAME + "==" + VERSION + " --hash=sha256:" + digest + "\n", encoding="ascii")
        return self.run_command([
            self.uv, "--no-config", "--offline", "pip", "install",
            "--python", str(self.python), "--require-hashes", "--only-binary", ":all:",
            "--no-index", "--find-links", str(self.wheelhouse), "-r", str(requirements),
        ])

    def test_real_uv_installer_accepts_correct_wheel_hash_offline(self):
        result = self.install(hashlib.sha256(self.wheel.read_bytes()).hexdigest())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata_paths = list(self.venv.rglob(DIST_INFO))
        self.assertEqual(len(metadata_paths), 1)
        installed = metadata_paths[0]
        # Metadata-only inspection: never import fixture or load entrypoints.
        distribution = importlib.metadata.PathDistribution(installed)
        self.assertEqual(distribution.metadata["Name"], NAME)
        self.assertEqual(distribution.version, VERSION)
        self.assertEqual([(entry.group, entry.name, entry.value) for entry in distribution.entry_points],
                         [("console_scripts", ENTRY, MODULE + ":main")])
        for name, expected in PAYLOAD.items():
            self.assertEqual((installed.parent / name).read_bytes(), expected)
        script = self.python.parent / (ENTRY + ".exe" if os.name == "nt" else ENTRY)
        self.assertTrue(script.is_file())  # Existence only; do not execute.

    def test_real_uv_installer_rejects_wrong_wheel_hash_offline(self):
        actual = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        wrong = ("0" if actual[0] != "0" else "1") + actual[1:]
        result = self.install(wrong)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("hash mismatch", (result.stdout + result.stderr).lower())
        self.assertFalse(list(self.venv.rglob(DIST_INFO)))
        self.assertFalse(list(self.venv.rglob(MODULE + ".py")))
        self.assertFalse((self.python.parent / ENTRY).exists())
        self.assertFalse((self.python.parent / (ENTRY + ".exe")).exists())


if __name__ == "__main__":
    unittest.main()
