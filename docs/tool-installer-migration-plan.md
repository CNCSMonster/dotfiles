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

> **注意**：语言运行时当前**不走** manifest 的 `manager = "mise"`，而是由 `tools.toml`
> 的 `mise-install@1` script job（`scripts/mise-install.sh`）统一执行 `mise install`，
> 版本单点锁定在 `mise/config.toml` 的 `[tools]`。manifest 中曾存在的 mise 条目
> 从未被 tools.toml 引用，已于 2026-10 清理；`mise` manager 类型仍被 tool-installer
> 支持，需要时可重新声明。

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
>
> **决策（2026-09-25）：Layer 2 的失败保持致命，不因"属于网络型可选产物"而降级为警告。**
> E2E 的职责是证明"装完整了"；降级恰恰是 yazi 插件在镜像列表为空时**从未被调用**
> 却长期无人发现的原因（见 `CHANGELOG.md`）。要 CI 变绿就修因，不要静音。
> 同理，`allow_fail` 的容忍只影响**是否中断**，不影响**是否可见**。

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
| 系统包（apt/brew）| 走 `scripts/lib/apt.sh`：有界超时、装包前源预检、失败归因（见 §4.3） |
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

### 4.3 系统包（apt）策略：有界、可见、可归因

`setup.sh`（Layer 1 运行时依赖预检）与 `scripts/install-system-packages.sh`（Layer 0）
共用 `scripts/lib/apt.sh`，这是本仓库 apt 执行策略的单一事实来源。

| 原则 | 实现 |
|------|------|
| **有界** | `Acquire::http(s)::Timeout=30`、`Acquire::Retries=1`、`DPkg::Lock::Timeout=60`（命令行参数，覆盖 `/etc/apt/apt.conf.d`），坏源与锁占用都在分钟内失败，不会把安装挂死 |
| **可见** | 不再使用 `-qq`；装包前打印 `📦 正在通过 apt 补齐...`，apt 输出原样透出 |
| **可归因** | `apt_sources_health_check` 在装包前逐源 5s 探测，先暴露不可达源；`apt_failure_hint` 把 apt 输出翻译成「原因 + 可直接执行的修复命令」（区分：无 sudo、锁占用、DNS 失败、源不可达/云内网源） |

> **2026-09 事故**：宿主把 apt 源指向腾讯云内网源 `mirrors.tencentyun.com`（解析到链路本地
> 地址 `169.254.0.3`），在非腾讯云内网环境是 TCP 黑洞。旧代码 `apt-get update -qq` 静默重试，
> `./setup.sh` 在 `🔍 缺少 Layer 1 运行时依赖` 之后挂起 4 分钟以上，最终只留下
> `❌ 运行时依赖安装失败`，没有任何可执行的修复指引。
>
> **边界**：`apt.sh` 只诊断、只提示，绝不改写 `/etc/apt` 下的用户源配置——换源属于用户决策，
> 脚本只打印一条可复制的修复命令。
>
> 同次修复：`DEBIAN_FRONTEND=noninteractive` 原先写在 `sudo` 之前，会被 `sudo` 的 `env_reset`
> 丢弃（改用 `sudo env VAR=... apt-get`）；`./setup.sh --install` 单跑时没有 sudo 缓存，原先
> 直接判死，现在交互终端会现场 `sudo -v` 提升一次。

**与 `apt-retry.conf` 的区别（刻意不同，不要互相对齐）**：Docker 构建复制该文件
（`Retries 5` / `Timeout 300`），面向「CI 偶发网络抖动，宁可久等也要成功」；本机安装走
fail-fast，「宁可快速失败也要给出归因」。

**接入范围（2026-09 已完成）**：仓库内所有裸 `apt-get` 调用点都已走本库——
`setup.sh`（python3 引导 + Layer 1 运行时依赖预检）、`scripts/install-system-packages.sh`、
`scripts/install-wezterm.sh`、`scripts/install-fonts.sh`、`scripts/setup-rootless-docker.sh`、
`scripts/llvmup`。两条约定：

- **调用形态**：同目录 `source lib/apt.sh`，再用 `apt_run <sudo 前缀> <apt-get 参数>`；
  各脚本原有的失败语义（致命 / 跳过 / 警告）不变，apt 只是换成有界且可归因的执行方式。
- **健康预检时机**：只在会执行 `apt-get update` 的路径上跑 `apt_sources_health_check`
  （setup.sh、install-system-packages、install-wezterm、setup-rootless-docker）；纯 install
  的路径（install-fonts）靠失败归因即可，不多花一次探测。

`llvmup` 只有一份真实文件 `scripts/llvmup`；`shells/scripts/llvmup` 是指向它的相对符号链接
（PATH 入口，部署后经 `~/.config/shells/scripts` 调用）。历史上后者是**复制件**，幂等 skip
修复（`513573d`）只落在 `scripts/` 那份，两份已漂移，2026-10-03 合并为链接——这是仓库里
唯一一对同名重复脚本。调用时 `BASH_SOURCE` 可能是链接本身，因此用 `readlink -f` 解析真实
路径再定位库；找不到库时**显式**打印警告再退回无界模式，不静默降级。

