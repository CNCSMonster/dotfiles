"""Module entry point for ``python -m tool_installer``."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
