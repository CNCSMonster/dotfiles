# rustup-init.sh Vendor 更新 SOP

## 范围

本文件**只讲 `scripts/vendor/rustup-init.sh` 的更新操作流程**（定期比对、人工审查、回滚）。

> **vendor 准入条件、禁止清单、完整 vendor 清单，一律以
> [`docs/tool-installer-migration-plan.md`](../../docs/tool-installer-migration-plan.md) §3
> 为唯一来源**，本文件不重复、也不得另立一份。
>
> 历史上本文件曾自带一份准入条件与"已移除"清单，结果是两份清单漂移：它把
> `vendor/xdotter` 写成"已移除"，而该文件当时仍在库并被 `setup.sh` 使用。清单只允许有一份。

## 为什么它被 vendor

`rustup-init.sh` 属于 §3.1 的**供应链安全关键脚本**：官方安装方式是把远程脚本直接管道给
shell（`curl … | sh`），入库一份经人工审查的副本可以：
- 避免执行未经审查的远程内容
- 让安装流程在离线/镜像不可用时仍可解释

它由 [`scripts/install-rustup.sh`](../install-rustup.sh) 调用（`exec … vendor/rustup-init.sh -y`），
是 `[build-base]` 模块的前置步骤。

---

## 定期检查流程

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
- 无输出 → 本地已是最新，本次检查完成 ✅
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

如果想让定期检查更省心，可以加 crontab 提醒：

```bash
# 每天 9:00 输出提醒
0 9 * * * echo "⏰ Vendor 脚本检查时间: cd ~/dotfiles && diff scripts/vendor/rustup-init.sh <(curl -fsSL --proto '=https' --tlsv1.2 https://rsproxy.cn/rustup-init.sh)"
```

但这只是提醒，不自动执行。**检查和更新始终由人完成**。
