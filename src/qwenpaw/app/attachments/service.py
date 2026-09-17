"""附件保存与删除的受控生命周期操作。"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ...services.workspace_files import resolve_workspace_path

DOCUMENTS_DIRECTORY = "documents"
LEGACY_DOCUMENTS_DIRECTORY = "资料"


class AttachmentLifecycleError(RuntimeError):
    """附件当前状态不允许执行所请求的转换。"""


class AttachmentLifecycleService:
    def __init__(self, *, repository, runtime_root: Path) -> None:
        self._repository, self._root = repository, Path(runtime_root)

    async def save(self, *, attachment_id: UUID, owner_user_id: UUID, target_path: str | None = None):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle != "temporary":
            raise AttachmentLifecycleError("attachment_not_temporary")
        source = self._source_path(record.storage_key, lifecycle="temporary")
        target_path = target_path or record.original_name
        target = resolve_workspace_path(self._documents_root(), target_path, portable=True)
        if not source.is_file() or target.exists():
            raise AttachmentLifecycleError("attachment_source_missing" if not source.is_file() else "attachment_target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        now = datetime.now(UTC)
        updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="saved", storage_key=str(target), saved_path=target_path, saved_at=now, deleted_at=None, updated_at=now)
        if updated is None:
            os.replace(target, source)
            raise FileNotFoundError("attachment_not_found")
        return updated

    async def move(self, *, attachment_id: UUID, owner_user_id: UUID, target_path: str):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle != "saved":
            raise AttachmentLifecycleError("attachment_not_saved")
        source = self._source_path(record.storage_key, lifecycle="saved")
        target = resolve_workspace_path(self._documents_root(), target_path, portable=True)
        if not source.is_file() or target.exists():
            raise AttachmentLifecycleError("attachment_source_missing" if not source.is_file() else "attachment_target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        now = datetime.now(UTC)
        updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="saved", storage_key=str(target), saved_path=target_path, saved_at=record.saved_at, deleted_at=None, updated_at=now)
        if updated is None:
            os.replace(target, source)
            raise FileNotFoundError("attachment_not_found")
        return updated

    async def delete(self, *, attachment_id: UUID, owner_user_id: UUID):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle == "deleted":
            return record
        source = self._source_path(record.storage_key, lifecycle=record.lifecycle)
        if source.is_file():
            source.unlink()
        now = datetime.now(UTC)
        updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="deleted", storage_key=record.storage_key, saved_path=record.saved_path, saved_at=record.saved_at, deleted_at=now, updated_at=now)
        if updated is None:
            raise FileNotFoundError("attachment_not_found")
        return updated

    def _source_path(self, storage_key: str, *, lifecycle: str) -> Path:
        try:
            source = Path(storage_key).resolve(strict=False)
            roots = ((self._root / "media").resolve(),) if lifecycle == "temporary" else self._saved_roots()
        except OSError as exc:
            raise AttachmentLifecycleError("attachment_source_missing") from exc
        if not any(source.is_relative_to(root) for root in roots) or source.is_symlink():
            raise AttachmentLifecycleError("attachment_source_denied")
        return source

    def _documents_root(self) -> Path:
        """返回新建已保存附件的标准英文目录。"""
        return self._root / DOCUMENTS_DIRECTORY

    def _saved_roots(self) -> tuple[Path, ...]:
        """允许读取历史中文目录，所有新写入仍固定落在 documents/。"""
        return tuple(
            (self._root / directory).resolve()
            for directory in (DOCUMENTS_DIRECTORY, LEGACY_DOCUMENTS_DIRECTORY)
        )
