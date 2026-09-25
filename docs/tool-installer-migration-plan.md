# 工具安装管理迁移方案

**文档版本：** 1.0
**更新日期：** 2026-06-04
**目的：** 将工具安装从 monolithic shell 函数迁移到声明式三层架构，明确 vendor 策略和各层职责边界

---

## 1. 背景

迁移前，`setup.sh` + `shells/common/install-functions.sh`（现已删除）中硬编码了 45+ 个工具的 shell 安装逻辑，存在以下问题：

- **难以维护**：新增/修改工具需要写 shell 函数，重复代码多
- **跨平台困难**：Linux/macOS 分支逻辑散落在各处
- **版本管理混乱**：`latest` 和固定版本混用，不可复现
- **CI 脆弱**：网络波动导致安装失败，无统一 fallback 策略

---

## 2. 目标架构

迁移到 **三层声明式架构**，由 `setup.sh` 统一编排：

```
┌─────────────────────────────────────────┐
│  setup.sh（编排入口）                │
│  do_bootstrap → do_deploy → do_install  │
└─────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌─────────┐   ┌──────────┐   ┌──────────┐
│ Layer 0 │   │ Layer 1  │   │ Layer 2  │
│Bootstrap│   │tool-     │   │ Post     │
│         │   │installer │   │ Scripts  │
└─────────┘   └──────────┘   └──────────┘
```

### 2.1 Layer 0: Bootstrap

**职责：** 安装 tool-installer 本身及其绝对必要的前置依赖

**包含：**
- 系统包（python3, curl, gh, build-essential 等）
- GitHub CLI 登录（环境变量或交互式）
- **tool-installer 本体**（Python zipapp，从 vendor 复制到 `~/.local/bin`）

**明确不包含：**
- ❌ cargo-binstall 或其他任何工具的二进制
- ❌ Rust 工具链
- ❌ 任何可由 Layer 1 自行获取的工具

### 2.2 Layer 1: 声明式工具安装

**职责：** 读取声明式配置，安装所有开发工具

**输入：**
- `tools.toml` — 定义模块、分组、依赖关系
- `manifest.toml` — 定义每个工具的安装策略（manager、版本、参数）

**支持的 Manager 类型：**

| Manager | 说明 | 示例工具 |
|---------|------|----------|
| `github-release` | 下载预编译 release | neovim, helix, starship |
| `cargo-install` | Cargo 安装（支持 binstall_first）| bat, eza, fd-find |
| `mise` | 语言运行时版本管理 | go, node, zig |
| `npm` / `pip` | 包管理器 | LSP 服务器 |
| `script` | 自定义脚本 | rustup-install |

**关键设计：**
- `binstall_first = true` 时，优先尝试 `cargo-binstall` 下载预编译二进制，失败自动 fallback 到 `cargo install`
- 所有版本必须 pin，禁止 `latest`
- 跨平台差异在 `manifest.toml` 中用 `[tool.linux]` / `[tool.macos]` 声明，不写死逻辑

### 2.3 Layer 2: 后置配置

**职责：** 依赖 Layer 1 已安装工具的后续配置（`scripts/layer2-post.sh`）

**包含：**
- Helix runtime（themes / queries / tutor，需 helix 已安装）
- Yazi 插件（`ya pkg install`）
- LLVM / clangd（`scripts/llvmup`，仅 Linux）
- 字体缓存刷新（`fc-cache`）
- git 全局配置 include 优先级修复（`~/.gitconfig` → XDG 配置）
- 默认 shell 设为 zsh（`chsh`）

> **不包含**：字体安装与 LSP 服务器安装——二者分别是 Layer 1 的 `fonts` 与
> `lsp-servers` 模块，由 `tools.toml`/`manifest.toml` 声明式管理。本节的早期版本
> 把两者误列为 Layer 2 的职责，与实现不符。
>
> **返回码契约**：每个步骤 `0` = 成功或不适用（打印 ⚠️ 说明），`1` = 应当完成但没完成
> （打印 ❌）。`main` 汇总失败项；有失败则整个脚本返回 `1`，让 `setup.sh` 不再打印
> "全部安装完成"。历史上这些步骤用 `|| true` 吞掉错误后仍无条件打印 ✅，是"假成功"的来源。

---

## 3. Vendor 策略

> **本节是 vendor 政策与清单的唯一来源。**
> `scripts/vendor/README.md` 只保留 `rustup-init.sh` 的更新 SOP，不再重复准入条件与清单。
> 历史上两份文档各写一份清单，已经漂移：那份 README 曾把 `vendor/xdotter` 写进"已移除"
> 表，而文件当时仍在库、且被 `setup.sh` 使用。

### 3.1 准入条件

Vendor 目录只存放满足以下条件**之一**的资源；三条之外一律不入库：

| 条件 | 说明 | 示例 |
|------|------|------|
| **自定义工具** | 无标准分发渠道，必须自行构建/打包 | `tool-installer`（Python zipapp）|
| **供应链安全关键脚本** | 需要人工审查，避免 `curl \| sh` | `rustup-init.sh` |
| **自举依赖** | 上层工具依赖它才能工作，**且无法通过上层工具自身获取** | `tool-installer` 本身、`tomli` |

