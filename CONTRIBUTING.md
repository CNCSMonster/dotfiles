# Contributing

本文档面向想要验证、修改或贡献此 dotfiles 项目的开发者。

---

## Docker 构建验证

Docker 镜像用于验证 `setup.sh` 在干净 Ubuntu 环境中可正常执行。

### 一行验证命令

```bash
./scripts/docker-build-test.sh
```

构建完成后自动运行验证脚本。

---

## 验证逻辑

验证脚本检查三类内容：

| 类别 | 说明 | 示例 |
|------|------|------|
| **工具安装** | 所有工具是否正确安装 | `rustc --version`, `nvim --version` |
| **配置部署** | xdotter 是否正确部署配置 | `~/.zshrc`, `~/.config/git` 符号链接 |
| **功能测试** | 编译器是否可正常工作 | GCC/Clang/Rust 编译测试 |

### 关键验证点

**这个项目独有的配置验证：**

```bash
# xdotter 部署的符号链接
~/.zshrc -> ~/dotfiles/shells/zsh/zshrc
~/.config/mise -> ~/dotfiles/mise
~/.config/yazi/yazi.toml -> ~/dotfiles/yazi/yazi.toml   # keymap/theme/init.lua/package.toml 同理

# 配置文件
~/.cargo/config.toml  # Rust 镜像源配置
~/.config/git/config  # Git 配置
~/.config/starship.toml  # 提示符配置
```

这些符号链接和配置文件的存在证明 xdotter 正确部署。

---

## CI 流程

GitHub Actions 共 4 个 workflow，覆盖改动验证与镜像发布：

1. **E2E 自动验证**（`runner-verify.yml`）：每次 push / PR 触发 `E2E Full Install`，在最小镜像容器 `ubuntu:24.04` / `ubuntu:26.04`（GitHub runner 裸机跑 macOS）内直接运行 `./setup.sh`，再执行验证脚本检查工具 + 配置 + 功能。使用最小容器是为了真实暴露 setup.sh 对环境的隐含依赖（runner 镜像预装 clang/libicu/unzip 会掩盖这类问题）。纯文档改动（`**.md` / `docs/**`）不触发两条安装链。
2. **tool-installer 验证**（`tool-installer-verify.yml`）：同样在 push / PR 触发（纯文档改动跳过），跑双 OS `Dry-run (all modules)`（离线解析全模块安装计划）与安装链作业；CI 中 `TOOL_INSTALLER_STRICT=1`，`allow_fail` 失败同样计入汇总并使作业非零退出（本地默认只报告、不改退出码）。
3. **完整 Docker 验证**（`docker-build.yml`）：`Dockerfile Build Check` 通过 GitHub Actions 页面手动触发，矩阵构建 `ubuntu:24.04` / `ubuntu:26.04` 基镜像并在镜像内运行验证脚本。
4. **镜像发布**（`docker-release.yml`）：release 发布时自动（或手动）矩阵构建两个基镜像并推送 GHCR（`latest` / `<version>`，26.04 基镜像带 `-26.04` 后缀）。

验证脚本输出 `通过: N` / `失败: 0` 即通过。

详情见：
- [`.github/workflows/runner-verify.yml`](.github/workflows/runner-verify.yml)
- [`.github/workflows/tool-installer-verify.yml`](.github/workflows/tool-installer-verify.yml)
- [`.github/workflows/docker-build.yml`](.github/workflows/docker-build.yml)
- [`.github/workflows/docker-release.yml`](.github/workflows/docker-release.yml)

---

## 修改后流程

1. 本地修改 dotfiles 配置
2. （首次克隆推荐）启用本地 git hook：`git config core.hooksPath .githooks`，提交时将自动触发轻量守卫（冲突标记检查、Shell 语法检查、manifest 架构矩阵解析，以及 `tool-installer` 源码改动后的单测与 vendor 同步检查）
3. 运行 `./scripts/docker-build-test.sh --gh-token "$(gh auth token)"` 做完整 Docker 构建验证（可选但推荐）
4. 按脚本提示运行镜像内验证命令，确保验证通过（`失败：0`）
5. 提交并推送（runner direct CI 自动验证）

## 自动化工具优先原则

项目 `scripts/` 目录下的脚本封装了资源限制、重试、token 管理等复杂逻辑。
**任何构建/验证操作必须先检查是否有对应的脚本，而不是手动拼凑原始命令。**

| 你要做的事 | 用这个 | 不要手动 |
|-----------|--------|-----------|
| 构建 Docker 镜像 | `scripts/docker-build-test.sh` | `docker build ...` |
| 验证镜像内容 | `scripts/verify-docker-build.sh` | `docker run ...` |
| 改 `manifest.toml`/`tools.toml` 后校验平台覆盖 | `scripts/check-manifest-platforms.sh` | 手工逐平台 dry-run |

脚本会自动处理：网络重试、GitHub API 限额（token 注入）、内存/CPU 限制、镜像源切换。
CI 用的就是同一套脚本，本地 = CI 行为。

---

## 项目结构

```
.
├── setup.sh                    # 一键安装脚本（三层架构）
├── xdotter.toml                # xdotter 配置
├── tools.toml                  # 工具组声明（版本钉定）
├── manifest.toml               # 工具清单（下载源 / 校验和）
├── tool-installer/             # 声明式安装器（Python 源码 + 离线测试）
├── scripts/                    # 自动化脚本（节选，共 20+）
│   ├── docker-build-test.sh    # Docker 构建脚本
│   ├── verify-docker-build.sh  # 验证脚本
│   └── check-manifest-platforms.sh  # 平台覆盖校验
├── .github/workflows/          # CI（共 4 个）
│   ├── runner-verify.yml       # E2E 安装验证（最小容器 + macOS）
│   ├── tool-installer-verify.yml  # dry-run + 安装链验证
│   ├── docker-build.yml        # Docker 镜像构建验证（手动触发）
│   └── docker-release.yml      # release 镜像发布（GHCR）
├── shells/                     # Shell 配置
└── docs/                       # 用户文档
```
