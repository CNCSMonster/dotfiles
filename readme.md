# My Dotfiles

笔者的开发环境配置文件合集, 用于快速配置新环境，与多机器配置统一环境。项目main 分支版本主要支持 Ubuntu 22 和 24, 项目不同分支中的版本为分支名对应环境的适配版本。

## 快速开始

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
./setup.sh
```

安装完成后重启终端或运行 `source ~/.zshrc`。

### 验证安装

```bash
# 验证 xdotter 是否正确部署配置（本项目独有）
ls -la ~/.zshrc ~/.config/mise ~/.config/yazi
```

预期输出：`~/.zshrc` 等应为符号链接，指向 `~/.config/shells/` 下的配置。

---

## 部署方式

| 场景 | 命令 |
|------|------|
| 完整安装（推荐） | `./setup.sh` |
| 只部署配置 | `xd deploy` |

> xd 为 xdotter 项目提供的可执行文件，可以参考 https://github.com/CNCSMonster/xdotter 项目文档安装

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
