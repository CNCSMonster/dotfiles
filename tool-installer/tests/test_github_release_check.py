"""github-release 的 version_probe check 语义测试。

关注点：目标路径已存在文件、但它不是本安装器放的那个工具时，check 应当收敛到
NOT_SATISFIED（触发覆盖安装），而不是 CHECK_ERROR（executor 会抛 InstallationError
并中断整个安装流程）。

分三类：
  - ProbeOutputContract：桩掉 subprocess.run，只锁「探测输出/退出码 → CheckResult」的映射，
    以及真·环境错误仍保持 CHECK_ERROR。
  - RealProbe：不落桩，真实执行临时 HOME 下的假二进制，覆盖 is_file / 坏软链 / 不可执行 /
    非零退出码这条真实文件系统路径。
  - Executor*：锁住 executor 对 NOT_SATISFIED / CHECK_ERROR 的既有分工。
"""

from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 目录名 tool-installer 带连字符、不能作包路径，故显式补一层（unittest 的
# `-t tool-installer` 之外，直接 python3 -m unittest tests.test_x 也要能跑）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer import environment as env_module  # noqa: E402
from tool_installer import executor  # noqa: E402
from tool_installer.environment import refresh_path  # noqa: E402
from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers import github_release as gr  # noqa: E402
from tool_installer.managers.base import CheckResult  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    InstallPlan,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)

PROBE = {"command": ["{bin}", "--version"], "regex": r"version v?(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"}

GO_YQ_OUTPUT = "yq (https://github.com/mikefarah/yq/) version v4.53.3\n"
PY_YQ_OUTPUT = "yq 3.4.3\n"


def make_item(
    probe=PROBE,
    version="4.53.3",
    install_name="yq",
    name="yq",
    repo="mikefarah/yq",
) -> PlanItem:
    fields = {"repo": repo, "asset": "yq_linux_amd64.tar.gz", "bin": "yq_linux_amd64"}
    if install_name:
        fields["install_name"] = install_name
    if probe:
        fields["version_probe"] = probe
    return PlanItem(
        module_name="editors",
        tool=ToolSpec(reference=ToolReference(raw=f"{name}@{version}", name=name, version=version)),
        strategy=MergedStrategy(tool_name=name, manager="github-release", fields=fields),
        environment=Environment(os="linux", arch="x86_64"),
    )


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["yq", "--version"], returncode=returncode, stdout=stdout, stderr=""
    )


def github_manager_mock() -> mock.Mock:
    """A manager stand-in whose token report is a plain string.

    _execute_item does `"not configured" in source`, so a bare Mock() return value
    would raise TypeError for the wrong reason.
    """
    manager = mock.Mock()
    manager.get_token_report.return_value = "env:GITHUB_TOKEN"
    return manager


class _Capture(list):
    """stdout sink that records writes; read it back with read()."""

    def write(self, s):
        self.append(s)
        return len(s)

    def flush(self) -> None:
        pass

    def read(self) -> str:
        return "".join(self)


