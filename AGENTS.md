# AGENTS.md

This file is the common entry point for AI coding agents working on this repository.
Keep it short and stable. Use project documentation as the source of truth.

## Project goal

This repository manages dotfiles and bootstraps a complete development environment.

## Core model

- `xdotter` deploys configuration through symlinks.
- `setup.sh` installs tools and runs the bootstrap flow.
- Configuration deployment and tool installation are intentionally separate.
- `main` is the code-bearing branch; platform differences should be handled in install logic, not by creating divergent config branches.

## Read first

Before changing files, read the relevant current docs:

1. `readme.md` — user-facing quick start.
2. `CONTRIBUTING.md` — verification and contribution flow.
3. `docs/shell-config-architecture.md` — shell configuration layering.
4. `docs/xdotter-usage.md` — dotfile deployment model.
5. `docs/config-consistency-check-sop.md` — config/completion consistency checks.

## Priorities

1. Keep documentation and implementation consistent.
2. Keep the project clean, predictable, and easy to audit.
3. Prefer small consistency fixes over convenience features.
4. Preserve the separation between deployment (`xdotter`) and installation (`setup.sh`).

## Do not

- Do not add shell completion commands unless verified by official docs or direct local command testing.
- Do not add placeholder config for tools that do not expose a usable shell completion command.
- Do not modify download logic unless explicitly requested; download optimization is handled separately.
- Do not bypass project scripts with ad-hoc commands when a script already exists.
- Do not create platform-specific config branches for normal Linux/macOS differences.
- Do not delete or overwrite user config without explicit confirmation.

## Verification

Use the lightest verification that proves the change:

- Documentation-only changes: run `git diff --check` and inspect the diff.
- Shell changes: run `bash -n` on changed shell files where applicable.
- xdotter changes: run `xd validate` and `xd deploy --dry-run` when available.
- Full local Docker verification: `./scripts/docker-build-test.sh`, then run the verification command printed by the script.
- CI runner verification runs `./setup.sh` on Ubuntu and macOS.

## Commit discipline

- Keep commits focused on one logical change.
- Use the existing commit style, for example `docs: fix setup verification docs` or `feat(shell): add opencode completion`.
- Do not push unless the user explicitly asks.
