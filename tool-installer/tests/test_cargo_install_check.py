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

import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 目录名 tool-installer 带连字符、不能作包路径，故显式补一层。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


if __name__ == "__main__":
    unittest.main()
