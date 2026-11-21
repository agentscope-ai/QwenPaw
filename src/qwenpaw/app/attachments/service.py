"""附件保存与删除的受控生命周期操作。"""
from __future__ import annotations

import os
import hashlib
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ...access.agent_repository import agent_database_id
from ...constant import WORKING_DIR
from ...services.workspace_files import resolve_workspace_path
from ...utils.io_utils import run_sync_io
from ..chats.repo.conversation import AttachmentRecord

DOCUMENTS_DIRECTORY = "documents"
LEGACY_DOCUMENTS_DIRECTORY = "资料"


def resolve_owned_attachment_path(
    record: AttachmentRecord, *, owner_user_id: UUID, working_dir: Path | None = None,
) -> Path:
    """将已登记附件重绑到当前数据根目录，不信任旧服务器绝对路径。"""
    from ...artifacts.service import reject_symlink_path
    from ...workspaces import WorkspaceKind, WorkspaceResolver

    if record.owner_user_id != owner_user_id or record.lifecycle == "deleted":
        raise FileNotFoundError("attachment_not_found")
    base = Path(working_dir if working_dir is not None else WORKING_DIR).expanduser().resolve()
    storage_key = record.storage_key.replace("\\", "/")
    current_prefix = base.as_posix().rstrip("/") + "/"
    # 当前数据根可能自身叫 workspaces；先去掉明确的根，避免误判其父目录。
    matches_current = (
        storage_key.casefold().startswith(current_prefix.casefold())
        if os.name == "nt" else storage_key.startswith(current_prefix)
    )
    parts = (storage_key[len(current_prefix):] if matches_current else storage_key).split("/")
    for index, part in enumerate(parts):
        if part == "user_workspaces":
            if parts[index + 1:index + 2] != [str(owner_user_id)]:
                break
            key_index = index + 2
            private = True
        elif part == "workspaces":
            key_index = index + 1
            private = False
        else:
            continue
        # 根目录一旦确定，后面的同名目录只是文件相对路径，不能重新解释为根。
        if len(parts) <= key_index + 2:
            break
        agent_key = parts[key_index]
        if agent_database_id(agent_key) != record.agent_id:
            break
        relative = "/".join(parts[key_index + 1:])
        allowed = {"media"} if record.lifecycle == "temporary" else {DOCUMENTS_DIRECTORY, LEGACY_DOCUMENTS_DIRECTORY}
        if parts[key_index + 1] not in allowed:
            break
        try:
            runtime = WorkspaceResolver(working_dir=base).resolve(
                kind=WorkspaceKind.USER_RUNTIME, resource_id=agent_key,
                actor_user_id=owner_user_id,
            ).path
            root = runtime if private else base / "workspaces" / agent_key
            reject_symlink_path(root / relative)
            target = resolve_workspace_path(root, relative, portable=True)
            if target.is_file():
                return target
        except (ValueError, OSError):
            pass
        break
    else:
        return _registered_legacy_attachment_path(record, base)
    raise FileNotFoundError("attachment_not_found")


def _registered_legacy_attachment_path(record: AttachmentRecord, base: Path) -> Path:
    """旧自定义目录只接受登记根、原作用域和内容校验同时成立的原件。"""
    from ...artifacts.service import reject_symlink_path
    from ...config import load_config

    digest = record.content_hash.removeprefix("sha256:")
    source = Path(record.storage_key).expanduser()
    if not source.is_absolute() or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise FileNotFoundError("attachment_not_found")
    allowed = {"media"} if record.lifecycle == "temporary" else {DOCUMENTS_DIRECTORY, LEGACY_DOCUMENTS_DIRECTORY}
    for key, profile in load_config().agents.profiles.items():
        if agent_database_id(key) != record.agent_id:
            continue
        root = Path(profile.workspace_dir).expanduser().absolute()
        try:
            relative = source.absolute().relative_to(root)
            if len(relative.parts) < 2 or relative.parts[0] not in allowed:
                continue
            reject_symlink_path(source)
            target = resolve_workspace_path(root, relative.as_posix(), portable=True)
            # 私有目录只走标准所有者解析，不能借自定义登记根改变其归属。
            if any(target.is_relative_to(base / name) for name in ("user_workspaces", "user_libraries")):
                continue
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest.lower():
                return target
        except (ValueError, OSError):
            continue
    raise FileNotFoundError("attachment_not_found")


async def resolve_attachment_runtime_root(*, user_id: UUID, agent_key: str) -> Path:
    """聊天附件按上传者隔离，目录规则不随 Agent 编辑角色变化。"""
    from ...identity.runtime import get_identity_schema
    from ...persistence.agent_user_workspaces import AgentUserWorkspaceRepository
    from ...services import workspace_files
    from ...workspaces import WorkspaceKind, WorkspaceResolver

    resolver = WorkspaceResolver(working_dir=workspace_files.WORKING_DIR)
    runtime = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id=agent_key,
        actor_user_id=user_id,
    )
    root = await run_sync_io(resolver.ensure_standard_directories, runtime)
    await AgentUserWorkspaceRepository(schema=get_identity_schema()).ensure_private(
        user_id=user_id, agent_key=agent_key, workspace_key=runtime.workspace_key,
    )
    return root


