# xdotter 使用指南

本项目使用 [xdotter](https://github.com/cncsmonster/xdotter) 管理 dotfile 部署。

## 官方文档

- [**xdotter README**](https://github.com/cncsmonster/xdotter) - 安装、命令、配置详解

## 项目结构

```
dotfiles/
├── xdotter.toml          # 主配置 - 定义 3 个模块依赖
├── langs/xdotter.toml    # 语言工具 (Go, Rust)
├── shells/xdotter.toml   # Shell 配置 (bash, zsh)
├── helix/xdotter.toml    # Helix 编辑器配置
└── ...                   # 其他 dotfiles (git, yazi, wezterm 等)
```

## 配置格式

xdotter.toml 使用 TOML 格式：

```toml
# 依赖模块
[dependencies]
langs = "langs"
shells = "shells"
helix = "helix"

# 符号链接
[links]
"navi" = "~/.local/share/navi/cheats"
"yazi/yazi.toml" = "~/.config/yazi/yazi.toml"
"yazi/keymap.toml" = "~/.config/yazi/keymap.toml"
"git/config" = "~/.config/git/config"
"git/.gitignore_global" = "~/.config/git/.gitignore_global"
```

## 常用命令

```bash
# 部署 dotfiles
xd deploy

# 详细模式部署
xd deploy -v

# 干运行（预览变更，不实际执行）
xd deploy --dry-run

# 移除已部署的 dotfiles
xd undeploy

# 检查部署状态（xdotter 没有 validate 子命令，体检靠 status）
xd status
```

`setup.sh` 调用 `xd deploy --force` 前，会列出**将被覆盖的既有普通文件**，在交互终端获得确认后再备份到
`~/.local/state/dotfiles/deploy-backup/<时间戳>/<原绝对路径>`；备份失败则中止覆盖式部署。
拒绝确认或没有交互终端时，中止本次部署并返回非零，不会自动接管已有文件。非空真实目录即使带 `--force` 也不会被替换（xdotter 报冲突），需手动处理后重跑。

`xd status` 输出一行总览加七类异常计数，全为 0 才算部署无漂移：

```
Status: N/N deployed   # N 随 xdotter.toml 的链接数变化，两数相等即全部部署
Not deployed / Wrong links / Broken links / Source missing
Source type invalid / Non-symlink paths / Permission issues
```

## 版本要求

本项目需要 **xdotter v0.3.4+**（v0.3.4 移除了 `--config` 参数）
