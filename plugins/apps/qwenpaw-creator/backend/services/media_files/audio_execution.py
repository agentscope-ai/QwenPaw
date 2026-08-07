# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""TTS audio generation and character voice enrollment over Project files.

Synthesized narration lands as an immutable audio ``SourceAssetVersion`` (the
type ``AudioCreation`` Timeline elements reference); voice enrollment writes a
``CharacterVoice`` binding onto one character VisualEntity.  Both publish via
the commit boundary, mirroring the grounding-visual promotion path.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from domain.errors import ValidationError
from models import tts_model
from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.commit import ProjectCommitError
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    CharacterVoice,
    IndexedFile,
    SourceAssetVersion,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from utils.logger import setup_logger

logger = setup_logger("media_files.audio")

_MEDIA_TYPE_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
}


@dataclass(frozen=True, slots=True)
class FileTtsExecutionResult:
    source_asset_version_id: str
    logical_asset_id: str
    file_id: str
    duration_seconds: float | None
    voice: str
    model: str
    project_etag: str
    project_generation: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class FileVoiceEnrollmentResult:
    entity_id: str
    voice_id: str
    target_model: str
    sample_source_version_id: str | None
    project_etag: str
    project_generation: int
    replayed: bool
    # "design" when built from a description, "clone" from an audio sample.
    origin: str = "clone"


def _stable_id(prefix: str, project_id: str, idempotency_key: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file-audio:{prefix}:{project_id}:{idempotency_key}",
    ).hex
    return f"{prefix}-{digest}"


def _wav_duration_seconds(content: bytes) -> float | None:
    """Duration of a WAV payload, robust against streaming-writer headers.

    qwen3-tts emits streamed WAVs whose data-chunk length is a placeholder
    (~2^30 frames), so the header-declared frame count can claim hours of
    audio. The real payload size bounds the duration, so the byte-derived
    value wins whenever the header exceeds it.
    """

    with contextlib.suppress(Exception):
        with wave.open(io.BytesIO(content)) as handle:
            rate = handle.getframerate()
            frame_bytes = handle.getnchannels() * handle.getsampwidth()
            if rate <= 0 or frame_bytes <= 0:
                return None
            header_seconds = handle.getnframes() / rate
            byte_bound_seconds = len(content) / (rate * frame_bytes)
            duration = (
                header_seconds
                if header_seconds <= byte_bound_seconds + 1
                else byte_bound_seconds
            )
            if duration > 0:
                return round(duration, 3)
    return None


