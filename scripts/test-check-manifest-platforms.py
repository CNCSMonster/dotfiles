#!/usr/bin/env python3
"""Offline regression tests for scripts/check-manifest-platforms.sh.

Two layers, both fully isolated: no network, no installs, no commits, and no
changes to the real manifest / tools.toml / guard script.

Layer 1 extracts the pure lock_provenance and npm_target_coverage FunctionDefs
from the guard's embedded Python via ast and executes them together in a
namespace built from stdlib stubs (json / re / Path / Environment).  The online
script, its imports (tool_installer.*), its config reads and its dispatch loop
are never executed.  It builds temporary lock files in a TemporaryDirectory to
cover the provenance contract (matching platform, wrong OS/arch, missing
provenance, bad JSON, unsafe/out-of-root paths, >8 MiB locks, missing
lock_digest) and the npm os/cpu artifact coverage contract (cross-platform
native packages[], pure-JS locks, missing target-platform artifact).

Layer 2 copies the unmodified guard into an isolated temp repo root (so its
ROOT derivation resolves to the fixture dir instead of the real checkout),
symlinks the real tool-installer package, and runs the real CLI with temporary
tools.toml + manifest.toml + lock fixtures.  It covers main()'s locked-platform
logic: a tool locked on only ONE platform while the others keep an old manager
must PASS and print an info line (legacy progressive layout); three platforms
each with a provenance-matched lock must exit 0 without fabricating extra lock
files; a lock whose provenance does not match its platform still FAILS; and
platform-specific npm locks whose packages[] cover their own os/cpu combination
pass while a lock missing the target artifact is rejected.  Universal locks
(platforms[] + resolution=universal) are covered in Layer 1: they must list the
target platform and still pass the npm os/cpu artifact coverage check.

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


# npm os/cpu identifiers for each declared platform (macos->darwin,
# aarch64->arm64, x86_64->x64).  Real package-lock v3 lists ALL optional
# native artifacts in packages[], one record per (os, cpu) combination.
NPM_COMBOS = {
    ("linux", "x86_64"): ("linux", "x64"),
    ("linux", "aarch64"): ("linux", "arm64"),
    ("macos", "aarch64"): ("darwin", "arm64"),
}


def npm_native_lock(pkg: str, version: str, combos: list[tuple[str, str]],
                    provenance: dict) -> str:
    # A package-lock v3 with explicit os/cpu-tagged optional native packages.
    # Pure-JS locks are built with npm_lock (no os/cpu records) instead.
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
    for index, (os_name, cpu) in enumerate(combos):
        suffix = f"{os_name}-{cpu}-{index}"
        name = f"{pkg}-{suffix}"
        data["packages"]["node_modules/" + name] = {
            "version": version,
            "resolved": f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz",
            "integrity": _npm_integrity(),
            "optional": True,
            "os": [os_name],
            "cpu": [cpu],
        }
    data["x-tool-lock-generator"] = provenance
    return json.dumps(data, indent=2) + "\n"


def python_any_wheel_lock(pkg: str, version: str, provenance: dict) -> str:
    # Hashed requirements lock with platform-independent (py3-none-any) hashes.
    # The validator forbids markers/extras/URLs; the wheel tag is not part of
    # the restricted grammar, so an any-wheel-style lock is a normal hashed line.
    head = "# generator: " + json.dumps(provenance) + "\n"
    return head + f"{pkg}=={version} --hash=sha256:{'0' * 64} --hash=sha256:{'1' * 64}\n"


# --------------------------------------------------------------------------- #
# Layer 1: AST-extracted pure function
# --------------------------------------------------------------------------- #
class Environment:
    """Minimal stub for the guard's Environment (os / arch only)."""

    def __init__(self, os: str, arch: str):
        self.os = os
        self.arch = arch


def load_embedded():
    """Compile ONLY the pure lock_provenance + npm_target_coverage FunctionDefs.

    Both functions are exec'd into one namespace so lock_provenance can call
    npm_target_coverage.  The online script, its imports, config reads and
    dispatch loop are never executed.  json / re / Path are pure stdlib;
    Environment is an offline stub.  No tool_installer imports, no network.
    """
    script = GUARD.read_text(encoding="utf-8")
    source = script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    wanted = {"lock_provenance", "npm_target_coverage"}
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {n.name for n in nodes} != wanted:
        raise AssertionError("embedded pure functions not found: "
                             + str(wanted - {n.name for n in nodes}))
    namespace = {"json": json, "re": re, "Path": Path, "Environment": Environment}
    exec(compile(ast.Module(body=nodes, type_ignores=[]),
                 "<embedded pure functions>", "exec"), namespace)
    return namespace


