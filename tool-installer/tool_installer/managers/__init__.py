"""Manager registry."""

from __future__ import annotations

from typing import Dict, Optional

from ..models import GithubReleaseConfig
from .base import CommandRunner, Manager
from .commands import (
    AptManager,
    BrewCaskManager,
    BrewManager,
    CargoBinstallManager,
    CargoInstallManager,
    MiseManager,
    NpmGlobalManager,
    PnpmGlobalManager,
    RustupManager,
    UvToolManager,
)
from .github_release import GithubReleaseManager
from .script import ScriptManager


def default_registry(
    gh_config: Optional[GithubReleaseConfig] = None,
    runner: Optional[CommandRunner] = None,
) -> Dict[str, Manager]:
    return {
        "apt": AptManager(runner),
        "brew": BrewManager(runner),
        "brew-cask": BrewCaskManager(runner),
        "cargo-binstall": CargoBinstallManager(runner),
        "cargo-install": CargoInstallManager(runner),
        "rustup": RustupManager(runner),
        "mise": MiseManager(runner),
        "npm-global": NpmGlobalManager(runner),
        "pnpm-global": PnpmGlobalManager(runner),
        "uv-tool": UvToolManager(runner),
        "github-release": GithubReleaseManager(gh_config),
        "script": ScriptManager(),
    }
