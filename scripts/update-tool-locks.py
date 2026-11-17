#!/usr/bin/env python3
"""Offline lock validation and explicitly authorized host-only lock maintenance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool-installer"))
from tool_installer.environment import detect_environment
from tool_installer.errors import ToolInstallerError, ConfigError
from tool_installer.hash_lock import validate_npm_lock, validate_python_lock, _target
from tool_installer.models import Environment
from tool_installer.parser import parse_tools_file, parse_manifest_file
from tool_installer.strategy import _validate_strategy

LIMIT = 8 * 1024 * 1024


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
        raise ConfigError("No strategy for selected OS")
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
    fields.setdefault("bin", tool.reference.name)
    _validate_strategy(tool.reference.name, tool.reference.version, fields, config.manifest_path.parent)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", fields["bin"]):
        raise ConfigError("Invalid locked-manager bin")
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


def run_command(command, *, cwd):
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
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                capture_output=True, check=False, timeout=300)
    except subprocess.TimeoutExpired:
        raise ConfigError("Generator timed out after 300 seconds; output unchanged") from None
    if result.returncode:
        # Resolver stderr can contain registry credentials; do not echo it.
        raise ConfigError(f"{Path(command[0]).name} failed (exit {result.returncode}); output unchanged")
    return result.stdout.strip()


def generate(fields, version, environment, *, runner=run_command):
    if environment != detect_environment():
        raise ConfigError("Generation supports only the host OS/architecture; cross-platform locks are refused")
    executable = shutil.which("npm" if fields["manager"] == "npm-locked" else "uv")
    if not executable:
        raise ConfigError("Required generator is not installed; no tools will be installed automatically")
    with tempfile.TemporaryDirectory(prefix="tool-lock-") as directory:
        project = Path(directory)
        generator_version = runner([executable, "--version"], cwd=project)
        provenance = {"generator": str(Path(executable).resolve()), "version": generator_version,
                      "os": environment.os, "arch": environment.arch,
                      "python": sys.version.split()[0] if fields["manager"] == "python-locked" else None}
        if fields["manager"] == "npm-locked":
            (project / "package.json").write_text(json.dumps({"name": "tool-lock-maintenance", "version": "1.0.0", "private": True,
                "dependencies": {fields["pkg"]: version}}))
            runner([executable, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=project)
            text = (project / "package-lock.json").read_text(encoding="utf-8")
            validate(text, fields, version)  # Validate before parsing/re-serializing duplicate keys.
            data = json.loads(text)
            data["x-tool-lock-generator"] = provenance
            text = json.dumps(data, indent=2) + "\n"
        else:
            help_text = runner([executable, "pip", "compile", "--help"], cwd=project)
            help_text += "\n" + runner([executable, "--help"], cwd=project)
            flags = ["--generate-hashes", "--only-binary", "--no-strip-markers", "--no-strip-extras",
                     "--no-annotate", "--no-header", "--python", "--no-python-downloads", "--no-config"]
            if any(flag not in help_text for flag in flags):
                raise ConfigError("Installed uv lacks required compile flags; refusing an unverifiable Python grammar")
            (project / "requirements.in").write_text(fields["pkg"] + "==" + version + "\n")
            runner([executable, "pip", "compile", "requirements.in", "--output-file", "requirements.txt",
                    "--generate-hashes", "--only-binary", ":all:", "--no-strip-markers", "--no-strip-extras",
                    "--no-annotate", "--no-header", "--python", sys.executable, "--no-python-downloads", "--no-config"], cwd=project)
            text = "# generator: " + json.dumps(provenance, ensure_ascii=True) + "\n" + flatten_python((project / "requirements.txt").read_text(encoding="utf-8"))
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
    parser = argparse.ArgumentParser(description=__doc__, epilog="""Default --check is offline: it validates only the selected existing lock and root pin, not dependency closure or artifact authenticity. --generate may contact registries but never installs packages: npm lock-only disables scripts; uv uses binary-only metadata with the current Python and disables Python downloads. Run from an activated login shell. Resolver environment is isolated (no ambient credentials, proxy, NODE_OPTIONS or package-manager config); only PATH is inherited. Each command has a 300-second timeout. Only host OS/arch generation is allowed; Python locks are specific to the current interpreter/libc, not portable across every machine of the same arch. Markers, extras, URLs and unsupported grammar cause refusal, never semantic stripping. Existing output needs --force; validated output is published atomically. No manifest/tools/vendor edits. Generator path/version is recorded in lock metadata/comments. Parent output directory must exist. Example: python3 scripts/update-tool-locks.py --module python-tools --tool example --check. Generation: same selection plus --generate [--force].""")
    parser.add_argument("--tools", type=Path, default=Path(__file__).resolve().parents[1] / "tools.toml")
    parser.add_argument("--module", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--os", choices=["linux", "macos"])
    parser.add_argument("--arch", choices=["x86_64", "aarch64"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--generate", action="store_true")
    parser.add_argument("--force", action="store_true", help="authorize atomic replacement (requires --generate)")
    args = parser.parse_args(argv)
    try:
        if args.force and not args.generate:
            raise ConfigError("--force requires --generate")
        host = detect_environment()
        environment = Environment(args.os or host.os, args.arch or host.arch)
        fields, version, output = select(args.tools, args.module, args.tool, environment)
        if args.generate:
            if os.path.lexists(output) and not args.force:
                raise ConfigError("Output already exists; use --force")
            text = generate(fields, version, environment, runner=runner)
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
