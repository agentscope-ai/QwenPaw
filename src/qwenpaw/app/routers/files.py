# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse

from qwenpaw.constant import WORKING_DIR
from qwenpaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
    _normalize_path,
)

router = APIRouter(prefix="/files", tags=["files"])

_ALLOWED_ROOT: Path = WORKING_DIR.resolve()

# Reuse the FileGuard sensitive path detection for the preview endpoint.
_file_guardian = FilePathToolGuardian()


def _is_preview_outside_workspace_allowed() -> bool:
    """Check ``security.file_guard.allow_preview_outside_workspace``."""
    try:
        from qwenpaw.platform_ops.security_policy import (
            load_effective_security_policy,
        )

        return bool(
            load_effective_security_policy().file_guard.allow_preview_outside_workspace
        )
    except Exception:
        return False


def _check_path(path: Path) -> str | None:
    """Return ``None`` when *path* is allowed, or an error reason string.

    When ``allow_preview_outside_workspace`` is enabled, skip the
    WORKING_DIR containment check so that console can preview files
    (e.g. media produced by tools) stored outside the workspace.
    The sensitive-file guard is **always** enforced.
    """
    resolved = path.resolve()
    # 1. Must not be a FileGuard-sensitive path.
    normalized = _normalize_path(str(resolved))
    guardian = _file_guardian
    try:
        from qwenpaw.identity.runtime import is_multi_user_enabled

        if is_multi_user_enabled():
            guardian = FilePathToolGuardian()
    except Exception:
        pass
    # pylint: disable-next=protected-access
    if guardian._is_sensitive(normalized):
        return "SENSITIVE_FILE_BLOCKED"
    # 2. Workspace scope check (skippable via config).
    if not _is_preview_outside_workspace_allowed():
        if not (resolved == _ALLOWED_ROOT or resolved.is_relative_to(_ALLOWED_ROOT)):
            return "OUTSIDE_WORKSPACE"
    return None


async def _is_owned_legacy_attachment(path: Path, user_id) -> bool:
    """旧附件目录中的文件必须有匹配用户和 Agent 的有效归属记录。"""
    try:
        relative = path.relative_to(WORKING_DIR.resolve() / "workspaces")
    except ValueError:
        return False
    if len(relative.parts) < 3 or relative.parts[1] not in {"media", "documents", "资料"}:
        return False
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.app.chats.repo import PostgresConversationRepository
    from qwenpaw.identity.runtime import get_identity_schema
    from qwenpaw.artifacts.service import reject_symlink_path

    agent_id = agent_database_id(relative.parts[0])
    repository = PostgresConversationRepository(
        schema=get_identity_schema(),
    ).with_user(user_id)
    attachments = await repository.list_owned_attachments(
        owner_user_id=user_id, agent_id=agent_id,
    )
    for record in attachments:
        if (record.owner_user_id != user_id or record.agent_id != agent_id
                or record.lifecycle == "deleted"):
            continue
        source = Path(record.storage_key)
        try:
            reject_symlink_path(source)
        except ValueError:
            continue
        if source.resolve() == path:
            return True
    return False


async def _is_owned_registered_artifact(path: Path, user_id, agent_key: str) -> bool:
    """旧路径预览也须依据有效产物登记，不把路径本身当成永久授权。"""
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.artifacts.repository import PostgresArtifactRepository
    from qwenpaw.artifacts.service import ArtifactNotFound, ArtifactService
    from qwenpaw.identity.runtime import get_identity_schema

    repository = PostgresArtifactRepository(schema=get_identity_schema())
    records = await repository.list_active(
        owner_user_id=user_id, agent_id=agent_database_id(agent_key),
    )
    service = ArtifactService(repository=repository, working_dir=WORKING_DIR)
    root = WORKING_DIR.resolve() / "user_workspaces" / str(user_id) / agent_key
    for record in records:
        if (record.owner_user_id != user_id or record.agent_id != agent_database_id(agent_key)
                or record.status != "active" or (root / record.relative_path).resolve() != path):
            continue
        try:
            _, registered_path = await service.download_owned_path(
                owner_user_id=user_id, artifact_id=record.id,
            )
        except ArtifactNotFound:
            continue
        if registered_path == path:
            return True
    return False


async def _authorize_private_preview(request: Request, path: Path, unresolved_path: Path) -> None:
    """已登记本人内容保留读取权；其余工作文件仍校验实时 Agent 权限。"""
    from qwenpaw.access.dependencies import get_actor
    from qwenpaw.app.agent_context import get_agent_for_request
    from qwenpaw.artifacts.service import reject_symlink_path

    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    user_root = WORKING_DIR.resolve() / "user_workspaces" / str(actor.user_id)
    try:
        reject_symlink_path(unresolved_path)
        reject_symlink_path(user_root)
        if path.is_relative_to(user_root):
            relative = path.relative_to(user_root)
            if len(relative.parts) < 2:
                raise ValueError()
            agent_key = relative.parts[0]
            persistent_owned = (
                relative.parts[1:3] == ("artifacts", ".registered")
                and await _is_owned_registered_artifact(path, actor.user_id, agent_key)
            )
        else:
            if not await _is_owned_legacy_attachment(path, actor.user_id):
                raise ValueError()
            agent_key = path.relative_to(WORKING_DIR.resolve() / "workspaces").parts[0]
            persistent_owned = True
        if persistent_owned:
            return
        # 旧 file:// 媒体链接没有请求头时，可从已确认本人归属的受控路径取 Agent。
        # 显式选择了另一个 Agent 的请求则不能借此跨越作用域。
        selected = (getattr(request.state, "agent_id", None), request.headers.get("X-Agent-Id"))
        if any(value and value != agent_key for value in selected):
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=403, detail="OUTSIDE_USER_WORKSPACE") from None
    await get_agent_for_request(request, agent_id=agent_key, recheck_access=True)


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file",
)
async def preview_file(
    filepath: str,
    request: Request,
):
    """Preview file."""
    # ASGI 已解码路径一次；再次 unquote 会改写真实含 % 字符的文件名。
    normalized = filepath

    # Normalize /C:/... to C:/... on Windows.
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = Path("/" + normalized)
    unresolved_path = path.absolute()
    path = path.resolve()
    from qwenpaw.identity.runtime import is_multi_user_enabled

    if is_multi_user_enabled():
        await _authorize_private_preview(request, path, unresolved_path)
    reason = _check_path(path)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    if not os.access(path, os.R_OK):
        raise HTTPException(status_code=500, detail="Permission denied")
    return FileResponse(path, filename=path.name)
