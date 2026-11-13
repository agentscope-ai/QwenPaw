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
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from pathlib import Path

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
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError
from starlette.routing import Match
from starlette.types import Scope
from starlette.datastructures import UploadFile

from domain.errors import (
    CasConflictError,
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
    BadRequestError,
)
from models.config import (
    EXECUTION_AUTHORIZATION_REQUIRED,
    get_execution_authorization_mode,
)
from schemas.common import StrictModel
from schemas.projects import (
    ExecutionPreauthorizationPolicy,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProductionStageRequest,
    SubtitleAnimationPolicy,
    SubtitleStylePolicy,
)
from services.file_agent_runtime import (
    interrupt_creator_agent_runtime,
    notify_creator_agent_runtime,
)
from services.project_files import archive as project_archive
from services.project_files.archive import (
    extract_archive as _extract_archive_sanitized,
)
from services.project_files.edit_impact import apply_frontend_edit_impacts
from services.project_files.facade import CreatorFileServices
from services.project_files.json_pointer import (
    JsonCasConflict,
    escape_pointer_token,
)
from services.project_files.assets import AssetFileStore
from services.project_files.models import (
    ExecutionPreauthorization,
    OverlayCreation,
    Project,
    ProjectSettings,
    SubtitleAnimation,
    SubtitleStyle,
    is_subtitle_overlay,
)
from services.project_files.store import (
    InvalidProjectId,
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
    SessionStoreError,
)
from services.storage_root import require_creator_data_root
from services.project_files.serialization import load_project_json
from utils.logger import setup_logger
from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
    semantic_etag,
)

logger = setup_logger("project_routes")

_CREATE_SCOPE = "POST /projects"
_COPY_SCOPE = "POST /projects/{project_id}/copy"


