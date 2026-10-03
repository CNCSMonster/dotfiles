"""Command-based package managers with SPEC-aligned checks."""

from __future__ import annotations

import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Sequence

from ..errors import InstallationError
from ..github_token import detect_github_token
from ..models import PlanItem
from .apt_policy import (
    APT_COMMAND_TIMEOUT,
    APT_HTTP_TIMEOUT,
    APT_LOCK_TIMEOUT,
    APT_RETRIES,
    apt_options,
    failure_message,
    preflight_source_warnings,
)
from .base import CheckResult, CommandManager, CommandRunner, _run_with_sudo


def _noninteractive(cmd: List[str]) -> List[str]:
    """给命令套上 `env DEBIAN_FRONTEND=noninteractive`（与 scripts/lib/apt.sh 同形）。

    变量必须作为 env 子命令的参数、跟在 sudo **之后**：sudo 默认 env_reset 会丢掉
    普通环境变量（Step 1 时踩过：`DEBIAN_FRONTEND=... sudo apt-get` 被静默清掉，
    改成 `sudo env DEBIAN_FRONTEND=... apt-get` 才生效）。root 时 env 直接执行，
    两种路径同一个答案。
    """
    return ["env", "DEBIAN_FRONTEND=noninteractive", *cmd]


def _selector(item: PlanItem) -> str:
    return item.tool.reference.version


def _package_list(item: PlanItem) -> List[str]:
    """manifest 的 pkg 字段：空格分隔的包清单（单包即一个元素）。

    一个 tool 条目对应一个"包组"（如 system-packages 的 28 个构建依赖），而不是
    每包一条——这是跨平台约束下的形态选择：manifest 的 tool 必须每个平台都有
    策略段，而 22 个 Linux 专属包（build-essential、libssl-dev…）在 brew 侧没有
    对应名，按包拆条目会让 macOS 段无从写起。
    """
    return item.strategy.fields["pkg"].split()


def _v1_eq(a: str, b: str) -> bool:
    """v1 version equality: strip one leading v/V, then exact match."""
    def norm(v: str) -> str:
        if v and v[0] in ("v", "V"):
            return v[1:]
        return v
    return norm(a) == norm(b)


def _cargo_v1_eq(installed: str, requested: str) -> bool:
    """Cargo version equality that forgives a pre-release tag on the installed side.

    cargo-binstall hands out GitHub release artifacts whose banner reads
    ``0.28.1-nightly 2026-03-25`` while the manifest pins the crates.io release
    as ``gitui@0.28.1``.  Exact equality then reads as "not installed" and the
    crate recompiles from source on every run, so a pre-release of version X
    satisfies a plain-X request.
    """
    if _v1_eq(installed, requested):
        return True
    core = installed.split("+", 1)[0].split("-", 1)[0]
    if core == installed:
        return False
    return _v1_eq(core, requested)


