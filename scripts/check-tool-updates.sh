#!/usr/bin/env bash
# 工具版本新鲜度检查：对比 tools.toml/manifest.toml/mise/config.toml 中锁定的版本
# 与各上游源（crates.io / GitHub releases / npm / PyPI）的最新版。
#
# 原则：本项目所有工具保持锁定版本（可复现、易排查）。本脚本只报告，绝不改动任何锁定。
# 用法: ./scripts/check-tool-updates.sh          # 人类可读表格
#       ./scripts/check-tool-updates.sh --stale   # 仅列出有更新可用的条目
#
# 依赖: python3；GitHub release 查询优先用已登录的 gh（无限流），无 gh 时匿名 API（60/小时）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "${SCRIPT_DIR}" "$@" <<'PYEOF'
import json, os, re, subprocess, sys, urllib.request

root = os.path.abspath(os.path.join(sys.argv[1], ".."))
stale_only = "--stale" in sys.argv[2:]

def load(path):
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (ImportError, FileNotFoundError):
        return None

tools_toml  = load(os.path.join(root, "tools.toml"))
manifest    = load(os.path.join(root, "manifest.toml"))
mise_conf   = load(os.path.join(root, "mise", "config.toml"))

UA = {"User-Agent": "dotfiles-check-tool-updates"}

def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def gh_repo_latest(repo):
    # 优先 gh（带认证 token），失败再匿名 API
    try:
        out = subprocess.run(["gh", "api", f"repos/{repo}/releases/latest",
                              "--jq", ".tag_name"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        return http_json(f"https://api.github.com/repos/{repo}/releases/latest").get("tag_name", "?")
    except Exception as e:
        return f"err:{e}"

def crate_latest(name):
    try:
        d = http_json(f"https://crates.io/api/v1/crates/{name}")
        return d.get("crate", {}).get("max_version", "?")
    except Exception as e:
        return f"err:{e}"

def npm_latest(name):
    try:
        return http_json(f"https://registry.npmjs.org/{name}/latest").get("version", "?")
    except Exception as e:
        return f"err:{e}"

def pypi_latest(name):
    try:
        return http_json(f"https://pypi.org/pypi/{name}/json").get("info", {}).get("version", "?")
    except Exception as e:
        return f"err:{e}"

def norm(v):
    if v is None:
        return "?"
    v = str(v).strip().strip('"').lower()
    return re.sub(r"^v", "", v)

def tool_entry(tool):
    """manifest: 取 linux(优先)/macos 段的 manager + pkg/repo"""
    t = manifest.get(tool) if manifest else None
    if not isinstance(t, dict):
        return None
    for plat in ("linux", "macos"):
        p = t.get(plat)
        if isinstance(p, dict) and "manager" in p:
            return p
    return None

# ── 收集 pinned 清单: (tool, pinned, source) ──
pinned = []
if tools_toml:
    for group, entries in tools_toml.items():
        if not isinstance(entries, dict):
            continue
        for key in entries:
            if key in ("depends", "manifest"):
                continue
            m = re.match(r"^([^@]+)@(.+)$", key)
            if m:
                pinned.append((m.group(1), m.group(2), "tools.toml"))
            else:
                pinned.append((key, "-", "tools.toml"))
if mise_conf:
    for name, ver in (mise_conf.get("tools") or {}).items():
        pinned.append((f"mise:{name}", str(ver), "mise/config.toml"))

rows = []
for tool, pin, src in pinned:
    entry = tool_entry(tool)
    mgr = entry.get("manager") if entry else None
    latest = None
    kind = ""

    if tool.startswith("mise:"):
        rows.append((tool, pin, "-", "mise", "skip(mise)"))
        continue
    if mgr == "cargo-install":
        crate = entry.get("pkg", tool)
        # 一些 crate 名与工具名不同
        crate_map = {"nu": "nu", "fd-find": "fd-find", "bash-lsp": "bash-lsp"}
        latest, kind = crate_latest(crate_map.get(crate, crate)), "crates.io"
    elif mgr == "github-release":
        repo = entry.get("repo")
        if repo:
            latest, kind = gh_repo_latest(repo), "github"
    elif mgr == "npm-global":
        latest, kind = npm_latest(entry.get("pkg", tool)), "npm"
    elif mgr == "uv-tool":
        latest, kind = pypi_latest(entry.get("pkg", tool)), "pypi"
    elif mgr == "rustup":
        latest, kind = "rolling", "rustup"
    elif mgr == "script":
        special = {
            "uv":        lambda: pypi_latest("uv"),
            "wezterm":   lambda: gh_repo_latest("wez/wezterm"),
            "lua-lsp":   lambda: gh_repo_latest("LuaLS/lua-language-server"),
            "rustup-install": lambda: "script",
            "mise-install":   lambda: "script",
            "system-packages":lambda: "apt/brew",
            "fonts":     lambda: "mixed",
        }.get(tool, lambda: "script")
        latest, kind = special(), "special"

    if latest is None:
        status = "skip(no upstream)"
    elif tool == "rust":
        status = "channel(stable)"
    elif pin in ("1", "-"):
        status = "internal(脚本层)"
    elif norm(pin) == norm(latest) or (re.match(r"^\d{8}$", norm(pin)) and norm(latest).startswith(norm(pin))):
        # 后者：wezterm 等按日期前缀锁定 nightly 构建
        status = "up-to-date"
    else:
        status = "UPDATE?"
    rows.append((tool, pin, latest, kind, status))

w = max((len(r[0]) for r in rows), default=4)
print(f"{'TOOL'.ljust(w)}  {'PINNED':<14} {'LATEST':<16} {'SOURCE':<10} STATUS")
print("-" * (w + 52))
stale = 0
for tool, pin, latest, kind, status in rows:
    if status == "UPDATE?":
        stale += 1
    if stale_only and status != "UPDATE?":
        continue
    print(f"{tool.ljust(w)}  {pin:<14} {str(latest):<16} {kind:<10} {status}")
print("-" * (w + 52))
print(f"锁定条目: {len(rows)}  有更新可用: {stale}  （只报告，不自动改动锁定）")
PYEOF
