# Vendor 策略与更新 SOP

## 概述

`vendor/` 目录存放从第三方项目 vendor 的资源（二进制或脚本）。
这些资源由我们审查后放入项目，确保供应链安全和构建稳定性。

**核心原则**：vendor 只用于必要场景，人审查后才更新。

---

## Vendor 准入条件

以下类型允许放入 `vendor/`：

| 条件 | 说明 | 示例 |
|------|------|------|
| **自定义工具** | 无标准分发渠道，必须自行构建/打包 | `tool-installer`（Python zipapp）|
| **供应链安全关键脚本** | 需要人工审查，避免 `curl \| sh` | `rustup-init.sh` |
| **自举依赖** | 上层工具依赖它才能工作，且无法通过上层工具自身获取 | `tool-installer` 本身 |

## 明确禁止 Vendor

以下类型**禁止**放入 `vendor/`：

- ❌ **主流生态工具的二进制**（cargo-binstall, xdotter 等）
  - 这些工具有标准分发渠道（GitHub releases, crates.io）
  - 应由 Layer 1 的对应 manager 自行获取
  - Vendor 二进制增加维护负担（跨平台、版本更新、架构兼容）

- ❌ **可由 tool-installer 自行下载的工具**
  - tool-installer 的 `github-release` manager 已支持镜像回退
  - `_download_binstall` 已实现 cargo-binstall 的自举下载
  - 预装这些工具会掩盖 tool-installer 自身路径的 bug

- ❌ **临时 workaround**
  - 网络问题的修复应在工具内部解决（timeout、retry、镜像 fallback）
  - 不应通过 vendor 二进制绕过

---

## 当前 Vendor 清单

| 文件 | 类型 | 准入理由 | 状态 |
|------|------|----------|------|
| `tool-installer` | 自定义 zipapp | 无标准分发渠道，Layer 0 必须预装 | ✅ 保留 |
| `rustup-init.sh` | 审查脚本 | 供应链安全，避免 `curl \| sh` | ✅ 保留 |

## 已移除

| 文件 | 移除原因 |
|------|----------|
| `cargo-binstall` | 违反 vendor 策略，应由 tool-installer 自行获取 |
| `xdotter` | 违反 vendor 策略，应由 github-release manager 获取 |

---

## 每日检查流程

### 第 1 步：检查是否有上游更新

```bash
# 下载远程最新版本到临时文件
curl -fsSL --proto '=https' --tlsv1.2 \
    https://rsproxy.cn/rustup-init.sh \
    -o /tmp/rustup-init-remote.sh

# 与本地 vendor 版本对比
diff -u scripts/vendor/rustup-init.sh /tmp/rustup-init-remote.sh
```

**结果判断**：
- 无输出 → 本地已是最新，今日检查完成 ✅
- 有输出 → 进入第 2 步

### 第 2 步：审查变更内容

```bash
# 看完整 diff
diff -u scripts/vendor/rustup-init.sh /tmp/rustup-init-remote.sh | less
```

**审查要点**（逐条过）：
- [ ] 变更是否合理？（版本号更新、bug 修复、兼容性调整等）
- [ ] 是否有可疑的网络请求？（新增 `curl`、`wget`、`nc` 等）
- [ ] 是否有敏感路径读取？（`~/.ssh/`、`~/.gnupg/`、`/etc/shadow` 等）
- [ ] 是否有动态执行？（新增 `eval`、`source` 外部内容等）
- [ ] 是否有环境变量外传？（POST 数据到外部 URL）
- [ ] 变更是否影响现有安装流程？

### 第 3 步：根据审查结果决定

#### 情况 A：变更安全，可以更新

```bash
# 替换 vendor 文件
curl -fsSL --proto '=https' --tlsv1.2 \
    https://rsproxy.cn/rustup-init.sh \
    -o scripts/vendor/rustup-init.sh

# 提交
git add scripts/vendor/rustup-init.sh
git commit -m "vendor: update rustup-init.sh ($(date +%Y-%m-%d))"
```

更新上方「Vendor 清单」表格中的 Vendor 日期。

#### 情况 B：变更可疑或不确定

**不更新**。记录原因：

```
[日期] rustup-init.sh 远程有变更，暂不更新。
原因: <描述可疑点或不确定之处>
后续: 持续关注，待确认后再更新
```

#### 情况 C：变更很大但不一定有问题

可以先在测试环境验证：

```bash
# 在干净容器或虚拟机中用新版本跑一次 setup.sh
# 确认安装流程正常后再更新 vendor
```

### 第 4 步：清理临时文件

```bash
rm -f /tmp/rustup-init-remote.sh
```

---

## 回滚

如果更新后发现有问题：

```bash
# 回退到上一个版本
git checkout HEAD~1 -- scripts/vendor/rustup-init.sh
```

---

## 自动化建议（可选）

如果想让每日检查更省心，可以加 crontab 提醒：

```bash
# 每天 9:00 输出提醒
0 9 * * * echo "⏰ Vendor 脚本每日检查时间: cd ~/dotfiles && diff scripts/vendor/rustup-init.sh <(curl -fsSL --proto '=https' --tlsv1.2 https://rsproxy.cn/rustup-init.sh)"
```

但这只是提醒，不自动执行。**检查和更新始终由人完成**。
