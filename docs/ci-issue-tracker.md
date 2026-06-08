# CI 问题追踪记录

> 本文档记录 `feat/tool-installer-migration` 分支在 CI 和本地测试中发现的问题及修复措施。
> 目标：**保证所有工具的安装都能完成**，不因可预见的错误中断。

---

## 1. zls version_probe 正则不匹配

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | root 用户本地执行 `setup-new.sh`，已有 `~/.local/bin/zls` |
| **错误信息** | `❌ Error: Check failed for zls with manager github-release` |
| **根因** | `zls --version` 输出是 `0.15.1`（纯版本号），但 manifest 正则是 `zls (?P<version>...)`，期望带 `zls ` 前缀，永远匹配不上 |
| **为什么 CI 没发现** | CI runner 是全新环境，`~/.local/bin/zls` 不存在 → version_probe 不被调用 → 直接安装，跳过检查 |
| **修复** | `aca1be9` → manifest 中 `[zls.*.version_probe].regex` 改为 `(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)` |
| **防护措施** | CI 新增 `re-install` job（`aca1be9`），在已安装环境中第二次执行 `install dev`，强制触发所有 version_probe |

---

## 2. `local` 关键字在脚本顶层使用

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | 本地执行 `setup-new.sh` 调用 `install-fonts.sh` |
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
| **发现场景** | 非 root 用户执行 `setup-new.sh`（无 NOPASSWD） |
| **错误信息** | `⚠️  需要 sudo 权限，但当前用户无 NOPASSWD 配置` |
| **根因** | `sudo_run` 使用 `sudo -n true` 检测，只允许 NOPASSWD |
| **修复** | `b269bbd` → 与 main 分支一致：`if root: direct; else: sudo` |

---

## 5. `cp` 遇到符号链接报 "same file"

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-09 |
| **发现场景** | 非 root 用户执行 `setup-new.sh` bootstrap |
| **错误信息** | `cp: 'vendor/tool-installer' and '~/.local/bin/tool-installer' are the same file` |
| **根因** | 目标文件已是源文件的符号链接 |
| **修复** | `7d0e928` → `cp + chmod` 改为 `install -m 755` |

---

## 6. cargo config 安装时残留修改

| 项目 | 内容 |
|------|------|
| **发现时间** | 2026-06-10 |
| **发现场景** | 安装后 `langs/rust/cargo/config.toml` 被修改 |
| **根因** | `setup-new.sh` 的 `do_install()` 临时禁用 sccache/wild linker，但某些情况下未恢复 |
| **影响** | git 工作树出现意外修改，需手动 `git checkout` 恢复 |
| **状态** | 已观察，未修复（当前恢复逻辑看起来正确，需进一步确认） |

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
