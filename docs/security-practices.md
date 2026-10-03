# 安全实践文档

本文档记录本项目中采用的安全实践和防御措施。

---

## 下载文件完整性校验

### SHA256 哈希校验

对于从网络下载的二进制文件和压缩包，项目进行 SHA256 校验和验证，以防止：

- **中间人攻击** - 网络传输过程中文件被篡改
- **DNS 劫持** - 被重定向到恶意下载源
- **官方源被入侵** - 上游发布被篡改的文件
- **传输错误** - 网络问题导致的文件损坏

### 实现

SHA256 在 `manifest.toml` 中按工具、按平台声明，由 `tool-installer` 下载后校验：

```toml
[helix.linux.x86_64]
sha256 = "3f08e63ecd388fff657ad39722f88bb03dcf326f1f2da2700d99e1dc40ab2e8b"
```

当前所有 `github-release` 条目均带 `sha256` 声明。

### 更新哈希值

升级工具版本时，同步更新 `manifest.toml` 对应条目的 `sha256`：

```bash
# 计算新版本的 SHA256
curl -sL <download-url> | sha256sum

# 或先下载再计算
curl -sL -o /tmp/test.tar.xz <download-url>
sha256sum /tmp/test.tar.xz
```

---

## 不依赖外部插件仓库

### 风险说明

使用第三方版本管理插件（如 asdf/mise 插件）存在以下风险：

1. **恶意代码注入** - 插件脚本以用户权限执行，可访问所有文件
2. **仓库被接管** - 原作者离职或仓库被恶意 transfer
3. **无版本锁定** - 插件更新后可能引入恶意代码
4. **无哈希校验** - asdf 插件不支持下载文件的完整性验证

### 本项目方案

本项目**不依赖外部版本管理器插件仓库**（asdf/mise plugin 一类），采用以下方式：

- 安装逻辑集中在 `tool-installer`（Python 包）与声明式 `manifest.toml` / `tools.toml`
- 从官方源下载（GitHub Releases、官方镜像）
- 固定版本号，避免意外升级
- 对关键工具进行 SHA256 校验

### 对比

| 方案 | 外部依赖 | 哈希校验 | 版本控制 |
|------|---------|---------|---------|
| asdf/mise 插件 | ✅ 有 | ❌ 无 | ⚠️ 部分 |
| 本项目方案 | ❌ 无 | ✅ 有 | ✅ 完全 |

> 边界说明：shell 插件（zcomet 管理的 `zsh-completions` 等）从 GitHub 拉取但钉死版本，且只参与 shell 配置层，不进入工具安装链。

---

## 固定版本号

### 原则

安装的工具默认使用**固定版本号**，而不是 `latest` 或 `stable`。

例外及其语义是显式设计，写在 `tools.toml` 中：

| 例外 | 写法 | 语义 |
|------|------|------|
| 系统包 | `system-packages@latest` | apt 侧“装了即满足”，不比 candidate、不隐式升级 |
| Rust 工具链 | `rust@stable` | moving channel，跟随 rustup stable |
| 脚本型安装任务 | `mise-install@1` | 任务型条目，`@1` 为迭代号 |

### 原因

1. **可重现性** - 不同时间运行脚本得到相同的结果
2. **稳定性** - 避免新版本的回归问题
3. **安全性** - 明确知道安装的是什么版本

### 实现

```toml
# 好的做法 - tools.toml 中钉版
"helix@25.07.1" = "Helix 编辑器"

# 避免 - 未经设计的 latest（例外场景按上表语义显式声明）
```

---

## 用户级安装

### 原则

优先使用用户级安装（`~/.local/bin`、`~/.cargo/bin`），而不是系统级安装。

### 优点

1. **最小权限** - 不需要 root/sudo 权限
2. **隔离性** - 不影响系统其他用户
3. **易清理** - 删除用户目录即可完全移除

---

## 临时文件清理

### 原则

下载和安装过程中产生的临时文件必须及时清理。

### 实现

```bash
# 安装完成后清理
rm -rf "$HELIX_TMP" "$DEST"
```

---

## 安全更新流程

当需要更新工具版本时，遵循以下流程：

1. **审查变更** - 阅读上游的 Release Notes 和 Changelog
2. **获取哈希** - 下载新版本并计算 SHA256
3. **更新脚本** - 修改版本号和哈希值
4. **测试验证** - 在干净环境中测试安装流程
5. **提交记录** - Commit message 说明更新原因

---

## 已知限制

### 哈希校验的局限性

| 能保护 | 不能保护 |
|-------|---------|
| 文件完整性 | 插件脚本本身的恶意代码 |
| 检测篡改 | 官方私钥泄露 |
| 传输错误 | 版本本身的漏洞 |

### 信任假设

本项目的安全模型基于以下假设：

1. **Git 仓库是可信的** - 从可信源克隆代码
2. **GitHub Releases 是可信的** - 官方发布未被入侵
3. **本地系统是可信的** - 运行环境未被控制

如果这些假设不成立，哈希校验无法提供保护。

---

## 参考

- [SHA-256 - Wikipedia](https://en.wikipedia.org/wiki/SHA-2)
- [Software Supply Chain Security - OWASP](https://owasp.org/www-community/Supply_Chain_Security)
- [SLSA Framework](https://slsa.dev/)