class ProbeOutputContract(unittest.TestCase):
    """HOME 指向临时目录、subprocess.run 用桩：只锁映射关系。"""

    def setUp(self) -> None:
        self._dt = tempfile.TemporaryDirectory()
        self.addCleanup(self._dt.cleanup)
        self.fake_home = Path(self._dt.name) / "home"
        (self.fake_home / ".local" / "bin").mkdir(parents=True)

    def fake_binary(self, name: str = "yq") -> None:
        (self.fake_home / ".local" / "bin" / name).write_text("#!/bin/sh\n")

    def run_check(self, item, *, result=None, raises=None, home=True, binary=True, latest=None):
        manager = gr.GithubReleaseManager()
        if binary:
            self.fake_binary(item.strategy.fields.get("install_name", item.tool.reference.name))
        environ = {"HOME": str(self.fake_home)} if home else {}
        run = mock.Mock(side_effect=raises) if raises else mock.Mock(return_value=result or completed())
        patches = [
            mock.patch.object(gr.os, "environ", environ),
            mock.patch.object(gr.subprocess, "run", run),
        ]
        if latest is not None:
            patches.append(mock.patch.object(manager, "_latest_tag", mock.Mock(return_value=latest)))
        with mock.patch("sys.stdout", new_callable=_Capture) as cap:
            for p in patches:
                p.start()
            self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
            outcome = manager.check(item)
        return outcome, cap.read()

    # ── 既有契约（不该被本次改动破坏）──

    def test_no_probe_is_not_check_capable(self):
        self.assertIs(self.run_check(make_item(probe=None))[0], CheckResult.NOT_SATISFIED)

    def test_missing_binary_is_not_satisfied(self):
        outcome, _ = self.run_check(make_item(install_name="absent-tool"), binary=False)
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_matching_pinned_version_is_satisfied(self):
        """钉死版本且匹配 → SATISFIED，绝不能被 probe 降级改成无谓重下。"""
        outcome, _ = self.run_check(make_item(version="4.53.3"), result=completed(GO_YQ_OUTPUT))
        self.assertIs(outcome, CheckResult.SATISFIED)

    def test_different_pinned_version_is_not_satisfied(self):
        outcome, _ = self.run_check(make_item(version="4.53.3"), result=completed("yq version v4.40.1\n"))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_latest_matching_release_tag_is_satisfied(self):
        outcome, _ = self.run_check(make_item(version="latest"), result=completed(GO_YQ_OUTPUT), latest="v4.53.3")
        self.assertIs(outcome, CheckResult.SATISFIED)

    def test_latest_newer_than_installed_is_not_satisfied(self):
        outcome, _ = self.run_check(make_item(version="latest"), result=completed(GO_YQ_OUTPUT), latest="v4.60.0")
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_home_unset_stays_check_error(self):
        """HOME 缺失是环境问题，重装也不会好转，保持 CHECK_ERROR。"""
        self.assertIs(self.run_check(make_item(), home=False)[0], CheckResult.CHECK_ERROR)

    def test_unresolvable_latest_tag_stays_check_error(self):
        """latest 且拿不到 tag 是网络/仓库问题，保持 CHECK_ERROR。"""
        manager = gr.GithubReleaseManager()
        self.fake_binary()
        with mock.patch.object(gr.os, "environ", {"HOME": str(self.fake_home)}), mock.patch.object(
            gr.subprocess, "run", mock.Mock(return_value=completed(GO_YQ_OUTPUT))
        ), mock.patch.object(manager, "_latest_tag", side_effect=InstallationError("boom")):
            self.assertIs(manager.check(make_item(version="latest")), CheckResult.CHECK_ERROR)

    def test_invalid_regex_stays_check_error(self):
        """regex 在 strategy 解析期已校验，真出现说明是配置错误，不能当成未安装。"""
        bad = {"command": ["{bin}", "--version"], "regex": "version (?P<version>[0-9+"}
        outcome, _ = self.run_check(make_item(probe=bad), result=completed(GO_YQ_OUTPUT))
        self.assertIs(outcome, CheckResult.CHECK_ERROR)

    # ── 本次修复：探测失败要收敛，不要中断整份计划 ──

    def test_heterogeneous_tool_output_triggers_overwrite(self):
        """同名异构工具（Python 版 yq 输出 "yq 3.4.3"）→ 覆盖安装并告警。"""
        outcome, text = self.run_check(make_item(), result=completed(PY_YQ_OUTPUT))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)
        self.assertIn("覆盖", text)

    def test_warning_stays_one_bounded_line(self):
        """多行 / 超长输出不能把告警撑成一段日志噪声。"""
        spam = ("booom\n" + "x" * 500 + "\ntraceback line\n")
        outcome, text = self.run_check(make_item(), result=completed(spam))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertLess(len(text.strip()), 200)

    def test_nonzero_exit_triggers_overwrite(self):
        """旧二进制退出码非 0（如动态库缺失 127）→ 覆盖安装。"""
        outcome, _ = self.run_check(make_item(), result=completed("error: not found", returncode=127))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_unrunnable_binary_triggers_overwrite(self):
        """文件存在但不可执行（OSError）→ 覆盖安装。"""
        outcome, _ = self.run_check(make_item(), raises=OSError("Exec format error"))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_timeout_triggers_overwrite(self):
        outcome, _ = self.run_check(
            make_item(), raises=subprocess.TimeoutExpired(cmd=["yq", "--version"], timeout=30)
        )
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_empty_captured_version_triggers_overwrite(self):
        probe = {"command": ["{bin}", "-V"], "regex": r"V(?P<version>.*)"}
        outcome, _ = self.run_check(make_item(probe=probe), result=completed("xV\n"))
        self.assertIs(outcome, CheckResult.NOT_SATISFIED)

    def test_warning_is_printed_before_returning_not_satisfied(self):
        _, text = self.run_check(make_item(), result=completed(PY_YQ_OUTPUT))
        self.assertIn("⚠️", text)

    def test_warning_names_the_binary_when_it_differs_from_tool(self):
        """install_name 与 tool name 不同（如按插件名落盘）时告警要指到真身。"""
        item = make_item(name="kubectl", install_name="kubectl-aws")
        _, text = self.run_check(item, result=completed("some plugin\n"))
        self.assertIn("kubectl-aws", text)


