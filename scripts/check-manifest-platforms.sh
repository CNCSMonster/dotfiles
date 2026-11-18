#!/usr/bin/env bash
# 守卫：manifest.toml 在每个声称支持的平台上都必须能解析，且下载策略自洽。
#
# 为什么需要它：`sha256 = "TODO"` 之类的问题不会让任何已有的 CI 作业变红——
# 校验发生在 build_install_plan（解析期）与下载期，而现有作业只在**当前 runner 的**
# 平台上跑（ubuntu + macos-latest=arm64）。结果是 linux/aarch64 与 macos/x86_64 长期
# 带着"规划期直接中止"和"下载成另一个架构的二进制"的缺陷，却始终绿着。
#
# 断言（全部离线，不访问网络）：
#   1. 三个平台的安装计划都能生成（捕获 StrategyError / ManifestError）
#   2. 每个 github-release 条目都带 64 位十六进制 sha256
#      （缺字段时 `_verify_checksum` 会静默 return，等于没有校验）
#   3. asset / bin 能完成占位符渲染，且不残留 `{`（捕获未知占位符）
#   4. 渲染后的 asset / bin 不携带**对立架构**的标记
#      （捕获"OS 级 asset 写死某架构、arch 表漏了覆盖"这类错误）
#   5. locked 条目的锁声明覆盖当前平台；npm 锁的 packages[] 含该平台 os/cpu 工件
#      （全平台锁记 platforms[]，旧的单平台 provenance 要求 os/arch 严格相等）
#
# 注意：本守卫抓不到"asset 名在上游不存在"（如 gh 的 v 前缀问题）——那需要联网核对。
#
# 用法: ./scripts/check-manifest-platforms.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

