"""TOML loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Union

from .errors import ConfigError

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    from .vendor import tomli as _toml  # type: ignore[no-redef]


def load_toml(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a TOML document from *path*.

    Raises ConfigError with path context for expected user-facing failures.
    """
    toml_path = Path(path)
    try:
        with toml_path.open("rb") as file:
            data = _toml.load(file)
    except FileNotFoundError as exc:
        raise ConfigError(f"TOML file not found: {toml_path}") from exc
    except IsADirectoryError as exc:
        raise ConfigError(f"TOML path is a directory: {toml_path}") from exc
    except PermissionError as exc:
        raise ConfigError(f"TOML file is not readable: {toml_path}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read TOML file {toml_path}: {exc}") from exc
    except _toml.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {toml_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"TOML root must be a table: {toml_path}")
    return data
