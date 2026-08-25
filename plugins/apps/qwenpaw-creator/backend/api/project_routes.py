# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=try-except-raise
"""File-native Project lifecycle routes.

``project.json`` and its Project-local ``runtime/`` tree are the only durable
authorities used here.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import stat as stat_module
import zipfile
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from pathlib import Path, PurePosixPath

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Response,
    status,
    Request,
)
from fastapi.responses import StreamingResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.routing import Match
from starlette.types import Scope
from starlette.datastructures import UploadFile

from domain.errors import (
    ConflictError,
    StorageIntegrityError,
    ValidationError,
    BadRequestError,
)
from schemas.projects import (
    ExecutionPreauthorizationPolicy,
    ProjectCreateRequest,
    ProjectCreateResponse,
)
from services.file_agent_runtime import (
    interrupt_creator_agent_runtime,
    notify_creator_agent_runtime,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ExecutionPreauthorization,
    Project,
    ProjectSettings,
)
from services.project_files.store import (
    ProjectAlreadyExists,
    ProjectIntegrityError,
    ProjectNotFound,
    ProjectStoreError,
    _safe_project_id,
)
from services.runtime_files.errors import RuntimeFileError
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.session_store import (
    ProjectRuntimeBootstrap,
    RuntimeSessionNotFound,
)
from services.storage_root import require_creator_data_root
from services.project_files.serialization import load_project_json
from utils.logger import setup_logger
from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)

logger = setup_logger("project_routes")

_CREATE_SCOPE = "POST /projects"
_COPY_SCOPE = "POST /projects/{project_id}/copy"


def _log_safe(value: Any) -> str:
    """Neutralize CR/LF in user-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


# Hard limits for project archive imports. The zip cap bounds what a
# request may write to disk; the extraction caps stop zip bombs before
# a single member is inflated.
_IMPORT_MAX_ZIP_BYTES = 2 * 1024 * 1024 * 1024
_IMPORT_MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024
_IMPORT_MAX_MEMBERS = 20000


