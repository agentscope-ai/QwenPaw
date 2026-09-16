# -*- coding: utf-8 -*-
"""共享应用工作区的不可变发布快照。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4


class SnapshotBuildError(RuntimeError):
    """源工作区不能安全固化。"""


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    publication_id: UUID
    path: Path
    workspace_key: str
    workspace_hash: str
    files: tuple[str, ...]


class PublicationSnapshotBuilder:
    """把允许发布的文件复制到按 publication 隔离的只读基线。"""

    _EXCLUDED_DIRS = frozenset(
        {".git", ".pytest_cache", "__pycache__", "sessions", "chats", "attachments", "tmp"}
    )
    _EXCLUDED_FILES = frozenset({".env", "audit.db", "chats.json"})
    _SECRET_SUFFIXES = (".secret", ".token", ".key")

    def __init__(self, working_dir: Path) -> None:
        self.working_dir = Path(working_dir).expanduser().resolve()

    def build(self, source: Path, publication_id: UUID) -> SnapshotResult:
        source = Path(source).expanduser().resolve()
        if not source.is_dir():
            raise SnapshotBuildError("snapshot_source_not_found")
        root = self.working_dir / "published_workspaces"
        target = root / str(publication_id)
        if target.exists():
            raise SnapshotBuildError("publication_snapshot_exists")
        staging = root / ".staging" / f"{publication_id}.{uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        digest = hashlib.sha256()
        copied: list[str] = []
        try:
            for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
                relative = path.relative_to(source)
                if path.is_symlink():
                    raise SnapshotBuildError("snapshot_symlink_denied")
                if self._excluded(relative):
                    continue
                if path.is_dir():
                    continue
                relative_key = relative.as_posix()
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                destination.write_bytes(data)
                digest.update(relative_key.encode("utf-8"))
                digest.update(b"\x00")
                digest.update(data)
                digest.update(b"\x00")
                copied.append(relative_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        return SnapshotResult(
            publication_id=publication_id,
            path=target,
            workspace_key=f"published_workspaces/{publication_id}",
            workspace_hash=digest.hexdigest(),
            files=tuple(copied),
        )

    def verify(self, workspace_key: str, expected_hash: str) -> bool:
        """重新计算已发布基线摘要，拒绝路径替换和内容漂移。"""
        expected_key = workspace_key.replace("\\", "/")
        if not re.fullmatch(r"published_workspaces/[0-9a-f-]{36}", expected_key):
            return False
        source = self.working_dir.joinpath(*expected_key.split("/"))
        try:
            source = source.resolve(strict=True)
            source.relative_to((self.working_dir / "published_workspaces").resolve())
        except (OSError, ValueError):
            return False
        if not source.is_dir() or source.is_symlink():
            return False
        digest = hashlib.sha256()
        try:
            for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
                relative = path.relative_to(source)
                if path.is_symlink():
                    return False
                if self._excluded(relative) or path.is_dir():
                    continue
                digest.update(relative.as_posix().encode("utf-8"))
                digest.update(b"\x00")
                digest.update(path.read_bytes())
                digest.update(b"\x00")
        except OSError:
            return False
        return digest.hexdigest() == expected_hash

    def _excluded(self, relative: Path) -> bool:
        if any(part in self._EXCLUDED_DIRS for part in relative.parts[:-1]):
            return True
        name = relative.name.lower()
        return name in self._EXCLUDED_FILES or name.endswith(self._SECRET_SUFFIXES)
