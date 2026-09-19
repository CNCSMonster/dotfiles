"""Script manager."""

from __future__ import annotations

import os
import subprocess
from typing import Dict

from ..errors import InstallationError
from ..models import PlanItem
from .base import CheckResult


class ScriptManager:
    """Script manager for custom installation scripts.

    Not check-capable in v1. Always returns NOT_SATISFIED.
    """

    def check(self, item: PlanItem) -> CheckResult:
        # Script manager does not support installed-state checks in v1
        return CheckResult.NOT_SATISFIED

    def install(self, item: PlanItem) -> None:
        env: Dict[str, str] = dict(os.environ)
        env.update(
            {
                "TOOL_INSTALLER_TOOL_NAME": item.tool.reference.name,
                "TOOL_INSTALLER_VERSION": item.tool.reference.version,
                "TOOL_INSTALLER_OS": item.environment.os,
                "TOOL_INSTALLER_ARCH": item.environment.arch,
                "TOOL_INSTALLER_FORCE": "true" if item.strategy.force else "false",
            }
        )
        result = subprocess.run([item.strategy.fields["path"]], check=False, env=env)
        if result.returncode != 0:
            raise InstallationError(f"Script failed for {item.tool.reference.name}")
