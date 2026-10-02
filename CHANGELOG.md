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

### Added

- **apt 策略下沉到 tool-installer（Step 1）**：新增 `tool_installer/managers/apt_policy.py`，
  与 `scripts/lib/apt.sh` 同一套「有界 / 可见 / 可归因」策略，服务稳定期（自举期必须留 shell：
  python3 引导与 Layer 1 门禁跑在工具可用之前，无法依赖工具自己）
  - `AptManager` 覆写 `install()`：装包前源预检 → 带 30s / 1 次 / 60s 有界参数执行 → 回显 apt
    输出 → 失败归因到可复制的修复命令。该 manager 此前零使用、零测试，`subprocess.run` 无
    timeout，与 shell 改造前一样能在坏源上挂死
  - `SubprocessRunner` 为**所有** manager 加 3600s 兜底 timeout，并把 `TimeoutExpired` 转成
    `InstallationError`（裸超时会绕过 executor 的 `allow_fail` 汇总直接 traceback）
  - 回归测试 `tool-installer/tests/test_apt_policy.py`（21 例，离线），已重建 `vendor/tool-installer`
  - Step 2（未做）：系统包迁到声明式 `manager = "apt"`；先裁决 `DEBIAN_FRONTEND` 与清单语义
- **Step 2 批次 1：非预期问题的授权与三档判定**（用户拍板 2026-10-03：预期不问、非预期要问、
  `--yes` 全同意、没人可问时既不擅自决定也不中断）
  - `tool-installer install --yes` → `TOOL_INSTALLER_ASSUME_YES=1`（与 `TOOL_INSTALLER_STRICT`
    同一传播约定）；新增 `tool_installer/interaction.py` 的 `Decision` 三态，交互默认答案 **N**
  - `AptManager` 补 `command -v` 视角的检测：命令已存在但 dpkg 没记录时会**静默装出第二份实现**
    （PATH 上两个 git，用哪个取决于顺序），现在这种状态必须授权；manifest 为 `apt` 新增可选
    `bin` 字段（包名与命令名不同时声明）
  - 新增 `AuthorizationRequired` + executor 专门分支：**缺授权只跳过该工具并结束时汇总，
    绝不中断整轮安装**（与 allow_fail 同哲学，两种模式都打印，仅退出码不同）
  - 探测 fail-open、执行 fail-closed：`dpkg-query` 探测失败当作"未装"继续，真正的失败交给
    `apt install` 去归因
  - 已核实边界（L1 实测 + L2 手册）：`--yes` **不绕过 sudo 认证**——sudo 上游（本机 sudo-rs
    0.2.13 / 传统 1.9.17p2）不存在"用调用方参数完成授权"的机制；Ubuntu 26.04 的 sudo 已是
    sudo-rs，凭证缓存默认 15 分钟
  - 回归测试 `tool-installer/tests/test_authorization.py`（20 例，离线），已重建 `vendor/tool-installer`
- **Step 2 批次 2：系统包清单声明式化**（2026-10-03；调研修正了两处原计划预设）
  - `manifest.toml [system-packages.linux]` → `manager = "apt"` + 26 包清单（与迁移前
    `for pkg in` 原文逐字 diff 核对一致）；macOS 保留 script（Homebrew 引导 + 4 包，
    行为不变；22 个 Linux 专属包在 brew 侧无对应名，按包拆条目会让 macOS 段无从写起）
  - `tools.toml`：`system-packages@1` → `@latest`（`@1` 会被 check 当成 pin 与 dpkg 版本
    比对，永远不等 → 每轮判未满足重装）
  - `AptManager` 多包支持：check 任一缺失即整组重装（与旧 `missing` 批量同语义）、
    `install_command` 一个事务展开、冲突检测逐包收集一次问询、pin 限单包显式报错
  - **latest 语义裁决**：apt 的 latest = 装了即满足，**不比 apt candidate**——否则
    ./setup.sh 每轮把基线包升级到 candidate，而旧清单只判定存在性；对齐版本用
    `name@版本`，强制重装用 `force = true`。`AptManager.check` 此前零测试，补 9 例锁契约
  - **shell 侧经调研确认无需三档**：apt.sh 调用方全是预期的依赖安装；唯一带"已有则
    跳过"判定的 Linux 分支随迁移消失（授权三档是 check/install 分离组件的特性）
  - **修复旧 SOP 提取缺陷**：`grep '\b[a-z][a-z0-9-]{2,}\b'` 漏 `g++`、`-w pkg` 误删
    `pkg-config`——声明清单与被核查清单本就不同源；改用 tool-installer 的 parser 读
    manifest，26 包全量提取（`config-consistency-check-sop.md` 1.1 已同步）
  - 验证：`check-manifest-platforms.sh` 4/4 平台、121 测试、dry-run
    `version=latest manager=apt`、清单逐字 diff、`bash -n`、vendor 重建 + 同步守卫
