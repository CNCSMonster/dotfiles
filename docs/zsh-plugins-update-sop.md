# Zsh 插件版本更新 SOP

本文档描述如何安全地更新通过 zcomet 管理的 zsh 插件版本。

## 背景

所有 zsh 插件在 `shells/zsh/config.zsh` 中通过 `zcomet load` 加载，并使用 `@<version>` 固定版本号。例如：

```zsh
zcomet load Aloxaf/fzf-tab@v1.3.0
zcomet load romkatv/powerlevel10k@v1.20.0
```

固定版本可防止自动更新带来的供应链攻击和破坏性变更风险，但需要定期人工检查并升级到新版本。

## 更新流程

### 1. 查看当前已固定的版本

```bash
grep 'zcomet load\|zcomet fpath' shells/zsh/config.zsh
```

### 2. 检查各插件最新稳定版本

```bash
for repo in "tj/git-extras" "QuarticCat/zsh-smartcache" "chisui/zsh-nix-shell" \
            "romkatv/zsh-no-ps2" "hlissner/zsh-autopair" "Aloxaf/fzf-tab" \
            "zsh-users/zsh-autosuggestions" "zdharma-continuum/fast-syntax-highlighting" \
            "romkatv/powerlevel10k" "zsh-users/zsh-completions" \
            "nix-community/nix-zsh-completions"; do
    echo "=== $repo ==="
    git ls-remote --tags --refs "https://github.com/$repo.git" 2>/dev/null \
        | grep -o 'refs/tags/[^{}]*' | sed 's|refs/tags/||' | sort -V | tail -5
    echo
done
```

> 对于没有 tag 的仓库（如 QuarticCat/zsh-smartcache），使用 `git ls-remote <repo> HEAD` 获取最新 commit hash。

### 3. 检查破坏性变更（Breaking Changes）

对每个有新版的插件，检查其变更日志和发布说明：

```bash
# 方法 A: 查看仓库的 Releases / CHANGELOG
# https://github.com/<owner>/<repo>/releases

# 方法 B: 查看两个版本之间的 diff
git -C ~/.zcomet/repos/<owner>/<repo> diff <old-tag>..<new-tag> --stat
```

**重点检查：**
- 配置项名称/格式是否变更（如 `zstyle` 参数）
- 插件加载方式是否变更（如文件名、入口点）
- 依赖是否变更（是否需要新增外部工具）
- 是否有明确的 Breaking Changes 标注

### 4. 检查安全隐患

对每个待更新的插件，执行以下安全检查：

#### 4.1 仓库健康度
- 仓库是否仍然活跃（近期有提交、Issue 有人回复）
- 维护者是否有变更（警惕账号交接/被盗）
- 是否有已知的安全问题（搜索 `"<repo>" security vulnerability`）

#### 4.2 代码变更审查
```bash
# 查看新版本的关键变更
git -C ~/.zcomet/repos/<owner>/<repo> diff <old-tag>..<new-tag> -- '*.zsh' '*.sh'
```

**警惕以下行为：**
- 新增网络请求（`curl`、`wget`、`nc`、`/dev/tcp/`）
- 新增对敏感目录的读取（`~/.ssh/`、`~/.aws/`、`~/.gnupg/`）
- 新增环境变量外传（将数据 POST 到外部 URL）
- 新增 `precmd`/`preexec`/`zshaddhistory` hook 中的隐蔽逻辑
- 新增 `eval`、`source` 动态内容
- 新增对 `$PATH` 的修改

#### 4.3 依赖链审查
- 检查是否新增对第三方仓库的引用（submodule、其他插件）
- 检查是否新增从外部 URL 下载并执行脚本的逻辑

### 5. 更新配置

所有检查通过后，更新 `shells/zsh/config.zsh` 中的版本号：

```diff
-zcomet load Aloxaf/fzf-tab@v1.3.0
+zcomet load Aloxaf/fzf-tab@v1.4.0
```

### 6. 本地验证

```bash
# 清理旧版本缓存
rm -rf ~/.zcomet/repos/<owner>/<repo>
rm -f ~/.zcomet/repos/.zwc/*

# 重启 zsh 触发新版本的 clone
zsh

# 验证插件功能正常
# - 补全是否正常工作
# - 提示符是否显示正常
# - 有无报错信息
```

### 7. 更新 CHANGELOG

在 `CHANGELOG.md` 的 `[Unreleased]` 部分记录：

```markdown
### Changed
- **zsh-plugins**: Update fzf-tab v1.3.0 → v1.4.0
```

## 版本固定清单

| 插件 | 当前版本 | 仓库 |
|------|---------|------|
| zsh-users/zsh-completions | `0.36.0` | https://github.com/zsh-users/zsh-completions |
| nix-community/nix-zsh-completions | `0.5.1` | https://github.com/nix-community/nix-zsh-completions |
| tj/git-extras | `7.4.0` | https://github.com/tj/git-extras |
| QuarticCat/zsh-smartcache | `54aba13` (commit) | https://github.com/QuarticCat/zsh-smartcache |
| chisui/zsh-nix-shell | `v0.8.0` | https://github.com/chisui/zsh-nix-shell |
| romkatv/zsh-no-ps2 | `v1.0.0` | https://github.com/romkatv/zsh-no-ps2 |
| hlissner/zsh-autopair | `v1.0` | https://github.com/hlissner/zsh-autopair |
| Aloxaf/fzf-tab | `v1.3.0` | https://github.com/Aloxaf/fzf-tab |
| zsh-users/zsh-autosuggestions | `v0.7.1` | https://github.com/zsh-users/zsh-autosuggestions |
| zdharma-continuum/fast-syntax-highlighting | `v1.56` | https://github.com/zdharma-continuum/fast-syntax-highlighting |
| romkatv/powerlevel10k | `v1.20.0` | https://github.com/romkatv/powerlevel10k |

## 更新频率建议

- **常规更新**：每 1-3 个月检查一次
- **安全紧急更新**：发现漏洞后 24 小时内完成评估和升级
- **核心插件**（powerlevel10k、fzf-tab）：优先测试，确认兼容性后再更新

## 回滚

如果新版本导致 zsh 启动异常：

```bash
# 恢复旧版本
git checkout HEAD -- shells/zsh/config.zsh
zsh
```

## 相关文件

- 插件配置: `shells/zsh/config.zsh`
- 本文档: `docs/zsh-plugins-update-sop.md`