def _ffprobe_duration_seconds(content: bytes, media_type: str) -> float | None:
    """Duration of any audio payload, via ffprobe on a temporary file.

    The WebSocket family streams MP3, which carries no frame count in a
    parsable header the way WAV does.
    """

    extension = _MEDIA_TYPE_EXTENSIONS.get(media_type, ".mp3")
    with contextlib.suppress(Exception):
        with tempfile.TemporaryDirectory(prefix="creator-audio-") as directory:
            probe_path = Path(directory) / f"probe{extension}"
            probe_path.write_bytes(content)
            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    os.fspath(probe_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            value = float(completed.stdout.strip())
            if value > 0:
                return round(value, 3)
    return None


def _audio_duration_seconds(
    content: bytes,
    media_type: str,
) -> float | None:
    """Duration of synthesized audio, whichever container it arrives in."""

    if media_type in {"audio/wav", "audio/x-wav"}:
        wav_duration = _wav_duration_seconds(content)
        if wav_duration is not None:
            return wav_duration
    return _ffprobe_duration_seconds(content, media_type)


def _entity_id_from_ref(ref: str) -> str:
    """Accept ``asset:<entityId>`` or a bare visual entity id."""

    value = ref.strip()
    value = value.removeprefix("asset:")
    if not value:
        raise ValidationError(f"invalid character ref: {ref!r}")
    return value


def _default_preview_text(entity: Any) -> str:
    """Audition script for a designed voice when the agent supplies none.

    The provider requires a minimum length, so pad with the character's own
    description before falling back to a generic line.
    """

    parts = [entity.name, entity.description or "", entity.continuity or ""]
    sentence = "，".join(part.strip() for part in parts if part.strip())
    if len(sentence) >= tts_model.VOICE_PREVIEW_MIN_CHARS:
        return sentence[:180]
    return f"你好，我是{entity.name}。这是一段用于试听的角色音色预览。"


def _require_character(project: Any, entity_id: str) -> Any:
    entity = project.visual.entities.items.get(entity_id)
    if entity is None:
        raise ValidationError(f"visual entity not found: {entity_id}")
    if entity.kind != "character":
        raise ValidationError(
            f"voice operations require a character entity, got {entity.kind}",
        )
    return entity


def _register_audio_asset(
    services: CreatorFileServices,
    *,
    project_id: str,
    idempotency_key: str,
    content: bytes,
    media_type: str,
    name: str,
    duration_seconds: float | None,
    metadata: Mapping[str, Any],
    provenance_refs: tuple[str, ...],
    caused_by_request_id: str,
) -> FileTtsExecutionResult:
    """Publish audio bytes + SourceAssetVersion; replays return the prior ids."""

    checksum = hashlib.sha256(content).hexdigest()
    logical_asset_id = _stable_id("asset", project_id, idempotency_key)
    version_id = _stable_id("asset-version", project_id, idempotency_key)
    file_id = _stable_id("file", project_id, idempotency_key)
    extension = _MEDIA_TYPE_EXTENSIONS.get(media_type, ".wav")
    relative_uri = PurePosixPath(
        "assets",
        "sources",
        f"{file_id}{extension}",
    ).as_posix()
    created_at = datetime.now(UTC)
    project_root = services.projects.project_root(project_id)
    file_store = AssetFileStore(project_root)
    voice = str(metadata.get("voice") or "")
    model = str(metadata.get("model") or "")

    with services.projects.lifecycle_lock(project_id):
        base = services.projects.read(project_id)
        candidate = base.project.model_dump(mode="json")
        files = candidate["assets"]["files_by_id"]
        versions = candidate["assets"]["source_versions_by_id"]
        existing_version = versions.get(version_id)
        if existing_version is not None:
            if existing_version.get("checksum") != checksum:
                raise ProjectCommitError(
                    "TTS asset version id collision with different content",
                )
            return FileTtsExecutionResult(
                source_asset_version_id=version_id,
                logical_asset_id=logical_asset_id,
                file_id=file_id,
                duration_seconds=duration_seconds,
                voice=voice,
                model=model,
                project_etag=base.etag,
                project_generation=base.generation,
                replayed=True,
            )
        indexed = IndexedFile(
            file_id=file_id,
            kind="source_original",
            relative_uri=relative_uri,
            sha256=checksum,
            size_bytes=len(content),
            media_type=media_type,
            created_at=created_at,
        )
        version = SourceAssetVersion(
            version_id=version_id,
            logical_asset_id=logical_asset_id,
            name=name[:160],
            file_id=file_id,
            checksum=checksum,
            media_kind="audio",
            media_type=media_type,
            provenance_refs=list(provenance_refs),
            duration_seconds=duration_seconds,
            created_at=created_at,
            metadata=dict(metadata),
        )
        if file_id not in files:
            staged = file_store.stage_bytes(
                content,
                staging_id=f"tts-{file_id[:48]}",
            )
            try:
                file_store.publish(
                    staged,
                    relative_uri,
                    expected_sha256=checksum,
                    expected_size_bytes=len(content),
                )
            except AssetAlreadyExists:
                file_store.abandon(staged)
            files[file_id] = indexed.model_dump(mode="json")
        versions[version_id] = version.model_dump(mode="json")
        commit = services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id=caused_by_request_id,
            round_id=_stable_id("round", project_id, idempotency_key),
            transaction_id=_stable_id(
                "transaction",
                project_id,
                idempotency_key,
            ),
            advance_accepted_baseline=True,
            _lifecycle_lock_held=True,
        )
        services.poller.note_commit(commit.snapshot)
    return FileTtsExecutionResult(
        source_asset_version_id=version_id,
        logical_asset_id=logical_asset_id,
        file_id=file_id,
        duration_seconds=duration_seconds,
        voice=voice,
        model=model,
        project_etag=commit.snapshot.etag,
        project_generation=commit.snapshot.generation,
        replayed=False,
    )


