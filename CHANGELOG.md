# Changelog

All notable changes to this project will be documented in this file.

> **历史说明：** 早于 tool-installer 迁移的条目会提到
> `shells/common/install-functions.sh`、`install-common-tools`、`download_xdotter`、
> `ensure_python3`、`.github/workflows/macos-setup.yml` 等**已不存在**的文件或函数。
> 这些是当时的事实记录，不再逐一改写（迁移后 install-functions.sh 被删除，
> macos-setup.yml 的职责由 `runner-verify.yml` 的 macOS 矩阵承担）。
> 当前架构见 `docs/tool-installer-migration-plan.md`；确认某个文件是否存在请用
> `git ls-files`，不要依据本文件的历史条目。

## [Unreleased]

### Fixed
- **github-release 镜像回退以 SHA256 为准**：`_verify_checksum` 原先在下载循环之外执行，
  镜像返回 HTTP 200 但内容不符时第一个响应的源即被选中、随后校验失败直接抛错，
  官方直连永不被尝试。现在校验参与**源选择**：候选源必须同时传输成功且校验通过，
  校验失败会打印告警并继续下一个源
  - 传输层重试预算（每源 `retry + 1` 次）与未声明 `sha256` 条目的行为保持不变
  - 回归测试：`tool-installer/tests/test_github_release_download.py`
- **allow_fail 失败在非严格模式也可见**：`execute_plan` 原先只在
  `TOOL_INSTALLER_STRICT=1` 时汇总，而 `setup.sh`（真实用户入口）从不设置该变量，
  于是被容忍的失败完全静默。现在两种模式都打印失败清单，仅退出码不同
  - 回归测试：`tool-installer/tests/test_executor_tolerated_failures.py`
- **Layer 2 不再输出假成功**：`scripts/layer2-post.sh` 的 Helix runtime 步骤在三个下载
  路径全部失败、什么都没复制时仍无条件打印 ✅。现在每步返回明确状态，`main` 汇总失败项，
  有失败则脚本返回非零，`setup.sh` 不再在结尾宣称"全部安装完成"
  - `chsh` 失败等"需用户手动收尾"的情况仍为非致命（打印 ⚠️ 而非 ✅）
- **补齐 manifest 的 8 处 `sha256 = "TODO"`，并修掉途中发现的两个连带缺陷**：
  `TODO` 不只是"缺校验"——`strategy.py::_validate_github_release` 会拒绝非 64 位十六进制摘要，
  而 `build_install_plan` 在非 `--skip-errors` 时会中止**整个模块**。后果是
  `linux/aarch64` 在 `gh` 上、`macos/x86_64` 在 `cargo-binstall` 上规划期直接失败，
  **Intel Mac 完全装不上**（CI 只跑 `macos-latest` = arm64，所以从未暴露）
  - 8 个摘要均从钉版 release 下载后本地计算，并在上游提供校验文件时做了交叉验证
    （gh `checksums.txt`、xdotter `SHA256SUMS`、starship `.sha256`、yq `checksums`）
  - `gh` 的两条 arch 条目把 `asset`/`bin` 写成 `gh_{version}_…`，而 pin 带 `v`、asset 名不带，
    渲染出上游不存在的 `gh_v2.97.0_…`；改为与同级条目一致的硬编码写法
  - `xdotter.linux.aarch64` 复用了 x86_64 的摘要，在 aarch64 上校验永远不可能通过
  - `zellij` 官方 `.sha256sum` 给的是**解包后二进制**的哈希，与本项目"校验归档本身"的约定
    不同；此处填的是归档摘要，并用"内部二进制哈希 == 官方值"反证其真实性
  - 现在四个平台（linux/macos × x86_64/aarch64）的安装计划都能正常生成
