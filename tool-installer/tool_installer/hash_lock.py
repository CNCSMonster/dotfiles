"""Offline, validation-only hash-lock checks; never resolve, download or install.

Both APIs consume already-read UTF-8 text and return a SHA-256 hex digest bound
to the format, requested root and exact input text (including whitespace).
This is a change-detection token, not proof of authenticity or artifact contents.
Python accepts a deliberately restricted requirements grammar: one physical line
per named package, == numeric release (optional a/b/rc/post/dev suffix), and one
or more --hash=sha256:<64 hex> tokens. Blank/full-comment lines are allowed;
extras, markers, continuations, URLs and all other options are not. Every listed
transitive must be pinned and hashed; this does NOT prove closure completeness.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any, Dict
from urllib.parse import urlsplit

from .errors import ConfigError

_NPM_NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", re.ASCII)
_NPM_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", re.ASCII,
)
_PY_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", re.ASCII)
_PY_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?", re.ASCII)
_HASH = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}", re.ASCII)


def _digest(kind: str, text: str, pkg: str, version: str) -> str:
    payload = json.dumps(["hash-lock-v1", kind, pkg, version, text], ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _target(text: str, pkg: str, version: str, python: bool = False) -> None:
    name_re, version_re = (_PY_NAME, _PY_VERSION) if python else (_NPM_NAME, _NPM_VERSION)
    if not isinstance(text, str):
        raise ConfigError("Hash lock must be text")
    if not isinstance(pkg, str) or not name_re.fullmatch(pkg):
        raise ConfigError("Invalid hash-lock root package")
    if not isinstance(version, str) or not version_re.fullmatch(version):
        raise ConfigError("Hash-lock root version must be exact")


def _object(pairs: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("Duplicate JSON key in npm lock")
        result[key] = value
    return result


def _integrity(value: Any) -> None:
    if not isinstance(value, str) or not value.split():
        raise ConfigError("npm package requires integrity")
    for token in value.split():
        algorithm, separator, encoded = token.partition("-")
        if not separator or algorithm not in {"sha256", "sha512"}:
            raise ConfigError("npm integrity requires sha256 or sha512 SRI")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ConfigError("Malformed npm SRI base64") from exc
        if len(raw) != {"sha256": 32, "sha512": 64}[algorithm] or base64.b64encode(raw).decode("ascii") != encoded:
            raise ConfigError("Malformed npm SRI digest")


def _remote(record: Any) -> None:
    if not isinstance(record, dict):
        raise ConfigError("npm package record must be an object")
    if "link" in record or "inBundle" in record or "bundled" in record:
        raise ConfigError("npm linked/bundled packages are unsupported")
    version = record.get("version")
    if not isinstance(version, str) or not _NPM_VERSION.fullmatch(version):
        raise ConfigError("npm package version must be exact")
    resolved = record.get("resolved")
    try:
        url = urlsplit(resolved) if isinstance(resolved, str) else None
        valid = url is not None and url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and not url.fragment and not any(c.isspace() for c in resolved)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("npm package requires an HTTPS archive URL")
    _integrity(record.get("integrity"))


def validate_npm_lock(text: str, pkg: str, version: str) -> str:
    """Validate package-lock v2/v3 with exactly one direct production root.

    Every non-root packages entry (including optional/dev entries) needs exact
    semver, HTTPS resolved URL and canonical sha256/sha512 SRI. Workspaces,
    links, bundled packages and alternate root dependency groups are rejected.
    v2's redundant dependencies tree, when present, is checked too. Dependency
    edge ranges are not installed versions and need not be exact. No resolver
    or archive-content verification is performed; dependency closure completeness
    is not proven. Redundant legacy records must agree with a packages record.
    """
    _target(text, pkg, version)
    try:
        data = json.loads(text, object_pairs_hook=_object)
    except (ValueError, RecursionError) as exc:
        raise ConfigError("Invalid npm lock JSON") from exc
    if not isinstance(data, dict) or type(data.get("lockfileVersion")) is not int or data["lockfileVersion"] not in (2, 3):
        raise ConfigError("npm lockfileVersion must be 2 or 3")
    packages = data.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise ConfigError("npm lock requires packages root")
    root = packages[""]
    if root.get("dependencies") != {pkg: version}:
        raise ConfigError("npm root dependencies must equal requested package/version")
    if any(root.get(key) for key in ("devDependencies", "optionalDependencies", "peerDependencies", "workspaces")):
        raise ConfigError("npm alternate root dependency groups are unsupported")
    if any(key in root for key in ("link", "resolved", "integrity")):
        raise ConfigError("Invalid npm root package record")
    for path, record in packages.items():
        if not path:
            continue
        # Only node_modules paths, including scoped and nested packages.
        parts = path.split("/node_modules/")
        first = parts[0].removeprefix("node_modules/")
        if not path.startswith("node_modules/") or not _NPM_NAME.fullmatch(first) or any(not _NPM_NAME.fullmatch(part) for part in parts[1:]):
            raise ConfigError("Invalid npm package path")
        _remote(record)
    direct = packages.get("node_modules/" + pkg)
    if not isinstance(direct, dict) or direct.get("version") != version:
        raise ConfigError("npm direct package version differs from requested root")

    def legacy(tree: Any) -> None:
        if not isinstance(tree, dict):
            raise ConfigError("Invalid npm dependencies tree")
        for name, record in tree.items():
            if not _NPM_NAME.fullmatch(name):
                raise ConfigError("Invalid npm dependency name")
            _remote(record)
            candidates = [value for path, value in packages.items()
                          if path == "node_modules/" + name or path.endswith("/node_modules/" + name)]
            if not any(all(value.get(key) == record.get(key) for key in ("version", "resolved", "integrity")) for value in candidates):
                raise ConfigError("npm legacy record conflicts with packages records")
            if "dependencies" in record:
                legacy(record["dependencies"])

    if "dependencies" in data:
        try:
            legacy(data["dependencies"])
        except RecursionError as exc:
            raise ConfigError("npm dependencies tree is too deep") from exc
    return _digest("npm", text, pkg, version)


def validate_python_lock(text: str, pkg: str, version: str) -> str:
    """Validate restricted hashed requirements, not dependency closure or files.

    Package identity uses PEP 503 name normalization; root version matches the
    supplied version literally. Duplicate normalized names are rejected.
    """
    _target(text, pkg, version, python=True)
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    pinned: Dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        name, separator, pin = tokens[0].partition("==")
        if not separator or not _PY_NAME.fullmatch(name) or not _PY_VERSION.fullmatch(pin):
            raise ConfigError(f"Invalid pinned requirement on line {number}")
        if len(tokens) < 2 or not all(_HASH.fullmatch(token) for token in tokens[1:]):
            raise ConfigError(f"Requirement needs only sha256 hashes on line {number}")
        normalized = normalize(name)
        if normalized in pinned:
            raise ConfigError(f"Duplicate requirement on line {number}")
        pinned[normalized] = pin
    if pinned.get(normalize(pkg)) != version:
        raise ConfigError("Python lock root differs from requested package/version")
    return _digest("python", text, pkg, version)
