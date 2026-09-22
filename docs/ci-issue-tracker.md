# CI 问题追踪记录

> 本文档记录 `feat/tool-installer-migration` 分支在 CI 和本地测试中发现的问题及修复措施。
> 目标：**保证所有工具的安装都能完成**，不因可预见的错误中断。

---

## 1. zls version_probe 正则不匹配

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | root 用户本地执行 `setup.sh`，已有 `~/.local/bin/zls` |
| **错误信息** | `❌ Error: Check failed for zls with manager github-release` |
| **根因** | `zls --version` 输出是 `0.15.1`（纯版本号），但 manifest 正则是 `zls (?P<version>...)`，期望带 `zls ` 前缀，永远匹配不上 |
| **为什么 CI 没发现** | CI runner 是全新环境，`~/.local/bin/zls` 不存在 → version_probe 不被调用 → 直接安装，跳过检查 |
| **修复** | `aca1be9` → manifest 中 `[zls.*.version_probe].regex` 改为 `(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)` |
| **防护措施** | `full-install` job 的 "Re-install is idempotent" 步骤：在同一 runner 上第二次执行 `install dev`，强制触发所有 version_probe / check，并断言除 `manager=script` 的工具外全部 Skip。曾长期独立成 `re-install` job，但独立 job 跑在全新 runner 的空 `$HOME` 上、等于又装了一遍，验证不到幂等，故合并 |

---

## 2. `local` 关键字在脚本顶层使用

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | 本地执行 `setup.sh` 调用 `install-fonts.sh` |
| **错误信息** | `local: can only be used in a function` → `❌ Error: Script failed for fonts` |
| **根因** | `install-fonts.sh` 顶层代码使用 `local` 声明变量，`set -u` 启用后报错 |
| **修复** | `e297bf1` → 移除 `scripts/install-fonts.sh` 中的 `local` 关键字 |
| **防护措施** | 所有脚本使用 `bash -n` 语法检查 |

---

## 3. GitHub mirrors SHA256 校验失败不 fallback

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | 本地安装 zls（走 mirror 下载） |
| **错误信息** | `❌ Error: Check failed for zls with manager github-release` |
| **根因** | mirror 返回的内容可能与官方不同 → SHA256 不匹配 → `_verify_checksum` 抛 `InstallationError` → **不会** fallback 到官方源 |
| **当前状态** | **已设计方案，代码未实现** |
| **设计方案** | 见 `project_tool_installer_mirror_fallback` memory：`sources` 配置、SHA256 失败触发 fallback |
| **临时措施** | 安装前手动禁用 mirrors：`perl -pi -e 's/^github_mirrors/#github_mirrors/' manifest.toml`，装完恢复 |
| **TODO** | 实现 `_download_asset` 内嵌 SHA256 校验逻辑，不匹配则继续下一个 URL |

---

## 4. `sudo_run` NOPASSWD-only 设计

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-09 |
| **发现场景** | 非 root 用户执行 `setup.sh`（无 NOPASSWD） |
| **错误信息** | `⚠️  需要 sudo 权限，但当前用户无 NOPASSWD 配置` |
| **根因** | `sudo_run` 使用 `sudo -n true` 检测，只允许 NOPASSWD |
| **修复** | `b269bbd` → 与 main 分支一致：`if root: direct; else: sudo` |

---

## 5. `cp` 遇到符号链接报 "same file"

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-09 |
| **发现场景** | 非 root 用户执行 `setup.sh` bootstrap |
| **错误信息** | `cp: 'vendor/tool-installer' and '~/.local/bin/tool-installer' are the same file` |
| **根因** | 目标文件已是源文件的符号链接 |
| **修复** | `7d0e928` → `cp + chmod` 改为 `install -m 755` |

---

## 6. cargo config 安装时残留修改

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | 安装后 `langs/rust/cargo/config.toml` 被修改 |
| **根因** | `setup.sh` 的 `do_install()` 临时禁用 sccache/wild linker，但某些情况下未恢复 |
| **影响** | git 工作树出现意外修改，需手动 `git checkout` 恢复 |
| **状态** | 已观察，未修复（当前恢复逻辑看起来正确，需进一步确认） |

---

## 7. cargo-install 的 check 认不出连字符命名的二进制

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-09-23 |
| **发现场景** | 分析 `tool-installer Migration Verify` 耗时：`Apply: dev (idempotency)` 这一"应该全部 Skip"的作业耗时 237s，**超过**首次真实安装的 200s |
| **错误信息** | `error: binary \`tree-sitter-grep\` already exists in destination` → `cargo install ... errored with exit status: 101` |
| **根因** | `CargoInstallManager.check()` 用 `pkg.replace("-", "_")` 猜二进制名，而 `tree-sitter-grep` / `tree-sitter-show-ast` 的 `[[bin]]` 就是带连字符的 crate 名。manifest 未声明 `bin` → check 永远找不到 → 判 `NOT_SATISFIED` → 每次 install 都源码重编译（CI 日志实测 3m17s / 3m20s） |
| **影响** | 两个 `allow_fail` 工具每次重装；`TOOL_INSTALLER_STRICT=1` 也拦不住，因为重装最终"成功"了，成本被静默吸收 |
| **修复** | `check()` 改为按 `[bin]` → `[pkg 下划线, pkg 原名]` 的顺序探测候选名，两类命名约定都能命中；回归测试见 `tool-installer/tests/test_cargo_install_check.py` |
| **防护措施** | 幂等步骤对 "already exists in destination" 直接判失败——该字符串是"二进制在盘上但 check 说没装"的确定信号，无需按工具逐个维护白名单 |

