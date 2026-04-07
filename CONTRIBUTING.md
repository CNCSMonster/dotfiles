# Contributing

本文档面向想要验证、修改或贡献此 dotfiles 项目的开发者。

---

## Docker 构建验证

Docker 镜像用于验证 `setup.sh` 在干净 Ubuntu 环境中可正常执行。

### 一行验证命令

```bash
./scripts/docker-build-test.sh
```

构建完成后自动运行验证脚本。

---

## 验证逻辑

验证脚本检查三类内容：

| 类别 | 说明 | 示例 |
|------|------|------|
| **工具安装** | 所有工具是否正确安装 | `rustc --version`, `nvim --version` |
| **配置部署** | xdotter 是否正确部署配置 | `~/.zshrc`, `~/.config/git` 符号链接 |
| **功能测试** | 编译器是否可正常工作 | GCC/Clang/Rust 编译测试 |

### 关键验证点

**这个项目独有的配置验证：**

```bash
# xdotter 部署的符号链接
~/.zshrc -> ~/.config/shells/zsh/zshrc
~/.config/mise -> ~/.local/share/mise
~/.config/yazi -> ~/.config/yazi

# 配置文件
~/.cargo/config.toml  # Rust 镜像源配置
~/.config/git/config  # Git 配置
~/.config/starship.toml  # 提示符配置
```

这些符号链接和配置文件的存在证明 xdotter 正确部署。

---

## CI 流程

GitHub Actions 在每次 push 时自动运行：

1. 使用 `docker/build-push-action@v6` 构建镜像
2. 运行验证脚本检查工具 + 配置 + 功能
3. 输出 `通过：XX  失败：0` 即通过

详情见 [`.github/workflows/docker-build.yml`](.github/workflows/docker-build.yml)。

---

## 修改后流程

1. 本地修改 dotfiles 配置
2. 运行 `./scripts/docker-build-test.sh`
3. 确保验证通过（`失败：0`）
4. 提交并推送（CI 自动验证）

---

## 项目结构

```
.
├── setup.sh                    # 一键安装脚本
├── xdotter.toml                # xdotter 配置
├── scripts/
│   ├── docker-build-test.sh    # Docker 构建脚本
│   └── verify-docker-build.sh  # 验证脚本
├── .github/workflows/
│   └── docker-build.yml        # CI 配置
├── shells/                     # Shell 配置
└── docs/                       # 用户文档
```
