# Rust 工具更新 SOP

本文档描述如何检查和更新通过 `cargo binstall` 安装的 Rust 工具。

## 前置条件

- Rust 工具链已安装 (`rustup`)
- `cargo-binstall` 已安装

## 更新流程

### 1. 检查可用更新

```bash
# 方法 A: 使用 cargo-install-update（推荐）
cargo install-update --list

# 方法 B: 手动检查单个包
cargo search uv | grep "^uv = "
```

### 2. 确认 Rust 工具链版本

某些工具需要较新的 Rust 版本才能编译：

```bash
# 查看当前 Rust 版本
rustc --version

# 查看已安装的工具链
rustup show

# 如需更新 Rust
rustup update stable
```

### 3. 更新工具

#### 方法 A: 使用 cargo binstall（推荐）

```bash
# 更新到最新版
cargo binstall <package> -y

# 更新到指定版本
cargo binstall <package>@<version> -y
```

#### 方法 B: 从源码编译（备选）

如果 binstall 失败且 Rust 版本满足要求：

```bash
cargo install <package> --locked
```

### 4. 更新配置文件

如果希望固定新版本，更新 `shells/common/install-functions.sh`：

```bash
local CRATES=(
    ...
    <package>@<new-version>
)
```

## 常见问题

### 问题 1: binstall 下载失败

**原因**: 无预编译二进制或网络问题

**解决**:
```bash
# 检查是否有预编译二进制
# 访问 https://github.com/<owner>/<repo>/releases

# 尝试从源码编译
cargo install <package> --locked
```

### 问题 2: cargo install 编译失败

**原因**: Rust 版本不满足要求

**解决**:
```bash
# 查看项目要求的 Rust 版本
curl -sL https://raw.githubusercontent.com/<owner>/<repo>/main/Cargo.toml | grep rust-version

# 更新 Rust 工具链
rustup update stable

# 或使用 nightly
rustup run nightly cargo install <package> --locked
```

### 问题 3: 版本冲突

**原因**: 依赖冲突或锁定文件问题

**解决**:
```bash
# 不使用 --locked
cargo install <package>

# 或强制重装
cargo install <package> --force
```

## 当前已安装的工具

查看 `~/.cargo/.crates.toml` 或运行：

```bash
ls ~/.cargo/bin | head -20
```

## 相关文件

- 安装配置: `shells/common/install-functions.sh`
- 安装记录: `~/.cargo/.crates.toml`
- 二进制目录: `~/.cargo/bin/`