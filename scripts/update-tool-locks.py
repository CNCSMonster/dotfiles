#!/usr/bin/env python3
"""Offline lock validation and platform-universal lock maintenance.

A lock is a resolution snapshot for every declared platform, not a copy of one
host's resolution: generation resolves once per declared target (npm os/cpu or
uv --python-platform), refuses to publish when the results differ, and records
the verified target list in the lock provenance. Consumers still validate the
lock offline; no resolver runs during install planning or checking.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool-installer"))
from tool_installer.errors import ToolInstallerError, ConfigError
from tool_installer.hash_lock import validate_npm_lock, validate_python_lock, _target
from tool_installer.models import Environment
from tool_installer.parser import parse_tools_file, parse_manifest_file
from tool_installer.strategy import _validate_strategy
from tool_installer.managers.locked import declared_bins

LIMIT = 8 * 1024 * 1024

# The project's declared platform matrix (README「支持平台」; Termux is separate).
# (tool environment os, tool environment arch, npm os, npm cpu, uv --python-platform)
PLATFORMS = (
    ("linux", "x86_64", "linux", "x64", "x86_64-unknown-linux-gnu"),
    ("linux", "aarch64", "linux", "arm64", "aarch64-unknown-linux-gnu"),
    ("macos", "aarch64", "darwin", "arm64", "aarch64-apple-darwin"),
)
PLATFORM_NAMES = tuple(f"{os_name}/{arch}" for os_name, arch, *_ in PLATFORMS)


def select(tools, module, name, environment):
    config = parse_tools_file(tools, module)
    matches = [t for m in config.modules.values() for t in m.tools
               if t.reference.name == name or t.reference.raw == name]
    unique = {t.reference.raw: t for t in matches}
    if len(unique) != 1:
        raise ConfigError("Tool must select exactly one declared version in tools.toml")
    tool = next(iter(unique.values()))
    manifest, _ = parse_manifest_file(config.manifest_path)
    table = manifest.get(tool.reference.name, {})
    os_table = table.get(environment.os)
    if not isinstance(os_table, dict):
        raise ConfigError(f"No strategy for selected OS {environment.os}")
    arch_table = os_table.get(environment.arch, {})
    if not isinstance(arch_table, dict):
        raise ConfigError("Invalid architecture strategy")
    fields = {}
    for source in (table, os_table, arch_table):
        for key, value in source.items():
            if key not in {"linux", "macos", "x86_64", "aarch64"}:
                fields[key] = value
    if fields.get("manager") not in {"npm-locked", "python-locked"}:
        raise ConfigError("Only npm-locked/python-locked declarations are supported; edit declarations separately")
    if "bins" not in fields:
        fields.setdefault("bin", tool.reference.name)
    _validate_strategy(tool.reference.name, tool.reference.version, fields, config.manifest_path.parent)
    declared_bins(fields)
    root = config.manifest_path.parent.resolve()
    raw = fields["lock"]
    if Path(raw).is_absolute() or "\\" in raw or any(p in {"", ".", ".."} for p in raw.split("/")):
        raise ConfigError("Lock must be a safe manifest-relative path")
    output = root / raw
    try:
        output.relative_to(root)
    except ValueError:
        raise ConfigError("Lock escapes manifest directory")
    if output.resolve() != output:
        raise ConfigError("Lock path must not contain symlinks or escape manifest directory")
    _target("", fields["pkg"], tool.reference.version, python=fields["manager"] == "python-locked")
    return fields, tool.reference.version, output


def select_universal(tools, module, name):
    """Require one declaration for every declared platform.

    A shared lock cannot honestly represent per-platform strategies, so any
    divergence is refused instead of silently writing the host variant.
    """
    selections = [select(tools, module, name, Environment(os_name, arch))
                  for os_name, arch, *_ in PLATFORMS]
    reference = selections[0]
    for platform, selection in zip(PLATFORM_NAMES, selections):
        if selection != reference:
            raise ConfigError(
                f"Locked declaration differs on {platform}; universal locks require "
                "the same manager/pkg/lock on every declared platform")
    return reference


def validate(text, fields, version):
    if len(text.encode("utf-8")) > LIMIT:
        raise ConfigError("Lock exceeds 8 MiB")
    validator = validate_npm_lock if fields["manager"] == "npm-locked" else validate_python_lock
    return validator(text, fields["pkg"], version)


def flatten_python(text):
    """Join only explicit continuations; never discard environment markers."""
    lines, pending = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if pending:
                raise ConfigError("Unexpected comment/blank in requirement continuation")
            continue
        if ";" in line:
            raise ConfigError("Python environment markers cannot be represented by the validator; refusing to strip markers")
        continued = line.endswith("\\")
        pending += (line[:-1].strip() if continued else line) + " "
        if not continued:
            lines.append(pending.strip())
            pending = ""
    if pending:
        raise ConfigError("Unterminated requirement continuation")
    return "\n".join(lines) + "\n"


def run_command(command, *, cwd, extra_env=None):
    # Retain activated executable lookup, never ambient runtime injection/config/secrets.
    cwd = Path(cwd)
    user_config = cwd / "isolated-user.npmrc"
    global_config = cwd / "isolated-global.npmrc"
    user_config.write_text("", encoding="utf-8")
    global_config.write_text("", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(cwd),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(cwd),
           "XDG_CONFIG_HOME": str(cwd / "config"), "XDG_CACHE_HOME": str(cwd / "cache"),
           "NPM_CONFIG_USERCONFIG": str(user_config),
           "NPM_CONFIG_GLOBALCONFIG": str(global_config),
           "NPM_CONFIG_CACHE": str(cwd / "npm-cache"),
           "NPM_CONFIG_IGNORE_SCRIPTS": "true", "NPM_CONFIG_AUDIT": "false",
           "NPM_CONFIG_FUND": "false", "UV_NO_CONFIG": "1",
           "UV_PYTHON_DOWNLOADS": "never", "UV_CACHE_DIR": str(cwd / "uv-cache")}
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                capture_output=True, check=False, timeout=300)
    except subprocess.TimeoutExpired:
        raise ConfigError("Generator timed out after 300 seconds; output unchanged") from None
    if result.returncode:
        # Resolver stderr can contain registry credentials; do not echo it.
        raise ConfigError(f"{Path(command[0]).name} failed (exit {result.returncode}); output unchanged")
    return result.stdout.strip()


def _provenance(executable, generator_version, manager):
    return {"generator": str(Path(executable).resolve()), "version": generator_version,
            "platforms": list(PLATFORM_NAMES), "resolution": "universal",
            "python": sys.version.split()[0] if manager == "python-locked" else None}


def generate(fields, version, *, runner=run_command):
    executable = shutil.which("npm" if fields["manager"] == "npm-locked" else "uv")
    if not executable:
        raise ConfigError("Required generator is not installed; no tools will be installed automatically")
    with tempfile.TemporaryDirectory(prefix="tool-lock-") as directory:
        project = Path(directory)
        generator_version = runner([executable, "--version"], cwd=project)
        provenance = _provenance(executable, generator_version, fields["manager"])
        if fields["manager"] == "npm-locked":
            package = {"name": "tool-lock-maintenance", "version": "1.0.0",
                       "private": True, "dependencies": {fields["pkg"]: version}}
            expected = None
            for os_name, arch, npm_os, npm_cpu, _uv in PLATFORMS:
                target = project / f"npm-{os_name}-{arch}"
                target.mkdir()
                (target / "package.json").write_text(json.dumps(package))
                runner([executable, "install", "--package-lock-only", "--ignore-scripts",
                        "--no-audit", "--no-fund"], cwd=target,
                       extra_env={"NPM_CONFIG_OS": npm_os, "NPM_CONFIG_CPU": npm_cpu})
                text = (target / "package-lock.json").read_text(encoding="utf-8")
                validate(text, fields, version)
                if expected is None:
                    expected = json.loads(text)
                elif json.loads(text) != expected:
                    raise ConfigError(
                        f"npm resolution differs for {os_name}/{arch}; a universal lock "
                        "cannot represent platform-specific dependency closure")
            expected["x-tool-lock-generator"] = provenance
            text = json.dumps(expected, indent=2) + "\n"
        else:
            help_text = runner([executable, "pip", "compile", "--help"], cwd=project)
            help_text += "\n" + runner([executable, "--help"], cwd=project)
            flags = ["--generate-hashes", "--only-binary", "--no-strip-markers", "--no-strip-extras",
                     "--no-annotate", "--no-header", "--python", "--no-python-downloads", "--no-config"]
            if any(flag not in help_text for flag in flags):
                raise ConfigError("Installed uv lacks required compile flags; refusing an unverifiable Python grammar")
            expected = None
            for os_name, arch, _npm_os, _npm_cpu, uv_platform in PLATFORMS:
                target = project / f"py-{os_name}-{arch}"
                target.mkdir()
                (target / "requirements.in").write_text(fields["pkg"] + "==" + version + "\n")
                runner([executable, "pip", "compile", "requirements.in",
                        "--output-file", "requirements.txt",
                        "--generate-hashes", "--only-binary", ":all:", "--no-strip-markers",
                        "--no-strip-extras", "--no-annotate", "--no-header", "--python",
                        sys.executable, "--no-python-downloads", "--no-config",
                        "--python-platform", uv_platform], cwd=target)
                flattened = flatten_python((target / "requirements.txt").read_text(encoding="utf-8"))
                if expected is None:
                    expected = flattened
                elif flattened != expected:
                    raise ConfigError(
                        f"Python resolution differs for {os_name}/{arch}; a universal lock "
                        "cannot represent platform-specific dependency closure")
            text = "# generator: " + json.dumps(provenance, ensure_ascii=True) + "\n" + expected
        validate(text, fields, version)
        return text


def publish(output, text, force=False):
    if output.is_symlink() or output.resolve() != output:
        raise ConfigError("Refusing symlink output")
    if os.path.lexists(output) and not force:
        raise ConfigError("Output already exists; use --force for atomic replacement")
    # Parent must already exist: maintenance does not create directory trees.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink()
            raise
    try:
        if force:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)  # Exclusive publication, including concurrent creation.
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None, *, runner=run_command):
    parser = argparse.ArgumentParser(description=__doc__, epilog="""Default --check is offline: it validates only the selected existing lock and root pin, not dependency closure or artifact authenticity. --generate may contact registries but never installs packages: npm lock-only disables scripts; uv uses binary-only metadata with the current Python and disables Python downloads. It resolves once per declared platform (npm os/cpu override, uv --python-platform) and refuses to publish unless every target produces the same lock, then records the verified platform list. Run from an activated login shell. Resolver environment is isolated (no ambient credentials, proxy, NODE_OPTIONS or package-manager config); only PATH is inherited. Each command has a 300-second timeout. Markers, extras, URLs and unsupported grammar cause refusal, never semantic stripping. Existing output needs --force; validated output is published atomically. No manifest/tools/vendor edits. Generator path/version is recorded in lock metadata/comments. Parent output directory must exist. Example: python3 scripts/update-tool-locks.py --module dev --tool example --check. Generation: same selection plus --generate [--force].""")
    parser.add_argument("--tools", type=Path, default=Path(__file__).resolve().parents[1] / "tools.toml")
    parser.add_argument("--module", required=True)
    parser.add_argument("--tool", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--generate", action="store_true")
    parser.add_argument("--force", action="store_true", help="authorize atomic replacement (requires --generate)")
    args = parser.parse_args(argv)
    try:
        if args.force and not args.generate:
            raise ConfigError("--force requires --generate")
        fields, version, output = select_universal(args.tools, args.module, args.tool)
        if args.generate:
            if os.path.lexists(output) and not args.force:
                raise ConfigError("Output already exists; use --force")
            text = generate(fields, version, runner=runner)
            publish(output, text, args.force)
        else:
            if not output.is_file() or output.stat().st_size > LIMIT:
                raise ConfigError("Lock must be an existing regular file no larger than 8 MiB")
            text = output.read_text(encoding="utf-8")
        print(f"OK {output}: {validate(text, fields, version)}")
        return 0
    except (ToolInstallerError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
