"""工具二进制升级最小可回滚备份的契约测试。

全程：临时 HOME + 桩掉网络下载/命令 runner，绝不联网、不实际安装、不执行包入口、
不改 vendor / 正式配置。

覆盖：
  - 覆盖前留存旧字节 + receipt（绝对路径 / 原始 sha256 或 link target / 工具 / 版本 / 时间戳）
  - 成功后备份默认保留、可凭 receipt 手动回滚
  - os.replace 失败 / 安装失败时自动还原原有目标与旧字节
  - 首次安装不产生备份
  - 符号链接只记 link target、不跟随内容
  - extract_dir 旧共享目录先完整备份后删除，失败还原
  - cargo 路径覆盖前备份 bin 候选；run 失败 / 重试耗尽自动还原；binstall 捷径也覆盖
  - HOME 缺失边缘：cargo 无可用备份根时 fail-closed（零 runner.run、不写 CWD）；
    CARGO_HOME 可用时按 <CARGO_HOME>/.. 备份并成功保留 / 失败还原
  - github-release HOME 缺失：fail-closed 且文案明确「无法备份」，不进入下载
  - helper 参数化 state_root：落点可钉死并成功 / 失败还原；相对路径被拒绝
  - 同 label 同秒并发用 mkdtemp 不撞车
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Dict, List
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers import github_release as gr  # noqa: E402
from tool_installer.managers import commands as cmdmod  # noqa: E402
from tool_installer.managers.commands import CargoInstallManager  # noqa: E402
from tool_installer.managers.upgrade_backup import (  # noqa: E402
    MANIFEST_NAME,
    UpgradeBackup,
    rollback as rollback_slot,
    state_root_for,
)
from tool_installer.models import (  # noqa: E402
    Environment,
    GithubReleaseConfig,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)

REPO = "mikefarah/yq"
VERSION = "4.53.3"
ASSET = "yq_linux_amd64"
GOOD = b"the-real-artifact-v2"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()
OLD = b"OLD-BINARY-v1"
OLD_SHA = hashlib.sha256(OLD).hexdigest()
MIRROR = "https://mirror.example"

STATE_REL = Path(".local") / "state" / "dotfiles" / "tool-upgrade-backup"


def state_root(home: Path) -> Path:
    return home / STATE_REL


def slots(home: Path) -> List[Path]:
    root = state_root(home)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def make_item(*, name: str = "yq", sha256: str | None = GOOD_SHA, fields: dict | None = None) -> PlanItem:
    f = {"repo": REPO, "asset": ASSET, "bin": ASSET}
    if sha256 is not None:
        f["sha256"] = sha256
    if fields:
        f.update(fields)
    return PlanItem(
        module_name="editors",
        tool=ToolSpec(reference=ToolReference(raw=f"{name}@{VERSION}", name=name, version=VERSION)),
        strategy=MergedStrategy(tool_name=name, manager="github-release", fields=f),
        environment=Environment(os="linux", arch="x86_64"),
    )


def make_manager(*, retry: int = 0) -> gr.GithubReleaseManager:
    cfg = GithubReleaseConfig(github_mirrors=[MIRROR], timeout=1.0, retry=retry)
    return gr.GithubReleaseManager(cfg)


def stub_fetch(manager: gr.GithubReleaseManager, payload: bytes) -> List[str]:
    """桩掉 _fetch_into：任何 URL 都写回同一份（已校验）字节。"""
    calls: List[str] = []

    def fake(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(payload)

    manager._fetch_into = fake  # type: ignore[method-assign]
    return calls


def zip_payload(entries: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class HomeFixture(unittest.TestCase):
    """临时 HOME，测试期间绝不碰真实家目录。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._old_home = os.environ.get("HOME")
        self._old_cargo_home = os.environ.get("CARGO_HOME")
        os.environ["HOME"] = str(self.home)
        os.environ.pop("CARGO_HOME", None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_cargo_home is None:
            os.environ.pop("CARGO_HOME", None)
        else:
            os.environ["CARGO_HOME"] = self._old_cargo_home
        self._tmp.cleanup()

    def bin_dir(self) -> Path:
        d = self.home / ".local" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def destination(self, name: str = "yq") -> Path:
        return self.bin_dir() / name


class GithubReleaseBackup(HomeFixture):
    def install(self, item: PlanItem, payload: bytes = GOOD) -> gr.GithubReleaseManager:
        manager = make_manager()
        stub_fetch(manager, payload)
        manager.install(item)
        return manager

    # ---- T1 / receipt ----
    def test_overwrite_creates_backup_with_old_bytes_and_receipt(self):
        dest = self.destination()
        dest.write_bytes(OLD)

        self.install(make_item())

        self.assertEqual(dest.read_bytes(), GOOD, "新二进制仍是校验通过的那份")
        found = slots(self.home)
        self.assertEqual(len(found), 1, "覆盖前必须生成恰好一份备份")
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["tool"], "yq")
        self.assertEqual(receipt["version"], VERSION)
        self.assertTrue(receipt["timestamp"], "receipt 必须含时间戳")
        self.assertIn(str(os.getpid()), found[0].name, "slot 名含 pid")
        self.assertEqual(len(receipt["entries"]), 1)
        entry = receipt["entries"][0]
        self.assertEqual(entry["absolute_path"], str(dest))
        self.assertEqual(entry["kind"], "file")
        self.assertEqual(entry["sha256"], OLD_SHA, "receipt 记录原始 sha256")
        self.assertEqual((found[0] / entry["backup"]).read_bytes(), OLD, "旧字节可取回")

    # ---- 成功后保留 + 手动回滚（T2）----
    def test_success_retains_backup_and_manual_rollback_restores_old_bytes(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        self.install(make_item())
        found = slots(self.home)
        self.assertEqual(len(found), 1)
        self.assertTrue((found[0] / MANIFEST_NAME).is_file())

        count = rollback_slot(found[0])

        self.assertEqual(count, 1)
        self.assertEqual(dest.read_bytes(), OLD, "凭 receipt 可手动回滚")
        self.assertTrue((found[0] / MANIFEST_NAME).is_file(), "回滚后备份仍保留，不被删")

    def test_success_does_not_delete_backup(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        self.install(make_item())
        found = slots(self.home)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].is_dir())
        # 再装一次也不删旧备份（保留策略：不自动 GC）
        self.install(make_item())
        self.assertGreaterEqual(len(slots(self.home)), 2)

    # ---- 首次安装不备份（T4）----
    def test_first_install_creates_no_backup(self):
        self.assertFalse(self.destination().exists())
        self.install(make_item())
        self.assertEqual(self.destination().read_bytes(), GOOD)
        self.assertEqual(slots(self.home), [], "首次安装不得创建 state 目录/备份")

    # ---- os.replace 失败自动还原（T3）----
    def test_os_replace_failure_restores_old_target_and_cleans_tmp(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        real_replace = os.replace
        seen: List[str] = []

        def flaky(src, dst):
            seen.append(str(src))
            if "installing_" in str(src):
                raise OSError("simulated os.replace failure")
            return real_replace(src, dst)

        manager = make_manager()
        stub_fetch(manager, GOOD)
        with mock.patch.object(gr.os, "replace", side_effect=flaky):
            with self.assertRaises(OSError):
                manager.install(make_item())

        self.assertEqual(dest.read_bytes(), OLD, "失败后旧目标与旧字节必须还原")
        self.assertEqual(list(self.bin_dir().glob(".installing_*")), [], "临时文件被清理")
        self.assertEqual(len(slots(self.home)), 1, "备份保留，可人工核对")
        self.assertTrue(any("installing_" in s for s in seen))
        self.assertTrue(any("restore_" in s for s in seen), "还原走 os.replace")

    # ---- publish 阶段安装失败（非 os.replace）也自动还原 ----
    def test_copy2_failure_during_publish_restores_old_target(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        real_copy2 = gr.shutil.copy2

        def flaky_copy2(src, dst, *a, **kw):
            if "installing_" in str(dst):
                raise OSError("simulated staging copy failure")
            return real_copy2(src, dst, *a, **kw)

        manager = make_manager()
        stub_fetch(manager, GOOD)
        with mock.patch.object(gr.shutil, "copy2", side_effect=flaky_copy2):
            with self.assertRaises(OSError):
                manager.install(make_item())

        self.assertEqual(dest.read_bytes(), OLD, "staging 失败时旧目标已还原")
        self.assertEqual(list(self.bin_dir().glob(".installing_*")), [])
        self.assertEqual(len(slots(self.home)), 1)

    # ---- 回滚本身失败时仍报出安装错误与备份位置 ----
    def test_rollback_failure_is_reported_with_backup_location(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        real_replace = os.replace

        def flaky(src, dst):
            if "installing_" in str(src):
                raise OSError("publish failed")
            return real_replace(src, dst)

        manager = make_manager()
        stub_fetch(manager, GOOD)
        with mock.patch.object(gr.os, "replace", side_effect=flaky), \
                mock.patch.object(UpgradeBackup, "rollback", side_effect=OSError("rollback failed")):
            with self.assertRaises(InstallationError) as ctx:
                manager.install(make_item())

        message = str(ctx.exception)
        self.assertIn("自动回滚也失败", message)
        self.assertIn("manifest.json", message)
        self.assertEqual(len(slots(self.home)), 1, "备份仍在磁盘上")

    # ---- 安装失败（下载/校验阶段）不产生备份 ----
    def test_install_failure_before_publish_creates_no_backup(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        manager = make_manager()
        stub_fetch(manager, b"TAMPERED")  # sha256 不匹配 → 所有源耗尽
        with self.assertRaises(InstallationError):
            manager.install(make_item())
        self.assertEqual(dest.read_bytes(), OLD)
        self.assertEqual(slots(self.home), [])

    # ---- 符号链接：只记 link target，不跟随内容 ----
    def test_symlink_is_recorded_not_followed_and_restored(self):
        dest = self.destination()
        secret = self.home / "secret" / "real-binary"
        secret.parent.mkdir(parents=True)
        secret.write_bytes(b"SENSITIVE-DO-NOT-READ")
        dest.symlink_to(secret)

        self.install(make_item())

        found = slots(self.home)
        self.assertEqual(len(found), 1)
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        entry = receipt["entries"][0]
        self.assertEqual(entry["kind"], "symlink")
        self.assertEqual(entry["link_target"], str(secret))
        self.assertIsNone(entry["sha256"], "符号链接不记录内容摘要")
        self.assertEqual(entry["backup"], "", "符号链接不复制指向内容")
        self.assertEqual(
            sorted(p.name for p in found[0].iterdir() if p.name != MANIFEST_NAME),
            [],
            "slot 里不得出现被跟随复制的敏感字节",
        )
        self.assertEqual(dest.read_bytes(), GOOD, "publish 覆盖的是链接本身")

    def test_symlink_failure_restores_link_without_following(self):
        dest = self.destination()
        secret = self.home / "secret-target"
        secret.write_bytes(b"SENSITIVE")
        dest.symlink_to(secret)
        real_replace = os.replace

        def flaky(src, dst):
            if "installing_" in str(src):
                raise OSError("boom")
            return real_replace(src, dst)

        manager = make_manager()
        stub_fetch(manager, GOOD)
        with mock.patch.object(gr.os, "replace", side_effect=flaky):
            with self.assertRaises(OSError):
                manager.install(make_item())

        self.assertTrue(dest.is_symlink(), "还原回符号链接本身")
        self.assertEqual(os.readlink(dest), str(secret))
        self.assertEqual(secret.read_bytes(), b"SENSITIVE", "从未读取/改动指向内容")

    # ---- extract_dir：旧目录先完整备份后删除，失败还原（T5）----
    def _extract_item(self, payload: bytes) -> PlanItem:
        return make_item(
            fields={
                "asset": "bundle.zip",
                "bin": "pkg/tool",
                "extract_dir": "yq-share",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    def _extract_manager(self, payload: bytes) -> gr.GithubReleaseManager:
        manager = make_manager()
        stub_fetch(manager, payload)
        return manager

    def test_extract_dir_backs_up_whole_old_tree_before_rmtree(self):
        payload = zip_payload({"pkg/tool": b"NEW-EXEC", "pkg/data.txt": b"NEW-DATA"})
        item = self._extract_item(payload)
        share = self.home / ".local" / "share" / "yq-share"
        share.mkdir(parents=True)
        (share / "pkg").mkdir()
        (share / "pkg" / "tool").write_bytes(b"OLD-EXEC")
        (share / "pkg" / "data.txt").write_bytes(b"OLD-DATA")
        (share / "old-only.txt").write_bytes(b"OLD-ONLY")
        wrapper = self.destination()
        wrapper.write_text("#!/usr/bin/env bash\nOLD-WRAPPER\n")

        # 备份必须发生在 rmtree 之前：用 wrapper 观察 rmtree 时备份已存在。
        real_rmtree = gr.shutil.rmtree
        observed = {}

        def spy_rmtree(path, *a, **kw):
            if str(path) == str(share):
                observed["slots_at_rmtree"] = len(slots(self.home))
                observed["backup_tree"] = any(
                    (s / "01-yq-share.tree" / "old-only.txt").exists() for s in slots(self.home)
                )
            return real_rmtree(path, *a, **kw)

        with mock.patch.object(gr.shutil, "rmtree", side_effect=spy_rmtree):
            self._extract_manager(payload).install(item)

        self.assertEqual(observed.get("slots_at_rmtree"), 1, "rmtree 之前已生成备份")
        self.assertTrue(observed.get("backup_tree"), "rmtree 之前旧目录已完整备份")
        self.assertEqual((share / "pkg" / "tool").read_bytes(), b"NEW-EXEC")
        self.assertEqual((share / "pkg" / "data.txt").read_bytes(), b"NEW-DATA")
        self.assertFalse((share / "old-only.txt").exists(), "旧树已被新树替换")
        self.assertEqual(wrapper.read_text(), (
            '#!/usr/bin/env bash\nexec "' + str(share / "pkg" / "tool") + '" "$@"\n'
        ))

        found = slots(self.home)
        self.assertEqual(len(found), 1)
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        kinds = [e["kind"] for e in receipt["entries"]]
        self.assertIn("dir", kinds)
        self.assertIn("file", kinds)
        tree = found[0] / receipt["entries"][1]["backup"]
        self.assertEqual((tree / "old-only.txt").read_bytes(), b"OLD-ONLY")
        self.assertEqual((tree / "pkg" / "tool").read_bytes(), b"OLD-EXEC")

    def test_extract_dir_failure_restores_old_tree_and_wrapper(self):
        payload = zip_payload({"pkg/tool": b"NEW-EXEC"})
        item = self._extract_item(payload)
        share = self.home / ".local" / "share" / "yq-share"
        share.mkdir(parents=True)
        (share / "pkg").mkdir()
        (share / "pkg" / "tool").write_bytes(b"OLD-EXEC")
        (share / "old-only.txt").write_bytes(b"OLD-ONLY")
        wrapper = self.destination()
        wrapper.write_text("OLD-WRAPPER\n")

        real_copytree = gr.shutil.copytree
        call_count = {"n": 0}

        def flaky_copytree(src, dst, *a, **kw):
            # 第一次是真正发布新树；让它失败以触发还原（还原里的 copytree 放行）。
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("simulated copytree failure mid-publish")
            return real_copytree(src, dst, *a, **kw)

        manager = self._extract_manager(payload)
        with mock.patch.object(gr.shutil, "copytree", side_effect=flaky_copytree):
            with self.assertRaises(OSError):
                manager.install(item)

        self.assertEqual((share / "pkg" / "tool").read_bytes(), b"OLD-EXEC", "旧共享目录还原")
        self.assertEqual((share / "old-only.txt").read_bytes(), b"OLD-ONLY", "旧树完整还原")
        self.assertEqual(wrapper.read_text(), "OLD-WRAPPER\n", "旧 wrapper 还原")
        self.assertEqual(len(slots(self.home)), 1, "备份保留")


class CargoBackup(HomeFixture):
    def make_item(self, pkg: str = "taplo-cli", bin_name: str | None = "taplo") -> PlanItem:
        fields: dict = {"pkg": pkg}
        if bin_name:
            fields["bin"] = bin_name
        return PlanItem(
            module_name="cargo-tools",
            tool=ToolSpec(reference=ToolReference(raw=f"{pkg}@0.10.0", name=pkg, version="0.10.0")),
            strategy=MergedStrategy(tool_name=pkg, manager="cargo-install", fields=fields),
            environment=Environment(os="linux", arch="x86_64"),
        )

    def cargo_bin(self, name: str = "taplo") -> Path:
        d = self.home / ".cargo" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def stack_patches(self, stack: ExitStack, runner: mock.Mock, bin_dirs: List[Path]) -> CargoInstallManager:
        stack.enter_context(
            mock.patch.object(CargoInstallManager, "_cargo_bin_dirs", lambda _self: bin_dirs)
        )
        stack.enter_context(mock.patch.object(cmdmod.time, "sleep", lambda _s: None))
        stack.enter_context(
            mock.patch.object(cmdmod, "detect_github_token", return_value=(None, None))
        )
        return CargoInstallManager(runner=runner)

    # ---- T6：cargo 覆盖前备份 bin 候选；失败/重试耗尽还原 ----
    def test_cargo_failure_restores_old_binary_after_retries_exhausted(self):
        target = self.cargo_bin("taplo")
        target.write_bytes(OLD)
        calls: List[list] = []
        runner = mock.Mock()
        slot_seen: List[bool] = []

        def run(args, **kwargs):
            calls.append(list(args))
            # 模拟 --force 已经在失败前覆盖了 bin（真实 cargo 的语义）
            target.write_bytes(GOOD)
            slot_seen.append(len(slots(self.home)) >= 1)
            return subprocess.CompletedProcess(args, 1, "", "")

        runner.run.side_effect = run
        with ExitStack() as stack:
            mgr = self.stack_patches(stack, runner, [target.parent])
            with self.assertRaises(InstallationError):
                mgr.install(self.make_item())

        self.assertEqual(len(calls), 3, "重试耗尽：3 次 cargo install")
        self.assertTrue(all("--force" in c for c in calls), "force 语义未改变")
        self.assertTrue(all(slot_seen), "每次 run 之前备份已存在")
        self.assertEqual(target.read_bytes(), OLD, "失败后旧字节自动还原")
        found = slots(self.home)
        self.assertEqual(len(found), 1)
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["tool"], "taplo-cli")
        self.assertEqual(receipt["version"], "0.10.0")
        self.assertTrue(receipt["timestamp"])
        entry = receipt["entries"][0]
        self.assertEqual(entry["absolute_path"], str(target))
        self.assertEqual(entry["sha256"], OLD_SHA)
        self.assertEqual((found[0] / entry["backup"]).read_bytes(), OLD)

    def test_cargo_success_retains_backup(self):
        target = self.cargo_bin("taplo")
        target.write_bytes(OLD)
        runner = mock.Mock()

        def run(args, **kwargs):
            target.write_bytes(GOOD)
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        with ExitStack() as stack:
            mgr = self.stack_patches(stack, runner, [target.parent])
            mgr.install(self.make_item())

        self.assertEqual(target.read_bytes(), GOOD)
        self.assertEqual(len(slots(self.home)), 1, "成功后备份保留，不自动删")

    def test_cargo_first_install_no_backup(self):
        self.assertFalse(self.cargo_bin("taplo").exists())
        runner = mock.Mock()
        runner.run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with ExitStack() as stack:
            mgr = self.stack_patches(stack, runner, [self.home / ".cargo" / "bin"])
            mgr.install(self.make_item())
        self.assertEqual(slots(self.home), [], "首次安装不备份")

    def test_cargo_backs_up_all_existing_bin_candidates(self):
        underscore = self.cargo_bin("tree_sitter_grep")
        hyphen = self.cargo_bin("tree-sitter-grep")
        underscore.write_bytes(b"OLD-UNDERSCORE")
        hyphen.write_bytes(b"OLD-HYPHEN")
        runner = mock.Mock()
        runner.run.return_value = subprocess.CompletedProcess([], 1, "", "")
        with ExitStack() as stack:
            mgr = self.stack_patches(stack, runner, [self.home / ".cargo" / "bin"])
            with self.assertRaises(InstallationError):
                mgr.install(self.make_item(pkg="tree-sitter-grep", bin_name=None))

        receipt = json.loads((slots(self.home)[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(receipt["entries"]), 2, "连字符/下划线候选都备份")
        self.assertEqual(underscore.read_bytes(), b"OLD-UNDERSCORE")
        self.assertEqual(hyphen.read_bytes(), b"OLD-HYPHEN")

    def test_cargo_runner_exception_also_rolls_back(self):
        target = self.cargo_bin("taplo")
        target.write_bytes(OLD)
        runner = mock.Mock()

        def run(args, **kwargs):
            target.write_bytes(GOOD)
            raise OSError("runner exploded")

        runner.run.side_effect = run
        with ExitStack() as stack:
            mgr = self.stack_patches(stack, runner, [target.parent])
            with self.assertRaises(OSError):
                mgr.install(self.make_item())
        self.assertEqual(target.read_bytes(), OLD, "意外 run 异常也还原")

    # ---- binstall 捷径也覆盖 ----
    def _binstall_item(self) -> PlanItem:
        item = self.make_item()
        item.strategy.fields["binstall_first"] = True
        return item

    def test_binstall_shortcut_is_backed_up_before_run(self):
        target = self.cargo_bin("taplo")
        target.write_bytes(OLD)
        calls: List[list] = []
        runner = mock.Mock()
        observed: Dict[str, object] = {}

        def run(args, **kwargs):
            calls.append(list(args))
            if len(calls) == 1:
                observed["backup_before_run"] = len(slots(self.home)) == 1
                target.write_bytes(GOOD)  # 模拟 binstall --force 覆盖
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(CargoInstallManager, "_ensure_binstall", return_value="/bin/cargo-binstall")
            )
            stack.enter_context(
                mock.patch.object(
                    CargoInstallManager,
                    "_binstall_command",
                    return_value=["cargo", "binstall", "-y"],
                )
            )
            mgr = self.stack_patches(stack, runner, [target.parent])
            mgr.install(self._binstall_item())

        self.assertEqual(len(calls), 1, "binstall 成功即返回，不回退源码编译")
        self.assertTrue(observed["backup_before_run"], "binstall run 之前已备份")
        self.assertEqual(target.read_bytes(), GOOD)
        self.assertEqual(len(slots(self.home)), 1, "成功后备份保留")
        receipt = json.loads((slots(self.home)[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["entries"][0]["sha256"], OLD_SHA)

    def test_binstall_failure_then_cargo_failure_restores_old_binary(self):
        target = self.cargo_bin("taplo")
        target.write_bytes(OLD)
        calls: List[list] = []
        runner = mock.Mock()

        def run(args, **kwargs):
            calls.append(list(args))
            target.write_bytes(GOOD)  # 每一步都模拟覆盖
            if len(calls) == 1:
                return subprocess.CompletedProcess(args, 1, "", "")  # binstall 404
            return subprocess.CompletedProcess(args, 1, "", "")  # cargo 全失败

        runner.run.side_effect = run
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(CargoInstallManager, "_ensure_binstall", return_value="/bin/cargo-binstall")
            )
            stack.enter_context(
                mock.patch.object(
                    CargoInstallManager,
                    "_binstall_command",
                    return_value=["cargo", "binstall", "-y"],
                )
            )
            mgr = self.stack_patches(stack, runner, [target.parent])
            with self.assertRaises(InstallationError):
                mgr.install(self._binstall_item())

        self.assertEqual(len(calls), 4, "1 次 binstall + 3 次 cargo")
        self.assertEqual(target.read_bytes(), OLD, "捷径与回退都失败后还原旧字节")
        self.assertEqual(len(slots(self.home)), 1)


class ConcurrentSlotSafety(HomeFixture):
    """同 label / 同秒 / 多进程(线程)并发：mkdtemp 保证不撞车。"""

    def test_same_label_same_second_concurrent_creates_distinct_slots(self):
        # 钉死时间，让所有线程落在"同一秒"。
        with mock.patch(
            "tool_installer.managers.upgrade_backup.time.strftime",
            return_value="20261117-120000",
        ):
            barrier = threading.Barrier(8)
            results: List[Path] = []
            lock = threading.Lock()

            def worker(i: int) -> None:
                dest = self.destination(f"tool{i}")
                dest.write_bytes(f"OLD-{i}".encode())
                b = UpgradeBackup(self.home, label="same-label", tool=f"tool{i}", version="1.0")
                barrier.wait()
                b.backup(dest)
                with lock:
                    results.append(b.slot)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(worker, range(8)))

        self.assertEqual(len(results), 8)
        self.assertEqual(len(set(results)), 8, "mkdtemp 随机后缀使 8 个 slot 互不相同")
        self.assertEqual(len(slots(self.home)), 8)
        for i, slot in enumerate(sorted(results, key=lambda p: p.name)):
            self.assertTrue((slot / MANIFEST_NAME).is_file())
            receipt = json.loads((slot / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(receipt["timestamp"], "20261117-120000")
        # 每个 slot 的备份字节彼此独立、可各自还原
        for i in range(8):
            self.assertTrue(
                any((s / f"00-tool{i}").read_bytes() == f"OLD-{i}".encode()
                    for s in slots(self.home) if (s / f"00-tool{i}").exists()),
                f"tool{i} 的旧字节在各自的 slot 里",
            )

    def test_real_multiprocess_same_label_creates_distinct_slots(self):
        """真·多进程：两个 python 进程同 label 并发写同一 state root。"""
        repo = str(Path(__file__).resolve().parents[1])
        script = (
            "import sys\n"
            f"sys.path.insert(0, {repo!r})\n"
            "from pathlib import Path\n"
            "from tool_installer.managers.upgrade_backup import UpgradeBackup, MANIFEST_NAME\n"
            "home = Path(sys.argv[1])\n"
            "idx = sys.argv[2]\n"
            "dest = home / '.local' / 'bin' / ('mproc-' + idx)\n"
            "dest.parent.mkdir(parents=True, exist_ok=True)\n"
            "dest.write_bytes(('OLD-' + idx).encode())\n"
            "b = UpgradeBackup(home, label='shared-label', tool='mproc', version='1.0')\n"
            "b.backup(dest)\n"
            "print(str(b.slot))\n"
        )
        env = dict(os.environ, HOME=str(self.home))
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.home), str(i)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            for i in range(2)
        ]
        slot_paths: List[Path] = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, f"子进程失败: {err}")
            slot_paths.append(Path(out.strip()))

        self.assertEqual(len(set(slot_paths)), 2, "两个进程得到不同的 slot")
        self.assertEqual(len(slots(self.home)), 2)
        for slot in slot_paths:
            self.assertIn("shared-label-", slot.name)
            self.assertTrue((slot / MANIFEST_NAME).is_file())
            receipt = json.loads((slot / MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(receipt["tool"], "mproc")
            self.assertEqual(len(receipt["entries"]), 1)


class NoHomeFixture(unittest.TestCase):
    """HOME / CARGO_HOME 均不设置；用临时 CWD 侦测任何「写进当前目录」的退化。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old_home = os.environ.get("HOME")
        self._old_cargo_home = os.environ.get("CARGO_HOME")
        self._old_cwd = os.getcwd()
        os.environ.pop("HOME", None)
        os.environ.pop("CARGO_HOME", None)
        os.chdir(self.tmp)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.chdir(self._old_cwd)
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        if self._old_cargo_home is None:
            os.environ.pop("CARGO_HOME", None)
        else:
            os.environ["CARGO_HOME"] = self._old_cargo_home
        self._tmp.cleanup()

    def assert_no_cwd_writes(self) -> None:
        self.assertFalse(
            (self.tmp / ".local").exists(),
            "不得在当前工作目录写安装目标或备份",
        )
        self.assertEqual(list(self.tmp.iterdir()), [], "CWD 必须保持干净")


class CargoHomeMissing(NoHomeFixture):
    """HOME 缺失边缘：不允许无备份覆盖；CARGO_HOME 可用时仍可备份/还原。"""

    def make_item(self, pkg: str = "taplo-cli", bin_name: str = "taplo") -> PlanItem:
        fields = {"pkg": pkg, "bin": bin_name}
        return PlanItem(
            module_name="cargo-tools",
            tool=ToolSpec(reference=ToolReference(raw=f"{pkg}@0.10.0", name=pkg, version="0.10.0")),
            strategy=MergedStrategy(tool_name=pkg, manager="cargo-install", fields=fields),
            environment=Environment(os="linux", arch="x86_64"),
        )

    def manager(self, runner=None, *, patch_bin_dirs=True) -> CargoInstallManager:
        if runner is None:
            runner = mock.Mock()
        runner.run.side_effect = AssertionError("runner.run 绝不能被调用")
        stack = ExitStack()
        self.addCleanup(stack.close)
        if patch_bin_dirs:
            stack.enter_context(
                mock.patch.object(
                    CargoInstallManager, "_cargo_bin_dirs",
                    side_effect=AssertionError("备份根未确定前不应探测候选 bin"),
                )
            )
        stack.enter_context(mock.patch.object(cmdmod.time, "sleep", lambda _s: None))
        stack.enter_context(
            mock.patch.object(cmdmod, "detect_github_token", return_value=(None, None))
        )
        # 钉死确定性：HOME/CARGO_HOME 都缺失时不得退回 passwd 里的 Path.home()。
        stack.enter_context(
            mock.patch.object(Path, "home", side_effect=AssertionError("不应调用 Path.home()"))
        )
        return CargoInstallManager(runner=runner), runner

    # ---- fail-closed：无任何 runner.run、无 CWD 写入 ----
    def test_home_and_cargo_home_missing_fails_closed_without_any_run(self):
        mgr, runner = self.manager()
        with self.assertRaises(InstallationError) as ctx:
            mgr.install(self.make_item())
        message = str(ctx.exception)
        self.assertIn("备份", message)
        self.assertIn("无备份覆盖", message)
        self.assertIn("fail-closed", message)
        self.assertIn("CARGO_HOME", message)
        self.assertEqual(runner.run.call_count, 0, "不执行 runner.run")
        self.assert_no_cwd_writes()

    def test_relative_cargo_home_fails_closed_without_any_run(self):
        os.environ["CARGO_HOME"] = "relative-cargo"
        mgr, runner = self.manager()
        with self.assertRaises(InstallationError) as ctx:
            mgr.install(self.make_item())
        self.assertIn("无备份覆盖", str(ctx.exception))
        self.assertEqual(runner.run.call_count, 0)
        self.assert_no_cwd_writes()

    def test_relative_home_fails_closed_without_any_run(self):
        os.environ["HOME"] = "relative-home"
        mgr, runner = self.manager()
        with self.assertRaises(InstallationError) as ctx:
            mgr.install(self.make_item())
        self.assertIn("无备份覆盖", str(ctx.exception))
        self.assertEqual(runner.run.call_count, 0)
        self.assert_no_cwd_writes()

    # ---- CARGO_HOME 可用：用 <CARGO_HOME>/.. 作备份根 ----
    def _cargo_home_setup(self):
        cargo_home = self.tmp / "cargo-home"
        target = cargo_home / "bin" / "taplo"
        target.parent.mkdir(parents=True)
        target.write_bytes(OLD)
        os.environ["CARGO_HOME"] = str(cargo_home)
        return cargo_home, target

    def test_cargo_home_only_success_creates_backup_under_parent(self):
        cargo_home, target = self._cargo_home_setup()
        runner = mock.Mock()
        calls: List[list] = []

        def run(args, **kwargs):
            calls.append(list(args))
            target.write_bytes(GOOD)  # 模拟 --force 覆盖
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(cmdmod.time, "sleep", lambda _s: None))
        stack.enter_context(
            mock.patch.object(cmdmod, "detect_github_token", return_value=(None, None))
        )
        stack.enter_context(
            mock.patch.object(Path, "home", side_effect=AssertionError("不应调用 Path.home()"))
        )
        mgr = CargoInstallManager(runner=runner)
        mgr.install(self.make_item())

        self.assertEqual(len(calls), 1)
        self.assertEqual(target.read_bytes(), GOOD)
        # 备份根 = <CARGO_HOME>/.. ，落点仍走 home/.local/state/dotfiles/tool-upgrade-backup
        found = slots(cargo_home.parent)
        self.assertEqual(len(found), 1, "CARGO_HOME/.. 下必须生成备份")
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["tool"], "taplo-cli")
        self.assertEqual(receipt["version"], "0.10.0")
        entry = receipt["entries"][0]
        self.assertEqual(entry["absolute_path"], str(target))
        self.assertEqual(entry["sha256"], OLD_SHA)
        self.assertEqual((found[0] / entry["backup"]).read_bytes(), OLD)
        self.assertEqual(len(slots(self.tmp)), 1, "没有写进 CWD 派生的落点")

    def test_cargo_home_only_failure_restores_old_binary(self):
        cargo_home, target = self._cargo_home_setup()
        runner = mock.Mock()
        seen: List[bool] = []

        def run(args, **kwargs):
            seen.append(len(slots(cargo_home.parent)) == 1)
            target.write_bytes(GOOD)
            return subprocess.CompletedProcess(args, 1, "", "")

        runner.run.side_effect = run
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(cmdmod.time, "sleep", lambda _s: None))
        stack.enter_context(
            mock.patch.object(cmdmod, "detect_github_token", return_value=(None, None))
        )
        stack.enter_context(
            mock.patch.object(Path, "home", side_effect=AssertionError("不应调用 Path.home()"))
        )
        mgr = CargoInstallManager(runner=runner)
        with self.assertRaises(InstallationError):
            mgr.install(self.make_item())

        self.assertEqual(runner.run.call_count, 3, "重试耗尽：3 次 cargo install")
        self.assertTrue(all(seen), "每次 run 之前备份已存在")
        self.assertEqual(target.read_bytes(), OLD, "失败后旧字节自动还原")
        self.assertEqual(len(slots(cargo_home.parent)), 1, "备份保留，可人工核对")

    def test_cargo_home_only_binstall_shortcut_is_backed_up_before_run(self):
        cargo_home, target = self._cargo_home_setup()
        item = self.make_item()
        item.strategy.fields["binstall_first"] = True
        runner = mock.Mock()
        observed: Dict[str, object] = {}
        calls: List[list] = []

        def run(args, **kwargs):
            calls.append(list(args))
            if len(calls) == 1:
                observed["backup_before_run"] = len(slots(cargo_home.parent)) == 1
                target.write_bytes(GOOD)
            return subprocess.CompletedProcess(args, 0, "", "")

        runner.run.side_effect = run
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch.object(
                CargoInstallManager, "_ensure_binstall", return_value="/bin/cargo-binstall",
            )
        )
        stack.enter_context(
            mock.patch.object(
                CargoInstallManager, "_binstall_command",
                return_value=["cargo", "binstall", "-y"],
            )
        )
        stack.enter_context(
            mock.patch.object(cmdmod, "detect_github_token", return_value=(None, None))
        )
        stack.enter_context(
            mock.patch.object(Path, "home", side_effect=AssertionError("不应调用 Path.home()"))
        )
        mgr = CargoInstallManager(runner=runner)
        mgr.install(item)

        self.assertEqual(len(calls), 1, "binstall 成功即返回")
        self.assertTrue(observed.get("backup_before_run"), "binstall run 之前已备份")
        self.assertEqual(target.read_bytes(), GOOD)
        self.assertEqual(len(slots(cargo_home.parent)), 1)


class GithubHomeMissing(NoHomeFixture):
    """github-release：HOME 缺失保持 fail-closed，文案明确「无法备份」。"""

    def make_item(self) -> PlanItem:
        return make_item()

    def manager_with_stubbed_download(self):
        manager = make_manager()
        download_calls: List[list] = []

        def forbidden(*args, **kwargs):
            download_calls.append(list(args))
            raise AssertionError("HOME 缺失时不得进入下载/安装阶段")

        manager._download_asset = forbidden  # type: ignore[method-assign]
        return manager, download_calls

    def test_home_missing_error_states_cannot_backup_and_no_download(self):
        manager, calls = self.manager_with_stubbed_download()
        with self.assertRaises(InstallationError) as ctx:
            manager.install(self.make_item())
        message = str(ctx.exception)
        self.assertIn("HOME", message)
        self.assertIn("无法备份", message)
        self.assertIn("无备份覆盖", message)
        self.assertIn("回滚", message)
        self.assertIn("fail-closed", message)
        self.assertEqual(calls, [], "未进入任何下载/安装")
        self.assert_no_cwd_writes()

    def test_relative_home_rejected_before_any_download(self):
        os.environ["HOME"] = "relative-home"
        manager, calls = self.manager_with_stubbed_download()
        with self.assertRaises(InstallationError) as ctx:
            manager.install(self.make_item())
        self.assertIn("绝对路径", str(ctx.exception))
        self.assertIn("当前工作目录", str(ctx.exception))
        self.assertEqual(calls, [])
        self.assert_no_cwd_writes()


class ParameterizedStateRoot(HomeFixture):
    """helper 参数化 state root：落点可钉死，且仍拒绝相对路径/CWD。"""

    def test_default_state_root_matches_state_root_for(self):
        self.assertEqual(state_root_for(self.home), state_root(self.home))

    def test_explicit_state_root_backup_and_manual_rollback(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        custom = self.home / "custom-state-root"
        backup = UpgradeBackup(
            self.home, label="yq", tool="yq", version=VERSION, state_root=custom,
        )
        backup.backup(dest)
        found = sorted(p for p in custom.iterdir() if p.is_dir())
        self.assertEqual(len(found), 1, "slot 建在显式 state_root 下")
        receipt = json.loads((found[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["entries"][0]["sha256"], OLD_SHA)
        self.assertEqual(slots(self.home), [], "默认落点不得再产生备份")

        dest.write_bytes(GOOD)  # 模拟「升级后」需要人工还原
        self.assertEqual(rollback_slot(found[0]), 1)
        self.assertEqual(dest.read_bytes(), OLD, "凭 receipt 可还原旧字节")
        self.assertTrue((found[0] / MANIFEST_NAME).is_file(), "还原后备份仍保留")

    def test_explicit_state_root_failure_rolls_back(self):
        dest = self.destination()
        dest.write_bytes(OLD)
        custom = self.home / "custom-state-root"
        backup = UpgradeBackup(
            self.home, label="yq", tool="yq", version=VERSION, state_root=custom,
        )
        backup.backup(dest)
        dest.write_bytes(GOOD)  # 模拟安装失败前已被覆盖
        self.assertEqual(backup.rollback(), 1)
        self.assertEqual(dest.read_bytes(), OLD, "失败路径自动还原")
        self.assertEqual(len(slots(self.home)), 0)

    def test_relative_state_root_is_rejected_without_writing_cwd(self):
        with self.assertRaises(InstallationError) as ctx:
            UpgradeBackup(
                self.home, label="yq", tool="yq", version=VERSION,
                state_root=Path("relative-state"),
            )
        self.assertIn("绝对路径", str(ctx.exception))
        self.assertIn("当前工作目录", str(ctx.exception))
        self.assertEqual(slots(self.home), [])


if __name__ == "__main__":
    unittest.main()
