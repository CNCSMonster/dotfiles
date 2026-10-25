"""Installation executor supporting sequential and concurrent execution."""

from __future__ import annotations

import concurrent.futures
import os
import sys
from typing import List, Mapping, Optional, Tuple

from .errors import AuthorizationRequired, InstallationError
from .managers.base import CheckResult, Manager
from .models import InstallPlan, PlanItem


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
    grouped = {}  # manager name -> items (dict 保插入序，执行顺序不变)
    for plan_item in plan.items:
        grouped.setdefault(plan_item.strategy.manager, []).append(plan_item)
    for manager_name, group in grouped.items():
        managers[manager_name].preflight(group)

    token_reported = False
    tolerated: List[str] = []
    pending: List[str] = []

    # 并发度控制：默认并发 4；设为 1 时退化为严格串行
    concurrency_env = os.environ.get("TOOL_INSTALLER_CONCURRENCY", "4")
    try:
        max_workers = max(1, int(concurrency_env))
    except ValueError:
        max_workers = 4

    # 将 items 切分为可并发批次与严格串行批次
    # 仅无状态且无独占锁的 manager (github-release) 参与并发
    batches: List[List[PlanItem]] = []
    current_batch: List[PlanItem] = []
    current_is_concurrent = False

    for item in plan.items:
        item_can_concurrent = (item.strategy.manager == "github-release") and (max_workers > 1)
        if not current_batch:
            current_batch.append(item)
            current_is_concurrent = item_can_concurrent
        elif item_can_concurrent and current_is_concurrent:
            current_batch.append(item)
        else:
            batches.append(current_batch)
            current_batch = [item]
            current_is_concurrent = item_can_concurrent
    if current_batch:
        batches.append(current_batch)

    for batch in batches:
        is_concurrent_batch = (
            len(batch) > 1 and batch[0].strategy.manager == "github-release" and max_workers > 1
        )

        if is_concurrent_batch:
            # 并发执行独立下载与安装
            manager = managers[batch[0].strategy.manager]
            workers = min(len(batch), max_workers)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_execute_item_wrapped, item, manager, token_reported)
                    for item in batch
                ]
                for item, future in zip(batch, futures):
                    kind, exc = future.result()
                    if item.strategy.manager == "github-release":
                        token_reported = True
                    if kind == "ok":
                        continue
                    elif kind == "auth":
                        print(_format_warning(item, "authorize", str(exc)), file=sys.stderr)
                        pending.append(item.tool.reference.name)
                    elif kind == "tolerated":
                        print(_format_warning(item, "install", str(exc)), file=sys.stderr)
                        tolerated.append(item.tool.reference.name)
                    elif kind == "failed":
                        raise exc
        else:
            # 串行执行
            for item in batch:
                manager = managers[item.strategy.manager]
                try:
                    _execute_item(item, manager, token_reported)
                    if item.strategy.manager == "github-release":
                        token_reported = True
                except AuthorizationRequired as exc:
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

    if pending:
        summary = f"{len(pending)} tool(s) skipped pending authorization: {', '.join(pending)}"
        print(
            f"⚠️  Skipped, authorization required: {summary}. "
            "Re-run with --yes, or run in an interactive terminal.",
            file=sys.stderr,
        )

    if tolerated:
        summary = f"{len(tolerated)} allow_fail tool(s) failed: {', '.join(tolerated)}"
        if os.environ.get("TOOL_INSTALLER_STRICT") == "1":
            raise InstallationError(f"strict mode: {summary}")
        print(
            f"⚠️  Tolerated failures (non-strict, install continues): {summary}. "
            "Set TOOL_INSTALLER_STRICT=1 to fail instead.",
            file=sys.stderr,
        )


def _execute_item_wrapped(
    item: PlanItem, manager: Manager, token_reported: bool
) -> Tuple[str, Optional[Exception]]:
    """Helper to wrap execution for thread pool results."""
    try:
        _execute_item(item, manager, token_reported)
        return ("ok", None)
    except AuthorizationRequired as exc:
        return ("auth", exc)
    except InstallationError as exc:
        if item.tool.allow_fail:
            return ("tolerated", exc)
        return ("failed", exc)


def _execute_item(item: PlanItem, manager: Manager, token_reported: bool) -> None:
    print(f"📦 Installing {item.tool.reference.name}")

    if item.strategy.manager == "github-release" and hasattr(manager, "get_token_report"):
        source = manager.get_token_report()
        if token_reported:
            print(f"🔑 GitHub token: (cached) {source}")
        elif "not configured" in source:
            print(f"⚠️  GitHub token: {source}")
        else:
            print(f"🔑 GitHub token: {source}")

    if item.strategy.force:
        manager.install(item)
        return

    result = manager.check(item)
    if result == CheckResult.CHECK_ERROR:
        from .environment import refresh_path

        if refresh_path():
            result = manager.check(item)

    if result == CheckResult.SATISFIED:
        print(f"✅ Skip {item.tool.reference.name}")
        return

    if result == CheckResult.CHECK_ERROR:
        raise InstallationError(
            f"Check failed for {item.tool.reference.name} with manager {item.strategy.manager}"
        )

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
