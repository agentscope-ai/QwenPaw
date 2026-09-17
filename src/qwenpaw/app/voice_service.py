"""Voice management projection and request-owned temporary audio."""

import copy
import asyncio
import hashlib
import re
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request, UploadFile
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..agents.utils import audio_transcription as audio
from ..access.dependencies import get_actor
from .agent_context import get_agent_for_request, get_agent_access_state

MAX_AUDIO_BYTES = 25 * 1024 * 1024
_uploads = threading.BoundedSemaphore(4)
_settings_lock = asyncio.Lock()
EXTENSIONS = frozenset({".webm", ".mp4", ".m4a", ".wav", ".mp3", ".ogg", ".flac"})


def upload_limit():
    from ..constant import UPLOAD_MAX_SIZE_MB

    return (
        min(MAX_AUDIO_BYTES, int(UPLOAD_MAX_SIZE_MB * 1024 * 1024))
        if UPLOAD_MAX_SIZE_MB
        else MAX_AUDIO_BYTES
    )


class VoiceUploadRoute(APIRoute):
    """Bound multipart bytes before FastAPI spools the uploaded file."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            if (
                self.path.endswith(("/transcribe", "/transcription-test"))
                and request.method == "POST"
            ):
                from starlette.formparsers import MultiPartException

                limit = upload_limit() + 64 * 1024  # bounded multipart metadata
                receive = request._receive
                total = 0

                async def bounded_receive():
                    nonlocal total
                    message = await receive()
                    total += len(message.get("body", b""))
                    if total > limit:
                        # Starlette closes partial spool files for this exception.
                        raise MultiPartException("Audio exceeds the size limit")
                    return message

                if not _uploads.acquire(blocking=False):
                    raise http_error("TRANSCRIPTION_BUSY")
                try:
                    request._receive = bounded_receive
                    return await handler(request)
                except StarletteHTTPException:
                    if total > limit:
                        raise http_error("FILE_TOO_LARGE") from None
                    raise
                finally:
                    request._receive = receive
                    _uploads.release()
            return await handler(request)

        return guarded


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    audio_mode: Literal["auto", "native"]
    transcription_provider_type: Literal["disabled", "whisper_api", "local_whisper"]
    transcription_provider_id: str
    transcription_model: str
    transcription_local_model: Literal[
        "tiny", "base", "small", "medium", "large-v3", "turbo"
    ]


def http_error(code):
    error = audio.TranscriptionError(code)
    return HTTPException(
        status_code=error.status, detail={"code": code, "message": error.message}
    )


def settings_from_config(config):
    return VoiceSettings(
        **{key: getattr(config.agents, key) for key in VoiceSettings.model_fields}
    )


async def management_view(config):
    settings = settings_from_config(config)
    providers = audio.list_transcription_providers()
    for provider in providers:
        try:
            from ..models.runtime import require_transcription_service

            await require_transcription_service(provider["id"], None)
        except Exception:
            provider["available"] = False
    return {
        "settings": settings.model_dump(),
        "providers": providers,
        "local_status": audio.check_local_whisper_available(
            settings.transcription_local_model
        ),
        "local_models": list(audio.LOCAL_MODELS),
    }


async def save_settings(body, *, load, save, partial=False):
    async with _settings_lock:
        original = load()
        fields = settings_from_config(original).model_dump() if partial else {}
        fields.update(body)
        try:
            settings = VoiceSettings.model_validate(fields)
            # Model and provider identifiers cannot smuggle a URL or local path.
            if (
                not re.fullmatch(r"[\w./:-]{1,160}", settings.transcription_model)
                or "://" in settings.transcription_model
            ):
                raise ValueError
            if settings.transcription_provider_id and not re.fullmatch(
                r"[\w.-]{1,128}", settings.transcription_provider_id
            ):
                raise ValueError
            if (
                settings.transcription_provider_type == "whisper_api"
                and settings.transcription_provider_id
            ):
                manager = audio._get_manager()
                provider = (
                    manager.get_provider(settings.transcription_provider_id)
                    if manager
                    else None
                )
                if provider is None or audio._url_for_provider(provider) is None:
                    raise ValueError
                from ..models.runtime import require_transcription_service

                await require_transcription_service(
                    settings.transcription_provider_id, settings.transcription_model
                )
            elif settings.transcription_provider_type == "whisper_api":
                raise ValueError
        except (ValidationError, ValueError):
            raise http_error("INVALID_VOICE_SETTINGS") from None
        except Exception:
            raise http_error("TRANSCRIPTION_NOT_READY") from None
        candidate = copy.deepcopy(original)
        for key, value in settings.model_dump().items():
            setattr(candidate.agents, key, value)
        # Build a safe response before saving; failed projection must not partially apply.
        response = await management_view(candidate)
        try:
            # Re-read after all awaits; commit only voice fields without yielding.
            candidate = copy.deepcopy(load())
            for key, value in settings.model_dump().items():
                setattr(candidate.agents, key, value)
            save(candidate)
        except Exception:
            raise http_error("TRANSCRIPTION_NOT_READY") from None
        return response


async def runtime_scope(request, conversation_id=None):
    path_agent = request.path_params.get("agentId")
    if path_agent:
        request.state.agent_id = path_agent
    workspace = await get_agent_for_request(request)
    _, historical = get_agent_access_state(request)
    if historical:
        raise HTTPException(status_code=403, detail="forbidden")
    if conversation_id:
        from .routers.console import _require_console_conversation_write

        await _require_console_conversation_write(request, workspace, conversation_id)
    return workspace


async def transcription_status(request):
    await runtime_scope(request)
    try:
        snapshot = audio.capture_snapshot()
        await audio.require_registered_service(snapshot)
        return {"enabled": True, "available": True, "reason": None}
    except audio.TranscriptionError as exc:
        return {
            "enabled": exc.code != "TRANSCRIPTION_DISABLED",
            "available": False,
            "reason": exc.code,
        }
    except Exception:
        return {
            "enabled": True,
            "available": False,
            "reason": "TRANSCRIPTION_NOT_READY",
        }


def audio_temp_root():
    from ..constant import WORKING_DIR

    return Path(WORKING_DIR).resolve() / "tmp" / "voice-transcription"


async def transcribe_upload(request: Request, file: UploadFile, *, admin_test=False):
    form = await request.form()
    allowed = {"file"} if admin_test else {"file", "conversation_id"}
    keys = [key for key, _ in form.multi_items()]
    if set(keys) - allowed or len(keys) != len(set(keys)):
        raise http_error("INVALID_TRANSCRIPTION_REQUEST")
    conversation_id = form.get("conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        raise http_error("INVALID_TRANSCRIPTION_REQUEST")
    workspace = None if admin_test else await runtime_scope(request, conversation_id)
    try:
        snapshot = audio.capture_snapshot()
        await audio.require_registered_service(snapshot)
    except audio.TranscriptionError as exc:
        raise http_error(exc.code) from None
    except Exception:
        raise http_error("TRANSCRIPTION_NOT_READY") from None
    suffix = Path(file.filename or "audio.webm").suffix.lower()
    if suffix not in EXTENSIONS:
        raise http_error("UNSUPPORTED_FILE_TYPE")
    try:
        actor = get_actor(request)
        owner = hashlib.sha256(str(actor.user_id or "legacy").encode()).hexdigest()[:24]
        agent = hashlib.sha256(
            str(workspace.agent_id if workspace else "admin-test").encode()
        ).hexdigest()[:24]
        root = audio_temp_root().resolve()
        directory = root / owner / agent
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root):
            raise http_error("TRANSCRIPTION_NOT_READY")
        limit = upload_limit()
        # TemporaryDirectory owns only this random request; original attachments are never passed here.
        with tempfile.TemporaryDirectory(prefix="request-", dir=directory) as owned:
            target = Path(owned) / ("audio" + suffix)
            size = 0
            with target.open("wb") as stream:
                while chunk := await file.read(64 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise http_error("FILE_TOO_LARGE")
                    stream.write(chunk)
            if not size:
                raise http_error("EMPTY_AUDIO")
            return {"text": await audio.transcribe_snapshot(str(target), snapshot)}
    except audio.TranscriptionError as exc:
        raise http_error(exc.code) from None
    except HTTPException:
        raise
    except Exception:
        raise http_error("UPSTREAM_FAILED") from None
    finally:
        await file.close()
