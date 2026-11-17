"""cargo-install 的 check 二进制名解析测试。

关注点：crate 的 `[[bin]]` 名可以就是 crate 名（`tree-sitter-grep` 带连字符），
未必需按 Rust 惯例下划线化。若 check 只认下划线名，已装好的连字符二进制会被判成
NOT_SATISFIED，于是每次 install 都走一遍源码重编译——CI 里 tree-sitter-grep 与
tree-sitter-show-ast 各耗 40s+，且先撞上 cargo 的
"binary `tree-sitter-grep` already exists in destination"。

  - BinaryNames：纯函数 `_cargo_binary_names`，锁 manifest `bin` 优先、
    以及未声明时连字符/下划线两种候选的次序。
  - CheckAgainstFilesystem：临时 bin 目录 + 真二进制，锁住「连字符命名也能
    命中 SATISFIED」和「版本不符仍 NOT_SATISFIED」。
  - PrereleaseVersionTolerance：`_cargo_v1_eq` 只赦免同一发行号的 `-pre` /
    `+build` 后缀（gitui 的 binstall 产物自称 0.28.1-nightly）。
"""

from __future__ import annotations

import contextlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 目录名 tool-installer 带连字符、不能作包路径，故显式补一层。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers.base import CheckResult  # noqa: E402
from tool_installer.managers.commands import CargoInstallManager, _cargo_v1_eq  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)


def make_item(pkg: str, version: str, bin_name: str | None = None) -> PlanItem:
    fields = {"pkg": pkg}
    if bin_name:
        fields["bin"] = bin_name
    return PlanItem(
        module_name="cargo-tools",
        tool=ToolSpec(reference=ToolReference(raw=f"{pkg}@{version}", name=pkg, version=version)),
        strategy=MergedStrategy(tool_name=pkg, manager="cargo-install", fields=fields),
        environment=Environment(os="linux", arch="x86_64"),
    )


class BinaryNames(unittest.TestCase):
    def test_declared_bin_wins_and_is_sole_candidate(self):
        item = make_item("fd-find", "10.1.0", bin_name="fdfind")
        names = CargoInstallManager._cargo_binary_names("fd-find", item.strategy.fields)
        self.assertEqual(names, ["fdfind"])

    def test_underscore_convention_probed_before_hyphen(self):
        names = CargoInstallManager._cargo_binary_names("tree-sitter-grep", {})
        self.assertEqual(names, ["tree_sitter_grep", "tree-sitter-grep"])

    def test_single_name_yields_one_candidate(self):
        self.assertEqual(CargoInstallManager._cargo_binary_names("bat", {}), ["bat"])


