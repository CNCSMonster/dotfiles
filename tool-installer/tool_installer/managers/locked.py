"""Restricted opt-in installs. Receipts are local ownership evidence, not signatures.

No protection is claimed against hostile concurrent same-user filesystem mutation.
Only existing host runtimes are used; package entry points are never probed.
"""
from __future__ import annotations

import json
import configparser
import stat
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from ..environment import refresh_path
from ..errors import AuthorizationRequired, ConfigError, InstallationError, StrategyError
from ..hash_lock import validate_npm_lock, validate_python_lock
from .base import CheckResult, CommandManager

_SAFE_BIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)


def declared_bins(fields):
    """Effective publication names for a locked strategy.

    bins (a non-empty array of unique safe filenames) wins over bin when both
    are present. The legacy single bin is normalized to a one-element list so
    install/check share one code path.
    """
    if "bins" in fields:
        bins = fields["bins"]
        if (not isinstance(bins, list) or not bins
                or any(not isinstance(b, str) or not _SAFE_BIN.fullmatch(b) for b in bins)
                or len(set(bins)) != len(bins)):
            raise StrategyError("Locked manager bins must be a non-empty array of unique safe filenames")
        return list(bins)
    name = fields.get("bin")
    if not isinstance(name, str) or not _SAFE_BIN.fullmatch(name):
        raise StrategyError("Locked manager bin must be one safe filename")
    return [name]


def read_lock(root, fields, version, manager):
    try:
        declared_bins(fields)
        raw = fields["lock"]
        path = Path(raw)
        if path.is_absolute() or any(p in {"", ".", ".."} for p in raw.split("/")) or "\\" in raw:
            raise StrategyError("Lock must be a safe manifest-relative path")
        root = Path(root).resolve(strict=True)
        path = (root / path).resolve(strict=True)
        path.relative_to(root)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
            raise StrategyError("Lock must be a regular file no larger than 8 MiB")
        text = path.read_text(encoding="utf-8")
        validator = validate_npm_lock if manager == "npm-locked" else validate_python_lock
        return text, validator(text, fields["pkg"], version)
    except (OSError, ValueError, TypeError, ConfigError) as exc:
        raise StrategyError("Invalid locked-manager lock: " + str(exc)) from exc


