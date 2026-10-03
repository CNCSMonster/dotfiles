"""apt 执行策略：有界超时、装包前源预检、失败归因。

与 ``scripts/lib/apt.sh`` 是同一套策略的两份实现，因为两者服务不同的启动阶段：

- **本模块（Python）**：稳定期。tool-installer 可用之后的所有 apt 调用
  （``AptManager``）。
- **scripts/lib/apt.sh（shell）**：自举期。python3 尚未安装时引导 python3、以及
  跑在 ``tool-installer install dev`` 之前的 Layer 1 运行时依赖门禁——那时无法依赖
  本工具自己（鸡生蛋）。

因此两侧的数值（连接超时 / 重试 / dpkg 锁等待）必须保持一致，改一侧时同步另一侧，
政策与背景见 ``docs/tool-installer-migration-plan.md`` §4.3。

边界与 shell 侧相同：只读、只诊断、只提示，**绝不改写 /etc/apt 下的用户源配置**
（换源是用户的决定，这里只给出可直接复制的命令）。
"""

from __future__ import annotations

import glob
import os
import re
import socket
from typing import Callable, Iterable, List, Optional, Sequence

# ── 有界超时策略（与 scripts/lib/apt.sh 的 APT_OPTS 数值一致） ──
APT_HTTP_TIMEOUT = 30
APT_RETRIES = 1
APT_LOCK_TIMEOUT = 60

# 整条 apt 命令的兜底上限。apt 内部已有 per-object 超时，这层只保证"永不无限等"，
# 不参与正常安装的时限判断（大包下载不会因为这个值被打断）。
APT_COMMAND_TIMEOUT = 1800

DEFAULT_SOURCE_PATHS: Sequence[str] = ("/etc/apt/sources.list", "/etc/apt/sources.list.d")

TENCENT_INTERNAL_FIX = (
    "sudo sed -i 's/mirrors\\.tencentyun\\.com/mirrors.cloud.tencent.com/g' "
    "/etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null"
)


def apt_options() -> List[str]:
    """作为命令行参数传给 apt-get（优先级高于 /etc/apt/apt.conf.d 与用户配置）。"""
    return [
        "-o", f"Acquire::http::Timeout={APT_HTTP_TIMEOUT}",
        "-o", f"Acquire::https::Timeout={APT_HTTP_TIMEOUT}",
        "-o", f"Acquire::Retries={APT_RETRIES}",
        "-o", f"DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}",
    ]


# ── 失败归因 ──


def attribute_failure(log: str) -> str:
    """把 apt 输出翻译成「原因 + 可执行的修复动作」。只读日志，不改任何配置。

    分支顺序与 scripts/lib/apt.sh 的 apt_failure_hint 一致：DNS 判断必须排在
    "源不可达"之前，否则 DNS 故障会被误归因为网络源问题。
    """
    if re.search(
        r"(password is required|a terminal is required|no tty|requires elevated privileges)",
        log,
        re.I,
    ):
        return (
            "需要 sudo 权限（当前无交互终端）。请在终端执行后重跑: "
            "sudo -v && ./setup.sh"
        )

    if "Permission denied" in log and re.search(r"lock|/var/lib", log, re.I):
        return (
            "权限不足：apt 需要 root（当前既非 root 也无可用 sudo）。"
            "请用 root 运行，或配置 sudo 后重跑 ./setup.sh"
        )

    if re.search(
        r"could not get lock|could not open lock|unable to acquire .*lock|waiting for cache lock",
        log,
        re.I,
    ):
        return (
            "dpkg/apt 前端锁被占用（常见: apt-daily / unattended-upgrades 在后台运行）。"
            "查看: ps aux | grep -E 'apt|dpkg'；等它结束后重跑 ./setup.sh"
        )

    if re.search(
        r"temporary failure resolving|could not resolve|name or service not known",
        log,
        re.I,
    ):
        return "DNS 解析失败：检查网络 / 代理 / /etc/resolv.conf 后重跑 ./setup.sh"

    hits = [
        line.strip()
        for line in log.splitlines()
        if re.search(r"failed to fetch|could not connect|connection timed out|^\s*err:", line, re.I)
    ]
    if hits:
        # dict.fromkeys 去重且保持 apt 原始顺序
        head = "\n".join(f"     {h}" for h in dict.fromkeys(hits))
        if "tencentyun" in log.lower():
            return (
                f"apt 源获取失败（apt 原始诊断）:\n{head}\n"
                "   原因: 腾讯云内网源在非腾讯云内网环境不可达（解析到 169.254.x）。"
                "换成公网源后重跑:\n"
                f"     {TENCENT_INTERNAL_FIX}"
            )
        return (
            f"apt 源获取失败（apt 原始诊断）:\n{head}\n"
            "   处理: 把上方不可达的源换成本机可达的公网源后重跑 ./setup.sh"
        )

    if re.search(r"command timed out after", log, re.I):
        return (
            "命令超时（有界上限已触发）：多半是源在黑洞上重试，"
            "典型是云内网专用源（169.254.x）在非该云环境不可达。检查源地址后重跑 ./setup.sh"
        )

    return "apt 执行失败（未识别的失败模式），原始输出见上方；修复后重跑 ./setup.sh"