class CheckAgainstFilesystem(unittest.TestCase):
    """临时 bin 目录 + 真二进制：不碰开发者真实的 ~/.cargo/bin。"""

    def setUp(self) -> None:
        self._dt = tempfile.TemporaryDirectory()
        self.addCleanup(self._dt.cleanup)
        self.bin_dir = Path(self._dt.name) / "bin"
        self.bin_dir.mkdir()
        self.manager = CargoInstallManager()
        bin_dir = self.bin_dir
        patcher = mock.patch.object(
            CargoInstallManager, "_cargo_bin_dirs", lambda _: [bin_dir]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_binary(self, name: str, version_line: str) -> Path:
        path = self.bin_dir / name
        path.write_text(f"#!/bin/sh\necho '{version_line}'\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def test_hyphenated_binary_is_recognized_as_satisfied(self):
        # 真实事故：tree-sitter-grep 装出来的就是这个名字。
        self.write_binary("tree-sitter-grep", "tree-sitter-grep 0.1.0")
        outcome = self.manager.check(make_item("tree-sitter-grep", "0.1.0"))
        self.assertIs(outcome, CheckResult.SATISFIED)

    def test_underscore_binary_is_recognized_as_satisfied(self):
        self.write_binary("tree_sitter_grep", "tree_sitter_grep 0.1.0")
        outcome = self.manager.check(make_item("tree-sitter-grep", "0.1.0"))
        self.assertIs(outcome, CheckResult.SATISFIED)

    def test_declared_bin_is_still_honored(self):
        self.write_binary("fdfind", "fdfind 10.1.0")
        outcome = self.manager.check(make_item("fd-find", "10.1.0", bin_name="fdfind"))
        self.assertIs(outcome, CheckResult.SATISFIED)

    def test_wrong_version_stays_not_satisfied(self):
        self.write_binary("tree-sitter-show-ast", "tree-sitter-show-ast 0.0.1")
        outcome = self.manager.check(make_item("tree-sitter-show-ast", "0.0.2"))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_absent_binary_is_not_satisfied(self):
        outcome = self.manager.check(make_item("tree-sitter-grep", "0.1.0"))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_nightly_banner_satisfies_the_release_pin(self):
        # gitui 的真实情形：binstall 产物自称 nightly，manifest 钉正式版。
        self.write_binary("gitui", "gitui 0.28.1-nightly 2026-03-25 ()")
        outcome = self.manager.check(make_item("gitui", "0.28.1"))
        self.assertIs(outcome, CheckResult.SATISFIED)


class PrereleaseVersionTolerance(unittest.TestCase):
    """binstall 的 GitHub release 二进制会自称 nightly，manifest 钉的是 crates.io 正式版。

    gitui 就是这个组合：`gitui --version` 输出 `0.28.1-nightly 2026-03-25`，
    tools.toml 钉 `gitui@0.28.1`。严格字符串相等永远不成立，于是 CI 每次 install
    都重装 gitui（见 docs/ci-issue-tracker.md #8）。
    """

    def test_gitui_nightly_banner_satisfies_the_release_pin(self):
        self.assertTrue(_cargo_v1_eq("0.28.1-nightly", "0.28.1"))

    def test_build_metadata_is_forgiven_too(self):
        self.assertTrue(_cargo_v1_eq("1.4.2+2026-03-25", "1.4.2"))

    def test_exact_match_still_works(self):
        self.assertTrue(_cargo_v1_eq("0.28.1", "0.28.1"))
        self.assertTrue(_cargo_v1_eq("v0.28.1", "0.28.1"))

    def test_prerelease_of_another_line_does_not_match(self):
        # 只赦免同一发行号的预发布后缀，跨版本仍要重装。
        self.assertFalse(_cargo_v1_eq("0.29.0-nightly", "0.28.1"))
        self.assertFalse(_cargo_v1_eq("0.28.1", "0.29.0"))

    def test_requested_prerelease_is_not_downgraded(self):
        # 钉 0.28.1-nightly 时，装上正式版 0.28.1 不算满足。
        self.assertFalse(_cargo_v1_eq("0.28.1", "0.28.1-nightly"))


class BinstallFallback(unittest.TestCase):
    """binstall 阶段的超时/失败都必须静默回退源码编译——这是 binstall_first 的既定语义。

    回归记录（2026-10-03）：SubprocessRunner 在 Step 1 把 TimeoutExpired 包装成
    InstallationError 后，只 catch 前者的回退接不住，30 秒超时（binstall 没下完
    就回退的正常节奏）冒泡成整工具失败；CI 里 taplo（quickinstall 资产 404）与
    tree-sitter-* 直接 fatal，从 Step 1 那次 push 开始红。
    """

    @staticmethod
    def item() -> PlanItem:
        item = make_item("taplo-cli", "0.10.0")
        item.strategy.fields["binstall_first"] = True
        return item

    @staticmethod
    def runner_with(calls: list) -> mock.Mock:
        """首调（binstall）抛超时形态的 InstallationError，后续 cargo install 成功。"""
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            calls.append(list(args))
            if len(calls) == 1:
                raise InstallationError("Command timed out after 30s: cargo")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = side_effect
        return runner

    def test_timeout_wrapped_as_installation_error_still_falls_back(self) -> None:
        calls: list = []
        runner = self.runner_with(calls)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(CargoInstallManager, "_ensure_binstall", return_value="/bin/cargo-binstall")
            )
            stack.enter_context(
                mock.patch.object(
                    CargoInstallManager,
                    "_binstall_command",
                    return_value=["cargo", "binstall", "--no-confirm"],
                )
            )
            CargoInstallManager(runner=runner).install(self.item())

        self.assertEqual(len(calls), 2, "binstall 超时后应回退一次源码 cargo install")
        self.assertIn("binstall", calls[0], "第一次应是 binstall 调用")
        self.assertIn("install", calls[1], "回退到 cargo install")
        self.assertIn("taplo-cli", " ".join(calls[1]))

    def test_binstall_nonzero_exit_also_falls_back(self) -> None:
        """404 时 binstall 以非零退出，回退路径与超时一致。"""
        calls: list = []
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            calls.append(list(args))
            if len(calls) == 1:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = side_effect
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(CargoInstallManager, "_ensure_binstall", return_value="/bin/cargo-binstall")
            )
            stack.enter_context(
                mock.patch.object(
                    CargoInstallManager,
                    "_binstall_command",
                    return_value=["cargo", "binstall", "--no-confirm"],
                )
            )
            CargoInstallManager(runner=runner).install(self.item())

        self.assertEqual(len(calls), 2)

    def test_binstall_command_generation(self) -> None:
        mgr = CargoInstallManager(runner=mock.Mock())
        item = self.item()
        cmd = mgr._binstall_command(item, ["cargo", "binstall"])
        self.assertEqual(
            cmd,
            ["cargo", "binstall", "-y", "--disable-strategies", "compile", "--version", "0.10.0", "taplo-cli"],
        )

        custom_fields = {
            "pkg": "custom-cli",
            "binstall_fallback_compile": True,
        }
        cmd2 = mgr._binstall_command(item, ["/usr/bin/cargo-binstall"], fields=custom_fields)
        self.assertEqual(
            cmd2,
            ["/usr/bin/cargo-binstall", "-y", "--version", "0.10.0", "custom-cli"],
        )