def _log_safe(value: Any) -> str:
    """Neutralize CR/LF in user-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


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
storage_router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    route_class=CreatorErrorRoute,
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
    from services.media_files.motion_blueprints import SUBTITLE_TEMPLATE_PACKS

    preauthorization = (
        ExecutionPreauthorization.model_validate(
            request.execution_preauthorization.model_dump(mode="python"),
        )
        if request.execution_preauthorization is not None
        else None
    )
    # The launch form follows the persisted permission ladder. Both full
    # confirmation and cost-only confirmation review the script before any
    # image/video spending; automatic and YOLO launches can keep going.
    # Explicit API stages remain available for intentional script-only work.
    script_first = (
        request.scenario == "short_drama"
        and get_execution_authorization_mode()
        == EXECUTION_AUTHORIZATION_REQUIRED
    )
    # Reject an unknown pack on the way in, the same way the style route does.
    # Persisting one would store a setting that every renderer, prompt and the
    # UI reads back as "smart recommend" — a fourth state nobody can see.
    wanted_template = (request.subtitle_template or "").strip()
    if wanted_template and wanted_template not in SUBTITLE_TEMPLATE_PACKS:
        raise ValidationError(f"未知的字幕风格包：{wanted_template}")
    return ProjectSettings(
        production_stage=request.production_stage
        or ("script" if script_first else "media"),
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        content_type=request.content_type,
        subtitle_policy=request.subtitle_policy or "off",
        subtitle_template=wanted_template or None,
        subtitle_style=(
            SubtitleStyle(**request.subtitle_style.model_dump())
            if request.subtitle_style is not None
            else None
        ),
        subtitle_animation=(
            SubtitleAnimation(**request.subtitle_animation.model_dump())
            if request.subtitle_animation is not None
            else None
        ),
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
        "subtitleTemplate": project.settings.subtitle_template,
        "subtitleStyle": (
            SubtitleStylePolicy.model_validate(
                project.settings.subtitle_style.model_dump(mode="python"),
            ).model_dump(by_alias=True, mode="json")
            if project.settings.subtitle_style is not None
            else None
        ),
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


@storage_router.get("")
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
            except SessionStoreError as exc:
                # One project's corrupt session record (field run
                # 2026-08-25: a session claiming another project) must not
                # take the whole listing down; surface the project without
                # a status and leave the repair to its own detail view.
                logger.warning(
                    "project list: session snapshot failed for %s: %s",
                    item.project_id,
                    exc,
                )
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
    if request.template_id:
        from services.media_files.video_templates import (
            apply_video_template_to_project,
            get_video_template,
        )

        template = get_video_template(request.template_id)
        if template is None:
            from services.media_files.user_templates import (
                load_user_template,
            )
            from services.media_files.video_templates import (
                VideoTemplate,
                VideoTemplateDesignFloor,
            )

            user_tpl = load_user_template(request.template_id)
            if user_tpl is None:
                raise ValidationError(
                    f"未知的视频模板: {request.template_id}",
                )
            template = VideoTemplate(
                template_id=user_tpl.template_id,
                name=user_tpl.name,
                description=user_tpl.description,
                content_type=user_tpl.content_type,
                scenario=user_tpl.scenario,
                opening_caption_blueprint=(user_tpl.opening_caption_blueprint),
                closing_caption_blueprint=(user_tpl.closing_caption_blueprint),
                default_transition_kind=(user_tpl.default_transition_kind),
                transition_blend_seconds=(user_tpl.transition_blend_seconds),
                caption_blueprint_order=tuple(
                    user_tpl.caption_blueprint_order,
                ),
                color_grade=user_tpl.color_grade,
                energy=user_tpl.energy,
                density=user_tpl.density,
                decoration=user_tpl.decoration,
                design_floor=VideoTemplateDesignFloor(
                    opening=user_tpl.design_floor_opening,
                    transitions=user_tpl.design_floor_transitions,
                    body=user_tpl.design_floor_body,
                    ending=user_tpl.design_floor_ending,
                ),
                decoration_catalog=(),
                frame_blueprint="",
                preview_description=user_tpl.preview_description,
                icon_emoji=user_tpl.icon_emoji,
            )
        project = apply_video_template_to_project(project, template)
    initial_response = ProjectCreateResponse(
        projectId=project_id,
        creatorSessionId=session_id,
        conversationId=conversation_id,
        projectSnapshotId=project_snapshot_id,
        header=_header(project),
    )

    def operation() -> ProjectCreateResponse:
        # The global name lock only covers the uniqueness check.  The create
        # itself stages privately and publishes via an atomic rename that
        # refuses an existing Project id, so holding a global boundary across
        # the Runtime bootstrap would only serialize unrelated creations.
        target_name = request.name.strip()
        with CrossProcessFileLock(
            services.projects.root / ".project-names.lock",
        ):
            existing = services.projects.list()
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
                    goal_id=(
                        goal_id if request.initial_goal is not None else None
                    ),
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


@router.post("/{project_id}/production-stage")
async def set_production_stage(
    project_id: str,
    request: ProductionStageRequest,
    services: CreatorFileServices = Depends(project_file_services),
):
    expected = semantic_etag(request.project_etag)
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    if snapshot.etag != expected:
        raise ConflictError("剧本已更新，请查看最新内容后重新确认。")
    candidate = snapshot.project.model_dump(mode="json")
    candidate["settings"]["production_stage"] = request.stage
    result = await services.commit_candidate(
        base=snapshot,
        candidate=candidate,
        origin="frontend_edit",
        review_policy="auto_fix",
        production_stage_confirmation=expected,
    )
    notify_creator_agent_runtime(project_id)
    return {"ok": True, "generation": result.snapshot.generation}


class SubtitleToggleRequest(StrictModel):
    enabled: bool


@router.patch("/{project_id}/subtitles/toggle")
async def toggle_subtitles(
    project_id: str,
    request: SubtitleToggleRequest,
    services: CreatorFileServices = Depends(project_file_services),
):
    """Batch enable or disable all subtitle overlay elements.

    ``is_subtitle_overlay`` is the single definition of what counts as a
    subtitle here, so a pet-OS bubble (which the prompts keep free of
    ``caption_role`` on purpose) is never hidden by the toolbar toggle.
    """

    def operation() -> dict[str, Any]:
        snapshot = services.projects.read(project_id)
        base = snapshot.project.model_dump(mode="json")
        candidate = snapshot.project.model_dump(mode="json")
        content_type = snapshot.project.settings.content_type
        updated_count = 0
        changed: list[str] = []
        captions: list[str] = []
        for timeline_id, timeline in snapshot.project.timelines.items.items():
            # Rolled-back copies are frozen; the work graph never reads them.
            if str(timeline_id).startswith("snapshot:"):
                continue
            for element_id, element in timeline.elements_by_id.items():
                creation = element.creation
                if not isinstance(creation, OverlayCreation):
                    continue
                if not is_subtitle_overlay(
                    text=creation.text,
                    vibe=creation.vibe,
                    caption_role=creation.caption_role,
                    content_type=content_type,
                ):
                    continue
                pointer = (
                    "/timelines/items/"
                    f"{escape_pointer_token(str(timeline_id))}"
                    "/elements_by_id/"
                    f"{escape_pointer_token(str(element_id))}/enabled"
                )
                captions.append(pointer)
                if bool(element.enabled) == request.enabled:
                    continue
                candidate["timelines"]["items"][timeline_id]["elements_by_id"][
                    element_id
                ]["enabled"] = request.enabled
                updated_count += 1
                changed.append(pointer)
        # The final cut bakes captions in, so a toggle has to flag the render
        # stale; committing on its own keeps the previously composed video.
        # Repeating a toggle that changes nothing still refreshes the cut,
        # which recovers videos composed before their captions were hidden.
        if changed:
            candidate, _ = apply_frontend_edit_impacts(
                candidate,
                changed,
                base=base,
            )
        elif captions:
            candidate, _ = apply_frontend_edit_impacts(candidate, captions)
        return {
            "candidate": candidate,
            "snapshot": snapshot,
            "count": updated_count,
        }

    try:
        data = await asyncio.to_thread(operation)
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    except InvalidProjectId as exc:
        raise BadRequestError(str(exc)) from exc
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc

    result = await services.commit_candidate(
        base=data["snapshot"],
        candidate=data["candidate"],
        origin="frontend_edit",
        review_policy="auto_fix",
    )
    notify_creator_agent_runtime(project_id)
    return {
        "ok": True,
        "generation": result.snapshot.generation,
        "toggled": data["count"],
        "enabled": request.enabled,
    }


class SubtitleStyleRequest(StrictModel):
    """One request that changes how subtitles look and keeps copy honest.

    A key that is present wins, so the same call can switch, adjust or go
    back: ``subtitleTemplate`` ``null``/``""`` mean smart recommend and
    ``subtitleStyle`` ``null`` (or an all-default object) clears the colour /
    size / outline overrides.  ``animation`` overrides the pack's signature
    motion for the addressed captions, field by field.
    """

    subtitle_template: str | None = Field(None, alias="subtitleTemplate")
    subtitle_style: SubtitleStylePolicy | None = Field(
        None,
        alias="subtitleStyle",
    )
    animation: SubtitleAnimationPolicy | None = None
    element_ids: list[str] | None = Field(
        None,
        alias="elementIds",
        max_length=500,
    )
    sync_prompts: bool = Field(True, alias="syncPrompts")


@router.patch("/{project_id}/subtitles/style")
async def set_subtitle_style(
    project_id: str,
    request: SubtitleStyleRequest,
    services: CreatorFileServices = Depends(project_file_services),
):
    """Switch the subtitle style pack and keep every layer of it in step.

    Picking a pack used to change only what the creation form remembered:
    the burned-in captions, the live preview and each subtitle's 动效描述
    kept describing the old look until a model happened to redesign them.
    This route writes the setting, redraws the deterministic caption
    documents it owns and fills the canonical style sentence into empty
    descriptions — never overwriting wording a user or an agent wrote.
    """

    from services.media_files.informal_launch_template import (
        uses_informal_launch_captions,
    )
    from services.media_files.motion_blueprints import (
        SUBTITLE_TEMPLATE_PACKS,
        subtitle_pack_prompt_line,
        sync_subtitle_prompt,
    )
    from services.media_files.motion_design import (
        build_caption_document,
        caption_animation_override,
        caption_owned_template,
        design_canvas_size,
        externalize_motion_document,
        normalise_caption_animation,
        pack_caption_animation,
        resolve_caption_animation,
        resolve_caption_location,
    )
    from services.project_files.models import (
        IndexedFile,
        MotionGraphic,
    )

    def operation() -> dict[str, Any]:
        snapshot = services.projects.read(project_id)
        project = snapshot.project
        settings = project.settings
        pack_id = settings.subtitle_template
        # A style pack is a project-wide promise (see the section's own note):
        # scoping it to some captions would leave the rest describing — and
        # drawing — the previous look, which is the drift this route removes.
        if request.element_ids and (
            "subtitle_template" in request.model_fields_set
            or "subtitle_style" in request.model_fields_set
        ):
            raise ValidationError(
                "elementIds 只能配合入场/出场/循环选择；"
                "风格包与覆盖样式始终作用于全项目字幕。",
            )
        # A present key is authoritative, so the UI can also go back:
        # ``null``/``""`` mean smart recommend and an explicit ``null`` style
        # clears every colour / size / outline override.
        if "subtitle_template" in request.model_fields_set:
            wanted = (request.subtitle_template or "").strip()
            if wanted and wanted not in SUBTITLE_TEMPLATE_PACKS:
                raise ValidationError(f"未知的字幕风格包：{wanted}")
            pack_id = wanted or None
        style_model = settings.subtitle_style
        if "subtitle_style" in request.model_fields_set:
            style_model = (
                SubtitleStyle(**request.subtitle_style.model_dump())
                if request.subtitle_style is not None
                else None
            )
            if style_model is not None and not (
                style_model.color
                or style_model.font_scale is not None
                or style_model.stroke_scale is not None
                or style_model.background_opacity is not None
                or style_model.font_family is not None
            ):
                # "No overrides" is stored as no style object at all, so an
                # untouched project keeps serialising exactly as it did.
                style_model = None
        style_json = (
            style_model.model_dump(mode="json")
            if style_model is not None
            else None
        )
        candidate = project.model_dump(mode="json")
        candidate["settings"]["subtitle_template"] = pack_id
        candidate["settings"]["subtitle_style"] = style_json
        # Redrawn documents are published as content-addressed Project files
        # before the commit references them, exactly as the design pass does,
        # so switching a pack here cannot leave a second copy of the truth.
        file_store = AssetFileStore(services.projects.project_root(project_id))
        indexed_files: dict[str, IndexedFile] = {}

        def externalize(document: MotionGraphic) -> dict[str, Any]:
            stored, indexed = externalize_motion_document(document, file_store)
            indexed_files[indexed.file_id] = indexed
            return stored.model_dump(mode="json")
        timelines = candidate["timelines"]["items"]
        # The caption boxes are validated against the same canvas the design
        # pass and the renderer use, so a switch here cannot bake a document
        # the next pass would refuse to repair.
        canvas_size = design_canvas_size(project)
        pointers = ["/settings/subtitle_template", "/settings/subtitle_style"]
        selected = set(request.element_ids or ())
        requested_animation = (
            request.animation.model_dump(exclude_none=True)
            if request.animation is not None
            else None
        )
        synced = 0
        redrawn = 0
        skipped = 0
        for timeline_id, timeline in project.timelines.items.items():
            # Rolled-back copies are frozen, and a 发布会 timeline owns its
            # lettering through the official template: neither is redrawn.
            if str(timeline_id).startswith("snapshot:"):
                continue
            if uses_informal_launch_captions(timeline):
                continue
            items = timelines[str(timeline_id)]["elements_by_id"]
            for element_id, element in timeline.elements_by_id.items():
                creation = element.creation
                if not isinstance(creation, OverlayCreation):
                    continue
                if not is_subtitle_overlay(
                    text=creation.text,
                    vibe=creation.vibe,
                    caption_role=creation.caption_role,
                    content_type=settings.content_type,
                ):
                    continue
                if selected and element_id not in selected:
                    continue
                raw = items.get(str(element_id))
                if not isinstance(raw, dict):
                    continue
                # The element root is what invalidates the composed master;
                # a ``/creation/prompt`` pointer would also throw away a
                # hand-designed document, which a style switch must not do.
                pointers.append(
                    "/timelines/items/"
                    f"{escape_pointer_token(str(timeline_id))}"
                    "/elements_by_id/"
                    f"{escape_pointer_token(str(element_id))}",
                )
                motion = creation.motion
                # Only these two kinds of caption can honour a pack in pixels:
                # the documents this pipeline drew (redrawn below) and a
                # caption with no document at all (the compose-time fallback
                # burns the pack typography into it).  A free-form design, a
                # blueprint 花字 or an authored card owns its own look, so its
                # description must keep describing that — writing the pack
                # sentence into it would invent the very mismatch users report.
                owned = caption_owned_template(motion)
                if not owned and motion is not None:
                    if requested_animation:
                        skipped += 1
                    continue
                override = caption_animation_override(settings)
                animation = normalise_caption_animation(
                    resolve_caption_animation(motion, pack_id, override)
                    if owned
                    else pack_caption_animation(pack_id, override),
                )
                if requested_animation:
                    animation.update(requested_animation)
                if request.sync_prompts:
                    prompt, changed = sync_subtitle_prompt(
                        creation.prompt,
                        pack_id,
                        style_json,
                        animation,
                    )
                    if changed and prompt != creation.prompt:
                        raw["creation"]["prompt"] = prompt
                        synced += 1
                if not owned and not requested_animation:
                    # A caption that never had a document and got no motion
                    # pick keeps waiting for its design pass; a style switch
                    # must not quietly preempt a pending free-form design.
                    continue
                location = resolve_caption_location(
                    text=creation.text,
                    caption_role=creation.caption_role,
                    content_type=settings.content_type,
                    vibe=creation.vibe,
                    location=element.location,
                    canvas_size=canvas_size,
                )
                document, _concept = build_caption_document(
                    text=creation.text,
                    location=location,
                    pack_id=pack_id,
                    style=style_json,
                    animation=animation,
                )
                payload = externalize(document)
                if raw["creation"].get("motion") != payload:
                    raw["creation"]["motion"] = payload
                    redrawn += 1
                if raw.get("location") != location.model_dump(mode="json"):
                    # The document was measured for the box it is being drawn
                    # into, so the element has to end up with that same box;
                    # leaving a narrower one behind would clip the copy again.
                    raw["location"] = location.model_dump(mode="json")
        files_by_id = candidate["assets"]["files_by_id"]
        for file_id, indexed in indexed_files.items():
            if file_id not in files_by_id:
                files_by_id[file_id] = indexed.model_dump(mode="json")
        # No ``base`` on purpose: a repeated pick of the same pack still has
        # to refresh the composed video (see the toolbar toggle for the same
        # deliberate no-op refresh).
        candidate, _impact = apply_frontend_edit_impacts(candidate, pointers)
        return {
            "candidate": candidate,
            "snapshot": snapshot,
            "pack": pack_id,
            "style": style_json,
            # The exact sentence the renderer was built from, so the UI can
            # echo the truth instead of keeping a second copy of the wording.
            "style_line": subtitle_pack_prompt_line(pack_id, style_json),
            "synced": synced,
            "redrawn": redrawn,
            "skipped": skipped,
        }

    try:
        data = await asyncio.to_thread(operation)
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    except InvalidProjectId as exc:
        raise BadRequestError(str(exc)) from exc
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc

    try:
        result = await services.commit_candidate(
            base=data["snapshot"],
            candidate=data["candidate"],
            origin="frontend_edit",
            review_policy="auto_fix",
        )
    except JsonCasConflict as exc:
        # The agent may be editing the same caption; a stale-field collision is
        # a retryable conflict, never a 500 (same mapping /patch already gives).
        raise CasConflictError(
            "Project 字段已被其他写者修改",
            details={"conflicts": exc.conflicts},
        ) from exc
    notify_creator_agent_runtime(project_id)
    return {
        "ok": True,
        "generation": result.snapshot.generation,
        "subtitleTemplate": data["pack"],
        "subtitleStyle": data["style"],
        "styleLine": data["style_line"],
        "syncedPrompts": data["synced"],
        "redrawnDocuments": data["redrawn"],
        # Captions whose look belongs to an independent design: the caller has
        # to be able to say so instead of reporting a silent success.
        "skippedNonTemplate": data["skipped"],
    }


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    cascade: bool = Query(
        True,
        description="When false, only the project manifest is removed; "
        "assets and runtime data are preserved on disk.",
    ),
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
    # Release the poller and the per-project log before the directory
    # rename. On Windows an open creator.log inside the tree makes
    # os.replace fail with WinError 5.
    services.poller.close(project_id)
    from utils.logger import close_creator_project_logging

    close_creator_project_logging(project_id)
    try:
        await asyncio.to_thread(
            services.projects.delete,
            project_id,
            cascade=cascade,
        )
    except ProjectNotFound:
        pass
    except (ProjectIntegrityError, ProjectStoreError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    # Cancellation only signals workers; a late project-scoped emit can
    # reopen the log between the pre-delete close and rename. Drop that
    # handler again so deleted projects do not keep an open target.
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
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    except InvalidProjectId as exc:
        raise BadRequestError(str(exc)) from exc
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
        # The global name lock only covers the replay-receipt check and the
        # copy-name computation.  The asset tree copy and Runtime bootstrap
        # run in a private staging directory outside the lock (export learned
        # this the hard way: holding a global boundary across large-tree I/O
        # caused routine 10-second lock timeouts) and are published by the
        # create's atomic rename, which refuses an already-existing Project.
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
            source_name = services.projects.read(project_id).project.name
            copy_name = f"{source_name} copy"
            existing = services.projects.list()
            base_name = copy_name
            suffix = 1
            while any(item.name == copy_name for item in existing):
                suffix += 1
                copy_name = f"{base_name} {suffix}"

        # Freeze the source Project and its asset tree at one revision for
        # the whole copy. Project commits/deletion take the exclusive side.
        with services.projects.lifecycle_lock(project_id, shared=True):
            source_snapshot = services.projects.read(project_id)
            source = source_snapshot.project
            source_root = services.projects.project_root(project_id)

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
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    except InvalidProjectId as exc:
        raise BadRequestError(str(exc)) from exc
    except (ConflictError, StorageIntegrityError):
        raise
    except (ProjectIntegrityError, ProjectStoreError, RuntimeFileError) as exc:
        raise StorageIntegrityError(str(exc)) from exc
    notify_creator_agent_runtime(result["projectId"])
    response.status_code = status.HTTP_201_CREATED
    return result


# pylint: enable=too-many-statements


@storage_router.get("/{project_id}/export")
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
    except ProjectNotFound as exc:
        # A missing Project is a client addressing mistake, not a storage
        # fault: it must stay a 404 instead of the 503 the generic branch
        # below would report.
        raise NotFoundError(str(exc)) from exc
    except InvalidProjectId as exc:
        raise BadRequestError(str(exc)) from exc
    except BadRequestError:
        raise
    except Exception as e:
        logger.error(
            f"failed to export project {_log_safe(project_id)}",
            exc_info=True,
        )
        raise StorageIntegrityError(
            message=f"Failed to export project {project_id}: {str(e)}",
        ) from e


def _validate_import_archive(saved_zip: Path) -> None:
    project_archive.validate_archive(saved_zip)


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
                if written > project_archive.MAX_ARCHIVE_BYTES:
                    raise BadRequestError(
                        "uploaded archive exceeds the "
                        f"{project_archive.MAX_ARCHIVE_BYTES} byte limit",
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
    report = AssetFileStore(dirs[0]).validate_index(project.assets)
    if not report.valid:
        raise BadRequestError(
            "archive contains missing or corrupt indexed media: "
            + ", ".join(item.file_id for item in report.failures[:5]),
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
                _extract_archive_sanitized,
                saved_zip,
                extract_dir,
            )
            logger.info(
                f"unpacked zip file {_log_safe(saved_zip)} to {extract_dir}",
            )
        except Exception as e:
            raise BadRequestError(
                f"failed to unpack zip file {saved_zip}: {str(e)}",
            ) from e

        # Large Project documents must not block the API event loop while
        # the browser waits for server-side import after upload completes.
        project_dir, project_id = await asyncio.to_thread(
            _resolve_extracted_project,
            extract_dir,
        )

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
        await asyncio.to_thread(saved_zip.unlink, missing_ok=True)
        await asyncio.to_thread(shutil.rmtree, extract_dir, ignore_errors=True)
        logger.info(
            "deleted temporary importing file and folder "
            f"{_log_safe(saved_zip)}, {extract_dir}",
        )


@storage_router.post("/import")
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
