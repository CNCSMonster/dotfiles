"""Command-line interface for tool-installer."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .environment import detect_environment
from .errors import ToolInstallerError
from .executor import execute_plan, print_dry_run
from .interaction import ASSUME_YES_ENV
from .managers import default_registry
from .parser import parse_manifest_file, parse_tools_file
from .resolver import collect_ordered_tools, resolve_modules
from .strategy import build_install_plan


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(prog="tool-installer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="install a module from ./tools.toml")
    install.add_argument("module", help="module name to install")
    install.add_argument("--dry-run", action="store_true", help="print the installation plan without executing it")
    install.add_argument(
        "--skip-errors",
        action="store_true",
        help="tolerate an unresolvable tool entry instead of aborting the module",
    )
    install.add_argument(
        "--yes",
        dest="assume_yes",
        action="store_true",
        help="assume yes for unexpected-state prompts (a command already exists but is not "
        "apt-managed, a locally modified config file). Expected operations are never "
        "prompted, with or without this flag. Never bypasses sudo authentication.",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the tool-installer CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            return _run_install(args.module, args.dry_run, args.skip_errors, args.assume_yes)
    except ToolInstallerError as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_install(
    module: str, dry_run: bool, skip_errors: bool = False, assume_yes: bool = False
) -> int:
    if assume_yes:
        # 用环境变量而非层层传参：与 TOOL_INSTALLER_STRICT 同一约定，manager 内部
        # （AptManager 等）在任何深度都能读到，也方便 setup.sh / 脚本统一设置。
        os.environ[ASSUME_YES_ENV] = "1"
    tools_path = Path.cwd() / "tools.toml"
    config = parse_tools_file(tools_path, module)
    manifest, gh_config = parse_manifest_file(config.manifest_path)
    modules = resolve_modules(config, module)
    ordered_tools = collect_ordered_tools(modules)
    environment = detect_environment()
    plan = build_install_plan(
        ordered_tools, manifest, environment, config.manifest_path.parent, skip_errors=skip_errors
    )
    if dry_run:
        print_dry_run(plan)
    else:
        execute_plan(plan, default_registry(gh_config))
    return 0