def failure_message(pkg: str, log: str) -> str:
    """保持与 CommandManager 基类一致的首行格式，只在其后追加归因。"""
    return f"Install failed for {pkg} with manager apt\n{attribute_failure(log)}"


# ── 装包前的源预检 ──


def is_private_ip(ip: str) -> bool:
    """私网 / 链路本地地址判定（169.254.x 是云内网专用源与 metadata 的常见段）。"""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if first in (0, 10, 127):
        return True
    if first == 169 and second == 254:
        return True
    if first == 172 and 16 <= second <= 31:
        return True
    if first == 192 and second == 168:
        return True
    return False


def _uris_in(text: str) -> List[str]:
    """覆盖经典 .list（deb <uri> …）与 deb822 .sources（URIs: <uri>）两种格式。"""
    return re.findall(r"https?://[^/\s]+", text)


def _candidate_files(path: str) -> List[str]:
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.list")) + glob.glob(os.path.join(path, "*.sources")))
    if os.path.isfile(path):
        return [path]
    return []


def iter_source_uris(paths: Optional[Sequence[str]] = None) -> List[str]:
    """读取 apt 源里配置的所有 http(s) 主机（去重排序）。paths 供测试注入。"""
    found = set()
    for path in paths if paths is not None else DEFAULT_SOURCE_PATHS:
        for name in _candidate_files(path):
            try:
                with open(name, encoding="utf-8", errors="replace") as handle:
                    found.update(_uris_in(handle.read()))
            except OSError:
                continue
    return sorted(found)


def _host_of(uri: str) -> str:
    host = uri.split("://", 1)[-1].split("/", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _resolve_ipv4(host: str, resolve: Callable[..., object]) -> Optional[str]:
    try:
        infos = resolve(host, 80, socket.AF_INET)  # type: ignore[call-arg]
    except OSError:
        return None
    if not isinstance(infos, (list, tuple)):
        return None
    for info in infos:
        try:
            ip = info[4][0]
        except (IndexError, TypeError):
            continue
        if isinstance(ip, str) and ip.count(".") == 3:
            return ip
    return None


def preflight_source_warnings(
    uris: Optional[Iterable[str]] = None,
    resolve: Optional[Callable[..., object]] = None,
) -> List[str]:
    """装包前的源预检：报告解析到私网/链路本地地址的源，**只提示不阻断**。

    与 shell 侧 ``apt_sources_health_check`` 同策略；差异在于 shell 侧额外做 5s TCP
    探测（它在装包前的 shell 上下文里），本侧做 DNS 解析 + 私网判定——"公网源真的
    不可达"这一事实由 apt 自己的有界超时兜底，失败后由 :func:`attribute_failure` 归因。

    ``resolve`` 可注入，供测试离线运行。
    """
    resolver = resolve or socket.getaddrinfo
    warnings: List[str] = []
    flagged: List[str] = []
    seen = set()

    for uri in uris if uris is not None else iter_source_uris():
        host = _host_of(uri)
        if not host or host in seen:
            continue
        seen.add(host)
        ip = _resolve_ipv4(host, resolver)
        if ip and is_private_ip(ip):
            flagged.append(f"{uri} → {ip}")

    if not flagged:
        return warnings

    warnings.append(
        "❌ 检测到解析到私网/链路本地地址的 apt 源（本机网络不可达，会拖到超时）:"
    )
    warnings.extend(f"     {entry}" for entry in flagged)
    if any("tencentyun" in entry for entry in flagged):
        warnings.append("   腾讯云内网源 → 公网源（复制执行后重跑 ./setup.sh）:")
        warnings.append(f"     {TENCENT_INTERNAL_FIX}")
    else:
        warnings.append("   处理: 把该源替换为本机可达的公网源后重跑 ./setup.sh")
    return warnings
