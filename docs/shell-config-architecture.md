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
├── install-functions.sh # 安装函数集合
├── inter.sh            # 交互式 shell 配置
└── alias.sh            # 命令别名
```

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
- **mise 环境激活**（提供 npm/node/go 等命令）
- 镜像源配置（Rust, Go 等）

**示例：**
```bash
# ✅ 应该放在 env.sh
export PATH="/usr/local/bin:$PATH"
export EDITOR='hx'
export RUSTUP_DIST_SERVER='https://rsproxy.cn'

# mise 提供 npm/node/go 等命令
eval "$(mise activate $SH)"
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
- 快捷键绑定（navi Ctrl+N, mcfly Ctrl+R）
- 命令增强（zoxide cd 增强）
- 历史搜索增强（mcfly）

**示例：**
```bash
# ✅ 应该放在 inter.sh
eval "$(starship init $SH)"     # prompt
eval "$(navi widget $SH)"       # Ctrl+N 快捷键
eval "$(zoxide init $SH)"       # cd 命令增强

# ❌ 不应该放在 inter.sh
export PATH="..."               # 应该在 env.sh
eval "$(mise activate $SH)"     # 应该在 env.sh
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

**加载时机：** 需要时手动 source

**包含内容：**
- 工具函数（字符串处理、文件操作）
- 辅助函数（日志输出、重试逻辑）

**示例：**
```bash
# fn.sh 提供通用函数
function log_info() { echo "[INFO] $1"; }
function retry_fn() { ... }  # 重试函数
```

---

### 4. install-functions.sh - 安装函数集合

**职责：** 提供系统工具和开发环境的安装函数

**加载时机：** 安装脚本中（如 setup.sh）

**包含内容：**
- 系统工具安装（apt、wget、curl）
- 开发工具安装（Neovim、Helix、Rust）
- LSP 语言服务器安装

**示例：**
```bash
# install-functions.sh 提供安装函数
function install-neovim() { ... }
function install-rust() { ... }
function install-typescript-lsp() { ... }
```

**依赖关系：**
- ✅ 依赖 `env.sh`（mise 环境已初始化）
- ✅ 不依赖 `inter.sh`（支持非交互式环境）

---

### 5. alias.sh - 命令别名

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

### 决策 1：mise activate 放在 env.sh

**原因：**
1. mise 提供的是**基础命令可用性**（npm/node/go）
2. 不是交互式特性，Docker/CI 同样需要
3. 与 PATH 环境变量性质相同

**对比：**
| 配置 | 位置 | 原因 |
|------|------|------|
| `mise activate` | env.sh | 提供命令可用性 |
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
- 在 `mise activate` **之后**（env.sh 已加载）
- 在其他交互式工具**之前**

---

### 决策 3：install-functions.sh 不依赖 inter.sh

**原因：**
1. 安装脚本常在非交互式环境运行（Docker、CI）
2. inter.sh 第一行就会 return
3. 但需要 mise 环境（由 env.sh 提供）

**正确依赖链：**
```
setup.sh
  ↓
source env.sh           # ✅ mise 环境已激活
source fn.sh            # ✅ 工具函数
source install-functions.sh  # ✅ 使用 npm/node 安装
# 不 source inter.sh    # ❌ 非交互式会 return
```

---

## 加载顺序

### 交互式 Shell（如打开终端）

```bash
~/.bashrc 或 ~/.zshrc
  ↓
source shells/common/env.sh      # 1. 基础环境（包括 mise）
source shells/common/fn.sh       # 2. 工具函数
source shells/common/alias.sh    # 3. 命令别名
source shells/common/inter.sh    # 4. 交互式配置
```

### 非交互式 Shell（如 Docker RUN）

```bash
setup.sh
  ↓
source shells/common/env.sh      # 1. 基础环境（包括 mise）
source shells/common/fn.sh       # 2. 工具函数
source shells/common/install-functions.sh  # 3. 安装函数
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

### ❌ 错误 3：install-functions.sh 依赖 inter.sh

```bash
# setup.sh（错误）
source shells/common/inter.sh  # ❌ 非交互式直接 return
source shells/common/install-functions.sh
```

**问题：** mise 环境未激活，npm 命令找不到

**修正：** 在 `env.sh` 中激活 mise

---

## 总结

| 文件 | 职责 | 加载时机 | 示例内容 |
|------|------|----------|----------|
| **env.sh** | 基础环境 | 所有场景 | PATH, mise, 镜像源 |
| **fn.sh** | 功能函数 | 需要时 | log_info, retry_fn |
| **install-functions.sh** | 安装函数 | 安装脚本 | install-rust, install-neovim |
| **inter.sh** | 交互特性 | 仅交互式 | starship, navi widget |
| **alias.sh** | 命令别名 | 仅交互式 | ll, gs |

**核心原则：**
1. **env.sh** - 所有场景都需要的基础配置
2. **inter.sh** - 仅交互式 shell 的特性配置
3. **install-functions.sh** - 依赖 env.sh，不依赖 inter.sh

---

**文档结束**
