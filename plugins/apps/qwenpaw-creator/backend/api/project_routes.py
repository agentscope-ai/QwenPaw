# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=try-except-raise
"""File-native Project lifecycle routes.

``project.json`` and its Project-local ``runtime/`` tree are the only durable
authorities used here.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import ValidationError as PydanticValidationError
from starlette.routing import Match
from starlette.types import Scope

from domain.errors import ConflictError, StorageIntegrityError, ValidationError
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
)
from services.runtime_files.errors import RuntimeFileError
from services.runtime_files.idempotency_store import IdempotencyRecordStore
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.session_store import ProjectRuntimeBootstrap

from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)


_CREATE_SCOPE = "POST /projects"


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
    return {
        "items": [
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
            }
            for item in page
        ],
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
                raise ValidationError(f"项目名称「{target_name}」已存在，请使用其他名称")

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
    try:
        await asyncio.to_thread(services.projects.delete, project_id)
    except ProjectNotFound:
        pass
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    services.poller.close(project_id)
    try:
        await asyncio.to_thread(
            services.poller.poll_once,
            project_id,
            force=True,
        )
    except ProjectNotFound:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)
