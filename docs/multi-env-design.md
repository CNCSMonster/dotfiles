# 多环境配置设计

## 设计理念

本项目使用 **单代码库 + 平台检测** 管理所有环境。通用逻辑统一写在 main，平台差异通过 `uname -s` 分支处理。

```
main  ──────────────────────────→  通用配置（Linux + macOS）
  └─ macos       ── 仅多一个 .github/workflows/macos-setup.yml CI workflow
```

> **已删除的分支**: `wsl2-ubuntu-24`、`exp-main`、`exp-wsl-ubuntu-24`、`ci-runner-direct`
> 原因：项目中无 WSL 专属代码，分支落后导致维护成本过高

## 使用方法

### 当前分支

```bash
# main 适用于所有 Linux 环境（包括 WSL）
git checkout main

# macOS 专属 CI 验证
git checkout macos
```

### 创建新环境

```bash
# 基于 main 创建新环境
git checkout -b new-environment-name

# 仅当该平台有「配置层」差异（非安装层）时才需要
# 示例：WSL 需要不同的 systemd 集成、macOS 需要完全不同的 Neovim 插件
```

## 平台差异处理

项目通过 `uname -s` 在代码中处理平台差异（安装层），而非通过分支（配置层）。示例：

```bash
if [[ "$(uname -s)" == "Darwin" ]]; then
    # macOS: Homebrew
    brew install ...
else
    # Linux: apt
    sudo apt-get install ...
fi
```

不同分支可以有：
- 独立的 CI workflow 文件（如 `macos-setup.yml`）
- 真正平台专属的配置（如 WSL `.wslconfig`、macOS `~/.hushlogin`）

## 分支命名规范

```
<环境类型>-<系统>-<版本>
```

示例：
- `macos` — macOS CI 验证
- ~~`wsl2-ubuntu-24`~~ — 已删除，无 WSL 专属代码

## 查看当前配置

```bash
# 查看当前分支
git branch --show-current

# 查看 xdotter 部署的链接
xd deploy --dry-run
```
