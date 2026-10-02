"""授权与三档判定的契约测试（离线，不碰网络、不需要 TTY）。

政策（migration-plan §4.3 Step 2，2026-10-03 拍板）：

1. **预期操作不问**；**非预期状态要问**——命令已存在但不是 apt 装的，装下去会静默
   多出一份实现（PATH 上两个 git，用哪个取决于顺序，用户毫无察觉）。
2. **`--yes` 全部同意**，一个都不问。
3. **无 TTY 且没传 `--yes`** → 既不擅自决定也不中断：跳过该工具，结束时汇总。
4. `--yes` 管不到 sudo 认证——已核实 sudo 上游（sudo-rs 0.2.x / 传统 1.9.x）不存在
   "用调用方参数完成授权"的机制，这条靠文档不靠测试。

本文件锁住 1–3，以及最要紧的一条：**缺授权绝不中断整轮安装**。
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer import cli, executor  # noqa: E402
from tool_installer.errors import (  # noqa: E402
    AuthorizationRequired,
    InstallationError,
)
from tool_installer.interaction import (  # noqa: E402
    ASSUME_YES_ENV,
    Decision,
    ask,
)
from tool_installer.managers.apt_policy import unexpected_binary_state  # noqa: E402
from tool_installer.managers.base import CheckResult  # noqa: E402
from tool_installer.managers.commands import AptManager  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    InstallPlan,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)


def apt_item(name: str = "libclang-dev") -> PlanItem:
    return PlanItem(
        module_name="system-packages",
        tool=ToolSpec(
            reference=ToolReference(raw=f"{name}@latest", name=name, version="latest"),
            allow_fail=False,
        ),
        strategy=MergedStrategy(tool_name=name, manager="apt", fields={"pkg": name}),
        environment=Environment(os="linux", arch="x86_64"),
    )


class EnvBase(unittest.TestCase):
    """`--yes` 通过环境变量传播，必须保证每个用例起点干净。"""

    def setUp(self) -> None:
        os.environ.pop(ASSUME_YES_ENV, None)
        self.addCleanup(os.environ.pop, ASSUME_YES_ENV, None)
        # CI 的 job env 设了 TOOL_INSTALLER_STRICT=1，会泄漏进测试进程：
        # executor 的汇总从"打印"变"抛错"，同一份测试本地绿、CI 红
        # （已发生：批次 1/1.5 的 Unit tests job errors=2）。
        # 按既有约定隔离（test_executor_tolerated_failures 同模式）。
        self._strict = os.environ.pop("TOOL_INSTALLER_STRICT", None)
        self.addCleanup(self._restore_strict)

    def _restore_strict(self) -> None:
        if self._strict is None:
            os.environ.pop("TOOL_INSTALLER_STRICT", None)
        else:
            os.environ["TOOL_INSTALLER_STRICT"] = self._strict


class AskDecisionTest(EnvBase):
    def test_assume_yes_never_asks(self) -> None:
        os.environ[ASSUME_YES_ENV] = "1"
        with mock.patch("builtins.input", side_effect=AssertionError("不应询问")):
            self.assertEqual(ask("确认?"), Decision.YES)

    def test_no_tty_is_unauthorized_not_a_guess(self) -> None:
        """没有用户在场时既不答 y 也不答 n——那都是替他做决定。"""
        with mock.patch("tool_installer.interaction.is_interactive", return_value=False):
            self.assertEqual(ask("确认?"), Decision.UNAUTHORIZED)

    def test_interactive_default_is_no(self) -> None:
        """空回车 = N：默认不碰用户已有的东西。"""
        with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
            with mock.patch("builtins.input", return_value=""):
                self.assertEqual(ask("确认?"), Decision.NO)

    def test_interactive_yes(self) -> None:
        with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
            with mock.patch("builtins.input", return_value="Y"):
                self.assertEqual(ask("确认?"), Decision.YES)

    def test_garbage_reprompts_then_accepts(self) -> None:
        with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
            with mock.patch("builtins.input", side_effect=["x", "y"]):
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(ask("确认?"), Decision.YES)
        self.assertIn("请输入 y 或 n", out.getvalue())

    def test_closed_input_is_unauthorized(self) -> None:
        with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
            with mock.patch("builtins.input", side_effect=EOFError):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(ask("确认?"), Decision.UNAUTHORIZED)


class UnexpectedStateTest(unittest.TestCase):
    def test_command_exists_but_not_apt_managed(self) -> None:
        state = unexpected_binary_state(
            "git", "git", installed_in_apt=False, which=lambda _: "/usr/local/bin/git"
        )
        self.assertIsNotNone(state)
        self.assertIn("/usr/local/bin/git", state or "")
        self.assertIn("git", state or "")

    def test_absent_command_is_expected(self) -> None:
        self.assertIsNone(
            unexpected_binary_state("git", "git", installed_in_apt=False, which=lambda _: None)
        )

    def test_apt_managed_command_is_expected(self) -> None:
        self.assertIsNone(
            unexpected_binary_state(
                "git", "git", installed_in_apt=True, which=lambda _: "/usr/bin/git"
            )
        )

    def test_manifest_bin_name_is_the_one_probed(self) -> None:
        """包名与命令名不同时（bin 字段），检测必须针对命令名。"""
        probed = []
        result = unexpected_binary_state(
            "fd", "fd-find", installed_in_apt=False, which=lambda name: probed.append(name) or None
        )
        self.assertIsNone(result)
        self.assertEqual(probed, ["fd"])


class AptManagerAuthorizationTest(EnvBase):
    def setUp(self) -> None:
        super().setUp()
        root = mock.patch("tool_installer.managers.base._is_root", return_value=True)
        root.start()
        self.addCleanup(root.stop)

    @staticmethod
    def runner(installed: bool = False) -> mock.Mock:
        """dpkg-query 报未装，其余命令成功——正是"命令在、包不在"的现场。"""
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            if args and args[0] == "dpkg-query":
                return subprocess.CompletedProcess(args, 0 if installed else 1, "1.0" if installed else "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = side_effect
        return runner

    @staticmethod
    def apt_calls(runner: mock.Mock) -> list:
        return [c[0][0] for c in runner.run.call_args_list if c[0][0] and "apt-get" in c[0][0]]

    def test_conflict_without_tty_skips_without_running_apt(self) -> None:
        runner = self.runner()
        with mock.patch(
            "tool_installer.managers.apt_policy.shutil.which",
            return_value="/usr/local/bin/libclang-dev",
        ):
            with mock.patch("tool_installer.interaction.is_interactive", return_value=False):
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(AuthorizationRequired) as ctx:
                        AptManager(runner=runner).install(apt_item())
        self.assertIn("--yes", str(ctx.exception))
        self.assertEqual(self.apt_calls(runner), [])

    def test_conflict_with_assume_yes_installs(self) -> None:
        os.environ[ASSUME_YES_ENV] = "1"
        runner = self.runner()
        with mock.patch(
            "tool_installer.managers.apt_policy.shutil.which",
            return_value="/usr/local/bin/libclang-dev",
        ):
            with redirect_stdout(io.StringIO()):
                AptManager(runner=runner).install(apt_item())
        self.assertEqual(len(self.apt_calls(runner)), 1)

    def test_conflict_interactive_default_skips(self) -> None:
        runner = self.runner()
        with mock.patch(
            "tool_installer.managers.apt_policy.shutil.which",
            return_value="/usr/local/bin/libclang-dev",
        ):
            with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
                with mock.patch("builtins.input", return_value=""):
                    with redirect_stdout(io.StringIO()):
                        with self.assertRaises(AuthorizationRequired) as ctx:
                            AptManager(runner=runner).install(apt_item())
        self.assertIn("用户选择跳过", str(ctx.exception))
        self.assertEqual(self.apt_calls(runner), [])

    def test_conflict_interactive_yes_installs(self) -> None:
        runner = self.runner()
        with mock.patch(
            "tool_installer.managers.apt_policy.shutil.which",
            return_value="/usr/local/bin/libclang-dev",
        ):
            with mock.patch("tool_installer.interaction.is_interactive", return_value=True):
                with mock.patch("builtins.input", return_value="y"):
                    with redirect_stdout(io.StringIO()):
                        AptManager(runner=runner).install(apt_item())
        self.assertEqual(len(self.apt_calls(runner)), 1)

    def test_expected_state_never_asks(self) -> None:
        """命令不存在 = 预期情况，全程不该出现任何问询。"""
        runner = self.runner()
        with mock.patch("tool_installer.managers.apt_policy.shutil.which", return_value=None):
            with mock.patch(
                "builtins.input", side_effect=AssertionError("预期状态不应询问")
            ):
                with redirect_stdout(io.StringIO()):
                    AptManager(runner=runner).install(apt_item())
        self.assertEqual(len(self.apt_calls(runner)), 1)


def plan_with(*names: str) -> InstallPlan:
    items = []
    for name in names:
        item = apt_item(name)
        items.append(item)
    return InstallPlan(items=items)


class ExecutorAuthorizationSkipTest(EnvBase):
    def test_missing_authorization_does_not_abort_the_round(self) -> None:
        """核心契约：缺授权只跳过这一个工具，后面的照装，且必须汇总说出来。"""
        first = mock.Mock()
        first.check.return_value = CheckResult.NOT_SATISFIED
        managers = {"apt": first}

        # 第二个工具要真的被装到：让同一个 manager mock 按工具名区分行为
        calls = {"n": 0}

        def install(item):  # noqa: ANN001
            calls["n"] += 1
            if item.tool.reference.name == "git":
                raise AuthorizationRequired("git: 检测到 git 已存在（/usr/local/bin/git）")
            return None

        first.install.side_effect = install

        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            executor.execute_plan(plan_with("git", "fzf"), managers)

        self.assertEqual(calls["n"], 2, "缺授权后仍应继续安装其余工具")
        text = stderr.getvalue()
        self.assertIn("authorization required", text)
        self.assertIn("git", text)
        self.assertIn("--yes", text)

    def test_strict_mode_does_not_turn_skips_into_failures(self) -> None:
        """拍板语义：无 TTY 跳过 = "没人能授权"，不是失败 —— strict 管失败（tolerated），
        不管"没人可问"。否则无人值守 CI 永远红（实测：STRICT=1 下 clang 已存在于
        /usr/bin、dpkg 无记录，跳过正是不覆盖已有实现的正确选择）。"""
        first = mock.Mock()
        first.check.return_value = CheckResult.NOT_SATISFIED
        first.install.side_effect = AuthorizationRequired("git: 已存在")
        os.environ["TOOL_INSTALLER_STRICT"] = "1"
        self.addCleanup(os.environ.pop, "TOOL_INSTALLER_STRICT", None)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            # 不抛异常 = 核心断言
            executor.execute_plan(plan_with("git"), {"apt": first})
        self.assertIn("authorization required", err.getvalue(), "汇总照打")

    def test_strict_mode_still_fails_on_tolerated_failures(self) -> None:
        """对照：真正的失败（allow_fail 工具装失败）在 strict 下仍然 fatal。"""
        first = mock.Mock()
        first.check.return_value = CheckResult.NOT_SATISFIED
        first.install.side_effect = InstallationError("boom")
        item = apt_item("git")
        allow_fail_item = PlanItem(
            module_name=item.module_name,
            tool=ToolSpec(reference=item.tool.reference, allow_fail=True),
            strategy=item.strategy,
            environment=item.environment,
        )
        os.environ["TOOL_INSTALLER_STRICT"] = "1"
        self.addCleanup(os.environ.pop, "TOOL_INSTALLER_STRICT", None)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(InstallationError):
                executor.execute_plan(InstallPlan(items=[allow_fail_item]), {"apt": first})

    def test_ordinary_failure_still_goes_through_allow_fail(self) -> None:
        """AuthorizationRequired 是子类，但不能因此改变 allow_fail 的语义。"""
        first = mock.Mock()
        first.check.return_value = CheckResult.NOT_SATISFIED
        first.install.side_effect = InstallationError("boom")
        item = apt_item("git")
        allow_fail_item = PlanItem(
            module_name=item.module_name,
            tool=ToolSpec(reference=item.tool.reference, allow_fail=True),
            strategy=item.strategy,
            environment=item.environment,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            executor.execute_plan(InstallPlan(items=[allow_fail_item]), {"apt": first})
        self.assertIn("allow_fail", err.getvalue())


class CliFlagTest(unittest.TestCase):
    def test_yes_flag_is_parsed(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["install", "dev", "--yes"])
        self.assertTrue(args.assume_yes)

    def test_yes_flag_defaults_off(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["install", "dev"])
        self.assertFalse(args.assume_yes)


if __name__ == "__main__":
    unittest.main()