class AptManager(CommandManager):
    """APT package manager.

    Check: uses dpkg-query for installed version, apt-cache policy for candidate.
    Needs root privileges for install.

    Mirrors dotfiles setup.sh sudo_run() behavior:
    - Uses sudo when not root (password prompt in interactive terminal)
    - Runs apt-get with DEBIAN_FRONTEND=noninteractive (aligned with scripts/lib/apt.sh,
      decided 2026-10-03: 无人传 --yes 时 dpkg 也走"不问"——无人值守下提问会挂起，
      而 debconf 的默认值就是预期答案；dpkg 的提问不归授权三档管，它是机器对机器的
      配置协商，不是给用户的决策)

    执行策略与 scripts/lib/apt.sh 同源（见 managers/apt_policy.py）：装包前预检源、
    有界超时/重试/锁等待、失败归因到可复制的修复命令。
    """

    needs_privilege = True

    def check(self, item: PlanItem) -> CheckResult:
        """多包清单：任一包缺失 → NOT_SATISFIED；全部在场才做版本判定。

        **latest 的语义是"装了即满足"，不比 apt candidate**——与迁移前该清单的
        实现（scripts/install-system-packages.sh 的 Linux 分支：
        `command -v || dpkg -s || missing`）行为一致。理由：apt 清单装的是系统包，
        若 check 把落后的版本判为
        NOT_SATISFIED，后续 `apt-get install`（不带 pin）会把基线包升级到
        candidate，`./setup.sh` 就变成了"每轮把系统升级一遍"的入口；升级是系统
        管理决策，应由用户显式 `apt upgrade`。需要钉版本对齐用 `name@版本` 走
        精确比对分支，强制重装用 `force = true`。

        **能力视角优先**（`command -v` 命中即满足，dpkg 接住无命令的包）——
        与被替换的清单完全同构。纯 dpkg 视角会把"命令可用但元包无记录"判成未装：
        CI runner 的 /usr/bin/clang 由 clang-18 提供、元包 clang 无 dpkg 记录，
        于是每轮重装、每轮撞授权跳过，幂等性检查报 "check 未识别出
        system-packages"（2026-10-03 实测）。能力视角下冲突检测退为纵深防御
        （状态竞态时才触发）。"""
        pkgs = _package_list(item)
        binary_field = item.strategy.fields.get("bin")
        single = len(pkgs) == 1
        versions: List[str] = []
        for pkg in pkgs:
            name = (binary_field or pkg) if single else pkg
            if shutil.which(name):
                # 命令可用即满足；能力视角不查版本（旧清单也没有版本检查），
                # 要钉版本对齐就用 dpkg 可查的包条目或 force
                continue
            try:
                result = self.runner.run(
                    ["dpkg-query", "-W", "-f=${Version}", pkg],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                # 抛带归因而非返回 CHECK_ERROR：后者的错误消息只有
                # "Check failed for X with manager apt"，CI 日志里查不到现场
                # （2026-10-03 已发生：只有结论、没有包名/路径/异常）。
                raise InstallationError(
                    f"dpkg-query 无法执行，无法检查 {pkg}：{exc!r}。"
                    "系统缺少 dpkg，或 PATH 异常？"
                ) from None
            if result.returncode != 0:
                # 包在 dpkg 数据库里完全未知 → 未装
                return CheckResult.NOT_SATISFIED
            installed_version = result.stdout.strip()
            if not installed_version:
                # rc=0 但版本为空 = 包在数据库里但**未安装**（dpkg-query -W 对
                # not-installed / config-files 状态的记录也返回 0，只是没有版本可填）
                # —— 这是"需要装"，不是异常。CI 实测：裸 runner 上的
                # build-essential 就是这个状态，曾被我误判成 CHECK_ERROR。
                return CheckResult.NOT_SATISFIED
            versions.append(installed_version)

        requested = _selector(item)
        if requested == "latest":
            return CheckResult.SATISFIED
        # 精确 pin（pin 本身只允许单包，见 install_command）
        if all(_v1_eq(installed, requested) for installed in versions):
            return CheckResult.SATISFIED
        return CheckResult.NOT_SATISFIED

    def check_command(self, item: PlanItem) -> List[str]:
        raise NotImplementedError("Use check() instead")

    def install_command(self, item: PlanItem) -> List[str]:
        """Build apt install command: apt-get install -y <pkg...>.

        Mirrors setup.sh: sudo_run apt-get install -y <pkg>
        - Uses 'apt-get' (not 'apt') for scripting compatibility
        - Uses '-y' to auto-confirm (since we already prompted for sudo password)
        - DEBIAN_FRONTEND=noninteractive is added by install()/preflight() at exec
          time (not here): `sudo` env_reset would drop a plain env var, so the
          variable rides in an explicit `env` invocation after sudo — the same
          shape scripts/lib/apt.sh builds.
        - 多包一次装，与旧脚本的批量 `${missing[@]}` 同语义

        版本 pin 只允许单包："多包对齐到同一个 pin 版本"没有真实场景，宁可显式
        报错也不静默猜测语义。
        """
        pkgs = _package_list(item)
        selector = _selector(item)
        if selector != "latest":
            if len(pkgs) != 1:
                raise InstallationError(
                    f"版本 pin 不支持多包清单（pkg={item.strategy.fields['pkg']!r}）；"
                    "请用 @latest，或拆成单包条目分别 pin"
                )
            pkgs = [f"{pkgs[0]}={selector}"]
        return ["apt-get", "install", "-y", *pkgs]

    def _dpkg_installed(self, pkg: str) -> bool:
        """系统视角：dpkg 数据库是否记录了这个包（不比对版本）。

        与 check() 分工：check 要版本值做对齐判定，这里只回答"是不是 apt 装的"，
        供 install() 的缺口分类用（能力视角或 dpkg 任一满足即不是缺口）。
        """
        try:
            result = self.runner.run(
                ["dpkg-query", "-W", "-f=${Version}", pkg],
                check=False,
                capture_output=True,
                text=True,
            )
        except (OSError, InstallationError):
            # fail-open：这是**探测**不是执行。探测失败（dpkg-query 超时、被杀）
            # 当成"未装"继续，把真正的决定交给 apt install——它的失败会被归因。
            # 反之若在这里中断，一个辅助查询就能杀掉整轮安装，且错不在它。
            return False
        return result.returncode == 0 and bool(result.stdout.strip())

    def preflight(self, items: Sequence[PlanItem]) -> None:
        """每轮一次：源健康预检 + 刷新包索引（对齐 scripts/lib/apt.sh 的语义）。

        shell 侧 `apt_run update` 是**脚本开头一次、多包共用**；AptManager 原先两者
        都没有：既不 update（索引陈旧时 apt 报 "Unable to locate package"，而
        attribute_failure 归因不到这一类），又把源预检放在 install 里**逐项**跑
        （每项最多 源数×5 秒探测，19 个包就是 19 轮）。两处一并收敛到这里。

        失败只警告不中断：update 失败 ≠ 装不上（apt 仍用已缓存的索引），而 install
        侧的归因对"缺包/锁/死源"分辨得更细，不该被一个全局预检越俎代庖。
        """
        if not items:
            return
        for line in preflight_source_warnings():
            print(line)
        cmd = _noninteractive(["apt-get", *apt_options(), "update"])
        try:
            # 不 capture：update 的输出要实时可见（shell 侧 apt_run 同样 tee 到终端）
            result = _run_with_sudo(cmd, runner=self.runner, check=False)
        except OSError:
            # 连 sudo 都起不来：留给逐项 install 报错，那里有完整归因
            return
        if result.returncode != 0:
            print(
                f"⚠️  apt-get update failed (exit {result.returncode}); continuing with the "
                "cached index.\n    If a later install reports a missing package, fix the "
                "sources per the check above and re-run.",
                file=sys.stderr,
            )

    def install(self, item: PlanItem) -> None:
        """有界、可见、可归因的 apt 安装（覆盖基类的裸执行）。

        **只装缺口**（能力与 dpkg 双视角都判缺的包）；源预检已上移 preflight
        （每轮一次）；带 apt 命令行超时参数执行、输出回显，失败时翻译成可执行的
        修复动作。

        缺口粒度是三容器矩阵实测的结论（Ubuntu 22.04/24.04/26.04）：能力视角下
        check 已把"命令可用"判为满足，若 install 再把组内能力满足的包（clang 命令
        在、元包无 dpkg 记录）当"非预期已存在"去问询，无 TTY 场景会把**整组**跳过
        ——真正缺的包永远装不上，幂等检查每轮报 "check 未识别出 system-packages"。
        "不覆盖已有实现"由 check 的能力视角更早完成，install 不再问询。
        """
        # 装包名/版本的语义仍只由 install_command 负责（顺带校验 pin 合法性）
        raw_cmd = self.install_command(item)
        pkgs = _package_list(item)
        binary_field = item.strategy.fields.get("bin")
        single = len(pkgs) == 1

        missing = []
        for pkg in pkgs:
            name = (binary_field or pkg) if single else pkg
            if shutil.which(name) or self._dpkg_installed(pkg):
                # 能力视角（与 check 同构）或 dpkg 已记录 = 已满足，不是缺口
                continue
            missing.append(pkg)
        if not missing:
            # check 到 install 之间的竞态窗口（别处刚装上），整组已满足
            return

        # pin 单包时 missing == pkgs 必然成立（否则上面已 return）——走 raw_cmd
        # 保住 pin；latest 多包的缺口子集单独成命令（只装缺的，已满足的不重下）
        cmd_body = raw_cmd[1:] if missing == pkgs else ["install", "-y", *missing]
        pkg_label = ", ".join(missing)
        # 源预检已上移到 preflight（每轮一次）：逐项跑会在慢源上把探测放大成 N 轮
        # apt-get [options] install -y <pkg>：选项放子命令前最安全
        cmd = _noninteractive(["apt-get", *apt_options(), *cmd_body])
        suffix = (
            f"（{len(pkgs) - len(missing)} 个包已满足，跳过）"
            if len(missing) < len(pkgs)
            else ""
        )
        print(
            f"⏳ {' '.join(cmd)}"
            f"（有界：连接 {APT_HTTP_TIMEOUT}s / 重试 {APT_RETRIES} 次 / dpkg 锁 {APT_LOCK_TIMEOUT}s）"
            f"{suffix}"
        )

        kwargs: dict = {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": APT_COMMAND_TIMEOUT,
        }
        try:
            if self.needs_privilege:
                result = _run_with_sudo(cmd, runner=self.runner, **kwargs)
            else:
                result = self.runner.run(cmd, **kwargs)
        except InstallationError as exc:
            # runner 层的超时（带超时前已捕获的输出）→ 仍然走归因
            raise InstallationError(failure_message(pkg_label, str(exc))) from None

        # 执行完再回显：capture 是为了拿日志做归因，不是为了让用户看不到 apt 干了什么
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            log = f"{result.stdout or ''}\n{result.stderr or ''}"
            raise InstallationError(failure_message(pkg_label, log))


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

    Check: verifies the installed binary exists in a cargo bin dir and its
    ``--version`` banner matches the pinned version, falling back to
    ``cargo install --list`` when the banner cannot be parsed.

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
        - Otherwise → both ``pkg.replace("-", "_")`` (Rust default convention)
          and ``pkg`` verbatim, since crates may ship a hyphenated bin target
        """
        fields = item.strategy.fields
        pkg = fields["pkg"]
        requested = _selector(item)

        # Resolve binary name: manifest `bin` field → underscore/hyphen probes
        binary_names = self._cargo_binary_names(pkg, fields)

        # Check if binary exists in cargo bin directories
        bin_path = None
        for binary_name in binary_names:
            for bin_dir in self._cargo_bin_dirs():
                candidate = bin_dir / binary_name
                if candidate.is_file():
                    bin_path = candidate
                    break
            if bin_path is not None:
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
                return CheckResult.SATISFIED if _cargo_v1_eq(installed_version, tag) else CheckResult.NOT_SATISFIED
            if requested == "latest":
                return CheckResult.SATISFIED
            return CheckResult.SATISFIED if _cargo_v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

        if requested == "latest":
            latest_version = self._latest_registry_version(pkg)
            if latest_version is None:
                return CheckResult.CHECK_ERROR
            return CheckResult.SATISFIED if _cargo_v1_eq(installed_version, latest_version) else CheckResult.NOT_SATISFIED

        return CheckResult.SATISFIED if _cargo_v1_eq(installed_version, requested) else CheckResult.NOT_SATISFIED

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
                except (subprocess.TimeoutExpired, InstallationError):
                    # binstall 阶段的超时/失败都只是"没走捷径"，回退源码编译是本条目
                    # 的既定路径（binstall_first）。SubprocessRunner 在 Step 1 把
                    # TimeoutExpired 转成了 InstallationError，只 catch 前者会让超时
                    # 冒泡成整工具失败——CI 里表现为 taplo/tree-sitter 直接 fatal，
                    # 而 30 秒本来就是"binstall 没下完就回退"的正常节奏。
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

    @staticmethod
    def _cargo_binary_names(pkg: str, fields: dict) -> List[str]:
        """Candidate executable names for a cargo-installed package.

        A crate's bin target defaults to the crate name verbatim, so
        ``tree-sitter-grep`` installs a hyphenated ``tree-sitter-grep``;
        renaming to the underscore form is a separate common convention.
        Probing both keeps a hyphenated bin target from reading as "not
        installed" and recompiling from source on every run.
        """
        declared = fields.get("bin")
        if declared:
            return [declared]
        names = [pkg.replace("-", "_"), pkg]
        return list(dict.fromkeys(names))

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
        # --force: we only install when the check says not satisfied; a stale
        # binary already in ~/.cargo/bin (runner images ship some crates) is
        # exactly what we are reconciling, so overwrite instead of erroring.
        command = ["cargo", "install", "--force", fields["pkg"]]
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
