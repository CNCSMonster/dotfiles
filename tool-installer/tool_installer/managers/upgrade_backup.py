"""工具二进制升级的最小可回滚备份。

只负责「覆盖前留一份旧物 + 一份可核对的 receipt」以及「失败时把旧物还原回去」。
刻意不做：滚动保留 / 自动 GC / 交互确认 / 跟随符号链接读内容。成功后备份默认
**保留**，本模块不提供也不调用任何删除备份的接口（调用方也不应删）。

落点与 setup.sh 的配置部署备份（~/.local/state/dotfiles/deploy-backup/）并列但不同名：
    ~/.local/state/dotfiles/tool-upgrade-backup/<label>-<timestamp>-<pid>-<rand>/
目录用 tempfile.mkdtemp 创建，原子且自带随机后缀，因此同 label、同一秒、多个进程
也不会撞车。

receipt（manifest.json）记录每个目标的绝对路径、原始 sha256（普通文件）或 link
target（符号链接）、以及工具名 / 版本 / 时间戳 / pid，供人工核对与手动回滚。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..errors import InstallationError

MANIFEST_NAME = "manifest.json"
_STATE_REL = Path(".local") / "state" / "dotfiles" / "tool-upgrade-backup"


def state_root_for(home: Path) -> Path:
    """由 home 推导的确定性 state 根目录。

    只做路径拼接，不展开 ~、不解析 passwd、不碰 CWD。调用方若想自己钉死
    落点，可用 UpgradeBackup(..., state_root=...) 直接传入绝对路径。
    """
    return Path(home) / _STATE_REL


def stat_mode(target: Path) -> int:
    """记录原始权限位，便于人工核对（不改变还原逻辑）。"""
    return target.stat().st_mode & 0o7777


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute(path: Path) -> str:
    """绝对路径，但不解析（不跟随）符号链接本身。"""
    return os.path.abspath(os.fspath(path))


def _kind_of(target: Path) -> Optional[str]:
    """判定要备份的对象类型；不存在则 None（首次安装不备份）。"""
    if os.path.islink(target):
        return "symlink"
    if target.is_dir():
        return "dir"
    if target.is_file():
        return "file"
    return None


def _restore_entry(slot: Path, entry: Dict[str, Any]) -> None:
    """把一条 receipt 记录还原到它的绝对路径。"""
    target = Path(entry["absolute_path"])
    kind = entry["kind"]
    stored = slot / entry["backup"]
    target.parent.mkdir(parents=True, exist_ok=True)

    if kind == "dir":
        # 目录无法用 os.replace 原子换掉（目标非空），先在当前目录旁完整重建一份，
        # 再移走现有目录、把重建份改名到位；这样中途失败也不会留下半新半旧状态。
        staged = target.parent / f".restore_{target.name}_{os.getpid()}_{id(entry)}"
        try:
            shutil.copytree(stored, staged, symlinks=True)
            if os.path.islink(target) or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            os.replace(str(staged), str(target))
        finally:
            if staged.exists() and not staged.is_symlink():
                shutil.rmtree(staged, ignore_errors=True)
            elif os.path.lexists(staged):
                try:
                    staged.unlink()
                except OSError:
                    pass
        return

    if kind == "symlink":
        # 只重建链接本身，绝不读取/复制它指向的内容。
        tmp_symlink = target.parent / f".restore_{target.name}_{os.getpid()}_{id(entry)}.link"
        try:
            os.symlink(entry["link_target"], tmp_symlink)
            os.replace(str(tmp_symlink), str(target))
        finally:
            if os.path.lexists(tmp_symlink):
                try:
                    tmp_symlink.unlink()
                except OSError:
                    pass
        return

    # 普通文件：先复制到目标同目录的临时名，再 os.replace 原子覆盖；
    # slot 里的备份字节保持不动，receipt 仍然有效、备份仍然保留。
    tmp_file = target.parent / f".restore_{target.name}_{os.getpid()}_{id(entry)}.tmp"
    try:
        shutil.copy2(stored, tmp_file)
        os.replace(str(tmp_file), str(target))
    finally:
        if os.path.lexists(tmp_file):
            try:
                tmp_file.unlink()
            except OSError:
                pass


def rollback(slot: Path) -> int:
    """读取 slot 里的 manifest.json，逐条还原；返回还原条数。

    供安装失败时自动调用，也供人工凭 receipt 手动回滚（成功后备份仍在）。
    """
    manifest_path = Path(slot) / MANIFEST_NAME
    if not manifest_path.is_file():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    # 逆序还原：目录/入口的还原顺序与备份顺序相反更符合直觉。
    for entry in reversed(entries):
        _restore_entry(Path(slot), entry)
    return len(entries)


class UpgradeBackup:
    """一次工具升级的备份会话。

    构造时不创建目录；只有真的存在需要备份的目标时才惰性建 slot（首次安装
    不产生任何 state 目录）。调用方在 publish 之前依次 backup(...)，在异常路径
    调用 rollback()；成功路径什么都不用做——备份默认保留。
    """

    def __init__(
        self,
        home: Path,
        label: str,
        *,
        tool: str,
        version: str,
        state_root: Optional[Path] = None,
    ) -> None:
        # 显式 state_root 优先（参数化落点）；否则由 home 推导。两者都必须是
        # 绝对路径：不展开 ~、不接受相对路径，绝不把备份悄悄写进当前工作目录。
        root = Path(state_root) if state_root is not None else state_root_for(home)
        if not root.is_absolute():
            raise InstallationError(
                f"升级备份根目录必须是绝对路径（收到 {root!r}）；"
                "拒绝把备份写入当前工作目录。请设置绝对路径的 HOME，或传入显式 state_root。"
            )
        self._root = root
        self._label = label
        self._tool = tool
        self._version = version
        self._slot: Optional[Path] = None
        self._entries: List[Dict[str, Any]] = []
        self._timestamp: Optional[str] = None

    @property
    def slot(self) -> Optional[Path]:
        return self._slot

    @property
    def entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def _ensure_slot(self) -> Path:
        if self._slot is None:
            self._root.mkdir(parents=True, exist_ok=True)
            self._timestamp = time.strftime("%Y%m%d-%H%M%S")
            prefix = f"{self._label}-{self._timestamp}-{os.getpid()}-"
            self._slot = Path(tempfile.mkdtemp(prefix=prefix, dir=self._root))
        return self._slot

    def _write_manifest(self) -> None:
        if self._slot is None:
            return
        receipt = {
            "tool": self._tool,
            "version": self._version,
            "timestamp": self._timestamp,
            "pid": os.getpid(),
            "label": self._label,
            "entries": self._entries,
        }
        (self._slot / MANIFEST_NAME).write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def backup(self, target: Path) -> Optional[Dict[str, Any]]:
        """覆盖前备份一个目标；不存在（或不是文件/链接/目录）时返回 None。

        普通文件：完整旧字节 + 原始 sha256 + mode。
        符号链接：只记 link target，不跟随、不读取指向内容。
        目录：copytree(symlinks=True) 完整旧树（用于 extract_dir 共享目录）。
        """
        target = Path(target)
        kind = _kind_of(target)
        if kind is None:
            return None

        slot = self._ensure_slot()
        index = len(self._entries)
        abs_path = _absolute(target)
        entry: Dict[str, Any] = {
            "absolute_path": abs_path,
            "kind": kind,
        }

        if kind == "symlink":
            entry["link_target"] = os.readlink(target)
            entry["backup"] = ""  # 无字节副本；receipt 自身即备份
            entry["sha256"] = None
        elif kind == "dir":
            stored = slot / f"{index:02d}-{target.name}.tree"
            shutil.copytree(target, stored, symlinks=True)
            entry["backup"] = stored.name
            entry["sha256"] = None
        else:
            stored = slot / f"{index:02d}-{target.name}"
            shutil.copy2(target, stored)
            entry["backup"] = stored.name
            entry["sha256"] = _sha256(target)
            entry["mode"] = stat_mode(target)

        self._entries.append(entry)
        self._write_manifest()
        return entry

    def rollback(self) -> int:
        """失败时还原所有已备份目标；成功后调用方不应调用它。"""
        if self._slot is None:
            return 0
        return rollback(self._slot)
