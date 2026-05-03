# dotfiles

> One-command development environment setup — clone + run, new machine ready in ~30-50 minutes on a good connection.

[中文](readme.md)

---

## What problem does it solve

| Pain point | How this project addresses it |
|-----------|------------------------------|
| Hours spent manually installing tools and tweaking configs on a new machine | `./setup.sh` — one command installs everything and deploys all configs |
| Inconsistent environments across machines, "works on my machine" syndrome | Config files under version control, xdotter symlinks ensure consistency |
| Manual setup is error-prone and hard to reproduce | Docker image verification + CI auto-build, every change is reproducible |

---

## What you get

**Shell Environment**
zsh + zcomet plugin manager + starship prompt + zoxide (smart cd) + fzf (fuzzy finder) + eza (modern ls) + bat (modern cat) + fd (modern find) + ripgrep (modern grep)

**Editors**
Neovim (nightly) + Helix — with LSP servers for 9 languages: TypeScript, Python, Go, Zig, Lua, Bash, YAML, TOML, Markdown

**Language Toolchains**
Rust (stable) + Go + Node.js + Zig — managed by [mise](https://mise.jdx.dev/)

**Terminal Experience**
WezTerm config + Nerd Fonts + Zellij terminal multiplexer + Yazi file manager + macchina system info + navi cheatsheets

**Rust Tooling** (20+)
sccache, cargo-binstall, cargo-fuzz, starship, gitui, tokei, mdbook, uv, nu, and more

---

## Quick Start

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
./setup.sh
```

After installation, restart your terminal or run `source ~/.zshrc`.

Options: deploy configs only (no tool install) or install tools only (configs already deployed)

```bash
./setup.sh --deploy   # Deploy config files only
./setup.sh --install  # Install dev tools only
```

### Docker Verification

```bash
./scripts/docker-build-test.sh
```

Verifies setup.sh runs correctly in a clean Ubuntu container.

---

## How It Works

Two phases:

1. **Config Deployment** — [xdotter](https://github.com/CNCSMonster/xdotter) reads `xdotter.toml` and deploys config files to standard locations like `~/.config/` via symlinks
2. **Tool Installation** — `setup.sh` calls `install-functions.sh` to install the Rust toolchain, editors, LSP servers, language runtimes, etc. in order

Config and installation are decoupled: changing configs doesn't require reinstalling tools, and adding tools doesn't require changing configs.

---

## Supported Environments

| Environment | Status |
|-------------|--------|
| Ubuntu 22.04 / 24.04 | Primary support |
| WSL2 (Ubuntu) | Fully compatible |
| macOS (arm64/x86_64) | Supported (Homebrew) |

---

## Documentation

| Topic | Document |
|-------|----------|
| Security Design | [Security Practices](./docs/security-practices.md) |
| Rust Tool Updates | [Rust Tools Update SOP](./docs/rust-tools-update-sop.md) |
| Shell Config | [Shell Config Architecture](./docs/shell-config-architecture.md) |
| Cargo Audit | [Cargo Audit Practices](./docs/safe-cargo-audit.md) |
| xdotter Usage | [xdotter Docs](./docs/xdotter-usage.md) |
| Contributing | [Contributing Guide](./CONTRIBUTING.md) |

---

## Design Principles

- **Single codebase, cross-platform** — All platform differences handled via `uname -s` at the install layer, no multi-branch maintenance
- **Security first** — SHA256 verification for binary downloads, Docker secrets excluded from image layers, cargo-audit for dependency auditing
- **Reproducible** — Docker builds + CI auto-verification, every change tested in a clean environment

---

## Inspired by

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
