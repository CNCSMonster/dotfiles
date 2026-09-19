"""Domain errors for tool-installer."""

from __future__ import annotations


class ToolInstallerError(Exception):
    """Base class for expected tool-installer failures."""


class CliError(ToolInstallerError):
    """Raised for command-line usage errors."""


class ConfigError(ToolInstallerError):
    """Raised for invalid or unreadable configuration files."""


class DependencyError(ToolInstallerError):
    """Raised for module dependency graph errors."""


class ManifestError(ToolInstallerError):
    """Raised for manifest structure or lookup errors."""


class StrategyError(ToolInstallerError):
    """Raised when a tool has no valid executable strategy."""


class InstallationError(ToolInstallerError):
    """Raised when checking or installing a tool fails."""
