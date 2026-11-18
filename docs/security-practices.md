# 安全实践文档

本文档记录本项目中采用的安全实践和防御措施。

---

## 下载文件完整性校验

### SHA256 哈希校验

`github-release` 安装链对下载的二进制文件和压缩包进行 SHA256 校验，拒绝与仓库中已审查摘要不一致的文件。该保证不自动覆盖 npm、Python、系统包或脚本安装器。它可以检测：

- **中间人攻击** - 网络传输过程中文件被篡改
- **DNS 劫持** - 被重定向到恶意下载源
- **官方源被入侵** - 上游发布被篡改的文件
- **传输错误** - 网络问题导致的文件损坏

### 实现

SHA256 在 `manifest.toml` 中按工具、按平台声明，由 `tool-installer` 下载后校验：

```toml
[helix.linux.x86_64]
sha256 = "3f08e63ecd388fff657ad39722f88bb03dcf326f1f2da2700d99e1dc40ab2e8b"
```

当前所有 `github-release` 条目均带 `sha256` 声明。

### 更新哈希值

升级工具版本时，同步更新 `manifest.toml` 对应条目的 `sha256`：

```bash
# 计算新版本的 SHA256
curl -sL <download-url> | sha256sum

# 或先下载再计算
curl -sL -o /tmp/test.tar.xz <download-url>
sha256sum /tmp/test.tar.xz
```

---

## 不依赖外部插件仓库

### 风险说明

使用第三方版本管理插件（如 asdf/mise 插件）存在以下风险：

1. **恶意代码注入** - 插件脚本以用户权限执行，可访问所有文件
2. **仓库被接管** - 原作者离职或仓库被恶意 transfer
3. **无版本锁定** - 插件更新后可能引入恶意代码
4. **无哈希校验** - asdf 插件不支持下载文件的完整性验证

### 本项目方案

本项目**不依赖外部版本管理器插件仓库**（asdf/mise plugin 一类），采用以下方式：

- 安装逻辑集中在 `tool-installer`（Python 包）与声明式 `manifest.toml` / `tools.toml`
- 从官方源下载（GitHub Releases、官方镜像）
- 固定版本号，避免意外升级
- 对关键工具进行 SHA256 校验

### 对比

| 安装路径 | 版本与完整性边界 |
|----------|------------------|
| `github-release` | 顶层版本固定，下载工件与仓库中的 SHA256 比对 |
| Cargo / npm / Python | 顶层版本固定；不能据此推断所有间接依赖和安装脚本都已锁定 |
| apt / Homebrew / rustup 通道 | 依赖软件源或通道的信任机制，不保证跨时间得到相同内容 |
| script | 逐个审查安装脚本及其下载来源 |

> 边界说明：shell 插件（zcomet 管理的 `zsh-completions` 等）从 GitHub 拉取但钉死版本，且只参与 shell 配置层，不进入工具安装链。

---

## 固定版本号

### 原则

安装的工具默认使用**固定版本号**，而不是 `latest` 或 `stable`。

例外及其语义是显式设计，写在 `tools.toml` 中：

| 例外 | 写法 | 语义 |
|------|------|------|
| 系统包 | `system-packages@latest` | apt 侧“装了即满足”，不比 candidate、不隐式升级 |
| Rust 工具链 | `rust@stable` | moving channel，跟随 rustup stable |
| 脚本型安装任务 | `mise-install@1` | 任务型条目，`@1` 为迭代号 |

### 原因

1. **减少漂移** - 顶层工具版本保持一致；完整可复现还需要锁定间接依赖、平台、运行时和安装脚本下载物
2. **稳定性** - 避免新版本的回归问题
3. **安全性** - 明确知道安装的是什么版本

### 实现

```toml
# 好的做法 - tools.toml 中钉版
"helix@25.07.1" = "Helix 编辑器"

# 避免 - 未经设计的 latest（例外场景按上表语义显式声明）
```

---

## 用户级安装

### 原则

优先使用用户级安装（`~/.local/bin`、`~/.cargo/bin`），而不是系统级安装。

### 优点

1. **最小权限** - 不需要 root/sudo 权限
2. **隔离性** - 不影响系统其他用户
3. **易清理** - 删除用户目录即可完全移除

---

## 临时文件清理

### 原则

下载和安装过程中产生的临时文件必须及时清理。

### 实现

```bash
# 安装完成后清理
rm -rf "$HELIX_TMP" "$DEST"
```

---

## 安全更新流程

当需要更新工具版本时，遵循以下流程：

1. **审查变更** - 阅读上游的 Release Notes 和 Changelog
2. **获取哈希** - 下载新版本并计算 SHA256
3. **更新脚本** - 修改版本号和哈希值
4. **测试验证** - 在干净环境中测试安装流程
5. **提交记录** - Commit message 说明更新原因

---

## 工具二进制升级保护

