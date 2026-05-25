# 配置一致性检查 SOP

本文档描述如何检查项目中**已安装的工具与实际生效的 shell 补全**是否一致，发现并补齐缺失的补全配置。

## 背景

项目通过多种渠道安装 CLI 工具：
- `mise` — 管理 go、node、zig、yazi 等
- `cargo binstall/install` — 安装 Rust 工具
- `apt` — 安装系统级工具
- 二进制下载 — helix、wezterm 等

当前 **shell 补全来源** 包括：
- `zsh-completions` 插件（静态补全脚本，`@0.36.0`）
- `nix-zsh-completions` 插件（静态补全脚本，`@0.5.1`）
- `mise activate` 动态注册（仅限 mise 管理的工具）
- `shells/common/inter.sh` 中主动加载的工具自带补全（如 `xd`、`llm-proxy`、`codex`、`opencode`）

很多工具（如 `zola`、`helix`、`jaq`、`nu`、`tree-sitter-grep` 等）可能不在上述来源中，导致按 Tab 时无反应。

## 检查范围

| 维度 | 说明 |
|------|------|
| 补全是否缺失 | 已安装的工具是否生成了 zsh/bash 补全 |
| 补全是否多余 | 是否加载了补全但工具本身没装 |
| 补全加载位置 | 补全脚本是否放在正确的 `$fpath` 位置 |
| zsh-completions 版本 | 是否因版本过旧而缺少新工具补全 |

## 当前补全配置位置

| 文件 | 内容 |
|------|------|
| `shells/zsh/config.zsh` | `compinit` + `zcomet fpath zsh-users/zsh-completions@0.36.0 src` + `nix-community/nix-zsh-completions@0.5.1` |
| `shells/bash/bashrc` | `/usr/share/bash-completion/bash_completion` |
| `shells/common/inter.sh` | 交互式 shell 中主动加载工具自带补全：`xd`、`llm-proxy`、`codex`、`opencode` |

工具自带补全统一放在 `shells/common/inter.sh`，并用 `command -v` 守卫，避免未安装工具影响 shell 启动。

## 检查流程

### 1. 生成已安装工具清单

#### 1.1 从安装脚本提取

```bash
# 从 install-functions.sh 提取 cargo 安装的工具
grep 'cargo_install_common' shells/common/install-functions.sh \
    | grep -oP '[\w-]+(?:@[\d.]+)?' \
    | grep -v 'cargo_install' | sort -u > /tmp/installed-cargo.txt

# 从 mise/config.toml 提取
grep -oP '^\w+' mise/config.toml | sort -u > /tmp/installed-mise.txt

# 从 apt 安装提取（install-common-tools）
grep -A5 'function install-common-tools' shells/common/install-functions.sh \
    | grep -oP '[a-z][a-z0-9-]+' | sort -u > /tmp/installed-apt.txt
```

#### 1.2 从运行时环境提取（更准确）

```bash
# mise 管理的工具
mise list --current 2>/dev/null | awk '{print $1}' | sort -u > /tmp/installed-mise-runtime.txt

# cargo 安装的工具（有 bin 的）
cargo install --list 2>/dev/null | grep -oP '^\S+' | sort -u > /tmp/installed-cargo-runtime.txt

# PATH 中所有非系统自带的可执行文件（可选辅助）
comm -23 <(ls $(echo $PATH | tr ':' '\n' | sort -u) 2>/dev/null | sort -u) \
         <(dpkg -L $(dpkg --get-selections | grep install | awk '{print $1}') 2>/dev/null | grep '/usr/bin/' | xargs -I{} basename {} | sort -u)
```

#### 1.3 合并去重

```bash
cat /tmp/installed-*.txt | sort -u > /tmp/installed-tools.txt
```

### 2. 生成已生效补全清单

#### 2.1 zsh 补全

```zsh
# 在 zsh 中运行：列出所有已加载的补全函数
typeset -f + | grep '^_' | sed 's/^_//' | sort -u > /tmp/active-zsh-completions.txt

# 或者检查 fpath 中所有 _ 开头的文件
find ${(@)fpath} -maxdepth 1 -name '_*' -exec basename {} \; 2>/dev/null | sed 's/^_//' | sort -u > /tmp/available-zsh-completions.txt
```

#### 2.2 bash 补全

```bash
# 列出已注册的 bash 补全
compgen -c | sort -u > /tmp/available-bash-completions.txt
```

#### 2.3 mise 动态补全

```bash
# mise activate 为哪些命令注册了补全
mise complete -- <TAB>  # 在 shell 中测试
```

