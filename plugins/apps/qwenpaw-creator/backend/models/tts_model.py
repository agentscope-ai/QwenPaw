# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Text-to-speech client for Creator narration and character voices.

Two DashScope families share the ``creator_tts_model`` configuration and are
routed by :mod:`models.tts_capabilities`:

- ``qwen-tts`` synthesizes over HTTP and manages voices through
  ``qwen-voice-enrollment`` (clone) / ``qwen-voice-design`` (design), each
  bound to a companion ``-vc-`` / ``-vd-`` model;
- ``cosyvoice`` synthesizes over WebSocket and manages both clone and design
  through one ``voice-enrollment`` surface bound to the synthesis model itself.

Character voices therefore come from either an audio sample (clone) or a plain
text description (design); the newest models of both families have no system
voices, so designing one is the only way to speak with them.
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from models import config
from models.media_transport import upload_local_file_to_dashscope_temp
from models.tts_capabilities import TtsModelCapability, require_capability
from utils.exceptions import ModelError
from utils.logger import setup_logger
from utils.paths import local_path_from_file_url
from utils.remote_download import download_remote_file

logger = setup_logger("models.tts")

# qwen3-tts caps one request at ~512 tokens; a conservative character bound
# keeps requests inside the limit for mixed Chinese/English scripts.
TTS_MAX_TEXT_CHARS = 800

# The design API rejects shorter preview scripts.
VOICE_PREVIEW_MIN_CHARS = 15

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0
_PREFERRED_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class TTSSynthesis:
    audio_bytes: bytes
    media_type: str
    model: str
    voice: str
    characters: int


@dataclass(frozen=True, slots=True)
class VoiceEnrollment:
    voice_id: str
    target_model: str
    # "clone" when built from an audio sample, "design" from a description.
    origin: str = "clone"


def _active_capability() -> TtsModelCapability:
    configured = config.get_tts_model_name()
    capability = require_capability(configured)
    if configured and capability.model != configured:
        logger.warning(
            "TTS model %s is not supported by this build; using %s",
            configured,
            capability.model,
        )
    return capability