async def execute_file_tts_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
) -> FileTtsExecutionResult:
    """Synthesize speech and land it as an immutable audio source version."""

    del target_ref  # scope admission already enforced by the registry
    text = str(arguments.get("text") or "").strip()
    if not text:
        raise ValidationError("tts_generation requires non-empty text")
    voice = str(arguments.get("voice") or "").strip()
    character_ref = str(arguments.get("characterRef") or "").strip()
    label = str(arguments.get("label") or "").strip()
    raw_rate = arguments.get("speechRate")
    try:
        speech_rate = None if raw_rate is None else float(raw_rate)
    except (TypeError, ValueError) as exc:
        raise ValidationError("speechRate 必须是 0.5–2.0 的数字") from exc

    voice_id: str | None = None
    voice_model = ""
    character_entity_id = ""
    if character_ref:
        character_entity_id = _entity_id_from_ref(character_ref)
        snapshot = await asyncio.to_thread(services.projects.read, project_id)
        entity = _require_character(snapshot.project, character_entity_id)
        if entity.voice is not None:
            voice_id = entity.voice.voice_id
            # A created voice only speaks through the model it is bound to.
            voice_model = entity.voice.target_model

    synthesis = await tts_model.synthesize(
        text,
        voice=voice or None,
        voice_id=voice_id,
        voice_model=voice_model or None,
        speech_rate=speech_rate,
    )
    duration = _audio_duration_seconds(
        synthesis.audio_bytes,
        synthesis.media_type,
    )
    metadata: dict[str, Any] = {
        "sourceKind": "tts_generation",
        "model": synthesis.model,
        "voice": synthesis.voice,
        "textPreview": text[:120],
        "characters": synthesis.characters,
    }
    if speech_rate is not None and speech_rate != 1.0:
        metadata["speechRate"] = speech_rate
    if character_entity_id:
        metadata["characterEntityId"] = character_entity_id
    if voice_id:
        metadata["voiceId"] = voice_id
    provenance = (f"tts:{synthesis.model}",) + (
        (f"asset:{character_entity_id}",) if character_entity_id else ()
    )
    return await asyncio.to_thread(
        _register_audio_asset,
        services,
        project_id=project_id,
        idempotency_key=idempotency_key,
        content=synthesis.audio_bytes,
        media_type=synthesis.media_type,
        name=label or f"TTS {text[:40]}",
        duration_seconds=duration,
        metadata=metadata,
        provenance_refs=provenance,
        caused_by_request_id=idempotency_key,
    )


def _sample_bytes_for_version(
    services: CreatorFileServices,
    *,
    project_id: str,
    version_id: str,
) -> tuple[bytes, str]:
    snapshot = services.projects.read(project_id)
    version = snapshot.project.assets.source_versions_by_id.get(version_id)
    if version is None:
        raise ValidationError(f"sample source version not found: {version_id}")
    if version.media_kind != "audio":
        raise ValidationError("voice sample version must be audio media")
    if version.file_id is None:
        raise ValidationError("voice sample version has no local file")
    indexed = snapshot.project.assets.files_by_id.get(version.file_id)
    if indexed is None:
        raise ValidationError("voice sample file is not indexed")
    store = AssetFileStore(services.projects.project_root(project_id))
    return store.read_verified(indexed), indexed.media_type


