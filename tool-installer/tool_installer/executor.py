"""Serial installation executor."""

from __future__ import annotations

import sys
from typing import Mapping

from .errors import InstallationError
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
    token_reported = False
    for item in plan.items:
        manager = managers[item.strategy.manager]
        try:
            _execute_item(item, manager, token_reported)
            if item.strategy.manager == "github-release":
                token_reported = True
        except InstallationError as exc:
            if item.tool.allow_fail:
                print(_format_warning(item, "install", str(exc)), file=sys.stderr)
                if item.strategy.manager == "github-release":
                    token_reported = True
                continue
            raise


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