**判定只看一个问句：「tool-installer 能不能自己把它装出来？」**
能 → 必须交给 manager；不能 → 才可入库。**与它在流程里多早被用到无关。**

> **反例（务必记住）**：`xdotter` 曾以"部署阶段就需要它 + 慢网络"为由入库，但两条都不构成
> 准入理由——① `manifest.toml` 里有它的 `github-release` 配置，tool-installer 可以自己装；
> ② "网络不可靠"属于 §4 的范围，§3.2 明确要求**在工具内部解决**（timeout / retry / 镜像
> fallback），而不是 vendor 绕过。该二进制由提交 `60ddef7` 引入，2026-09-25 已按政策移除。

> **维护方式：** tool-installer 源码在本仓库 `tool-installer/` 目录内维护（事实 fork，无上游同步义务）。
> 修改源码后必须运行 `./scripts/build-tool-installer.sh` 重建 `vendor/tool-installer` 并一并提交——
> setup.sh 按字节比较判断是否更新已安装副本，漏跑脚本会导致改动不生效。
> 提交前后可用 `./scripts/check-tool-installer-sync.sh` 守卫一致性（CI 的
> "Vendor zipapp in sync" job 每次都会跑，zip 时间戳不参与比较）。
> 严格模式：`TOOL_INSTALLER_STRICT=1` 时 allow_fail 工具在安装结束时汇总失败清单并以
> 非零退出；CI 三条工作流与 Dockerfile 默认开启。
> **非严格模式（`setup.sh` 默认，从不设置该变量）同样会汇总失败清单**，只是仍以 0 退出——
> 静默容忍是 `ci-issue-tracker.md` #7/#8 两个工具被无谓重装数月的直接原因，因此"可见性"
> 与"是否中断"被拆成两个独立开关。

### 3.2 明确不 Vendor 的内容

以下类型**禁止**放入 vendor：

- ❌ **主流生态工具的二进制**（cargo-binstall, xdotter 等）
  - 这些工具有标准分发渠道（GitHub releases, crates.io）
  - 应由 Layer 1 的对应 manager 自行获取
  - Vendor 二进制增加维护负担（跨平台、版本更新、架构兼容）

- ❌ **可由 tool-installer 自行下载的工具**
  - tool-installer 的 `github-release` manager 已支持镜像回退，且回退**以 SHA256
    校验为准**：候选源必须同时"传得下来"和"校验通过"才算成功，镜像返回错误内容
    会继续尝试下一个源（官方直连在候选列表末位）
  - `_download_binstall` 已实现 cargo-binstall 的自举下载
  - 预装这些工具会掩盖 tool-installer 自身路径的 bug

- ❌ **临时 workaround**
  - 网络问题的修复应在工具内部解决（timeout、retry、镜像 fallback）
  - 不应通过 vendor 二进制绕过

### 3.3 Vendor 清单

项目有**三个** vendor 域，本节全部登记；路径必须写全——历史上正是"`vendor/` 与
`scripts/vendor/` 混为一谈"造成了两份清单不一致。

| 路径 | 类型 | 准入条件 | 状态 |
|------|------|----------|------|
| `vendor/tool-installer` | 自定义 zipapp | 自举依赖 | ✅ 保留 |
| `scripts/vendor/rustup-init.sh` | 审查脚本 | 供应链安全关键脚本 | ✅ 保留 |
| `tool-installer/tool_installer/vendor/tomli/` | Python 库 | 自举依赖（Python < 3.11 无 `tomllib`，而解析 TOML 是 tool-installer 工作的前提） | ✅ 保留 |
| `scripts/vendor/cargo-binstall-install.sh` | 脚本 | 不满足任何准入条件 | ✅ **已移除**（2026-09-25）：唯一调用方 `shells/common/install-functions.sh` 已在迁移中删除（`ff54dd5`），此后零引用，属孤儿文件 |
| `vendor/xdotter` | 主流二进制 | 不满足任何准入条件（见 §3.2） | ✅ **已移除**（2026-09-25） |

### 3.4 状态语义与守卫

状态列只允许四种取值，避免"决定"与"事实"再次混淆：

| 状态 | 含义 |
|------|------|
| ✅ 保留 | 在库，且满足 §3.1 某一条 |
| ✅ 已移除 | 已不在库（须注明日期） |
| ⚠️ 待处置 | 在库但无准入理由，或疑似死文件（须注明待决问题） |
| 🚫 例外 | 在库但**不**满足 §3.1 —— 必须附批准记录与复审条件，不得静默存在 |

**守卫规则**：若某个 vendor 二进制是 `manifest.toml` 里某个**受管工具**的副本（即 tool-installer
本可自行获取的东西），则必须有 CI 断言它与该工具的 `sha256`（`tools.toml` 钉版的产物）一致；
否则视为准入未完成。

