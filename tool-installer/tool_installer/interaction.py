"""交互与授权策略：默认问，除非显式 `--yes`，或者根本没有可应答的用户。

政策（migration-plan §4.3 Step 2，2026-10-03 拍板）：

- **预期操作不问**：下载、安装、把版本对齐到 manifest pin 的值——这是装机的本职，
  带 `-y` 直接做（`-y` 管的是 apt 自己那一层，与本模块无关）。
- **非预期状态要问**：现场和预期不一样——工具已存在但不是本管理器装的、配置文件被
  本地改过、包的安装脚本发问。这类问题会动到用户已有的东西。
- **`--yes` 全部同意**，一个都不问。
- **无 TTY 且没传 `--yes`** → 没有人可以应答，既不擅自决定也不中断，返回
  :attr:`Decision.UNAUTHORIZED`，由调用方跳过该工具并交给 executor 结束时汇总。
  （依赖调用方"记得传参"的约定早晚会失守，所以环境本身要能自证。）

边界（已核实，2026-10-03）：**认证不是决策**。`--yes` 管不到 sudo 密码——sudo 上游
（sudo-rs 0.2.x / 传统 sudo 1.9.x）只有 `-n`（不提示直接失败）、`-A`/`SUDO_ASKPASS`、
`-S`（换方式取密码）和 sudoers 的 `NOPASSWD`，**不存在"用调用方参数完成授权"的机制**。
"""

from __future__ import annotations

import enum
import os
import sys

ASSUME_YES_ENV = "TOOL_INSTALLER_ASSUME_YES"


class Decision(enum.Enum):
    """一次问询的结果，三种必须分开：同意、拒绝、无人可问。"""

    YES = "yes"
    NO = "no"
    UNAUTHORIZED = "unauthorized"


def assume_yes() -> bool:
    """是否处于 `--yes`（全部同意）模式。"""
    return os.environ.get(ASSUME_YES_ENV) == "1"


def is_interactive() -> bool:
    """stdin 与 stdout 都是 TTY = 有用户在场、且问题能被他看见。"""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError, OSError):
        # stdin/stdout 已关闭或重定向
        return False


def ask(prompt: str) -> Decision:
    """提出一个非预期问题。默认答案是 **N**（不碰用户已有的东西）。"""
    if assume_yes():
        return Decision.YES
    if not is_interactive():
        return Decision.UNAUTHORIZED

    while True:
        try:
            answer = input(f"{prompt} [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            # 输入流被关掉或用户 Ctrl-C：同样视为"无人可问"，由调用方跳过并汇总
            return Decision.UNAUTHORIZED
        if answer in ("", "n", "no"):
            return Decision.NO
        if answer in ("y", "yes"):
            return Decision.YES
        print("请输入 y 或 n")