**tool-installer 侧的同一套策略（Step 1，2026-10-03）**：策略有两个实现点，因为它们服务
不同的启动阶段——**稳定期用 Python，自举期用 shell**：

| | 位置 | 何时生效 |
|---|------|---------|
| Python | `tool_installer/managers/apt_policy.py` | tool-installer 可用之后的所有 apt 调用 |
| shell | `scripts/lib/apt.sh` | 引导 python3、Layer 1 门禁——它们跑在 tool-installer 启动**之前**，无法依赖工具自己（鸡生蛋） |

- `AptManager` 覆写 `install()`：装包前源预检（只提示不阻断）→ 带有界参数执行 → 回显 apt
  输出 → 失败归因。它此前是**零使用、零测试**的空壳（`subprocess.run` 无 timeout，与 shell
  改造前一样会挂死），`manifest.toml` 里至今没有 `manager = "apt"` 条目。
- `SubprocessRunner` 给**所有** manager 加了 3600s 兜底 timeout，并把 `TimeoutExpired` 转成
  `InstallationError`——裸超时会让 executor 走 traceback，绕过 `allow_fail` 的汇总处理。
- 两侧数值（30s / 1 次 / 60s）必须一致，改一侧同步另一侧；回归测试
  `tool-installer/tests/test_apt_policy.py`（21 例，离线，跑在 CI 的 unittest discover）。
- **`DEBIAN_FRONTEND` 已统一（2026-10-03 拍板）**：两侧都设 `noninteractive`——
  拍板原话是"无人加 yes，那对 dpkg 就使用不问的方式"：无人值守下 dpkg 提问会挂起，
  而 debconf 的默认值就是预期答案；**dpkg 的提问是机器对机器的配置协商，不归授权
  三档管**（三档管的是"动用户已有东西"的决策）。变量必须作为 `env` 子命令跟在
  sudo **之后**——sudo 默认 env_reset 会丢掉普通环境变量（Step 1 时踩过）。
- **Step 2（分两批）**：批次 1 = 非预期问题的授权与三档判定（已完成，见下）；批次 2 =
  把 `scripts/install-system-packages.sh` 的清单迁到声明式 `manager = "apt"`
  （已完成，见下）。`BrewManager` 仍零使用——macOS 分支经调研后保留 script，原因是
  22 个 Linux 专属包在 brew 侧没有对应名，按包拆条目会让 macOS 策略段无从写起。

**Step 2 批次 1（2026-10-03 已完成）：非预期问题的授权与三档判定**

拍板的规则（用户决策）：**预期操作不问；非预期状态问；传 `--yes` 则一个都不问；
没传又没人可问时，不擅自决定、也不中断。**

| 状态 | 性质 | 无 `--yes` 且有 TTY | `--yes` | 无 TTY 且无 `--yes` |
|---|---|---|---|---|
| 下载安装、版本对齐 | 预期 | 不问（apt 恒带 `-y`） | 不问 | 不问 |
| 命令已存在但非 apt 装的 | 非预期 | 问，**默认 N** | 直接过 | 跳过该工具 + 结束汇总 |
| 配置文件被本地改过 | 非预期 | 问（保留为默认） | **仍保留用户文件**，覆盖需显式 `--force-confnew` | 保留用户文件 |
| `sudo` 密码 | 认证≠决策 | 问 | **照样问** | 报错不挂起 |

实现：

- `tool_installer/interaction.py`：`Decision` 三态（YES / NO / UNAUTHORIZED），默认答案 **N**。
  三态不能压成布尔——"拒绝"与"没人能答"是两回事，后者必须交给汇总。
- `tool-installer install --yes` → `TOOL_INSTALLER_ASSUME_YES=1`（与 `TOOL_INSTALLER_STRICT`
  同一传播约定：环境变量，manager 在任何深度都能读到，调用方不会忘记层层传参）。
- `apt_policy.unexpected_binary_state()`：`command -v` 视角 × `dpkg` 视角交叉判定——
  "命令在、包不在" = 会静默装出第二份实现。manifest 为 `apt` 新增可选 `bin` 字段
  （包名与命令名不同时声明）。
- `AuthorizationRequired(InstallationError)` + executor 专门分支：**缺授权永不中断整轮安装**
  （跳过该工具继续装其余的，两种模式都打印汇总、**退出码都不受影响**——“没人可问”
  不是失败，strict 只管真失败）；它必须在
  `InstallationError` 之前捕获，否则会掉进 `allow_fail` 分支——“没人能授权”与“允许失败”
  是两件事。
- 探测 fail-open、执行 fail-closed：`_dpkg_installed()` 的探测失败（超时/被杀）当作"未装"
  继续，把决定权交给 `apt install`——后者的失败会被归因。辅助查询不该有能力杀掉整轮安装。

