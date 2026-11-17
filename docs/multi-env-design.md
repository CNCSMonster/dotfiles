# 多环境配置设计

## 设计理念

本项目使用 **单代码库 + 平台检测** 管理所有环境。通用逻辑统一写在 main，平台差异通过 `uname -s` 分支处理。

```
main  ──────────────────────────→  通用配置（Linux + macOS）
  └─ CI matrix   ── Linux / macOS 安装验证
```

> **已删除的分支**: `wsl2-ubuntu-24`、`exp-main`、`exp-wsl-ubuntu-24`、`ci-runner-direct`
> 原因：项目中无 WSL 专属代码，分支落后导致维护成本过高

## 平台验证与历史分支

所有平台使用 `main`，macOS 验证由 `.github/workflows/runner-verify.yml` 的矩阵作业承担，不需要独立平台分支。

2026-09-25 曾观察到 `origin/macos` 是迁移前旧快照；这是历史取证，不是当前分支状态。2026-11-17 本地已无该远程跟踪引用，未据此推断远端已删除。需要检查远端时使用只读 `git ls-remote --heads origin macos`，不要把旧分支处置列为持续待办。

## 使用方法

```bash
# 所有平台（含 WSL、macOS）都用 main
git checkout main
```

### 新增平台支持

在 main 中通过平台检测与声明式安装策略处理差异，配置差异通过条件配置处理，不创建长期分叉的平台配置分支。

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

## 查看当前配置

```bash
# 查看当前分支
git branch --show-current

# 只读检查历史平台分支是否仍存在于远端
git ls-remote --heads origin macos

# 查看 xdotter 部署的链接
xd status
xd deploy --dry-run
```