- **再修 5 处平台覆盖缺陷，并加上能持续拦住它们的守卫**：为验证上一条而写的四平台
  离线扫描又找出同类问题（都已修复并逐项核对上游产物）：
  - `ripgrep`：**整个缺失** `[ripgrep.linux.aarch64]` 与 `[ripgrep.macos.x86_64]` 段落，
    于是在 aarch64 上会下载 x86_64 二进制、在 Intel Mac 上会下载 arm64 二进制，
    且因没有 sha256 而静默跳过校验（已补齐 asset/bin/sha256，官方 `.sha256` 交叉验证通过）
  - `helix.macos.x86_64`：asset 正确但缺 sha256，校验被静默跳过（已补）
  - `zls.macos.x86_64`：asset 被误写成 aarch64 的包名，sha256 也对不上当前钉版的任何产物
    （既非归档哈希、也非解包后二进制哈希，是残留值）
  - `xdotter.macos.x86_64`：`bin` 继承成 aarch64 的名字，与单文件 asset 不匹配，
    会被 `_locate_executable` 判为 "single-file asset mismatch"
  - 新增 `scripts/check-manifest-platforms.sh`：离线秒级，断言四平台计划可生成、
    github-release 条目必带 64 位 sha256、asset/bin 可渲染且与目标架构一致；
    接入 `.github/workflows/tool-installer-verify.yml` 的 `Manifest platform matrix` 作业，
    并写入 `AGENTS.md` / `CONTRIBUTING.md` 的验证指引

### Vendor 政策执行
- **移除 `vendor/xdotter`，并让 vendor 政策成为可执行规则**：该二进制不满足准入条件——
  §3.1 的"自举依赖"要求"**无法**通过上层工具自身获取"，而 tool-installer 能装 xdotter；
  其真实的入库理由是"慢网络兜底"，正是 §3.2 明令禁止的 vendor 绕过
  - 删除 `vendor/xdotter`（744KB）及 `setup.sh::ensure_xdotter()` 的第三级回退；
    Linux x86_64 仍保留"tool-installer → 直连下载"两级，且 github-release 回退已改为以 SHA256 为准
  - `docs/tool-installer-migration-plan.md` §3 成为 vendor 政策与清单的**唯一来源**；
    `scripts/vendor/README.md` 降级为 `rustup-init.sh` 的更新 SOP（它此前把 xdotter
    写进"已移除"表，而文件当时仍在库并被 `setup.sh` 使用）
  - 清单补齐**三个** vendor 域，含此前两份文档都未登记的
    `tool-installer/tool_installer/vendor/tomli/`；新增四态状态语义
    （保留 / 已移除 / 待处置 / 例外）
  - 删除孤儿脚本 `scripts/vendor/cargo-binstall-install.sh`：其唯一调用方
    `shells/common/install-functions.sh` 已在迁移中删除（`ff54dd5`），此后全仓库零引用

### Docs
- **修正文档与实现的偏离**（`AGENTS.md` 第一优先级：文档与实现一致）：
  - `docs/multi-env-design.md`：`origin/macos` 实测落后 main 177 个提交、领先 2 个，
    且缺少 tool-installer 迁移，并非文档所称"main + 一个 workflow"；补充实测对照表，
    并记录 `.github/workflows/macos-setup.yml` 已不存在（职责由 `runner-verify.yml` 承担）
  - `docs/tool-installer-migration-plan.md`：Layer 2 职责按 `scripts/layer2-post.sh`
    实际内容重写（原文误把字体安装、LSP 服务器列为 Layer 2，二者实为 Layer 1 模块）；
    vendor 清单中 `vendor/rustup-init.sh` 更正为实际路径 `scripts/vendor/rustup-init.sh`
  - `docs/config-consistency-check-sop.md`：标注 `scripts/check-completions.sh`
    为尚未实现的建议形态，避免读者按图索骥找不到该文件

### Added
- **macOS Support**: Add cross-platform installation support

### Changed
- **Rust as First Citizen**: Move Rust toolchain installation to the top of `do_install()`
  - Rust is now installed immediately after `install-common-tools`, before all other dev tools
  - `do_deploy()`: Add minimum Rust installation fallback if cargo is not available
  - `download_xdotter()`: Add cargo availability check before fallback to `cargo install`
  - Rationale: xdotter (core tool) is built with Rust; many tools depend on cargo/binstall

### Fixed
- **macOS arm64 Support**: Add Homebrew installation for multiple tools on macOS
  - `install-helix`: Use Homebrew on macOS (was: GitHub Release download)
  - `install-marksman`: Use Homebrew on macOS (fixes CI: "不支持的架构：arm64")
  - `install-yq`: Use Homebrew on macOS
  - `install-zls`: Use Homebrew on macOS
  - `install-lua-lsp`: Use Homebrew on macOS
  - `install-zellij`: Use Homebrew on macOS
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
