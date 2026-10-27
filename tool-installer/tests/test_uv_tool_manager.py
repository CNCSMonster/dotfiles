"""uv-tool 管理器的单元测试。

验证重点：
- install_command 必须带上 --force，在 check 判定未满足时强制对齐已存在的陈旧或未跟踪二进制。
- --python 与 --with 参数与 --force 正确组合。
- check() 正确解析 uv tool list 输出并比对版本。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.managers.base import CheckResult
from tool_installer.managers.commands import UvToolManager
from tool_installer.models import (
    Environment,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)


def make_uv_item(
    pkg: str,
    version: str,
    python: str | None = None,
    with_deps: list[str] | None = None,
) -> PlanItem:
    fields: dict = {"pkg": pkg}
    if python:
        fields["python"] = python
    if with_deps:
        fields["with"] = with_deps
    return PlanItem(
        module_name="cargo-tools",
        tool=ToolSpec(
            reference=ToolReference(raw=f"{pkg}@{version}", name=pkg, version=version),
            allow_fail=False,
        ),
        strategy=MergedStrategy(tool_name=pkg, manager="uv-tool", fields=fields),
        environment=Environment(os="linux", arch="x86_64"),
    )


class UvToolManagerInstallCommandTest(unittest.TestCase):
    def test_pinned_version_has_force(self) -> None:
        mgr = UvToolManager()
        item = make_uv_item("tomlq", "0.1.0")
        cmd = mgr.install_command(item)
        self.assertEqual(cmd, ["uv", "tool", "install", "--force", "tomlq==0.1.0"])

    def test_latest_version_has_force(self) -> None:
        mgr = UvToolManager()
        item = make_uv_item("pyright", "latest")
        cmd = mgr.install_command(item)
        self.assertEqual(cmd, ["uv", "tool", "install", "--force", "pyright"])

    def test_optional_python_and_with_options(self) -> None:
        mgr = UvToolManager()
        item = make_uv_item("pkg", "1.0.0", python="3.12", with_deps=["dep1", "dep2"])
        cmd = mgr.install_command(item)
        self.assertEqual(
            cmd,
            ["uv", "tool", "install", "--force", "pkg==1.0.0", "--python", "3.12", "--with", "dep1", "--with", "dep2"],
        )


class UvToolManagerCheckTest(unittest.TestCase):
    def test_satisfied_when_matching(self) -> None:
        runner = mock.Mock()
        runner.run.return_value = mock.Mock(
            returncode=0,
            stdout="pyright v1.1.410\n- pyright\ntomlq v0.1.0\n- tomlq\n",
        )
        mgr = UvToolManager(runner)
        item = make_uv_item("tomlq", "0.1.0")
        self.assertEqual(mgr.check(item), CheckResult.SATISFIED)

    def test_not_satisfied_when_version_mismatch(self) -> None:
        runner = mock.Mock()
        runner.run.return_value = mock.Mock(
            returncode=0,
            stdout="tomlq v0.1.0\n- tomlq\n",
        )
        mgr = UvToolManager(runner)
        item = make_uv_item("tomlq", "0.2.0")
        self.assertEqual(mgr.check(item), CheckResult.NOT_SATISFIED)

    def test_not_satisfied_when_absent(self) -> None:
        runner = mock.Mock()
        runner.run.return_value = mock.Mock(
            returncode=0,
            stdout="pyright v1.1.410\n- pyright\n",
        )
        mgr = UvToolManager(runner)
        item = make_uv_item("tomlq", "0.1.0")
        self.assertEqual(mgr.check(item), CheckResult.NOT_SATISFIED)


if __name__ == "__main__":
    unittest.main()
