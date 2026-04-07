# My Dotfiles - Ubuntu 开发环境配置

基于 **xdotter** 的 dotfiles 管理系统，为 Ubuntu 22.04/24.04 提供一键开发环境配置。

**核心工具链：** Neovim · Rust · Go · Node.js · Zig · LLVM

**特点：** SHA256 校验 · 固定版本号 · 国内镜像加速 · Docker 验证

## 系统要求

| 要求 | 说明 |
|------|------|
| **OS** | Ubuntu 22.04 LTS / 24.04 LTS |
| **内存** | 建议 8GB+（Rust 编译需要） |
| **磁盘** | 建议 20GB+ 可用空间 |
| **Shell** | zsh（安装后自动切换） |

---

## 快速开始

```bash
git clone https://github.com/cncsmonster/dotfiles.git
cd dotfiles
chmod +x ./setup.sh && ./setup.sh
```

安装完成后**重启终端**或运行 `source ~/.zshrc` 使配置生效。

### 安装过程

执行 `./setup.sh` 会自动完成：

1. **部署 dotfiles 配置** - 使用 xdotter 部署所有配置文件
2. **安装 zcomet** - zsh 插件管理器（首次登录时后台自动安装）
3. **安装系统依赖** - apt 包和基础工具
4. **安装开发工具**
   - 编辑器：Neovim, Helix
   - 工具：Git, gdb, ripgrep, fd, htop
5. **安装语言工具链**
   - Rust, Go, Node.js, Zig, LLVM, Python

### 验证安装

```bash
nvim --version      # 应看到 NVIM v0.x.x
rustc --version     # 应看到 rustc 1.x.x
zsh --version       # 应看到 zsh 5.x.x
gms --version       # 应看到 gen-mdbook-summary 0.0.x
```

---

## 其他部署方式

| 场景 | 命令 | 说明 |
|------|------|------|
| **一键完整安装** | `./setup.sh` | 推荐：部署配置 + 安装工具 |
| **只部署配置** | `xd deploy` | 已有工具，只需配置 |
| **Docker 体验** | `docker run -it dotfiles:test` | 在容器中尝试效果 |

### zcomet 插件管理器说明

首次 zsh 登录时，zcomet 会在后台自动安装：

- **默认模式**：后台安装，shell 立即可用
- **等待完成**：`ZCOMET_BG_INSTALL=0 zsh`（阻塞约 10-30 秒）

---

## Docker 构建与测试

你可以构建 Docker 镜像来本地体验或验证配置：

```bash
# 构建镜像（自动资源控制，推荐）
./scripts/docker-build-test.sh

# 无缓存重建
./scripts/docker-build-test.sh --no-cache

# 网络不稳定时重试（例如最多 3 次）
./scripts/docker-build-test.sh --retry 3
```

构建脚本会：
- 检测可用内存和 CPU 核心数
- 动态计算资源限制
- 创建 BuildKit builder 并设置限制
- 避免构建过程耗尽系统资源

运行容器：

```bash
docker run -it dotfiles:test
```

详细说明见 [`scripts/README.md`](./scripts/README.md)。

---

## 深入了解

| 你想知道... | 阅读文档 |
|------------|---------|
| 🔒 为什么这个 dotfiles 可信？ | [安全实践](./docs/security-practices.md) |
| 📦 如何更新 Rust 工具？ | [Rust 工具更新 SOP](./docs/rust-tools-update-sop.md) |
| 🐚 Shell 配置如何组织？ | [Shell 配置架构](./docs/shell-config-architecture.md) |
| ✅ 如何审计 Rust 依赖安全？ | [Cargo Audit 实践](./docs/safe-cargo-audit.md) |

---

## 常见问题

**Q: 安装后命令不可用？**

A: 运行 `source ~/.zshrc` 或重启终端使配置生效。

**Q: Docker 构建失败？**

A: 使用 `./scripts/docker-build-test.sh --retry 3` 重试，或检查网络连接。

**Q: 只想更新某个工具？**

A: 参考 [Rust 工具更新 SOP](./docs/rust-tools-update-sop.md)。

---

## Inspired by

- https://github.com/TD-Sky/dotfiles
- https://github.com/SuperCuber/dotter
- https://github.com/5eqn/nvim-config
- https://juejin.cn/post/7283030649610223668