`github-release` 与 Cargo 工具升级在覆盖既有程序前，会把旧文件、符号链接目标或旧共享目录保存到 `~/.local/state/dotfiles/tool-upgrade-backup/<工具>-<时间戳>-<pid>-<随机后缀>/`，并写入含绝对路径和摘要的 `manifest.json`。发布失败时自动还原；成功后备份默认保留，可凭 receipt 人工回滚，不会自动清理。首次安装不产生备份。

版本探测无法确认已有程序的身份时，安装器返回检查错误并保留原文件，不自动覆盖；仅当身份可确认且版本不同，才走升级。人工设置 `force = true` 仍会跳过检查，因此使用前应确认目标来源。

目录型发布不是单系统调用级原子，依赖备份在失败时还原；符号链接只保存链接目标，不跟随读取其指向内容。若无法确定可靠的备份根目录，升级必须失败关闭，而不是无备份覆盖。

## 显式哈希锁安装模式

安装器支持逐工具启用 `npm-locked` / `python-locked`。两种策略声明 `pkg`、manifest 目录内的相对 `lock` 路径，以及 `bin`（单入口）或 `bins`（多入口，优先）；工具版本仍来自 tools selector。锁校验在安装计划阶段执行，执行前再次核对摘要。

正式清单使用**全平台锁**：一份锁同时服务 `linux/x86_64`、`linux/aarch64`、`macos/aarch64`。生成器对每个目标平台各解析一次（npm 用 `os`/`cpu` 配置覆盖，uv 用 `--python-platform`），三份结果必须完全一致才写入 `platforms` 列表与 `resolution = "universal"`；任一平台声明不同或解析结果不同都会拒绝生成，而不是拿宿主锁冒充其它平台。平台守卫要求锁的 `platforms` 覆盖全部三个平台，并叠加 npm `os`/`cpu` 工件覆盖检查。

- npm 接受受限 package-lock v2/v3：根依赖必须精确匹配钉版，列出的工件须有 HTTPS 地址和合法 SHA256/SHA512 integrity。安装使用隔离目录中的 `npm ci --ignore-scripts --no-audit --no-fund`，不运行生命周期脚本。
- Python 接受每个包单物理行的 `name==version --hash=sha256:...`，不接受 include、URL、markers 或 extras。它使用当前解释器创建独立 venv，再以 `uv pip install --require-hashes --only-binary :all:` 安装，不使用源码构建或下载解释器。
- 新安装使用独立 generation，仅在成功后发布声明的 `bin` 或 `bins` 全部入口。已有外来文件、目录、悬空或未认证软链接一律拒绝覆盖，force 不绕过；多入口中任一验证或发布失败会整体回滚，不留半套新命令；失败保留旧入口，旧 generation 不自动删除。
- check 比对锁摘要、本地 receipt、平台及入口，不运行已安装包的版本命令。receipt 是本机所有权记录，不是数字签名，不能抵抗同用户恶意篡改。

锁维护命令为 `python3 scripts/update-tool-locks.py --module <模块> --tool <逻辑工具名> --check`，默认只读离线校验；指定 `--generate` 才解析注册表元数据，已有文件还需 `--force` 才原子替换。它只接受已声明 locked 策略的工具，并要求同一工具的三个平台声明完全一致；遇到无法保留的 markers、extras 或平台相关闭包会拒绝，而不是偷偷删除条件。生成过程不安装目标包、不运行生命周期脚本；解析器自身仍须可信。

迁移兼容性须逐工具确认。多入口用 `bins` 声明并与原 manager 的入口集合保持一致（pyright 发布 `pyright`、`pyright-langserver`、`pyright-python`、`pyright-python-langserver`）；pyright 的 Node 运行时和特定回退路径中的 npm 下载不由 Python wheel 锁覆盖。`tomlq` 的 PyPI 包 0.1.0 只是转发到 `yq.tq_cli` 的薄壳，且与 yq 同时声明 `tomlq` 入口（双属主）；正式锁因此以 yq 为发行根，只发布 `tomlq` 入口，tools selector 同步为 yq 版本。

npm 侧声明了 install/postinstall 的包要区分两种情况：**制品随 tarball 交付、脚本只做校验或 chmod** 的可以迁 locked；**必须在安装期编译或下载额外二进制** 的不行。实测 dsh 的 node-pty 随包提供三平台 `prebuilds/`，运行时优先加载预编译；`spawn-helper` 在 tarball 里已是 755，npm 解包保留执行位，跳过 postinstall 的 chmod 不影响 macOS。qwen 的 `@qwen-code/audio-capture` 同样携带 prebuilds，其 install.js 只做定位/校验，失败时回退 SoX/arecord。koffi、sharp 也直接加载预编译产物。

