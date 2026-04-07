# Contributing

本文档面向想要验证、修改或贡献此 dotfiles 项目的开发者。

---

## Docker 构建验证

Docker 镜像用于验证 `setup.sh` 在干净 Ubuntu 环境中可正常执行。

### 快速验证

```bash
# 构建镜像（自动资源控制）
./scripts/docker-build-test.sh

# 运行容器
docker run -it dotfiles:test
```

### 高级用法

```bash
# 无缓存重建（确保从头验证）
./scripts/docker-build-test.sh --no-cache

# 网络不稳定时重试
./scripts/docker-build-test.sh --retry 3
```

### 构建脚本说明

`docker-build-test.sh` 会：
1. 检测可用内存和 CPU 核心数
2. 动态计算资源限制（防止 OOM）
3. 创建 BuildKit builder 并设置限制
4. 构建镜像

详情见 [`scripts/README.md`](./scripts/README.md)。

---

## 验证安装

构建完成后，在容器内验证：

```bash
# 基础工具
nvim --version
rustc --version
go version

# 运行验证脚本
/root/dotfiles/scripts/verify-docker-build.sh
```

预期输出：`失败：0`

---

## 项目结构

```
.
├── setup.sh                    # 一键安装脚本
├── xdotter.toml                # xdotter 配置
├── scripts/
│   ├── docker-build-test.sh    # Docker 构建验证
│   ├── verify-docker-build.sh  # 安装验证脚本
│   └── README.md               # 脚本说明
├── shells/                     # Shell 配置
│   ├── zsh/
│   └── common/
├── docs/                       # 用户文档
└── ...                         # 其他配置（nvim, git 等）
```

---

## 修改后验证流程

1. **本地修改** dotfiles 配置
2. **Docker 验证** `./scripts/docker-build-test.sh`
3. **检查输出** 确保 `失败：0`
4. **提交更改**

---

## 资源限制说明

BuildKit docker-container driver 采用分层架构：

| 层级 | 限制方式 | 效果 |
|------|---------|------|
| BuildKit Daemon | `--driver-opt memory=Xg` | ✅ 限制调度进程 |
| 临时构建容器 | 无直接限制 | ❌ 使用宿主机全部资源 |
| cargo 编译进程 | `CARGO_BUILD_JOBS` | ✅ 唯一有效的内存控制 |

公式：`BUILD_JOBS = floor((可用内存 - 2GB) / 1.5GB)`

---

## 发布流程

1. 修改后运行 Docker 验证
2. 确保所有测试通过
3. 更新 `CHANGELOG.md`
4. 提交并推送
