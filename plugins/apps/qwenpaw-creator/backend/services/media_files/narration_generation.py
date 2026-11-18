# -*- coding: utf-8 -*-
"""Input and request-order guards for direct narration regeneration."""

from __future__ import annotations

from typing import Any

from domain.errors import ConflictError, NotFoundError, ValidationError
from models import config as model_config
from services.project_files.facade import CreatorFileServices
from services.project_files.models import AudioCreation, Project
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    json_checksum,
)
from services.runtime_files.path_safety import hashed_runtime_segment


def narration_input(
    project: Project,
    timeline_id: str,
    element_id: str,
) -> tuple[dict[str, Any], str]:
    timeline = project.timelines.items.get(timeline_id)
    element = timeline.elements_by_id.get(element_id) if timeline else None
    if element is None:
        raise NotFoundError("旁白元素不存在")
    creation = element.creation
    if not isinstance(creation, AudioCreation) or not creation.script.strip():
        raise ValidationError("该元素不是携带台词文稿的音频元素")
    version = project.assets.source_versions_by_id.get(
        creation.source_asset_version_id,
    )
    metadata = version.metadata if version else {}
    arguments: dict[str, Any] = {
        "text": creation.script.strip(),
        "label": element.label or "旁白",
    }
    voice = str(metadata.get("voice") or "").strip()
    character_id = str(metadata.get("characterEntityId") or "").strip()
    if voice:
        arguments["voice"] = voice
    if character_id:
        arguments["characterRef"] = f"asset:{character_id}"
    if creation.speech_rate is not None:
        arguments["speechRate"] = creation.speech_rate
    character = project.visual.entities.items.get(character_id)
    binding = character.voice if character else None
    fingerprint = json_checksum(
        {
            "text": arguments["text"],
            "speechRate": (
                creation.speech_rate
                if creation.speech_rate is not None
                else 1.0
            ),
            "sourceVersionId": creation.source_asset_version_id,
            "sourceChecksum": version.checksum if version else None,
            "characterId": character_id,
            "voice": (
                binding.voice_id
                if binding
                else (voice or model_config.get_tts_voice())
            ),
            "voiceModel": (
                binding.target_model
                if binding
                else model_config.get_tts_model_name()
            ),
        },
    )
    return arguments, fingerprint


def narration_request_store(
    services: CreatorFileServices,
    project_id: str,
    timeline_id: str,
    element_id: str,
) -> AtomicJsonRecordStore:
    """Caller holds the Project lifecycle lock for all reads and writes."""
    return AtomicJsonRecordStore(
        services.projects.project_root(project_id)
        / "runtime"
        / "narration-requests"
        / f"{hashed_runtime_segment('element', timeline_id, element_id)}.json",
        locked=False,
    )


def begin_narration_request(
    services: CreatorFileServices,
    project_id: str,
    timeline_id: str,
    element_id: str,
    request_key: str,
) -> tuple[dict[str, Any], str, str]:
    """Freeze inputs and atomically order requests before waiting on TTS."""
    request_id = hashed_runtime_segment("request", request_key)
    with services.projects.lifecycle_lock(project_id):
        snapshot = services.projects.read(project_id)
        arguments, fingerprint = narration_input(
            snapshot.project,
            timeline_id,
            element_id,
        )
        store = narration_request_store(
            services,
            project_id,
            timeline_id,
            element_id,
        )
        record = store.read_or_none() or {"requests": {}}
        previous = record["requests"].get(request_id)
        if previous is not None:
            if fingerprint not in {
                previous["inputFingerprint"],
                previous.get("boundFingerprint"),
            }:
                raise ConflictError("Idempotency-Key 对应的旁白输入已变更")
            # Replaying an older request must never supersede a newer one.
        else:
            record["requests"][request_id] = {"inputFingerprint": fingerprint}
            record["latestRequestId"] = request_id
            store.write(record)
    return arguments, fingerprint, request_id