### 3. 交叉比对

```bash
# 已安装但无补全的工具（需要关注的）
comm -23 /tmp/installed-tools.txt /tmp/active-zsh-completions.txt > /tmp/missing-completions.txt

# 有补全但未安装的工具（可能是残留或多余的）
comm -13 /tmp/installed-tools.txt /tmp/active-zsh-completions.txt > /tmp/orphan-completions.txt
```

### 4. 检查结果分类

将 `/tmp/missing-completions.txt` 中的工具按优先级分类：

| 优先级 | 类别 | 示例 | 处理方式 |
|--------|------|------|----------|
| **P0** | 高频交互工具，子命令多 | `mise`、`uv`、`zoxide`、`fd`、`bat` | 优先补齐 |
| **P1** | 常用开发工具 | `cargo`、`rustup`、`go`、`node`、`pnpm` | 应补齐 |
| **P2** | 偶尔使用但有子命令 | `zola`、`tokei`、`jaq`、`kondo` | 建议补齐 |
| **P3** | 无子命令/补全意义不大 | `sccache`、`wild-linker` | 可忽略 |
| **P4** | 补全已由其他机制提供 | mise 管理的工具已有 mise activate | 无需处理 |

### 5. 补齐方案

对需要补齐的工具，按以下优先级选择方案：

#### 方案 A：工具自带补全生成（最佳）

工具自带补全生成统一添加到 `shells/common/inter.sh`，并使用 `$SH` 兼容 bash/zsh。

```bash
# shells/common/inter.sh
if command -v zola >/dev/null 2>&1; then
    eval "$(zola completion "$SH" 2>/dev/null)"
fi
```

如果工具对不同 shell 使用不同子命令，必须先通过官方文档或本机 `--help` 验证，再按实际命令配置。

**优点**：总是最新，跟随工具版本更新
**缺点**：每个工具都要写一段，并且必须验证补全命令确实存在

#### 方案 B：zsh-completions 已有但没加载

```bash
# 检查 zsh-completions 是否已包含该工具的补全
ls ~/.zcomet/repos/zsh-users/zsh-completions/src/_<工具名>
```

如果有，说明已被正确加载（通过 `zcomet fpath`），无需额外操作。

#### 方案 C：手写简单补全

对于没有自带补全生成、也不在 zsh-completions 中的工具，优先确认是否真的值得维护手写补全。若需要手写，放入专门的 shell 补全文件并在 `shells/common/inter.sh` 中按 shell 类型加载，避免把大量补全函数散落在 `config.zsh` 或 `bashrc`。

```zsh
# 示例：zsh 专用补全函数
if (( $+commands[jaq] )); then
    _jaq() {
        local -a opts
        opts=(
            '--compact-output[Compact output]'
            '--slurp[Read all inputs into an array]'
            '--raw-input[Read input as raw strings]'
        )
        _arguments $opts
    }
    compdef _jaq jaq
fi
```

### 6. 验证

```bash
# 重启 zsh
zsh

# 逐一测试补全是否正常
<工具名> <TAB>

# 检查无报错
compaudit  # 应提示 "There are insecure directories" 或 "no problems found"
```

### 7. 提交

将已验证的工具自带补全配置添加到 `shells/common/inter.sh`，并在 commit 中说明补齐了哪些工具的补全。不要为没有可验证 shell 补全命令的工具添加占位配置。

## 自动化脚本建议

可将上述流程整合为一个检查脚本 `scripts/check-completions.sh`，一键运行输出报告：

```bash
#!/usr/bin/env bash
# 用法：bash scripts/check-completions.sh
# 输出：
#   [MISSING]  zola - 高频使用，建议补全
#   [MISSING]  jaq  - 偶尔使用，建议补全
#   [OK]       fd   - zsh-completions 已提供
#   [OK]       uv   - 自带补全已加载
```

## 检查频率建议

- **每次新增工具后**：立即检查补全
- **zsh-completions 版本更新后**：验证是否新增了已安装工具的补全
- **定期审计**：每季度运行一次完整检查

## 相关文件

- zsh 补全配置: `shells/zsh/config.zsh`
- bash 补全配置: `shells/bash/bashrc`
- 工具自带补全加载: `shells/common/inter.sh`
- zsh-completions 版本: 通过 `zcomet fpath zsh-users/zsh-completions@0.36.0 src` 固定
- nix-zsh-completions 版本: 通过 `zcomet fpath nix-community/nix-zsh-completions@0.5.1` 固定
- 相关 SOP: `docs/zsh-plugins-update-sop.md`（更新 zsh-completions 后验证补全）
