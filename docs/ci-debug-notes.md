# CI 调试笔记：macOS 编译超时排查

> 日期：2026-04-22
> 问题：macOS CI 运行超时（>90 分钟被终止）
> 根因：`cargo-binstall` 安装失败，导致所有工具回退到源码编译

---

## 问题表现

- macOS runner 超时，Ubuntu 正常（22 分钟）
- CI 日志显示 27 个 Rust 工具全部报 "无预编译，稍后源码编译"
- 每个工具在 **1 秒内** 就报失败

## 排查教训

### 1. 自底向上验证基础设施

当**所有工具**都以同样方式失败时，首先怀疑基础设施，而不是每个工具都有问题：

```bash
# 验证 cargo-binstall 是否安装成功
cargo-binstall --version

# 验证 GitHub Token 是否可用
echo $GITHUB_TOKEN | head -c 10

# 手动测试一个已知有预编译的工具
cargo binstall bat --dry-run
```

### 2. 时间线是重要线索

- **正常**：每个工具下载/编译需要数十秒到几分钟
- **异常**：27 个工具全部在 1 秒内报失败 → 说明根本没执行

### 3. 预编译覆盖率调研结果

使用 `gh api`（已认证，不限流）检查 macOS aarch64 Release：

| 有预编译 (9) | 无预编译 (14) |
|-------------|--------------|
| sccache, bat, starship, zoxide, fd, nu, mdbook, jaq, zola | eza, uv, kondo, navi, mcfly, tokei, gitui, macchina, mise, cargo-audit, rust-script, tree-sitter-cli, tree-sitter-grep, tree-sitter-show-ast |

覆盖率约 33%，不是 0%。所以"全部无预编译"一定是 cargo-binstall 本身出了问题。

## 根因分析

1. **cargo-binstall 自身安装失败**：vendor 脚本路径计算错误，回退到源码编译也失败
2. **后续所有工具无法使用 binstall**：因为 cargo-binstall 根本没装上
3. **源码编译慢 + 并行度低**：CARGO_BUILD_JOBS=2 导致编译时间极长

## 修复措施

| 问题 | 修复 |
|------|------|
| vendor 脚本路径错误 | 移动到 `shells/scripts/vendor/`，使用 `BASH_SOURCE` 动态计算 |
| 并行度低 | macOS `CARGO_BUILD_JOBS=4`，Ubuntu 保持 `2` |
| 下载后缀硬编码 | 使用官方安装脚本替代手动拼接 URL |

## 未来排查清单

遇到 CI 安装问题时，按此顺序验证：

1. [ ] 基础工具版本（cargo-binstall, rustup, cargo --version）
2. [ ] 环境变量（GITHUB_TOKEN, PATH, CARGO_HOME）
3. [ ] 网络连通性（GitHub API, crates.io）
4. [ ] 平台兼容性（OS/架构匹配，预编译是否存在）
5. [ ] 具体工具安装日志

## 相关修复

- `f064729` fix: move vendor scripts to shells/scripts/vendor for proper xdotter deployment
- `790e39c` ci: optimize macOS cargo build parallelism to 4
- `409fccc` fix: use vendored cargo-binstall installer script
