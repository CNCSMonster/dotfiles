## Qwen Added Memories
- 配置 navi 等命令行工具的 cheats 时，对于新工具的命令，必须先通过官方文档验证命令的正确性，或者在隔离环境（如 Docker 容器）中实际运行验证后才能配置，避免配置错误的命令。
- Dotfiles 项目分支策略：实验在 exp-* 分支进行（如 exp-main, exp-wsl-ubuntu-24），实验完成后再转正。期间如需同步正式分支（main, wsl2-ubuntu-24）的最新内容，执行 rebase 对应正式分支到 exp 分支。
