"""GitHub token auto-detection.

Detection order:
1. GITHUB_TOKEN environment variable
2. gh auth token (GitHub CLI)

Returns (token, source_description). Token is None if not available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional, Tuple


def detect_github_token() -> Tuple[Optional[str], str]:
    """Detect GitHub token from environment or gh CLI.

    Returns:
        (token, source) where token is None if not available,
        and source describes where the token came from.
    """
    # 1. Environment variable
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token, "from GITHUB_TOKEN env"

    # 2. gh CLI
    if shutil.which("gh"):
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                gh_token = result.stdout.strip()
                if gh_token:
                    return gh_token, "from gh CLI (gh auth token)"
        except (subprocess.TimeoutExpired, OSError):
            pass

    return None, "not configured (anonymous, 60 req/hour)"
