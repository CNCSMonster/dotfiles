# Shell 配置架构设计文档

**文档版本：** 1.0  
**更新日期：** 2026-03-28  
**目的：** 说明 shells/common 目录下各配置文件的职责划分和设计原则

---

## 目录结构

```
shells/common/
├── env.sh              # 基础环境变量配置
├── fn.sh               # 功能函数库
├── inter.sh            # 交互式 shell 配置
└── alias.sh            # 命令别名
```

> 工具安装**不属于** shell 配置层：它由 `setup.sh` 调用 vendored `tool-installer`（zipapp）完成，读取 `tools.toml` + `manifest.toml`。历史上这层逻辑放在 `shells/common/install-functions.sh`，现已移除（见 `docs/tool-installer-migration-plan.md`）。

---

## 文件职责划分

### 1. env.sh - 基础环境变量

**职责：** 设置所有场景都需要的基础环境变量

**加载时机：** 所有 shell 会话（交互式 + 非交互式）

**包含内容：**
- PATH 环境变量
- 语言环境（LANG, LC_*）
- 编辑器配置（EDITOR, VISUAL）
- XDG 基础目录（XDG_CONFIG_HOME 等）
- **mise 环境**：非交互式用 `mise hook-env` 立即把 shims 注入 PATH；交互式激活在 `inter.sh`
- 镜像源配置（Rust, Go 等）

**示例：**
```bash
# ✅ 应该放在 env.sh
export PATH="/usr/local/bin:$PATH"
export EDITOR='hx'
export RUSTUP_DIST_SERVER='https://rsproxy.cn'

# 非交互式：hook-env 立即注入 shims（activate 依赖 prompt 钩子，在脚本里不生效）
if [[ $- != *i* ]] && command -v mise &>/dev/null; then
    eval "$(mise hook-env -s $SH)" 2>/dev/null || true
fi
```

**设计原则：**
- ✅ 所有场景都需要（交互式、Docker、CI/CD）
- ✅ 不包含交互式特性（prompt、快捷键）
- ✅ 不依赖外部工具（除了 mise）

---

### 2. inter.sh - 交互式 Shell 配置

**职责：** 配置仅在交互式 shell 中生效的特性

**加载时机：** 仅交互式 shell 会话

**包含内容：**
- Shell 提示符（starship）
- 快捷键绑定（navi Ctrl+N）
- 命令增强（zoxide cd 增强）
- 历史搜索增强（fzf Ctrl+R 目录感知）
- 第三方命令补全（xd、llm-proxy、codex、opencode）
- mise 交互式激活（`mise activate`）

**示例：**
```bash
# ✅ 应该放在 inter.sh
eval "$(starship init $SH)"     # prompt
eval "$(navi widget $SH)"       # Ctrl+N 快捷键
eval "$(zoxide init $SH)"       # cd 命令增强
eval "$(mise activate $SH)"     # mise 版本切换与 shims（交互式）

# ✅ 第三方命令补全统一放在这里
if command -v xd >/dev/null 2>&1; then
    eval "$(xd completion "$SH")"
fi
if command -v codex >/dev/null 2>&1; then
    eval "$(codex completion "$SH" 2>/dev/null)"
fi
if command -v opencode >/dev/null 2>&1; then
    eval "$(opencode --completions "$SH" 2>/dev/null)"
fi

# ❌ 不应该放在 inter.sh
export PATH="..."               # 应该在 env.sh
eval "$(mise hook-env -s $SH)"  # 非交互式初始化应该在 env.sh
```

**非交互式检测：**
```bash
# 第一行就检测非交互式并返回
[[ $- != *i* ]] && return
```

**典型非交互式场景：**
- Docker `RUN` 命令
- GitHub Actions CI/CD
- `bash -c "command"`
- `./setup.sh` 脚本执行

---

### 3. fn.sh - 功能函数库

**职责：** 提供通用功能函数

**加载时机：** 每次交互式 shell 初始化（`init.zsh` / `bashrc` 都会 source）

**包含内容：**
- 工具函数（fzf 跳转）
- npm/pnpm 镜像源切换函数

**示例：**
```bash
# fn.sh 提供通用函数
function fj() { ... }           # fzf 跳转目录
function npm-cn() { ... }       # 使用淘宝镜像运行 npm
function use-npm-mirror() { ... }  # 切换到淘宝镜像
```

**注意：** `retry_fn` 重试函数定义在 `setup.sh` 中，不在 fn.sh 中。

---

### 4. alias.sh - 命令别名

**职责：** 设置常用命令的快捷别名

**加载时机：** 交互式 shell 会话

**包含内容：**
- 系统命令别名
- 工具快捷方式

**示例：**
```bash
# alias.sh
alias ll='ls -la'
alias gs='git status'
```

---

## 关键设计决策

### 决策 1：mise 按 shell 类型分别初始化

