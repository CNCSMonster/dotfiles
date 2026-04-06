# 多环境配置设计

## 设计理念

本项目使用 **Git 分支** 管理不同环境的 dotfile 配置。

```
main              → 主机器配置（物理机）
wsl2-ubuntu-24    → WSL2 Ubuntu 24.04 配置
...               → 其他环境
```

## 使用方法

### 切换环境

```bash
# 切换到目标环境分支
git checkout wsl2-ubuntu-24

# 部署该环境的配置
./setup.sh
```

### 创建新环境

```bash
# 基于当前分支创建新环境
git checkout -b new-machine-name

# 修改 xdotter.toml 和环境特定的配置
# 提交并推送
git push -u origin new-machine-name
```

## 配置差异

不同分支可以有不同的：
- `xdotter.toml` - 链接不同的配置文件
- `shells/` - 不同的 Shell 配置
- `git/` - 不同的 Git 配置（如凭据、签名）
- `mise/` - 不同的工具版本
- 其他环境特定文件

## 分支命名规范

```
<环境类型>-<系统>-<版本>
```

示例：
- `wsl2-ubuntu-24` - WSL2 Ubuntu 24.04
- `desktop-arch` - 物理机 Arch Linux
- `server-2204` - 服务器 Ubuntu 22.04

## 同步配置

```bash
# 合并 main 的通用配置到环境分支
git checkout wsl2-ubuntu-24
git merge main

# 解决冲突后，保留环境特定的配置
```

## 查看当前配置

```bash
# 查看当前分支
git branch --show-current

# 查看 xdotter 部署的链接
xd deploy --dry-run
```
