"""Configuration parsers for tools.toml and manifest.toml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

from .errors import ConfigError, ManifestError
from .models import GithubReleaseConfig, ModuleSpec, ToolReference, ToolSpec, ToolsConfig
from .toml_loader import load_toml

_TOOL_REF_RE = re.compile(r"^[A-Za-z0-9._+\-]+(?:@[^@\s]+)?$")


def parse_tool_reference(raw: str) -> ToolReference:
    if not isinstance(raw, str) or not raw:
        raise ConfigError("Tool reference must be a non-empty string")
    if not _TOOL_REF_RE.match(raw):
        raise ConfigError(f"Invalid tool reference: {raw}")
    if raw.count("@") > 1:
        raise ConfigError(f"Invalid tool reference: {raw}")
    if "@" in raw:
        name, version = raw.split("@", 1)
    else:
        name, version = raw, "latest"
    if not name or not version:
        raise ConfigError(f"Invalid tool reference: {raw}")
    return ToolReference(raw=raw, name=name, version=version)


def parse_tools_file(path: Path, target_module: str) -> ToolsConfig:
    data = load_toml(path)
    _validate_root_tables(data, path)

    installer = data.get("tool-installer")
    if not isinstance(installer, dict):
        raise ConfigError("tools.toml requires [tool-installer]")
    unknown = set(installer) - {"manifest"}
    if unknown:
        raise ConfigError(f"Unknown [tool-installer] fields: {', '.join(sorted(unknown))}")
    manifest_value = installer.get("manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise ConfigError("[tool-installer].manifest must be a non-empty string")

    raw_modules: Dict[str, Dict[str, Any]] = {}
    for name, value in data.items():
        if name == "tool-installer":
            continue
        if not isinstance(value, dict):
            raise ConfigError(f"Top-level entry must be a table: {name}")
        raw_modules[name] = value

    if target_module not in raw_modules:
        raise ConfigError(f"Target module not found: {target_module}")

    reachable = _reachable_module_names(raw_modules, target_module)
    modules: Dict[str, ModuleSpec] = {}
    for name, value in raw_modules.items():
        if name in reachable:
            modules[name] = _parse_module(name, value, parse_tools=True)
        else:
            modules[name] = _parse_module(name, value, parse_tools=False)

    manifest_path = Path(manifest_value)
    if not manifest_path.is_absolute():
        manifest_path = path.parent / manifest_path
    return ToolsConfig(path=path, manifest_path=manifest_path, modules=modules)


def parse_manifest_file(path: Path) -> Tuple[Dict[str, Dict[str, Any]], GithubReleaseConfig]:
    data = load_toml(path)
    _validate_root_tables(data, path, error_type=ManifestError)

    gh_config = _parse_github_release_section(data.get("_github-release"), path)
    _reject_deprecated_network_section(data, path)

    manifest: Dict[str, Dict[str, Any]] = {}
    for name, value in data.items():
        if name.startswith("_"):
            continue
        if not isinstance(value, dict):
            raise ManifestError(f"Manifest top-level entry must be a table: {name}")
        if "platforms" in value:
            raise ManifestError(f"Unsupported manifest field for {name}: platforms")
        manifest[name] = value
    return manifest, gh_config


def _reject_deprecated_network_section(data: Mapping[str, Any], path: Path) -> None:
    if "_network" in data:
        raise ManifestError(
            f"[_network] is no longer supported in {path}. "
            "Use [_github-release] instead (see docs/draft-manifest-manager-config.md)."
        )


def _parse_github_release_section(raw: Any, path: Path) -> GithubReleaseConfig:
    if raw is None:
        return GithubReleaseConfig()
    if not isinstance(raw, dict):
        raise ManifestError(f"[_github-release] must be a table in {path}")

    known = {"github_mirrors", "timeout", "retry"}
    unknown = set(raw) - known
    if unknown:
        raise ManifestError(f"Unknown [_github-release] fields: {', '.join(sorted(unknown))}")

    mirrors: List[str] = []
    raw_mirrors = raw.get("github_mirrors")
    if raw_mirrors is not None:
        if not isinstance(raw_mirrors, list):
            raise ManifestError("[_github-release].github_mirrors must be an array")
        for i, item in enumerate(raw_mirrors):
            if not isinstance(item, str) or not item:
                raise ManifestError(f"[_github-release].github_mirrors[{i}] must be a non-empty string")
            mirrors.append(item.rstrip("/"))

    timeout = 30.0
    raw_timeout = raw.get("timeout")
    if raw_timeout is not None:
        if not isinstance(raw_timeout, (int, float)) or raw_timeout <= 0:
            raise ManifestError("[_github-release].timeout must be a positive number")
        timeout = float(raw_timeout)

    retry = 3
    raw_retry = raw.get("retry")
    if raw_retry is not None:
        if not isinstance(raw_retry, int) or raw_retry < 0:
            raise ManifestError("[_github-release].retry must be a non-negative integer")
        retry = raw_retry

    return GithubReleaseConfig(github_mirrors=mirrors, timeout=timeout, retry=retry)


def _validate_root_tables(data: Mapping[str, Any], path: Path, error_type: type[Exception] = ConfigError) -> None:
    for key, value in data.items():
        if not isinstance(value, dict):
            raise error_type(f"Bare top-level keys are not supported in {path}: {key}")


def _reachable_module_names(raw_modules: Mapping[str, Mapping[str, Any]], target_module: str) -> Set[str]:
    reachable: Set[str] = set()

    def visit(name: str) -> None:
        if name in reachable:
            return
        module = raw_modules.get(name)
        if module is None:
            return
        reachable.add(name)
        depends_value = module.get("depends", [])
        if isinstance(depends_value, list):
            for dependency in depends_value:
                if isinstance(dependency, str):
                    visit(dependency)

    visit(target_module)
    return reachable


def _parse_module(name: str, data: Mapping[str, Any], parse_tools: bool = True) -> ModuleSpec:
    if not name:
        raise ConfigError("Module name must be non-empty")
    if name == "tool-installer":
        raise ConfigError("tool-installer is reserved")

    depends_value = data.get("depends", [])
    if not isinstance(depends_value, list) or any(not isinstance(item, str) or not item for item in depends_value):
        raise ConfigError(f"Module {name} depends must be an array of non-empty strings")

    if not parse_tools:
        return ModuleSpec(name=name)

    tools: List[ToolSpec] = []
    for key, value in data.items():
        if key == "depends":
            continue
        tools.append(_parse_tool_spec(key, value))
    return ModuleSpec(name=name, depends=list(depends_value), tools=tools)


def _parse_tool_spec(key: str, value: Any) -> ToolSpec:
    reference = parse_tool_reference(key)
    if isinstance(value, str):
        return ToolSpec(reference=reference, desc=value, allow_fail=False)
    if isinstance(value, dict):
        unknown = set(value) - {"desc", "allow_fail"}
        if unknown:
            raise ConfigError(f"Unknown fields for tool {key}: {', '.join(sorted(unknown))}")
        desc = value.get("desc")
        if desc is not None and not isinstance(desc, str):
            raise ConfigError(f"Tool {key} desc must be a string")
        allow_fail = value.get("allow_fail", False)
        if not isinstance(allow_fail, bool):
            raise ConfigError(f"Tool {key} allow_fail must be a bool")
        return ToolSpec(reference=reference, desc=desc, allow_fail=allow_fail)
    raise ConfigError(f"Tool {key} value must be a string or table")
