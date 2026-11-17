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

from ..errors import AuthorizationRequired, ConfigError, InstallationError, StrategyError
from ..hash_lock import validate_npm_lock, validate_python_lock
from .base import CheckResult, CommandManager


def read_lock(root, fields, version, manager):
    try:
        name = fields.get("bin")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise StrategyError("Locked manager bin must be one safe filename")
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
        name = item.strategy.fields["bin"]
        home = Path.home().resolve()
        store = home / ".local/share/tool-installer/locked" / item.strategy.manager / name
        dest = home / ".local/bin" / name
        # Do not follow user-controlled directory aliases for publication or storage.
        for path in (store, dest.parent):
            if path.resolve() != path:
                raise AuthorizationRequired("Locked manager path contains a symlink")
        return store, dest

    def _identity(self, item):
        return {"format": 1, "manager": item.strategy.manager,
                "tool": item.tool.reference.name, "pkg": item.strategy.fields["pkg"],
                "bin": item.strategy.fields["bin"], "os": item.environment.os,
                "arch": item.environment.arch, "manifest": str(item.strategy.lock_root),
                "python": [sys.executable, list(sys.version_info[:3])]
                if item.strategy.manager == "python-locked" else None}

    def _owned(self, item, store, dest):
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
            if receipt["identity"] != self._identity(item) or receipt["target"] != str(target):
                raise ValueError()
            if not isinstance(receipt["version"], str) or not target.is_file() or not os.access(target, os.X_OK):
                raise ValueError()
            if not re.fullmatch("[0-9a-f]{64}", receipt["digest"]):
                raise ValueError()
            saved = generation / ("package-lock.json" if item.strategy.manager == "npm-locked" else "requirements.txt")
            if saved.is_symlink() or not stat.S_ISREG(saved.stat().st_mode) or saved.stat().st_size > 8 * 1024 * 1024:
                raise ValueError()
            validator = validate_npm_lock if item.strategy.manager == "npm-locked" else validate_python_lock
            if validator(saved.read_text(encoding="utf-8"), item.strategy.fields["pkg"], receipt["version"]) != receipt["digest"]:
                raise ValueError()
            return receipt
        except (OSError, ValueError, KeyError, TypeError, IndexError, ConfigError):
            raise AuthorizationRequired("Existing bin is not a verified owned generation") from None

    def check(self, item):
        self._lock(item)
        store, dest = self._paths(item)
        receipt = self._owned(item, store, dest)
        if receipt and receipt["digest"] == item.strategy.lock_digest and receipt["version"] == item.tool.reference.version:
            return CheckResult.SATISFIED
        return CheckResult.NOT_SATISFIED

    def _root_entry(self, item, generation, candidate):
        fields = item.strategy.fields
        if item.strategy.manager == "npm-locked":
            package = generation / "node_modules" / fields["pkg"]
            data = json.loads((package / "package.json").read_text())
            if data.get("name") != fields["pkg"] or data.get("version") != item.tool.reference.version:
                raise InstallationError("Installed npm root identity mismatch")
            bins = data.get("bin", {})
            if isinstance(bins, str):
                bins = {fields["pkg"].split("/")[-1]: bins}
            relative = bins.get(fields["bin"]) if isinstance(bins, dict) else None
            if not isinstance(relative, str) or (package / relative).resolve() != candidate.resolve():
                raise InstallationError("Bin is not declared by npm root")
        else:
            normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
            matches = []
            for metadata in generation.glob("lib/python*/site-packages/*.dist-info/METADATA"):
                from email.parser import Parser
                data = Parser().parsestr(metadata.read_text())
                entries = configparser.ConfigParser(interpolation=None)
                entries.optionxform = str
                entries.read(metadata.parent / "entry_points.txt")
                declares = entries.has_option("console_scripts", fields["bin"])
                if normalize(data.get("Name", "")) != normalize(fields["pkg"]) and declares:
                    # Conservative support: no dependency may compete for the published bin.
                    raise InstallationError("Python dependency declares the same console script as root")
                if normalize(data.get("Name", "")) == normalize(fields["pkg"]):
                    if data.get("Version") != item.tool.reference.version:
                        raise InstallationError("Installed Python root version mismatch")
                    matches.append(declares)
            if matches != [True]:
                raise InstallationError("Bin is not declared by Python root")

    def install_command(self, item):
        return [item.strategy.manager, "<isolated-generation>"]

    def install(self, item):
        text = self._lock(item)
        store, dest = self._paths(item)
        previous = self._owned(item, store, dest)
        if previous and previous["digest"] == item.strategy.lock_digest and previous["version"] == item.tool.reference.version:
            return
        store.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        generation = Path(tempfile.mkdtemp(prefix="gen-", dir=store)).resolve()
        created = generation
        published = False
        temporary = None
        try:
            # Allowlist environment: inherited npm/uv/pip configuration cannot override policy.
            env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(generation),
                   "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never",
                   "PYTHONNOUSERSITE": "1", "NPM_CONFIG_USERCONFIG": os.devnull,
                   "NPM_CONFIG_GLOBALCONFIG": os.devnull}
            if item.strategy.manager == "npm-locked":
                # Distinct empty files avoid npm treating user/global config as one file.
                for kind in ("user", "global"):
                    config = generation / (kind + ".npmrc")
                    config.write_text("")
                    env["NPM_CONFIG_" + kind.upper() + "CONFIG"] = str(config)
                (generation / "package-lock.json").write_text(text)
                (generation / "package.json").write_text(json.dumps({"private": True, "dependencies": {item.strategy.fields["pkg"]: item.tool.reference.version}}))
                commands = [["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]]
                candidate = generation / "node_modules/.bin" / item.strategy.fields["bin"]
            else:
                (generation / "requirements.txt").write_text(text)
                commands = [[sys.executable, "-I", "-m", "venv", "--without-pip", str(generation)],
                            ["uv", "--no-config", "pip", "install", "--python", str(generation / "bin/python"),
                             "--require-hashes", "--only-binary", ":all:", "-r", str(generation / "requirements.txt")]]
                candidate = generation / "bin" / item.strategy.fields["bin"]
            for command in commands:
                result = self.runner.run(command, check=False, cwd=str(generation), env=env)
                if result.returncode:
                    raise InstallationError("Isolated locked install failed")
            self._root_entry(item, generation, candidate)
            target = candidate.resolve(strict=True)
            target.relative_to(generation)
            if item.strategy.manager == "npm-locked":
                target.relative_to(generation / "node_modules" / item.strategy.fields["pkg"])
            if not target.is_file() or not os.access(target, os.X_OK):
                raise InstallationError("Locked package did not provide an executable bin")
            receipt = {"identity": self._identity(item), "digest": item.strategy.lock_digest,
                       "version": item.tool.reference.version, "target": str(target)}
            (generation / "receipt.json").write_text(json.dumps(receipt))
            # Revalidate before publishing; never migrate an outside target, even with force.
            self._lock(item)
            if self._owned(item, store, dest) != previous:
                raise AuthorizationRequired("Bin changed while installing")
            descriptor, name = tempfile.mkstemp(prefix=".tool-installer-", dir=dest.parent)
            os.close(descriptor)
            temporary = Path(name)
            temporary.unlink()
            temporary.symlink_to(target)
            if previous is None:
                # link(2) creates the symlink inode without replacing an existing destination.
                os.link(temporary, dest, follow_symlinks=False)
                temporary.unlink()
            else:
                os.replace(temporary, dest)
            published = True
        except (OSError, ValueError) as exc:
            raise InstallationError("Locked installation failed: " + str(exc)) from exc
        finally:
            if temporary is not None and os.path.lexists(temporary):
                temporary.unlink()
            if not published:
                # Cleanup only the exact absolute directory created by this attempt.
                if created.is_absolute() and created.parent == store and created.resolve() == created and not created.is_symlink():
                    shutil.rmtree(created)


class NpmLockedManager(LockedManager):
    pass


class PythonLockedManager(LockedManager):
    pass
