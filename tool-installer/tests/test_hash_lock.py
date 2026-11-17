"""Standard-library-only offline hash-lock contract tests."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tool_installer.errors import ConfigError  # noqa: E402
from tool_installer.hash_lock import validate_npm_lock, validate_python_lock  # noqa: E402

HASH = "--hash=sha256:" + "a" * 64


def remote() -> dict:
    return {"version": "1.2.3", "resolved": "https://registry.npmjs.org/pkg/-/pkg-1.2.3.tgz",
            "integrity": "sha512-" + base64.b64encode(b"a" * 64).decode("ascii")}


def npm_lock() -> dict:
    return {"lockfileVersion": 3, "packages": {"": {"dependencies": {"pkg": "1.2.3"}},
            "node_modules/pkg": remote(), "node_modules/pkg/node_modules/dep": remote()}}


class NpmHashLockTest(unittest.TestCase):
    def validate(self, data: object) -> str:
        return validate_npm_lock(json.dumps(data), "pkg", "1.2.3")

    def test_versions_and_digest(self) -> None:
        for version in (2, 3):
            data = npm_lock()
            data["lockfileVersion"] = version
            if version == 2:
                data["dependencies"] = {"pkg": dict(remote(), dependencies={"dep": remote()})}
            text = json.dumps(data)
            result = self.validate(data)
            self.assertEqual(result, validate_npm_lock(text, "pkg", "1.2.3"))
            self.assertEqual(len(result), 64)
            expected = hashlib.sha256(json.dumps(["hash-lock-v1", "npm", "pkg", "1.2.3", text], ensure_ascii=True).encode()).hexdigest()
            self.assertEqual(result, expected)
            self.assertNotEqual(result, validate_npm_lock(text + " ", "pkg", "1.2.3"))

    def test_sha256_scoped_and_prerelease(self) -> None:
        record = remote()
        record["version"] = "1.2.3-rc.1+build"
        record["integrity"] = "sha256-" + base64.b64encode(b"x" * 32).decode()
        data = {"lockfileVersion": 3, "packages": {"": {"dependencies": {"@scope/pkg": record["version"]}}, "node_modules/@scope/pkg": record}}
        validate_npm_lock(json.dumps(data), "@scope/pkg", record["version"])

    def test_invalid_structures(self) -> None:
        values = [None, [], {}, {"lockfileVersion": True}, {"lockfileVersion": 1},
                  {"lockfileVersion": 3, "packages": []}, {"lockfileVersion": 3, "packages": {"": []}}]
        for data in values:
            with self.subTest(data=data), self.assertRaises(ConfigError):
                self.validate(data)
        for text in ("{", '{"lockfileVersion":3,"lockfileVersion":2}'):
            with self.assertRaises(ConfigError):
                validate_npm_lock(text, "pkg", "1.2.3")

    def test_root_mismatches(self) -> None:
        for deps in ({}, {"pkg": "^1.2.3"}, {"other": "1.2.3"}, {"pkg": "1.2.3", "other": "1.2.3"}):
            data = npm_lock()
            data["packages"][""]["dependencies"] = deps
            with self.subTest(deps=deps), self.assertRaises(ConfigError):
                self.validate(data)
        for group in ("devDependencies", "optionalDependencies", "peerDependencies", "workspaces", "link", "resolved", "integrity"):
            data = npm_lock()
            data["packages"][""][group] = {"other": "1.2.3"}
            with self.subTest(group=group), self.assertRaises(ConfigError):
                self.validate(data)
        data = npm_lock()
        del data["packages"]["node_modules/pkg"]
        with self.assertRaises(ConfigError):
            self.validate(data)
        data = npm_lock()
        data["packages"]["node_modules/pkg"]["version"] = "2.0.0"
        with self.assertRaises(ConfigError):
            self.validate(data)

    def test_all_records_including_transitives_are_checked(self) -> None:
        mutations = [("version", v) for v in (None, "latest", "^1.2.3", "1.2", "01.2.3", "git+https://host/repo", "file:local")]
        mutations += [("resolved", v) for v in (None, "git+https://host/repo", "git://host/repo", "file:local", "link:local", "../local", "http://host/a", "https://user:pass@host/a", "https://[", "https://host/a#frag")]
        mutations += [("integrity", v) for v in (None, "", "sha1-AAAA", "sha256-%%%", "sha512-AAAA", "sha256-" + "A" * 43 + "=", 1)]
        # A canonical 32-byte zero hash is valid; use noncanonical padding bits instead.
        mutations.remove(("integrity", "sha256-" + "A" * 43 + "="))
        mutations.append(("integrity", "sha256-" + "A" * 42 + "B="))
        mutations += [(key, True) for key in ("link", "inBundle", "bundled")]
        for key, value in mutations:
            for path in ("node_modules/pkg", "node_modules/pkg/node_modules/dep"):
                data = npm_lock()
                data["packages"][path][key] = value
                with self.subTest(key=key, value=value, path=path), self.assertRaises(ConfigError):
                    self.validate(data)
        for record in (None, [], {}):
            data = npm_lock()
            data["packages"]["node_modules/pkg/node_modules/dep"] = record
            with self.assertRaises(ConfigError):
                self.validate(data)
        data = npm_lock()
        data["dependencies"] = {"hidden": dict(remote(), integrity=None)}
        with self.assertRaises(ConfigError):
            self.validate(data)

    def test_legacy_conflict_or_unlisted_record(self) -> None:
        for record in (dict(remote(), version="9.0.0"), remote()):
            data = npm_lock()
            data["lockfileVersion"] = 2
            data["dependencies"] = {"pkg" if record["version"] == "9.0.0" else "missing": record}
            with self.assertRaises(ConfigError):
                self.validate(data)

    def test_bad_paths(self) -> None:
        for path in ("workspace/pkg", "node_modules/../evil", "node_modules/", "node_modules/pkg/", "node_modules/pkg//node_modules/dep"):
            data = npm_lock()
            data["packages"][path] = remote()
            with self.subTest(path=path), self.assertRaises(ConfigError):
                self.validate(data)


class PythonHashLockTest(unittest.TestCase):
    def test_valid_hashes_normalization_and_digest(self) -> None:
        text = "# lock\nRoot_Pkg==1.2.3 " + HASH + "\ndep==2.0rc1 " + HASH + " " + HASH + "\n"
        digest = validate_python_lock(text, "root-pkg", "1.2.3")
        self.assertEqual(digest, validate_python_lock(text, "root-pkg", "1.2.3"))
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, validate_python_lock(text + "\n", "root-pkg", "1.2.3"))

    def test_rejects_unsafe_lines_even_after_valid_root(self) -> None:
        lines = ["-r other.txt", "--requirement other.txt", "-c constraints.txt", "--index-url https://host", "--extra-index-url https://host", "--find-links ./wheels", "--trusted-host host", "-e ./local", "dep @ https://host/a.whl", "https://host/a.whl", "git+https://host/repo", "file:local", "dep", "dep>=1", "dep==1.*", "dep===1", "dep==latest", "dep==1.0", "dep==1.0 --hash=sha512:" + "a" * 128, "dep==1.0 --hash=sha256:abc", "dep==1.0 " + HASH + " --no-deps", "dep[x]==1.0 " + HASH, "dep==1.0;python_version>'3' " + HASH, "dep==1.0 " + HASH + " # comment", "dep==1.0 " + HASH + chr(92), "dep==1.0 --hash=sha256:" + "g" * 64]
        for line in lines:
            with self.subTest(line=line), self.assertRaises(ConfigError):
                validate_python_lock("root==1.2.3 " + HASH + "\n" + line, "root", "1.2.3")

    def test_missing_wrong_duplicate_root(self) -> None:
        for text in ("", "# comment", "dep==1.2.3 " + HASH, "root==2.0 " + HASH, "root==1.2.3 " + HASH + "\nROOT==1.2.3 " + HASH):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                validate_python_lock(text, "root", "1.2.3")

    def test_invalid_api_arguments(self) -> None:
        for validator in (validate_npm_lock, validate_python_lock):
            for text, pkg, version in ((None, "pkg", "1.2.3"), ("", "", "1.2.3"), ("", "pkg", "latest"), ("", "pkg", None)):
                with self.assertRaises(ConfigError):
                    validator(text, pkg, version)

    def test_validation_does_not_execute_or_network(self) -> None:
        with mock.patch("subprocess.run", side_effect=AssertionError("no commands")), mock.patch("socket.socket", side_effect=AssertionError("no network")):
            validate_python_lock("root==1.2.3 " + HASH, "root", "1.2.3")
            validate_npm_lock(json.dumps(npm_lock()), "pkg", "1.2.3")


if __name__ == "__main__":
    unittest.main()