def _endpoint(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _require_text(text: str) -> str:
    value = text.strip()
    if not value:
        raise ValueError("TTS text must not be empty")
    if len(value) > TTS_MAX_TEXT_CHARS:
        raise ValueError(
            f"TTS text is too long ({len(value)} chars > {TTS_MAX_TEXT_CHARS}); "
            "split the script at sentence boundaries and synthesize each part",
        )
    return value


def _require_key() -> str:
    key = config.get_tts_api_key()
    if not key:
        raise ValueError(
            "TTS requires an API key; configure creator_tts_model or set "
            "TTS_API_KEY",
        )
    return key


async def _post_json(
    url: str,
    *,
    api_key: str,
    payload: Mapping[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-OssResourceResolve": "enable",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30, read=timeout_seconds),
    ) as client:
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            response = await client.post(url, headers=headers, json=payload)
            if (
                response.status_code in _RETRY_STATUS
                and attempt < _RETRY_ATTEMPTS
            ):
                wait = _RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "TTS request got HTTP %d (attempt %d/%d), retrying in %.0fs",
                    response.status_code,
                    attempt,
                    _RETRY_ATTEMPTS,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            if response.status_code >= 400:
                # Surface the provider's own explanation: "400 Bad Request"
                # alone tells neither the agent nor the user what to fix.
                detail = response.text[:400]
                raise ModelError(
                    f"TTS request failed (HTTP {response.status_code}): "
                    f"{detail}",
                    retryable=response.status_code >= 500,
                )
            return response.json()
    raise ModelError("TTS request retries exhausted")


def _download_audio(url: str) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="creator-tts-") as directory:
        target = Path(directory) / "speech.wav"
        download_remote_file(url, str(target))
        content = target.read_bytes()
    if not content:
        raise ModelError("TTS returned an empty audio payload")
    media_type = mimetypes.guess_type(urlparse(url).path)[0] or "audio/wav"
    if not media_type.startswith("audio/"):
        media_type = "audio/wav"
    return content, media_type


def _synthesize_over_websocket(
    *,
    model: str,
    voice: str,
    text: str,
    api_key: str,
    speech_rate: float = 1.0,
) -> tuple[bytes, str]:
    """Stream one utterance from the CosyVoice family over WebSocket.

    The official SDK owns the duplex protocol, so we drive it on a worker
    thread and collect the audio chunks its callback delivers.
    """

    import dashscope
    from dashscope.audio.tts_v2 import (  # noqa: PLC0415 - optional surface
        AudioFormat,
        ResultCallback,
        SpeechSynthesizer,
    )

    chunks: list[bytes] = []
    failure: list[str] = []
    finished = threading.Event()

    class _Collector(ResultCallback):
        def on_open(self) -> None:
            pass

        def on_data(self, data: bytes) -> None:
            chunks.append(data)

        def on_complete(self) -> None:
            finished.set()

        def on_error(self, message: Any) -> None:
            failure.append(str(message))
            finished.set()

        def on_close(self) -> None:
            finished.set()

        def on_event(self, message: Any) -> None:
            pass

    dashscope.api_key = api_key
    synthesizer = SpeechSynthesizer(
        model=model,
        voice=voice,
        format=AudioFormat.MP3_24000HZ_MONO_256KBPS,
        speech_rate=speech_rate,
        callback=_Collector(),
    )
    synthesizer.streaming_call(text)
    synthesizer.streaming_complete()
    finished.wait(timeout=config.get_tts_timeout_seconds())
    audio = b"".join(chunks)
    if not audio:
        detail = failure[0] if failure else "no audio was streamed"
        raise ModelError(
            f"TTS websocket synthesis failed: {detail}",
            model_name=model,
        )
    return audio, "audio/mpeg"


async def synthesize(
    text: str,
    *,
    voice: str | None = None,
    voice_id: str | None = None,
    voice_model: str | None = None,
    speech_rate: float | None = None,
) -> TTSSynthesis:
    """Render ``text`` to speech; ``voice_id`` selects a created voice.

    ``voice_model`` is the model a created voice is bound to (a character
    binding records it), because a voice only speaks through its own model.
    ``speech_rate`` (0.5–2.0) is a CosyVoice-family capability: the WebSocket
    synthesizer applies it natively, while the qwen-tts HTTP endpoint has no
    such parameter and rejects a non-default rate up front.
    """

    value = _require_text(text)
    key = _require_key()
    capability = _active_capability()
    if voice_id:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{3,199}", voice_id):
            raise ValueError(
                f"voice_id looks malformed: {voice_id!r}; pass the id "
                "returned by voice creation",
            )
        model = (voice_model or "").strip() or capability.clone_model()
        active_voice = voice_id
    else:
        model = capability.model
        active_voice = (voice or "").strip() or config.get_tts_voice()
        if not capability.has_system_voices:
            raise ValueError(
                f"{model} has no system voices; create a character voice "
                "first and synthesize with its voice id",
            )
        if active_voice not in capability.system_voices:
            # Fail fast on a made-up voice name: the provider would reject
            # it anyway, but only after the call burned an execution
            # authorization round-trip.
            raise ValueError(
                f"unknown voice {active_voice!r} for {model}; available "
                f"system voices: {', '.join(capability.system_voices)}",
            )
    transport = require_capability(model).transport
    rate = 1.0 if speech_rate is None else float(speech_rate)
    if not 0.5 <= rate <= 2.0:
        raise ValueError("speechRate must be between 0.5 and 2.0")
    if rate != 1.0 and transport != "websocket":
        raise ValueError(
            f"{model} 不支持数值语速参数；只有 CosyVoice 系列（WebSocket 合成）"
            "支持 speechRate 0.5–2.0，其它模型请通过增删文稿控制时长",
        )
    logger.info(
        "TTS synthesize: model=%s voice=%s chars=%d created=%s transport=%s",
        model,
        active_voice,
        len(value),
        bool(voice_id),
        transport,
    )
    # Transport follows the model that actually speaks: a created voice is
    # bound to its own model, which may sit in the other family than the
    # configured default (CosyVoice voice under a qwen-tts default).
    if transport == "websocket":
        content, media_type = await asyncio.to_thread(
            _synthesize_over_websocket,
            model=model,
            voice=active_voice,
            text=value,
            api_key=key,
            speech_rate=rate,
        )
        return TTSSynthesis(
            audio_bytes=content,
            media_type=media_type,
            model=model,
            voice=active_voice,
            characters=len(value),
        )
    payload: dict[str, Any] = {
        "model": model,
        "input": {"text": value, "voice": active_voice},
    }
    data = await _post_json(
        _endpoint(
            config.get_tts_base_url(),
            "services/aigc/multimodal-generation/generation",
        ),
        api_key=key,
        payload=payload,
        timeout_seconds=config.get_tts_timeout_seconds(),
    )
    output = data.get("output") or {}
    audio = output.get("audio") or {}
    audio_url = str(audio.get("url") or "")
    if not audio_url:
        raise ModelError(f"TTS response has no audio url: {output}")
    content, media_type = await asyncio.to_thread(_download_audio, audio_url)
    usage = data.get("usage") or {}
    return TTSSynthesis(
        audio_bytes=content,
        media_type=media_type,
        model=model,
        voice=active_voice,
        characters=int(usage.get("characters") or len(value)),
    )


def _normalize_preferred_name(name: str, *, limit: int = 20) -> str:
    """Provider-safe voice name prefix.

    Both families accept only lowercase alphanumerics, and they disagree on the
    maximum length: qwen-tts allows 20 characters, cosyvoice only 10.
    """

    value = _PREFERRED_NAME_PATTERN.sub("", name.strip().casefold())
    return (value or "creatorvoice")[:limit]


# cosyvoice rejects a prefix longer than this.
_COSYVOICE_PREFIX_LIMIT = 10


async def _sample_url(sample_media_url: str, api_key: str, model: str) -> str:
    """Return a URL the enrollment API can fetch, uploading local samples."""

    parsed = urlparse(sample_media_url)
    if parsed.scheme == "file":
        local_path = local_path_from_file_url(sample_media_url)
        media_type = mimetypes.guess_type(local_path.name)[0] or "audio/wav"
        return await upload_local_file_to_dashscope_temp(
            local_path,
            api_key=api_key,
            model_name=model,
            media_type=media_type,
        )
    if parsed.scheme in {"http", "https", "oss"}:
        return sample_media_url
    raise ValueError(
        "voice sample must be a local file or HTTP(S)/OSS media URL",
    )


async def enroll_voice(
    sample_media_url: str,
    *,
    preferred_name: str,
) -> VoiceEnrollment:
    """Clone a voice from a 10-20s audio sample and return its voice id."""

    key = _require_key()
    capability = _active_capability()
    target_model = capability.clone_model()
    audio_url = await _sample_url(sample_media_url, key, target_model)
    logger.info(
        "TTS clone voice: target_model=%s family=%s name=%s",
        target_model,
        capability.family,
        preferred_name,
    )
    if capability.family == "cosyvoice":
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": _normalize_preferred_name(
                    preferred_name,
                    limit=_COSYVOICE_PREFIX_LIMIT,
                ),
                "url": audio_url,
            },
        }
    else:
        payload = {
            "model": "qwen-voice-enrollment",
            "input": {
                "action": "create",
                "target_model": target_model,
                "preferred_name": _normalize_preferred_name(preferred_name),
                "audio": {"data": audio_url},
            },
        }
    data = await _post_json(
        _endpoint(
            config.get_tts_base_url(),
            "services/audio/tts/customization",
        ),
        api_key=key,
        payload=payload,
        timeout_seconds=config.get_tts_timeout_seconds(),
    )
    return VoiceEnrollment(
        voice_id=_require_voice_id(data),
        target_model=target_model,
        origin="clone",
    )


