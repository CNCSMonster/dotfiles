# cargo-binstall 安全审计文档

**文档版本：** 1.1
**更新日期：** 2026-04-06
**目的：** 说明 cargo-binstall 的下载机制和安全保障

---

## 1. 下载机制

### 1.1 下载源优先级

```
cargo binstall <crate>
       ↓
┌─────────────────────────────────────────────────────────────┐
│  下载源优先级（依次尝试，成功则停止）                        │
├─────────────────────────────────────────────────────────────┤
│  1️⃣ 项目官方 GitHub Releases（最高优先级）                   │
│  2️⃣ QuickInstall（第三方预编译仓库）                         │
│  3️⃣ cargo install（源码编译，最后手段）                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 流程说明

1. **GitHub Releases** - 优先从项目官方 releases 下载预编译二进制
2. **QuickInstall** - 若无官方 releases，尝试 cargo-bins 社区的预编译
3. **cargo install** - 上述都失败时，从 crates.io 源码编译

---

## 2. 安全保障机制

### 2.1 安全机制总览

| 机制 | 状态 | 说明 |
|------|------|------|
| **HTTPS + TLS 1.2+** | ✅ 强制 | 下载过程加密，防中间人攻击 |
| **crates.io checksum 验证** | ✅ 强制 | 验证 crate tar 的 SHA256 |
| **版本匹配检查** | ✅ 强制 | 确保 binary 与 crate 版本一致 |
| **签名验证 (minisign)** | 🟡 可选 | 需要 crate 配置公钥 |
| **不执行任意代码** | ✅ 设计 | 相比 `curl \| sh` 更安全 |

### 2.2 安全机制对比

| 下载方式 | HTTPS | Checksum | 签名 | 版本检查 | 不执行代码 |
|----------|-------|----------|------|----------|------------|
| **cargo binstall** | ✅ | ✅ | 🟡 | ✅ | ✅ |
| **GitHub Releases 手动** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **cargo install** | ✅ | ✅ | ❌ | ✅ | ❌ (执行 build.rs) |
| **curl \| sh** | 🟡 | ❌ | ❌ | ❌ | ❌ |

---

## 3. 供应链攻击风险

### 3.1 潜在攻击路径

| 路径 | 风险 | 缓解措施 |
|------|------|----------|
| crates.io 被攻破 | 替换 crate 源码或 checksum | crates.io 多重验证 |
| GitHub 账号被入侵 | 上传恶意二进制到 Releases | GitHub 二步验证 |
| QuickInstall 被攻破 | 上传恶意预编译二进制 | 签名验证（可选） |
| CI/CD 被入侵 | 编译过程注入恶意代码 | 最小权限原则 |
| 依赖项被投毒 | 传递依赖包含恶意代码 | cargo audit 定期扫描 |

### 3.2 风险等级评估

| 攻击路径 | 可能性 | 影响 | 风险等级 |
|----------|--------|------|----------|
| crates.io 被攻破 | 🟢 极低 | 🔴 高 | 🟡 中 |
| GitHub 账号入侵 | 🟡 中 | 🔴 高 | 🟠 中高 |
| QuickInstall 被攻破 | 🟡 中 | 🟡 中 | 🟡 中 |
| CI/CD 被入侵 | 🟡 中 | 🟡 中 | 🟡 中 |
| 依赖项投毒 | 🟢 低 | 🟡 中 | 🟢 低 |

---

## 4. 最佳实践

### 4.1 推荐场景

| 场景 | 推荐方式 | 理由 |
|------|----------|------|
| **个人开发** | cargo binstall | 速度快，风险可接受 |
| **关键工具** | cargo install --locked | 源码编译，完全可信 |
| **生产环境** | 手动验证 + 内部镜像 | 最大控制 |
| **CI/CD** | cargo binstall --only-signed | 平衡速度和安全 |

### 4.2 环境变量控制

`CARGO_INSTALL_STRICT` 在 `~/.config/shells/env.sh` 中定义（注释状态，需要时启用）：

```bash
# 严格模式：任何工具安装失败都终止脚本
export CARGO_INSTALL_STRICT=1
```

### 4.3 错误处理行为

| 模式 | 环境变量 | 行为 |
|------|----------|------|
| **默认模式** | 无 | 失败重试 3 次，跳过继续 |
| **严格模式** | `CARGO_INSTALL_STRICT=1` | 失败重试 3 次后终止脚本 |

---

## 5. CI/CD 配置

### 5.1 Docker 构建

```bash
# 启用严格模式
docker buildx build --build-arg CARGO_INSTALL_STRICT=1 .

# 禁用严格模式
docker buildx build --build-arg CARGO_INSTALL_STRICT=0 .
```

### 5.2 GitHub Actions

```yaml
jobs:
  build:
    env:
      CARGO_INSTALL_STRICT: 1  # 任何工具失败都终止构建
```

---

## 6. 结论

✅ **推荐使用 cargo binstall**，但需了解：

1. 依赖多个信任点（crates.io + GitHub + QuickInstall）
2. 签名验证是可选的，不是所有 crate 都配置
3. 对于关键工具，建议源码编译或手动验证
4. 定期运行 `cargo audit` 检查依赖漏洞
5. CI/CD 场景下，可设置 `CARGO_INSTALL_STRICT=1` 确保安装失败时及时发现问题

---

## 7. 参考资源

- cargo-binstall: https://github.com/cargo-bins/cargo-binstall
- QuickInstall: https://github.com/cargo-bins/cargo-quickinstall
- 签名验证：https://github.com/cargo-bins/cargo-binstall/blob/main/SIGNING.md
- cargo-audit: https://github.com/rustsec/rustsec
