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


# 兜底上限：任何外部命令都不允许无限等（黑洞源、挂死的 registry 最终都会撞上它）。
# 正常命令远达不到：最慢的是 cargo 源码编译，1 小时足够；短查询各自带更小的 timeout。
DEFAULT_COMMAND_TIMEOUT = 3600


def _timeout_detail(exc: subprocess.TimeoutExpired) -> str:
    """超时前已捕获的输出（可能为 bytes），让调用方仍能据此归因。"""
    chunks = []
    for raw in (exc.stdout, exc.stderr):
        if not raw:
            continue
        chunks.append(raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw))
    return "\n".join(chunks)


class SubprocessRunner:
    def run(self, args: Sequence[str], check: bool = False, **kwargs: object) -> subprocess.CompletedProcess[str]:
        kwargs.setdefault("text", True)
        # Ensure ~/.cargo/bin is in PATH for cargo/rustup tools
        env = kwargs.get("env") or dict(os.environ)
        cargo_bin = os.path.expanduser("~/.cargo/bin")
        if cargo_bin not in env.get("PATH", ""):
            env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
            kwargs["env"] = env
        kwargs.setdefault("timeout", DEFAULT_COMMAND_TIMEOUT)
        try:
            return subprocess.run(list(args), check=check, **kwargs)
        except subprocess.TimeoutExpired as exc:
            # 转成受控异常：executor 只 catch InstallationError，裸超时会变成
            # traceback 中断整轮安装，还丢掉"卡在哪"的现场。
            detail = _timeout_detail(exc)
            raise InstallationError(
                f"Command timed out after {exc.timeout}s: {args[0]}"
                + (f"\n{detail}" if detail else "")
            ) from None


def _is_root() -> bool:
    """Check if the current process has root privileges."""
    return os.geteuid() == 0


def _has_tty() -> bool:
    """Check if stdin is connected to a TTY (needed for sudo password prompt)."""
    return sys.stdin.isatty()


def _passwordless_sudo_available(runner: CommandRunner) -> bool:
    """免密 sudo 探测（`sudo -n true`，有密码则立即 rc≠0，不阻塞）。

    CI runner、云镜像、配了 NOPASSWD 的环境都是这种：能提权，但**没有 TTY**。
    shell 侧 setup.sh 的 preflight_runtime_deps 顺序就是 `sudo -n true` →
    交互 `sudo -v`；tool-installer 缺第一步会在无 TTY 时直接判死，即使免密
    sudo 完全可用（system-packages 迁到 apt 后，CI 的 install languages/
    lsp-servers 经 depends 链拿到 apt 条目，正是这样整个 job 挂掉的）。
    """
    try:
        result = runner.run(
            ["sudo", "-n", "true"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, InstallationError, subprocess.SubprocessError):
        # sudo 不可执行 / 探测超时：当作免密不可用，交给下面的 TTY 分支判定
        return False
    return result.returncode == 0


def _run_with_sudo(
    args: Sequence[str],
    runner: Optional[CommandRunner] = None,
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    """Run a command with sudo if not root, matching dotfiles sudo_run() semantics.

    - If already root: execute args directly (no sudo).
    - If passwordless sudo works: prepend sudo (no TTY needed).
    - Else if a TTY is available: prepend sudo (sudo can prompt).
    - Else: fail with a clear message.

    与 shell 侧 preflight_runtime_deps 的提权顺序一一对应（root → `sudo -n` →
    交互 `sudo -v` → 报错给出可复制的修复命令），两侧只能有一个答案。
    """
    r = runner or SubprocessRunner()
    if _is_root():
        cmd = list(args)
    elif _passwordless_sudo_available(r):
        cmd = ["sudo"] + list(args)
    elif not _has_tty():
        raise InstallationError(
            "This command requires elevated privileges but no TTY is available for sudo password input. "
            "Please run tool-installer in an interactive terminal, "
            "or run as root (e.g., 'sudo tool-installer install <module>')."
        )
    else:
        cmd = ["sudo"] + list(args)

    return r.run(cmd, **kwargs)


class Manager(Protocol):
    def preflight(self, items: Sequence[PlanItem]) -> None:
        """Optional once-per-round hook, run before any item is installed.

        Manager-specific global work: AptManager refreshes the package index and
        runs the source health check here — once per plan, never per item.
        """
        ...

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

    def preflight(self, items: Sequence[PlanItem]) -> None:
        """Once-per-round hook. Default: nothing to do."""
        return None

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