class AttachmentLifecycleError(RuntimeError):
    """附件当前状态不允许执行所请求的转换。"""


class AttachmentLifecycleService:
    def __init__(self, *, repository, runtime_root: Path, legacy_media_root: Path | None = None) -> None:
        self._repository, self._root = repository, Path(runtime_root)
        self._legacy_media_root = legacy_media_root

    async def save(self, *, attachment_id: UUID, owner_user_id: UUID, target_path: str | None = None):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None or record.id != attachment_id or record.owner_user_id != owner_user_id:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle != "temporary":
            raise AttachmentLifecycleError("attachment_not_temporary")
        source = self._source_path(record.storage_key, lifecycle="temporary")
        target_path = target_path or record.original_name
        target = resolve_workspace_path(self._documents_root(), target_path, portable=True)
        if not source.is_file() or target.exists():
            raise AttachmentLifecycleError("attachment_source_missing" if not source.is_file() else "attachment_target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._move_without_overwrite(source, target)
        now = datetime.now(UTC)
        try:
            updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="saved", storage_key=str(target), saved_path=target_path, saved_at=now, deleted_at=None, updated_at=now)
            if updated is None:
                raise FileNotFoundError("attachment_not_found")
        except BaseException:
            self._move_without_overwrite(target, source)
            raise
        return updated

    async def move(self, *, attachment_id: UUID, owner_user_id: UUID, target_path: str):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None or record.id != attachment_id or record.owner_user_id != owner_user_id:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle != "saved":
            raise AttachmentLifecycleError("attachment_not_saved")
        source = self._source_path(record.storage_key, lifecycle="saved")
        target = resolve_workspace_path(self._documents_root(), target_path, portable=True)
        if not source.is_file() or target.exists():
            raise AttachmentLifecycleError("attachment_source_missing" if not source.is_file() else "attachment_target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._move_without_overwrite(source, target)
        now = datetime.now(UTC)
        try:
            updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="saved", storage_key=str(target), saved_path=target_path, saved_at=record.saved_at, deleted_at=None, updated_at=now)
            if updated is None:
                raise FileNotFoundError("attachment_not_found")
        except BaseException:
            self._move_without_overwrite(target, source)
            raise
        return updated

    async def delete(self, *, attachment_id: UUID, owner_user_id: UUID):
        record = await self._repository.get_attachment(attachment_id=attachment_id, owner_user_id=owner_user_id)
        if record is None or record.id != attachment_id or record.owner_user_id != owner_user_id:
            raise FileNotFoundError("attachment_not_found")
        if record.lifecycle == "deleted":
            return record
        source = self._source_path(record.storage_key, lifecycle=record.lifecycle)
        staged = source.with_name(f".{secrets.token_hex(8)}.deleting") if source.is_file() else None
        if staged is not None:
            self._move_without_overwrite(source, staged)
        now = datetime.now(UTC)
        try:
            updated = await self._repository.update_attachment_lifecycle(attachment_id=attachment_id, owner_user_id=owner_user_id, lifecycle="deleted", storage_key=record.storage_key, saved_path=record.saved_path, saved_at=record.saved_at, deleted_at=now, updated_at=now)
            if updated is None:
                raise FileNotFoundError("attachment_not_found")
        except BaseException:
            if staged is not None:
                self._move_without_overwrite(staged, source)
            raise
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                # 删除原件失败时先保留可恢复文件，再恢复其原登记。
                self._move_without_overwrite(staged, source)
                await self._repository.update_attachment_lifecycle(
                    attachment_id=attachment_id, owner_user_id=owner_user_id,
                    lifecycle=record.lifecycle, storage_key=record.storage_key,
                    saved_path=record.saved_path, saved_at=record.saved_at,
                    deleted_at=record.deleted_at, updated_at=record.updated_at,
                )
                raise
        return updated

    @staticmethod
    def _move_without_overwrite(source: Path, target: Path) -> None:
        """独占创建目标后移除源，不覆盖并发出现的文件，也不依赖硬链接。"""
        created = None
        try:
            with target.open("xb") as destination:
                created = os.fstat(destination.fileno())
                with source.open("rb") as origin:
                    shutil.copyfileobj(origin, destination)
            source.unlink()
        except BaseException:
            if created is not None:
                try:
                    current = target.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if os.path.samestat(created, current):
                        target.unlink()
            raise

    def _source_path(self, storage_key: str, *, lifecycle: str) -> Path:
        try:
            from ...artifacts.service import reject_symlink_path
            source = Path(storage_key)
            reject_symlink_path(source)
            source = source.resolve(strict=False)
            roots = (
                tuple(root.resolve() for root in (self._root / "media", self._legacy_media_root) if root is not None)
                if lifecycle == "temporary" else self._saved_roots()
            )
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
        roots = [self._root]
        if self._legacy_media_root is not None:
            roots.append(self._legacy_media_root.parent)
        return tuple(
            (root / directory).resolve()
            for root in roots
            for directory in (DOCUMENTS_DIRECTORY, LEGACY_DOCUMENTS_DIRECTORY)
        )
