"""Manager base classes and command runner."""

from __future__ import annotations

import enum
import os
import subprocess
import sys
from typing import List, Optional, Protocol, Sequence

from ..errors import InstallationError
from ..models import PlanItem


class CheckResult(enum.Enum):
    """Outcome of an installed-state check."""

    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    CHECK_ERROR = "check_error"


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], check: bool = False, **kwargs: object) -> subprocess.CompletedProcess[str]:
        ...


class SubprocessRunner:
    def run(self, args: Sequence[str], check: bool = False, **kwargs: object) -> subprocess.CompletedProcess[str]:
        kwargs.setdefault("text", True)
        # Ensure ~/.cargo/bin is in PATH for cargo/rustup tools
        env = kwargs.get("env") or dict(os.environ)
        cargo_bin = os.path.expanduser("~/.cargo/bin")
        if cargo_bin not in env.get("PATH", ""):
            env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
            kwargs["env"] = env
        return subprocess.run(list(args), check=check, **kwargs)


def _is_root() -> bool:
    """Check if the current process has root privileges."""
    return os.geteuid() == 0


def _has_tty() -> bool:
    """Check if stdin is connected to a TTY (needed for sudo password prompt)."""
    return sys.stdin.isatty()


def _run_with_sudo(
    args: Sequence[str],
    runner: Optional[CommandRunner] = None,
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    """Run a command with sudo if not root, matching dotfiles sudo_run() semantics.

    - If already root: execute args directly (no sudo).
    - If not root: prepend sudo to args.
      - If no TTY is available and sudo is needed, fail with a clear message.

    This mirrors the dotfiles setup.sh sudo_run() helper:
        if [ "$EUID" -eq 0 ]; then "$@"; else sudo "$@"; fi
    """
    if _is_root():
        cmd = list(args)
    else:
        if not _has_tty():
            raise InstallationError(
                "This command requires elevated privileges but no TTY is available for sudo password input. "
                "Please run tool-installer in an interactive terminal, "
                "or run as root (e.g., 'sudo tool-installer install <module>')."
            )
        cmd = ["sudo"] + list(args)

    r = runner or SubprocessRunner()
    return r.run(cmd, **kwargs)


class Manager(Protocol):
    def check(self, item: PlanItem) -> CheckResult:
        """Return the installed-state check outcome for a plan item."""
        ...

    def install(self, item: PlanItem) -> None:
        ...


class CommandManager:
    """Base for managers that use external commands.

    Default: check is always NOT_SATISFIED (non-check-capable).
    Subclasses that are check-capable must override `check`.

    If `needs_privilege` is True, the install command will be executed
    through _run_with_sudo() (equivalent to dotfiles sudo_run).
    """

    needs_privilege: bool = False

    def __init__(self, runner: Optional[CommandRunner] = None) -> None:
        self.runner = runner or SubprocessRunner()

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError

    def install_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError

    def check(self, item: PlanItem) -> CheckResult:
        """Non-check-capable default: always returns NOT_SATISFIED."""
        return CheckResult.NOT_SATISFIED

    def install(self, item: PlanItem) -> None:
        cmd = self.install_command(item)
        if self.needs_privilege:
            result = _run_with_sudo(cmd, runner=self.runner, check=False)
        else:
            result = self.runner.run(cmd, check=False)
        if result.returncode != 0:
            raise InstallationError(f"Install failed for {item.tool.reference.name} with manager {item.strategy.manager}")
