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
~/.zshrc -> ~/.config/shells/zsh/zshrc
~/.config/mise -> ~/.local/share/mise
~/.config/yazi -> ~/.config/yazi

# 配置文件
~/.cargo/config.toml  # Rust 镜像源配置
~/.config/git/config  # Git 配置
~/.config/starship.toml  # 提示符配置
```

这些符号链接和配置文件的存在证明 xdotter 正确部署。

---

## CI 流程

GitHub Actions 有两类验证：

1. **自动验证**：每次 push / PR 触发 `Setup Verification (Runner Direct)`，在 `ubuntu-latest` 和 `macos-latest` 直接运行 `./setup.sh`，再执行验证脚本检查工具 + 配置 + 功能。
2. **完整 Docker 验证**：`Dockerfile Build Check` 通过 GitHub Actions 页面手动触发，构建 Docker 镜像并在镜像内运行验证脚本。

验证脚本输出 `通过：XX  失败：0` 即通过。

详情见：
- [`.github/workflows/runner-verify.yml`](.github/workflows/runner-verify.yml)
- [`.github/workflows/docker-build.yml`](.github/workflows/docker-build.yml)

---

## 修改后流程

1. 本地修改 dotfiles 配置
2. 运行 `./scripts/docker-build-test.sh --gh-token "$(gh auth token)"` 做完整 Docker 构建验证（可选但推荐）
3. 按脚本提示运行镜像内验证命令，确保验证通过（`失败：0`）
4. 提交并推送（runner direct CI 自动验证）

## 自动化工具优先原则

项目 `scripts/` 目录下的脚本封装了资源限制、重试、token 管理等复杂逻辑。
**任何构建/验证操作必须先检查是否有对应的脚本，而不是手动拼凑原始命令。**

| 你要做的事 | 用这个 | 不要手动 |
|-----------|--------|-----------|
| 构建 Docker 镜像 | `scripts/docker-build-test.sh` | `docker build ...` |
| 验证镜像内容 | `scripts/verify-docker-build.sh` | `docker run ...` |

脚本会自动处理：网络重试、GitHub API 限额（token 注入）、内存/CPU 限制、镜像源切换。
CI 用的就是同一套脚本，本地 = CI 行为。

---

## 项目结构

```
.
├── setup.sh                    # 一键安装脚本
├── xdotter.toml                # xdotter 配置
├── scripts/
│   ├── docker-build-test.sh    # Docker 构建脚本
│   └── verify-docker-build.sh  # 验证脚本
├── .github/workflows/
│   └── docker-build.yml        # CI 配置
├── shells/                     # Shell 配置
└── docs/                       # 用户文档
```
