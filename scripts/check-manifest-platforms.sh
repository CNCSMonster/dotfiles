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
    if provenance.get("os") != env.os or provenance.get("arch") != env.arch:
        return (f"{env.os}/{env.arch}: lock 由 {provenance.get('os')!r}/{provenance.get('arch')!r} 生成，"
                "不能用于该平台")
    return None


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
                    failures.append(f"{platform}: {item.tool.reference.name} 的 lock: {error}")
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

    required_platforms = {f"{env.os}/{env.arch}" for env in PLATFORMS}
    for (name, version), present in sorted(locked_coverage.items()):
        missing = sorted(required_platforms - present)
        if missing:
            failures.append(f"{name}@{version} 的 locked 策略缺少平台: {', '.join(missing)}")

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
        f"asset/bin 与目标架构一致；locked 条目逐平台校验生成环境）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