- **修复：apt 索引刷新与源预检的执行时机（tool-installer）**
  - 新增 `Manager.preflight(items)` 钩子（每轮一次，executor 在逐项执行前按 manager
    分组调用）；`AptManager` 在其中 `apt-get update` **一轮一次**，对齐 shell 侧 apt_run
    语义——原先从不 update，索引陈旧时 `Unable to locate package` 且归因不到这一类
  - 源健康预检从 install **逐项**上移到 preflight **一轮一次**（原先每项最多 源数×5 秒
    探测，19 个包就是 19 轮）；输出不 capture，保持实时可见（与 shell tee 同语义）
  - update 失败只警告继续：索引陈旧 ≠ 装不上（apt 仍用缓存索引），失败交给 install 归因
  - 防漂移测试 `test_bounded_numbers_match_scripts_lib_apt_sh`：直接读 `scripts/lib/apt.sh`
    断言 `Timeout=30 / Retries=1 / Lock=60` 与 `apt_policy.APT_*` 相等，改一侧不改另一侧会点名
  - 回归测试 112 例全绿，已重建 `vendor/tool-installer`

### Fixed
- **apt 安装不再静默挂死，失败可归因**：`setup.sh` 的 Layer 1 运行时依赖预检与 Layer 0 系统包
  安装原先用 `apt-get update -qq` 静默执行且无超时上限；宿主指向腾讯云内网源
  （`mirrors.tencentyun.com` → `169.254.0.3`）时在 TCP 黑洞上重试 4 分钟以上才失败，只留下
  `❌ 运行时依赖安装失败`，没有可执行的修复指引。新增 `scripts/lib/apt.sh`（单一事实来源）并
  在两处接入：有界超时/重试/锁等待、装包前逐源 5s 可达性预检、失败归因为可直接复制的修复命令
  - `DEBIAN_FRONTEND=noninteractive` 原先写在 `sudo` 之前，被 `env_reset` 丢弃；改为 `sudo env VAR=... apt-get`
  - `./setup.sh --install` 单跑无 sudo 缓存时原先直接判死，现在交互终端现场 `sudo -v` 提升
  - 只诊断不改源：`/etc/apt` 下的用户配置永不被脚本改写
  - 政策与调用点清单见 `docs/tool-installer-migration-plan.md` §4.3
- **其余 apt 调用点也接入有界/归因策略**：`setup.sh` 的 python3 引导、
  `scripts/install-wezterm.sh`、`scripts/install-fonts.sh`、`scripts/setup-rootless-docker.sh`、
  `scripts/llvmup`（含 PATH 上的 `shells/scripts/llvmup` 副本）原先仍是裸 `apt-get`（部分带
  `-qq` 或 `2>/dev/null`），同样能在坏源上无界挂起。全部改走 `scripts/lib/apt.sh`
  - `llvmup` 用 `readlink -f` 定位库以兼容两种调用形态，库缺失时显式警告后再降级
  - 只在会执行 `update` 的路径跑源可达性预检；纯 install 路径靠失败归因
  - 各脚本原有的失败语义（致命 / 跳过 / 警告）保持不变
- **llvmup 合并为单一文件**：`shells/scripts/llvmup`（PATH 入口）原是 `scripts/llvmup` 的
  复制件，幂等 skip 修复（`513573d`）只落在后者，两份已漂移。改为指向 `scripts/llvmup` 的
  相对符号链接，这是仓库里唯一一对同名重复脚本，现在内容只有一份
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
  - **决策：Layer 2 的真实失败保持致命**，不因"属于网络型可选产物"降级为警告。
    要 CI 变绿就修因，不要静音；`AGENTS.md` 的 Do-not 已固化这条
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
- **修复 yazi 插件在镜像列表为空时从未被安装**：`install_yazi_plugins` 把
  `ya pkg install` 只写在镜像 `for` 循环里，而 CI 的 `ci-disable-mirrors.sh` 会清空镜像
  列表，于是循环体一次都不执行——命令从未被调用，重试 3 次后必然失败；任何未配置镜像的
  用户同样受影响。现在镜像之后必经直连兜底（桩测试：镜像为空时旧代码调用 `ya` **0 次**，
  新代码 1 次且成功）
  - 该 bug 长期潜伏，正是因为 Layer 2 旧代码无条件打印 ✅；暴露它的那次改动让 CI 三个平台
    同时变红，才被发现

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
