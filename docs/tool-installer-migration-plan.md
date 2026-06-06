# 工具安装管理迁移方案

**文档版本：** 1.0
**更新日期：** 2026-06-04
**目的：** 将工具安装从 monolithic shell 函数迁移到声明式三层架构，明确 vendor 策略和各层职责边界

---

## 1. 背景

当前 `setup.sh` + `shells/common/install-functions.sh` 中硬编码了 45+ 个工具的 shell 安装逻辑，存在以下问题：

- **难以维护**：新增/修改工具需要写 shell 函数，重复代码多
- **跨平台困难**：Linux/macOS 分支逻辑散落在各处
- **版本管理混乱**：`latest` 和固定版本混用，不可复现
- **CI 脆弱**：网络波动导致安装失败，无统一 fallback 策略

---

## 2. 目标架构

迁移到 **三层声明式架构**，由 `setup-new.sh` 统一编排：

```
┌─────────────────────────────────────────┐
│  setup-new.sh（编排入口）                │
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

**职责：** 依赖 Layer 1 已安装工具的后续配置

**包含：**
- LSP 服务器配置
- 字体安装
- 其他需要工具已存在才能执行的配置

---

## 3. Vendor 策略

### 3.1 准入条件

Vendor 目录只存放满足以下条件之一的资源：

| 条件 | 说明 | 示例 |
|------|------|------|
| **自定义工具** | 无标准分发渠道，必须自行构建/打包 | `tool-installer`（Python zipapp）|
| **供应链安全关键脚本** | 需要人工审查，避免 `curl \| sh` | `rustup-init.sh` |
| **自举依赖** | 上层工具依赖它才能工作，且无法通过上层工具自身获取 | `tool-installer` 本身 |

### 3.2 明确不 Vendor 的内容

以下类型**禁止**放入 vendor：

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

### 3.3 当前 Vendor 清单

| 文件 | 类型 | 准入理由 | 状态 |
|------|------|----------|------|
| `vendor/tool-installer` | 自定义 zipapp | 无标准分发渠道，Layer 0 必须预装 | ✅ 保留 |
| `vendor/rustup-init.sh` | 审查脚本 | 供应链安全，避免 `curl \| sh` | ✅ 保留 |
| `vendor/cargo-binstall` | 主流二进制 | **违反策略**，应由 tool-installer 自行获取 | ❌ 移除 |
| `vendor/xdotter` | 主流二进制 | **违反策略**，应由 github-release manager 获取 | ❌ 移除 |

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

## 5. 实施步骤

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

### Phase 2: 清理违规 vendor

1. **评估 vendor/xdotter**
   - xdotter 已有 GitHub release manager 配置
   - 检查 Docker build 是否仍需要 vendor fallback
   - 如不需要，移除

2. **更新 vendor/README.md**
   - 明确准入条件和禁止清单
   - 更新当前 vendor 清单

### Phase 3: 文档补全

1. 本文档作为设计基线
2. 更新 `CONTRIBUTING.md` 中关于 vendor 的指引
3. `CHANGELOG.md` 记录迁移完成

---

## 6. 验证方式

| 验证项 | 命令/方法 |
|--------|-----------|
| 工作树无未提交更改 | `git status` |
| 无违规 vendor 二进制 | `ls vendor/` 只有 `tool-installer` + `rustup-init.sh` |
| CI 通过（ubuntu + macos）| `gh run list --branch feat/tool-installer-migration` |
| cargo 工具使用预编译 | 日志中无大量 `Compiling` 输出，安装时间 < 5 分钟 |
| binstall_first 生效 | 日志中出现 `cargo-binstall` 下载/安装输出 |

---

## 7. 附录：当前问题复盘

### 7.1 CI 超时事件（Run 26939026915）

**现象：** `setup-new.sh` 在 ubuntu-latest 上运行 1 小时后超时取消。

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
