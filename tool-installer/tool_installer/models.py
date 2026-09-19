"""Core data models for tool-installer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ToolReference:
    """A parsed tool key from tools.toml."""

    raw: str
    name: str
    version: str = "latest"


@dataclass(frozen=True)
class ToolSpec:
    """A selected tool declaration and its user-facing metadata."""

    reference: ToolReference
    desc: Optional[str] = None
    allow_fail: bool = False


@dataclass(frozen=True)
class ModuleSpec:
    """A module from tools.toml."""

    name: str
    depends: List[str] = field(default_factory=list)
    tools: List[ToolSpec] = field(default_factory=list)


@dataclass(frozen=True)
class ToolsConfig:
    """Parsed tools.toml entry configuration."""

    path: Path
    manifest_path: Path
    modules: Dict[str, ModuleSpec]


@dataclass(frozen=True)
class GithubReleaseConfig:
    """Configuration for the github-release manager from manifest [_github-release] section."""

    github_mirrors: List[str] = field(default_factory=list)
    timeout: float = 30.0
    retry: int = 3


@dataclass(frozen=True)
class Environment:
    """Normalized execution environment."""

    os: str
    arch: str


@dataclass(frozen=True)
class MergedStrategy:
    """A manifest strategy after OS/Arch merge and validation."""

    tool_name: str
    manager: str
    fields: Dict[str, Any]
    force: bool = False


@dataclass(frozen=True)
class PlanItem:
    """One serial action in an installation plan."""

    module_name: str
    tool: ToolSpec
    strategy: MergedStrategy
    environment: Environment


@dataclass(frozen=True)
class InstallPlan:
    """A fully resolved ordered installation plan."""

    items: List[PlanItem]
