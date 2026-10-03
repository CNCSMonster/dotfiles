"""Serial installation executor."""

from __future__ import annotations

import os
import sys
from typing import List, Mapping

from .errors import AuthorizationRequired, InstallationError
from .managers.base import CheckResult
from .models import InstallPlan, PlanItem
from .managers.base import Manager


def _format_warning(item: PlanItem, phase: str, reason: str) -> str:
    """Format a warning with the minimum fields required by SPEC."""
    return (
        f"⚠️ Warning: tool={item.tool.reference.name}, "
        f"manager={item.strategy.manager}, "
        f"phase={phase}, "
        f"reason={reason}"
    )


def execute_plan(plan: InstallPlan, managers: Mapping[str, Manager]) -> None:
    # 轮级前置：每种**本轮用到**的 manager 各跑一次 preflight（AptManager 在这里
    # 刷索引 + 做源预检），对齐 shell 侧"脚本开头 update 一次、多包共用"的语义。
    # 先做完所有前置再逐项执行；前置自身把失败收敛为警告，不阻断整轮。
    grouped = {}  # manager name -> items (dict 保插入序，执行顺序不变)
    for plan_item in plan.items:
        grouped.setdefault(plan_item.strategy.manager, []).append(plan_item)
    for manager_name, group in grouped.items():
        managers[manager_name].preflight(group)

    token_reported = False
    tolerated: List[str] = []
    pending: List[str] = []
    for item in plan.items:
        manager = managers[item.strategy.manager]
        try:
            _execute_item(item, manager, token_reported)
            if item.strategy.manager == "github-release":
                token_reported = True
        except AuthorizationRequired as exc:
            # 缺授权不是失败：跳过这个工具继续装其余的，最后统一汇总。
            # 放在 InstallationError 之前捕获（它是子类），否则会走 allow_fail 分支——
            # 而"没人在场能回答"与"允许失败"是两件事，不该混为一谈。
            print(_format_warning(item, "authorize", str(exc)), file=sys.stderr)
            pending.append(item.tool.reference.name)
            if item.strategy.manager == "github-release":
                token_reported = True
            continue
        except InstallationError as exc:
            if item.tool.allow_fail:
                print(_format_warning(item, "install", str(exc)), file=sys.stderr)
                tolerated.append(item.tool.reference.name)
                if item.strategy.manager == "github-release":
                    token_reported = True
                continue
            raise
    # 授权跳过**不是失败**：它是"这个环境下没有人能授权"（无 TTY 且未传 --yes），
    # 拍板语义就是跳过 + 汇总、不中断。strict 管的是**失败**（tolerated），把
    # "没人可问"升格成 fatal 会让无人值守 CI 永远红，而它要报告的信息一个字不少。
    # CI 实测（STRICT=1）：clang 已存在于 /usr/bin（能用）、dpkg 无记录，跳过正是
    # 不覆盖已有实现的正确选择；它不阻塞后续安装，汇总也照打。
    if pending:
        summary = f"{len(pending)} tool(s) skipped pending authorization: {', '.join(pending)}"
        print(
            f"⚠️  Skipped, authorization required: {summary}. "
            "Re-run with --yes, or run in an interactive terminal.",
            file=sys.stderr,
        )

    # Fail at the end rather than immediately: later tools are independent,
    # and CI gets the complete failure list in one run.
    #
    # Tolerated failures are reported in BOTH modes. In non-strict mode the exit
    # code stays 0 (the project's stated goal is not to abort an install over a
    # predictable failure), but staying silent is what let two allow_fail tools
    # reinstall on every run for months — the cost was absorbed with no signal.
    # setup.sh, the real user entry point, never sets TOOL_INSTALLER_STRICT, so
    # this summary is the only place a manual install learns about them.
    if tolerated:
        summary = f"{len(tolerated)} allow_fail tool(s) failed: {', '.join(tolerated)}"
        if os.environ.get("TOOL_INSTALLER_STRICT") == "1":
            raise InstallationError(f"strict mode: {summary}")
        print(
            f"⚠️  Tolerated failures (non-strict, install continues): {summary}. "
            "Set TOOL_INSTALLER_STRICT=1 to fail instead.",
            file=sys.stderr,
        )


def _execute_item(item: PlanItem, manager: Manager, token_reported: bool) -> None:
    print(f"📦 Installing {item.tool.reference.name}")

    # Report GitHub token source for github-release managers
    if item.strategy.manager == "github-release" and hasattr(manager, "get_token_report"):
        source = manager.get_token_report()
        if token_reported:
            print(f"🔑 GitHub token: (cached) {source}")
        elif "not configured" in source:
            print(f"⚠️  GitHub token: {source}")
        else:
            print(f"🔑 GitHub token: {source}")

    if item.strategy.force:
        # Bypass check and attempt installation
        manager.install(item)
        return

    # Run installed-state check
    result = manager.check(item)
    if result == CheckResult.CHECK_ERROR:
        # The check may have failed because this run itself installed the
        # runtime the check needs (mise/node, uv) after our PATH snapshot.
        from .environment import refresh_path

        if refresh_path():
            result = manager.check(item)

    if result == CheckResult.SATISFIED:
        print(f"✅ Skip {item.tool.reference.name}")
        return

    if result == CheckResult.CHECK_ERROR:
        # check_error is an installation failure for that tool
        raise InstallationError(
            f"Check failed for {item.tool.reference.name} with manager {item.strategy.manager}"
        )

    # not_satisfied: attempt installation
    manager.install(item)


def print_dry_run(plan: InstallPlan) -> None:
    for item in plan.items:
        print(
            " ".join(
                [
                    "PLAN",
                    f"module={item.module_name}",
                    f"tool={item.tool.reference.name}",
                    f"version={item.tool.reference.version}",
                    f"manager={item.strategy.manager}",
                    f"os={item.environment.os}",
                    f"arch={item.environment.arch}",
                    f"force={str(item.strategy.force).lower()}",
                    f"allow_fail={str(item.tool.allow_fail).lower()}",
                ]
            )
        )
