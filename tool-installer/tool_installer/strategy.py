"""Manifest strategy resolution and validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .errors import ManifestError, StrategyError
from .models import Environment, InstallPlan, MergedStrategy, PlanItem, ToolSpec

_OS_TABLES = {"linux", "macos"}
_ARCH_TABLES = {"x86_64", "aarch64"}
_COMMON = {"manager", "force"}
_SUPPORTED: Dict[str, Dict[str, Any]] = {
    "apt": {"required": {"pkg"}, "optional": set()},
    "brew": {"required": {"pkg"}, "optional": set(), "latest_only": True},
    "brew-cask": {"required": {"pkg"}, "optional": set(), "latest_only": True},
    "cargo-binstall": {"required": {"pkg"}, "optional": {"bin"}},
    "cargo-install": {"required": {"pkg"}, "optional": {"bin", "locked", "binstall_first", "binstall_retry", "binstall_fallback_compile", "git", "tag", "branch", "rev"}},
    "rustup": {"required": set(), "optional": {"components", "targets", "profile", "set_default"}},
    "mise": {"required": {"plugin"}, "optional": set()},
    "npm-global": {"required": {"pkg"}, "optional": {"bin", "registry"}},
    "pnpm-global": {"required": {"pkg"}, "optional": {"bin", "registry"}},
    "uv-tool": {"required": {"pkg"}, "optional": {"bin", "python", "with"}},
    "github-release": {"required": {"repo", "asset", "bin"}, "optional": {"sha256", "install_name", "version_probe"}},
    "script": {"required": {"path"}, "optional": set()},
}
_STRING_FIELDS = {"manager", "pkg", "bin", "registry", "plugin", "python", "git", "tag", "branch", "rev", "profile", "repo", "asset", "sha256", "install_name", "path"}
_BOOL_FIELDS = {"force", "locked", "binstall_first", "set_default", "binstall_fallback_compile"}
_INT_FIELDS = {"binstall_retry"}
_ARRAY_FIELDS = {"with", "components", "targets"}
_NESTED_TABLE_FIELDS = {"version_probe"}
_VERSION_PROBE_FIELDS = {"command", "regex"}


def build_install_plan(
    ordered_tools: List[Tuple[str, ToolSpec]],
    manifest: Mapping[str, Mapping[str, Any]],
    environment: Environment,
    manifest_dir: Path,
) -> InstallPlan:
    items: List[PlanItem] = []
    rustup_defaults = 0
    for module_name, tool in ordered_tools:
        strategy = resolve_tool_strategy(tool, manifest, environment, manifest_dir)
        if strategy.manager == "rustup" and strategy.fields.get("set_default") is True:
            rustup_defaults += 1
        items.append(PlanItem(module_name=module_name, tool=tool, strategy=strategy, environment=environment))
    if rustup_defaults > 1:
        raise StrategyError("At most one rustup strategy may set set_default = true")
    return InstallPlan(items=items)


def resolve_tool_strategy(
    tool: ToolSpec,
    manifest: Mapping[str, Mapping[str, Any]],
    environment: Environment,
    manifest_dir: Path,
) -> MergedStrategy:
    name = tool.reference.name
    table = manifest.get(name)
    if table is None:
        raise ManifestError(f"Missing manifest strategy for tool: {name}")
    os_table = table.get(environment.os)
    if not isinstance(os_table, dict):
        raise StrategyError(f"Missing {environment.os} strategy for tool: {name}")

    merged: Dict[str, Any] = {}
    merged.update(_strategy_fields(table))
    merged.update(_strategy_fields(os_table))
    arch_table = os_table.get(environment.arch)
    if arch_table is not None:
        if not isinstance(arch_table, dict):
            raise StrategyError(f"Architecture strategy must be a table for {name}")
        merged.update(_strategy_fields(arch_table))

    # Apply bin default: defaults to the parsed logical tool name
    manager = merged.get("manager", "")
    contract = _SUPPORTED.get(manager)
    if contract and "bin" in (contract["required"] | contract["optional"]) and "bin" not in merged:
        merged["bin"] = name

    _validate_strategy(name, tool.reference.version, merged, manifest_dir)
    return MergedStrategy(tool_name=name, manager=merged["manager"], fields=merged, force=merged.get("force", False))


def _strategy_fields(table: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in table.items():
        if key in _OS_TABLES or key in _ARCH_TABLES:
            continue
        # Nested tables (like version_probe) are preserved as-is
        if key in _NESTED_TABLE_FIELDS and isinstance(value, dict):
            result[key] = value
            continue
        # Skip OS/Arch subtables
        if isinstance(value, dict):
            continue
        result[key] = value
    return result


def _validate_strategy(tool_name: str, version: str, fields: Dict[str, Any], manifest_dir: Path) -> None:
    manager = fields.get("manager")
    if not isinstance(manager, str) or not manager:
        raise StrategyError(f"Strategy for {tool_name} must contain manager")
    contract = _SUPPORTED.get(manager)
    if contract is None:
        raise StrategyError(f"Unsupported manager for {tool_name}: {manager}")
    allowed = _COMMON | contract["required"] | contract["optional"]
    unknown = set(fields) - allowed
    if unknown:
        raise StrategyError(f"Unknown strategy fields for {tool_name}: {', '.join(sorted(unknown))}")
    for required in contract["required"]:
        if required not in fields:
            raise StrategyError(f"Missing required field for {tool_name}: {required}")
    for key, value in fields.items():
        if key in _NESTED_TABLE_FIELDS:
            if key == "version_probe":
                _validate_version_probe(tool_name, value)
            continue
        _validate_field(tool_name, key, value)
    if fields.get("force", False) is not False and not isinstance(fields.get("force"), bool):
        raise StrategyError(f"force for {tool_name} must be a bool")
    if contract.get("latest_only") and version != "latest":
        raise StrategyError(f"Manager {manager} does not support non-latest selector for {tool_name}")
    if manager == "cargo-install":
        _validate_cargo_install(tool_name, version, fields)
    if manager == "github-release":
        _validate_github_release(tool_name, fields)
    if manager == "script":
        _validate_script(tool_name, fields, manifest_dir)


def _validate_version_probe(tool_name: str, probe: Any) -> None:
    """Validate the version_probe subtable for github-release manager."""
    if not isinstance(probe, dict):
        raise StrategyError(f"version_probe for {tool_name} must be a table")

    # Check for unknown fields in version_probe
    unknown_probe = set(probe) - _VERSION_PROBE_FIELDS
    if unknown_probe:
        raise StrategyError(f"Unknown version_probe fields for {tool_name}: {', '.join(sorted(unknown_probe))}")

    # command is required
    if "command" not in probe:
        raise StrategyError(f"version_probe.command is required for {tool_name}")
    cmd = probe["command"]
    if not isinstance(cmd, list) or not cmd:
        raise StrategyError(f"version_probe.command for {tool_name} must be a non-empty array")
    for i, part in enumerate(cmd):
        if not isinstance(part, str) or not part:
            raise StrategyError(f"version_probe.command[{i}] for {tool_name} must be a non-empty string")
        # Only {bin} placeholder is supported
        # Check that no other {xxx} placeholders exist
        for m in re.finditer(r"\{([^}]+)\}", part):
            if m.group(1) != "bin":
                raise StrategyError(f"version_probe.command for {tool_name} only supports {{bin}} placeholder, found {{{m.group(1)}}}")

    # regex is required
    if "regex" not in probe:
        raise StrategyError(f"version_probe.regex is required for {tool_name}")
    regex_str = probe["regex"]
    if not isinstance(regex_str, str) or not regex_str:
        raise StrategyError(f"version_probe.regex for {tool_name} must be a non-empty string")
    # Must be a valid regex with a named capture group 'version'
    try:
        pattern = re.compile(regex_str)
    except re.error as exc:
        raise StrategyError(f"version_probe.regex for {tool_name} is not a valid regex: {exc}")
    if "version" not in pattern.groupindex:
        raise StrategyError(f"version_probe.regex for {tool_name} must contain a named capture group 'version'")


def _validate_field(tool_name: str, key: str, value: Any) -> None:
    if key in _STRING_FIELDS:
        if not isinstance(value, str) or not value:
            raise StrategyError(f"Field {key} for {tool_name} must be a non-empty string")
    elif key in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise StrategyError(f"Field {key} for {tool_name} must be a bool")
    elif key in _INT_FIELDS:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise StrategyError(f"Field {key} for {tool_name} must be a non-negative integer")
    elif key in _ARRAY_FIELDS:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise StrategyError(f"Field {key} for {tool_name} must be an array of non-empty strings")


def _validate_cargo_install(tool_name: str, version: str, fields: Mapping[str, Any]) -> None:
    selectors = [key for key in ("tag", "branch", "rev") if key in fields]
    if len(selectors) > 1:
        raise StrategyError(f"cargo-install selector fields are mutually exclusive for {tool_name}")
    if selectors and "git" not in fields:
        raise StrategyError(f"cargo-install {selectors[0]} requires git for {tool_name}")
    if "git" in fields and version != "latest":
        raise StrategyError(f"cargo-install git strategies require latest selector for {tool_name}")


def _validate_github_release(tool_name: str, fields: Mapping[str, Any]) -> None:
    repo = fields["repo"]
    if not re.match(r"^[^/\s]+/[^/\s]+$", repo):
        raise StrategyError(f"github-release repo must be owner/name for {tool_name}")
    bin_value = fields["bin"]
    if Path(bin_value).is_absolute() or ".." in Path(bin_value).parts:
        raise StrategyError(f"github-release bin must be a safe relative path for {tool_name}")
    install_name = fields.get("install_name")
    if install_name and ("/" in install_name or os.sep in install_name):
        raise StrategyError(f"github-release install_name must be a filename for {tool_name}")
    sha256 = fields.get("sha256")
    if sha256 and not re.match(r"^[0-9a-fA-F]{64}$", sha256):
        raise StrategyError(f"github-release sha256 must be a 64-character hex digest for {tool_name}")


def _validate_script(tool_name: str, fields: Mapping[str, Any], manifest_dir: Path) -> None:
    raw_path = fields["path"]
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise StrategyError(f"script path must be a safe relative path for {tool_name}")
    resolved = (manifest_dir / path).resolve()
    try:
        resolved.relative_to(manifest_dir.resolve())
    except ValueError as exc:
        raise StrategyError(f"script path escapes manifest directory for {tool_name}") from exc
    if not resolved.is_file():
        raise StrategyError(f"script path does not exist for {tool_name}: {raw_path}")
    if not os.access(resolved, os.X_OK):
        raise StrategyError(f"script path is not executable for {tool_name}: {raw_path}")
    fields["path"] = str(resolved)
