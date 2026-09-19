"""Command-based package managers with SPEC-aligned checks."""

from __future__ import annotations

import json
import re
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from ..errors import InstallationError
from ..github_token import detect_github_token
from ..models import PlanItem
from .base import CheckResult, CommandManager, CommandRunner


def _selector(item: PlanItem) -> str:
    return item.tool.reference.version


def _v1_eq(a: str, b: str) -> bool:
    """v1 version equality: strip one leading v/V, then exact match."""
    def norm(v: str) -> str:
        if v and v[0] in ("v", "V"):
            return v[1:]
        return v
    return norm(a) == norm(b)


class AptManager(CommandManager):
    """APT package manager.

    Check: uses dpkg-query for installed version, apt-cache policy for candidate.
    Needs root privileges for install.

    Mirrors dotfiles setup.sh sudo_run() behavior:
    - Uses sudo when not root (password prompt in interactive terminal)
    - Runs apt-get install interactively (no DEBIAN_FRONTEND=noninteractive)
    """

    needs_privilege = True

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["dpkg-query", "-W", "-f=${Version}", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            # Package not installed
            return CheckResult.NOT_SATISFIED

        installed_version = result.stdout.strip()
        if not installed_version:
            return CheckResult.CHECK_ERROR

        requested = _selector(item)
        if requested == "latest":
            # Resolve latest candidate from apt-cache
            try:
                cand = self._get_apt_candidate(pkg)
                if cand is None:
                    return CheckResult.CHECK_ERROR
                return CheckResult.SATISFIED if _v1_eq(installed_version, cand) else CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR
        else:
            return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _get_apt_candidate(self, pkg: str) -> Optional[str]:
        """Get the candidate version from apt-cache policy."""
        try:
            result = self.runner.run(
                ["apt-cache", "policy", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        # Parse "Candidate: X.Y.Z" line
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Candidate:"):
                candidate = stripped.split(":", 1)[1].strip()
                if candidate and candidate != "(none)":
                    return candidate
                return None
        return None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        """Build apt install command.

        Mirrors setup.sh: sudo_run apt-get install -y <pkg>
        - Uses 'apt-get' (not 'apt') for scripting compatibility
        - Uses '-y' to auto-confirm (since we already prompted for sudo password)
        - Does NOT set DEBIAN_FRONTEND=noninteractive
          (respects user's apt configuration for any remaining interactive prompts)
        """
        pkg = item.strategy.fields["pkg"]
        if _selector(item) != "latest":
            pkg = f"{pkg}={_selector(item)}"
        return ["apt-get", "install", "-y", pkg]


class BrewManager(CommandManager):
    """Homebrew formula manager.

    Check: uses brew info/outdated metadata. Only supports latest.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["brew", "info", "--json=v2", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Find the formula in the output
        formulas = data.get("formulae", [])
        formula = None
        for f in formulas:
            if f.get("name") == pkg:
                formula = f
                break
        if formula is None:
            return CheckResult.CHECK_ERROR

        installed = formula.get("installed")
        if not installed:
            return CheckResult.NOT_SATISFIED

        # Check if outdated
        installed_version = installed[0].get("installed_version", "") if installed else ""
        latest_version = formula.get("versions", {}).get("stable", "")

        if not installed_version or not latest_version:
            return CheckResult.CHECK_ERROR

        return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["brew", "install", item.strategy.fields["pkg"]]


class BrewCaskManager(CommandManager):
    """Homebrew cask manager.

    Check: uses brew info --cask. Only supports latest.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["brew", "info", "--json=v2", "--cask", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        casks = data.get("casks", [])
        cask = None
        for c in casks:
            if c.get("token") == pkg:
                cask = c
                break
        if cask is None:
            return CheckResult.CHECK_ERROR

        installed = cask.get("installed")
        if not installed:
            return CheckResult.NOT_SATISFIED

        installed_version = installed[0] if installed else ""
        latest_version = cask.get("version", "")

        if not installed_version or not latest_version:
            return CheckResult.CHECK_ERROR

        return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["brew", "install", "--cask", item.strategy.fields["pkg"]]


class CargoBinstallManager(CommandManager):
    """Cargo-binstall manager.

    Non-check-capable in v1. Always installs when reached.
    """

    def check(self, item: PlanItem) -> CheckResult:
        return CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        command = ["cargo", "binstall", "-y", item.strategy.fields["pkg"]]
        if _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        return command


class CargoInstallManager(CommandManager):
    """Cargo install manager.

    Check: uses cargo install --list for tracked packages.

    When the opt-in ``binstall_first`` strategy field is true for a
    registry install, installation first tries cargo-binstall without its
    compile strategy and falls back to the normal cargo install command on
    any binstall/bootstrap failure.
    """

    _BINSTALL_RELEASE_BASE = (
        "https://github.com/cargo-bins/cargo-binstall/releases/latest/download"
    )
    _BINSTALL_TARGETS = {
        ("linux", "x86_64"): "x86_64-unknown-linux-musl",
        ("linux", "aarch64"): "aarch64-unknown-linux-musl",
        ("macos", "x86_64"): "x86_64-apple-darwin",
        ("macos", "aarch64"): "aarch64-apple-darwin",
    }

    def check(self, item: PlanItem) -> CheckResult:
        """Check if the tool is installed by verifying binary existence and version.

        Instead of relying on ``cargo install --list`` (which only tracks tools
        installed via ``cargo install``, not ``cargo binstall``), we:
        1. Check if the binary exists in ``~/.cargo/bin/`` or ``~/.local/bin/``
        2. Run ``<binary> --version`` to get the installed version
        3. Compare with the requested version

        Binary name resolution follows a deterministic rule:
        - If ``bin`` field is declared in manifest → use it
        - Otherwise → ``pkg.replace("-", "_")`` (Rust default convention)
        """
        fields = item.strategy.fields
        pkg = fields["pkg"]
        requested = _selector(item)

        # Resolve binary name: manifest `bin` field → fallback to Rust convention
        binary_name = fields.get("bin", pkg.replace("-", "_"))

        # Check if binary exists in cargo bin directories
        bin_path = None
        for bin_dir in self._cargo_bin_dirs():
            candidate = bin_dir / binary_name
            if candidate.is_file():
                bin_path = candidate
                break

        if bin_path is None:
            return CheckResult.NOT_SATISFIED

        # Binary exists, try to get version via --version
        try:
            result = self.runner.run(
                [str(bin_path), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            # Binary exists but --version failed (unusual), fallback to cargo install --list
            return self._fallback_check_via_cargo_list(item, pkg, requested, fields)

        installed_version = self._parse_binary_version(result.stdout)
        if installed_version is None:
            # --version succeeded but couldn't parse version, fallback
            return self._fallback_check_via_cargo_list(item, pkg, requested, fields)

        # Version comparison
        if fields.get("git"):
            tag = fields.get("tag")
            if tag is not None:
                return CheckResult.SATISFIED if _v1_eq(installed_version, tag) else CheckResult.NOT_SATISFIED
            if requested == "latest":
                return CheckResult.SATISFIED
            return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg)
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _fallback_check_via_cargo_list(self, item: PlanItem, pkg: str, requested: str, fields: dict) -> CheckResult:
        """Fallback: use cargo install --list when binary --version is unavailable."""
        try:
            result = self.runner.run(
                ["cargo", "install", "--list"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        found_version = self._parse_cargo_list_version(pkg, result.stdout)
        if found_version is None:
            return CheckResult.NOT_SATISFIED

        if fields.get("git"):
            tag = fields.get("tag")
            if tag is not None:
                return CheckResult.SATISFIED if _v1_eq(found_version, tag) else CheckResult.NOT_SATISFIED
            if requested == "latest":
                return CheckResult.SATISFIED
            return CheckResult.SATISFIED if _v1_eq(found_version, requested) else CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg)
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(found_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(found_version, requested) else CheckResult.NOT_SATISFIED

    @staticmethod
    def _parse_binary_version(output: str) -> Optional[str]:
        """Parse version from ``<binary> --version`` output.

        Handles common patterns:
        - ``bat 0.26.1``
        - ``Wild 0.8.0 non-git-build``
        - ``v0.23.4 [+git]``
        - ``tokei 14.0.0 compiled with ...``
        - ``gitui 0.28.1-nightly 2026-03-25``
        """
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Skip URLs
            if stripped.startswith(("http", "https")):
                continue

            # Try to find a version-like token
            # Common patterns: "toolname v1.2.3", "v1.2.3", "1.2.3"
            tokens = stripped.split()
            for token in tokens:
                # Strip leading v/V prefix
                clean = token[1:] if token and token[0] in ("v", "V") else token
                # Check if it looks like a semver-ish version (digits + dots)
                if clean and clean[0].isdigit() and "." in clean:
                    # Take only the version part (before space/paren/comma)
                    version = clean.split()[0].split("(")[0].split(",")[0]
                    if version:
                        return version
        return None

    def _parse_cargo_list_version(self, pkg: str, stdout: str) -> Optional[str]:
        # Parse cargo install --list output for both formats:
        #   crates.io:  "<pkg> v<version>:"
        #   git source: "<pkg> v<version> (<url>):"
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith(f"{pkg} v"):
                continue
            rest = stripped[len(pkg):].strip()  # "v1.2.3:" or "v1.2.3 (url):"
            if rest and rest[0] in ("v", "V"):
                rest = rest[1:]  # "1.2.3:" or "1.2.3 (url):"
            end = len(rest)
            for delim in (":", " "):
                pos = rest.find(delim)
                if pos != -1:
                    end = min(end, pos)
            version = rest[:end]
            return version if version else None
        return None

    def _latest_registry_version(self, pkg: str) -> Optional[str]:
        try:
            result = self.runner.run(
                ["cargo", "search", pkg, "--limit", "1", "--registry", "crates-io"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        # Expected format: `ripgrep = "14.1.0" # ...`
        prefix = pkg + " = \""
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                remainder = line[len(prefix):]
                version = remainder.split("\"", 1)[0]
                return version if version else None
        return None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        """Return the normal cargo install command.

        ``binstall_first`` is intentionally implemented in ``install()`` so
        callers that inspect the command still see the deterministic source
        build fallback command.
        """
        return self._cargo_install_command(item)

    def install(self, item: PlanItem) -> None:
        fields = item.strategy.fields
        if fields.get("binstall_first") is True and "git" not in fields:
            binstall_retry = int(fields.get("binstall_retry", 0) or 0)
            binstall = self._ensure_binstall(item, retry=binstall_retry)
            if binstall is not None:
                try:
                    # Inject GITHUB_TOKEN from gh auth if not already set,
                    # so cargo-binstall can use authenticated API requests
                    token, _source = detect_github_token()
                    env = None
                    if token is not None and not os.environ.get("GITHUB_TOKEN"):
                        env = {**os.environ, "GITHUB_TOKEN": token}
                    command = self._binstall_command(item, binstall, fields)
                    result = self.runner.run(
                        command,
                        check=False,
                        timeout=30,
                        env=env,
                    )
                    if result.returncode == 0:
                        return
                except subprocess.TimeoutExpired:
                    pass

        # Retry cargo install on transient failures (network, registry, etc.)
        max_retries = 2
        for attempt in range(1 + max_retries):
            result = self.runner.run(self._cargo_install_command(item), check=False)
            if result.returncode == 0:
                return
            if attempt < max_retries:
                delay = 2 ** attempt  # exponential backoff: 1s, 2s
                time.sleep(delay)

        raise InstallationError(
            f"Install failed for {item.tool.reference.name} with manager {item.strategy.manager} "
            f"after {1 + max_retries} attempts"
        )

    def _cargo_bin_dirs(self) -> List[Path]:
        """Return common cargo binary directories."""
        dirs: List[Path] = []
        cargo_home = os.environ.get("CARGO_HOME")
        if cargo_home:
            dirs.append(Path(cargo_home) / "bin")
        home = os.environ.get("HOME")
        if home:
            dirs.append(Path(home) / ".cargo" / "bin")
            dirs.append(Path(home) / ".local" / "bin")
        dirs.append(Path.home() / ".cargo" / "bin")
        return dirs

    def _cargo_install_command(self, item: PlanItem) -> List[str]:
        fields = item.strategy.fields
        command = ["cargo", "install", fields["pkg"]]
        if fields.get("locked") is True:
            command.append("--locked")
        if "git" in fields:
            command.extend(["--git", fields["git"]])
            for key in ("tag", "branch", "rev"):
                if key in fields:
                    command.extend([f"--{key}", fields[key]])
        elif _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        return command

    def _binstall_command(self, item: PlanItem, invocation: List[str], fields: Optional[Dict[str, Any]] = None) -> List[str]:
        fields = fields or item.strategy.fields
        if fields.get("binstall_fallback_compile", False):
            command = list(invocation) + ["-y"]
        else:
            command = list(invocation) + ["-y", "--disable-strategies", "compile"]
        if _selector(item) != "latest":
            command.extend(["--version", _selector(item)])
        command.append(item.strategy.fields["pkg"])
        return command

    def _ensure_binstall(self, item: PlanItem, retry: int = 0) -> Optional[List[str]]:
        """Return a cargo-binstall invocation, or None when unavailable.

        All bootstrap failures are intentionally non-fatal so
        ``binstall_first`` remains an optimization over the normal
        ``cargo install`` path rather than a new hard dependency.
        """
        if shutil.which("cargo-binstall") and self._verified_binstall("cargo-binstall"):
            return ["cargo", "binstall"]

        home_binary = self._cargo_home_bin() / "cargo-binstall"
        if home_binary.is_file() and os.access(home_binary, os.X_OK):
            if self._verified_binstall(str(home_binary)):
                return [str(home_binary)]
            return None

        for attempt in range(1 + retry):
            if self._download_binstall(item, home_binary):
                if self._verified_binstall(str(home_binary)):
                    return [str(home_binary)]
        return None

    def _verified_binstall(self, binary: str) -> bool:
        try:
            result = self.runner.run([binary, "-V"], check=False, capture_output=True, text=True)
        except OSError:
            return False
        return result.returncode == 0

    def _cargo_home_bin(self) -> Path:
        cargo_home = os.environ.get("CARGO_HOME")
        if cargo_home:
            return Path(cargo_home) / "bin"
        home = os.environ.get("HOME")
        if home:
            return Path(home) / ".cargo" / "bin"
        return Path.home() / ".cargo" / "bin"

    def _download_binstall(self, item: PlanItem, destination: Path) -> bool:
        target = self._BINSTALL_TARGETS.get((item.environment.os, item.environment.arch))
        if target is None:
            return False
        asset = f"cargo-binstall-{target}.tgz"

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / asset

                # Try gh CLI first (has GITHUB_TOKEN auth, avoids rate limits in CI)
                if shutil.which("gh"):
                    try:
                        self.runner.run(
                            [
                                "gh", "release", "download",
                                "latest",
                                "--repo", "cargo-bins/cargo-binstall",
                                "--pattern", asset,
                                "--dir", str(temp),
                            ],
                            check=True,
                            capture_output=True,
                            timeout=60,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        # gh failed, fall through to urllib
                        pass

                # If gh didn't produce the file, try urllib
                if not archive.is_file():
                    url = f"{self._BINSTALL_RELEASE_BASE}/{asset}"
                    with urllib.request.urlopen(url, timeout=30) as response:
                        archive.write_bytes(response.read())

                if not archive.is_file():
                    return False

                executable = self._extract_binstall(archive, Path(temp))
                temp_dest = destination.parent / f".{destination.name}.installing"
                shutil.copy2(executable, temp_dest)
                temp_dest.chmod(temp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                os.replace(str(temp_dest), str(destination))
            return True
        except (OSError, tarfile.TarError, urllib.error.URLError, TimeoutError):
            try:
                temp_dest = destination.parent / f".{destination.name}.installing"
                temp_dest.unlink()
            except OSError:
                pass
            return False

    def _extract_binstall(self, archive: Path, temp_dir: Path) -> Path:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                if name == "cargo-binstall" and member.isfile():
                    extracted = temp_dir / "cargo-binstall.extracted"
                    source = tar.extractfile(member)
                    if source is None:
                        break
                    with source, extracted.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
                    extracted.chmod(extracted.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    return extracted
        raise tarfile.TarError("cargo-binstall executable not found in archive")


class MiseManager(CommandManager):
    """Mise version manager.

    Check: uses mise list/ls to determine installed versions.
    """

    def check(self, item: PlanItem) -> CheckResult:
        plugin = item.strategy.fields["plugin"]
        requested = _selector(item)

        try:
            result = self.runner.run(
                ["mise", "ls", "--json", plugin],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Check if requested version is installed
        # mise ls --json returns entries with `installed` field; filter to only installed
        installed_versions = []
        if isinstance(data, list):
            for entry in data:
                if not entry.get("installed", True):
                    continue
                version = entry.get("version", "")
                if version:
                    installed_versions.append(version)
        elif isinstance(data, dict):
            versions = data.get("versions", [])
            for v in versions:
                if isinstance(v, str):
                    installed_versions.append(v)
                elif isinstance(v, dict):
                    if not v.get("installed", True):
                        continue
                    ver = v.get("version", "")
                    if ver:
                        installed_versions.append(ver)

        if not installed_versions:
            return CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest = self._latest_version(plugin)
            if latest is None:
                return CheckResult.CHECK_ERROR
            for iv in installed_versions:
                if _v1_eq(iv, latest):
                    return CheckResult.SATISFIED
            return CheckResult.NOT_SATISFIED

        # Check if any installed version matches
        for iv in installed_versions:
            if _v1_eq(iv, requested):
                return CheckResult.SATISFIED

        return CheckResult.NOT_SATISFIED

    def _latest_version(self, plugin: str) -> Optional[str]:
        try:
            result = self.runner.run(
                ["mise", "latest", plugin],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        latest = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return latest or None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        return ["mise", "install", f"{item.strategy.fields['plugin']}@{_selector(item)}"]


class NpmGlobalManager(CommandManager):
    """NPM global package manager.

    Check: uses npm list -g --json for global package metadata.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        requested = _selector(item)
        command = ["npm", "list", "-g", "--json", pkg]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])

        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # Parse npm list output
        deps = data.get("dependencies", {})
        pkg_info = deps.get(pkg)
        if pkg_info is None:
            return CheckResult.NOT_SATISFIED

        installed_version = pkg_info.get("version")
        if not installed_version:
            return CheckResult.CHECK_ERROR

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg, item.strategy.fields.get("registry"))
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _latest_registry_version(self, pkg: str, registry: Optional[str] = None) -> Optional[str]:
        command = ["npm", "view", pkg, "version", "--json"]
        if registry:
            command.extend(["--registry", registry])
        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw.strip('"')
        return parsed if isinstance(parsed, str) and parsed else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}@{_selector(item)}"
        command = ["npm", "install", "-g", package]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])
        return command


class PnpmGlobalManager(CommandManager):
    """PNPM global package manager.

    Check: uses pnpm list -g --json for global package metadata.
    """

    def check(self, item: PlanItem) -> CheckResult:
        pkg = item.strategy.fields["pkg"]
        requested = _selector(item)
        command = ["pnpm", "list", "-g", "--json", pkg]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])

        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult.CHECK_ERROR

        # pnpm list returns array
        installed_version = None
        if isinstance(data, list) and data:
            installed_version = data[0].get("version")
        elif isinstance(data, dict):
            installed_version = data.get("version")

        if not installed_version:
            return CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg, item.strategy.fields.get("registry"))
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

    def _latest_registry_version(self, pkg: str, registry: Optional[str] = None) -> Optional[str]:
        command = ["pnpm", "view", pkg, "version", "--json"]
        if registry:
            command.extend(["--registry", registry])
        try:
            result = self.runner.run(command, check=False, capture_output=True, text=True)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw.strip('"')
        return parsed if isinstance(parsed, str) and parsed else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}@{_selector(item)}"
        command = ["pnpm", "add", "-g", package]
        if "registry" in item.strategy.fields:
            command.extend(["--registry", item.strategy.fields["registry"]])
        return command


class UvToolManager(CommandManager):
    """UV tool manager.

    Check: exact versions read recorded tool metadata. latest is non-check-capable in v1.
    """

    def check(self, item: PlanItem) -> CheckResult:
        requested = _selector(item)
        if requested == "latest":
            # Non-check-capable in v1
            return CheckResult.NOT_SATISFIED

        pkg = item.strategy.fields["pkg"]
        try:
            result = self.runner.run(
                ["uv", "tool", "list"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # `uv tool list` has no JSON output mode; parse the stable text form:
        #   pkgname v1.2.3
        #   - binary1
        for line in result.stdout.splitlines():
            match = re.match(r"^(\S+) v(\S+)\s*$", line)
            if match and match.group(1) == pkg:
                return (
                    CheckResult.SATISFIED
                    if _v1_eq(match.group(2), requested)
                    else CheckResult.NOT_SATISFIED
                )

        return CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        package = item.strategy.fields["pkg"] if _selector(item) == "latest" else f"{item.strategy.fields['pkg']}=={_selector(item)}"
        command = ["uv", "tool", "install", package]
        if "python" in item.strategy.fields:
            command.extend(["--python", item.strategy.fields["python"]])
        for dependency in item.strategy.fields.get("with", []):
            command.extend(["--with", dependency])
        return command


class RustupManager(CommandManager):
    """Rustup toolchain manager.

    Check: verifies toolchain, components, and targets via rustup show.
    """

    def check(self, item: PlanItem) -> CheckResult:
        fields = item.strategy.fields
        selector = "stable" if _selector(item) == "latest" else _selector(item)

        try:
            result = self.runner.run(
                ["rustup", "show", "active-toolchain"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # Check the full list of installed toolchains
        try:
            list_result = self.runner.run(
                ["rustup", "toolchain", "list"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CheckResult.CHECK_ERROR

        if list_result.returncode != 0:
            return CheckResult.CHECK_ERROR

        # Check if the requested toolchain is in the list
        toolchain_found = False
        for line in list_result.stdout.splitlines():
            if line.strip().startswith(selector):
                toolchain_found = True
                break

        if not toolchain_found:
            return CheckResult.NOT_SATISFIED

        # Check components
        required_components = fields.get("components", [])
        if required_components:
            try:
                comp_result = self.runner.run(
                    ["rustup", "component", "list", "--toolchain", selector],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if comp_result.returncode != 0:
                    return CheckResult.CHECK_ERROR

                for component in required_components:
                    if f"{component} (installed)" not in comp_result.stdout:
                        return CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR

        # Check targets
        required_targets = fields.get("targets", [])
        if required_targets:
            try:
                target_result = self.runner.run(
                    ["rustup", "target", "list", "--toolchain", selector],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if target_result.returncode != 0:
                    return CheckResult.CHECK_ERROR

                for target in required_targets:
                    if f"{target} (installed)" not in target_result.stdout:
                        return CheckResult.NOT_SATISFIED
            except OSError:
                return CheckResult.CHECK_ERROR

        if selector in ("stable", "nightly"):
            current = self._moving_channel_current(selector)
            if current is None:
                return CheckResult.CHECK_ERROR
            if not current:
                return CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED

    def _moving_channel_current(self, selector: str) -> Optional[bool]:
        try:
            result = self.runner.run(
                ["rustup", "check"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        saw_selector = False
        for line in result.stdout.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith(selector.lower()):
                saw_selector = True
                if "up to date" in stripped or "up-to-date" in stripped:
                    return True
                if "update available" in stripped or "outdated" in stripped:
                    return False
        return None if not saw_selector else None

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        selector = "stable" if _selector(item) == "latest" else _selector(item)
        command = ["rustup", "toolchain", "install", selector]
        if "profile" in item.strategy.fields:
            command.extend(["--profile", item.strategy.fields["profile"]])
        for component in item.strategy.fields.get("components", []):
            command.extend(["--component", component])
        for target in item.strategy.fields.get("targets", []):
            command.extend(["--target", target])
        return command

    def install(self, item: PlanItem) -> None:
        super().install(item)
        if item.strategy.fields.get("set_default") is True:
            selector = "stable" if _selector(item) == "latest" else _selector(item)
            result = self.runner.run(["rustup", "default", selector], check=False)
            if result.returncode != 0:
                raise InstallationError(f"Install failed for {item.tool.reference.name} with manager {item.strategy.manager}")
