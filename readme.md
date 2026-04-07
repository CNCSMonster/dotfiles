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
node --version
```

---

## 其他部署方式

| 场景 | 命令 |
|------|------|
| 只部署配置（不安装工具） | `xd deploy` |
| Docker 体验 | `docker run -it dotfiles:test` |

---

## Docker 构建

```bash
# 构建镜像
./scripts/docker-build-test.sh

# 运行容器
docker run -it dotfiles:test
```

详情见 [`scripts/README.md`](./scripts/README.md)。

---

## 文档

| 主题 | 文档 |
|------|------|
| 安全设计 | [安全实践](./docs/security-practices.md) |
| Rust 工具更新 | [Rust 工具更新 SOP](./docs/rust-tools-update-sop.md) |
| Shell 配置 | [Shell 配置架构](./docs/shell-config-architecture.md) |
| Cargo Audit | [Cargo Audit 实践](./docs/safe-cargo-audit.md) |

---

## Inspired by

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config