离线集成测试使用自造工件：npm 从独立缓存以 HTTPS resolved 锁进行真实离线安装，覆盖错误 SRI 和旧入口保护；Python 使用本地 wheelhouse 验证 uv 接受正确哈希、拒绝错误哈希，仅是安装部件验证，不是完整 Python manager 端到端验收。测试不执行第三方包入口。

全平台验证覆盖到锁闭包层：7 个 npm 锁 × 3 个平台共 21 次 `npm ci --ignore-scripts` 全部退出 0；codex、dsh、qwen 在 linux/x64、linux/arm64、darwin/arm64 分别选中目标平台的预编译子包（dsh 三平台的 node-pty `pty.node` 就位，darwin `spawn-helper` 为 775；qwen 三平台 `@img/sharp-*` 正确）。这证明锁内工件、integrity 与平台选择一致，但未在 macOS 实机运行 CLI。Python 两个锁在 3.12 与 3.14 上都能安装并运行：`tomlq` 读、`-T -i` 单行改写、坏输入保留原文件，`pyright --version` 可启动；每个包在三平台都至少有一个匹配 wheel 的哈希在锁内。`-i` 仍非原子，`__tomlq_meta__` 被扰动时格式会大幅失真。

正式清单当前状态：7 个 npm 工具（typescript-lsp、yaml-lsp、bash-lsp、codex、pi-coding-agent、dsh、qwen-code）与 2 个 Python 工具（pyright、tomlq）全部使用 locked，锁位于 `locks/npm/` 与 `locks/python/`，不再按平台复制；manifest 中已没有 `npm-global` / `uv-tool` / `pnpm-global` 条目。

不能据此声称 npm/Python 已全部受哈希保护。校验器只检查列出的记录，不自行证明依赖闭包完整；闭包遗漏须由包管理器在哈希强制模式下拒绝。宿主 Node/npm/uv/Python 仍是信任前提。

## 已知限制

### 哈希校验的局限性

| 能保护 | 不能保护 |
|-------|---------|
| 文件完整性 | 插件脚本本身的恶意代码 |
| 检测篡改 | 官方私钥泄露 |
| 传输错误 | 版本本身的漏洞 |

### 信任假设

本项目的安全模型基于以下假设：

1. **Git 仓库是可信的** - 从可信源克隆代码
2. **GitHub Releases 是可信的** - 官方发布未被入侵
3. **本地系统是可信的** - 运行环境未被控制

已独立审查并固定在可信仓库中的摘要，可以发现上游随后替换工件；但不能证明最初取到的工件没有恶意代码。若攻击者同时控制仓库中的摘要与下载物，单纯哈希比对不能提供保护。

### TOML 编辑工具的身份与写入边界

逻辑工具名 `tomlq` 不等于实际发行包名。正式清单已直接以 `yq` 为根（tools selector `tomlq@4.4.5`，manifest `pkg = "yq"`），只发布 `tomlq` 入口；`tomlq --version` 输出 `tomlq 4.4.5` 和 jq 版本。旧的 `uv-tool` 安装会留下 `tomlq==0.1.0` 壳包 receipt，且两个发行包都声明 `tomlq` 入口；巡检若仍报告 `installed.identity` 的 `dual_owner`，表示本机还没重装，不是清单漂移。

`tomlq -T` 使用注释与格式保留机制，但不保证任意 jq 变换逐字节保真；`-i` 原地写入也不是原子替换。修改重要配置前保留备份，不能把格式保留等同于写入故障可恢复。

### 巡检结论的边界

- 钉版检查与本机实装检查分开报告；清单升级不代表机器已经升级。`installed_osv` 按本机可确认版本查询公告，独立列出命中、`trigger_note` 与 `reachability`，不进入 `open/new/regression/resolved/state` 基线；它只证明版本范围命中，不证明二进制来源或漏洞已实际利用。
- `state_legacy_keys` 是重构前按实装版本记账的历史键清单。这些键保留在 state 中作为时间线证据，但不再参与当前风险判定；当前钉版 findings 不会被宽泛清理。
- 顶层版本查询不覆盖间接依赖。巡检的 `candidate_transitive` 只审查与当前 SSOT 对齐的候选锁，独立列出命中和缺口；它不是本机已安装依赖树，不能与 `open` 基线混同。
- 版本探测失败、API 失败、摘要缺失或无法解释的公告范围必须列为数据缺口，不能算作“没有风险”。
- 包有历史公告不等于当前版本受影响；是否处置以影响范围、修复版本及实际使用路径为准。
- 用户级程序仍可读取用户可访问的 SSH 密钥、令牌和工作文件；非 root 不等于安全隔离。
- 哈希锁仅覆盖锁文件列出的工件，不自动覆盖生命周期脚本或运行时额外下载。

---

## 参考

- [SHA-256 - Wikipedia](https://en.wikipedia.org/wiki/SHA-2)
- [Software Supply Chain Security - OWASP](https://owasp.org/www-community/Supply_Chain_Security)
- [SLSA Framework](https://slsa.dev/)