`mise activate` 依赖 shell prompt 钩子：非交互式进程没有 prompt，调用 activate 后
shims 不会立即进入 PATH，脚本里的 node/npm 仍然找不到。因此拆成两条路径：

1. **env.sh**：仅非交互式执行 `mise hook-env -s $SH`，立即注入 shims（Docker/CI/安装器）
2. **inter.sh**：交互式执行 `mise activate $SH`，负责版本切换钩子与 prompt 集成

**对比：**
| 配置 | 位置 | 原因 |
|------|------|------|
| `mise hook-env` | env.sh（非交互式分支） | 脚本/CI 需要立即可用的命令 |
| `mise activate` | inter.sh | 依赖 prompt 钩子，仅交互式有意义 |
| `starship init` | inter.sh | 仅交互式 prompt |
| `zoxide init` | inter.sh | 交互式 cd 增强 |

---

### 决策 2：交互式检测放在 inter.sh 第一行

**原因：**
1. 防止在非交互式环境加载交互式特性
2. 避免错误（如 starship 在非交互式会失败）
3. 提高性能（不必要的初始化）

**检测代码：**
```bash
[[ $- != *i* ]] && return
```

**检测时机：**
- 在 env.sh 载入**之后**（非交互式的 mise hook-env 已完成）
- 在交互式工具（starship/zoxide/navi/mise activate）**之前**

---

### 决策 3：工具安装与 shell 配置分离

**原因：**
1. 安装脚本常在非交互式环境运行（Docker、CI），需要稳定的执行入口
2. 安装逻辑（版本锁定、下载、fallback）属于声明式配置，不应散落在 sourced shell 函数里
3. 非交互式 mise 环境仍由 `env.sh` 的 `hook-env` 提供，供安装器在需要 node/npm 时调用

**安装入口：**
```
setup.sh
  ↓
source env.sh            # ✅ hook-env 已把 mise shims 注入 PATH
tool-installer install dev   # ✅ 读取 tools.toml + manifest.toml
```

---

## 加载顺序

### 交互式 Shell（如打开终端）

```bash
~/.bashrc 或 ~/.zshrc
  ↓
source shells/common/env.sh      # 1. 基础环境（含非交互式 mise hook-env）
source shells/zsh/config.zsh     # 2. zsh 专属交互配置（仅 zsh；bash 无此层）
source shells/common/fn.sh       # 3. 工具函数
source shells/common/alias.sh    # 4. 命令别名
source shells/common/inter.sh    # 5. 交互式配置（含 mise activate）
```

### 非交互式 Shell（如 Docker RUN）

```bash
setup.sh
  ↓
source shells/common/env.sh      # 1. 基础环境（hook-env 注入 mise shims）
python3 vendor/tool-installer install dev  # 2. 工具安装（非 shell 配置层）
# 不加载 inter.sh（交互式特性不需要）
```

---

## 常见错误示例

### ❌ 错误 1：在 inter.sh 中设置 PATH

```bash
# inter.sh（错误）
export PATH="$HOME/.local/bin:$PATH"  # ❌ 非交互式环境用不到
```

**问题：** Docker/CI 无法使用这个 PATH

**修正：** 移到 `env.sh`

---

### ❌ 错误 2：在 env.sh 中初始化 starship

```bash
# env.sh（错误）
eval "$(starship init $SH)"  # ❌ 非交互式会失败
```

**问题：** Docker 构建时报错

**修正：** 移到 `inter.sh`

---

### ❌ 错误 3：在非交互式环境依赖 inter.sh 才有的能力

```bash
# 安装流程（错误）
source shells/common/inter.sh  # ❌ 非交互式直接 return
npm install -g <lsp>           # mise/npm 环境可能未就绪
```

**问题：** mise 环境未激活，npm 命令找不到

**修正：** 在 `env.sh` 中激活 mise（安装器依赖它），不要把交互式特性拉进非交互路径

---

## 总结

| 文件 | 职责 | 加载时机 | 示例内容 |
|------|------|----------|----------|
| **env.sh** | 基础环境 | 所有场景 | PATH, mise, 镜像源 |
| **fn.sh** | 功能函数 | 需要时 | fj, npm-cn, use-npm-mirror |
| **inter.sh** | 交互特性+补全 | 仅交互式 | starship, navi, **fzf 历史搜索增强**, **xd/codex/opencode completion** |
| **alias.sh** | 命令别名 | 仅交互式 | ll, gs |

> 工具安装不在此表：由 `setup.sh` 调用 `tool-installer` 完成（`tools.toml` + `manifest.toml`）。

**核心原则：**
1. **env.sh** - 所有场景都需要的基础配置
2. **inter.sh** - 仅交互式 shell 的特性配置
3. **安装逻辑** - 独立于 shell 配置层，交给 tool-installer

---

**文档结束**
