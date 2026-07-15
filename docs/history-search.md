# 历史搜索方案设计

**更新日期：** 2026-07-15  
**目的：** 说明历史搜索工具选型决策和当前方案架构

---

## 背景

曾使用 mcfly 作为历史搜索工具（Ctrl+R 触发），但因以下问题移除：
- 多 shell session 启动时 SQLite 锁竞争，可能导致阻塞或死锁
- ML 排序带来的体验提升不明显

## 方案选型

| 工具 | 目录感知 | 锁/冻结风险 | 新增依赖 | 评估 |
|------|---------|------------|---------|------|
| mcfly | ✅ | ❌ SQLite 锁 | cargo install | 已移除 |
| atuin (daemon) | ✅ | ❌ daemon 冻结 | cargo/brew | 不采用 |
| atuin (非 daemon) | ✅ | ⚠️ 理论竞争 | cargo/brew | 不采用 |
| hstr | ❌ | ✅ 无 | brew/apt | 不采用 |
| **fzf (增强)** | ✅ (sidecar) | ✅ 无 | 已有 | **采用** |

### 为什么不选 atuin

atuin 非 daemon 模式使用 SQLite WAL + busy timeout，理论上不会卡死。
但 daemon 模式存在已知问题：daemon 崩溃后 socket 残留，导致所有 shell 命令冻结（[#3382](https://github.com/atuinsh/atuin/issues/3382)，2026-04 报告，至今未关闭）。

核心原则：**功能可以少，但工具链的稳定性和可用性不能妥协。**

---

## 当前方案：fzf 增强

### 架构

```
Ctrl+R (自定义 widget，替换 fzf 默认绑定)
       ↓
  合并两个数据源：
  1. sidecar 文件（PWD + 命令，当前目录优先）
  2. shell history 文件（全量历史，补充 sidecar 之前的记录）
       ↓
  去重后送入 fzf TUI 展示
       ↑
  precmd hook 写入 sidecar
  (PWD + 命令)
```

### 组件

#### 1. Ctrl+R - 目录感知历史搜索

- 自定义 widget，替换 fzf 默认的 Ctrl+R 绑定
- 合并 sidecar 文件（带目录信息）和 shell history 文件（全量历史）
- 当前目录的命令优先展示（排在列表前面）
- 通过 awk 去重，保证每条命令只出现一次

#### 2. precmd hook (`_fhd_track`)

- 每次命令执行后记录 `PWD\t命令` 到 sidecar 文件
- zsh: 仅使用 builtin（fc, printf），不 fork 外部进程
- bash: 使用 history + sed
- 错误静默处理（`2>/dev/null`），不影响 shell 使用

### sidecar 文件格式

```
/Users/kuku/project1	git status
/Users/kuku/project1	npm run build
/Users/kuku/dotfiles	xd deploy --dry-run
/Users/kuku/project2	docker compose up
```

---

## 局限性

1. **sidecar 文件仅记录安装后执行的命令**：通过合并 shell history 文件弥补，不会丢失历史
2. **目录匹配是精确匹配**：`/a/b` 和 `/a/b/c` 视为不同目录（不像 atuin 有 workspace 模式）
3. **sidecar 文件无自动清理**：长期使用会缓慢增长（正常频率约 10KB/天）

---

## 稳定性保证

- 不引入任何新的外部工具或数据库
- 不依赖任何 daemon 进程
- 不修改 shell 原生 history 文件
- hook 出错时静默降级，不影响 shell 正常使用
- fzf 已作为系统包安装，无额外安装步骤
- 即使 sidecar 文件为空，仍可通过 shell history 文件搜索全量历史

---

## 配置位置

| 组件 | 文件 | 说明 |
|------|------|------|
| `_fhd_track` | `shells/common/inter.sh` | precmd hook，记录目录历史 |
| `_fhd_source` | `shells/common/inter.sh` | 合并 sidecar + shell history |
| `_fhd_widget` | `shells/common/inter.sh` | Ctrl+R widget 定义 |

---

**文档结束**