async def execute_file_voice_enrollment_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
) -> FileVoiceEnrollmentResult:
    """Clone a voice for one character and bind it on the VisualEntity."""

    # The character can come from the explicit argument (project:assets scoped
    # runs) or from an asset:<entityId> targetRef.
    character_ref = str(arguments.get("characterRef") or "").strip()
    entity_id = _entity_id_from_ref(character_ref or target_ref)
    snapshot = await asyncio.to_thread(services.projects.read, project_id)
    entity = _require_character(snapshot.project, entity_id)
    if (
        entity.voice is not None
        and entity.voice.enrollment_key == idempotency_key
    ):
        return FileVoiceEnrollmentResult(
            entity_id=entity_id,
            voice_id=entity.voice.voice_id,
            target_model=entity.voice.target_model,
            sample_source_version_id=entity.voice.sample_source_version_id,
            project_etag=snapshot.etag,
            project_generation=snapshot.generation,
            replayed=True,
            origin=(
                "design"
                if entity.voice.sample_source_version_id is None
                else "clone"
            ),
        )

    sample_version_id = str(
        arguments.get("sampleSourceVersionId") or "",
    ).strip()
    sample_text = str(arguments.get("sampleText") or "").strip()
    voice_prompt = str(arguments.get("voicePrompt") or "").strip()
    preferred_name = (
        str(arguments.get("preferredName") or "").strip() or entity.name
    )

    if voice_prompt:
        # Design path: no audio sample at all, the timbre comes from the
        # character's own description.
        preview_text = str(arguments.get("previewText") or "").strip()
        if len(preview_text) < tts_model.VOICE_PREVIEW_MIN_CHARS:
            preview_text = _default_preview_text(entity)
        enrollment = await tts_model.design_voice(
            voice_prompt=voice_prompt,
            preview_text=preview_text,
            preferred_name=preferred_name,
        )
        sample_version_id = ""
    else:
        if sample_version_id:
            sample_bytes, sample_media_type = await asyncio.to_thread(
                _sample_bytes_for_version,
                services,
                project_id=project_id,
                version_id=sample_version_id,
            )
        elif sample_text:
            # Audition path: synthesize a system-voice sample, keep it as an
            # audio asset so the binding stays reproducible, then clone it.
            audition = await execute_file_tts_command(
                services,
                project_id=project_id,
                target_ref=target_ref,
                arguments={
                    "text": sample_text,
                    "voice": str(arguments.get("voice") or ""),
                    "label": f"Voice sample: {entity.name}"[:60],
                },
                idempotency_key=f"{idempotency_key}:sample",
            )
            sample_version_id = audition.source_asset_version_id
            sample_bytes, sample_media_type = await asyncio.to_thread(
                _sample_bytes_for_version,
                services,
                project_id=project_id,
                version_id=sample_version_id,
            )
        else:
            raise ValidationError(
                "create_character_voice requires voicePrompt (design) or "
                "sampleSourceVersionId / sampleText (clone)",
            )

        extension = _MEDIA_TYPE_EXTENSIONS.get(sample_media_type, ".wav")
        with tempfile.TemporaryDirectory(prefix="creator-voice-") as directory:
            sample_path = Path(directory) / f"sample{extension}"
            sample_path.write_bytes(sample_bytes)
            enrollment = await tts_model.enroll_voice(
                sample_path.as_uri(),
                preferred_name=preferred_name,
            )

    binding = CharacterVoice(
        voice_id=enrollment.voice_id,
        target_model=enrollment.target_model,
        preferred_name=preferred_name,
        sample_source_version_id=sample_version_id or None,
        enrollment_key=idempotency_key,
        created_at=datetime.now(UTC),
    )

    def _commit_binding() -> FileVoiceEnrollmentResult:
        with services.projects.lifecycle_lock(project_id):
            base = services.projects.read(project_id)
            candidate = base.project.model_dump(mode="json")
            entities = candidate["visual"]["entities"]["items"]
            if entity_id not in entities:
                raise ValidationError(
                    f"visual entity disappeared during enrollment: {entity_id}",
                )
            entities[entity_id]["voice"] = binding.model_dump(mode="json")
            commit = services.commits.commit(
                base=base,
                candidate=candidate,
                origin=ChangeOrigin.RUNTIME_TASK,
                review_policy=ReviewPolicy.AUTO_FIX,
                caused_by_request_id=idempotency_key,
                round_id=_stable_id("round", project_id, idempotency_key),
                transaction_id=_stable_id(
                    "transaction",
                    project_id,
                    idempotency_key,
                ),
                advance_accepted_baseline=True,
                _lifecycle_lock_held=True,
            )
            services.poller.note_commit(commit.snapshot)
        return FileVoiceEnrollmentResult(
            entity_id=entity_id,
            voice_id=enrollment.voice_id,
            target_model=enrollment.target_model,
            sample_source_version_id=sample_version_id or None,
            project_etag=commit.snapshot.etag,
            project_generation=commit.snapshot.generation,
            replayed=False,
            origin=enrollment.origin,
        )

    result = await asyncio.to_thread(_commit_binding)
    previous = (
        entity.voice
        if entity.voice is not None
        and entity.voice.voice_id != result.voice_id
        else None
    )
    if previous is not None:
        # Route the delete by the model the old voice was bound to; the three
        # voice namespaces each only accept their own management surface.
        await tts_model.delete_voice(
            previous.voice_id,
            target_model=previous.target_model,
        )
    return result


__all__ = [
    "FileTtsExecutionResult",
    "FileVoiceEnrollmentResult",
    "execute_file_tts_command",
    "execute_file_voice_enrollment_command",
]
