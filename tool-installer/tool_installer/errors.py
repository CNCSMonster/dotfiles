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


class AuthorizationRequired(InstallationError):
    """Raised when an unexpected state needs a decision nobody is there to make.

    与 InstallationError 分开，是因为处理方式不同：普通失败按 allow_fail 决定是否中断，
    而"缺授权"永远不该中断整轮安装——它只应被跳过并在结束时汇总（见 executor）。
    仍继承 InstallationError，保证上层任何只 catch 安装错误的地方都不会漏接。
    """