`vendor/tool-installer` 不适用该规则——它没有上游分发包，靠
`scripts/check-tool-installer-sync.sh` 保证"源码 ⇄ 产物"一致，这是另一个维度的一致性。

现状缺口（已知）：除 `vendor/tool-installer` 外，清单里没有任何条目有 CI 断言。
`vendor/xdotter` 当年与 `tools.toml` 钉版、`manifest.toml` sha256 三者恰好一致，
但**没有任何机制保证它们继续一致**，这正是它必须移除、而不是"保留并祈祷"的原因之一。

---

## 4. 网络问题处理原则

### 4.1 分层责任

| 层级 | 责任 |
|------|------|
| Layer 0 | 保证 tool-installer 可安装，不处理工具下载 |
| Layer 1 | 负责所有工具的网络获取，内置 retry、timeout、镜像 fallback |
| Manager 内部 | 每个 manager 实现自己的网络容错（如 github-release 的 mirror 列表） |

### 4.2 cargo-binstall 的自举

tool-installer 的 `cargo-install` manager 已实现 `_ensure_binstall`：

1. 检查 PATH 中的 `cargo-binstall`
2. 检查 `~/.cargo/bin/cargo-binstall`
3. 尝试从 GitHub releases 下载
4. 以上全部失败 → fallback 到 `cargo install cargo-binstall`

**Layer 0 不应干预此流程。**预装 cargo-binstall 不仅多余，还会：
- 掩盖 `_ensure_binstall` 的验证 bug
- 导致测试环境无法覆盖真实 fallback 路径
- 增加 vendor 维护负担

---

## 5. 实施步骤（迁移期记录）

> §5–§7 是迁移当时的实施记录与复盘，其中提到的 `layer0-bootstrap.sh` 等文件已不存在。
> **当前 vendor 政策与清单以 §3 为准**，本节及之后不作为规范。

### Phase 1: 修复当前分支的阻塞问题

1. **移除 vendor/cargo-binstall**
   - `git rm vendor/cargo-binstall`
   - 从 `layer0-bootstrap.sh` 删除 cargo-binstall 复制逻辑

2. **修复 tool-installer 的 binstall 验证 bug**
   - `tool_installer/managers/commands.py` line 439
   - `[binary, "--version"]` → `[binary, "-V"]`
   - 重新打包 `vendor/tool-installer`

3. **验证 CI 通过**
   - 确保 `binstall_first = true` 生效
   - cargo 工具从预编译二进制安装，不再源码编译

### Phase 2: 清理违规 vendor（已完成）

1. **移除 `vendor/xdotter`** ✅ 2026-09-25
   - 结论：执行 §3.2，不开例外。该二进制的唯一价值是"慢网络下的兜底"，而 §4 要求这类
     问题在工具内部解决；`github-release` 的回退已改为**以 SHA256 校验为准**并有回归测试
   - 已删除 `vendor/xdotter`，并移除 `setup.sh::ensure_xdotter()` 的第三级回退

2. **修正 vendor 文档** ✅ 2026-09-25
   - `scripts/vendor/README.md` 降级为 `rustup-init.sh` 的更新 SOP，不再重复政策与清单
   - 政策与清单统一到本文档 §3

### Phase 3: 文档补全

1. 本文档作为设计基线
2. 更新 `CONTRIBUTING.md` 中关于 vendor 的指引
3. `CHANGELOG.md` 记录迁移完成

---

## 6. 验证方式

| 验证项 | 命令/方法 |
|--------|-----------|
| 工作树无未提交更改 | `git status` |
| 无违规 vendor 二进制 | `ls vendor/` 只有 `tool-installer`（权威清单见 §3.3） |
| CI 通过（ubuntu + macos）| `gh run list --branch feat/tool-installer-migration` |
| cargo 工具使用预编译 | 日志中无大量 `Compiling` 输出，安装时间 < 5 分钟 |
| binstall_first 生效 | 日志中出现 `cargo-binstall` 下载/安装输出 |

---

## 7. 附录：当前问题复盘

### 7.1 CI 超时事件（Run 26939026915）

**现象：** `setup.sh` 在 ubuntu-latest 上运行 1 小时后超时取消。

**表面原因：** 29 个 cargo 工具全部从源码编译，`CARGO_BUILD_JOBS=2` 下耗时过长。

**根因链：**
1. `layer0-bootstrap.sh` vendor 了 cargo-binstall 到 `~/.cargo/bin`
2. tool-installer 的 `_ensure_binstall` 尝试验证 `~/.cargo/bin/cargo-binstall`
3. 验证调用 `cargo-binstall --version`，但 vendor 的 v1.19.1 不支持无参 `--version`
4. 验证失败 → tool-installer 认为 cargo-binstall 不可用
5. 所有 `binstall_first = true` 失效 → 全部 fallback 到 `cargo install` 源码编译

**修复方向：**
- 移除 vendor cargo-binstall（本就不该存在）
- 修复 tool-installer 验证参数（`--version` → `-V`）
- 让 tool-installer 的自举机制正常工作