class NoAutoDownload(unittest.TestCase):
    """离线回归：_ensure_binstall 不得再隐式从 GitHub releases/latest 下载未钉版、
    无摘要的 cargo-binstall。

    约束（最小修复，不破坏既有功能）：
    - 不再自动 latest 下载；删除下载 helper 与 URL/latest 命令；
    - 已有 cargo-binstall（PATH 或旧 ~/.cargo/bin）须 -V 验证通过后照常使用；
    - 缺失/验证不过时静默回退 cargo install（binstall_first 既定语义）；
    - binstall 命令生成与执行路径保持正常。

    全部离线：runner 为 Mock，urllib.request.urlopen 被拦截，绝不联网/下载/安装。
    """

    @staticmethod
    def item() -> PlanItem:
        item = make_item("taplo-cli", "0.10.0")
        item.strategy.fields["binstall_first"] = True
        return item

    def setUp(self) -> None:
        self._dt = tempfile.TemporaryDirectory()
        self.addCleanup(self._dt.cleanup)
        self.home_bin = Path(self._dt.name) / "bin"
        self.home_bin.mkdir()

    def _no_network(self, stack: contextlib.ExitStack) -> list:
        """拦截一切 urllib 下载入口，返回被尝试调用的记录（应始终为空）。"""
        attempted: list = []

        def blocked(*args, **kwargs):  # noqa: ANN002, ANN003
            attempted.append(("urlopen", args, kwargs))
            raise AssertionError("不应发生任何网络下载 (urllib.request.urlopen)")

        stack.enter_context(mock.patch("urllib.request.urlopen", side_effect=blocked))
        return attempted

    def _write_binstall(self) -> Path:
        binary = self.home_bin / "cargo-binstall"
        binary.write_text("#!/bin/sh\necho 'cargo-binstall 1.0.0'\n")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return binary

    def test_source_has_no_download_url_latest_command_or_helpers(self) -> None:
        """源码级断言：latest 下载 URL / gh release latest 命令 / 下载 helper 全部消失。"""
        import tool_installer.managers.commands as cmdmod

        source = Path(cmdmod.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "releases/latest/download",
            '"release", "download"',
            '"gh", "release", "download"',
            "urlopen(url",
            "_BINSTALL_RELEASE_BASE",
            "_BINSTALL_TARGETS",
            "_download_binstall",
            "_extract_binstall",
        ):
            self.assertNotIn(forbidden, source, f"残留下载/自举代码: {forbidden}")

        for attr in ("_download_binstall", "_extract_binstall", "_BINSTALL_RELEASE_BASE", "_BINSTALL_TARGETS"):
            self.assertFalse(hasattr(CargoInstallManager, attr), f"下载 helper 仍存在: {attr}")

    def test_existing_path_binstall_is_verified_then_used(self) -> None:
        """PATH 上已有 cargo-binstall：验证通过后返回 cargo binstall 调用，且绝不触网。"""
        runner = mock.Mock()
        mgr = CargoInstallManager(runner=runner)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch("tool_installer.managers.commands.shutil.which", return_value="/usr/bin/cargo-binstall")
            )
            verify = stack.enter_context(mock.patch.object(CargoInstallManager, "_verified_binstall", return_value=True))
            attempted = self._no_network(stack)
            out = mgr._ensure_binstall(self.item())

        self.assertEqual(out, ["cargo", "binstall"])
        verify.assert_called_once_with("cargo-binstall")
        self.assertEqual(attempted, [], "不得触发任何下载")

    def test_old_home_binary_still_usable(self) -> None:
        """旧 ~/.cargo/bin/cargo-binstall（无 PATH 命中）验证通过后仍可直接使用。"""
        binary = self._write_binstall()
        runner = mock.Mock()
        mgr = CargoInstallManager(runner=runner)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("tool_installer.managers.commands.shutil.which", return_value=None))
            stack.enter_context(mock.patch.object(CargoInstallManager, "_cargo_home_bin", return_value=self.home_bin))
            verify = stack.enter_context(mock.patch.object(CargoInstallManager, "_verified_binstall", return_value=True))
            attempted = self._no_network(stack)
            out = mgr._ensure_binstall(self.item())

        self.assertEqual(out, [str(binary)])
        verify.assert_called_once_with(str(binary))
        self.assertEqual(attempted, [], "不得触发任何下载")

    def test_missing_binstall_never_downloads_and_falls_back(self) -> None:
        """缺失时：不下载、不执行 latest/gh/urlopen，直接回退一次 cargo install。"""
        calls: list = []
        runner = mock.Mock()

        def run(args, **kwargs):  # noqa: ANN001, ANN003
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        mgr = CargoInstallManager(runner=runner)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("tool_installer.managers.commands.shutil.which", return_value=None))
            stack.enter_context(mock.patch.object(CargoInstallManager, "_cargo_home_bin", return_value=self.home_bin))
            stack.enter_context(
                mock.patch("tool_installer.managers.commands.detect_github_token", return_value=(None, None))
            )
            attempted = self._no_network(stack)
            self.assertIsNone(mgr._ensure_binstall(self.item()), "缺失时应返回 None 而非下载")
            mgr.install(self.item())

        self.assertEqual(attempted, [], "缺失时不得触网下载")
        self.assertEqual(len(calls), 1, "缺失时应直接回退一次 cargo install，不跑 binstall/下载")
        joined = " ".join(calls[0])
        self.assertIn("cargo", joined)
        self.assertIn("install", joined)
        self.assertIn("taplo-cli", joined)
        for forbidden in ("gh", "release", "download", "latest", "binstall", "urlopen"):
            self.assertNotIn(forbidden, joined, f"不得出现下载/自举命令: {forbidden}")

    def test_unverifiable_existing_binstall_still_falls_back(self) -> None:
        """已有但 -V 验证失败的 bin 不得被使用，仍回退 cargo install。"""
        calls: list = []
        runner = mock.Mock()

        def run(args, **kwargs):  # noqa: ANN001, ANN003
            calls.append(list(args))
            if "-V" in args:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        mgr = CargoInstallManager(runner=runner)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch("tool_installer.managers.commands.shutil.which", return_value="/usr/bin/cargo-binstall")
            )
            stack.enter_context(mock.patch.object(CargoInstallManager, "_cargo_home_bin", return_value=self.home_bin))
            stack.enter_context(
                mock.patch("tool_installer.managers.commands.detect_github_token", return_value=(None, None))
            )
            attempted = self._no_network(stack)
            self.assertIsNone(mgr._ensure_binstall(self.item()), "验证不过不应返回可用调用")
            calls.clear()
            mgr.install(self.item())

        self.assertEqual(attempted, [])
        # install() 内部会再次调一次 _ensure_binstall，故 -V 验证会出现两次；
        # 真正要断言的是：没有任何 binstall 安装命令，且恰好回退一次 cargo install。
        install_calls = [c for c in calls if "--force" in c]
        self.assertEqual(len(install_calls), 1, "应回退一次 cargo install")
        joined_install = " ".join(install_calls[0])
        self.assertIn("cargo", joined_install)
        self.assertIn("install", joined_install)
        self.assertIn("taplo-cli", joined_install)
        for c in calls:
            joined = " ".join(c)
            self.assertNotIn("--disable-strategies", joined, "不得执行 binstall 安装命令")
            for forbidden in ("gh", "release", "download", "latest", "urlopen"):
                self.assertNotIn(forbidden, joined, f"不得出现下载/自举命令: {forbidden}")

    def test_binstall_command_runs_normally_when_verified(self) -> None:
        """已验证的 home bin 走正常 binstall 命令（rc=0 即返回），不回退源码编译。"""
        binary = self._write_binstall()
        calls: list = []
        runner = mock.Mock()

        def run(args, **kwargs):  # noqa: ANN001, ANN003
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        mgr = CargoInstallManager(runner=runner)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("tool_installer.managers.commands.shutil.which", return_value=None))
            stack.enter_context(mock.patch.object(CargoInstallManager, "_cargo_home_bin", return_value=self.home_bin))
            stack.enter_context(mock.patch.object(CargoInstallManager, "_verified_binstall", return_value=True))
            stack.enter_context(
                mock.patch("tool_installer.managers.commands.detect_github_token", return_value=(None, None))
            )
            attempted = self._no_network(stack)
            mgr.install(self.item())

        self.assertEqual(attempted, [])
        self.assertEqual(len(calls), 1, "binstall 成功即返回，不应回退 cargo install")
        joined = " ".join(calls[0])
        self.assertIn(str(binary), joined)
        self.assertIn("taplo-cli", joined)
        self.assertIn("--disable-strategies", joined)
        self.assertNotIn("--force", joined, "不应落入 cargo install 回退")


if __name__ == "__main__":
    unittest.main()
