# -*- coding: utf-8 -*-
"""Character-voice HTTP surface: capability probe plus direct enrollment.

Voice enrollment used to be reachable only through the assistant agent's
create_character_voice tool. The asset library drives it directly here —
same executor, no agent turn.

Notification semantics: completion publishes a quiet-level event on the
runtime notification bus — it lands in the per-project outbox and rides
along with the next steer/digest, never waking the agent by itself
(same policy as manual work-graph dispatch node transitions).
"""

from __future__ import annotations

from typing import Any
import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, Header

from domain.errors import NotFoundError, ValidationError
from models import tts_capabilities
from models.config import get_tts_model_name
from services.file_agent_runtime.notifications import RuntimeEventKind
from services.file_agent_runtime.registry import get_creator_agent_runtime
from services.project_files.facade import CreatorFileServices
from services.specialist_tools import (
    character_voice_tool_spec,
    invoke_character_voice_tool,
)

from .dependencies import CreatorErrorRoute, project_file_services

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["character-voice"],
    route_class=CreatorErrorRoute,
)


@router.get("/voice-capabilities")
async def get_voice_capabilities(project_id: str) -> dict[str, Any]:
    # Capability is deployment-wide; kept per-project for URL symmetry.
    del project_id
    model = get_tts_model_name()
    capability = tts_capabilities.capability_for(model)
    return {
        "model": model,
        "configured": character_voice_tool_spec() is not None,
        # Design = build a timbre from a plain-language prompt; when false the
        # UI must collect an audio sample instead of a voice prompt.
        "supportsDesign": bool(capability and capability.supports_design),
    }


@router.post("/character-voice")
async def create_character_voice(
    project_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    character_ref = str(payload.get("characterRef") or "").strip()
    if not character_ref:
        raise ValidationError("characterRef is required")
    if not character_ref.startswith("asset:"):
        character_ref = f"asset:{character_ref.replace('visual-entity:', '')}"
    request_key = idempotency_key or f"voice-http-{uuid4().hex}"
    result = await invoke_character_voice_tool(
        services,
        project_id=project_id,
        target_ref=character_ref,
        arguments=payload,
        idempotency_key=request_key,
    )
    runtime = get_creator_agent_runtime()
    if runtime is not None and not result.get("replayed"):
        try:
            await runtime.notifications.notify(
                project_id,
                kind=RuntimeEventKind.VOICE_ENROLLED,
                request_id=f"voice-enrolled-{request_key}",
                text=(
                    f"角色 {result.get('entityId')} 的参考音色已通过资产库"
                    f"直接生成并绑定（{result.get('voiceOrigin')}）。"
                    "这是状态同步，不是新的用户指令。"
                ),
                payload={
                    "entityId": result.get("entityId"),
                    "voiceOrigin": result.get("voiceOrigin"),
                    "sampleSourceVersionId": result.get(
                        "sampleSourceVersionId",
                    ),
                },
            )
        except Exception:  # noqa: BLE001 - the bind already succeeded
            pass
    return result


@router.post("/timelines/{timeline_id}/elements/{element_id}/narration")
async def regenerate_narration(
    project_id: str,
    timeline_id: str,
    element_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    """Re-synthesize one narration element's audio straight through the TTS
    executor (no agent turn) and rebind the element to the new version.

    The synthesis inputs come from the element itself — its script and
    speech rate — plus the voice identity recorded on the current audio
    version, so the regenerated narration keeps the user-selected voice.
    """

    # pylint: disable=import-outside-toplevel
    from services.media_files.audio_execution import (
        execute_file_tts_command,
    )
    from services.media_files.narration_generation import (
        begin_narration_request,
        narration_input,
        narration_request_store,
    )
    from services.project_files.commit import ProjectCommitBoundary
    from services.project_files.models import (
        AudioCreation,
        is_snapshot_timeline_id,
    )

    if is_snapshot_timeline_id(timeline_id):
        raise ValidationError("历史快照是冻结副本，不能重新合成旁白")
    request_key = idempotency_key or f"narration-http-{uuid4().hex}"
    arguments, input_fingerprint, request_id = await asyncio.to_thread(
        begin_narration_request,
        services,
        project_id,
        timeline_id,
        element_id,
        request_key,
    )
    result = await execute_file_tts_command(
        services,
        project_id=project_id,
        target_ref=f"timeline:{timeline_id}",
        arguments=arguments,
        idempotency_key=request_key,
    )

    new_version_id = result.source_asset_version_id

    def _rebind() -> tuple[bool, str | None]:
        # Input validation and binding share the same lock as every Project
        # writer; a fresh CAS baseline alone cannot protect these reads.
        with services.projects.lifecycle_lock(project_id):
            fresh = services.projects.read(project_id)
            request_store = narration_request_store(
                services,
                project_id,
                timeline_id,
                element_id,
            )
            record = request_store.read()
            if record.get("latestRequestId") != request_id:
                return False, "SUPERSEDED"
            try:
                _, current_fingerprint = narration_input(
                    fresh.project,
                    timeline_id,
                    element_id,
                )
            except (NotFoundError, ValidationError):
                return False, "INPUT_CHANGED"
            if current_fingerprint != input_fingerprint:
                return False, "INPUT_CHANGED"
            candidate = fresh.project.model_copy(deep=True)
            target = candidate.timelines.items[timeline_id].elements_by_id[
                element_id
            ]
            assert isinstance(target.creation, AudioCreation)
            if target.creation.source_asset_version_id == new_version_id:
                return False, None
            target.creation.source_asset_version_id = new_version_id
            # A retry may observe this request's own binding change. Record
            # the only additional input state it is allowed to replay, before
            # publication so a crash after commit does not break idempotency.
            _, bound_fingerprint = narration_input(
                candidate,
                timeline_id,
                element_id,
            )
            record["requests"][request_id][
                "boundFingerprint"
            ] = bound_fingerprint
            request_store.write(record)
            ProjectCommitBoundary(services.projects).commit(
                base=fresh,
                candidate=candidate.model_dump(mode="json"),
                origin="runtime_task",
                _lifecycle_lock_held=True,
            )
            return True, None

    rebound, stale_reason = await asyncio.to_thread(_rebind)

    runtime = get_creator_agent_runtime()
    if runtime is not None and rebound:
        try:
            await runtime.notifications.notify(
                project_id,
                kind=RuntimeEventKind.NARRATION_REGENERATED,
                request_id=f"narration-regen-{request_key}",
                text=(
                    f"元素 {element_id} 的旁白已按当前文稿与音色"
                    f"（{result.voice or result.model}）直接重新合成并"
                    "替换。这是状态同步，不是新的用户指令。"
                ),
                payload={
                    "timelineId": timeline_id,
                    "elementId": element_id,
                    "audioVersionId": new_version_id,
                },
            )
        except Exception:  # noqa: BLE001 - the rebind already succeeded
            pass

    return {
        "audioVersionId": new_version_id,
        "replayed": result.replayed,
        "rebound": rebound,
        "stale": stale_reason is not None,
        "staleReason": stale_reason,
        "voice": result.voice,
        "model": result.model,
        "durationSeconds": result.duration_seconds,
    }
