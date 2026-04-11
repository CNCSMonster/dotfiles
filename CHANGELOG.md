# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Zellij**: Add terminal multiplexer configuration and installation
  - `zellij/config.kdl` based on TD-Sky/dotfiles scheme
  - 4 custom layouts: `horizontal`, `vertical`, `three-vertical`, `four-grid`
  - `Alt + [` / `Alt + ]` cycle through layouts
  - `Ctrl + p` → Pane mode → `h/j/k/l` for pane navigation
  - Add `install-zellij` function to `install-functions.sh`
  - Add zellij to `setup.sh` installation flow
  - Add zellij to `xdotter.toml` for config deployment

### Fixed
- **CI Build**: Fixed Dockerfile build check failures
  - Fixed xdotter deployment command (v0.3.4 removed `--config` parameter)
  - Fixed LSP installation functions missing `return 0` on success
  - Fixed bash arithmetic logic in LSP install counters (post-increment `((installed++))` returns 0 when counter is 0, triggering false failure detection)

## 2026-04-05

### Fixed
- **xdotter**: Pin version to v0.3.4 to avoid breaking changes from automatic updates
  - xdotter v0.3.4 removed `-c`/`--config` parameter
  - Changed deployment command from `xd --config <path>` to `cd <dir> && xd deploy`
  - Added `XDOTTER_VERSION` build argument in Dockerfile for version control

- **LSP Installation Functions**: Add explicit `return 0` after successful installation
  - `install-typescript-lsp`
  - `install-pyright`
  - `install-yaml-lsp`
  - `install-taplo`
  - `install-lua-lsp`
  - `install-bash-lsp`
  - `install-zls`

- **Bash Counter Logic**: Use pre-increment to avoid false failure detection
  - Changed `((installed++))` to `((++installed))` in LSP install counters
  - Post-increment returns old value (0) as exit code, triggering `||` branch incorrectly
  - Pre-increment returns new value (1) as exit code, correctly indicating success