class ExecutorHandlesProbeResults(unittest.TestCase):
    """锁住 executor 与 check 结果的分工：NOT_SATISFIED 装、CHECK_ERROR 抛。"""

    def setUp(self) -> None:
        patcher = mock.patch("sys.stdout", new_callable=_Capture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_not_satisfied_runs_install(self):
        item = make_item()
        manager = github_manager_mock()
        manager.check.return_value = CheckResult.NOT_SATISFIED
        with mock.patch.object(env_module, "refresh_path", mock.Mock(return_value=False)):
            executor._execute_item(item, manager, token_reported=False)
        manager.check.assert_called_once_with(item)
        manager.install.assert_called_once_with(item)

    def test_satisfied_skips_install(self):
        item = make_item()
        manager = github_manager_mock()
        manager.check.return_value = CheckResult.SATISFIED
        with mock.patch.object(env_module, "refresh_path", mock.Mock(return_value=False)):
            executor._execute_item(item, manager, token_reported=False)
        manager.install.assert_not_called()

    def test_persistent_check_error_still_raises(self):
        item = make_item()
        manager = github_manager_mock()
        manager.check.return_value = CheckResult.CHECK_ERROR
        with mock.patch.object(env_module, "refresh_path", mock.Mock(return_value=False)):
            with self.assertRaises(InstallationError):
                executor._execute_item(item, manager, token_reported=False)
        manager.install.assert_not_called()

    def test_check_error_retries_after_refresh_path_then_installs(self):
        item = make_item()
        manager = github_manager_mock()
        manager.check.side_effect = [CheckResult.CHECK_ERROR, CheckResult.NOT_SATISFIED]
        with mock.patch.object(env_module, "refresh_path", mock.Mock(return_value=True)) as rp:
            executor._execute_item(item, manager, token_reported=False)
        rp.assert_called_once_with()
        self.assertEqual(manager.check.call_count, 2)
        manager.install.assert_called_once_with(item)


class ExecutePlanPublicApi(unittest.TestCase):
    """走公开入口 execute_plan，不依赖 _execute_item 这个私有名字。

    只锁本次关心的两条契约：NOT_SATISFIED 触发覆盖安装、持续 CHECK_ERROR 仍然抛。
    """

    def setUp(self) -> None:
        patcher = mock.patch("sys.stdout", new_callable=_Capture)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.refresh = mock.Mock(return_value=False)
        patcher2 = mock.patch.object(env_module, "refresh_path", self.refresh)
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def execute(self, check_result):
        item = make_item()
        manager = github_manager_mock()
        manager.check.return_value = check_result
        executor.execute_plan(InstallPlan(items=[item]), {"github-release": manager})
        return item, manager

    def test_probe_inconclusive_overwrites_via_public_api(self):
        item, manager = self.execute(CheckResult.NOT_SATISFIED)
        manager.install.assert_called_once_with(item)

    def test_persistent_check_error_still_raises_via_public_api(self):
        with self.assertRaises(InstallationError):
            self.execute(CheckResult.CHECK_ERROR)


class RealProbe(unittest.TestCase):
    """真实文件系统 + 真实 subprocess：只动临时 HOME，不碰仓库文件。"""

    def setUp(self) -> None:
        self._dt = tempfile.TemporaryDirectory()
        self.addCleanup(self._dt.cleanup)
        self.bin_dir = Path(self._dt.name) / ".local" / "bin"
        self.bin_dir.mkdir(parents=True)
        patcher = mock.patch.object(gr.os, "environ", {"HOME": self._dt.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.warning = ""

    def write_binary(self, body: str, *, executable: bool = True, name: str = "yq") -> Path:
        path = self.bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def check(self, item=None) -> CheckResult:
        with mock.patch("sys.stdout", new_callable=_Capture) as cap:
            outcome = gr.GithubReleaseManager().check(item or make_item())
        self.warning = cap.read()
        return outcome

    def test_real_binary_reporting_matching_version_is_satisfied(self):
        self.write_binary(f"echo '{GO_YQ_OUTPUT.strip()}'")
        self.assertIs(self.check(), CheckResult.SATISFIED)

    def test_real_foreign_binary_is_overwritten(self):
        self.write_binary(f"echo '{PY_YQ_OUTPUT.strip()}'")
        self.assertIs(self.check(), CheckResult.NOT_SATISFIED)
        self.assertIn("同名异构工具", self.warning)

    def test_broken_symlink_is_not_satisfied(self):
        (self.bin_dir / "yq").symlink_to(self.bin_dir / "does-not-exist")
        self.assertIs(self.check(), CheckResult.NOT_SATISFIED)

    def test_non_executable_file_is_not_satisfied(self):
        self.write_binary(f"echo '{GO_YQ_OUTPUT.strip()}'", executable=False)
        self.assertIs(self.check(), CheckResult.NOT_SATISFIED)

    def test_nonzero_exit_code_is_not_satisfied(self):
        self.write_binary("echo 'fatal: missing shared library' >&2; exit 127")
        self.assertIs(self.check(), CheckResult.NOT_SATISFIED)

    def test_empty_stdout_is_not_satisfied(self):
        self.write_binary("true")
        self.assertIs(self.check(), CheckResult.NOT_SATISFIED)

    def test_probe_runs_the_target_path_not_a_same_named_command_on_path(self):
        """probe 必须打到家目录那个二进制，不能被 PATH 上的同名工具顶替。"""
        self.write_binary("echo 'REAL-TARGET version v4.53.3'")
        item = make_item(
            probe={"command": ["{bin}", "--version"], "regex": r"REAL-TARGET version v?(?P<version>[\d.]+)"}
        )
        self.assertIs(self.check(item), CheckResult.SATISFIED)

    def test_probe_passes_timeout_to_subprocess(self):
        """真跑一次，只旁听参数：证明 30s 上限确实传给了 subprocess.run。

        真超时路径的收敛由 ProbeOutputContract.test_timeout_triggers_overwrite 覆盖
        （那里抛 TimeoutExpired），不在这里等 30 秒。
        """
        self.write_binary(f"echo '{GO_YQ_OUTPUT.strip()}'")
        real_run = subprocess.run
        seen = {}

        def spy(cmd, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            return real_run(cmd, **kwargs)

        with mock.patch.object(gr.subprocess, "run", spy):
            outcome = self.check()
        self.assertEqual(seen["timeout"], 30)
        self.assertIs(outcome, CheckResult.SATISFIED)


class RefreshPathContract(unittest.TestCase):
    def test_refresh_path_is_exported_and_used_by_executor(self):
        self.assertTrue(callable(refresh_path))
        self.assertIn("refresh_path", Path(executor.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
