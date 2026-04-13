## Qwen Added Memories
- 配置 navi 等命令行工具的 cheats 时，对于新工具的命令，必须先通过官方文档验证命令的正确性，或者在隔离环境（如 Docker 容器）中实际运行验证后才能配置，避免配置错误的命令。
- 审核 PR 时，以项目文档中的设计标准来验证：
  - `docs/xdotter-usage.md` — xdotter 模块化模式（dependencies + links + 符号链接部署）
  - `docs/multi-env-design.md` — 分支策略（main = Ubuntu 通用，其他分支 = 环境专属）
  - `docs/shell-config-architecture.md` — Shell 配置架构
  - `CONTRIBUTING.md` — PR 验证检查清单
