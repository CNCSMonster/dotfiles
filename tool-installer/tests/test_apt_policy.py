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
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer import executor  # noqa: E402
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
    CheckResult,
    SubprocessRunner,
    _run_with_sudo,
)
from tool_installer.managers.commands import AptManager  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    InstallPlan,
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
        # 与 scripts/lib/apt.sh 同形：env 子命令跟在（可能的）sudo 之后，绕过 env_reset
        self.assertEqual(args[:3], ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get"])
        self.assertIn("Acquire::http::Timeout=30", args)
        self.assertIn("DPkg::Lock::Timeout=60", args)
        self.assertEqual(args[-1], "libclang-dev=18.0-59")
        self.assertEqual(runner.run.call_args[1]["timeout"], apt_policy.APT_COMMAND_TIMEOUT)

    def test_success_echoes_apt_output(self) -> None:
        runner = self.runner(stdout="Reading package lists... Done\n")
        with redirect_stdout(io.StringIO()) as out:
            AptManager(runner=runner).install(apt_item())
        self.assertIn("Reading package lists... Done", out.getvalue())
        self.assertIn("⏳ env DEBIAN_FRONTEND=noninteractive apt-get", out.getvalue())

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
                manager = AptManager(runner=runner)
                manager.preflight([apt_item()])
                manager.install(apt_item())
        text = out.getvalue()
        self.assertIn("检测到私网 apt 源", text)
        # 预检必须早于 apt 启动（现在由每轮一次的 preflight 负责）
        self.assertLess(text.index("检测到私网 apt 源"), text.index("⏳ env"))


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


    def test_bounded_numbers_match_scripts_lib_apt_sh(self) -> None:
        """有界数值在 shell 与 Python 各写一遍，靠"记得同步"会失守——这里锁死。

        这是 2026-09 事故的直接教训：shell 侧先修好，Python 侧晚一个月移植，
        期间两边数值可能已经漂移。改任一侧的数值，本测试会点名。
        """
        apt_sh = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "apt.sh"
        self.assertTrue(apt_sh.is_file(), f"找不到 {apt_sh}，路径变更需同步本测试")
        text = apt_sh.read_text(encoding="utf-8")
        expected = {
            "Acquire::http::Timeout": apt_policy.APT_HTTP_TIMEOUT,
            "Acquire::https::Timeout": apt_policy.APT_HTTP_TIMEOUT,
            "Acquire::Retries": apt_policy.APT_RETRIES,
            "DPkg::Lock::Timeout": apt_policy.APT_LOCK_TIMEOUT,
        }
        for key, value in expected.items():
            match = re.search(rf'-o "{key}=(\d+)"', text)
            self.assertIsNotNone(match, f"scripts/lib/apt.sh 缺少 {key}（python 侧 = {value}）")
            self.assertEqual(
                int(match.group(1)),
                value,
                f"{key} 两处不一致：shell={match.group(1)}，tool-installer={value}。"
                "改一处必须同步另一处。",
            )


class SudoPrivilegeTest(unittest.TestCase):
    """提权顺序与 shell 侧 preflight_runtime_deps 一一对应：root → `sudo -n` → TTY → 报错。

    这块原先零覆盖，于是"无 TTY 就判死"的缺陷一路活到 CI：system-packages 迁 apt 后，
    CI（免密 sudo、无 TTY）的 install languages 经 depends 链拿到 apt 条目，整个 job 挂掉。
    """

    @staticmethod
    def runner(passwordless_rc: int = 0) -> mock.Mock:
        """sudo -n true 返回 passwordless_rc，其余命令成功。"""
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            if list(args[:3]) == ["sudo", "-n", "true"]:
                return subprocess.CompletedProcess(args, passwordless_rc, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = side_effect
        return runner

    @staticmethod
    def commands(runner: mock.Mock) -> list:
        return [c[0][0] for c in runner.run.call_args_list]

    def test_passwordless_sudo_works_without_tty(self) -> None:
        """CI/云镜像场景：免密可用、无 TTY —— 修复前这里直接判死。"""
        runner = self.runner(passwordless_rc=0)
        with mock.patch("tool_installer.managers.base._is_root", return_value=False), \
             mock.patch("tool_installer.managers.base._has_tty", return_value=False):
            _run_with_sudo(["apt-get", "update"], runner=runner)
        cmds = self.commands(runner)
        self.assertIn(["sudo", "-n", "true"], cmds, "必须先探测免密")
        self.assertEqual(cmds[-1], ["sudo", "apt-get", "update"])

    def test_password_required_and_no_tty_fails_with_clear_message(self) -> None:
        runner = self.runner(passwordless_rc=1)
        with mock.patch("tool_installer.managers.base._is_root", return_value=False), \
             mock.patch("tool_installer.managers.base._has_tty", return_value=False):
            with self.assertRaises(InstallationError) as ctx:
                _run_with_sudo(["apt-get", "update"], runner=runner)
        self.assertIn("no TTY", str(ctx.exception))

    def test_password_required_with_tty_runs_sudo(self) -> None:
        runner = self.runner(passwordless_rc=1)
        with mock.patch("tool_installer.managers.base._is_root", return_value=False), \
             mock.patch("tool_installer.managers.base._has_tty", return_value=True):
            _run_with_sudo(["apt-get", "update"], runner=runner)
        self.assertEqual(self.commands(runner)[-1], ["sudo", "apt-get", "update"])

    def test_root_neither_probes_nor_wraps(self) -> None:
        runner = self.runner()
        with mock.patch("tool_installer.managers.base._is_root", return_value=True):
            _run_with_sudo(["apt-get", "update"], runner=runner)
        cmds = self.commands(runner)
        self.assertEqual(cmds[-1], ["apt-get", "update"], "root 直接执行，不包 sudo")
        self.assertNotIn(["sudo", "-n", "true"], cmds, "root 不需要探测")

    def test_missing_sudo_binary_falls_through_to_tty_check(self) -> None:
        runner = mock.Mock()
        runner.run.side_effect = OSError("sudo not found")
        with mock.patch("tool_installer.managers.base._is_root", return_value=False), \
             mock.patch("tool_installer.managers.base._has_tty", return_value=False):
            with self.assertRaises(InstallationError):
                _run_with_sudo(["apt-get", "update"], runner=runner)


class PreflightTest(unittest.TestCase):
    """preflight = 每轮一次的索引刷新 + 源预检（对齐 scripts/lib/apt.sh 语义）。"""

    def setUp(self) -> None:
        root = mock.patch("tool_installer.managers.base._is_root", return_value=True)
        root.start()
        self.addCleanup(root.stop)
        no_conflict = mock.patch(
            "tool_installer.managers.apt_policy.shutil.which", return_value=None
        )
        no_conflict.start()
        self.addCleanup(no_conflict.stop)

    @staticmethod
    def runner(rc: int = 0) -> mock.Mock:
        """rc 作用于 apt-get；dpkg-query 恒报"未装"，让 executor 走到 install。"""
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            if args and args[0] == "dpkg-query":
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, rc, "", "")

        runner.run.side_effect = side_effect
        return runner

    @staticmethod
    def apt_commands(runner: mock.Mock) -> list:
        return [
            c[0][0]
            for c in runner.run.call_args_list
            if c[0][0] and "apt-get" in c[0][0]
        ]

    @staticmethod
    def items(*names: str) -> list:
        return [
            PlanItem(
                module_name="system-packages",
                tool=ToolSpec(
                    reference=ToolReference(raw=f"{n}@latest", name=n, version="latest"),
                    allow_fail=False,
                ),
                strategy=MergedStrategy(tool_name=n, manager="apt", fields={"pkg": n}),
                environment=Environment(os="linux", arch="x86_64"),
            )
            for n in names
        ]

    def test_update_runs_once_per_round_not_per_package(self) -> None:
        """shell 是脚本开头一次、多包共用；每包一次会把 19 个包放大成 19 轮往返。"""
        runner = self.runner()
        AptManager(runner=runner).preflight(self.items("pkg-a", "pkg-b", "pkg-c"))
        updates = [c for c in self.apt_commands(runner) if "update" in c]
        self.assertEqual(len(updates), 1)
        # 选项在子命令前，与 shell 的 apt-get "${APT_OPTS[@]}" update 同形；
        # 外层是 env DEBIAN_FRONTEND=noninteractive（与 shell 同，绕过 sudo env_reset）
        self.assertEqual(updates[0][:3], ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get"])
        self.assertEqual(updates[0][3], "-o")
        self.assertEqual(updates[0][-1], "update")

    def test_update_failure_warns_but_does_not_raise(self) -> None:
        """索引陈旧不必然装不上（apt 还有缓存索引），预检不该杀掉整轮。"""
        runner = self.runner(rc=1)
        with redirect_stderr(io.StringIO()) as err:
            AptManager(runner=runner).preflight(self.items("pkg-a"))
        self.assertIn("apt-get update failed", err.getvalue())

    def test_empty_group_is_a_no_op(self) -> None:
        runner = self.runner()
        AptManager(runner=runner).preflight([])
        runner.run.assert_not_called()

    def test_source_check_moved_from_install_to_preflight(self) -> None:
        """源预检原本逐项跑（每项最多 源数×5 秒），必须只在 preflight 出现一次。"""
        runner = self.runner()
        warn = ["⚠️ 假警告"]
        with mock.patch(
            "tool_installer.managers.commands.preflight_source_warnings", return_value=warn
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                AptManager(runner=runner).preflight(self.items("pkg-a"))
            self.assertIn("假警告", out.getvalue())

            out2 = io.StringIO()
            with redirect_stdout(out2):
                AptManager(runner=runner).install(self.items("pkg-a")[0])
            self.assertNotIn("假警告", out2.getvalue(), "install 不应再逐项做源预检")

    def test_executor_runs_preflight_before_any_install(self) -> None:
        runner = self.runner()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            executor.execute_plan(
                InstallPlan(items=self.items("pkg-a", "pkg-b")),
                {"apt": AptManager(runner=runner)},
            )
        commands = self.apt_commands(runner)
        self.assertEqual(sum(1 for c in commands if "update" in c), 1, "update 应恰好一次")
        self.assertEqual(sum(1 for c in commands if "install" in c), 2, "每包各装一次")
        self.assertIn("update", commands[0], "所有前置必须先于任何 install")


class AptManagerCheckTest(unittest.TestCase):
    """check 的契约：多包任一缺失即重装；latest = 装了即满足，**不比 candidate**。

    后者是刻意的语义裁决（见 check docstring）：系统包清单的旧实现是
    `command -v || dpkg -s || missing`，从不升级已装的包；若 check 把
    "版本落后 candidate" 判为未满足，./setup.sh 就会变成每轮升级系统的入口。
    """

    def setUp(self) -> None:
        root = mock.patch("tool_installer.managers.base._is_root", return_value=True)
        root.start()
        self.addCleanup(root.stop)

    @staticmethod
    def item(pkgs: str, version: str = "latest") -> PlanItem:
        return PlanItem(
            module_name="system-packages",
            tool=ToolSpec(
                reference=ToolReference(
                    raw=f"system-packages@{version}",
                    name="system-packages",
                    version=version,
                ),
                allow_fail=False,
            ),
            strategy=MergedStrategy(
                tool_name="system-packages", manager="apt", fields={"pkg": pkgs}
            ),
            environment=Environment(os="linux", arch="x86_64"),
        )

    @staticmethod
    def runner(installed: dict) -> mock.Mock:
        """installed: pkg -> version；未列出的包视为未装。"""
        runner = mock.Mock()

        def side_effect(args, **kwargs):  # noqa: ANN001
            if args[0] == "dpkg-query":
                pkg = args[-1]
                if pkg in installed:
                    return subprocess.CompletedProcess(args, 0, installed[pkg], "")
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = side_effect
        return runner

    @staticmethod
    def apt_cache_calls(runner: mock.Mock) -> list:
        return [
            c[0][0]
            for c in runner.run.call_args_list
            if c[0][0] and c[0][0][0] == "apt-cache"
        ]

    def test_all_installed_is_satisfied(self) -> None:
        runner = self.runner({"a": "1.0", "b": "2.0", "c": "3.0"})
        result = AptManager(runner=runner).check(self.item("a b c"))
        self.assertIs(result, CheckResult.SATISFIED)
        self.assertEqual(self.apt_cache_calls(runner), [], "latest 不应查 candidate")

    def test_one_missing_is_not_satisfied(self) -> None:
        runner = self.runner({"a": "1.0", "b": "2.0"})
        result = AptManager(runner=runner).check(self.item("a b c"))
        self.assertIs(result, CheckResult.NOT_SATISFIED)

    def test_stale_installed_version_is_still_satisfied_for_latest(self) -> None:
        """锁"不升级"：装了但版本旧，latest 仍算满足——这正是迁移前脚本的行为。"""
        runner = self.runner({"pkg": "0.9.0-1ubuntu1"})
        result = AptManager(runner=runner).check(self.item("pkg"))
        self.assertIs(result, CheckResult.SATISFIED)
        self.assertEqual(self.apt_cache_calls(runner), [])

    def test_pin_mismatch_is_not_satisfied(self) -> None:
        runner = self.runner({"pkg": "1.3.0"})
        result = AptManager(runner=runner).check(self.item("pkg", version="1.2.0"))
        self.assertIs(result, CheckResult.NOT_SATISFIED)

    def test_pin_match_tolerates_leading_v(self) -> None:
        runner = self.runner({"pkg": "v1.2.0"})
        result = AptManager(runner=runner).check(self.item("pkg", version="1.2.0"))
        self.assertIs(result, CheckResult.SATISFIED)

    def test_nothing_installed_is_not_satisfied(self) -> None:
        runner = self.runner({})
        result = AptManager(runner=runner).check(self.item("a b c"))
        self.assertIs(result, CheckResult.NOT_SATISFIED)


class InstallCommandShapeTest(unittest.TestCase):
    """命令形态：多包一次装（与旧脚本批量 `${missing[@]}` 同语义）、pin 限单包。"""

    @staticmethod
    def item(pkgs: str, version: str = "latest") -> PlanItem:
        return PlanItem(
            module_name="system-packages",
            tool=ToolSpec(
                reference=ToolReference(
                    raw=f"system-packages@{version}",
                    name="system-packages",
                    version=version,
                ),
                allow_fail=False,
            ),
            strategy=MergedStrategy(
                tool_name="system-packages", manager="apt", fields={"pkg": pkgs}
            ),
            environment=Environment(os="linux", arch="x86_64"),
        )

    def test_multi_package_expands_into_one_transaction(self) -> None:
        cmd = AptManager().install_command(self.item("libssl-dev unzip iproute2"))
        self.assertEqual(cmd, ["apt-get", "install", "-y", "libssl-dev", "unzip", "iproute2"])

    def test_single_package_shape_is_unchanged(self) -> None:
        cmd = AptManager().install_command(self.item("libclang-dev"))
        self.assertEqual(cmd, ["apt-get", "install", "-y", "libclang-dev"])

    def test_pin_on_multi_package_is_rejected_explicitly(self) -> None:
        """多包 + pin 没有真实语义，宁可报错也不静默猜测。"""
        with self.assertRaises(InstallationError) as ctx:
            AptManager().install_command(self.item("a b", version="1.2.0"))
        self.assertIn("多包", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
