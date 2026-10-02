"""apt 执行策略的契约测试（离线，不碰网络、不碰 /etc/apt）。

锁住三件事，都是 2026-09 事故（apt 源指向腾讯云内网 169.254.0.3，setup.sh 静默挂起
4 分钟）暴露出来的缺口：

  1. **有界** —— 连接超时/重试/锁等待的数值必须与 scripts/lib/apt.sh 一致，
     且任何外部命令都不允许无限等（SubprocessRunner 的兜底 timeout）。
  2. **可归因** —— apt 的每类失败都要翻译成"原因 + 可直接执行的修复命令"，
     尤其是云内网专用源，必须给出换公网源的 sed。
  3. **只诊断不改写** —— 源预检只读 /etc/apt、只输出提示，绝不修改用户源配置。
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers import apt_policy  # noqa: E402
from tool_installer.managers.apt_policy import (  # noqa: E402
    apt_options,
    attribute_failure,
    failure_message,
    is_private_ip,
    iter_source_uris,
    preflight_source_warnings,
)
from tool_installer.managers.base import (  # noqa: E402
    DEFAULT_COMMAND_TIMEOUT,
    SubprocessRunner,
)
from tool_installer.managers.commands import AptManager  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)

TENCENTYUN_LOG = """\
Get:1 http://mirrors.tencentyun.com/ubuntu noble/main amd64 Packages [28.8 MB]
Fetched 2,896 kB in 4min 22s (11.0 kB/s)
E: Failed to fetch http://mirrors.tencentyun.com/ubuntu/pool/universe/l/llvm-defaults/libclang-dev_18.0-59%7eexp2_amd64.deb  Could not connect to mirrors.tencentyun.com:80 (169.254.0.3), connection timed out
E: Unable to fetch some archives, maybe run apt-get update or try with --fix-missing?
"""


def apt_item(version: str = "latest") -> PlanItem:
    return PlanItem(
        module_name="system-packages",
        tool=ToolSpec(
            reference=ToolReference(raw="libclang-dev@latest", name="libclang-dev", version=version),
            allow_fail=False,
        ),
        strategy=MergedStrategy(
            tool_name="libclang-dev", manager="apt", fields={"pkg": "libclang-dev"}
        ),
        environment=Environment(os="linux", arch="x86_64"),
    )


class AptOptionsTest(unittest.TestCase):
    def test_bounded_options_match_shell_side(self) -> None:
        """数值必须与 scripts/lib/apt.sh 的 APT_OPTS 一致（政策见 migration-plan §4.3）。"""
        self.assertEqual(apt_policy.APT_HTTP_TIMEOUT, 30)
        self.assertEqual(apt_policy.APT_RETRIES, 1)
        self.assertEqual(apt_policy.APT_LOCK_TIMEOUT, 60)

        opts = apt_options()
        self.assertIn("Acquire::http::Timeout=30", opts)
        self.assertIn("Acquire::https::Timeout=30", opts)
        self.assertIn("Acquire::Retries=1", opts)
        self.assertIn("DPkg::Lock::Timeout=60", opts)

    def test_runner_has_a_finite_fallback(self) -> None:
        """任何外部命令都必须有上限——这正是事故里缺失的那道保险。"""
        self.assertGreater(DEFAULT_COMMAND_TIMEOUT, 0)
        self.assertLessEqual(DEFAULT_COMMAND_TIMEOUT, 3600)


class AttributionTest(unittest.TestCase):
    """每类失败都要给出原因与可执行动作，而不是一句 "Install failed"。"""

    CASES = [
        (
            "云内网专用源",
            TENCENTYUN_LOG,
            ["腾讯云内网源", "mirrors.cloud.tencent.com"],
        ),
        (
            "普通源不可达",
            "E: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/noble/InRelease\n"
            "  Could not connect to 93.184.216.34:80 (93.184.216.34), connection timed out",
            ["apt 源获取失败", "公网源"],
        ),
        (
            "DNS 失败",
            "Err:1 http://archive.ubuntu.com/ubuntu InRelease\n"
            "  Temporary failure resolving 'archive.ubuntu.com'",
            ["DNS 解析失败"],
        ),
        (
            "dpkg 锁",
            "E: Could not get lock /var/lib/dpkg/lock-frontend - open (11: Resource temporarily unavailable)",
            ["前端锁被占用", "apt-daily"],
        ),
        (
            "无 sudo 终端",
            "sudo: a password is required",
            ["需要 sudo 权限", "sudo -v"],
        ),
        (
            "权限不足",
            "E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)",
            ["权限不足"],
        ),
        (
            "命令超时",
            "Command timed out after 1800s: apt-get",
            ["命令超时", "169.254.x"],
        ),
        (
            "未知失败仍要可见",
            "E: Sub-process /usr/bin/dpkg returned an error code (2)",
            ["未识别的失败模式"],
        ),
    ]

    def test_attribution_table(self) -> None:
        for name, log, expected in self.CASES:
            with self.subTest(case=name):
                message = attribute_failure(log)
                for needle in expected:
                    self.assertIn(needle, message)

    def test_dns_is_attributed_before_unreachable_source(self) -> None:
        """DNS 必须先判，否则 DNS 故障会被误归因为"源坏了，去换源"。"""
        log = "E: Failed to fetch http://x/ubuntu InRelease\n  Temporary failure resolving 'x'"
        self.assertIn("DNS 解析失败", attribute_failure(log))

    def test_failure_message_keeps_base_class_first_line(self) -> None:
        message = failure_message("libclang-dev", TENCENTYUN_LOG)
        self.assertTrue(message.startswith("Install failed for libclang-dev with manager apt"))


class PrivateIpTest(unittest.TestCase):
    def test_private_and_link_local(self) -> None:
        for ip in ("169.254.0.3", "169.254.0.23", "10.1.2.3", "172.16.0.1", "172.31.9.9",
                   "192.168.1.1", "127.0.0.1", "0.0.0.0"):
            with self.subTest(ip=ip):
                self.assertTrue(is_private_ip(ip))

    def test_public(self) -> None:
        for ip in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "172.15.0.1", "172.32.0.1", "192.169.1.1"):
            with self.subTest(ip=ip):
                self.assertFalse(is_private_ip(ip))

    def test_garbage_is_not_private(self) -> None:
        for ip in ("", "169.254", "not-an-ip", "::1"):
            with self.subTest(ip=ip):
                self.assertFalse(is_private_ip(ip))


class SourcePreflightTest(unittest.TestCase):
    def test_parses_both_classic_and_deb822_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.list").write_text(
                "deb http://mirrors.tencentyun.com/ubuntu noble main\n", encoding="utf-8"
            )
            (root / "b.sources").write_text(
                "Types: deb\nURIs: http://169.254.0.23/ubuntu\nSuites: noble\n", encoding="utf-8"
            )
            self.assertEqual(
                iter_source_uris([tmp]),
                ["http://169.254.0.23", "http://mirrors.tencentyun.com"],
            )

    def test_flags_internal_source_with_fix_command(self) -> None:
        uris = ["http://mirrors.tencentyun.com", "http://archive.ubuntu.com"]

        def resolve(host: str, port: int, family: int):  # noqa: ARG001
            return [(2, 1, 6, "", ("169.254.0.3", port))]

        with redirect_stdout(io.StringIO()) as out:
            warnings = preflight_source_warnings(uris=uris, resolve=resolve)
            for line in warnings:
                print(line)
        text = out.getvalue()
        self.assertIn("mirrors.tencentyun.com → 169.254.0.3", text)
        self.assertIn("mirrors.cloud.tencent.com", text)

    def test_stays_silent_on_reachable_sources(self) -> None:
        def resolve(host: str, port: int, family: int):  # noqa: ARG001
            return [(2, 1, 6, "", ("93.184.216.34", port))]

        self.assertEqual(
            preflight_source_warnings(uris=["http://archive.ubuntu.com"], resolve=resolve), []
        )

    def test_unresolvable_host_is_not_a_false_alarm(self) -> None:
        def resolve(host: str, port: int, family: int):  # noqa: ARG001
            raise OSError("no dns")

        self.assertEqual(
            preflight_source_warnings(uris=["http://archive.ubuntu.com"], resolve=resolve), []
        )


class AptManagerInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        # 统一走"已是 root"分支，避免测试环境的 TTY/sudo 差异影响命令形态
        root = mock.patch("tool_installer.managers.base._is_root", return_value=True)
        root.start()
        self.addCleanup(root.stop)
        # 授权检测依赖宿主 PATH（万一测试机上真有个同名命令就会误触发）。
        # 本类只关心执行策略，非预期状态判定有专门的 test_authorization.py 覆盖。
        no_conflict = mock.patch(
            "tool_installer.managers.apt_policy.shutil.which", return_value=None
        )
        no_conflict.start()
        self.addCleanup(no_conflict.stop)

    @staticmethod
    def runner(returncode: int = 0, stdout: str = "", stderr: str = "") -> mock.Mock:
        runner = mock.Mock()
        runner.run.return_value = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )
        return runner

    def test_install_command_is_unchanged(self) -> None:
        """Step 1 只加执行策略，不改"装哪个包"的语义。"""
        self.assertEqual(
            AptManager().install_command(apt_item()), ["apt-get", "install", "-y", "libclang-dev"]
        )

    def test_install_passes_bounded_options_and_pins_version(self) -> None:
        runner = self.runner()
        with redirect_stdout(io.StringIO()):
            AptManager(runner=runner).install(apt_item(version="18.0-59"))

        args = runner.run.call_args[0][0]
        self.assertEqual(args[0], "apt-get")
        self.assertIn("Acquire::http::Timeout=30", args)
        self.assertIn("DPkg::Lock::Timeout=60", args)
        self.assertEqual(args[-1], "libclang-dev=18.0-59")
        self.assertEqual(runner.run.call_args[1]["timeout"], apt_policy.APT_COMMAND_TIMEOUT)

    def test_success_echoes_apt_output(self) -> None:
        runner = self.runner(stdout="Reading package lists... Done\n")
        with redirect_stdout(io.StringIO()) as out:
            AptManager(runner=runner).install(apt_item())
        self.assertIn("Reading package lists... Done", out.getvalue())
        self.assertIn("⏳ apt-get", out.getvalue())

    def test_failure_carries_attribution(self) -> None:
        runner = self.runner(returncode=100, stdout=TENCENTYUN_LOG)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(InstallationError) as ctx:
                AptManager(runner=runner).install(apt_item())
        self.assertIn("腾讯云内网源", str(ctx.exception))
        self.assertIn("mirrors.cloud.tencent.com", str(ctx.exception))

    def test_runner_timeout_is_attributed(self) -> None:
        runner = self.runner()
        runner.run.side_effect = InstallationError(
            "Command timed out after 1800s: apt-get\nE: Failed to fetch http://x/y"
        )
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(InstallationError) as ctx:
                AptManager(runner=runner).install(apt_item())
        self.assertIn("apt 源获取失败", str(ctx.exception))

    def test_preflight_runs_before_the_install(self) -> None:
        runner = self.runner()
        with mock.patch(
            "tool_installer.managers.commands.preflight_source_warnings",
            return_value=["❌ 检测到私网 apt 源"],
        ):
            with redirect_stdout(io.StringIO()) as out:
                AptManager(runner=runner).install(apt_item())
        text = out.getvalue()
        self.assertIn("检测到私网 apt 源", text)
        # 预检必须早于 apt 启动
        self.assertLess(text.index("检测到私网 apt 源"), text.index("⏳ apt-get"))


class RunnerTimeoutTest(unittest.TestCase):
    def test_default_timeout_is_passed_to_subprocess(self) -> None:
        completed = subprocess.CompletedProcess(args=["true"], returncode=0)
        with mock.patch("tool_installer.managers.base.subprocess.run", return_value=completed) as run:
            SubprocessRunner().run(["true"])
        self.assertEqual(run.call_args[1]["timeout"], DEFAULT_COMMAND_TIMEOUT)

    def test_timeout_becomes_a_controlled_error(self) -> None:
        """裸 TimeoutExpired 会让 executor 走 traceback；必须转成 InstallationError。"""
        with mock.patch(
            "tool_installer.managers.base.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=3600),
        ):
            with self.assertRaises(InstallationError) as ctx:
                SubprocessRunner().run(["sleep", "999"])
        self.assertIn("timed out after 3600s", str(ctx.exception))

    def test_caller_supplied_timeout_wins(self) -> None:
        completed = subprocess.CompletedProcess(args=["true"], returncode=0)
        with mock.patch("tool_installer.managers.base.subprocess.run", return_value=completed) as run:
            SubprocessRunner().run(["true"], timeout=10)
        self.assertEqual(run.call_args[1]["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
