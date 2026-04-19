# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **macOS Support**: Add cross-platform installation support
  - `setup.sh`: `download_xdotter()` detects macOS and uses `apple-darwin` binary
  - `setup.sh`: `ensure_python3()` uses Homebrew on macOS, apt on Linux
  - `install-functions.sh`: `install-common-tools()` uses Homebrew for macOS, apt for Linux
  - `install-functions.sh`: `ensure_cargo_binstall()` supports macOS architectures (x86_64/aarch64)
  - All changes use `uname -s` branching — single codebase, cross-platform compatible
  - See **Branch Architecture** section below for details

- **GitHub Actions CI**: Add macOS verification workflow
  - `.github/workflows/macos-setup.yml` — runs on `macos-latest` runner
  - Triggered by `[macos-ci]` commit message tag or manual dispatch
  - Verifies full setup.sh installation on macOS

- **CI Actions Update**: Upgrade all GitHub Actions to Node.js 24 compatible versions
  - `actions/checkout` v4 → v6
  - `docker/setup-buildx-action` v3 → v4
  - `docker/build-push-action` v6 → v7

- **Documentation**: Add config consistency check SOP
  - `docs/config-consistency-check-sop.md` — audit installed tools vs active shell completions
  - `docs/zsh-plugins-update-sop.md` — extended with completion coverage verification

### Changed
- **Branch Architecture**: Simplified from multi-branch to single-codebase with platform detection
  - Merged and removed: `exp-main`, `exp-wsl-ubuntu-24`, `wsl2-ubuntu-24`, `feat/issue-3-fontconfig`, `fix/docker-ci-env-detection`, `ci-runner-direct`
  - `macos` branch now equals `main` + macOS CI workflow only (no code divergence)
  - Rationale: No WSL-specific code exists in the codebase; all platform differences are limited to installation layer, handled by `uname -s` branching in main
  - Going forward: All new features land in `main`; `macos` branch is for CI verification only; create environment branches only when truly platform-specific config is needed

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

---

## Branch Architecture

### Current Structure (2026-04-19)

```
main  ──────────────────────────→  通用配置（单代码库，跨平台）
  ├─ macos       ── +macos-setup.yml (CI 验证)
  └─ wsl2-ubuntu-24 ── 与 main 完全一致 (CI 验证)
```

### 设计理念

- **单代码库**: 所有平台差异控制在"安装层"（包管理器、二进制下载），通过 `uname -s` 分支处理
- **环境分支**: 仅用于 CI 验证，不包含任何代码差异（wsl2-ubuntu-24）或仅包含 CI workflow（macos）
- **不复用旧分支**: 已删除 `exp-main`、`exp-wsl-ubuntu-24`、`ci-runner-direct` 等，避免历史包袱

### 为什么不分多套代码

| 问题 | 多分支方案 | 单代码库方案 |
|------|-----------|-------------|
| 通用重构（如 cargo_install_from_source） | 每个分支各做一遍 | 一次完成 |
| 分支同步 | 20-36 commit 落后，合并冲突 | 始终一致 |
| 维护成本 | 分支数 × 改动量 | 线性增长 |
| 新人上手 | 不知道该看哪个分支 | 看 main 就行 |

### 何时应该拆分分支

只有当某个平台的**配置层**（非安装层）需要完全不同的内容时，才应该拆分独立分支。例如：
- macOS 需要完全不同的 Neovim 插件集合
- WSL 需要完全不同的 systemd 集成方案或 `.wslconfig`
- 某个平台的 shell 配置与主流差异超过 30%

当前项目**不满足**上述条件，所以单代码库是正确选择。