class _RemovedProjectPutRoute(CreatorErrorRoute):
    """Keep the removed whole-Project PUT absent instead of exposing a 405 alias."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match is Match.PARTIAL and scope.get("method") == "PUT":
            return Match.NONE, child_scope
        return match, child_scope


router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    route_class=_RemovedProjectPutRoute,
)


def _stable_id(kind: str, identity: str) -> str:
    return f"{kind}-{uuid5(NAMESPACE_URL, f'qwenpaw-creator:{kind}:{identity}').hex}"


def _project_snapshot_id(project_id: str, generation: int = 0) -> str:
    return f"project-snapshot-{uuid5(NAMESPACE_URL, f'{project_id}:{generation}').hex}"


def _request_hash(request: ProjectCreateRequest) -> str:
    return IdempotencyRecordStore.request_hash(
        {
            "scope": _CREATE_SCOPE,
            "request": request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        },
    )


def _copy_request_hash(source_project_id: str) -> str:
    return IdempotencyRecordStore.request_hash(
        {
            "scope": _COPY_SCOPE,
            "sourceProjectId": source_project_id,
        },
    )


def _settings(request: ProjectCreateRequest) -> ProjectSettings:
    preauthorization = (
        ExecutionPreauthorization.model_validate(
            request.execution_preauthorization.model_dump(mode="python"),
        )
        if request.execution_preauthorization is not None
        else None
    )
    return ProjectSettings(
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        content_type=request.content_type,
        execution_preauthorization=preauthorization,
    )


def _header(project: Project) -> dict[str, Any]:
    preauthorization = project.settings.execution_preauthorization
    return {
        "id": project.project_id,
        "name": project.name,
        "description": project.description,
        "scenario": project.scenario,
        "aspectRatio": project.settings.aspect_ratio,
        "resolution": project.settings.resolution,
        "contentType": project.settings.content_type,
        **(
            {
                "executionPreauthorization": (
                    ExecutionPreauthorizationPolicy.model_validate(
                        preauthorization.model_dump(mode="python"),
                    ).model_dump(mode="json", by_alias=True)
                ),
            }
            if preauthorization is not None
            else {}
        ),
    }


def _existing_bootstrap(
    services: CreatorFileServices,
    *,
    project_id: str,
    expected_session_id: str,
    expected_conversation_id: str,
    request_hash: str,
) -> ProjectCreateResponse:
    services.projects.read(project_id)
    session = services.sessions.get_project_session(project_id)
    conversations = services.sessions.list_conversations(
        project_id,
        session.session_id,
    )
    defaults = [item for item in conversations if item.is_default]
    if len(defaults) != 1:
        raise StorageIntegrityError(
            "Project Runtime 必须且只能有一个默认 Conversation",
        )
    create_metadata = session.metadata.get("projectCreate")
    if not isinstance(create_metadata, dict):
        raise ConflictError("Project 已存在但缺少文件创建幂等记录")
    if create_metadata.get("requestHash") != request_hash:
        raise ConflictError("clientRequestId 已用于不同 Project payload")
    project_snapshot_id = create_metadata.get("projectSnapshotId")
    stored_response = create_metadata.get("response")
    if (
        session.session_id != expected_session_id
        or defaults[0].conversation_id != expected_conversation_id
        or not isinstance(project_snapshot_id, str)
        or not project_snapshot_id
    ):
        raise StorageIntegrityError("Project Runtime 创建记录与确定性身份不一致")
    try:
        response = ProjectCreateResponse.model_validate(stored_response)
    except PydanticValidationError as exc:
        raise StorageIntegrityError("Project 创建响应快照损坏") from exc
    if (
        response.project_id != project_id
        or response.creator_session_id != expected_session_id
        or response.conversation_id != expected_conversation_id
        or response.project_snapshot_id != project_snapshot_id
        or response.header.get("id") != project_id
    ):
        raise StorageIntegrityError("Project 创建响应快照身份不一致")
    return response


def _existing_copy_receipt(
    services: CreatorFileServices,
    *,
    target_project_id: str,
    expected_session_id: str,
    expected_conversation_id: str,
    client_request_id: str,
    request_hash: str,
) -> dict[str, str]:
    """Validate and replay one atomically published Project copy receipt."""

    services.projects.read(target_project_id)
    session = services.sessions.get_project_session(target_project_id)
    conversations = services.sessions.list_conversations(
        target_project_id,
        session.session_id,
    )
    defaults = [item for item in conversations if item.is_default]
    if len(defaults) != 1:
        raise StorageIntegrityError(
            "复制 Project Runtime 必须且只能有一个默认 Conversation",
        )
    receipt = session.metadata.get("projectCopy")
    if not isinstance(receipt, dict):
        raise ConflictError("Idempotency-Key 已用于非复制 Project 请求")
    if (
        receipt.get("clientRequestId") != client_request_id
        or receipt.get("requestHash") != request_hash
    ):
        raise ConflictError("Idempotency-Key 已用于不同的 Project 复制请求")
    if (
        session.session_id != expected_session_id
        or defaults[0].conversation_id != expected_conversation_id
        or not isinstance(receipt.get("sourceGeneration"), int)
        or not isinstance(receipt.get("sourceEtag"), str)
        or not receipt.get("sourceEtag")
    ):
        raise StorageIntegrityError("Project 复制记录与确定性身份不一致")
    stored_response = receipt.get("response")
    if stored_response != {"projectId": target_project_id}:
        raise StorageIntegrityError("Project 复制响应快照损坏")
    return {"projectId": target_project_id}


@router.get("")
async def list_projects(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: Literal["updated_at", "created_at", "name"] = Query("updated_at"),
    sort_order: Literal["asc", "desc"] = Query("desc"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    try:
        records = await asyncio.to_thread(
            services.projects.list,
            sort_by,
            sort_order,
        )
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    page = records[offset : offset + limit]

    def _build_items() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in page:
            try:
                session = services.sessions.get_project_session_snapshot(
                    item.project_id,
                )
                session_status: str | None = session.status.value
            except RuntimeSessionNotFound:
                session_status = None
            items.append(
                {
                    "projectId": item.project_id,
                    "name": item.name,
                    "description": item.description,
                    "scenario": item.scenario,
                    "aspectRatio": item.aspect_ratio,
                    "resolution": item.resolution,
                    "contentType": item.content_type,
                    "createdAt": item.created_at,
                    "updatedAt": item.updated_at,
                    "coverVersionId": item.cover_version_id,
                    "coverVersionSource": item.cover_version_source,
                    "finalVideoVersionId": item.final_video_version_id,
                    "status": session_status,
                },
            )
        return items

    return {
        "items": await asyncio.to_thread(_build_items),
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "",
    response_model=ProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    request: ProjectCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> ProjectCreateResponse:
    client_request_id = resolve_idempotency_key(
        idempotency_key,
        stable_client_id=request.client_request_id,
    )
    request_hash = _request_hash(request)
    project_id = _stable_id("project", client_request_id)
    session_id = _stable_id("session", client_request_id)
    conversation_id = _stable_id("conversation", client_request_id)
    goal_id = _stable_id("goal", client_request_id)
    message_id = _stable_id("message", client_request_id)
    project_snapshot_id = _project_snapshot_id(project_id)
    project = Project.new(
        project_id=project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        scenario=request.scenario,
        settings=_settings(request),
    )
    initial_response = ProjectCreateResponse(
        projectId=project_id,
        creatorSessionId=session_id,
        conversationId=conversation_id,
        projectSnapshotId=project_snapshot_id,
        header=_header(project),
    )

    def operation() -> ProjectCreateResponse:
        # The name-uniqueness check and the create must share one
        # cross-process lock; per-project lifecycle locks have different
        # domains for different project ids.
        with CrossProcessFileLock(
            services.projects.root / ".project-names.lock",
        ):
            existing = services.projects.list()
            target_name = request.name.strip()
            if any(item.name == target_name for item in existing):
                raise ValidationError(
                    f"项目名称「{target_name}」已存在，请使用其他名称",
                )

            holder: list[ProjectRuntimeBootstrap] = []

            def initialize(staged_project_root) -> None:
                holder.append(
                    services.sessions.initialize_staged_project(
                        staged_project_root,
                        project_id,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        session_metadata={
                            "projectCreate": {
                                "clientRequestId": client_request_id,
                                "requestHash": request_hash,
                                "projectSnapshotId": project_snapshot_id,
                                "response": initial_response.model_dump(
                                    mode="json",
                                    by_alias=True,
                                ),
                            },
                        },
                        initial_goal=request.initial_goal,
                        goal_id=goal_id
                        if request.initial_goal is not None
                        else None,
                        initial_message_id=(
                            message_id
                            if request.initial_goal is not None
                            else None
                        ),
                        initial_client_message_id=(
                            f"initial-goal:{client_request_id}"
                            if request.initial_goal is not None
                            else None
                        ),
                    ),
                )

            try:
                snapshot = services.projects.create(
                    project,
                    initialize_staged_project=initialize,
                )
            except ProjectAlreadyExists:
                return _existing_bootstrap(
                    services,
                    project_id=project_id,
                    expected_session_id=session_id,
                    expected_conversation_id=conversation_id,
                    request_hash=request_hash,
                )
        if len(holder) != 1:
            raise StorageIntegrityError("Project Runtime 未随 Project 原子创建")
        services.poller.note_commit(snapshot)
        # Return the response from the durable creation receipt as well.  This
        # makes the first call and every later replay byte-for-byte stable even
        # if project.json is subsequently edited.
        return _existing_bootstrap(
            services,
            project_id=project_id,
            expected_session_id=session_id,
            expected_conversation_id=conversation_id,
            request_hash=request_hash,
        )

    try:
        result = await asyncio.to_thread(operation)
    except (ConflictError, StorageIntegrityError):
        raise
    except (ProjectIntegrityError, ProjectStoreError, RuntimeFileError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    notify_creator_agent_runtime(project_id)
    response.status_code = status.HTTP_201_CREATED
    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> Response:
    # Deletion is naturally idempotent at the filesystem lifecycle boundary:
    # one process atomically renames the Project out of discovery and every
    # concurrent/replayed request observes the same absent state.
    resolve_idempotency_key(idempotency_key)
    await interrupt_creator_agent_runtime(
        project_id,
        superseded=False,
        reason="project_deleted",
    )
    # Signal every detached provider/review/scheduler worker before the
    # Project id disappears. Cancellation is synchronous; cleanup is not
    # awaited because deletion itself is the terminal boundary.
    from api.file_session_routes import _cancel_detached_project_tasks

    _cancel_detached_project_tasks(services, project_id)
    try:
        await asyncio.to_thread(services.projects.delete, project_id)
    except ProjectNotFound:
        pass
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    services.poller.close(project_id)
    from utils.logger import close_creator_project_logging

    close_creator_project_logging(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/recreate-params")
async def get_recreate_params(
    project_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    logger.info(f"fetching recreate params for:{_log_safe(project_id)}")

    def operation() -> dict[str, Any]:
        snapshot = services.projects.read(project_id)
        project = snapshot.project

        base_name = re.sub(r" copy$", "", project.name)
        base_name = re.sub(r"\s+\d+$", "", base_name)

        existing = services.projects.list()
        max_count = 1
        pattern = re.compile(rf"^{re.escape(base_name)}\s+(\d+)$")
        for item in existing:
            match = pattern.match(item.name)
            if match:
                count = int(match.group(1))
                if count > max_count:
                    max_count = count
        next_name = f"{base_name} {max_count + 1}"

        source_urls: list[str] = []
        for version in project.assets.source_versions_by_id.values():
            url = version.metadata.get("publicSourceUrl")
            if url and isinstance(url, str):
                source_urls.append(url)

        return {
            "name": next_name,
            "description": project.description,
            "scenario": project.scenario,
            "contentType": project.settings.content_type,
            "resolution": project.settings.resolution,
            "aspectRatio": project.settings.aspect_ratio,
            "sourceUrls": source_urls,
        }

    try:
        return await asyncio.to_thread(operation)
    except ProjectNotFound:
        raise
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc


# pylint: disable=too-many-statements
@router.post("/{project_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_project(
    project_id: str,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    logger.info(f"copying project:{_log_safe(project_id)}")
    client_request_id = resolve_idempotency_key(idempotency_key)
    request_hash = _copy_request_hash(project_id)
    copy_identity = f"{_COPY_SCOPE}:{client_request_id}"
    new_project_id = _stable_id("project", copy_identity)
    new_session_id = _stable_id("session", copy_identity)
    new_conversation_id = _stable_id("conversation", copy_identity)

    def operation() -> dict[str, Any]:
        with CrossProcessFileLock(
            services.projects.root / ".project-names.lock",
        ):
            try:
                return _existing_copy_receipt(
                    services,
                    target_project_id=new_project_id,
                    expected_session_id=new_session_id,
                    expected_conversation_id=new_conversation_id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                )
            except ProjectNotFound:
                pass

            # Freeze the source Project and its asset tree at one revision for
            # the whole copy. Project commits/deletion take the exclusive side.
            with services.projects.lifecycle_lock(project_id, shared=True):
                source_snapshot = services.projects.read(project_id)
                source = source_snapshot.project
                source_root = services.projects.project_root(project_id)
                copy_name = f"{source.name} copy"
                existing = services.projects.list()
                base_name = copy_name
                suffix = 1
                while any(item.name == copy_name for item in existing):
                    suffix += 1
                    copy_name = f"{base_name} {suffix}"

                new_project = Project.new(
                    project_id=new_project_id,
                    name=copy_name,
                    description=source.description,
                    scenario=source.scenario,
                    settings=source.settings,
                )
                new_project = new_project.model_copy(
                    update={
                        "strategy": source.strategy,
                        "visual": source.visual,
                        "timelines": source.timelines,
                        "assets": source.assets,
                    },
                )
                initial_response = {"projectId": new_project_id}
                holder: list[ProjectRuntimeBootstrap] = []

                def initialize(staged_root: Path) -> None:
                    assets_src = source_root / "assets"
                    assets_dst = staged_root / "assets"
                    if assets_src.is_dir():
                        for item in assets_src.iterdir():
                            dst = assets_dst / item.name
                            if item.is_dir():
                                shutil.copytree(
                                    str(item),
                                    str(dst),
                                    dirs_exist_ok=True,
                                )
                            else:
                                shutil.copy2(str(item), str(dst))
                    holder.append(
                        services.sessions.initialize_staged_project(
                            staged_root,
                            new_project_id,
                            session_id=new_session_id,
                            conversation_id=new_conversation_id,
                            session_metadata={
                                "projectCopy": {
                                    "clientRequestId": client_request_id,
                                    "requestHash": request_hash,
                                    "sourceProjectId": project_id,
                                    "sourceGeneration": source_snapshot.generation,
                                    "sourceEtag": source_snapshot.etag,
                                    "response": initial_response,
                                },
                            },
                        ),
                    )

                try:
                    snapshot = services.projects.create(
                        new_project,
                        initialize_staged_project=initialize,
                    )
                except ProjectAlreadyExists:
                    return _existing_copy_receipt(
                        services,
                        target_project_id=new_project_id,
                        expected_session_id=new_session_id,
                        expected_conversation_id=new_conversation_id,
                        client_request_id=client_request_id,
                        request_hash=request_hash,
                    )

        if len(holder) != 1:
            raise StorageIntegrityError(
                "Project Runtime 未随复制 Project 原子创建",
            )
        services.poller.note_commit(snapshot)
        return _existing_copy_receipt(
            services,
            target_project_id=new_project_id,
            expected_session_id=new_session_id,
            expected_conversation_id=new_conversation_id,
            client_request_id=client_request_id,
            request_hash=request_hash,
        )

    try:
        result = await asyncio.to_thread(operation)
    except ProjectNotFound:
        raise
    except (ConflictError, StorageIntegrityError):
        raise
    except (ProjectIntegrityError, ProjectStoreError, RuntimeFileError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    notify_creator_agent_runtime(result["projectId"])
    response.status_code = status.HTTP_201_CREATED
    return result


# pylint: enable=too-many-statements


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> StreamingResponse:
    # Export is a read: it must never cancel a running Agent, consume
    # pending messages or mutate session state. The archive is the same
    # best-effort on-disk snapshot documented on ProjectStore.export.
    logger.info(f"exporting project:{_log_safe(project_id)}")
    resolve_idempotency_key(idempotency_key)
    try:
        safe_id = _safe_project_id(project_id)
        # The archive is built on disk first; knowing its exact size lets the
        # download UI show a real percentage instead of an indeterminate bar.
        archive_size, archive_chunks = await asyncio.to_thread(
            services.projects.export,
            project_id,
        )
        return StreamingResponse(
            content=archive_chunks,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_id}.zip"',
                "Content-Length": str(archive_size),
            },
        )
    except Exception as e:
        logger.error(
            f"failed to export project {_log_safe(project_id)}",
            exc_info=True,
        )
        raise StorageIntegrityError(
            message=f"Failed to export project {project_id}: {str(e)}",
        ) from e


def _validate_import_archive(saved_zip: Path) -> None:
    """Preflight the archive with ZipInfo before anything is inflated."""

    try:
        with zipfile.ZipFile(saved_zip) as archive:
            members = archive.infolist()
            if len(members) > _IMPORT_MAX_MEMBERS:
                raise BadRequestError(
                    f"archive holds more than {_IMPORT_MAX_MEMBERS} entries",
                )
            total = 0
            for info in members:
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise BadRequestError(
                        f"archive entry escapes the extraction root: "
                        f"{info.filename!r}",
                    )
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat_module.S_IFLNK:
                    raise BadRequestError(
                        f"archive entry is a symlink: {info.filename!r}",
                    )
                total += info.file_size
                if (
                    info.file_size > _IMPORT_MAX_EXTRACTED_BYTES
                    or total > _IMPORT_MAX_EXTRACTED_BYTES
                ):
                    raise BadRequestError(
                        "archive expands beyond the "
                        f"{_IMPORT_MAX_EXTRACTED_BYTES} byte import limit",
                    )
    except zipfile.BadZipFile as e:
        raise BadRequestError(f"not a valid zip archive: {str(e)}") from e


async def _save_upload_to(upload, saved_zip: Path) -> None:
    """Stream the upload to disk, enforcing the archive size cap."""

    try:
        written = 0
        with open(saved_zip, "wb") as f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _IMPORT_MAX_ZIP_BYTES:
                    raise BadRequestError(
                        "uploaded archive exceeds the "
                        f"{_IMPORT_MAX_ZIP_BYTES} byte limit",
                    )
                f.write(chunk)
        logger.info(
            f"zip file size of {_log_safe(saved_zip)}: "
            f"{saved_zip.stat().st_size}",
        )
    except BadRequestError:
        raise
    except Exception as e:
        raise BadRequestError(
            f"failed to save uploaded file to {saved_zip}: {str(e)}",
        ) from e


def _resolve_extracted_project(extract_dir: Path) -> tuple[Path, str]:
    """Locate the single project folder and verify its identity."""

    # extract_dir/project-xxx/, where project-xxx should be the only item
    dirs = list(extract_dir.iterdir())
    if not (
        len(dirs) == 1
        and dirs[0].is_dir()
        and dirs[0].name.startswith("project-")
        and dirs[0].name == _safe_project_id(dirs[0].name)
    ):
        raise BadRequestError(
            f"expecting only one project-* folder from unpacked file: {dirs}",
        )

    project_json_path = dirs[0] / "project.json"
    if not project_json_path.is_file():
        raise BadRequestError(
            "project.json not found in the uploaded data.",
        )

    logger.info(f"loading project obj from {_log_safe(project_json_path)}")
    try:
        project = load_project_json(project_json_path.read_bytes())
        project_id = str(project.project_id)
        if not project_id:
            raise ValueError(
                f"project_id not found in {project_json_path}",
            )
    except Exception as e:
        raise BadRequestError(f"Invalid Project object: {str(e)}") from e

    logger.info(
        f"found project id in {_log_safe(project_json_path)}: "
        f"{_log_safe(project_id)}",
    )
    if project_id != dirs[0].name:
        raise BadRequestError(
            f"archive folder {dirs[0].name!r} does not match "
            f"project.json project_id {project_id!r}",
        )
    return dirs[0], project_id


async def _run_import(upload) -> str:
    data_root = require_creator_data_root()
    imports_root = data_root / "imports"
    imports_root.mkdir(parents=True, exist_ok=True)

    uploaded_file = Path(upload.filename or "import.zip").name
    # Save the uploaded zip into the imports folder, then extract
    # it there so we can inspect project.json before publishing.
    temp_str = uuid4().hex
    saved_zip = imports_root / f"{temp_str}-{uploaded_file}"
    extract_dir = imports_root / f"{temp_str}"
    try:
        await _save_upload_to(upload, saved_zip)
        await asyncio.to_thread(_validate_import_archive, saved_zip)

        extract_dir.mkdir(mode=0o700)
        try:
            await asyncio.to_thread(
                shutil.unpack_archive,
                str(saved_zip),
                extract_dir=extract_dir,
                format="zip",
            )
            logger.info(
                f"unpacked zip file {_log_safe(saved_zip)} to {extract_dir}",
            )
        except Exception as e:
            raise BadRequestError(
                f"failed to unpack zip file {saved_zip}: {str(e)}",
            ) from e

        project_dir, project_id = _resolve_extracted_project(extract_dir)

        target_project_dir = Path(data_root, project_dir.name)
        if target_project_dir.exists():
            raise BadRequestError(
                f"project already exists {target_project_dir}",
            )
        # move the unpacked project-*** folder into creator data root so the
        # Project directory is published under its real project_id.
        await asyncio.to_thread(shutil.move, project_dir, data_root)
        logger.info(
            f"moved project folder {_log_safe(project_dir)} to {data_root}",
        )
        return project_id
    finally:
        saved_zip.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
        logger.info(
            "deleted temporary importing file and folder "
            f"{_log_safe(saved_zip)}, {extract_dir}",
        )


@router.post("/import")
async def import_project(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    logger.info(
        f"import request, idempotency_key:{_log_safe(idempotency_key)}",
    )
    resolve_idempotency_key(idempotency_key)
    form = await request.form()
    logger.debug("import request, form is ready")
    for k, v in form.multi_items():
        logger.debug(
            f"import request form, k:{_log_safe(k)}, v: type:{type(v)}",
        )
    upload = next(
        (
            value
            for _, value in form.multi_items()
            if isinstance(value, UploadFile)
        ),
        None,
    )
    if upload is None:
        raise BadRequestError("No uploaded file in the request")

    try:
        project_id = await _run_import(upload)
    except Exception as e:
        logger.error("failed to import project", exc_info=True)
        raise BadRequestError(f"Failed to import project: {str(e)}") from e
    return {"projectId": project_id}
