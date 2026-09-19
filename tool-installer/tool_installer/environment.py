"""Environment normalization."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from typing import List

from .errors import StrategyError
from .models import Environment


def refresh_path() -> List[str]:
    """Re-discover tool directories created during this very run.

    PATH is a snapshot from process start, but the installer itself installs
    the runtimes (mise/node, uv) that later items probe against; without a
    refresh, npm-global checks fail on a bare system with a frozen PATH.
    Returns the directories that were added.
    """
    current = os.environ.get("PATH", "").split(os.pathsep)
    added: List[str] = []

    def consider(candidate: str) -> None:
        if candidate and candidate not in current and os.path.isdir(candidate):
            current.append(candidate)
            added.append(candidate)
            os.environ["PATH"] = os.pathsep.join(current)

    consider(os.path.expanduser("~/.local/bin"))
    consider(os.path.expanduser("~/.cargo/bin"))

    mise = shutil.which("mise")
    if mise:
        try:
            proc = subprocess.run(
                [mise, "env", "--json"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            mise_path = json.loads(proc.stdout or "{}").get("PATH", "")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            mise_path = ""
        # Only PATH is consumed; any [env] secrets in the payload stay unread.
        for directory in mise_path.split(os.pathsep):
            consider(directory)

    return added


def detect_environment() -> Environment:
    return normalize_environment(platform.system(), platform.machine())


def normalize_environment(system: str, machine: str) -> Environment:
    os_name = system.lower()
    if os_name == "darwin":
        normalized_os = "macos"
    elif os_name == "linux":
        normalized_os = "linux"
    else:
        raise StrategyError(f"Unsupported OS: {system}")

    arch = machine.lower()
    if arch in {"x86_64", "amd64"}:
        normalized_arch = "x86_64"
    elif arch in {"aarch64", "arm64"}:
        normalized_arch = "aarch64"
    else:
        raise StrategyError(f"Unsupported architecture: {machine}")

    return Environment(os=normalized_os, arch=normalized_arch)