**已核实的边界（2026-10-03，L1 实测 + L2 手册）**：`--yes` 管不到 sudo 认证。上游只有
`-n`（不提示直接失败，实测 `sudo: interactive authentication is required`）、`-A`/`SUDO_ASKPASS`、
`-S`（都是换方式取密码）与 sudoers 的 `NOPASSWD`（管理员配置，非调用参数），**不存在"用调用方
参数完成授权"的机制**。另：Ubuntu 26.04 的 `/usr/bin/sudo` 已是 **sudo-rs**（本机 0.2.13，
上游 0.2.15 @2026-08-31），其凭证缓存默认 **15 分钟**——长构建超过 15 分钟没有 sudo 调用后
会再要密码，无 TTY 时由 `attribute_failure` 归因提示 `sudo -v && ./setup.sh`。

回归测试：`tool-installer/tests/test_authorization.py`（20 例，离线）。

**Step 2 批次 1.5（2026-10-03 已完成）：apt 执行时机的两处不一致**

批次 1 复盘时发现 shell 与 Python 侧的执行语义不同步：

| | `scripts/lib/apt.sh`（shell） | `AptManager`（修复前） |
|---|---|---|
| 包索引刷新 | 每轮开头 `apt-get update` 一次，多包共用 | **从不 update**（索引陈旧时 `Unable to locate package`，且 `attribute_failure` 归因不到这一类） |
| 源健康预检 | 每轮一次 | 在 `install` 里**逐项**跑（每项最多 源数×5 秒，19 包 = 19 轮） |
| 输出 | tee 实时可见 | install 实时（未变），update 新增同样不 capture |

修法：新增 `Manager.preflight(items)` 钩子（每轮一次，executor 在逐项循环**之前**按
本轮用到的 manager 分组调用；`ScriptManager`/`GithubReleaseManager` 为 no-op），
`AptManager` 在其中 update + 源预检。update 失败只警告继续——索引陈旧 ≠ 装不上
（apt 仍用已缓存的索引），真正的失败交给 install 侧归因，不被全局预检越俎代庖。

防漂移：`test_bounded_numbers_match_scripts_lib_apt_sh` 直接读 `scripts/lib/apt.sh`
断言 `Timeout=30 / Retries=1 / Lock=60` 等于 `apt_policy.APT_*`——数值两处各写一遍，
靠"记得同步"早晚会失守，现在改一侧不改另一侧会点名。

**Step 2 批次 2（2026-10-03 已完成）：系统包清单声明式化**

调研先修正了原计划的两处预设：

1. **shell 侧不需要同步三档**：`apt.sh` 的调用方（setup.sh 依赖预检、wezterm/fonts/
   rootless-docker/llvmup）全是"装依赖"的预期操作，没有非预期判定；唯一带
   "已有则跳过"判定的 `install-system-packages.sh` Linux 分支随迁移消失。授权三档是
   AptManager 的特性——只有 check/install 分离的组件才会遇到 dpkg 与 command 两个
   视角的差异。
2. **形态选"多包 pkg 字段"而非每包一条**：manifest 的 tool 必须每个平台都有策略段，
   而 22 个 Linux 专属包（build-essential、libssl-dev…）在 brew 侧没有对应名，按包拆
   条目会让 macOS 段无从写起。`pkg` 保持 str（空白分隔的清单），契约不改。

改动：

- `manifest.toml [system-packages.linux]` → `manager = "apt"` + 26 包清单（与迁移前
  `for pkg in` 原文逐字 diff 核对）；macOS 保留 script（Homebrew 引导 + 4 包，行为不变）。
- `tools.toml`：`system-packages@1` → `@latest`。`@1` 会被 check 当成 pin 版本与 dpkg
  版本比对，永远不等 → 每轮判未满足重装。
- `AptManager`：多包 check（任一缺失即整组重装，与旧 `missing` 批量同语义）；
  `install_command` 展开多包为一个事务；冲突检测逐包收集、**一次问询**（逐包问会把
  用户按在终端里答 26 遍）；pin 限单包，多包 + pin 显式报错。
- **latest 语义裁决**：apt 的 latest = "装了即满足"，不比 apt candidate。否则
  `./setup.sh` 每轮把基线包升级到 candidate（`apt-get install` 不带 pin 会升级），而旧
  清单从来只判定存在性。要对齐版本用 `name@版本`（走精确比对），强制重装用
  `force = true`。`AptManager.check` 此前零测试，迁移前补 9 例锁住该契约。
- **发现旧 SOP 提取本身是坏的**：`grep -oP '\b[a-z][a-z0-9-]{2,}\b' | grep -vwE 'for|pkg'`
  漏掉 `g++`（`+` 不在字符类）与 `pkg-config`（被 `-w pkg` 误删）——声明清单与被核查
  清单本就不同源。改为用 tool-installer 自己的 parser 读 manifest，26 包全量提取。

验证：`check-manifest-platforms.sh` 4/4 平台、121 测试、dry-run 输出
`version=latest manager=apt`、清单逐字 diff、`bash -n`。

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
