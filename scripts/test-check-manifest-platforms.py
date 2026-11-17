#!/usr/bin/env python3
"""Offline regression tests for scripts/check-manifest-platforms.sh.

Two layers, both fully isolated: no network, no installs, no commits, and no
changes to the real manifest / tools.toml / guard script.

Layer 1 extracts ONLY the pure lock_provenance FunctionDef from the guard's
embedded Python via ast and executes it in a namespace built from stdlib
stubs (json / re / Path / Environment).  The online script, its imports
(tool_installer.*), its config reads and its dispatch loop are never executed.
It builds temporary lock files in a TemporaryDirectory to cover the provenance
contract: matching platform, wrong OS/arch, missing provenance, bad JSON,
unsafe/out-of-root paths, >8 MiB locks and a missing lock_digest.

Layer 2 copies the unmodified guard into an isolated temp repo root (so its
ROOT derivation resolves to the fixture dir instead of the real checkout),
symlinks the real tool-installer package, and runs the real CLI with temporary
tools.toml + manifest.toml + lock fixtures.  It covers main()'s locked-platform
coverage logic: a locked tool declared on only one platform must explicitly name
the other two missing platforms; three platforms each with a provenance-matched
lock must exit 0 without fabricating any extra "other platform" lock files.

Usage: python3 -B scripts/test-check-manifest-platforms.py
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace


REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check-manifest-platforms.sh"
HEX64 = "0123456789abcdef" * 4
PLATFORMS = (("linux", "x86_64"), ("linux", "aarch64"), ("macos", "aarch64"))
MAX_LOCK_BYTES = 8 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Shared fixture builders
# --------------------------------------------------------------------------- #
def _npm_integrity() -> str:
    """A canonical sha512 SRI accepted by tool_installer.hash_lock._integrity."""
    raw = hashlib.sha512(b"manifest-platforms-fixture").digest()
    return "sha512-" + base64.b64encode(raw).decode("ascii")


def npm_lock(pkg: str, version: str, provenance: dict | None = None,
             *, include_provenance: bool = True) -> str:
    """A minimal but fully valid npm package-lock v3 with generator metadata."""
    data = {
        "name": "fixture",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"dependencies": {pkg: version}},
            "node_modules/" + pkg: {
                "version": version,
                "resolved": f"https://registry.npmjs.org/{pkg}/-/{pkg}-{version}.tgz",
                "integrity": _npm_integrity(),
            },
        },
    }
    if include_provenance:
        data["x-tool-lock-generator"] = provenance or _provenance("linux", "x86_64", "npm")
    return json.dumps(data, indent=2) + "\n"


def python_lock(pkg: str, version: str, provenance: dict | None = None,
                *, include_provenance: bool = True) -> str:
    """A minimal but fully valid hashed requirements.txt with a generator line."""
    head = ""
    if include_provenance:
        head = "# generator: " + json.dumps(
            provenance or _provenance("linux", "x86_64", "uv")) + "\n"
    return head + f"{pkg}=={version} --hash=sha256:{'0' * 64}\n"


def _provenance(os_name: str, arch: str, manager: str) -> dict:
    return {
        "generator": f"/usr/bin/{manager}",
        "version": "10.0.0" if manager == "npm" else "0.11.18",
        "os": os_name,
        "arch": arch,
        "python": None,
    }


# --------------------------------------------------------------------------- #
# Layer 1: AST-extracted pure function
# --------------------------------------------------------------------------- #
class Environment:
    """Minimal stub for the guard's Environment (os / arch only)."""

    def __init__(self, os: str, arch: str):
        self.os = os
        self.arch = arch


def load_lock_provenance():
    """Compile only the lock_provenance FunctionDef; never run the online script."""
    script = GUARD.read_text(encoding="utf-8")
    source = script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name == "lock_provenance"]
    if len(nodes) != 1:
        raise AssertionError("embedded lock_provenance function not found")
    # json / re / Path are pure stdlib; Environment is an offline stub.
    # No tool_installer imports, no config reads, no main() dispatch, no network.
    namespace = {"json": json, "re": re, "Path": Path, "Environment": Environment}
    exec(compile(ast.Module(body=nodes, type_ignores=[]),
                 "<embedded lock_provenance>", "exec"), namespace)
    return namespace["lock_provenance"]


class LockProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.lock_provenance = load_lock_provenance()
        self.tmp = tempfile.TemporaryDirectory(prefix="mp-ast-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = Environment("linux", "x86_64")

    def _strategy(self, text: str | None, *, manager="npm-locked", raw="l.json",
                  digest="digest", link_outside=False, write=True):
        """Write an isolated lock file and return a MergedStrategy-like stub."""
        root = self.root
        if text is not None and write:
            target = root / raw
            if link_outside:
                outside = Path(tempfile.mkdtemp(prefix="mp-outside-")) / "outside"
                self.addCleanup(lambda p=outside: p.unlink(missing_ok=True))
                outside.write_text(text)
                target.symlink_to(outside)
            else:
                target.write_text(text)
        return SimpleNamespace(
            lock_root=root,
            lock_digest=digest,
            fields={"lock": raw},
            manager=manager,
        )

    def test_npm_same_platform_passes(self):
        text = npm_lock("t", "1.0.0", _provenance("linux", "x86_64", "npm"))
        self.assertIsNone(self.lock_provenance(self._strategy(text), self.env))

    def test_python_same_platform_passes(self):
        text = python_lock("t", "1.0.0", _provenance("linux", "x86_64", "uv"))
        strategy = self._strategy(text, manager="python-locked")
        self.assertIsNone(self.lock_provenance(strategy, self.env))

    def test_wrong_os_rejected(self):
        for manager, build in (("npm-locked", npm_lock),
                               ("python-locked", python_lock)):
            with self.subTest(manager=manager):
                text = build("t", "1.0.0", _provenance("macos", "x86_64", "npm"))
                result = self.lock_provenance(
                    self._strategy(text, manager=manager), self.env)
                self.assertIsNotNone(result)
                self.assertIn("生成", result)
                self.assertIn("不能用于该平台", result)

    def test_wrong_arch_rejected(self):
        text = npm_lock("t", "1.0.0", _provenance("linux", "aarch64", "npm"))
        result = self.lock_provenance(self._strategy(text), self.env)
        self.assertIsNotNone(result)
        self.assertIn("'aarch64'", result)

    def test_missing_provenance_rejected(self):
        for manager, build in (("npm-locked", npm_lock),
                               ("python-locked", python_lock)):
            with self.subTest(manager=manager):
                text = build("t", "1.0.0", include_provenance=False)
                result = self.lock_provenance(
                    self._strategy(text, manager=manager), self.env)
                self.assertIsNotNone(result)
                self.assertIn("生成", result)

    def test_bad_json_rejected(self):
        cases = [
            ("npm-locked", "{ not json"),
            ("python-locked", "# generator: {bad json\n"),
        ]
        for manager, text in cases:
            with self.subTest(manager=manager):
                result = self.lock_provenance(
                    self._strategy(text, manager=manager), self.env)
                self.assertIsNotNone(result)
                self.assertIn("元数据无法解析", result)

    def test_unsafe_paths_rejected(self):
        text = npm_lock("t", "1.0.0")
        unsafe = ["/abs.json", "a\\b.json", "../x.json", "./x.json",
                  "a//b.json", ""]
        for raw in unsafe:
            with self.subTest(raw=raw):
                result = self.lock_provenance(
                    self._strategy(text, raw=raw, write=False), self.env)
                self.assertIsNotNone(result)
                self.assertIn("lock 路径不安全", result)

    def test_non_string_lock_field_rejected(self):
        strategy = SimpleNamespace(
            lock_root=self.root, lock_digest="digest",
            fields={"lock": 5}, manager="npm-locked")
        result = self.lock_provenance(strategy, self.env)
        self.assertIn("lock 路径不安全", result)

    def test_missing_lock_digest_rejected(self):
        text = npm_lock("t", "1.0.0")
        for digest in (None, ""):
            with self.subTest(digest=digest):
                result = self.lock_provenance(
                    self._strategy(text, digest=digest), self.env)
                self.assertIn("缺少已校验的 lock 摘要", result)
        # lock_root is None must hit the same guard.
        strategy = SimpleNamespace(
            lock_root=None, lock_digest="digest",
            fields={"lock": "l.json"}, manager="npm-locked")
        self.assertIn("缺少已校验的 lock 摘要",
                      self.lock_provenance(strategy, self.env))

    def test_symlink_escaping_lock_root_rejected(self):
        text = npm_lock("t", "1.0.0")
        result = self.lock_provenance(
            self._strategy(text, link_outside=True), self.env)
        self.assertIsNotNone(result)
        self.assertIn("无法读取", result)

    def test_oversize_lock_rejected(self):
        (self.root / "l.json").write_text("A" * (MAX_LOCK_BYTES + 1))
        strategy = SimpleNamespace(
            lock_root=self.root, lock_digest="digest",
            fields={"lock": "l.json"}, manager="npm-locked")
        self.assertIn("超过 8 MiB", self.lock_provenance(strategy, self.env))


# --------------------------------------------------------------------------- #
# Layer 2: real CLI against isolated temp repo fixtures
# --------------------------------------------------------------------------- #
def _tools_toml(entries: list[tuple[str, str]]) -> str:
    lines = ['[tool-installer]', 'manifest = "./manifest.toml"', '', '[dev]']
    for name, version in entries:
        lines.append(f'"{name}@{version}" = "fixture"')
    return "\n".join(lines) + "\n"


def _github_release_block() -> str:
    return f'''manager = "github-release"
repo = "o/r"
asset = "x-{{arch}}.tar.gz"
bin = "x"
sha256 = "{HEX64}"'''


def _locked_block(manager: str, pkg: str, lock: str) -> str:
    return f'''manager = "{manager}"
pkg = "{pkg}"
lock = "{lock}"'''


def _populate(tmp: Path, tools: str, manifest: str, locks: dict[str, str]) -> None:
    """Copy guard + symlink installer + write isolated fixtures."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / "check-manifest-platforms.sh").write_text(
        GUARD.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp / "tool-installer").symlink_to(REPO / "tool-installer")
    (tmp / "tools.toml").write_text(tools, encoding="utf-8")
    (tmp / "manifest.toml").write_text(manifest, encoding="utf-8")
    for rel, text in locks.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def run_guard(tmp: Path):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        ["bash", str(tmp / "scripts" / "check-manifest-platforms.sh")],
        capture_output=True, text=True, env=env, cwd=str(tmp), timeout=120)


def _snapshot(tmp: Path) -> list[str]:
    """Files in the fixture root (excluding the symlinked installer package)."""
    out = []
    for path in tmp.rglob("*"):
        rel = path.relative_to(tmp)
        if rel.parts and rel.parts[0] == "tool-installer":
            continue
        if path.is_file():
            out.append(str(rel))
    return sorted(out)


class GuardCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mp-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_single_platform_names_the_other_two(self):
        """A locked tool declared on only one platform must name both missing ones.

        The other two platforms carry a valid github-release strategy so their
        plans still build (and are simply not counted as locked coverage).  This
        isolates the coverage failure from plan-generation failures.
        """
        manifest = "\n".join([
            "[npmtool.linux.x86_64]",
            _locked_block("npm-locked", "npmtool", "locks/linux-x86_64.json"),
            "",
            "[npmtool.linux.aarch64]",
            _github_release_block(),
            "",
            "[npmtool.macos.aarch64]",
            _github_release_block(),
            "",
        ])
        locks = {
            "locks/linux-x86_64.json": npm_lock(
                "npmtool", "1.2.3", _provenance("linux", "x86_64", "npm")),
        }
        _populate(self.root, _tools_toml([("npmtool", "1.2.3")]), manifest, locks)
        before = _snapshot(self.root)
        result = run_guard(self.root)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("npmtool@1.2.3 的 locked 策略缺少平台", combined)
        self.assertIn("linux/aarch64, macos/aarch64", combined)
        self.assertEqual(before, _snapshot(self.root),
                         "guard must not create or modify fixture files")

    def test_three_platforms_exit_zero_without_fake_locks(self):
        """Each declared platform has a provenance-matched lock -> exit 0.

        Both npm-locked and python-locked managers are exercised.  Exactly six
        lock files exist (2 tools x 3 platforms); the guard must not fabricate
        any additional "other platform" lock (e.g. macos/x86_64).
        """
        manifest_parts = []
        locks = {}
        for os_name, arch in PLATFORMS:
            tag = f"{os_name}-{arch}"
            for manager, pkg, builder in (
                ("npm-locked", "npmtool", npm_lock),
                ("python-locked", "pytool", python_lock),
            ):
                suffix = "json" if manager == "npm-locked" else "txt"
                rel = f"locks/{pkg}/{tag}.{suffix}"
                manifest_parts += [
                    f"[{pkg}.{os_name}.{arch}]",
                    _locked_block(manager, pkg, rel),
                    "",
                ]
                locks[rel] = builder(
                    pkg, "1.2.3",
                    _provenance(os_name, arch,
                                "npm" if manager == "npm-locked" else "uv"))
        manifest = "\n".join(manifest_parts)
        tools = _tools_toml([("npmtool", "1.2.3"), ("pytool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        before = _snapshot(self.root)
        result = run_guard(self.root)
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\n" + result.stderr)
        self.assertIn("locked 条目逐平台校验生成环境", result.stdout)
        self.assertNotIn("缺少平台", result.stdout + result.stderr)
        self.assertEqual(before, _snapshot(self.root),
                         "guard must not create or modify fixture files")
        produced = [p for p in before if p.startswith("locks/")]
        self.assertEqual(len(produced), 6, produced)
        self.assertEqual(sorted(produced), sorted(locks.keys()))
        self.assertFalse(any("macos-x86_64" in p for p in produced),
                         "no fabricated macos/x86_64 lock")


if __name__ == "__main__":
    unittest.main()
