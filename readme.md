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

按需模块默认不装，需要时单独安装（模块清单见 `tools.toml`）：

```bash
tool-installer install network-tools   # 目前是 rathole（NAT 穿透 / 隧道反向代理）
tool-installer install devbox-tools    # 目前是 rootless docker（免 sudo；macOS 只给 colima 指引）
```

## 包含什么

| 类别 | 内容 |
|------|------|
| **Shell** | zsh + zcomet + starship + zoxide + fzf + eza + bat + fd + ripgrep |
| **编辑器** | Neovim (nightly) + Helix，9 种语言 LSP |
| **语言** | Rust + Go + Node.js + Zig，[mise](https://mise.jdx.dev/) 统一版本管理 |
| **终端** | WezTerm + Zellij + Yazi + macchina + navi + Nerd Fonts |
| **Rust 生态** | 20+ 工具：sccache, cargo-binstall, gitui, tokei, uv, nu 等 |
| **文档排版** | Typst（简历 / PDF 渲染）+ IBM Plex、Noto CJK 字体 |

## Termux（Android）最小远程开发环境

Termux 仅提供手机连接远程开发环境所需的工具，不安装完整的本地语言运行时、编辑器生态或 AI CLI。首次使用时先在 Termux 中安装 Git 并获取仓库：

```bash
pkg update
pkg install -y git

git clone https://github.com/CNCSMonster/dotfiles.git
cd dotfiles
./setup-termux.sh
```

安装 `openssh`、`git`、`tmux`、`fzf`、`ripgrep`、`zoxide`、`yazi`、`vim` 和 `tree`。脚本只安装缺失的包，不默认执行全量系统升级；Termux 包版本跟随 Termux 软件源。

支持预览待安装包：

```bash
./setup-termux.sh --dry-run
```

## 工作原理

[xdotter](https://github.com/CNCSMonster/xdotter) 通过符号链接部署配置 → `setup.sh` 按序安装工具链。两者解耦，改配置不重装工具，加工具不改配置。

## 支持平台

Ubuntu 22.04/24.04 · WSL2 · macOS (arm64/x86_64) · Termux（Android，最小远程开发工具集）

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
