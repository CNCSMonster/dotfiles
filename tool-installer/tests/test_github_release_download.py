"""github-release 下载与完整性校验的源选择契约测试。

关注点：一次下载的「成功」必须同时满足**传输成功**与**SHA256 匹配**。镜像返回
HTTP 200 但内容不对，属于**该源失败**，不是**安装失败**——官方直连（候选列表最后
一项）必须仍有机会被尝试。

修复前 `_verify_checksum` 在下载循环之外执行：第一个能返回字节的源直接胜出并被
`return`，校验随后失败即抛错，剩余候选（含 direct GitHub）永不被访问。本文件把这
条语义钉死，防止回归。

  - DownloadSourceFallback：桩掉 `_fetch_into`，只锁「候选顺序 + 校验参与选源」。
  - InstallWiring：真文件系统路径，锁 install() 装的是**通过校验的那份字节**。
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from typing import Dict, List
from unittest import mock

# 目录名 tool-installer 带连字符、不能作包路径，故显式补一层。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tool_installer.errors import InstallationError  # noqa: E402
from tool_installer.managers import github_release as gr  # noqa: E402
from tool_installer.models import (  # noqa: E402
    Environment,
    GithubReleaseConfig,
    MergedStrategy,
    PlanItem,
    ToolReference,
    ToolSpec,
)

MIRROR = "https://mirror.example"
GOOD = b"the-real-artifact"
EVIL = b"a-tampered-artifact"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()

REPO = "mikefarah/yq"
VERSION = "4.53.3"
ASSET = "yq_linux_amd64"
DOWNLOAD_PATH = f"releases/download/{VERSION}/{ASSET}"


def make_item(*, sha256: str | None = GOOD_SHA, name: str = "yq") -> PlanItem:
    fields = {"repo": REPO, "asset": ASSET, "bin": ASSET}
    if sha256 is not None:
        fields["sha256"] = sha256
    return PlanItem(
        module_name="editors",
        tool=ToolSpec(reference=ToolReference(raw=f"{name}@{VERSION}", name=name, version=VERSION)),
        strategy=MergedStrategy(tool_name=name, manager="github-release", fields=fields),
        environment=Environment(os="linux", arch="x86_64"),
    )


def make_manager(*, retry: int = 0, mirrors: List[str] | None = None) -> gr.GithubReleaseManager:
    # retry=0 keeps the transport-retry loop out of the source-selection assertions.
    cfg = GithubReleaseConfig(
        github_mirrors=[MIRROR] if mirrors is None else mirrors,
        timeout=1.0,
        retry=retry,
    )
    return gr.GithubReleaseManager(cfg)


def stub_fetch(manager: gr.GithubReleaseManager, payloads: Dict[str, object]) -> List[str]:
    """Replace `_fetch_into` with a stub driven by ``{url: bytes | Exception}``.

    Returns the list of attempted URLs, in order.
    """
    calls: List[str] = []

    def fake(url: str, dest: Path) -> None:
        calls.append(url)
        if url not in payloads:
            raise AssertionError(f"unexpected URL attempted: {url}")
        payload = payloads[url]
        if isinstance(payload, Exception):
            raise payload
        assert isinstance(payload, bytes)
        dest.write_bytes(payload)

    manager._fetch_into = fake  # type: ignore[method-assign]
    return calls


def mirror_url() -> str:
    return make_manager()._build_download_urls(REPO, DOWNLOAD_PATH)[0]


def direct_url() -> str:
    return make_manager()._build_download_urls(REPO, DOWNLOAD_PATH)[-1]


class DownloadSourceFallback(unittest.TestCase):
    def download(self, item: PlanItem, manager: gr.GithubReleaseManager) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / ASSET
            manager._download_asset(item, REPO, DOWNLOAD_PATH, dest)
            return dest.read_bytes()

    def test_checksum_mismatch_on_mirror_falls_back_to_direct(self):
        manager = make_manager()
        calls = stub_fetch(manager, {mirror_url(): EVIL, direct_url(): GOOD})

        payload = self.download(make_item(), manager)

        self.assertEqual(payload, GOOD)
        self.assertEqual(calls, [mirror_url(), direct_url()], "候选顺序必须是镜像在前、直连在后")

    def test_integrity_failure_names_the_falling_source_and_is_reported(self):
        manager = make_manager()
        stub_fetch(manager, {mirror_url(): EVIL, direct_url(): GOOD})
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            self.download(make_item(), manager)

        warning = stderr.getvalue()
        self.assertIn("mirror.example", warning)
        self.assertIn("yq", warning)

    def test_transport_error_still_falls_back_to_direct(self):
        manager = make_manager()
        calls = stub_fetch(
            manager,
            {mirror_url(): urllib.error.URLError("connection reset"), direct_url(): GOOD},
        )

        self.assertEqual(self.download(make_item(), manager), GOOD)
        self.assertEqual(calls, [mirror_url(), direct_url()])

    def test_all_sources_exhausted_lists_every_candidate(self):
        manager = make_manager()
        stub_fetch(manager, {mirror_url(): EVIL, direct_url(): EVIL})

        with self.assertRaises(InstallationError) as ctx:
            self.download(make_item(), manager)

        message = str(ctx.exception)
        self.assertIn("any of 2 source(s)", message)
        self.assertIn("mirror.example", message)
        self.assertIn("direct GitHub", message)
        self.assertIn("Checksum mismatch", message)

    def test_checksum_failure_does_not_retry_the_same_source(self):
        # 完整性失败是「这个源的字节不可信」，重试同一 URL 只会拿到同样的坏字节。
        manager = make_manager(retry=3)
        calls = stub_fetch(manager, {mirror_url(): EVIL, direct_url(): GOOD})

        self.assertEqual(self.download(make_item(), manager), GOOD)
        self.assertEqual(calls.count(mirror_url()), 1)
        self.assertEqual(calls.count(direct_url()), 1)

    def test_without_sha256_first_transferable_source_wins(self):
        # 未声明 sha256 的条目行为不变：第一个传输成功的源直接胜出，不试探直连。
        manager = make_manager()
        calls = stub_fetch(manager, {mirror_url(): EVIL, direct_url(): GOOD})

        self.assertEqual(self.download(make_item(sha256=None), manager), EVIL)
        self.assertEqual(calls, [mirror_url()])


class TransportRetryBudget(unittest.TestCase):
    """传输层重试语义必须原样保留：每个源各有 retry+1 次尝试机会。

    这条走真实的 `_fetch_into`（只桩掉 urlopen / sleep），因为重试循环就在它内部——
    桩掉 `_fetch_into` 的同类断言等于什么都没测。
    """

    def test_each_source_gets_retry_plus_one_attempts(self):
        manager = make_manager(retry=2)
        attempted: List[str] = []

        def fake_urlopen(req, timeout=None):  # noqa: ARG001
            attempted.append(req.full_url)
            raise urllib.error.URLError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / ASSET
            with mock.patch.object(gr.urllib.request, "urlopen", fake_urlopen), \
                    mock.patch.object(gr.time, "sleep", lambda _s: None):
                with self.assertRaises(InstallationError):
                    manager._download_asset(make_item(), REPO, DOWNLOAD_PATH, dest)

        self.assertEqual(attempted.count(mirror_url()), 3, "retry=2 表示最多 3 次尝试")
        self.assertEqual(attempted.count(direct_url()), 3)


class InstallWiring(unittest.TestCase):
    """install() 必须安装「通过校验的那份字节」，而不是最先到达的那份。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._old_env = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._old_env is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_env
        self._tmp.cleanup()

    def test_installed_binary_is_the_verified_payload(self):
        manager = make_manager()
        stub_fetch(manager, {mirror_url(): EVIL, direct_url(): GOOD})

        manager.install(make_item())

        installed = self.home / ".local" / "bin" / "yq"
        self.assertEqual(installed.read_bytes(), GOOD)

    def test_install_fails_without_writing_when_no_source_matches(self):
        manager = make_manager()
        stub_fetch(manager, {mirror_url(): EVIL, direct_url(): EVIL})

        with self.assertRaises(InstallationError):
            manager.install(make_item())

        self.assertFalse((self.home / ".local" / "bin" / "yq").exists())


if __name__ == "__main__":
    unittest.main()