---

## 8. 幂等断言挖出的两类重跑：gitui 预发布版本号 与 rust moving channel

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-09-23 |
| **发现场景** | `84b9b31` 把独立的 idempotency job 合进 `Apply: dev (full + idempotency)`（同一 job 装完立刻第二次 `install dev`，见 #7 防护措施）后，第一次真跑就红：ubuntu-latest 与 macos-latest 同时报 `check 未识别出以下已安装工具（会被无谓重装）：gitui rust` |
| **性质** | 断言没有误报，是这条断言此前从未在"已装环境"里跑过。两个工具的成因不同，一个要修、一个要放行 |
| **其余工具** | 同一次运行里，其余带 check 的工具全部命中 `✅ Skip`（违规名单只有这两个名字），且 `already exists in destination` 未再出现——#7 的连字符修复由此得到 CI 验证 |

### 8a. gitui：binstall 产物自称 nightly，manifest 钉的是 crates.io 正式版

| 项目 | 内容 |
|------|------|
| **根因** | `gitui --version` 输出 `gitui 0.28.1-nightly 2026-03-25 ()`，`_parse_binary_version()` 取到 `0.28.1-nightly`；tools.toml 钉 `gitui@0.28.1`，而 `_v1_eq()` 是严格字符串比较 → 永远 `NOT_SATISFIED`。gitui 开了 `binstall_first`，装的是 GitHub release 产物，其版本串自带 nightly 后缀，与 crates.io 版本号天然对不上 |
| **为什么以前没发现** | gitui 是 `allow_fail`，重装走 binstall 预编译包（不源码编译、输出近乎为零），成本被静默吸收；`TOOL_INSTALLER_STRICT=1` 只汇总退出码，装"成功"就不报 |
| **修复** | 新增 `_cargo_v1_eq(installed, requested)`：先严格相等，失败后若 installed 带 `-pre` / `+build` 后缀，再用去掉后缀的 core 比一次。只赦免**同一发行号**的预发布（`0.28.1-nightly` 满足 `0.28.1`）；跨版本（`0.29.0-nightly` vs `0.28.1`）仍 `NOT_SATISFIED`，反向（钉 nightly 却装了正式版）也不赦免。作用域只限 `CargoInstallManager` 的 `--version` 路径，apt / brew / github-release / mise 继续走严格 `_v1_eq` |
| **验证** | 本机真实 `~/.cargo/bin/gitui` 的 check 由 `NOT_SATISFIED` → `SATISFIED`（bat / eza / tree-sitter-grep 保持 SATISFIED 未退化）；回归测试 `tool-installer/tests/test_cargo_install_check.py::PrereleaseVersionTolerance` 与 `::CheckAgainstFilesystem::test_nightly_banner_satisfies_the_release_pin` |

### 8b. rust：moving channel 每次重跑是设计意图，不是漏判

| 项目 | 内容 |
|------|------|
| **根因** | `RustupManager.check()` 在确认 toolchain 存在、component 齐备之后，对 `stable` / `nightly` 这类 moving channel 还额外要求 `rustup check` 报 "up to date"（`_moving_channel_current()`）。runner 镜像预装的 stable 落后上游一天，check 就判 `NOT_SATISFIED`，于是重跑一次 `rustup toolchain install stable` |
| **判断** | 这是"stable 该保持新鲜"的正确语义，不是"认不出已装"。把它列进违规名单等于要求安装器永远不更新工具链，方向错；所以放行而不是改 check |
| **防护措施** | 幂等步骤维护 `/tmp/moving-channel.txt`（当前只有 `rust`）作为豁免名单，且只放行名单内的名字——任何**新出现**的重跑仍会硬失败。`manager=script` 的条目由 dry-run 输出动态推导成 `/tmp/script-tools.txt`，无需手工维护 |

---

## 所有 SHA256 校验状态（2026-06-10 验证）

| 工具 | 版本 | SHA256 状态 |
|------|------|-------------|
| neovim | v0.12.2 | ✅ |
| helix | 25.07.1 | ✅ |
| zellij | v0.44.3 | ✅ |
| yq | v4.53.3 | ✅ |
| starship | v1.25.1 | ✅ |
| xdotter | v0.5.2 | ✅ |
| cargo-binstall | v1.19.1 | ✅ |
| zola | v0.22.1 | ✅ |
| marksman | 2026-02-08 | ✅ |
| zls | 0.15.1 | ✅ |
| lua-lsp | 3.17.1 | ✅ |

---

## 待完成

- [ ] **#2 最高优先级**：实现 GitHub mirrors SHA256 fallback 逻辑
  - `_download_asset()` 内嵌 SHA256 校验
  - 校验失败 → 继续下一个 URL
  - 支持 `sources` 配置项