async def design_voice(
    *,
    voice_prompt: str,
    preview_text: str,
    preferred_name: str,
) -> VoiceEnrollment:
    """Create a voice from a plain-language description, no sample needed.

    ``voice_prompt`` describes the timbre ("low, hoarse middle-aged man, slow
    delivery"); ``preview_text`` is the audition script the provider renders
    while building the voice.
    """

    description = voice_prompt.strip()
    if not description:
        raise ValueError("voice design requires a voice_prompt description")
    preview = preview_text.strip()
    if len(preview) < VOICE_PREVIEW_MIN_CHARS:
        raise ValueError(
            "voice design preview_text must be at least "
            f"{VOICE_PREVIEW_MIN_CHARS} characters, got {len(preview)}",
        )
    key = _require_key()
    capability = _active_capability()
    if not capability.supports_design:
        raise ValueError(
            f"{capability.model} does not support voice design; clone from an "
            "audio sample instead",
        )
    target_model = capability.design_model()
    logger.info(
        "TTS design voice: target_model=%s family=%s name=%s",
        target_model,
        capability.family,
        preferred_name,
    )
    if capability.family == "cosyvoice":
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": _normalize_preferred_name(
                    preferred_name,
                    limit=_COSYVOICE_PREFIX_LIMIT,
                ),
                "voice_prompt": description,
                "preview_text": preview,
            },
        }
    else:
        payload = {
            "model": "qwen-voice-design",
            "input": {
                "action": "create",
                "target_model": target_model,
                "preferred_name": _normalize_preferred_name(preferred_name),
                "voice_prompt": description,
                "preview_text": preview,
            },
        }
    data = await _post_json(
        _endpoint(
            config.get_tts_base_url(),
            "services/audio/tts/customization",
        ),
        api_key=key,
        payload=payload,
        timeout_seconds=config.get_tts_timeout_seconds(),
    )
    return VoiceEnrollment(
        voice_id=_require_voice_id(data),
        target_model=target_model,
        origin="design",
    )


