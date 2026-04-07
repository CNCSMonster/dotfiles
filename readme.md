# My Dotfiles

基于 **xdotter** 的 Ubuntu 开发环境配置，为 Ubuntu 22.04/24.04 提供一键部署。

## 快速开始

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
./setup.sh
```

安装完成后重启终端或运行 `source ~/.zshrc`。

### 验证安装

```bash
nvim --version
rustc --version
go version
```

---

## 部署方式

| 场景 | 命令 |
|------|------|
| 完整安装（推荐） | `./setup.sh` |
| 只部署配置 | `xd deploy` |

---

## zcomet 插件管理器

首次 zsh 登录时，zcomet 会在后台自动安装：

- **默认**：后台安装，shell 立即可用
- **等待完成**：`ZCOMET_BG_INSTALL=0 zsh`（阻塞约 10-30 秒）

安装完成后重启 shell 即可使用插件系统。

---

## 文档

| 主题 | 文档 |
|------|------|
| 安全设计 | [安全实践](./docs/security-practices.md) |
| Rust 工具更新 | [Rust 工具更新 SOP](./docs/rust-tools-update-sop.md) |
| Shell 配置 | [Shell 配置架构](./docs/shell-config-architecture.md) |
| Cargo Audit | [Cargo Audit 实践](./docs/safe-cargo-audit.md) |

---

## For Contributors

想要验证或修改此项目？见 [Contributing Guide](./CONTRIBUTING.md)。

---

## Inspired by

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
