# xdotter 使用指南

本项目使用 [xdotter](https://github.com/cncsmonster/xdotter) 管理 dotfile 部署。

## 官方文档

- [**xdotter README**](https://github.com/cncsmonster/xdotter) - 安装、命令、配置详解

## 项目结构

```
dotfiles/
├── xdotter.toml          # 主配置 - 定义 4 个模块依赖
├── langs/xdotter.toml    # 语言工具 (Go, Rust)
├── shells/xdotter.toml   # Shell 配置 (bash, zsh)
├── nvims/xdotter.toml    # Neovim 配置
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
nvims = "nvims"
helix = "helix"

# 符号链接
[links]
"navi" = "~/.local/share/navi/cheats"
"yazi" = "~/.config/yazi"
"git" = "~/.config/git"
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

# 验证配置文件
xd validate
```

## 版本要求

本项目需要 **xdotter v0.3.4+**（v0.3.4 移除了 `--config` 参数）
