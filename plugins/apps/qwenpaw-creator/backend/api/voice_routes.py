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
    from services.project_files.commit import ProjectCommitBoundary
    from services.project_files.models import (
        AudioCreation,
        is_snapshot_timeline_id,
    )

    if is_snapshot_timeline_id(timeline_id):
        raise ValidationError("历史快照是冻结副本，不能重新合成旁白")
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    timeline = snapshot.project.timelines.items.get(timeline_id)
    if timeline is None:
        raise NotFoundError(f"timeline 不存在: {timeline_id}")
    element = timeline.elements_by_id.get(element_id)
    if element is None:
        raise NotFoundError(f"element 不存在: {element_id}")
    creation = element.creation
    if not isinstance(creation, AudioCreation) or not creation.script.strip():
        raise ValidationError("该元素不是携带台词文稿的音频元素")

    current = snapshot.project.assets.source_versions_by_id.get(
        creation.source_asset_version_id,
    )
    meta: dict[str, Any] = dict(current.metadata) if current else {}
    arguments: dict[str, Any] = {
        "text": creation.script,
        "label": element.label or "旁白",
    }
    if meta.get("voice"):
        arguments["voice"] = meta["voice"]
    if meta.get("characterEntityId"):
        arguments["characterRef"] = f"asset:{meta['characterEntityId']}"
    if creation.speech_rate is not None:
        arguments["speechRate"] = creation.speech_rate

    request_key = idempotency_key or f"narration-http-{uuid4().hex}"
    result = await execute_file_tts_command(
        services,
        project_id=project_id,
        target_ref=f"timeline:{timeline_id}",
        arguments=arguments,
        idempotency_key=request_key,
    )

    rebound = False
    new_version_id = result.source_asset_version_id
    if new_version_id != creation.source_asset_version_id:

        def _rebind() -> None:
            fresh = services.projects.read(project_id)
            candidate = fresh.project.model_copy(deep=True)
            fresh_timeline = candidate.timelines.items.get(timeline_id)
            target = (
                fresh_timeline.elements_by_id.get(element_id)
                if fresh_timeline
                else None
            )
            if target is None:
                raise NotFoundError("元素在重新合成期间被删除")
            if not isinstance(target.creation, AudioCreation):
                raise ValidationError("元素类型在重新合成期间被修改")
            target.creation.source_asset_version_id = new_version_id
            ProjectCommitBoundary(services.projects).commit(
                base=fresh,
                candidate=candidate.model_dump(mode="json"),
                origin="runtime_task",
            )

        await asyncio.to_thread(_rebind)
        rebound = True

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
        "voice": result.voice,
        "model": result.model,
        "durationSeconds": result.duration_seconds,
    }
