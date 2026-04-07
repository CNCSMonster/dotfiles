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

### 高级用法

```bash
# 无缓存重建
./scripts/docker-build-test.sh --no-cache

# 网络不稳定时重试
./scripts/docker-build-test.sh --retry 3
```

---

## CI 流程

GitHub Actions 在每次 push 时自动运行：

1. 使用 `docker/build-push-action@v6` 构建镜像
2. 自动运行 `/root/dotfiles/scripts/verify-docker-build.sh`
3. 验证脚本输出 `失败：0` 即通过

详情见 [`.github/workflows/docker-build.yml`](.github/workflows/docker-build.yml)。

---

## 验证标准

验证脚本检查：
- Neovim 可运行
- Rust 工具链可用
- 主要工具版本正常

输出示例：
```
验证通过！
失败：0
```

---

## 修改后流程

1. 本地修改 dotfiles 配置
2. 运行 `./scripts/docker-build-test.sh`
3. 确保验证通过（`失败：0`）
4. 提交并推送（CI 自动验证）

---

## 资源限制

构建脚本自动检测系统资源并设置限制：

- `BUILD_JOBS = floor((可用内存 - 2GB) / 1.5GB)`
- 防止 Rust 编译时 OOM

---

## 项目结构

```
.
├── setup.sh                    # 一键安装脚本
├── xdotter.toml                # xdotter 配置
├── scripts/
│   ├── docker-build-test.sh    # Docker 构建脚本
│   ├── verify-docker-build.sh  # 验证脚本
│   └── README.md               # 脚本说明
├── .github/workflows/
│   └── docker-build.yml        # CI 配置
├── shells/                     # Shell 配置
└── docs/                       # 用户文档
```