def load_lock_provenance():
    return load_embedded()["lock_provenance"]


def load_npm_target_coverage():
    return load_embedded()["npm_target_coverage"]


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

    def test_universal_provenance_covers_each_declared_platform(self):
        names = [f"{os_name}/{arch}" for os_name, arch in PLATFORMS]
        for manager, build in (("npm-locked", npm_lock),
                               ("python-locked", python_lock)):
            with self.subTest(manager=manager):
                text = build("t", "1.0.0", {"generator": "/usr/bin/x",
                                            "version": "1.0",
                                            "platforms": names,
                                            "resolution": "universal"})
                for os_name, arch in PLATFORMS:
                    self.assertIsNone(self.lock_provenance(
                        self._strategy(text, manager=manager),
                        Environment(os_name, arch)))

    def test_universal_provenance_missing_target_rejected(self):
        prov = {"generator": "/usr/bin/x", "version": "1.0",
                "platforms": ["linux/x86_64", "linux/aarch64"],
                "resolution": "universal"}
        text = npm_lock("t", "1.0.0", prov)
        self.assertIsNone(self.lock_provenance(self._strategy(text), self.env))
        result = self.lock_provenance(
            self._strategy(text), Environment("macos", "aarch64"))
        self.assertIn("未声明覆盖该平台", result)
        self.assertIn("macos/aarch64", result)

    def test_universal_provenance_requires_resolution_and_platform_list(self):
        base = {"generator": "/usr/bin/x", "version": "1.0",
                "platforms": ["linux/x86_64"]}
        for prov, needle in (
            (base, "resolution=universal"),
            (dict(base, resolution="universal", platforms="linux/x86_64"), "platforms 元数据非法"),
            (dict(base, resolution="universal", platforms=[]), "platforms 元数据非法"),
            (dict(base, resolution="universal", platforms=[1]), "platforms 元数据非法"),
        ):
            with self.subTest(prov=prov):
                text = npm_lock("t", "1.0.0", prov)
                self.assertIn(needle, self.lock_provenance(
                    self._strategy(text), self.env))

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
# Layer 1b: npm os/cpu artifact coverage (pure function, offline)
# --------------------------------------------------------------------------- #
class NpmCoverageTests(unittest.TestCase):
    def setUp(self):
        self.coverage = load_npm_target_coverage()
        self.lock_provenance = load_lock_provenance()
        self.tmp = tempfile.TemporaryDirectory(prefix="mp-cov-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def _env(self, os_name, arch):
        return Environment(os_name, arch)

    def _data(self, combos):
        # Build a packages dict with os/cpu-tagged native records, mirroring
        # package-lock v3 optionalDependencies artifacts.
        packages = {"": {"dependencies": {"t": "1.0.0"}},
                    "node_modules/t": {"version": "1.0.0"}}
        for index, (os_name, cpu) in enumerate(combos):
            name = f"t-native-{os_name}-{cpu}-{index}"
            packages["node_modules/" + name] = {
                "os": [os_name], "cpu": [cpu], "optional": True}
        return {"packages": packages}

    def test_cross_platform_lock_covers_all_three(self):
        # A single lock listing native artifacts for every declared platform
        # must report coverage for each platform independently.
        combos = [NPM_COMBOS[p] for p in PLATFORMS] + [("win32", "x64")]
        data = self._data(combos)
        for os_name, arch in PLATFORMS:
            with self.subTest(platform=f"{os_name}/{arch}"):
                self.assertIsNone(self.coverage(data, self._env(os_name, arch)))

    def test_pure_js_lock_covers_all_three(self):
        # No os/cpu records at all -> platform-independent, passes everywhere.
        data = {"packages": {"": {"dependencies": {"t": "1.0.0"}},
                             "node_modules/t": {"version": "1.0.0"}}}
        for os_name, arch in PLATFORMS:
            with self.subTest(platform=f"{os_name}/{arch}"):
                self.assertIsNone(self.coverage(data, self._env(os_name, arch)))

    def test_missing_target_artifact_rejected(self):
        # Native records exist but only for darwin/arm64 -> linux/x86_64 fails.
        data = self._data([("darwin", "arm64")])
        result = self.coverage(data, self._env("linux", "x86_64"))
        self.assertIsNotNone(result)
        self.assertIn("linux/x64", result)
        self.assertIn("packages[]", result)
        # darwin/arm64 target is present, so macos/aarch64 itself passes.
        self.assertIsNone(self.coverage(data, self._env("macos", "aarch64")))

    def test_missing_packages_rejected(self):
        self.assertIn("缺少 packages[]", self.coverage({}, self._env("linux", "x86_64")))

    def test_os_only_record_is_cpu_agnostic(self):
        # os=["linux"], cpu omitted -> covers both linux cpu targets.
        packages = {"": {}, "node_modules/native": {"os": ["linux"]}}
        data = {"packages": packages}
        for arch in ("x86_64", "aarch64"):
            self.assertIsNone(self.coverage(data, self._env("linux", arch)))

    def test_lock_provenance_wires_coverage(self):
        # End-to-end through lock_provenance: provenance matches, but the lock
        # lacks the target native artifact -> rejected with a coverage error.
        text = npm_native_lock("t", "1.0.0", [("darwin", "arm64")],
                               _provenance("linux", "x86_64", "npm"))
        (self.root / "l.json").write_text(text)
        strategy = SimpleNamespace(
            lock_root=self.root, lock_digest="digest",
            fields={"lock": "l.json"}, manager="npm-locked")
        result = self.lock_provenance(strategy, self._env("linux", "x86_64"))
        self.assertIsNotNone(result)
        self.assertIn("平台工件", result)
        self.assertIn("linux/x64", result)

    def test_lock_provenance_native_covered_passes(self):
        text = npm_native_lock("t", "1.0.0",
                               [("linux", "x64"), ("linux", "arm64"), ("darwin", "arm64")],
                               _provenance("linux", "x86_64", "npm"))
        (self.root / "l.json").write_text(text)
        strategy = SimpleNamespace(
            lock_root=self.root, lock_digest="digest",
            fields={"lock": "l.json"}, manager="npm-locked")
        self.assertIsNone(self.lock_provenance(strategy, self._env("linux", "x86_64")))


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


def _old_manager_block(pkg: str, manager: str = "npm-global") -> str:
    # Legacy manager used during the platform-progressive locked migration.
    return f'''manager = "{manager}"
pkg = "{pkg}"'''


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

    def test_single_platform_locked_with_old_managers_passes_with_info(self):
        """Progressive migration: locked on ONE platform, old managers elsewhere.

        The guard must NOT demand three-platform locked coverage.  It should
        exit 0, print an info line naming the two platforms still on the old
        manager, and still validate the single locked platform strictly.
        """
        manifest = "\n".join([
            "[npmtool.linux.x86_64]",
            _locked_block("npm-locked", "npmtool", "locks/linux-x86_64.json"),
            "",
            "[npmtool.linux.aarch64]",
            _old_manager_block("npmtool"),
            "",
            "[npmtool.macos.aarch64]",
            _old_manager_block("npmtool"),
            "",
        ])
        locks = {
            "locks/linux-x86_64.json": npm_lock(
                "npmtool", "1.2.3", _provenance("linux", "x86_64", "npm")),
        }
        _populate(self.root, _tools_toml([("npmtool", "1.2.3")]), manifest, locks)
        before = _snapshot(self.root)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn("仍使用旧 manager", combined)
        self.assertIn("linux/aarch64, macos/aarch64", combined)
        self.assertNotIn("缺少平台", combined)
        self.assertNotIn("平台工件", combined)
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
        self.assertIn("locked 条目逐平台校验全平台覆盖", result.stdout)
        self.assertNotIn("缺少平台", result.stdout + result.stderr)
        self.assertEqual(before, _snapshot(self.root),
                         "guard must not create or modify fixture files")
        produced = [p for p in before if p.startswith("locks/")]
        self.assertEqual(len(produced), 6, produced)
        self.assertEqual(sorted(produced), sorted(locks.keys()))
        self.assertFalse(any("macos-x86_64" in p for p in produced),
                         "no fabricated macos/x86_64 lock")

    def _three_platform_locks(self, builder):
        # Build one provenance-matched lock per platform.  Each lock lists the
        # os/cpu artifact for EVERY platform (as a real host-generated lock
        # would), but provenance is strictly the platform that generated it.
        manifest_parts, locks = [], {}
        for os_name, arch in PLATFORMS:
            tag = f"{os_name}-{arch}"
            rel = f"locks/npmtool/{tag}.json"
            manifest_parts += [
                f"[npmtool.{os_name}.{arch}]",
                _locked_block("npm-locked", "npmtool", rel),
                "",
            ]
            locks[rel] = builder(os_name, arch)
        return "\n".join(manifest_parts), locks

    def test_cross_platform_npm_native_locks_three_platforms_pass(self):
        # Three separate provenance-matched npm locks, each carrying native
        # packages[] for all three (os,cpu) combos -> all three platforms pass.
        combos = [NPM_COMBOS[p] for p in PLATFORMS]

        def build(os_name, arch):
            return npm_native_lock("npmtool", "1.2.3", combos,
                                   _provenance(os_name, arch, "npm"))

        manifest, locks = self._three_platform_locks(build)
        tools = _tools_toml([("npmtool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        before = _snapshot(self.root)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn("平台工件", combined)
        self.assertNotIn("缺少平台", combined)
        self.assertEqual(before, _snapshot(self.root),
                         "guard must not create or modify fixture files")

    def test_pure_js_npm_locks_three_platforms_pass(self):
        # Pure-JS npm locks (no os/cpu records) are platform-independent and
        # provenance-matched per platform -> all three platforms pass.
        def build(os_name, arch):
            return npm_lock("npmtool", "1.2.3", _provenance(os_name, arch, "npm"))
        manifest, locks = self._three_platform_locks(build)
        tools = _tools_toml([("npmtool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn("平台工件", combined)
        self.assertNotIn("缺少平台", combined)

    def test_python_any_wheel_locks_three_platforms_pass(self):
        # Three provenance-matched Python locks with platform-independent
        # (py3-none-any style) hashes -> all three platforms pass.  Confirms no
        # over-strict wheel-tag rejection was introduced.
        manifest_parts, locks = [], {}
        for os_name, arch in PLATFORMS:
            tag = f"{os_name}-{arch}"
            rel = f"locks/pytool/{tag}.txt"
            manifest_parts += [
                f"[pytool.{os_name}.{arch}]",
                _locked_block("python-locked", "pytool", rel),
                "",
            ]
            locks[rel] = python_any_wheel_lock(
                "pytool", "1.2.3", _provenance(os_name, arch, "uv"))
        manifest = "\n".join(manifest_parts)
        tools = _tools_toml([("pytool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn("缺少平台", combined)

    def test_missing_target_platform_artifact_rejected(self):
        # A provenance-matched npm lock whose packages[] only has darwin/arm64
        # native artifacts must fail on linux/x86_64 with an item-level error
        # naming the tool@version and the missing linux/x64 combination.
        combos_by_platform = {
            ("linux", "x86_64"): [("darwin", "arm64")],  # missing linux/x64
            ("linux", "aarch64"): [NPM_COMBOS[("linux", "aarch64")]],
            ("macos", "aarch64"): [NPM_COMBOS[("macos", "aarch64")]],
        }

        def build(os_name, arch):
            return npm_native_lock("npmtool", "1.2.3",
                                   combos_by_platform[(os_name, arch)],
                                   _provenance(os_name, arch, "npm"))

        manifest, locks = self._three_platform_locks(build)
        tools = _tools_toml([("npmtool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("npmtool@1.2.3 的 lock", combined)
        self.assertIn("linux/x64", combined)
        self.assertIn("平台工件", combined)

    def test_one_platform_wrong_provenance_fails(self):
        # Progressive migration does NOT weaken provenance equality: a lock
        # generated for a different OS/arch still fails on every platform.
        def build(os_name, arch):
            provenance = (_provenance("macos", "aarch64", "npm")
                         if (os_name, arch) == ("linux", "x86_64")
                         else _provenance(os_name, arch, "npm"))
            return npm_lock("npmtool", "1.2.3", provenance)

        manifest, locks = self._three_platform_locks(build)
        tools = _tools_toml([("npmtool", "1.2.3")])
        _populate(self.root, tools, manifest, locks)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("npmtool@1.2.3 的 lock", combined)
        self.assertIn("不能用于该平台", combined)

    def test_declared_locked_but_no_platform_adopts_is_config_error(self):
        # A locked declaration that resolves to locked on NONE of the three
        # PLATFORMS is dead configuration and must be reported.
        manifest = "\n".join([
            "[npmtool.linux.x86_64]",
            _old_manager_block("npmtool"),
            "",
            "[npmtool.linux.aarch64]",
            _old_manager_block("npmtool"),
            "",
            "[npmtool.macos.aarch64]",
            _old_manager_block("npmtool"),
            "",
            # Locked declared only on an unsupported platform.
            "[npmtool.macos.x86_64]",
            _locked_block("npm-locked", "npmtool", "locks/unused.json"),
            "",
        ])
        locks = {
            "locks/unused.json": npm_lock(
                "npmtool", "1.2.3", _provenance("macos", "x86_64", "npm")),
        }
        _populate(self.root, _tools_toml([("npmtool", "1.2.3")]), manifest, locks)
        result = run_guard(self.root)
        combined = result.stdout + "\n" + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("没有任何 PLATFORMS 平台采用", combined)
        self.assertIn("配置错误", combined)


if __name__ == "__main__":
    unittest.main()
