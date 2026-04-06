# Safe Cargo Audit 使用指南

使用 `bubblewrap` (bwrap) 沙箱运行 `cargo audit`，防止恶意代码执行。

## 安装

`cargo-audit` 已集成到 dotfiles 中，运行以下命令自动安装：

```bash
./setup.sh
```

安装后，`safe-cargo-audit` 命令将位于 `~/.local/bin/safe-cargo-audit`。

## 使用方法

`safe-cargo-audit` 支持 `cargo audit` 的所有参数，直接使用即可。

### 基本用法

```bash
# 进入 Rust 项目目录
cd /path/to/your/rust-project

# 快速审计（默认）
safe-cargo-audit

# 等同于
cargo audit
```

### 传递参数

```bash
# 显示详细信息
safe-cargo-audit --details

# 忽略特定漏洞
safe-cargo-audit --ignore RUSTSEC-2024-0XXX

# JSON 输出
safe-cargo-audit --json

# 更新漏洞数据库
safe-cargo-audit --db --update

# 组合参数
safe-cargo-audit --details --ignore RUSTSEC-2024-0XXX
```

### 查看帮助

```bash
safe-cargo-audit --help
```

## 安全特性

### 默认配置

| 特性 | 说明 |
|------|------|
| **只读项目目录** | `--ro-bind` 防止修改源码 |
| **网络访问** | ✅ 允许（更新漏洞数据库需要） |
| **隔离 /home** | `--tmpfs /home` 防止访问用户文件 |
| **临时缓存** | 退出后自动清理，不留痕迹 |

### 沙箱环境

```bash
# 文件系统
- 项目目录：只读挂载
- /home: 临时文件系统（隔离）
- /root: 临时文件系统（隔离）
- /tmp: 临时文件系统（隔离）
- /etc/ssl: 只读挂载（SSL 证书）
- /etc/ca-certificates: 只读挂载（CA 证书）

# 网络
- ✅ 允许访问（更新漏洞数据库需要）

# 设备
- /dev: 最小化挂载（构建需要）
- /proc: 挂载 proc 文件系统
```

## 与普通 cargo audit 的对比

| 特性 | cargo audit | safe-cargo-audit |
|------|-------------|------------------|
| **文件系统** | 完全访问 | 只读项目目录 |
| **网络访问** | 完全访问 | ✅ 允许（更新漏洞数据库需要） |
| **/home 访问** | 完全访问 | 隔离（tmpfs） |
| **缓存持久化** | 持久化 | 临时（退出清理） |
| **安全性** | 🟡 中等 | 🟢 高 |
| **参数兼容性** | - | ✅ 100% 兼容 |

## 使用场景

### ✅ 推荐使用

- 审计不熟悉的第三方项目（沙箱隔离更安全）
- 审计包含大量依赖的项目
- CI/CD 自动化审计
- 定期安全检查
- 需要隔离环境的场景

### ⚠️ 完全禁用网络（可选）

如果你希望在**完全离线**环境下审计（更安全），可以手动修改脚本移除 `--share-net`：

```bash
# 编辑脚本，移除 --share-net 行
# 注意：需要先更新漏洞数据库才能在离线模式下使用
cargo audit --db --update  # 在沙箱外更新
# 然后编辑 ~/.local/bin/safe-cargo-audit，删除 --share-net 行
safe-cargo-audit           # 在沙箱内使用本地缓存
```

## 故障排查

### 问题 1: bwrap 权限错误

**症状：** `bwrap: No permissions to create namespace`

**解决：**
```bash
# 检查内核是否支持 unprivileged user namespaces
cat /proc/sys/kernel/unprivileged_userns_clone

# 如果为 0，启用它
sudo sysctl -w kernel.unprivileged_userns_clone=1
```

## 高级用法

### CI/CD 集成

```yaml
# .github/workflows/audit.yml
jobs:
  safe-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get install bubblewrap
      - run: cargo install cargo-audit
      - run: safe-cargo-audit
```

### 脚本中使用

```bash
#!/bin/bash

# 在 Rust 项目中运行安全审计
cd /path/to/rust-project

# 沙箱模式（安全）
if safe-cargo-audit; then
    echo "✅ 审计通过"
else
    echo "❌ 发现漏洞"
    exit 1
fi
```

## 参考资源

- [bubblewrap 官方仓库](https://github.com/containers/bubblewrap)
- [cargo-audit 文档](https://github.com/rustsec/rustsec)
- [Linux Namespaces 文档](https://man7.org/linux/man-pages/man7/namespaces.7.html)

---

**最后更新**: 2026-03-28