class LockedManager(CommandManager):
    def _lock(self, item):
        if item.strategy.lock_root is None or not item.strategy.lock_digest:
            raise InstallationError("Locked manager requires a validated plan")
        try:
            text, digest = read_lock(item.strategy.lock_root, item.strategy.fields,
                                     item.tool.reference.version, item.strategy.manager)
        except StrategyError as exc:
            raise InstallationError(str(exc)) from exc
        if digest != item.strategy.lock_digest:
            raise InstallationError("Lock changed since planning")
        return text

    def _paths(self, item):
        bins = declared_bins(item.strategy.fields)
        home = Path.home().resolve()
        # The store remains keyed by the logical bin field so single-bin layouts
        # are unchanged; every declared bin shares one store (and one generation).
        store_key = item.strategy.fields.get("bin") or bins[0]
        store = home / ".local/share/tool-installer/locked" / item.strategy.manager / store_key
        bindir = home / ".local/bin"
        dests = {name: bindir / name for name in bins}
        # Do not follow user-controlled directory aliases for publication or storage.
        for path in (store, bindir):
            if path.resolve() != path:
                raise AuthorizationRequired("Locked manager path contains a symlink")
        return store, dests

    def _identity(self, item):
        return {"format": 1, "manager": item.strategy.manager,
                "tool": item.tool.reference.name, "pkg": item.strategy.fields["pkg"],
                "bin": item.strategy.fields.get("bin") or declared_bins(item.strategy.fields)[0],
                "bins": declared_bins(item.strategy.fields),
                "os": item.environment.os,
                "arch": item.environment.arch, "manifest": str(item.strategy.lock_root),
                "python": [sys.executable, list(sys.version_info[:3])]
                if item.strategy.manager == "python-locked" else None}

    def _owned_one(self, item, store, dest, name):
        """Verify one published bin against its owning generation.

        Returns (receipt, generation, target) or None when dest is absent. A
        receipt that omits this name is incomplete, not foreign: identity,
        digest and saved lock are still verified, and _receipt_complete decides
        satisfaction. Any other anomaly fails closed.
        """
        if not os.path.lexists(dest):
            return None
        try:
            if not dest.is_symlink():
                raise ValueError()
            target = Path(os.readlink(dest))
            if not target.is_absolute() or target.resolve(strict=True) != target:
                raise ValueError()
            relative = target.relative_to(store)
            generation = store / relative.parts[0]
            if generation.parent != store or not generation.name.startswith("gen-"):
                raise ValueError()
            receipt_path = generation / "receipt.json"
            if receipt_path.is_symlink() or not stat.S_ISREG(receipt_path.stat().st_mode) or receipt_path.stat().st_size > 65536:
                raise ValueError()
            receipt = json.loads(receipt_path.read_text())
            if receipt["identity"] != self._identity(item):
                raise ValueError()
            if not isinstance(receipt["version"], str) or not target.is_file() or not os.access(target, os.X_OK):
                raise ValueError()
            if not re.fullmatch("[0-9a-f]{64}", receipt["digest"]):
                raise ValueError()
            if not isinstance(receipt["targets"], dict):
                raise ValueError()
            saved = generation / ("package-lock.json" if item.strategy.manager == "npm-locked" else "requirements.txt")
            if saved.is_symlink() or not stat.S_ISREG(saved.stat().st_mode) or saved.stat().st_size > 8 * 1024 * 1024:
                raise ValueError()
            validator = validate_npm_lock if item.strategy.manager == "npm-locked" else validate_python_lock
            if validator(saved.read_text(encoding="utf-8"), item.strategy.fields["pkg"], receipt["version"]) != receipt["digest"]:
                raise ValueError()
            return receipt, generation, target
        except (OSError, ValueError, KeyError, TypeError, IndexError, ConfigError):
            raise AuthorizationRequired("Existing bin is not a verified owned generation") from None

    def _owned(self, item, store, dests):
        """Return None (nothing published) or the single shared receipt.

        All bins must be absent, or all present, verified, and pointing into the
        same generation with the same receipt. Anything else fails closed.
        """
        receipts, generations = [], []
        for name, dest in dests.items():
            result = self._owned_one(item, store, dest, name)
            if result is None:
                receipts.append(None)
                continue
            receipt, generation, target = result
            targets = receipt["targets"]
            if name in targets and targets[name] != str(target):
                # A bin whose recorded target differs from its live symlink is
                # foreign/tampered, even when force is requested.
                raise AuthorizationRequired("Existing bin is not a verified owned generation")
            receipts.append(receipt)
            generations.append(generation)
        present = [r for r in receipts if r is not None]
        if not present:
            return None
        if len(present) != len(dests):
            raise AuthorizationRequired("Locked bins are partially published")
        if any(g != generations[0] for g in generations) or any(r != present[0] for r in present):
            raise AuthorizationRequired("Locked bins do not share one verified generation")
        return present[0]

    def _receipt_complete(self, item, receipt, dests):
        """A receipt is complete only when it records exactly the declared bins
        with absolute targets. A missing (or extra) bin is NOT_SATISFIED, never
        a false positive."""
        targets = receipt.get("targets")
        if not isinstance(targets, dict) or set(targets) != set(dests):
            return False
        return all(isinstance(value, str) and Path(value).is_absolute() for value in targets.values())

    def check(self, item):
        self._lock(item)
        store, dests = self._paths(item)
        receipt = self._owned(item, store, dests)
        if (receipt is not None and self._receipt_complete(item, receipt, dests)
                and receipt["digest"] == item.strategy.lock_digest
                and receipt["version"] == item.tool.reference.version):
            return CheckResult.SATISFIED
        return CheckResult.NOT_SATISFIED

    def _root_entry(self, item, generation, candidates):
        """Verify every declared bin is a root entry of this isolated generation.

        candidates maps bin name to invocation path (npm .bin symlink / venv
        script). No package entry point is ever executed.
        """
        fields = item.strategy.fields
        bins = declared_bins(fields)
        if item.strategy.manager == "npm-locked":
            package = generation / "node_modules" / fields["pkg"]
            data = json.loads((package / "package.json").read_text())
            if data.get("name") != fields["pkg"] or data.get("version") != item.tool.reference.version:
                raise InstallationError("Installed npm root identity mismatch")
            declared = data.get("bin", {})
            if isinstance(declared, str):
                declared = {fields["pkg"].split("/")[-1]: declared}
            if not isinstance(declared, dict):
                raise InstallationError("Bin is not declared by npm root")
            for name in bins:
                relative = declared.get(name)
                if not isinstance(relative, str) or (package / relative).resolve() != candidates[name].resolve():
                    raise InstallationError("Bin is not declared by npm root")
        else:
            from email.parser import Parser
            normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
            root_count = 0
            for metadata in generation.glob("lib/python*/site-packages/*.dist-info/METADATA"):
                data = Parser().parsestr(metadata.read_text())
                entries = configparser.ConfigParser(interpolation=None)
                entries.optionxform = str
                entries.read(metadata.parent / "entry_points.txt")
                scripts = set(entries.options("console_scripts")) if entries.has_section("console_scripts") else set()
                if normalize(data.get("Name", "")) != normalize(fields["pkg"]):
                    # Conservative support: no dependency may compete for any published bin.
                    if scripts.intersection(bins):
                        raise InstallationError("Python dependency declares the same console script as root")
                    continue
                root_count += 1
                if data.get("Version") != item.tool.reference.version:
                    raise InstallationError("Installed Python root version mismatch")
                if any(name not in scripts for name in bins):
                    raise InstallationError("Bin is not declared by Python root")
            if root_count != 1:
                raise InstallationError("Bin is not declared by Python root")

    def install_command(self, item):
        return [item.strategy.manager, "<isolated-generation>"]

    def _python_candidates(self, env, generation):
        """Host CPython executables to try, current interpreter first.

        Locks are wheel-only, so a host newer than every published wheel cannot
        resolve them. Fall back to another already-installed CPython instead of
        downloading an interpreter or building from source; candidates come from
        uv's installed-interpreter inventory, which is read-only here.
        """
        candidates = [sys.executable]
        seen = {os.path.realpath(sys.executable)}
        try:
            result = self.runner.run(
                ["uv", "--no-config", "python", "list", "--only-installed", "--output-format", "json"],
                check=False, capture_output=True, text=True, cwd=os.getcwd(),
                env=dict(env, HOME=os.environ.get("HOME", env["HOME"]),
                         UV_CACHE_DIR=str(generation / "uv-cache")))
        except OSError:
            return candidates
        if result.returncode:
            return candidates
        try:
            entries = json.loads(result.stdout or "[]")
        except (TypeError, ValueError):
            return candidates
        found = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get("implementation") != "cpython":
                continue
            path, parts = entry.get("path"), entry.get("version_parts")
            if not isinstance(path, str) or not os.path.isabs(path) or not isinstance(parts, dict):
                continue
            try:
                version = (int(parts["major"]), int(parts["minor"]))
            except (KeyError, TypeError, ValueError):
                continue
            if version[0] != sys.version_info[0]:
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            found.append((version, real))
        for _, path in sorted(found, reverse=True):
            candidates.append(path)
        return candidates

    def _install_python(self, text, env, generation):
        tried = []
        for interpreter in self._python_candidates(env, generation):
            # A failed resolve can leave a partial environment; start clean.
            shutil.rmtree(generation)
            generation.mkdir()
            (generation / "requirements.txt").write_text(text)
            commands = [
                [interpreter, "-I", "-m", "venv", "--without-pip", str(generation)],
                ["uv", "--no-config", "pip", "install", "--python", str(generation / "bin/python"),
                 "--require-hashes", "--only-binary", ":all:", "-r", str(generation / "requirements.txt")],
            ]
            for command in commands:
                if self.runner.run(command, check=False, cwd=str(generation), env=env).returncode:
                    break
            else:
                return
            tried.append(interpreter)
        raise InstallationError(
            "Isolated locked install failed (interpreters tried: " + ", ".join(tried) + ")")

    def install(self, item):
        text = self._lock(item)
        store, dests = self._paths(item)
        previous = self._owned(item, store, dests)
        if (previous is not None and self._receipt_complete(item, previous, dests)
                and previous["digest"] == item.strategy.lock_digest
                and previous["version"] == item.tool.reference.version):
            return
        store.mkdir(parents=True, exist_ok=True)
        for dest in dests.values():
            dest.parent.mkdir(parents=True, exist_ok=True)
        generation = Path(tempfile.mkdtemp(prefix="gen-", dir=store)).resolve()
        created = generation
        temporary = {}          # bin name -> staged temporary symlink
        old_links = {}          # bin name -> previous absolute link target
        published = []          # bin names whose dest was already replaced
        success = False
        try:
            # PATH is a snapshot from process start, while mise/node and uv may
            # only be installed earlier in this same run. check() is receipt-based
            # and never shells out, so the executor's CHECK_ERROR refresh hook
            # cannot fire here; refresh before resolving npm/uv.
            refresh_path()
            # Allowlist environment: inherited npm/uv/pip configuration cannot override policy.
            env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(generation),
                   "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never",
                   "PYTHONNOUSERSITE": "1", "NPM_CONFIG_USERCONFIG": os.devnull,
                   "NPM_CONFIG_GLOBALCONFIG": os.devnull}
            bins = declared_bins(item.strategy.fields)
            if item.strategy.manager == "npm-locked":
                # Distinct empty files avoid npm treating user/global config as one file.
                for kind in ("user", "global"):
                    config = generation / (kind + ".npmrc")
                    config.write_text("")
                    env["NPM_CONFIG_" + kind.upper() + "CONFIG"] = str(config)
                (generation / "package-lock.json").write_text(text)
                (generation / "package.json").write_text(json.dumps({"private": True, "dependencies": {item.strategy.fields["pkg"]: item.tool.reference.version}}))
                result = self.runner.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                                         check=False, cwd=str(generation), env=env)
                if result.returncode:
                    raise InstallationError("Isolated locked install failed")
                candidates = {name: generation / "node_modules/.bin" / name for name in bins}
            else:
                candidates = {name: generation / "bin" / name for name in bins}
                self._install_python(text, env, generation)
            # Verify every root entry and resolve every target BEFORE any publication.
            self._root_entry(item, generation, candidates)
            targets = {}
            for name, candidate in candidates.items():
                target = candidate.resolve(strict=True)
                target.relative_to(generation)
                if item.strategy.manager == "npm-locked":
                    target.relative_to(generation / "node_modules" / item.strategy.fields["pkg"])
                if not target.is_file() or not os.access(target, os.X_OK):
                    raise InstallationError("Locked package did not provide an executable bin")
                targets[name] = str(target)
            receipt = {"identity": self._identity(item), "digest": item.strategy.lock_digest,
                       "version": item.tool.reference.version, "targets": targets}
            (generation / "receipt.json").write_text(json.dumps(receipt))
            # Revalidate before publishing; never migrate an outside target, even with force.
            self._lock(item)
            if self._owned(item, store, dests) != previous:
                raise AuthorizationRequired("Bin changed while installing")
            # Stage all symlinks first so a mid-publication failure cannot leave
            # a half-installed set of new entries.
            for name, dest in dests.items():
                descriptor, filename = tempfile.mkstemp(prefix=".tool-installer-", dir=dest.parent)
                os.close(descriptor)
                staged = Path(filename)
                staged.unlink()
                staged.symlink_to(targets[name])
                temporary[name] = staged
                if previous is not None:
                    old_links[name] = os.readlink(dest)
            for name, dest in dests.items():
                if previous is None:
                    # link(2) creates the symlink inode without replacing an existing destination.
                    os.link(temporary[name], dest, follow_symlinks=False)
                else:
                    os.replace(temporary[name], dest)
                published.append(name)
            success = True
        except (OSError, ValueError) as exc:
            raise InstallationError("Locked installation failed: " + str(exc)) from exc
        finally:
            for staged in temporary.values():
                if os.path.lexists(staged):
                    staged.unlink()
            if not success:
                # Roll back every already-published entry: remove newly created
                # links, or atomically restore the previous owned links.
                for name in published:
                    dest = dests[name]
                    if previous is None:
                        if os.path.lexists(dest):
                            dest.unlink()
                    else:
                        descriptor, filename = tempfile.mkstemp(prefix=".tool-installer-", dir=dest.parent)
                        os.close(descriptor)
                        restored = Path(filename)
                        restored.unlink()
                        restored.symlink_to(old_links[name])
                        os.replace(restored, dest)
                # Cleanup only the exact absolute directory created by this attempt.
                if created.is_absolute() and created.parent == store and created.resolve() == created and not created.is_symlink():
                    shutil.rmtree(created)


class NpmLockedManager(LockedManager):
    pass


class PythonLockedManager(LockedManager):
    pass