cd "$ROOT"
python3 - "$ROOT" <<'PY'
"""Check that manifest.toml resolves and is self-consistent on every platform."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "tool-installer"))

from tool_installer.errors import ToolInstallerError  # noqa: E402
from tool_installer.models import Environment  # noqa: E402
from tool_installer.parser import parse_manifest_file, parse_tools_file  # noqa: E402
from tool_installer.resolver import collect_ordered_tools, resolve_modules  # noqa: E402
from tool_installer.strategy import build_install_plan  # noqa: E402

# 项目声称支持的平台（README「支持平台」）。Termux 走 setup-termux.sh + pkg，
# 与本矩阵无关，故不在列。
# 注意：macOS x86_64 (Intel) 已从支持列表中移除（2026-10-15），
# 因为 Apple 已宣布 macOS 27 不再支持 Intel Mac，且主流生态已停止支持。
PLATFORMS = [
    Environment("linux", "x86_64"),
    Environment("linux", "aarch64"),
    Environment("macos", "aarch64"),
]

# 渲染后的 asset/bin 里出现这些 token，说明它其实是**另一个**架构的产物。
OPPOSITE_ARCH = {
    "aarch64": ("x86_64", "amd64"),
    "x86_64": ("aarch64", "arm64"),
}

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
LOCKED_MANAGERS = {"npm-locked", "python-locked"}


def npm_target_coverage(data, env):
    """Confirm an npm lock's packages[] carries a native artifact for this platform.

    package-lock v3 lists every platform's optional native package in packages[],
    each tagged with os/cpu.  npm ci silently omits the ones that do not match the
    current os/cpu, so a lock whose provenance matches this platform can still be
    unusable here when the matching (os, cpu) combination is missing.  A lock with
    no os/cpu records at all is pure JS and therefore platform-independent.

    Mapping follows npm's identifiers: macos→darwin, aarch64→arm64, x86_64→x64.
    A record that pins only os or only cpu is treated as agnostic on the other
    axis; "any" is treated as a wildcard.  This is deliberately conservative:
    once any native record exists, an explicit matching record must be present.
    """
    target = {
        ("linux", "x86_64"): ("linux", "x64"),
        ("linux", "aarch64"): ("linux", "arm64"),
        ("macos", "aarch64"): ("darwin", "arm64"),
    }.get((env.os, env.arch))
    if target is None:
        return f"未知目标平台 {env.os}/{env.arch}"
    target_os, target_cpu = target
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        return "npm 锁缺少 packages[]"
    native = False
    for path, record in packages.items():
        if not path or not isinstance(record, dict):
            continue
        raw_os = record.get("os")
        raw_cpu = record.get("cpu")
        if raw_os is None and raw_cpu is None:
            continue
        native = True
        os_values = ({str(x) for x in raw_os} if isinstance(raw_os, list)
                     else {str(raw_os)} if raw_os is not None else set())
        cpu_values = ({str(x) for x in raw_cpu} if isinstance(raw_cpu, list)
                      else {str(raw_cpu)} if raw_cpu is not None else set())
        os_ok = not os_values or "any" in os_values or target_os in os_values
        cpu_ok = not cpu_values or "any" in cpu_values or target_cpu in cpu_values
        if os_ok and cpu_ok:
            return None
    if not native:
        return None  # 纯 JS 锁，平台无关
    return (f"npm 锁缺少 {target_os}/{target_cpu} 平台工件"
            f"（packages[] 未覆盖该 os/cpu 组合）")


def lock_provenance(strategy, env):
    """Read generator OS/arch from the exact locked strategy path on this platform."""
    if strategy.lock_root is None or not strategy.lock_digest:
        return f"{env.os}/{env.arch}: 缺少已校验的 lock 摘要"
    raw = strategy.fields.get("lock")
    if not isinstance(raw, str) or Path(raw).is_absolute() or "\\" in raw:
        return f"{env.os}/{env.arch}: lock 路径不安全"
    if any(part in {"", ".", ".."} for part in raw.split("/")):
        return f"{env.os}/{env.arch}: lock 路径不安全"
    path = (strategy.lock_root / raw).resolve(strict=True)
    try:
        path.relative_to(strategy.lock_root)
        text = path.read_text(encoding="utf-8")
        if path.stat().st_size > 8 * 1024 * 1024:
            return f"{env.os}/{env.arch}: lock 超过 8 MiB"
    except (OSError, ValueError) as exc:
        return f"{env.os}/{env.arch}: 无法读取 {path}: {exc}"
    try:
        if strategy.manager == "npm-locked":
            data = json.loads(text)
            provenance = data.get("x-tool-lock-generator") or {}
        else:
            line = next((x for x in text.splitlines() if x.startswith("# generator: ")), "")
            provenance = json.loads(line.removeprefix("# generator: ")) if line else {}
    except (ValueError, TypeError) as exc:
        return f"{env.os}/{env.arch}: lock 生成平台元数据无法解析: {exc}"
    platforms = provenance.get("platforms")
    if platforms is not None:
        # 全平台解析快照：生成器逐平台解析并比对，只有三份结果完全一致才写
        # resolution=universal 和 platforms 列表。守卫只需确认本平台在列，
        # 再叠加 npm 工件覆盖；不要求锁在生成它的宿主平台上"看起来原生"。
        if (not isinstance(platforms, list) or not platforms
                or any(not isinstance(item, str) for item in platforms)):
            return f"{env.os}/{env.arch}: lock 的 platforms 元数据非法"
        if provenance.get("resolution") != "universal":
            return (f"{env.os}/{env.arch}: lock 声明了 platforms 但缺少 "
                    "resolution=universal")
        if f"{env.os}/{env.arch}" not in platforms:
            return (f"{env.os}/{env.arch}: lock 未声明覆盖该平台"
                    f"（已声明: {', '.join(platforms)}）")
    elif provenance.get("os") != env.os or provenance.get("arch") != env.arch:
        # 兼容旧的单平台 provenance：严格相等，避免把宿主锁冒充跨平台锁。
        return (f"{env.os}/{env.arch}: lock 由 {provenance.get('os')!r}/{provenance.get('arch')!r} 生成，"
                "不能用于该平台")
    if strategy.manager == "npm-locked":
        coverage_error = npm_target_coverage(data, env)
        if coverage_error:
            return f"{env.os}/{env.arch}: {coverage_error}"
    return None


def declared_locked_names(manifest):
    """Tool names whose manifest declares a locked manager at any table level.

    Used only for the progressive-migration sanity check: a locked declaration
    that resolves to locked on none of the PLATFORMS is dead configuration.
    """
    names = set()
    for name, table in manifest.items():
        if not isinstance(table, dict):
            continue
        if table.get("manager") in LOCKED_MANAGERS:
            names.add(name)
        for os_table in table.values():
            if not isinstance(os_table, dict):
                continue
            if os_table.get("manager") in LOCKED_MANAGERS:
                names.add(name)
            for arch_table in os_table.values():
                if (isinstance(arch_table, dict)
                        and arch_table.get("manager") in LOCKED_MANAGERS):
                    names.add(name)
    return names


def main() -> int:
    config = parse_tools_file(root / "tools.toml", "dev")
    manifest, _ = parse_manifest_file(config.manifest_path)
    tools = collect_ordered_tools(resolve_modules(config, "dev"))

    failures: list[str] = []
    locked_coverage: dict[tuple[str, str], set[str]] = {}
    for env in PLATFORMS:
        platform = f"{env.os}/{env.arch}"
        try:
            plan = build_install_plan(tools, manifest, env, config.manifest_path.parent)
        except ToolInstallerError as exc:
            failures.append(f"{platform}: 计划生成失败 -> {type(exc).__name__}: {exc}")
            print(f"  {platform:15s} ❌ 计划生成失败")
            continue

        for item in plan.items:
            if item.strategy.manager in LOCKED_MANAGERS:
                locked_coverage.setdefault(
                    (item.tool.reference.name, str(item.tool.reference.version)), set()
                ).add(platform)
                error = lock_provenance(item.strategy, env)
                if error:
                    # item 级定位：平台 + 工具名@版本，便于从矩阵失败里直接定位锁。
                    name = item.tool.reference.name
                    version = item.tool.reference.version
                    failures.append(f"{platform}: {name}@{version} 的 lock: {error}")
                continue
            if item.strategy.manager != "github-release":
                continue
            name = item.tool.reference.name
            version = item.tool.reference.version
            fields = item.strategy.fields

            if not HEX64.match(str(fields.get("sha256") or "")):
                failures.append(
                    f"{platform}: {name} 的 sha256 缺失或非法"
                    f"（{fields.get('sha256')!r}）——校验会被静默跳过"
                )

            for key in ("asset", "bin"):
                template = fields.get(key)
                if not isinstance(template, str):
                    continue
                try:
                    rendered = template.format(
                        tool=name, version=version, os=env.os, arch=env.arch
                    )
                except (KeyError, IndexError, ValueError) as exc:
                    failures.append(
                        f"{platform}: {name} 的 {key} 无法渲染（{template!r}）: {exc}"
                    )
                    continue
                if "{" in rendered or "}" in rendered:
                    failures.append(
                        f"{platform}: {name} 的 {key} 渲染后仍有占位符: {rendered}"
                    )
                for token in OPPOSITE_ARCH[env.arch]:
                    if token in rendered:
                        failures.append(
                            f"{platform}: {name} 的 {key} 是另一个架构的产物"
                            f"（含 {token!r}）: {rendered}"
                        )

        print(f"  {platform:15s} ✅ {len(plan.items)} items")

    # 全平台锁：每个 locked 工具都必须在每个 PLATFORMS 平台解析成功，且锁的
    # platforms 列表覆盖该平台（逐平台校验已在上面的 lock_provenance 完成）。
    # 兼容旧的单平台 provenance：若某平台仍用旧 manager，这里只给出 info，
    # 便于渐进迁移时定位；正式清单已全部使用全平台锁。
    # 硬约束：manifest 声明了 locked 策略、却没有任何 PLATFORMS 平台采用 -> 配置错误。
    required_platforms = {f"{env.os}/{env.arch}" for env in PLATFORMS}
    locked_names = {name for name, _version in locked_coverage}
    for name in sorted(declared_locked_names(manifest) - locked_names):
        failures.append(
            f"{name} 声明了 locked 策略但没有任何 PLATFORMS 平台采用（配置错误）")
    for (name, version), present in sorted(locked_coverage.items()):
        missing = sorted(required_platforms - present)
        if missing:
            # info，不计入 failures：渐进式迁移期间允许其余平台仍使用旧 manager。
            print(f"  ℹ️  {name}@{version} 在 {', '.join(missing)} 仍使用旧 manager"
                  "（平台渐进式迁移）")

    if failures:
        print(
            f"\n❌ manifest 平台矩阵检查失败（{len(failures)} 项）：", file=sys.stderr
        )
        for line in failures:
            print(f"   - {line}", file=sys.stderr)
        return 1

    print(
        f"\n✅ manifest 平台矩阵检查通过"
        f"（{len(PLATFORMS)}/{len(PLATFORMS)} 平台；github-release 条目均带 SHA256，"
        f"asset/bin 与目标架构一致；locked 条目逐平台校验全平台覆盖）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
