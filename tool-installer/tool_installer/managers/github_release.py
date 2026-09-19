"""GitHub release manager."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional

from ..errors import InstallationError
from ..github_token import detect_github_token
from ..models import GithubReleaseConfig, PlanItem
from .base import CheckResult, Manager


def _is_relative_to(path: Path, base: Path) -> bool:
    """Python 3.8-compatible Path.is_relative_to()."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


class GithubReleaseManager:
    """Manager for GitHub release downloads.

    Check-capable only when version_probe is defined in the strategy.
    Without version_probe, always returns NOT_SATISFIED (non-check-capable).

    Supports mirror fallback and retry/timeout via GithubReleaseConfig.
    """

    def __init__(self, gh_config: Optional[GithubReleaseConfig] = None) -> None:
        self._cfg = gh_config or GithubReleaseConfig()
        self._token: Optional[str] = None
        self._token_source: Optional[str] = None
        self._token_resolved = False

    def ensure_token(self) -> None:
        """Resolve GitHub token once per process. Idempotent."""
        if self._token_resolved:
            return
        self._token_resolved = True
        self._token, self._token_source = detect_github_token()

    def get_token_report(self) -> str:
        """Return a human-readable token source description for display."""
        self.ensure_token()
        return self._token_source or "not configured"

    def has_token(self) -> bool:
        self.ensure_token()
        return self._token is not None

    def check(self, item: PlanItem) -> CheckResult:
        version_probe = item.strategy.fields.get("version_probe")
        if not version_probe:
            # Not check-capable: always install when reached
            return CheckResult.NOT_SATISFIED

        # Execute version probe
        install_name = item.strategy.fields.get("install_name", item.tool.reference.name)
        home = os.environ.get("HOME")
        if not home:
            return CheckResult.CHECK_ERROR

        bin_path = Path(home) / ".local" / "bin" / install_name
        if not bin_path.is_file():
            return CheckResult.NOT_SATISFIED

        probe = version_probe
        command = list(probe["command"])
        # Replace {bin} placeholder
        command = [c.replace("{bin}", str(bin_path)) for c in command]

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return CheckResult.CHECK_ERROR

        if result.returncode != 0:
            return CheckResult.CHECK_ERROR

        regex_str = probe["regex"]
        try:
            pattern = re.compile(regex_str)
        except re.error:
            return CheckResult.CHECK_ERROR

        match = pattern.search(result.stdout)
        if not match:
            return CheckResult.CHECK_ERROR

        captured_version = match.group("version")
        if not captured_version:
            return CheckResult.CHECK_ERROR

        # Compare using v1 version equality
        requested = item.tool.reference.version
        if requested == "latest":
            # For latest, we need to resolve the actual latest tag
            # and compare. If we can't resolve it, treat as check_error.
            try:
                latest_tag = self._latest_tag(item.strategy.fields["repo"])
                return self._compare_versions(captured_version, latest_tag)
            except (InstallationError, urllib.error.URLError, OSError):
                return CheckResult.CHECK_ERROR
        else:
            return self._compare_versions(captured_version, requested)

    @staticmethod
    def _compare_versions(installed: str, requested: str) -> CheckResult:
        """Compare versions using v1 equality (strip one leading v/V)."""
        def normalize(v: str) -> str:
            if v and v[0] in ("v", "V"):
                return v[1:]
            return v

        if normalize(installed) == normalize(requested):
            return CheckResult.SATISFIED
        return CheckResult.NOT_SATISFIED

    def _latest_tag(self, repo: str) -> str:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = self._fetch_url(api_url, is_api=True)
        data = json.loads(response.read().decode("utf-8"))
        tag = data.get("tag_name")
        if not isinstance(tag, str) or not tag:
            raise InstallationError(f"Could not resolve latest GitHub release for {repo}")
        return tag

    def install(self, item: PlanItem) -> None:
        home = os.environ.get("HOME")
        if not home:
            raise InstallationError("HOME is required for github-release installs")

        version = item.tool.reference.version
        if version == "latest":
            version = self._latest_tag(item.strategy.fields["repo"])

        asset_name = self._asset_name(item, version)
        repo = item.strategy.fields["repo"]
        download_path = f"releases/download/{version}/{asset_name}"

        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            downloaded = temp_dir / asset_name
            self._download_asset(repo, download_path, downloaded)
            self._verify_checksum(item, downloaded)
            executable = self._locate_executable(item, downloaded, temp_dir, version)

            install_dir = Path(home) / ".local" / "bin"
            install_dir.mkdir(parents=True, exist_ok=True)
            destination = install_dir / item.strategy.fields.get("install_name", item.tool.reference.name)

            # Atomic install: create temp file in the same directory as destination
            # then use os.replace for atomic rename on same filesystem
            tmp_dest = install_dir / f".installing_{item.tool.reference.name}.tmp"
            try:
                shutil.copy2(executable, tmp_dest)
                tmp_dest.chmod(tmp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                os.replace(str(tmp_dest), str(destination))
            except OSError:
                # Clean up temp file if rename failed
                try:
                    tmp_dest.unlink()
                except OSError:
                    pass
                raise

    def _build_download_urls(self, repo: str, path: str) -> List[str]:
        """Build a list of URLs to try: mirrors first, then direct GitHub."""
        urls: List[str] = []
        for mirror in self._cfg.github_mirrors:
            urls.append(f"{mirror}/https://github.com/{repo}/{path}")
        urls.append(f"https://github.com/{repo}/{path}")
        return urls

    @staticmethod
    def _is_github_url(url: str) -> bool:
        """Check if a URL points to github.com (not a mirror)."""
        return "github.com" in url

    def _apply_auth(self, req: urllib.request.Request, url: str) -> None:
        """Add Authorization header for github.com URLs only."""
        if self._is_github_url(url):
            self.ensure_token()
            if self._token:
                req.add_header("Authorization", f"token {self._token}")

    def _download_asset(self, repo: str, path: str, dest: Path) -> None:
        """Download a GitHub release asset with mirror fallback and retry."""
        urls = self._build_download_urls(repo, path)
        last_error: Optional[Exception] = None
        for url in urls:
            for attempt in range(self._cfg.retry + 1):
                try:
                    req = urllib.request.Request(url)
                    self._apply_auth(req, url)
                    with urllib.request.urlopen(req, timeout=self._cfg.timeout) as response:
                        # Read in chunks with total timeout to avoid hanging on slow transfers
                        deadline = time.monotonic() + self._cfg.timeout * 3
                        chunks: List[bytes] = []
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError("Download total timeout exceeded")
                            chunk = response.read(65536)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        dest.write_bytes(b"".join(chunks))
                    return
                except (urllib.error.URLError, OSError, TimeoutError) as exc:
                    last_error = exc
                    if attempt < self._cfg.retry:
                        time.sleep(min(2 ** attempt, 8))
            # This URL failed all retries; try next mirror
        raise InstallationError(
            f"Failed to download {repo}/{path} after trying all mirrors and direct: {last_error}"
        )

    def _fetch_url(self, url: str, is_api: bool = False) -> object:
        """Fetch a URL with retry and timeout. No mirror fallback for API calls."""
        last_error: Optional[Exception] = None
        for attempt in range(self._cfg.retry + 1):
            try:
                req = urllib.request.Request(url)
                if is_api:
                    req.add_header("Accept", "application/vnd.github.v3+json")
                self._apply_auth(req, url)
                return urllib.request.urlopen(req, timeout=self._cfg.timeout)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                if attempt < self._cfg.retry:
                    time.sleep(min(2 ** attempt, 8))
        raise InstallationError(f"Failed to fetch {url}: {last_error}")

    def _asset_name(self, item: PlanItem, version: str) -> str:
        return item.strategy.fields["asset"].format(
            tool=item.tool.reference.name,
            version=version,
            os=item.environment.os,
            arch=item.environment.arch,
        )

    def _verify_checksum(self, item: PlanItem, path: Path) -> None:
        expected = item.strategy.fields.get("sha256")
        if not expected:
            return
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != expected.lower():
            raise InstallationError(f"Checksum mismatch for {item.tool.reference.name}")

    def _locate_executable(self, item: PlanItem, asset: Path, temp_dir: Path, version: str = "") -> Path:
        bin_template = item.strategy.fields["bin"]
        bin_path = Path(bin_template.format(
            tool=item.tool.reference.name,
            version=version,
            os=item.environment.os,
            arch=item.environment.arch,
        ))
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        if zipfile.is_zipfile(asset):
            self._safe_extract_zip(asset, extract_dir)
            candidate = extract_dir / bin_path
        elif asset.name.endswith((".tar.gz", ".tgz", ".tar.xz")):
            self._safe_extract_tar(asset, extract_dir)
            candidate = extract_dir / bin_path
        else:
            # Single-file binary asset
            if bin_path.name == asset.name and len(bin_path.parts) == 1:
                return asset
            raise InstallationError(f"Unsupported archive or single-file asset mismatch for {item.tool.reference.name}")

        if not candidate.is_file():
            raise InstallationError(f"Executable not found in GitHub release asset: {bin_path}")

        # Verify the candidate resolves within the extracted contents
        try:
            candidate.resolve().relative_to(extract_dir.resolve())
        except ValueError:
            raise InstallationError(f"Executable resolves outside extracted contents for {item.tool.reference.name}")

        return candidate

    @staticmethod
    def _safe_extract_zip(archive: Path, dest: Path) -> None:
        """Extract a zip archive with path containment checks."""
        dest_resolved = dest.resolve()
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                # Skip the zip root directory entry
                if info.filename.endswith("/") and info.filename == Path(info.filename).name + "/":
                    continue

                target = dest_resolved / Path(info.filename)
                if not _is_relative_to(target.resolve(), dest_resolved):
                    raise InstallationError(f"Archive entry escapes extraction directory: {info.filename}")
                if info.filename.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    @staticmethod
    def _safe_extract_tar(archive: Path, dest: Path) -> None:
        """Extract a tar archive with path containment checks.

        Each entry is validated before extraction to prevent:
        - Absolute paths
        - Parent directory traversal (..)
        - Symlink targets escaping the extraction directory
        """
        dest_resolved = dest.resolve()
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                # Check for absolute paths
                if os.path.isabs(member.name):
                    raise InstallationError(f"Archive entry has absolute path: {member.name}")
                # Check for parent directory traversal
                parts = Path(member.name).parts
                if ".." in parts:
                    raise InstallationError(f"Archive entry contains parent traversal: {member.name}")

                target = dest_resolved / member.name
                if not _is_relative_to(target.resolve(), dest_resolved):
                    raise InstallationError(f"Archive entry escapes extraction directory: {member.name}")

                # Handle symlinks: resolve target must stay within dest
                if member.issym() or member.islnk():
                    link_name = member.linkname
                    if member.issym():
                        # Relative symlink from the entry's parent directory
                        link_target = (target.parent / link_name).resolve()
                    else:
                        # Hard link
                        link_target = dest_resolved / link_name
                    if not _is_relative_to(link_target, dest_resolved):
                        raise InstallationError(f"Symlink/hardlink escapes extraction directory: {member.name} -> {member.linkname}")

                # Extract the entry safely
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.issym():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    target.symlink_to(member.linkname)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(member)
                    if src is None:
                        raise InstallationError(f"Cannot extract file: {member.name}")
                    with src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    # Preserve permissions
                    mode = member.mode
                    if mode is not None:
                        target.chmod(mode)
                elif member.isdev():
                    # Device files are not supported
                    raise InstallationError(f"Device file in archive: {member.name}")
                else:
                    # Other types (block device, char device, etc.) are not supported
                    raise InstallationError(f"Unsupported archive entry type: {member.name}")

    def check_command(self, item: PlanItem) -> list:
        # Not used; check is handled via version_probe
        raise NotImplementedError

    def install_command(self, item: PlanItem) -> list:
        # Not used; install is handled via the install method
        raise NotImplementedError
