# Cargo Audit 使用指南

`cargo-audit` 已预装，用于审计 Rust 项目的依赖安全漏洞。

## 使用方法

### 1. 进入 Rust 项目目录

```bash
cd /path/to/your/rust-project
```

### 2. 运行审计

```bash
# 快速审计
cargo audit

# 更新漏洞数据库后审计
cargo audit --db --update

# 显示详细信息
cargo audit --details
```

### 3. 修复漏洞

```bash
# 更新所有依赖
cargo update

# 更新特定依赖
cargo update -p crate-name

# 重新审计验证
cargo audit
```

## 示例

```bash
# 审计当前项目
cd ~/projects/my-rust-app
cargo audit

# 审计其他目录的项目
cargo audit --manifest-path /path/to/Cargo.toml
```

## 更多信息

- [cargo-audit 官方文档](https://github.com/rustsec/rustsec)
- [RustSec 漏洞数据库](https://rustsec.org/)