def _require_voice_id(data: Mapping[str, Any]) -> str:
    output = data.get("output") or {}
    value = str(output.get("voice_id") or output.get("voice") or "")
    if not value:
        raise ModelError(f"voice creation returned no voice id: {output}")
    return value


def _management_payload(action: str, voice_id: str, target_model: str) -> dict:
    """Management call for one voice, routed by the model it is bound to.

    Voices live in three disjoint namespaces and each only answers to its own
    management model: cloned qwen-tts voices to ``qwen-voice-enrollment``,
    designed qwen-tts voices to ``qwen-voice-design``, and everything in the
    cosyvoice family to ``voice-enrollment``. Deleting through the wrong one
    returns HTTP 400 and leaks the voice against the account quota.
    """

    reference = (target_model or voice_id).casefold()
    if reference.startswith("cosyvoice") or "qwen-audio" in reference:
        verb = "delete_voice" if action == "delete" else action
        return {
            "model": "voice-enrollment",
            "input": {"action": verb, "voice_id": voice_id},
        }
    designed = "-vd-" in reference or "-vd" in target_model.casefold()
    return {
        "model": "qwen-voice-design" if designed else "qwen-voice-enrollment",
        "input": {"action": action, "voice": voice_id},
    }


async def delete_voice(voice_id: str, *, target_model: str = "") -> bool:
    """Best-effort deletion of a created voice; returns success.

    ``target_model`` is the model the voice is bound to (recorded on the
    character binding); it decides which management surface owns the voice.
    """

    try:
        await _post_json(
            _endpoint(
                config.get_tts_base_url(),
                "services/audio/tts/customization",
            ),
            api_key=_require_key(),
            payload=_management_payload("delete", voice_id, target_model),
            timeout_seconds=config.get_tts_timeout_seconds(),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - unbind must not fail the caller
        logger.warning("voice deletion failed for %s: %s", voice_id, exc)
        return False


__all__ = [
    "TTS_MAX_TEXT_CHARS",
    "VOICE_PREVIEW_MIN_CHARS",
    "TTSSynthesis",
    "VoiceEnrollment",
    "delete_voice",
    "design_voice",
    "enroll_voice",
    "synthesize",
]
