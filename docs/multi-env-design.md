# 多环境配置设计

## 设计理念

本项目使用 **单代码库 + 平台检测** 管理所有环境。通用逻辑统一写在 main，平台差异通过 `uname -s` 分支处理。

```
main  ──────────────────────────→  通用配置（Linux + macOS）
  └─ macos       ── 仅用于 macOS CI 验证，不承载平台专属配置
```

> **已删除的分支**: `wsl2-ubuntu-24`、`exp-main`、`exp-wsl-ubuntu-24`、`ci-runner-direct`
> 原因：项目中无 WSL 专属代码，分支落后导致维护成本过高

## 现状核对（2026-09-25 实测）

上面的"macos = main + 一个 CI workflow"是**设计意图**；分支的实际状态需要用 git 核对，
不能假定它与 main 同步。以下为实测结果：

| 分支 | 实测状态 | 结论 |
|------|---------|------|
| `main` | 代码分支，macOS 由 `.github/workflows/runner-verify.yml` 的 `macos-latest` 矩阵真实安装验证 | 唯一需要在意的分支 |
| `origin/macos` | 落后 main **177** 个提交、领先 **2** 个，最后一次提交 `a86cbee`（2026-04-20）；缺少 `tools.toml`、`tool-installer/`、`vendor/` 等 **94 个文件**的变更；workflows 只有 `docker-build.yml` + `runner-verify.yml` | **不是** "main + macOS workflow"，而是 tool-installer 迁移前的旧快照，属待处理技术债 |

> 历史说明：早期文档提到的 `.github/workflows/macos-setup.yml` 已不存在，其职责由
> `runner-verify.yml` 的 macOS 矩阵作业承担。
>
> `origin/macos` 的处置（快进到 main，或直接删除）尚未决定——因为删除远端分支不可逆，
> 需要仓库所有者确认。在决定之前，**不要把 `macos` 当作 main 的等价替代**。

## 使用方法

```bash
# 所有平台（含 WSL、macOS）都用 main
git checkout main
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
- 独立的 CI workflow 文件
- 真正平台专属的配置（如 WSL `.wslconfig`、macOS `~/.hushlogin`）

## 分支命名规范

```
<环境类型>-<系统>-<版本>
```

示例：
- `macos` — macOS CI 验证（当前落后，见上）
- ~~`wsl2-ubuntu-24`~~ — 已删除，无 WSL 专属代码

## 查看当前配置

```bash
# 查看当前分支
git branch --show-current

# 查看分支与 main 的实际差距（别凭印象）
git rev-list --left-right --count main...origin/macos

# 查看 xdotter 部署的链接
xd status
xd deploy --dry-run
```
