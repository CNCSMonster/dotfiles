# Vendor 脚本更新 SOP

## 概述

`scripts/vendor/` 目录存放从第三方项目 vendor 的脚本文件。
这些脚本由我们审查后放入项目，确保软件供应链安全。

**核心原则**：脚本不自动更新，人审查后才更新。

---

## Vendor 清单

| 脚本 | 来源 URL | Vendor 日期 | 说明 |
|------|----------|------------|------|
| `rustup-init.sh` | `https://rsproxy.cn/rustup-init.sh` | 2026-05-16 | Rustup 安装脚本 |
| `cargo-binstall-install.sh` | `shells/scripts/vendor/`（项目内迁移） | 见 git log | cargo-binstall 安装脚本 |

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
