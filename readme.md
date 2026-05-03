# dotfiles

> clone + run，一条命令部署完整开发环境。[English](README_EN.md)

## 快速开始

**前置条件：** `git`、`bash`、`sudo` 权限（macOS 需 Xcode Command Line Tools）

```bash
git clone https://github.com/cncsmonster/dotfiles.git && cd dotfiles && ./setup.sh
```

约 30-50 分钟（网络良好时），完成后重启终端或 `source ~/.zshrc`。

```bash
./setup.sh --deploy   # 只部署配置，不装工具
./setup.sh --install  # 只装工具，配置已部署时
```

## 包含什么

| 类别 | 内容 |
|------|------|
| **Shell** | zsh + zcomet + starship + zoxide + fzf + eza + bat + fd + ripgrep |
| **编辑器** | Neovim (nightly) + Helix，9 种语言 LSP |
| **语言** | Rust + Go + Node.js + Zig，[mise](https://mise.jdx.dev/) 统一版本管理 |
| **终端** | WezTerm + Zellij + Yazi + macchina + navi + Nerd Fonts |
| **Rust 生态** | 20+ 工具：sccache, cargo-binstall, gitui, tokei, uv, nu 等 |

## 工作原理

[xdotter](https://github.com/CNCSMonster/xdotter) 通过符号链接部署配置 → `setup.sh` 按序安装工具链。两者解耦，改配置不重装工具，加工具不改配置。

## 支持平台

Ubuntu 22.04/24.04 · WSL2 · macOS (arm64/x86_64)

## 文档

<details>
<summary>展开查看</summary>

| 主题 | 文档 |
|------|------|
| Shell 配置架构 | [shell-config-architecture.md](./docs/shell-config-architecture.md) |
| 安全实践 | [security-practices.md](./docs/security-practices.md) |
| Rust 工具更新 | [rust-tools-update-sop.md](./docs/rust-tools-update-sop.md) |
| xdotter 用法 | [xdotter-usage.md](./docs/xdotter-usage.md) |
| 贡献指南 | [CONTRIBUTING.md](./CONTRIBUTING.md) |

</details>
