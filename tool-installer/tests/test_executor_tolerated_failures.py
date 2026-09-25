"""executor 对被容忍失败的可见性契约测试。

`allow_fail` 的本意是"这一个工具失败不要中断整轮安装"，不是"不要告诉任何人"。
修复前只有 `TOOL_INSTALLER_STRICT=1` 才会在结束时汇总，而非严格模式（= setup.sh，
真实用户唯一入口，从不设置该变量）完全静默——`ci-issue-tracker.md` #7/#8 记录的
两个工具就是这样被无谓重装了数月而无人察觉。

本文件锁住两条契约：
  1. 非严格模式：安装继续、退出码不变，但失败清单必须打印出来。
  2. 严格模式：行为与退出码完全不变，仍然抛 InstallationError。
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer import executor  # noqa: E402
from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers.base import CheckResult  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    InstallPlan,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)


def make_item(name: str, *, allow_fail: bool) -> PlanItem:
    return PlanItem(
        module_name="cargo-tools",
        tool=ToolSpec(
            reference=ToolReference(raw=f"{name}@1.0.0", name=name, version="1.0.0"),
            allow_fail=allow_fail,
        ),
        # 不用 github-release：那条路径会打印 token 报告，与本文件关心的契约无关。
        strategy=MergedStrategy(tool_name=name, manager="script", fields={"path": "x.sh"}),
        environment=Environment(os="linux", arch="x86_64"),
    )


def failing_manager() -> mock.Mock:
    manager = mock.Mock()
    manager.check.return_value = CheckResult.NOT_SATISFIED
    manager.install.side_effect = InstallationError("boom")
    return manager


class ToleratedFailureVisibility(unittest.TestCase):
    def setUp(self) -> None:
        stdouts = mock.patch("sys.stdout", new_callable=io.StringIO)
        stdouts.start()
        self.addCleanup(stdouts.stop)
        self._strict = os.environ.pop("TOOL_INSTALLER_STRICT", None)
        self.addCleanup(self._restore_strict)

    def _restore_strict(self) -> None:
        if self._strict is None:
            os.environ.pop("TOOL_INSTALLER_STRICT", None)
        else:
            os.environ["TOOL_INSTALLER_STRICT"] = self._strict

    def run_plan(self, items, manager):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            executor.execute_plan(InstallPlan(items=items), {"script": manager})
        return stderr.getvalue()

    def test_non_strict_reports_tolerated_failures_without_raising(self):
        item = make_item("gitui", allow_fail=True)
        warning = self.run_plan([item], failing_manager())

        self.assertIn("Tolerated failures", warning)
        self.assertIn("gitui", warning)
        self.assertIn("TOOL_INSTALLER_STRICT=1", warning, "必须告诉用户如何升级为硬失败")

    def test_strict_mode_still_raises_and_names_the_tool(self):
        os.environ["TOOL_INSTALLER_STRICT"] = "1"
        item = make_item("gitui", allow_fail=True)

        with self.assertRaises(InstallationError) as ctx:
            self.run_plan([item], failing_manager())

        self.assertIn("strict mode", str(ctx.exception))
        self.assertIn("gitui", str(ctx.exception))

    def test_non_allow_fail_failure_still_aborts_immediately(self):
        item = make_item("sccache", allow_fail=False)

        with self.assertRaises(InstallationError):
            self.run_plan([item], failing_manager())

    def test_a_hard_failure_is_not_hidden_by_earlier_tolerated_ones(self):
        tolerated = make_item("gitui", allow_fail=True)
        hard = make_item("sccache", allow_fail=False)
        manager = failing_manager()

        with self.assertRaises(InstallationError):
            self.run_plan([tolerated, hard], manager)

    def test_no_tolerated_failures_prints_no_summary(self):
        manager = mock.Mock()
        manager.check.return_value = CheckResult.SATISFIED
        warning = self.run_plan([make_item("bat", allow_fail=True)], manager)

        self.assertEqual(warning, "")


if __name__ == "__main__":
    unittest.main()
